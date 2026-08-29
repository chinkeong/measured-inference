#!/usr/bin/env python3
"""Measure THIS box, once, and write results/<slug>/machine.json.

    python scripts/detect-machine.py --slug somenew-32b
    python scripts/detect-machine.py --json            # print, write nothing

WHY THIS FILE EXISTS. Four scripts in this repository open with

    BOARD, RESERVE = 24576, 1796

and every fit check, every ceiling and every "clears the desktop reserve"
verdict downstream is arithmetic on those two literals. Both are measurements
of ONE RTX 3090 on ONE day under ONE desktop load. Rule 14 is explicit that the
reserve is a measured anti-spill budget rather than a constant, and rule 3 says
a number without its conditions is unfalsifiable. Carried onto a 12 GB card the
pair does not fail loudly: `slack = BOARD - used` stays comfortably positive,
the deep-fill probe stamps PASS on a window that is quietly spilling to host
RAM, and a wrong number gets published wearing a conditions block that makes it
look measured.

So this script measures them here, on the machine that is about to do the work,
and writes them down with their provenance. Nothing below is defaulted from the
reference rig.

WHAT IT PROMISES.

  * Every field is MEASURED, DERIVED from something measured, CITED from the
    operator, or null. There is no fifth category and nothing is guessed
    (rule 1). A field it cannot measure is written as null WITH a "why" string
    in `provenance`, never dropped -- a missing key reads as "not applicable"
    to whoever finds the artefact later, which is how numbers come to look
    comparable when they are not.
  * It works with no nvidia-smi, no GPU, and no llama.cpp build: a CPU box gets
    board_total_mib 0 and says so.
  * It takes NO GPU job. nvidia-smi queries are read-only, so this does not
    acquire the rule-20 lock -- it would block a real run for five seconds and
    would refuse to run at all under MEASURED_INFERENCE_DRY_RUN. It does check
    that the card is idle, because a desktop reserve measured with a model
    resident is not a desktop reserve.
  * The one write it performs anywhere is `nvidia-smi -pl <the value already in
    force>`, to answer whether the power limit is writable without elevation.
    Setting a value to itself changes nothing, and the reading afterwards is
    recorded so the artefact can prove it.

THE FIELD THAT NEEDS A HUMAN. desktop_reserve_mib is the VRAM the graphical
session itself holds, and it depends on what the desktop is DOING. The
reference rig measured 1,181 MiB idle and 1,669 MiB with a real workload on
screen, and shipped the worst case plus its load-to-load variation. A five
second sample of an idle desktop cannot see that spread, so the artefact
records the sample window, the sample count and the desktop state you named
with --desktop-state. Re-run it with the desktop loaded before trusting `max`
as a fence.

Stdlib only, Python 3.10+, Linux/macOS/Windows.
"""
import argparse
import ctypes
import datetime
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "lib"))
import paths                                                   # noqa: E402

# gpu_lock is imported as a sibling of bench.py's own imports (bench.py:50).
# It is used ONLY to read state -- live_servers() and holder() -- so that the
# desktop reserve is never sampled while a model is resident. Nothing here
# acquires the lock or spawns anything.
sys.path.insert(0, os.path.join(_HERE, "bench"))
try:
    import gpu_lock                                            # noqa: E402
except Exception:                                              # pragma: no cover
    gpu_lock = None

# subprocess text-mode kwargs. On Windows a bare text=True decodes child output
# as cp1252, and one UTF-8 byte from a child then kills the reader mid-read.
# Copied from bench.py's _TEXT for exactly that reason.
_TEXT = dict(text=True, encoding="utf-8", errors="replace")

BACKENDS = ("cuda", "vulkan", "rocm", "metal", "cpu")
SCHEMA = "measured-inference/machine.json v1"
SLUG_ENV = getattr(paths, "SLUG_ENV", "MEASURED_INFERENCE_SLUG")

# The order machine.json is written in: the fields a reader wants first.
FIELD_ORDER = (
    "board_total_mib", "gpu_name", "backend", "driver", "host_ram_gb",
    "ram_channels", "os", "arch", "power_default_limit_w",
    "pl_writable_without_elevation", "desktop_reserve_mib",
)


# ---------------------------------------------------------------------------
# the record
# ---------------------------------------------------------------------------

class Profile(object):
    """Values plus a provenance entry for every one of them.

    A value is only ever set through one of these four, so a field cannot
    acquire a number without acquiring a label for where the number came from
    (rule 1: measured, cited, or labeled-derived -- there is no fourth
    category, and this class is where that is enforced rather than remembered).
    """

    def __init__(self):
        self.values = {}
        self.prov = {}

    def measured(self, key, value, how, **extra):
        self.values[key] = value
        self.prov[key] = dict({"how": "MEASURED: " + how}, **extra)

    def derived(self, key, value, how, **extra):
        self.values[key] = value
        self.prov[key] = dict({"how": "DERIVED: " + how}, **extra)

    def cited(self, key, value, how, **extra):
        self.values[key] = value
        self.prov[key] = dict({"how": "CITED: " + how}, **extra)

    def unknown(self, key, why, **extra):
        self.values[key] = None
        self.prov[key] = dict({"how": "UNKNOWN", "why": why}, **extra)

    def note(self, key, **extra):
        """Add evidence to an entry that already exists."""
        if key in self.prov:
            self.prov[key].update(extra)


def resolve_slug(explicit=None):
    """Which results/<slug>/ this profile belongs to, or None.

    Deliberately local rather than borrowed from paths.py: that module's slug
    helper is private, this script is the thing that runs BEFORE a campaign has
    a campaign.json, and machine.json needs neither.
    """
    slug = explicit or os.environ.get(SLUG_ENV)
    if slug:
        slug = slug.strip()
        if not slug or slug in (".", "..") or "/" in slug or "\\" in slug:
            raise SystemExit(
                "bad slug %r: a slug is a single path component, no slashes "
                "(AGENTS.md LAYOUT)." % slug)
        return slug
    root = os.path.join(paths.repo_root(), "results")
    found = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return None
    for name in names:
        d = os.path.join(root, name)
        if not os.path.isdir(d) or name.upper().startswith("TEMPLATE"):
            continue
        if (os.path.isfile(os.path.join(d, "campaign.json"))
                or os.path.isfile(os.path.join(d, "campaign.md"))):
            found.append(name)
    return found[0] if len(found) == 1 else None


def _run(args, timeout=20):
    """(returncode, combined output). (None, reason) when it will not run."""
    try:
        p = subprocess.run(args, capture_output=True, timeout=timeout, **_TEXT)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, "%s: %s" % (type(exc).__name__, exc)
    return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()


def _float(text):
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return None


def _int(text):
    v = _float(text)
    return None if v is None else int(round(v))


# ---------------------------------------------------------------------------
# NVIDIA
# ---------------------------------------------------------------------------

NVIDIA_FIELDS = ("name", "memory.total", "memory.used", "driver_version",
                 "power.default_limit", "power.limit")


def nvidia_query(fields, index=None, timeout=20):
    """One CSV row per GPU, as a list of lists of stripped strings."""
    if not shutil.which("nvidia-smi"):
        return None
    cmd = ["nvidia-smi", "--query-gpu=" + ",".join(fields),
           "--format=csv,noheader,nounits"]
    if index is not None:
        cmd += ["-i", str(index)]
    rc, out = _run(cmd, timeout=timeout)
    if rc != 0 or not out:
        return None
    rows = []
    for line in out.splitlines():
        if not line.strip():
            continue
        # "[N/A]" and "[Not Supported]" are nvidia-smi's own absences; they
        # become None here rather than the string, so a field that is not
        # supported cannot be mistaken for a measurement.
        cells = []
        for cell in line.split(","):
            cell = cell.strip()
            cells.append(None if cell.startswith("[") else cell)
        rows.append(cells)
    return rows or None


def nvidia_count():
    rows = nvidia_query(("name",))
    return len(rows) if rows else 0


# ---------------------------------------------------------------------------
# AMD / ROCm
# ---------------------------------------------------------------------------

def rocm_json(args):
    """rocm-smi --json as a dict, or None. Output shape drifts between ROCm
    releases, so callers search it by key text rather than by exact path."""
    if not shutil.which("rocm-smi"):
        return None
    rc, out = _run(["rocm-smi"] + list(args) + ["--json"], timeout=30)
    if rc != 0 or not out:
        return None
    start = out.find("{")
    if start < 0:
        return None
    try:
        data = json.loads(out[start:])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _rocm_find(data, *needles):
    """First value whose key contains all `needles` (case-insensitive)."""
    if not isinstance(data, dict):
        return None, None
    for card in sorted(data):
        block = data[card]
        if not isinstance(block, dict):
            continue
        for key in block:
            low = key.lower()
            if all(n.lower() in low for n in needles):
                return block[key], "%s -> %s" % (card, key)
    return None, None


# ---------------------------------------------------------------------------
# SMBIOS / DMI -- populated DIMMs, and the channels they sit on
# ---------------------------------------------------------------------------

def smbios_table():
    """(raw SMBIOS structure table, how) or (None, why it is unavailable)."""
    if sys.platform == "darwin":
        return None, ("macOS does not expose the SMBIOS table; "
                      "`system_profiler SPMemoryDataType` reports the modules "
                      "but not their channels")
    if os.name == "nt":
        try:
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.GetSystemFirmwareTable.restype = ctypes.c_uint32
            rsmb = 0x52534D42                      # 'RSMB', little-endian
            size = k32.GetSystemFirmwareTable(rsmb, 0, None, 0)
            if not size:
                return None, ("GetSystemFirmwareTable('RSMB') returned no "
                              "data (error %d)" % ctypes.get_last_error())
            buf = ctypes.create_string_buffer(size)
            got = k32.GetSystemFirmwareTable(rsmb, 0, buf, size)
            if not got:
                return None, ("GetSystemFirmwareTable('RSMB') failed (error "
                              "%d)" % ctypes.get_last_error())
            # RawSMBIOSData: 4 bytes of version info + a 4-byte length, then
            # the structure table itself.
            return buf.raw[8:got], "GetSystemFirmwareTable('RSMB')"
        except Exception as exc:                   # pragma: no cover
            return None, "%s: %s" % (type(exc).__name__, exc)
    path = "/sys/firmware/dmi/tables/DMI"
    try:
        with open(path, "rb") as fh:
            return fh.read(), path
    except OSError as exc:
        return None, ("%s: %s -- it is root-readable only, so run this as "
                      "root, or read the modules with `sudo dmidecode -t 17` "
                      "and pass --ram-channels N" % (path, exc.strerror or exc))


def smbios_memory_devices(raw):
    """Populated SMBIOS type-17 Memory Devices: size, speed, locators."""
    out, i, n = [], 0, len(raw)
    while i + 4 <= n:
        typ, length = raw[i], raw[i + 1]
        if length < 4:
            break
        body = raw[i:i + length]
        j = i + length
        strings = []
        if raw[j:j + 2] == b"\x00\x00":
            j += 2
        else:
            while j < n:
                end = raw.find(b"\x00", j)
                if end < 0:
                    j = n
                    break
                strings.append(raw[j:end].decode("latin-1", "replace").strip())
                if raw[end + 1:end + 2] == b"\x00":
                    j = end + 2
                    break
                j = end + 1
        if typ == 127:                              # end-of-table
            break
        if typ == 17 and length >= 0x15:
            def _s(offset):
                idx = body[offset] if offset < length else 0
                return strings[idx - 1] if 0 < idx <= len(strings) else ""
            size = int.from_bytes(body[0x0C:0x0E], "little")
            if size not in (0, 0xFFFF):             # 0 = empty slot
                if size == 0x7FFF and length >= 0x20:
                    mib = int.from_bytes(body[0x1C:0x20], "little")
                elif size & 0x8000:                 # bit 15 set: value is kB
                    mib = (size & 0x7FFF) // 1024
                else:
                    mib = size & 0x7FFF
                out.append({
                    "size_mib": mib,
                    "speed_mts": (int.from_bytes(body[0x15:0x17], "little")
                                  if length >= 0x17 else None) or None,
                    "locator": _s(0x10),
                    "bank_locator": _s(0x11),
                })
        i = j
    return out


_CONTROLLER_RE = re.compile(r"controller\s*[_-]?\s*(\w+)", re.I)
_CHANNEL_RE = re.compile(r"channel\s*[_-]?\s*(\w+)", re.I)


def channels_from_devices(devices):
    """(channel count, the distinct keys) from DIMM locator strings, or None.

    Boards label a slot "Controller0-ChannelA-DIMM0" or "ChannelB-DIMM1"; the
    number of DISTINCT (controller, channel) pairs among POPULATED slots is the
    number of channels actually in use, which is the thing rule 3 wants beside
    a memory-bandwidth number. Boards that label slots "DIMM_A1" carry no
    channel token at all -- that returns None, and null is the honest answer.
    """
    keys = []
    for dev in devices:
        text = "%s %s" % (dev.get("locator") or "", dev.get("bank_locator") or "")
        chan = _CHANNEL_RE.search(text)
        if not chan:
            continue
        ctrl = _CONTROLLER_RE.search(text)
        key = "%s/%s" % ((ctrl.group(1).lower() if ctrl else "-"),
                         chan.group(1).lower())
        if key not in keys:
            keys.append(key)
    return (len(keys), keys) if keys else (None, [])


# ---------------------------------------------------------------------------
# host RAM
# ---------------------------------------------------------------------------

def host_ram_bytes():
    """(bytes, how) -- reusing gpu_lock's reader so both agree on the number."""
    if gpu_lock is not None:
        try:
            status = gpu_lock._memory_status()
        except Exception:                          # pragma: no cover
            status = None
        if status:
            return status[0], ("gpu_lock._memory_status() "
                               "(GlobalMemoryStatusEx on Windows, "
                               "/proc/meminfo on Linux)")
    if sys.platform == "darwin":
        rc, out = _run(["sysctl", "-n", "hw.memsize"])
        if rc == 0:
            val = _int(out)
            if val:
                return val, "sysctl -n hw.memsize"
    return None, None


# ---------------------------------------------------------------------------
# elevation, and the power-limit write test
# ---------------------------------------------------------------------------

def elevated():
    """True/False, or None when the question cannot be answered here."""
    if os.name == "nt":
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:                          # pragma: no cover
            return None
    try:
        return os.geteuid() == 0
    except AttributeError:                         # pragma: no cover
        return None


def pl_write_test(index, current_w):
    """Is the power limit writable WITHOUT elevation? (value, why, evidence)

    Non-destructive by construction: it sets the limit to the value already in
    force, so a success changes nothing and a failure changes nothing. The
    limit is read back afterwards and recorded, so the artefact can show that.
    """
    if current_w is None:
        return None, ("no readable power.limit on this card, so there is "
                      "nothing to test"), {}
    is_root = elevated()
    if is_root:
        return None, ("this process is running elevated "
                      "(root/Administrator), and a successful set under "
                      "elevation says nothing about the unelevated case. "
                      "Re-run without elevation to answer it."), {}
    cmd = ["nvidia-smi", "-i", str(index), "-pl", "%g" % current_w]
    rc, out = _run(cmd, timeout=30)
    after = nvidia_query(("power.limit",), index=index)
    after_w = _float(after[0][0]) if after and after[0] else None
    evidence = {"command": " ".join(cmd),
                "set_to_the_value_already_in_force_w": current_w,
                "power_limit_after_w": after_w,
                "elevated": bool(is_root) if is_root is not None else None,
                "nvidia_smi_said": (out or "").splitlines()[:2]}
    low = (out or "").lower()
    first = (out or "").splitlines()[0] if out else ""
    if rc is None:
        return None, "could not run nvidia-smi -pl: %s" % out, evidence
    if "not supported" in low or "unsupported" in low:
        return None, ("this card does not support setting a power limit: %s"
                      % (first or "nvidia-smi said unsupported")), evidence
    if rc == 0 and "insufficient" not in low and "permission" not in low:
        return True, None, evidence
    if "insufficient" in low or "permission" in low or "privile" in low:
        return False, None, evidence
    return None, ("nvidia-smi -pl returned %d and a message this script does "
                  "not classify: %s" % (rc, first)), evidence


# ---------------------------------------------------------------------------
# the desktop reserve (rule 14)
# ---------------------------------------------------------------------------

def gpu_busy_reason():
    """Why a VRAM reading right now would NOT be a desktop reserve, or None."""
    if gpu_lock is None:
        return None
    try:
        live = gpu_lock.live_servers()
    except Exception:                              # pragma: no cover
        live = []
    if live:
        return ("a llama.cpp process is live (%s) -- its weights are in the "
                "reading, so this would measure the model, not the desktop. "
                "Stop it (python scripts/bench/gpu_lock.py kill) and re-run."
                % ", ".join("%s(%d)" % (n, p) for p, n in live))
    try:
        held = gpu_lock.holder()
    except Exception:                              # pragma: no cover
        held = None
    if held:
        return ("the rule-20 GPU lock is held by pid %s (tag %r) -- something "
                "is using the card, so a VRAM reading is not the desktop's."
                % (held.get("pid"), held.get("tag")))
    return None


def sample_used_mib(index, n, interval, log=None):
    """n readings of board VRAM in use, spaced `interval` seconds apart."""
    samples = []
    for k in range(n):
        if k:
            time.sleep(interval)
        rows = nvidia_query(("memory.used",), index=index)
        if not rows or not rows[0] or rows[0][0] is None:
            continue
        val = _int(rows[0][0])
        if val is not None:
            samples.append(val)
            if log:
                log("  sample %d/%d: %d MiB" % (k + 1, n, val))
    return samples


# ---------------------------------------------------------------------------
# assembling the profile
# ---------------------------------------------------------------------------

def detect(args, log):
    p = Profile()
    today = datetime.date.today().isoformat()

    # ---- os / arch: always available -------------------------------------
    p.measured("os", platform.platform(), "platform.platform()",
               system=platform.system(), release=platform.release())
    p.measured("arch", platform.machine(), "platform.machine()",
               processor=platform.processor() or None)

    # ---- host RAM ---------------------------------------------------------
    ram_bytes, ram_how = host_ram_bytes()
    if ram_bytes:
        p.measured("host_ram_gb", round(ram_bytes / float(1 << 30), 1), ram_how,
                   bytes=ram_bytes,
                   note="total physical RAM as the OS reports it -- the same "
                        "number gpu_lock sizes its per-job commit cap from")
    else:
        p.unknown("host_ram_gb",
                  "no memory reader for this platform (tried "
                  "gpu_lock._memory_status() and sysctl hw.memsize)")

    # ---- RAM channels -----------------------------------------------------
    if args.ram_channels is not None:
        p.cited("ram_channels", args.ram_channels,
                "--ram-channels %d, stated by the operator" % args.ram_channels)
    else:
        raw, how = smbios_table()
        if raw is None:
            p.unknown("ram_channels",
                      "SMBIOS unreadable (%s). Unknown is an acceptable value "
                      "here -- record it rather than guessing -- but if you "
                      "know the figure, pass --ram-channels N so rule 3 can "
                      "carry it beside every bandwidth number." % how)
        else:
            devices = smbios_memory_devices(raw)
            count, keys = channels_from_devices(devices)
            evidence = {"source": how,
                        "populated_dimms": len(devices),
                        "modules": devices}
            if count:
                p.derived("ram_channels", count,
                          "%d distinct (controller, channel) pairs among %d "
                          "populated DIMMs, from their SMBIOS type-17 locator "
                          "strings" % (count, len(devices)),
                          channel_keys=keys, **evidence)
            else:
                p.unknown("ram_channels",
                          "the SMBIOS type-17 locators on this board carry no "
                          "channel token (%s), so the channel count cannot be "
                          "derived from them. Pass --ram-channels N if you "
                          "know it."
                          % (", ".join(d.get("locator") or "?"
                                       for d in devices) or "no populated DIMMs"),
                          **evidence)

    # ---- the card ---------------------------------------------------------
    nv = nvidia_query(NVIDIA_FIELDS, index=args.gpu)
    gpu_count = nvidia_count()
    row = nv[0] if nv else None
    have_nvidia = row is not None

    if have_nvidia:
        name, total, _used, driver, default_pl, cur_pl = (row + [None] * 6)[:6]
        p.measured("gpu_name", name, "nvidia-smi --query-gpu=name (GPU %d of "
                                     "%d)" % (args.gpu, gpu_count or 1))
        total_mib = _int(total)
        if total_mib:
            p.measured("board_total_mib", total_mib,
                       "nvidia-smi --query-gpu=memory.total (MiB)")
        else:
            p.unknown("board_total_mib",
                      "nvidia-smi did not report memory.total for GPU %d"
                      % args.gpu)
        if driver:
            p.measured("driver", driver,
                       "nvidia-smi --query-gpu=driver_version")
        else:
            p.unknown("driver", "nvidia-smi did not report driver_version")
        dpl = _float(default_pl)
        if dpl is not None:
            p.measured("power_default_limit_w", dpl,
                       "nvidia-smi --query-gpu=power.default_limit (W)",
                       power_limit_now_w=_float(cur_pl))
        else:
            p.unknown("power_default_limit_w",
                      "nvidia-smi reports no power.default_limit for this "
                      "card (it is [N/A] on cards without a settable limit)")
        if gpu_count > 1:
            p.note("gpu_name", warning=(
                "%d GPUs on this box; this profile describes GPU %d only. "
                "Rule 3: say which card produced a number, and re-run with "
                "--gpu N for the others." % (gpu_count, args.gpu)))
    else:
        have_rocm = bool(shutil.which("rocm-smi"))
        rocm_mem = rocm_json(["--showmeminfo", "vram"])
        vram_total, where = _rocm_find(rocm_mem or {}, "vram", "total", "memory")
        vram_bytes = _int(vram_total)
        if vram_bytes:
            p.measured("board_total_mib", vram_bytes // (1 << 20),
                       "rocm-smi --showmeminfo vram --json (%s, bytes)" % where)
            name, nwhere = _rocm_find(rocm_json(["--showproductname"]) or {},
                                      "card series")
            if not name:
                name, nwhere = _rocm_find(rocm_json(["--showproductname"]) or {},
                                          "device name")
            if name:
                p.measured("gpu_name", str(name).strip(),
                           "rocm-smi --showproductname --json (%s)" % nwhere)
            else:
                p.unknown("gpu_name", "rocm-smi reported no product name")
            drv, dwhere = _rocm_find(rocm_json(["--showdriverversion"]) or {},
                                     "driver version")
            if drv:
                p.measured("driver", str(drv).strip(),
                           "rocm-smi --showdriverversion --json (%s)" % dwhere)
            else:
                p.unknown("driver", "rocm-smi reported no driver version")
            mx, mwhere = _rocm_find(rocm_json(["--showmaxpower"]) or {}, "power")
            if _float(mx) is not None:
                p.measured("power_default_limit_w", _float(mx),
                           "rocm-smi --showmaxpower --json (%s)" % mwhere)
            else:
                p.unknown("power_default_limit_w",
                          "rocm-smi reported no max power cap")
        elif sys.platform == "darwin":
            _detect_metal(p, args)
        elif have_rocm:
            # rocm-smi is installed and did NOT answer. That is a broken ROCm
            # stack, not a CPU box, and calling it 0 MiB would be a guess
            # dressed as a measurement.
            p.unknown("gpu_name", "rocm-smi is installed but reported no "
                                  "product name")
            p.unknown("board_total_mib",
                      "rocm-smi is on PATH but `rocm-smi --showmeminfo vram "
                      "--json` reported no VRAM total. Check the ROCm stack "
                      "(rocm-smi alone should list the card), then re-run, or "
                      "pass --board-total-mib N.")
            p.unknown("driver", "rocm-smi reported no driver version")
            p.unknown("power_default_limit_w",
                      "rocm-smi reported no max power cap")
        else:
            p.unknown("gpu_name",
                      "no nvidia-smi and no rocm-smi on PATH; if this box has "
                      "a GPU, its vendor tool is not installed")
            p.derived("board_total_mib", 0,
                      "no GPU vendor tool answered, so this is a CPU box and "
                      "there is no board memory. If that is wrong, install the "
                      "vendor tool and re-run -- 0 makes every fit check "
                      "refuse rather than pass.")
            p.unknown("driver", "no GPU vendor tool to ask")
            p.unknown("power_default_limit_w",
                      "no GPU vendor tool to ask; a CPU run has no board "
                      "power limit")

    # ---- backend ----------------------------------------------------------
    _detect_backend(p, args, have_nvidia)

    # ---- power limit writability -----------------------------------------
    if not have_nvidia:
        p.unknown("pl_writable_without_elevation",
                  "the writability test is nvidia-smi -pl; no nvidia-smi here")
    elif args.no_pl_test:
        p.unknown("pl_writable_without_elevation",
                  "skipped by --no-pl-test")
    else:
        cur = _float(row[5]) if len(row) > 5 else None
        log("power limit: testing writability (setting %s W, the value "
            "already in force -- a no-op)"
            % ("%g" % cur if cur is not None else "?"))
        value, why, evidence = pl_write_test(args.gpu, cur)
        if value is None:
            p.unknown("pl_writable_without_elevation", why, **evidence)
        else:
            p.measured("pl_writable_without_elevation", value,
                       "nvidia-smi -pl set to the value already in force; "
                       "non-destructive, and the limit was read back "
                       "afterwards to prove it", **evidence)

    # ---- the desktop reserve (rule 14) ------------------------------------
    _measure_reserve(p, args, have_nvidia, today, log)
    return p


def _detect_metal(p, args):
    """Apple Silicon: unified memory, so 'board total' is a policy, not a chip."""
    rc, out = _run(["system_profiler", "SPDisplaysDataType"], timeout=60)
    name = None
    if rc == 0:
        for line in (out or "").splitlines():
            if "Chipset Model:" in line:
                name = line.split(":", 1)[1].strip()
                break
    if name:
        p.measured("gpu_name", name,
                   "system_profiler SPDisplaysDataType (Chipset Model)")
    else:
        p.unknown("gpu_name", "system_profiler reported no Chipset Model")
    rc, out = _run(["sysctl", "-n", "iogpu.wired_limit_mb"])
    wired = _int(out) if rc == 0 else None
    if wired:
        p.measured("board_total_mib", wired,
                   "sysctl -n iogpu.wired_limit_mb -- the explicit cap on "
                   "GPU-wired unified memory on this machine")
    else:
        p.unknown("board_total_mib",
                  "Apple unified memory: iogpu.wired_limit_mb is 0 (the "
                  "default), so the GPU-addressable ceiling is Metal's "
                  "recommendedMaxWorkingSetSize, which no command line here "
                  "reports. Set it explicitly (sudo sysctl "
                  "iogpu.wired_limit_mb=N) and re-run, or pass "
                  "--board-total-mib N. A fraction of hw.memsize would be a "
                  "guess, and rule 1 has no category for those.")
    rc, out = _run(["sw_vers", "-productVersion"])
    if rc == 0 and out:
        p.measured("driver", out.strip(),
                   "sw_vers -productVersion -- Metal ships with the OS, so "
                   "the OS version IS the driver version")
    else:
        p.unknown("driver", "sw_vers did not answer")
    p.unknown("power_default_limit_w",
              "Apple Silicon exposes no settable board power limit")


def _detect_backend(p, args, have_nvidia):
    """Which llama.cpp backend this box will actually decode with.

    The backend is a property of the BUILD, not of the card, and that is the
    Linux trap this repository is walking into: scripts/setup.sh installs the
    VULKAN build on Linux even when nvidia-smi is present, because there are no
    official Linux CUDA binaries. Deriving "cuda" from the card would be wrong
    on exactly the machine this port is aimed at, so when the installed build
    can be identified it wins, and when it cannot the field says so.
    """
    if args.backend:
        p.cited("backend", args.backend,
                "--backend %s, stated by the operator" % args.backend)
        return

    # What setup.sh / setup.ps1 recorded about the build it installed.
    running = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    install = os.path.join(paths.repo_root(), "bin", "llama.cpp", "INSTALL.json")
    meta, foreign = {}, None
    if os.path.isfile(install):
        try:
            with open(install, "r", encoding="utf-8-sig") as fh:
                meta = json.load(fh) or {}
        except (OSError, ValueError):
            meta = {}
        built_for = str(meta.get("os") or "").lower()
        flavor = str(meta.get("flavor") or "").lower()
        if built_for and built_for != running:
            # The build in bin/ targets a DIFFERENT OS than the one running.
            # It is not authoritative about what this box will decode with,
            # and llama_bin() will hand it to a launcher that cannot exec it.
            # Recorded, not silently trusted -- this is the exact shape of the
            # Windows-to-Ubuntu move the port is for.
            foreign = ("bin/llama.cpp/INSTALL.json describes a %s build "
                       "(flavor %s, host %r) but this box is %s. That build "
                       "cannot run here, so it says nothing about this "
                       "machine's backend."
                       % (built_for, flavor or "?", meta.get("host"), running))
        elif flavor in BACKENDS:
            p.measured("backend", flavor,
                       "bin/llama.cpp/INSTALL.json, written by the setup "
                       "script that installed this build",
                       install_json=meta)
            return

    def _flag(key):
        if foreign:
            p.note(key, warning=foreign, install_json=meta)

    if sys.platform == "darwin":
        p.derived("backend", "metal",
                  "macOS: Metal is compiled into the official arm64 "
                  "llama.cpp build (scripts/setup.sh, PAT_MACOS_ARM64)")
        _flag("backend")
        return
    if have_nvidia and os.name == "nt":
        p.derived("backend", "cuda",
                  "an NVIDIA card is present and scripts/setup.ps1 installs "
                  "the CUDA build on Windows when nvidia-smi answers")
        _flag("backend")
        return
    if have_nvidia:
        p.unknown("backend",
                  "an NVIDIA card is present, but on Linux scripts/setup.sh "
                  "installs the VULKAN build -- there are no official Linux "
                  "CUDA binaries, so whether this box decodes through CUDA or "
                  "Vulkan depends on which llama-server you installed or "
                  "built. Run setup.sh (it writes bin/llama.cpp/INSTALL.json, "
                  "which this reads), or pass --backend cuda|vulkan.")
        _flag("backend")
        return
    if shutil.which("rocm-smi"):
        p.derived("backend", "rocm",
                  "rocm-smi answers, so this box has the ROCm stack")
        _flag("backend")
        return
    p.derived("backend", "cpu",
              "no GPU vendor tool answered. A Vulkan-capable integrated GPU "
              "would still be usable through the Vulkan build -- pass "
              "--backend vulkan if that is what you will run.")
    _flag("backend")


def _measure_reserve(p, args, have_nvidia, today, log):
    """VRAM the graphical session itself holds, with no model loaded."""
    key = "desktop_reserve_mib"
    state = args.desktop_state
    common = {"desktop_state": state or None,
              "samples_n": args.samples,
              "interval_s": args.interval,
              "gpu_index": args.gpu}
    if not have_nvidia:
        p.unknown(key,
                  "reading board VRAM in use needs a GPU vendor tool that "
                  "reports it; nvidia-smi is not available here. On a CPU box "
                  "there is no reserve; on any other card, measure it and "
                  "write the four fields by hand.", **common)
        return
    busy = gpu_busy_reason()
    if busy:
        p.unknown(key, busy, **common)
        return
    log("desktop reserve: %d samples, %.1fs apart, GPU %d (no model loaded)"
        % (args.samples, args.interval, args.gpu))
    samples = sample_used_mib(args.gpu, args.samples, args.interval, log=log)
    if not samples:
        p.unknown(key, "nvidia-smi returned no memory.used reading", **common)
        return
    how = ("nvidia-smi --query-gpu=memory.used, %d samples %.1fs apart with no "
           "llama.cpp process live" % (len(samples), args.interval))
    extra = dict(common)
    extra.update(
        samples_mib=samples,
        desktop_state=state or "NOT STATED -- pass --desktop-state",
        window_s=round(args.interval * max(0, len(samples) - 1), 1),
        warning=("min/max span this sample window ONLY. The reserve is what "
                 "the desktop is DOING: the reference rig read 1,181 MiB idle "
                 "and 1,669 MiB under a real workload, and shipped the worst "
                 "case plus its load-to-load variation. Re-run with the "
                 "desktop loaded before trusting max as an anti-spill fence "
                 "(rule 14)."))
    p.measured(key, {"min": min(samples), "max": max(samples),
                     "n": len(samples), "date": today}, how, **extra)


# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------

def build_record(p, slug):
    """machine.json, ordered so a human reads the important part first."""
    rec = {"_schema": SCHEMA,
           "slug": slug,
           "measured_at": datetime.datetime.now().isoformat(timespec="seconds"),
           "host": platform.node()}
    for key in FIELD_ORDER:
        rec[key] = p.values.get(key)
    for key in sorted(p.values):
        if key not in rec:
            rec[key] = p.values[key]
    rec["provenance"] = {k: p.prov[k] for k in FIELD_ORDER if k in p.prov}
    for key in sorted(p.prov):
        rec["provenance"].setdefault(key, p.prov[key])
    # relpath raises across Windows drive letters (a repo on E:, a script run
    # from C:), and a provenance field must never be the thing that kills the
    # measurement it is describing.
    try:
        me = os.path.relpath(os.path.abspath(__file__),
                             paths.repo_root()).replace("\\", "/")
    except ValueError:
        me = os.path.abspath(__file__).replace("\\", "/")
    rec["tool_versions"] = {
        "python": platform.python_version(),
        "detect_machine": me,
        "nvidia-smi": shutil.which("nvidia-smi"),
        "rocm-smi": shutil.which("rocm-smi"),
    }
    return rec


def write_record(rec, slug, log):
    """Write results/<slug>/machine.json, keeping any profile already there."""
    out_dir = os.path.join(paths.repo_root(), "results", slug)
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
        log("created %s" % out_dir)
    path = os.path.join(out_dir, "machine.json")
    if os.path.exists(path):
        # Never overwrite a measurement silently: an earlier profile may hold a
        # desktop reserve measured under a heavier desktop than today's, and
        # rule 28 says a record that existed cannot be recovered once gone.
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        kept = os.path.join(out_dir, "machine-%s.json" % stamp)
        shutil.copy2(path, kept)
        log("kept the previous profile as %s" % os.path.basename(kept))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(rec, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)
    return path


def summarize(rec, out):
    for key in FIELD_ORDER:
        val = rec.get(key)
        prov = (rec.get("provenance") or {}).get(key) or {}
        if isinstance(val, dict):
            val = json.dumps(val, sort_keys=True)
        label = prov.get("how", "").split(":")[0] or "-"
        if val is None:
            out.write("  %-30s null    (%s)\n" % (key, prov.get("why", "")[:90]))
        else:
            out.write("  %-30s %-8s %s\n" % (key, label, val))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        epilog="Fields that cannot be measured are written as null with a "
               "'why' string in provenance -- never guessed, never dropped.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slug", help="campaign to write into: "
                                   "results/<slug>/machine.json (default: "
                                   "$MEASURED_INFERENCE_SLUG, else the only "
                                   "campaign under results/)")
    ap.add_argument("--json", action="store_true",
                    help="print the profile to stdout and write nothing")
    ap.add_argument("--gpu", type=int, default=0, metavar="N",
                    help="which GPU to profile on a multi-card box (default 0)")
    ap.add_argument("--samples", type=int, default=8, metavar="N",
                    help="desktop-reserve samples (default 8)")
    ap.add_argument("--interval", type=float, default=1.0, metavar="S",
                    help="seconds between reserve samples (default 1.0)")
    ap.add_argument("--desktop-state", metavar="TEXT",
                    help="what the desktop was doing during the reserve "
                         "measurement, e.g. 'idle, no browser' or '4K video "
                         "playing'. Rule 3: it is a condition of the number.")
    ap.add_argument("--ram-channels", type=int, metavar="N",
                    help="record the memory channel count you know to be "
                         "true, when SMBIOS cannot be read (recorded as CITED)")
    ap.add_argument("--backend", choices=BACKENDS,
                    help="record the llama.cpp backend this box will decode "
                         "with, when the installed build cannot say")
    ap.add_argument("--board-total-mib", type=int, metavar="N",
                    help="record the board memory you know to be true, for "
                         "cards no vendor tool here can read (recorded as CITED)")
    ap.add_argument("--no-pl-test", action="store_true",
                    help="skip the power-limit writability probe (it sets the "
                         "limit to the value already in force)")
    args = ap.parse_args(argv)

    # progress on stderr so `--json | jq` stays clean
    log = (lambda msg: sys.stderr.write(msg + "\n")) if args.json else print

    if args.samples < 1:
        ap.error("--samples must be at least 1")
    if args.interval < 0:
        ap.error("--interval cannot be negative")
    if args.gpu < 0:
        ap.error("--gpu must be 0 or greater")
    if shutil.which("nvidia-smi"):
        count = nvidia_count()
        if count and args.gpu >= count:
            ap.error("--gpu %d, but nvidia-smi lists %d GPU(s) here (0..%d)"
                     % (args.gpu, count, count - 1))

    slug = resolve_slug(args.slug)
    if not slug and not args.json:
        ap.error("no campaign to write into. Pass --slug <slug>, set %s, or "
                 "use --json to print the profile without writing it."
                 % SLUG_ENV)

    profile = detect(args, log)
    if args.board_total_mib is not None:
        profile.cited("board_total_mib", args.board_total_mib,
                      "--board-total-mib %d, stated by the operator"
                      % args.board_total_mib)

    rec = build_record(profile, slug)
    if args.json:
        json.dump(rec, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        sys.stderr.write("\nprofile (nothing written):\n")
        summarize(rec, sys.stderr)
        return 0

    path = write_record(rec, slug, log)
    print("\nwrote %s" % path)
    summarize(rec, sys.stdout)
    missing = [k for k in FIELD_ORDER if rec.get(k) is None]
    if missing:
        print("\n%d field(s) could not be measured here: %s"
              % (len(missing), ", ".join(missing)))
        print("Each carries its reason in provenance. Fix what you can and "
              "re-run; the previous profile is kept beside this one.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
