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

THE FIELD THAT DECIDES WHICH ARITHMETIC IS EVEN RIGHT. `board_total_mib` minus
a desktop reserve is the fit budget on ONE topology: a discrete board with its
own memory, on the far side of a PCIe link, which spills to host RAM when it
overflows. Three other topologies are now first-class targets and the
subtraction is wrong on every one of them:

  unified      DGX Spark's GB10 has 128 GB of LPDDR5X shared coherently by the
               Grace CPU and the Blackwell GPU. There is no board. nvidia-smi
               still answers `memory.total`, and the answer is the WHOLE
               machine's memory -- so `board - reserve` silently prices the
               model against RAM the operating system is already living in,
               and nothing about the failure looks like a failure. Apple
               Silicon is the same shape.
  shared-igpu  An Intel or AMD integrated GPU has no memory either; it maps a
               share of system RAM, and the driver -- not the arithmetic here
               -- decides how large that share may be.
  system       CPU-only. There is no GPU pool at all.

So this script MEASURES which one it is and writes `memory_topology` beside
every number that depends on it, with the evidence it classified on. When the
evidence does not settle it, the field is null with the reason and the
downstream fit refuses rather than guessing -- a wrong PASS costs a day, an
UNPROVEN fit costs one command. The pool the fit must price against travels
with it: `host_mem_total_mib` and a measured `host_reserve_mib` (MemTotal minus
MemAvailable, sampled, exactly as the desktop reserve is sampled on a board),
plus `igpu_share_limit_mib` where a driver publishes one. The arithmetic that
consumes them lives in `scripts/check-request.py:memory_plan()`, so that the
planner and the Stage-0 gate cannot drift apart.

Two more fields hang off the same measurement. `spec_bandwidth_gbs` because
rule 10's decode estimate is bandwidth over file GB and a unified box's
bandwidth is a property of the memory, not of a board (GB10: 273 GB/s, CITED).
`cuda_arch` out of bin/llama.cpp/INSTALL.json because GB10 needs
-DCMAKE_CUDA_ARCHITECTURES=121a-real and `native` does not produce it.

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
import glob
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

# elevated() is defined ONCE, in scripts/bench/provenance.py, and imported
# here across the same edge gpu_lock came over. The full reasoning is written
# out in that file's "THE PRIVILEGE THE RUN HAD" section; the short version is
# that a second copy of a permission predicate drifts on the platform nobody
# ran it on, and this caller is the one that fails in the dangerous direction:
# a wrong answer turns a set that succeeded because the shell was elevated
# into a published pl_writable_without_elevation: true. Guarded like gpu_lock
# because this script has to run on a fresh clone; a failed import is answered
# null, never guessed.
try:
    import provenance as _provenance                           # noqa: E402
except Exception:                                              # pragma: no cover
    _provenance = None

# subprocess text-mode kwargs. On Windows a bare text=True decodes child output
# as cp1252, and one UTF-8 byte from a child then kills the reader mid-read.
# Copied from bench.py's _TEXT for exactly that reason.
_TEXT = dict(text=True, encoding="utf-8", errors="replace")

# The llama.cpp backends this box might decode with. `openvino` and `sycl` are
# here because the alternative is worse than being early: _detect_backend()
# accepts INSTALL.json's `flavor` only when it is in this tuple, so a flavor
# missing from it does not raise -- it falls through to a DERIVED guess from
# the card, which on an Intel box would confidently write "cpu" over a real
# OpenVINO build. A name recorded before a setup script writes it costs
# nothing; a backend silently misrecorded is a condition of every number the
# campaign then publishes (rule 3).
BACKENDS = ("cuda", "vulkan", "rocm", "metal", "cpu", "openvino", "sycl")
SCHEMA = "measured-inference/machine.json v2"
SLUG_ENV = getattr(paths, "SLUG_ENV", "MEASURED_INFERENCE_SLUG")

# The four memory topologies the fit arithmetic branches on. They are not
# vendor names: they are the four different sums.
#
#   discrete     a board with its own memory behind a link. Budget =
#                board_total - desktop_reserve. Overflow spills to host RAM
#                over PCIe: slow, survivable, MEASURABLE -- which is what makes
#                rule 13's second ceiling and collapse point findable at all.
#   unified      one physical pool, CPU and GPU coherent, no board and no link.
#                GB10 / DGX Spark, Apple Silicon, Jetson. Budget is a share of
#                system memory. Overflow does not spill anywhere: it is the OOM
#                killer, or swap.
#   shared-igpu  an integrated GPU mapping a share of system RAM, where the
#                driver caps the share. Same pool as `unified`, but the cap is
#                a second, lower ceiling that has to be read from the driver
#                rather than assumed -- assuming MemTotal over-promises by
#                roughly 2x on both i915/xe and WDDM.
#   system       CPU-only. No GPU pool. Weights are mmapped, so overflow is
#                page-cache thrash rather than a kill -- a different failure
#                again.
TOPOLOGIES = ("discrete", "unified", "shared-igpu", "system")

# NVIDIA parts whose GPU memory IS the host's memory. Matched case-insensitively
# against nvidia-smi's product name. Every entry is a claim about topology that
# changes the downstream sum, so each carries its source rather than being a
# name in a list.
UNIFIED_NVIDIA = (
    ("gb10",
     "NVIDIA GB10 Grace Blackwell Superchip (DGX Spark): 128 GB of LPDDR5X "
     "shared coherently by the Grace CPU and the Blackwell GPU. There is no "
     "discrete board, so nvidia-smi's memory.total is the whole machine's "
     "memory and board-minus-reserve would price the model against RAM the OS "
     "is already using."),
    ("orin", "NVIDIA Jetson Orin: Tegra SoC, one LPDDR5 pool shared by CPU "
             "and iGPU. No discrete board."),
    ("thor", "NVIDIA Jetson Thor: Tegra SoC, one LPDDR5X pool shared by CPU "
             "and iGPU. No discrete board."),
    ("xavier", "NVIDIA Jetson Xavier: Tegra SoC, one LPDDR4x pool shared by "
               "CPU and iGPU. No discrete board."),
    ("tegra", "NVIDIA Tegra SoC: one memory pool shared by CPU and iGPU. No "
              "discrete board."),
)

# Parts this script REFUSES to classify, and why. A Grace-Hopper or
# Grace-Blackwell superchip is neither: the GPU has its own HBM *and*
# cache-coherent access to the Grace LPDDR, so "discrete" under-counts the
# reachable memory and "unified" over-counts the fast memory. Neither sum is
# right, and picking one silently is exactly the failure this field exists to
# stop.
AMBIGUOUS_NVIDIA = (
    ("gh200", "NVIDIA GH200 Grace Hopper Superchip: the GPU has its own HBM3 "
              "AND cache-coherent access to the Grace LPDDR5X. 'discrete' "
              "under-counts what it can reach; 'unified' over-counts what it "
              "can reach FAST. Neither sum is right."),
    ("gb200", "NVIDIA GB200 Grace Blackwell Superchip: HBM3e per GPU plus "
              "cache-coherent Grace LPDDR5X. Same two-pool problem as GH200."),
)

# Memory bandwidth, in GB/s, for parts where the figure is a published
# specification rather than something this box can measure. Rule 10's decode
# estimate is bandwidth over file GB, and on a unified box the bandwidth
# belongs to the memory, not to a board -- so it has to come from somewhere,
# and CITED with a source is the only honest somewhere.
SPEC_BANDWIDTH = (
    ("gb10", 273.0,
     "NVIDIA DGX Spark / GB10 published specification: 128 GB LPDDR5X at "
     "273 GB/s. Recorded here from the 2026-08-29 backend-port research brief "
     "in this repository; re-read NVIDIA's own page before publishing a number "
     "derived from it."),
)

# DDR channels are 64 bits wide however the vendor sub-divides them, so a
# theoretical peak is channels x 8 bytes x MT/s. It is a CEILING, not a
# measurement -- the constant in rule 10 is re-derived against a measured
# figure, never against this one.
DDR_BYTES_PER_CHANNEL = 8

# What CMAKE_CUDA_ARCHITECTURES has to say for a part, when "native" is known
# not to produce it. Only entries this repository has a reason to assert.
CUDA_ARCH_REQUIRED = (
    ("gb10", "121a-real",
     "GB10 is sm_121a. -DCMAKE_CUDA_ARCHITECTURES=native, 120, 120f or a bare "
     "121 all build something that runs and none of them keeps "
     "MMVQ_PARAMETERS_GB10, so the build is slower than the hardware and "
     "nothing says so. Rebuild with --cuda-arch 121a-real."),
)

# The order machine.json is written in: the fields a reader wants first.
FIELD_ORDER = (
    "memory_topology", "board_total_mib", "gpu_name", "backend", "driver",
    "host_ram_gb", "host_mem_total_mib", "host_reserve_mib",
    "igpu_share_limit_mib", "spec_bandwidth_gbs", "cuda_arch", "compute_cap",
    "ram_channels", "ecc_mode", "os", "arch", "power_default_limit_w",
    "pl_writable_without_elevation", "elevated", "sudo_nopasswd",
    "privilege_path", "desktop_reserve_mib",
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
# the HOST pool -- what a unified, shared or CPU-only fit is priced against
# ---------------------------------------------------------------------------

def host_meminfo():
    """(total_mib, available_mib, how) for the pool a process allocates from.

    `available` is deliberately the kernel's own MemAvailable rather than
    MemFree: MemFree on a box that has read a 20 GB GGUF once reads near zero
    while 20 GB of reclaimable page cache is sitting right there, and a budget
    built on it would refuse every model on a healthy machine. MemAvailable is
    the kernel's estimate of what can be allocated WITHOUT swapping, which is
    the question the fit is asking.
    """
    if sys.platform.startswith("linux"):
        try:
            info = {}
            with open("/proc/meminfo", "r") as fh:
                for line in fh:
                    k, _, v = line.partition(":")
                    parts = v.split()
                    if parts and parts[0].isdigit():
                        info[k.strip()] = int(parts[0]) // 1024      # kB -> MiB
        except OSError as exc:
            return None, None, "/proc/meminfo unreadable: %s" % exc
        total = info.get("MemTotal")
        avail = info.get("MemAvailable")
        if avail is None and "MemFree" in info:
            return (total, None,
                    "/proc/meminfo has MemTotal but no MemAvailable (kernel "
                    "older than 3.14); MemFree is not a substitute")
        if total:
            return total, avail, "/proc/meminfo MemTotal / MemAvailable"
        return None, None, "/proc/meminfo carried no MemTotal"
    if os.name == "nt":
        if gpu_lock is None or not hasattr(gpu_lock, "_MEMORYSTATUSEX"):
            return None, None, ("gpu_lock did not import, so its "
                                "GlobalMemoryStatusEx binding is unavailable")
        try:
            st = gpu_lock._MEMORYSTATUSEX()
            st.dwLength = ctypes.sizeof(st)
            if not gpu_lock._k32.GlobalMemoryStatusEx(ctypes.byref(st)):
                return None, None, "GlobalMemoryStatusEx failed"
            return (int(st.ullTotalPhys) // (1 << 20),
                    int(st.ullAvailPhys) // (1 << 20),
                    "GlobalMemoryStatusEx ullTotalPhys / ullAvailPhys")
        except Exception as exc:                       # pragma: no cover
            return None, None, "GlobalMemoryStatusEx: %s" % exc
    if sys.platform == "darwin":
        rc, out = _run(["sysctl", "-n", "hw.memsize"])
        total = (_int(out) or 0) // (1 << 20) if rc == 0 else None
        rc, out = _run(["vm_stat"])
        avail = None
        if rc == 0 and out:
            page = 4096
            m = re.search(r"page size of (\d+) bytes", out)
            if m:
                page = int(m.group(1))
            free = 0
            for key in ("Pages free", "Pages inactive", "Pages speculable",
                        "Pages speculative", "Pages purgeable"):
                m = re.search(re.escape(key) + r":\s+(\d+)", out)
                if m:
                    free += int(m.group(1))
            if free:
                avail = free * page // (1 << 20)
        if total:
            return (total, avail,
                    "sysctl -n hw.memsize; free+inactive+speculative+purgeable "
                    "pages from vm_stat")
    return None, None, "no host-memory reader for platform %r" % sys.platform


def sample_host_available_mib(n, interval, log=None):
    """n readings of MemAvailable, spaced `interval` seconds apart."""
    samples = []
    for k in range(n):
        if k:
            time.sleep(interval)
        _, avail, _ = host_meminfo()
        if avail is not None:
            samples.append(int(avail))
            if log:
                log("  host sample %d/%d: %d MiB available" % (k + 1, n, avail))
    return samples


# ---------------------------------------------------------------------------
# is the GPU on the far side of a link, or is it in the same memory?
# ---------------------------------------------------------------------------

def device_tree_model():
    """The board name the firmware states, on the platforms that state one.

    Tegra and GB10 are SoCs, not PCIe cards, and the device tree names the
    board before any vendor tool is installed: /proc/device-tree/model reads
    "NVIDIA Jetson AGX Orin" or "NVIDIA DGX Spark". It is the cheapest
    corroboration there is for "this is not a discrete board".
    """
    for path in ("/proc/device-tree/model",
                 "/sys/firmware/devicetree/base/model"):
        try:
            with open(path, "rb") as fh:
                text = fh.read(256).split(b"\x00")[0]
            text = text.decode("utf-8", "replace").strip()
            if text:
                return text, path
        except OSError:
            continue
    return None, None


_PCI_VENDOR = {"0x8086": "Intel", "0x1002": "AMD", "0x10de": "NVIDIA",
               "0x1a03": "ASPEED", "0x102b": "Matrox"}


def drm_cards():
    """Every /sys/class/drm/cardN, with the evidence that classifies it.

    The signal that separates an integrated GPU from a discrete one without a
    PCI-ID database: a discrete card's driver publishes the size of its own
    device-local memory -- i915 `lmem_total_bytes`, xe
    `tile0/physical_vram_size_bytes`, amdgpu `mem_info_vram_total` -- and an
    integrated one has none to publish. The PCI address corroborates it: Intel
    and AMD integrated graphics sit on the root bus at 0000:00, and an add-in
    card never does.
    """
    out = []
    root = "/sys/class/drm"
    if not os.path.isdir(root):
        return out
    for name in sorted(os.listdir(root)):
        if not re.match(r"^card\d+$", name):
            continue
        dev = os.path.join(root, name, "device")

        def _read(*rel):
            try:
                with open(os.path.join(dev, *rel), "r") as fh:
                    return fh.read().strip()
            except OSError:
                return None

        vendor = _read("vendor")
        if not vendor:
            continue
        try:
            pci = os.path.basename(os.path.realpath(dev))
        except OSError:                                # pragma: no cover
            pci = None
        lmem = None
        for rel in (("lmem_total_bytes",),
                    ("tile0", "physical_vram_size_bytes"),
                    ("mem_info_vram_total",)):
            val = _read(*rel)
            if val and val.isdigit() and int(val) > 0:
                lmem = (int(val), "/".join(rel))
                break
        gtt = _read("mem_info_gtt_total")
        out.append({
            "card": name,
            "vendor_id": vendor.lower(),
            "vendor": _PCI_VENDOR.get(vendor.lower(), vendor),
            "device_id": _read("device"),
            "driver": (os.path.basename(os.path.realpath(
                os.path.join(dev, "driver"))) if os.path.exists(
                    os.path.join(dev, "driver")) else None),
            "pci_address": pci,
            "on_root_bus": bool(pci and pci.startswith("0000:00:")),
            "device_local_memory_bytes": lmem[0] if lmem else None,
            "device_local_memory_source": lmem[1] if lmem else None,
            "gtt_total_bytes": int(gtt) if gtt and gtt.isdigit() else None,
        })
    return out


def windows_video_controllers():
    """(controllers, how) on Windows, where there is no /sys/class/drm.

    AdapterRAM is famously wrong above 4 GB, so it is recorded and NOT used to
    size anything -- the only thing wanted here is the adapter's NAME, which is
    enough to tell an integrated part from an add-in card.
    """
    if os.name != "nt":
        return [], "not Windows"
    ps = shutil.which("powershell") or shutil.which("pwsh")
    if not ps:
        return [], "no powershell on PATH"
    cmd = [ps, "-NoProfile", "-NonInteractive", "-Command",
           "Get-CimInstance Win32_VideoController | "
           "Select-Object Name,AdapterCompatibility,AdapterRAM | "
           "ConvertTo-Json -Compress"]
    rc, out = _run(cmd, timeout=60)
    if rc != 0 or not out:
        return [], "Get-CimInstance Win32_VideoController returned nothing"
    try:
        data = json.loads(out)
    except ValueError:
        return [], "Win32_VideoController output was not JSON"
    if isinstance(data, dict):
        data = [data]
    return ([d for d in data if isinstance(d, dict)],
            "Get-CimInstance Win32_VideoController")


# The gap between two words of a product name, which is where the trademark
# marks live. Windows hands back the marketing string verbatim -- `Intel(R)
# Arc(TM) B390 Graphics`, `AMD Radeon(TM) Graphics` -- and every mark sits
# BETWEEN the brand word and the word after it, exactly where the patterns
# below assumed a plain space. That is how a name test comes to pass on Linux,
# where the name is a PCI id, and fail on Windows, where the name is prose,
# without anybody deciding that it should. Every multi-word name pattern in
# this module is built from _SEP, because one branch broken by a mark while
# the others go on working is the state this file was in until 2026-08-30,
# and it is exactly the shape of failure nobody looks for.
_SEP = r"\s*(?:\((?:tm|r)\)|[\u2122\u00ae])?\s+"

# Names that say "this GPU owns no memory". The Arc alternative is the BRAND
# and nothing more, because Intel ships Arc both ways: a Core Ultra's iGPU is
# `Arc Graphics`, `Arc 140V Graphics`, or the `Arc B390` named in
# REPORT-SPEC.md 7's card roster, and the add-in boards carry the same word.
# The model number is the only thing separating them, so _DISCRETE_INTEL_RE
# below names the boards and is asked FIRST.
#
# Until 2026-08-30 this branch read `arc\s+\d+\w*\s+graphics`, which matches
# no adapter name Windows has ever returned -- all of them write `Arc(TM)` --
# so every Arc-branded part fell straight through the Windows branch. With no
# Intel vendor tool to answer, board_total_mib is 0 on such a box, 0 is falsy,
# and the miss then fell past the size-ratio test as well and landed on the
# CPU-only fallback: a machine with a GPU profiled as a machine without one,
# and a campaign plan priced against the wrong pool with nothing looking wrong.
_IGPU_NAME_RE = re.compile(
    r"\b(uhd" + _SEP + r"graphics|hd" + _SEP + r"graphics|iris|arc|"
    r"radeon" + _SEP + r"graphics|vega" + _SEP + r"graphics|integrated)\b",
    re.I)

# Intel's DISCRETE boards, by name, because on Windows the name is the whole
# of the evidence: no Intel vendor tool answers, so there is no board size to
# read and the size-ratio test at step 7 never runs. Three families:
#
#   Arc Pro <n>    the professional add-in boards -- A40/A50/A60, and the
#                  B50/B70 of REPORT-SPEC.md 7's roster. "Pro" is the whole
#                  tell; no integrated part carries it.
#   Arc A<nnn>     Alchemist, which shipped only as discrete parts (A310
#                  through A770, plus the mobile A___M suffixes). No
#                  integrated GPU carries an A number.
#   Arc B5xx-B9xx  the Battlemage desktop cards that have shipped (B570,
#                  B580) plus every band above them, claimed in advance by
#                  `b[5-9]\d{2}`. The Core Ultra's integrated Battlemage parts
#                  are numbered B3xx -- the B390 of the roster is one -- so
#                  here it is the BAND, not the letter, that tells a board
#                  from an iGPU, and B6xx through B9xx sit on the board side
#                  because guessing that way costs one refusal and guessing
#                  the other way costs "system" (both below).
#
# Those three lines are assertions about Intel's naming rather than
# measurements, and they are what to re-read when a new part appears. The
# pattern fails safe in both directions when they go stale: an Arc board it
# misses is called shared-igpu, where check-request.py:memory_plan() refuses
# until somebody records the driver's share cap, and an iGPU it matches by
# mistake is called discrete, where the same function refuses until somebody
# records a board size. Either refusal costs one command. What both replace --
# "system", a box with no GPU at all -- costs a campaign plan, because
# "system" does not refuse: it prices the fit against host RAM and passes.
_DISCRETE_INTEL_RE = re.compile(
    r"\barc" + _SEP + r"(?:pro\b|a\d{3}[a-z]?\b|b[5-9]\d{2}[a-z]?\b)", re.I)

# NVIDIA product lines that are discrete boards by construction. NVIDIA's
# unified-memory parts are exactly the Tegra/Jetson line plus GB10, and those
# are matched above this; nothing sold as GeForce, Quadro, Tesla, TITAN or a
# datacenter PCIe/SXM part shares memory with the host. This is a POSITIVE
# identification, which is why it outranks the size-ratio test below -- a
# 24 GiB card in a 32 GiB box is 75% of the host's memory and is still a board.
_DISCRETE_NVIDIA_RE = re.compile(
    r"\b(geforce|quadro|tesla|titan|rtx|gtx|nvs|"
    r"[ahlv]\d{2,3}[a-z]?|p\d{2,3}|t\d{1,3}|k\d{2})\b", re.I)
# AMD discrete boards. "Radeon Graphics" with no model number is an APU's
# integrated part and is deliberately NOT here -- _IGPU_NAME_RE has it. The
# separator is _SEP for the same reason the Intel patterns use it: a Windows
# box calls a board `AMD Radeon(TM) RX 7900 XTX`, and `radeon\s+rx` does not
# match that string.
_DISCRETE_AMD_RE = re.compile(
    r"\b(instinct|mi\d{2,3}[a-z]?|radeon" + _SEP + r"(?:pro|rx)\b|"
    r"rx\s?\d{3,4})\b", re.I)


def classify_topology(gpu_name, board_mib, host_total_mib, drm, win_gpus,
                      dt_model, have_nvidia, have_rocm):
    """(topology, how, evidence) -- or (None, why it cannot be settled, ...).

    Ordered by how strong the evidence is, and it stops at the first thing that
    actually settles the question. Nothing here falls through to a default:
    the last branch returns None, because "we could not tell" is a value this
    schema carries and "discrete" is not a safe thing to assume on a box the
    script has not recognised.
    """
    ev = {"gpu_name": gpu_name, "board_total_mib": board_mib,
          "host_mem_total_mib": host_total_mib,
          "device_tree_model": dt_model,
          "drm_cards": drm or None,
          "windows_video_controllers": win_gpus or None}
    low = (gpu_name or "").lower()

    # 1. Named parts that are known SoCs, and named parts that are known to be
    #    neither. The refusal is as important as the match.
    for needle, why in AMBIGUOUS_NVIDIA:
        if needle in low:
            return None, why + (" Pass --topology explicitly once you have "
                                "decided which pool this campaign prices "
                                "against, and say so in the report."), ev
    for needle, why in UNIFIED_NVIDIA:
        if needle in low:
            return "unified", "the GPU is %r. %s" % (gpu_name, why), ev

    # 2. Apple Silicon: one pool by construction.
    if sys.platform == "darwin" and platform.machine().startswith("arm"):
        return ("unified",
                "macOS on Apple Silicon (%s): the SoC has one memory pool and "
                "Metal's working-set limit is a policy over it, not a separate "
                "board." % platform.machine(), ev)

    # 3. The firmware names the board and it is an SoC. `dgx spark` is built
    #    from _SEP like every other multi-word name here, which costs nothing
    #    and keeps the claim above true: the device tree writes `NVIDIA DGX
    #    Spark` with one plain space and that still matches, because _SEP only
    #    ADDS the marked and multi-space forms. A branch whose one input is a
    #    firmware string nobody here has read on real hardware yet is exactly
    #    where a lone plain space survives a sweep, to be found by the next
    #    box rather than by this file.
    if dt_model and re.search(r"jetson|dgx" + _SEP + r"spark|tegra|orin|thor",
                              dt_model, re.I):
        return ("unified",
                "the device tree names this board %r, which is an SoC with one "
                "memory pool rather than a host plus a card." % dt_model, ev)

    # 4. A named product line that is a board by construction.
    if have_nvidia and _DISCRETE_NVIDIA_RE.search(low):
        return ("discrete",
                "nvidia-smi names the card %r. NVIDIA's shared-memory parts "
                "are the Tegra/Jetson line and GB10, all matched above this; "
                "a GeForce, Quadro, Tesla, TITAN or datacenter part has its "
                "own board memory behind a PCIe link." % gpu_name, ev)
    if have_rocm and _DISCRETE_AMD_RE.search(low):
        return ("discrete",
                "rocm-smi names the card %r, which is a discrete Radeon or "
                "Instinct board rather than an APU's integrated graphics."
                % gpu_name, ev)

    # 5. What the kernel says about where the memory is. Root bus FIRST: an
    #    AMD APU publishes mem_info_vram_total for its BIOS carve-out, so
    #    "publishes device-local memory" alone would misread it as a board.
    if drm:
        rendering = [c for c in drm if c["vendor_id"] != "0x1a03"]
        igpu = [c for c in rendering
                if c["on_root_bus"] and c["vendor_id"] in ("0x8086", "0x1002")]
        if igpu and not have_nvidia:
            c = igpu[0]
            return ("shared-igpu",
                    "%s %s sits on the root bus at %s under %s: an integrated "
                    "GPU, which maps a share of system RAM rather than owning "
                    "any%s."
                    % (c["vendor"], c["card"], c["pci_address"],
                       c["driver"] or "an unnamed driver",
                       (" (its mem_info_vram_total of %.1f GiB is the BIOS "
                        "carve-out, not a board)"
                        % (c["device_local_memory_bytes"] / 2.0**30))
                       if c["device_local_memory_bytes"] else ""), ev)
        with_lmem = [c for c in rendering
                     if c["device_local_memory_bytes"] and not c["on_root_bus"]]
        if with_lmem:
            c = with_lmem[0]
            return ("discrete",
                    "%s %s is at %s, off the root bus, and publishes %.1f GiB "
                    "of device-local memory at %s -- memory an integrated GPU "
                    "does not have."
                    % (c["vendor"], c["card"], c["pci_address"],
                       c["device_local_memory_bytes"] / 2.0**30,
                       c["device_local_memory_source"]), ev)
        if rendering and not have_nvidia and not have_rocm:
            return (None,
                    "/sys/class/drm lists %s but none of them publishes "
                    "device-local memory off the root bus and none is an Intel "
                    "or AMD part on it, so this script cannot tell whether the "
                    "GPU owns memory or borrows it."
                    % ", ".join("%s %s" % (c["vendor"], c["card"])
                                for c in rendering), ev)

    # 6. Windows, where there is no /sys/class/drm to read and no vendor tool
    #    answering either, so the adapter NAME is the whole of the evidence
    #    and AdapterRAM is not usable (it is 32 bits wide and wrong above
    #    4 GB). The BOARD question is asked first, because BOTH vendors sell
    #    the iGPU and the add-in card under one brand -- `Intel(R) Arc(TM)
    #    B390 Graphics` beside `Intel(R) Arc(TM) B580 Graphics`, `AMD
    #    Radeon(TM) Graphics` beside `AMD Radeon(TM) RX 7900 XTX`, and the
    #    integrated half of each pair answers to _IGPU_NAME_RE -- and a box
    #    that lists both is a box whose campaign runs on the board. Getting
    #    this order wrong prices an add-in card against the host's RAM, which
    #    is a pass, not a refusal.
    #
    #    Asking the board question for INTEL alone did exactly that to every
    #    Ryzen desktop with a Radeon card in it: widening _IGPU_NAME_RE's
    #    separator on 2026-08-30 brought `AMD Radeon(TM) Graphics` into this
    #    branch for the first time, and an Intel-only board list then answered
    #    shared-igpu, naming the APU's iGPU on a box whose campaign runs on
    #    the RX board. Both discrete patterns are consulted here for that
    #    reason, and fixture-topo-discrete-radeon pins it.
    if win_gpus and not have_nvidia and not have_rocm:
        names = [str(g.get("Name") or "") for g in win_gpus]
        boards = [n for n in names if _DISCRETE_INTEL_RE.search(n)
                  or _DISCRETE_AMD_RE.search(n)]
        shared = [n for n in names
                  if n not in boards and _IGPU_NAME_RE.search(n)]
        if boards:
            intel = bool(_DISCRETE_INTEL_RE.search(boards[0]))
            family = ("an Intel add-in board: Arc Pro, an Alchemist A-series "
                      "part or a Battlemage desktop card"
                      if intel else
                      "an AMD add-in board: a Radeon RX, a Radeon Pro or an "
                      "Instinct part")
            beside = ((" %r is listed beside it and is the integrated part "
                       "that carries the same brand, which is why the board "
                       "question is asked first." % shared[0])
                      if shared else "")
            return ("discrete",
                    "Win32_VideoController names %r, %s.%s It has memory of "
                    "its own behind PCIe, and no %s vendor tool answered "
                    "here, so the board size read here is %r and the fit "
                    "refuses until it is recorded with --board-total-mib N."
                    % (boards[0], family, beside,
                       "Intel" if intel else "AMD", board_mib), ev)
        if shared:
            return ("shared-igpu",
                    "Win32_VideoController names %r, no vendor tool answered "
                    "for a discrete card, and no adapter name here is an "
                    "Intel or AMD add-in board -- so the GPU maps a share of "
                    "system RAM rather than owning any. The share the driver "
                    "allows is NOT MemTotal: record it with "
                    "--igpu-share-limit-mib N." % shared[0], ev)

    # 7. The measurement that needs no name: a discrete board is a FRACTION of
    #    the host's memory, and one pool counted twice is not. This is the
    #    branch that catches a GB10 whose product name this script has never
    #    seen -- and the band in the middle is where it refuses.
    if board_mib and host_total_mib:
        ratio = board_mib / float(host_total_mib)
        ev["board_over_host_ratio"] = round(ratio, 3)
        if ratio >= 0.90:
            return (None,
                    "the GPU reports %s MiB of memory against %s MiB of system "
                    "RAM -- %.0f%% of it. A discrete board is a fraction of the "
                    "host's memory; a number this close to all of it is one "
                    "pool being counted twice, and board-minus-reserve would "
                    "price the model against RAM the OS is living in. Refusing "
                    "to call this discrete. Pass --topology unified (or "
                    "shared-igpu) once you have confirmed which it is."
                    % (_c(board_mib), _c(host_total_mib), ratio * 100), ev)
        if ratio <= 0.75:
            return ("discrete",
                    "the GPU reports %s MiB of memory against %s MiB of system "
                    "RAM (%.0f%%). A pool that is a fraction of the host's is a "
                    "board of its own, not a share of the host's."
                    % (_c(board_mib), _c(host_total_mib), ratio * 100), ev)
        return (None,
                "the GPU reports %s MiB of memory against %s MiB of system RAM "
                "(%.0f%%). That is too large a share to read as a discrete "
                "board and too small to read as one pool, so this script will "
                "not pick. Pass --topology."
                % (_c(board_mib), _c(host_total_mib), ratio * 100), ev)

    # 8. No GPU pool at all, and the tools agree there is no GPU.
    if not have_nvidia and not have_rocm and not drm and not win_gpus:
        return ("system",
                "no GPU vendor tool answered, /sys/class/drm lists no card and "
                "no video controller was enumerated: there is no GPU memory "
                "pool, so the fit is priced against system RAM.", ev)
    if board_mib == 0 and not have_nvidia and not have_rocm:
        return ("system",
                "no GPU vendor tool answered, so there is no GPU memory pool "
                "and the fit is priced against system RAM.", ev)

    return (None,
            "nothing here settled it: %s answered for the card and %s for the "
            "host pool. Pass --topology %s -- the fit arithmetic differs on "
            "each, and this script will not pick one for you."
            % ("nvidia-smi" if have_nvidia else
               "rocm-smi" if have_rocm else "no vendor tool",
               "no reader" if not host_total_mib else "/proc/meminfo",
               "|".join(TOPOLOGIES)), ev)


def _c(n):
    """Thousands separators, for the prose above."""
    try:
        return "{:,}".format(int(n))
    except (TypeError, ValueError):                    # pragma: no cover
        return str(n)


# ---------------------------------------------------------------------------
# elevation, and the power-limit write test
# ---------------------------------------------------------------------------

def elevated():
    """True/False, or None when the question cannot be answered here.

    Delegated, not copied. The predicate lives in scripts/bench/provenance.py,
    which every probe in this tree already imports, so a sweep line and this
    machine profile can never disagree about what "elevated" meant on one box.
    A missing import is answered None and pl_write_test() refuses on None, so
    the failure is a field this script declines to fill rather than a claim it
    gets wrong.
    """
    if _provenance is None:                        # pragma: no cover
        return None
    return _provenance.elevated()


def record_elevation(p):
    """elevated / sudo_nopasswd / privilege_path onto the profile.

    WHY THE PRIVILEGE IS A FIELD OF THIS RECORD AND NOT A FOOTNOTE ON ONE.
    Some of the fields beside it can only be read by a privileged process, so
    elevation is a condition of the machine profile itself and not only of the
    sweeps that quote it later. The clearest case is the one this port walks
    into: on Linux the SMBIOS table at /sys/firmware/dmi/tables/DMI is
    root-readable only, so `ram_channels` is MEASURED in a root shell and null
    in a user shell on the same box, and rule 3 names RAM channels as a
    condition of every offload and iGPU speed. pl_writable_without_elevation
    is the other: it is a claim about the unelevated case and it is only
    filled by an unelevated run.

    The values come from scripts/bench/provenance.py, which is what stamps
    them onto every probe LINE, so a machine.json and the sweep lines taken on
    the same box say the same thing in the same words rather than two things
    that have to be reconciled. Nothing here judges the answer: an elevated
    run is an operating mode a campaign chooses so that the power-limit knob
    (rule 24) can be driven with nobody at the keyboard.
    """
    if _provenance is None:                        # pragma: no cover
        for key in ("elevated", "sudo_nopasswd", "privilege_path"):
            p.unknown(key, "scripts/bench/provenance.py did not import, and "
                           "this script keeps no second copy of the "
                           "predicate - see elevated()")
        return
    # Dispatched on the LABEL the other module wrote, never on a fall-through
    # to measured. provenance.py labels every `how` with one of the four this
    # script uses, and a label it does not recognise is a label this script
    # must not upgrade: writing an unrecognised one down as MEASURED is how a
    # value that was never measured acquires a provenance, which is the defect
    # the whole privilege block exists to prevent. Unknown keeps the reason
    # whole so the next reader can see the label that was not understood.
    for key, value, how in _provenance.elevation():
        label, _sep, why = how.partition(": ")
        why = why or how
        if value is None or label == "UNKNOWN":
            # null is not false: the field is absent, and `why` says which
            # question went unanswered and why it was not asked.
            p.unknown(key, why)
        elif label == "DERIVED":
            p.derived(key, value, why)
        elif label == "MEASURED":
            p.measured(key, value, why)
        elif label == "CITED":
            p.cited(key, value, why)
        else:                                      # pragma: no cover
            p.unknown(key, "provenance.py labelled this %r, which is not one "
                           "of MEASURED / DERIVED / CITED / UNKNOWN, so the "
                           "value it carried is not written down here: %s"
                           % (label, how))


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
    if is_root is None:
        # Null is not false, and this is where the difference costs something.
        # The field is NAMED for a condition - "without elevation" - so a
        # process that cannot say whether it was elevated cannot fill it: a
        # set that succeeded because the shell was privileged would be written
        # down as the card allowing it, and rule 3 says a number whose
        # condition is unknown is unfalsifiable. Nothing is run.
        return None, ("this process cannot tell whether it is elevated - "
                      "neither IsUserAnAdmin() nor os.geteuid() answered, or "
                      "scripts/bench/provenance.py did not import - and this "
                      "field is a claim about the UNELEVATED case, so it is "
                      "left unfilled rather than answered from a run whose "
                      "privileges are unknown. Nothing was set."), {}
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

# board_total_mib's provenance on a box where no GPU vendor tool answered, and
# the three sentences that can only be written once the topology is settled.
# They are module constants because two places quote them: detect(), which
# writes the field BEFORE classify_topology() has looked at a single adapter
# name, and the TOPO_FIXTURES below, whose whole purpose is to be the artefact
# a real box of that shape would emit. A fixture that hand-writes a provenance
# string the code cannot produce is a test that passes while the thing it names
# is broken, and that is what the discrete-arc fixture was until 2026-08-30.
#
# What the absence of a vendor tool proves is that there is no board SIZE to
# read. WHETHER there is a board is a different question, settled later and by
# other evidence, and until 2026-08-30 this string answered that one too --
# "so this is a CPU box and there is no board memory". On the Windows Arc box
# the 2026-08-30 classifier change was written for, that put "this is a CPU
# box" on the board field of the same machine.json that carries
# memory_topology 'discrete' two fields above it, and nothing warned: the
# board-on-a-shared-pool warning below tests `board_mib` for truth, and 0 is
# not true.
_BOARD_ZERO_NO_TOOL = (
    "no GPU vendor tool answered, so there is no board size to read. 0 makes "
    "every board-shaped fit check refuse rather than pass. If this box has a "
    "board, install the vendor tool and re-run, or record the size with "
    "--board-total-mib N.")

_BOARD_ZERO_ON_DISCRETE = (
    "memory_topology is 'discrete' and this is 0: the topology is known and "
    "the board size is not. scripts/check-request.py:memory_plan() refuses on "
    "that pair rather than passing. Record the board's memory with "
    "--board-total-mib N and re-run.")

_BOARD_ZERO_ON_SHARED = (
    "memory_topology is 'shared-igpu', so there is no board here for a size "
    "to be missing from. The fit is priced against host_mem_total_mib minus "
    "host_reserve_mib, capped by igpu_share_limit_mib -- see "
    "scripts/check-request.py:memory_plan().")

_BOARD_ZERO_ON_SYSTEM = (
    "memory_topology is 'system': nothing here answered for a GPU pool, so "
    "the 0 is the whole answer rather than a reading that is missing, and the "
    "fit is priced against host_mem_total_mib minus host_reserve_mib.")


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

    # ---- the host pool ----------------------------------------------------
    # Measured on every topology, not only the ones that price against it: on a
    # discrete box it is what gpu_lock sizes its commit cap from, and on every
    # other one it IS the budget. Recorded either way, so a machine.json can be
    # re-read after the fact without re-running anything.
    host_total, host_avail, host_how = host_meminfo()
    if host_total:
        p.measured("host_mem_total_mib", int(host_total), host_how,
                   available_now_mib=host_avail)
    else:
        p.unknown("host_mem_total_mib", host_how)

    # ---- the card ---------------------------------------------------------
    nv = nvidia_query(NVIDIA_FIELDS, index=args.gpu)
    gpu_count = nvidia_count()
    row = nv[0] if nv else None
    have_nvidia = row is not None
    have_rocm = bool(shutil.which("rocm-smi"))

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
        # compute_cap is a separate query on purpose: it postdates R470 and a
        # driver that does not know the field fails the WHOLE --query-gpu row,
        # which would cost the board size to learn the architecture.
        cc = nvidia_query(("compute_cap",), index=args.gpu)
        cc_val = cc[0][0] if cc and cc[0] else None
        if cc_val:
            p.measured("compute_cap", cc_val,
                       "nvidia-smi --query-gpu=compute_cap -- the SM version "
                       "this card actually is, which is what "
                       "-DCMAKE_CUDA_ARCHITECTURES has to match")
        else:
            p.unknown("compute_cap",
                      "nvidia-smi did not answer --query-gpu=compute_cap "
                      "(the field postdates driver R470)")
        dpl = _float(default_pl)
        if dpl is not None:
            p.measured("power_default_limit_w", dpl,
                       "nvidia-smi --query-gpu=power.default_limit (W)",
                       power_limit_now_w=_float(cur_pl))
        else:
            p.unknown("power_default_limit_w",
                      "nvidia-smi reports no power.default_limit for this "
                      "card (it is [N/A] on cards without a settable limit)")
        # ECC IS A BANDWIDTH CONDITION, NOT A RELIABILITY PREFERENCE.
        # Datacenter parts ship with ECC ON over their memory and every read
        # pays for it; consumer parts have no ECC at all and report [N/A].
        # Rule 10's decode estimate is bandwidth over file bytes, and rule 3
        # says a number travels with the conditions that produced it -- so a
        # throughput or J/token figure taken with ECC on is not comparable with
        # one taken with it off, and until now nothing in this profile said
        # which you were holding. Recorded, never changed: flipping it needs a
        # reboot and is the operator's call, not a detector's.
        _ecc = nvidia_query(("ecc.mode.current", "ecc.mode.pending"),
                            index=args.gpu)
        ecc_cur = _ecc[0][0] if _ecc and _ecc[0] else None
        ecc_pend = _ecc[0][1] if _ecc and _ecc[0] and len(_ecc[0]) > 1 else None
        if ecc_cur and ecc_cur not in ("[N/A]", "N/A", ""):
            p.measured("ecc_mode", ecc_cur,
                       "nvidia-smi --query-gpu=ecc.mode.current",
                       pending=ecc_pend,
                       note=("ECC taxes every memory read. A bandwidth-bound "
                             "decode number is not comparable across ECC "
                             "states (rule 3)."))
        else:
            p.unknown("ecc_mode",
                      "nvidia-smi reports no ecc.mode for this card, which is "
                      "what a consumer part without ECC memory returns. Not a "
                      "failure: there is no state to record.")
        if gpu_count > 1:
            p.note("gpu_name", warning=(
                "%d GPUs on this box; this profile describes GPU %d only. "
                "Rule 3: say which card produced a number, and re-run with "
                "--gpu N for the others. ALSO: nvidia-smi orders devices by "
                "PCI bus, CUDA does NOT by default -- so CUDA_VISIBLE_DEVICES=%d "
                "may not be the card this profile describes. Export "
                "CUDA_DEVICE_ORDER=PCI_BUS_ID before every launch so the two "
                "agree, or every number here is attributed to the wrong GPU."
                % (gpu_count, args.gpu, args.gpu)))
    else:
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
            p.derived("board_total_mib", 0, _BOARD_ZERO_NO_TOOL)
            p.unknown("driver", "no GPU vendor tool to ask")
            p.unknown("power_default_limit_w",
                      "no GPU vendor tool to ask; a CPU run has no board "
                      "power limit")

    # ---- backend ----------------------------------------------------------
    _detect_backend(p, args, have_nvidia)

    # ---- the privilege this profile was measured under --------------------
    # Recorded before the power-limit test because that test's answer depends
    # on it, and recorded whether or not the test runs: --no-pl-test and a box
    # with no nvidia-smi both skip the test, and neither is a reason to lose
    # the condition (rule 28 - not written during the run, not recoverable).
    record_elevation(p)

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

    # ---- which arithmetic is even right -----------------------------------
    if "compute_cap" not in p.values:
        p.unknown("compute_cap",
                  "compute_cap is an NVIDIA field and no NVIDIA card answered")
    _measure_topology(p, args, have_nvidia, have_rocm, today, log)
    return p


def _measure_topology(p, args, have_nvidia, have_rocm, today, log):
    """memory_topology, the host reserve, the iGPU share, bandwidth, cuda_arch.

    Everything here is a MEASUREMENT of the machine. The arithmetic that
    consumes it -- which pool the fit is priced against, and which of rule 13's
    two ceilings still means anything -- lives in
    scripts/check-request.py:memory_plan(), so that the Stage-0 gate and the
    planner cannot answer the same question differently.
    """
    gpu_name = p.values.get("gpu_name")
    board_mib = p.values.get("board_total_mib")
    host_total = p.values.get("host_mem_total_mib")
    drm = drm_cards()
    win_gpus, win_how = windows_video_controllers()
    dt_model, dt_path = device_tree_model()

    # ---- the topology itself ---------------------------------------------
    if args.topology:
        p.cited("memory_topology", args.topology,
                "--topology %s, stated by the operator" % args.topology,
                note="a stated topology overrides the evidence below; it is "
                     "recorded as CITED so a reader can tell it was asserted "
                     "rather than measured",
                evidence_that_was_overridden=classify_topology(
                    gpu_name, board_mib, host_total, drm, win_gpus, dt_model,
                    have_nvidia, have_rocm)[1])
        topology = args.topology
    else:
        topology, how, ev = classify_topology(
            gpu_name, board_mib, host_total, drm, win_gpus, dt_model,
            have_nvidia, have_rocm)
        ev["device_tree_path"] = dt_path
        ev["windows_probe"] = win_how if os.name == "nt" else None
        if topology:
            p.derived("memory_topology", topology, how, **ev)
        else:
            p.unknown("memory_topology", how, **ev)
    log("memory topology: %s" % (topology or "UNKNOWN -- see machine.json"))

    # A board reading on a box that has no board is the silent failure this
    # whole field exists to catch. Say so ON the reading, not only beside it.
    if topology in ("unified", "shared-igpu") and board_mib:
        p.note("board_total_mib", warning=(
            "memory_topology is %r: this is NOT a discrete board. %s MiB is "
            "the shared pool as the vendor tool reports it, and subtracting a "
            "desktop reserve from it prices the model against memory the "
            "operating system is already using. The fit budget comes from "
            "host_mem_total_mib minus host_reserve_mib instead -- see "
            "scripts/check-request.py:memory_plan()."
            % (topology, _c(board_mib))))

    # The mirror image, and the reason the warning above cannot catch it: a
    # board reading of 0 is falsy, so it passes that test whatever the
    # topology says. The 0 has exactly one writer -- the no-vendor-tool branch
    # of detect() -- and it is written before this classifier has run, so all
    # it can say is that nothing here could size a board. What it MEANS
    # depends on the topology, which exists by this line and did not by that
    # one, so the sentence that depends on it is attached here.
    if board_mib == 0:
        if topology == "discrete":
            p.note("board_total_mib", warning=_BOARD_ZERO_ON_DISCRETE)
        elif topology == "shared-igpu":
            p.note("board_total_mib", note=_BOARD_ZERO_ON_SHARED)
        elif topology == "system":
            p.note("board_total_mib", note=_BOARD_ZERO_ON_SYSTEM)

    # ---- the host reserve, measured the same way the desktop one is -------
    _measure_host_reserve(p, args, topology, today, log)

    # ---- what the driver will let an integrated GPU map -------------------
    _measure_igpu_share(p, args, topology, drm)

    # ---- bandwidth (rule 10) ---------------------------------------------
    _record_bandwidth(p, args, topology, gpu_name)

    # ---- the build's CUDA architecture -----------------------------------
    _record_cuda_arch(p, gpu_name, topology)


def _measure_host_reserve(p, args, topology, today, log):
    """MemTotal - MemAvailable, sampled: the host's own standing footprint.

    Exactly the shape of the desktop reserve on a board, and for the same
    reason (rule 14): the fence a fit is held to is what the machine is ALREADY
    holding when nothing has been loaded, and that is a dated range measured
    under a named load, never a constant.
    """
    key = "host_reserve_mib"
    total = p.values.get("host_mem_total_mib")
    common = {"desktop_state": args.desktop_state or None,
              "samples_n": args.samples, "interval_s": args.interval}
    if not total:
        p.unknown(key, "host_mem_total_mib is unknown, so there is nothing to "
                       "subtract MemAvailable from", **common)
        return
    log("host reserve: %d samples, %.1fs apart (MemTotal - MemAvailable)"
        % (args.samples, args.interval))
    avail = sample_host_available_mib(args.samples, args.interval, log=log)
    if not avail:
        p.unknown(key,
                  "no MemAvailable reading on this platform, so the host's "
                  "standing footprint is unmeasured. On unified, shared-igpu "
                  "and CPU-only boxes that IS the fit's reserve, so the fit "
                  "will refuse rather than guess it.", **common)
        return
    used = sorted(int(total) - a for a in avail)
    extra = dict(common)
    extra.update(
        memtotal_mib=int(total),
        available_samples_mib=avail,
        desktop_state=args.desktop_state or "NOT STATED -- pass --desktop-state",
        window_s=round(args.interval * max(0, len(avail) - 1), 1),
        warning=("min/max span this sample window ONLY, on whatever this box "
                 "was doing at the time. On a unified or CPU-only box this is "
                 "the anti-spill fence rule 14 is about, and it has to be "
                 "measured under the load the campaign will actually run "
                 "beside -- a reserve sampled on an idle box is a fence that "
                 "moves when someone opens a browser."))
    p.measured(key, {"min": used[0], "max": used[-1], "n": len(used),
                     "date": today},
               "MemTotal minus MemAvailable, %d samples %.1fs apart"
               % (len(used), args.interval), **extra)


def _measure_igpu_share(p, args, topology, drm):
    """How much of system RAM the driver will let an integrated GPU map.

    This is the second ceiling on a shared-igpu box and it is NOT MemTotal:
    i915/xe and WDDM both cap the mappable share at roughly half of RAM, so
    pricing against MemTotal over-promises by about 2x. Neither driver
    publishes the cap anywhere an unprivileged process can read it, so the
    honest answer here is usually UNKNOWN plus the two commands that DO answer
    it -- and the fit refuses on a shared-igpu box until one of them has.
    """
    key = "igpu_share_limit_mib"
    if args.igpu_share_limit_mib is not None:
        p.cited(key, args.igpu_share_limit_mib,
                "--igpu-share-limit-mib %d, stated by the operator"
                % args.igpu_share_limit_mib)
        return
    if topology != "shared-igpu":
        p.unknown(key, "not applicable: memory_topology is %r, and only an "
                       "integrated GPU has a driver-imposed share of system "
                       "RAM" % (topology or "UNKNOWN"))
        return
    # amdgpu is the one driver here that does publish it, as the GTT aperture.
    for card in drm or []:
        if card.get("gtt_total_bytes"):
            p.measured(key, int(card["gtt_total_bytes"]) // (1 << 20),
                       "%s/device/mem_info_gtt_total -- the GTT aperture, "
                       "which is how much system RAM amdgpu will map for the "
                       "GPU" % card["card"],
                       card=card["card"], vendor=card["vendor"],
                       device_local_memory_bytes=card
                       ["device_local_memory_bytes"])
            return
    p.unknown(key,
              "no driver here publishes the mappable share to an unprivileged "
              "process (i915 and xe do not; amdgpu's mem_info_gtt_total is "
              "absent). It is NOT MemTotal -- both i915/xe and WDDM cap it at "
              "roughly half of system RAM, so assuming MemTotal over-promises "
              "by about 2x and the fit will refuse instead. Read it with "
              "`clinfo | grep -i 'global memory size'` or, on the OpenVINO "
              "build, from GPU_DEVICE_TOTAL_MEM_SIZE, then pass "
              "--igpu-share-limit-mib N.")


def _record_bandwidth(p, args, topology, gpu_name):
    """spec_bandwidth_gbs: rule 10's decode estimate hangs off it.

    MEASURED is not on offer -- nothing here runs a bandwidth benchmark -- so
    it is CITED from a published specification when there is one for this part,
    DERIVED from the SMBIOS module speed and channel count when the pool is
    system RAM, and UNKNOWN otherwise. A decode estimate built on an UNKNOWN is
    not published; that is the point of writing it down as one.
    """
    key = "spec_bandwidth_gbs"
    if args.spec_bandwidth_gbs is not None:
        if not args.bandwidth_source:
            p.unknown(key,
                      "--spec-bandwidth-gbs %g was given with no "
                      "--bandwidth-source. Rule 1 has no category for a number "
                      "without a provenance, so it is refused rather than "
                      "recorded." % args.spec_bandwidth_gbs)
            return
        p.cited(key, float(args.spec_bandwidth_gbs),
                "--spec-bandwidth-gbs %g, source: %s"
                % (args.spec_bandwidth_gbs, args.bandwidth_source))
        return

    low = (gpu_name or "").lower()
    for needle, gbs, source in SPEC_BANDWIDTH:
        if needle in low:
            p.cited(key, gbs, source, matched_on=needle, gpu_name=gpu_name)
            return

    if topology in ("unified", "shared-igpu", "system"):
        chan = p.values.get("ram_channels")
        speed = None
        prov = p.prov.get("ram_channels") or {}
        for dev in (prov.get("modules") or []):
            if dev.get("speed_mts"):
                speed = max(speed or 0, dev["speed_mts"])
        if chan and speed:
            gbs = chan * DDR_BYTES_PER_CHANNEL * speed / 1000.0
            p.derived(key, round(gbs, 1),
                      "%d channels x %d B per channel x %d MT/s / 1000 = "
                      "%.1f GB/s. This is the THEORETICAL PEAK of the memory "
                      "controller, not a measurement: rule 10's constant is "
                      "re-derived against a measured figure, and real streams "
                      "land well under this."
                      % (chan, DDR_BYTES_PER_CHANNEL, speed, gbs),
                      channels=chan, speed_mts=speed,
                      assumption="DDR channels are 64 bits wide however the "
                                 "vendor sub-divides them")
            return
        p.unknown(key,
                  "the fit is priced against system memory (topology %r) and "
                  "rule 10's decode estimate needs its bandwidth, but %s. "
                  "Measure it (mbw, STREAM, `sysbench memory`) or pass "
                  "--spec-bandwidth-gbs N --bandwidth-source '...'."
                  % (topology,
                     "the channel count is unknown" if not chan else
                     "SMBIOS reported no module speed"))
        return
    p.unknown(key,
              "no published bandwidth on file for %r, and this script measures "
              "none. Pass --spec-bandwidth-gbs N --bandwidth-source '...' if "
              "rule 10's decode estimate is going to be published for this box."
              % (gpu_name or "this device"))


def _record_cuda_arch(p, gpu_name, topology):
    """What the installed build was compiled for -- and whether that is right.

    bin/llama.cpp/INSTALL.json records CMAKE_CUDA_ARCHITECTURES because
    setup.sh writes it there. On GB10 the value matters and the default does
    not produce it, so the mismatch is flagged HERE rather than discovered as a
    slow campaign nobody can explain.
    """
    key = "cuda_arch"
    install = os.path.join(paths.repo_root(), "bin", "llama.cpp",
                           "INSTALL.json")
    meta = {}
    if os.path.isfile(install):
        try:
            with open(install, "r", encoding="utf-8-sig") as fh:
                meta = json.load(fh) or {}
        except (OSError, ValueError):
            meta = {}
    val = meta.get("cuda_arch")
    low = (gpu_name or "").lower()
    want = None
    for needle, arch, why in CUDA_ARCH_REQUIRED:
        if needle in low:
            want = (arch, why)
            break

    if not os.path.isfile(install):
        p.unknown(key, "no bin/llama.cpp/INSTALL.json: nothing recorded which "
                       "architecture this build was compiled for. Run "
                       "scripts/setup.sh (or setup.ps1); it writes it.")
    elif val is None:
        p.unknown(key,
                  "bin/llama.cpp/INSTALL.json records cuda_arch: null -- this "
                  "build is a downloaded binary or a non-CUDA flavor (%s), so "
                  "no CMAKE_CUDA_ARCHITECTURES was chosen here."
                  % (meta.get("flavor") or "flavor not recorded"),
                  install_json=meta)
    else:
        p.measured(key, str(val),
                   "bin/llama.cpp/INSTALL.json, written by the setup script "
                   "that built this llama.cpp",
                   built_from_source=meta.get("built_from_source"),
                   flavor=meta.get("flavor"), tag=meta.get("tag"))
    if want:
        arch, why = want
        got = p.values.get(key)
        if got != arch:
            p.note(key, warning=(
                "this box is %r and the build records cuda_arch %r, not %r. %s"
                % (gpu_name, got, arch, why)))
        p.note(key, required_for_this_gpu=arch, required_because=why)
    if topology == "unified" and p.values.get(key) in (None, "native"):
        p.note(key, warning_unified=(
            "memory_topology is 'unified' and there is no official Linux "
            "aarch64 CUDA binary for this class of box, so the build is a "
            "source build and the architecture is a choice somebody made. "
            "Record it."))


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
# THE TOPOLOGY FIXTURES -- the decision table, made runnable
# ---------------------------------------------------------------------------
#
# A classifier whose whole job is to refuse in the ambiguous case cannot be
# checked by running it on the one box that happens to be here. These are the
# four topologies, the two refusals, and the four Windows boxes where an Arc-
# or Radeon-branded NAME is the only evidence there is -- each as (a) the
# inputs classify_topology() sees and (b) a machine.json the planner and the
# Stage-0 gate can be pointed at, so that "the arithmetic differs per
# topology" is a thing a reader can run rather than a thing this file claims.
#
# The four Windows boxes come in two pairs, iGPU alone and iGPU beside a
# board, because on Windows the two shapes differ by ONE adapter name and the
# classifier has nothing else to go on: each pair pins both halves of step 6's
# ordering, and a fix to one vendor's pattern that changes the other verdict
# fails here rather than in a campaign plan.
#
# WHAT IS MEASURED AND WHAT IS CONSTRUCTED, per fixture, is stated in its own
# provenance and in its FIXTURE.md. The discrete one is this repository's
# reference rig, measured. The other nine are constructed from published
# specifications and say so on every field -- a constructed number that admits
# it is a fixture; a constructed number that does not is the failure this whole
# workstream is about.

FIXTURE_PREFIX = "fixture-topo-"
_FX_DATE = "2026-08-29"


def _fx(topology, gpu_name, board, host_total, host_reserve, **kw):
    """One fixture machine.json, with a provenance entry on every field."""
    rec = {
        "_schema": SCHEMA,
        "_fixture": True,
        "measured_at": _FX_DATE + "T00:00:00",
        "host": "fixture",
        "memory_topology": topology,
        "board_total_mib": board,
        "gpu_name": gpu_name,
        "backend": kw.get("backend"),
        "driver": kw.get("driver"),
        "host_ram_gb": (round(host_total / 1024.0, 1) if host_total else None),
        "host_mem_total_mib": host_total,
        "host_reserve_mib": (
            None if host_reserve is None else
            {"min": host_reserve, "max": host_reserve, "n": kw.get("host_n", 1),
             # The date string is quoted verbatim beside every budget this
             # fixture produces, so a constructed one says so THERE, not only
             # in a provenance block nobody prints.
             "date": kw.get("host_date", _FX_DATE + " CONSTRUCTED")}),
        "igpu_share_limit_mib": kw.get("igpu_share_limit_mib"),
        "spec_bandwidth_gbs": kw.get("spec_bandwidth_gbs"),
        "cuda_arch": kw.get("cuda_arch"),
        "compute_cap": kw.get("compute_cap"),
        "ram_channels": kw.get("ram_channels"),
        "os": kw.get("os"),
        "arch": kw.get("arch"),
        "power_default_limit_w": kw.get("power_default_limit_w"),
        "pl_writable_without_elevation": None,
        "desktop_reserve_mib": kw.get("desktop_reserve_mib"),
        # A fixture is constructed, so it has no shell and no privileges to
        # report. Null with a why, never false.
        "elevated": None,
        "sudo_nopasswd": None,
        "privilege_path": None,
        "provenance": {},
    }
    prov = kw.get("provenance") or {}
    for key in FIELD_ORDER:
        rec["provenance"][key] = prov.get(key, {
            "how": "UNKNOWN", "why": "not set by this fixture"}
            if rec.get(key) is None else
            {"how": "FIXTURE: constructed, not measured"})
    rec["provenance"]["pl_writable_without_elevation"] = {
        "how": "UNKNOWN", "why": "fixtures run no power-limit probe"}
    for key in ("elevated", "sudo_nopasswd", "privilege_path"):
        rec["provenance"][key] = {
            "how": "UNKNOWN",
            "why": "a fixture is constructed, so no shell produced it"}
    return rec


_REF_DESKTOP_RESERVE = {"min": 412, "max": 1796, "n": 9, "date": "2026-08-27"}

# The two Windows adapters the Arc fixtures below are built from, written the
# way Get-CimInstance Win32_VideoController actually answers: the trademark
# mark sits inside the name, and AdapterRAM is recorded and used for nothing.
# Both names are Arc and only the model number says which is which. The
# board's 4,293,918,720 is the clamped value a 32-bit field returns for a card
# it cannot describe, which is why windows_video_controllers() reads the name
# and ignores the size.
_WIN_ARC_IGPU = {"Name": "Intel(R) Arc(TM) B390 Graphics",
                 "AdapterCompatibility": "Intel Corporation",
                 "AdapterRAM": 1073741824}
_WIN_ARC_BOARD = {"Name": "Intel(R) Arc(TM) B580 Graphics",
                  "AdapterCompatibility": "Intel Corporation",
                  "AdapterRAM": 4293918720}

# And the AMD pair, which is the same trap under a different brand: a Ryzen
# APU's integrated part is `AMD Radeon(TM) Graphics` with no model number at
# all, and the add-in card beside it is `AMD Radeon(TM) RX 7900 XTX`. Both
# begin `AMD Radeon(TM)`, so the RX and the digits are the whole of what tells
# them apart -- exactly the Arc situation, and the reason step 6 asks the
# board question against _DISCRETE_AMD_RE as well as _DISCRETE_INTEL_RE.
_WIN_RADEON_IGPU = {"Name": "AMD Radeon(TM) Graphics",
                    "AdapterCompatibility": "Advanced Micro Devices, Inc.",
                    "AdapterRAM": 536870912}
_WIN_RADEON_BOARD = {"Name": "AMD Radeon(TM) RX 7900 XTX",
                     "AdapterCompatibility": "Advanced Micro Devices, Inc.",
                     "AdapterRAM": 4293918720}

TOPO_FIXTURES = {}

TOPO_FIXTURES["discrete"] = {
    "expect": "discrete",
    "what": "The reference rig: an RTX 3090 in a 32 GiB desktop. A board of "
            "its own behind PCIe, so the budget is board minus the measured "
            "desktop reserve and rule 13's two ceilings and collapse point all "
            "mean what they have always meant.",
    "inputs": dict(gpu_name="NVIDIA GeForce RTX 3090", board_mib=24576,
                   host_total_mib=32581, drm=[], win_gpus=[], dt_model=None,
                   have_nvidia=True, have_rocm=False),
    "note": "board_total_mib, host_mem_total_mib and compute_cap were read on "
            "this machine on 2026-08-29 (nvidia-smi --query-gpu=name,"
            "memory.total,compute_cap; GlobalMemoryStatusEx). host_reserve_mib "
            "is the single reading taken at the same moment, 32,581 - 17,663. "
            "desktop_reserve_mib is the reference figure carried in "
            "scripts/lib/paths.py's own schema block. Note the ratio: the "
            "board is 75% of host RAM, which is why the size-ratio test is the "
            "LAST resort and the product name outranks it.",
    "machine": _fx("discrete", "NVIDIA GeForce RTX 3090", 24576, 32581, 14918,
                   backend="cuda", driver="596.36", compute_cap="8.6",
                   cuda_arch="86", os="Windows-10-10.0.26200-SP0",
                   arch="AMD64", power_default_limit_w=350.0,
                   ram_channels=2, host_n=2, host_date=_FX_DATE,
                   desktop_reserve_mib=dict(_REF_DESKTOP_RESERVE),
                   provenance={
                       "memory_topology": {
                           "how": "DERIVED: nvidia-smi names the card 'NVIDIA "
                                  "GeForce RTX 3090'. NVIDIA's shared-memory "
                                  "parts are the Tegra/Jetson line and GB10; a "
                                  "GeForce has its own board behind PCIe."},
                       "board_total_mib": {
                           "how": "MEASURED: nvidia-smi "
                                  "--query-gpu=memory.total, on this rig "
                                  "2026-08-29"},
                       "host_mem_total_mib": {
                           "how": "MEASURED: GlobalMemoryStatusEx "
                                  "ullTotalPhys, on this rig 2026-08-29"},
                       "host_reserve_mib": {
                           "how": "MEASURED: MemTotal - MemAvailable, 32,581 - "
                                  "17,663, on this rig 2026-08-29. Not part of "
                                  "the discrete sum; recorded because the same "
                                  "record has to be readable on any topology."},
                       "desktop_reserve_mib": {
                           "how": "MEASURED: the reference figure carried in "
                                  "scripts/lib/paths.py's own schema block -- "
                                  "a 1,669 MiB desktop worst case plus 127 MiB "
                                  "of load-to-load variation, n=9, 2026-08-27"},
                       "spec_bandwidth_gbs": {
                           "how": "UNKNOWN",
                           "why": "no published bandwidth on file for this "
                                  "part, and detect-machine.py measures none"},
                       "igpu_share_limit_mib": {
                           "how": "UNKNOWN",
                           "why": "not applicable on a discrete board"},
                   }),
}

TOPO_FIXTURES["unified"] = {
    "expect": "unified",
    "what": "NVIDIA DGX Spark (GB10): 128 GB of LPDDR5X shared coherently by "
            "the Grace CPU and the Blackwell GPU. nvidia-smi still answers "
            "memory.total and the answer is the whole machine, so "
            "board-minus-reserve would price the model against RAM the OS is "
            "living in. There is no board and nothing spills to host RAM, "
            "because it IS host RAM.",
    "inputs": dict(gpu_name="NVIDIA GB10", board_mib=131072,
                   host_total_mib=131072, drm=[], win_gpus=[],
                   dt_model="NVIDIA DGX Spark", have_nvidia=True,
                   have_rocm=False),
    "note": "CONSTRUCTED from the published specification (128 GB unified, "
            "273 GB/s, sm_121a) -- nobody has run detect-machine.py on a GB10 "
            "yet. board_total_mib and host_mem_total_mib are both the full "
            "131,072 MiB on purpose: a real box reports somewhat less after "
            "the firmware carve-out, and the gap between those two numbers is "
            "exactly the thing that must be MEASURED rather than assumed. "
            "host_reserve_mib 4,096 stands in for the host's standing "
            "footprint and is the field that most changes the answer.",
    "machine": _fx("unified", "NVIDIA GB10", 131072, 131072, 4096,
                   backend="cuda", driver="580.95.05", compute_cap="12.1",
                   cuda_arch="121a-real", spec_bandwidth_gbs=273.0,
                   ram_channels=None,
                   os="Linux-6.11.0-1008-nvidia-aarch64", arch="aarch64",
                   provenance={
                       "memory_topology": {
                           "how": "DERIVED: the GPU is 'NVIDIA GB10' and the "
                                  "device tree names the board 'NVIDIA DGX "
                                  "Spark'. One coherent LPDDR5X pool, no "
                                  "board.",
                           "device_tree_model": "NVIDIA DGX Spark"},
                       "spec_bandwidth_gbs": {
                           "how": "CITED: NVIDIA DGX Spark / GB10 published "
                                  "specification, 273 GB/s"},
                       "board_total_mib": {
                           "how": "FIXTURE: constructed from the 128 GB "
                                  "specification",
                           "warning": "memory_topology is 'unified': this is "
                                      "NOT a discrete board. Subtracting a "
                                      "desktop reserve from it prices the "
                                      "model against memory the OS is already "
                                      "using."},
                       "host_reserve_mib": {
                           "how": "FIXTURE: constructed. A real box measures "
                                  "this with detect-machine.py --desktop-state"},
                       "cuda_arch": {
                           "how": "FIXTURE: -DCMAKE_CUDA_ARCHITECTURES="
                                  "121a-real, which is what keeps "
                                  "MMVQ_PARAMETERS_GB10; native, 120, 120f "
                                  "and a bare 121 do not"},
                       "desktop_reserve_mib": {
                           "how": "UNKNOWN",
                           "why": "not applicable on a unified box: there is "
                                  "no board VRAM for a desktop to hold "
                                  "separately, and the host's standing "
                                  "footprint is host_reserve_mib"},
                   }),
}

TOPO_FIXTURES["shared-igpu"] = {
    "expect": "shared-igpu",
    "what": "An Intel integrated GPU (Lunar Lake class) mapping a share of a "
            "32 GiB LPDDR5X system. Same pool as unified, but the driver caps "
            "how much of it the GPU may map, and that cap is a second ceiling "
            "that has to be READ rather than assumed -- MemTotal over-promises "
            "by about 2x.",
    "inputs": dict(gpu_name=None, board_mib=None, host_total_mib=32768,
                   drm=[{"card": "card0", "vendor_id": "0x8086",
                         "vendor": "Intel", "device_id": "0x64a0",
                         "driver": "xe", "pci_address": "0000:00:02.0",
                         "on_root_bus": True,
                         "device_local_memory_bytes": None,
                         "device_local_memory_source": None,
                         "gtt_total_bytes": None}],
                   win_gpus=[], dt_model=None, have_nvidia=False,
                   have_rocm=False),
    "note": "CONSTRUCTED. The /sys/class/drm shape is the real one for an "
            "Intel iGPU under the xe driver: vendor 0x8086, root bus at "
            "0000:00:02.0, no lmem_total_bytes. igpu_share_limit_mib 16,384 is "
            "the half-of-RAM cap as clinfo reports it; the sibling fixture "
            "'shared-igpu-unmeasured' is the same box with that field null, to "
            "show the fit REFUSING rather than assuming MemTotal.",
    "machine": _fx("shared-igpu", "Intel integrated GPU (xe, 0000:00:02.0)",
                   None, 32768, 3072, backend="vulkan", ram_channels=2,
                   igpu_share_limit_mib=16384, spec_bandwidth_gbs=136.5,
                   os="Linux-6.14.0-generic-x86_64", arch="x86_64",
                   provenance={
                       "memory_topology": {
                           "how": "DERIVED: Intel card0 sits on the root bus "
                                  "at 0000:00:02.0 under xe and publishes no "
                                  "device-local memory."},
                       "board_total_mib": {
                           "how": "UNKNOWN",
                           "why": "an integrated GPU has no board; "
                                  "/sys/class/drm publishes no device-local "
                                  "memory for it"},
                       "igpu_share_limit_mib": {
                           "how": "CITED: clinfo CL_DEVICE_GLOBAL_MEM_SIZE, "
                                  "16 GiB -- half of the 32 GiB system"},
                       "spec_bandwidth_gbs": {
                           "how": "DERIVED: 2 channels x 8 B x 8533 MT/s / "
                                  "1000 = 136.5 GB/s, the memory controller's "
                                  "theoretical peak, not a measurement"},
                       "desktop_reserve_mib": {
                           "how": "UNKNOWN",
                           "why": "not applicable: there is no board VRAM. "
                                  "The desktop's footprint is inside "
                                  "host_reserve_mib"},
                   }),
}

TOPO_FIXTURES["shared-igpu-unmeasured"] = {
    "expect": "shared-igpu",
    "what": "The shared-igpu box with the driver's share cap UNREAD. Present "
            "so the refusal is demonstrable: neither i915 nor xe publishes the "
            "cap to an unprivileged process, and assuming MemTotal would "
            "over-promise by about 2x.",
    "inputs": TOPO_FIXTURES["shared-igpu"]["inputs"],
    "note": "Identical to 'shared-igpu' except igpu_share_limit_mib is null. "
            "The fit must report UNKNOWN and name the command that answers it.",
    "machine": _fx("shared-igpu", "Intel integrated GPU (xe, 0000:00:02.0)",
                   None, 32768, 3072, backend="vulkan", ram_channels=2,
                   igpu_share_limit_mib=None, spec_bandwidth_gbs=136.5,
                   os="Linux-6.14.0-generic-x86_64", arch="x86_64",
                   provenance={
                       "memory_topology": {
                           "how": "DERIVED: Intel card0 sits on the root bus "
                                  "at 0000:00:02.0 under xe and publishes no "
                                  "device-local memory."},
                       "board_total_mib": {
                           "how": "UNKNOWN",
                           "why": "an integrated GPU has no board"},
                       "igpu_share_limit_mib": {
                           "how": "UNKNOWN",
                           "why": "no driver here publishes the mappable share "
                                  "to an unprivileged process. Read it with "
                                  "`clinfo | grep -i 'global memory size'` or "
                                  "from OpenVINO's GPU_DEVICE_TOTAL_MEM_SIZE, "
                                  "then pass --igpu-share-limit-mib N"},
                   }),
}

TOPO_FIXTURES["shared-igpu-arc"] = {
    "expect": "shared-igpu",
    "what": "A Core Ultra box on Windows: the Arc B390-class iGPU named in "
            "REPORT-SPEC.md 7's card roster, mapping a share of 64 GiB of "
            "LPDDR5X. There is no /sys/class/drm to read here and no Intel "
            "vendor tool to ask, so the adapter NAME carries the whole "
            "classification -- and the name Windows returns has a trademark "
            "mark sitting in the middle of it.",
    "inputs": dict(gpu_name=None, board_mib=0, host_total_mib=65536, drm=[],
                   win_gpus=[dict(_WIN_ARC_IGPU)], dt_model=None,
                   have_nvidia=False, have_rocm=False),
    "note": "CONSTRUCTED. board_mib is 0 because no vendor tool answers on "
            "this box, and that 0 is why the fixture is here: until "
            "2026-08-30 the Arc branch of _IGPU_NAME_RE required `Arc "
            "<digits> Graphics` with a plain space, so it missed `Arc(TM) "
            "B390 Graphics` -- and every other Arc name Windows returns -- "
            "and the falsy 0 then carried the box past the size-ratio test as "
            "well, onto the CPU-only fallback. The profile that came out said "
            "memory_topology 'system': a machine with a GPU described as a "
            "machine without one, priced against the wrong pool, with nothing "
            "in the artefact looking wrong.",
    "machine": _fx("shared-igpu", "Intel(R) Arc(TM) B390 Graphics", 0, 65536,
                   5120, backend="openvino", ram_channels=2,
                   igpu_share_limit_mib=32768, spec_bandwidth_gbs=153.6,
                   os="Windows-10-10.0.26200-SP0", arch="AMD64",
                   provenance={
                       "memory_topology": {
                           "how": "DERIVED: Win32_VideoController names "
                                  "'Intel(R) Arc(TM) B390 Graphics', an "
                                  "integrated Arc, and no adapter here is an "
                                  "Intel add-in board."},
                       "gpu_name": {
                           "how": "FIXTURE: the Win32_VideoController name. "
                                  "detect-machine.py fills gpu_name from "
                                  "nvidia-smi or rocm-smi only, so a real box "
                                  "of this shape records gpu_name null and "
                                  "carries this string in the topology "
                                  "evidence instead."},
                       "board_total_mib": {
                           "how": "DERIVED: " + _BOARD_ZERO_NO_TOOL,
                           "note": _BOARD_ZERO_ON_SHARED},
                       "igpu_share_limit_mib": {
                           "how": "CITED: dxdiag 'Shared Memory' / OpenVINO "
                                  "GPU_DEVICE_TOTAL_MEM_SIZE, 32 GiB -- half "
                                  "of the 64 GiB system, which is where WDDM "
                                  "leaves it by default"},
                       "spec_bandwidth_gbs": {
                           "how": "DERIVED: 2 channels x 8 B x 9600 MT/s / "
                                  "1000 = 153.6 GB/s (LPDDR5X-9600), the "
                                  "memory controller's theoretical peak and "
                                  "not a measurement. REPORT-SPEC.md 7 "
                                  "attaches the caveat this row must carry: "
                                  "one channel, or slower RAM, halves it."},
                       "desktop_reserve_mib": {
                           "how": "UNKNOWN",
                           "why": "not applicable: there is no board VRAM. "
                                  "The desktop's footprint is inside "
                                  "host_reserve_mib"},
                   }),
}

TOPO_FIXTURES["discrete-arc"] = {
    "expect": "discrete",
    "what": "The same Windows box with an Intel add-in board in it: an Arc "
            "B580 beside the Core Ultra's integrated Arc B390. Both adapters "
            "are Arc-branded, so the board is told from the iGPU by its MODEL "
            "NUMBER and by nothing else -- and the board is the part the "
            "campaign would run on.",
    "inputs": dict(gpu_name=None, board_mib=0, host_total_mib=65536, drm=[],
                   win_gpus=[dict(_WIN_ARC_IGPU), dict(_WIN_ARC_BOARD)],
                   dt_model=None, have_nvidia=False, have_rocm=False),
    "note": "CONSTRUCTED, and the second adapter is the whole point of it: "
            "both names are Arc, so a classifier that asks 'is any of these "
            "an iGPU?' first answers shared-igpu and prices an add-in board "
            "against 64 GiB of host RAM. The board question is asked first "
            "instead. board_total_mib stays 0 because no Intel vendor tool "
            "answers on Windows, which leaves this box with its topology "
            "KNOWN and its board size NOT: check-request.py:memory_plan() "
            "refuses on exactly that pair rather than passing, and the "
            "classifier verdict beside it names the flag that closes the "
            "gap -- --board-total-mib N, one command from a fit rather than "
            "a day spent inside a wrong one. That board_total_mib provenance "
            "is _BOARD_ZERO_NO_TOOL and _BOARD_ZERO_ON_DISCRETE verbatim, the "
            "two strings detect() and _measure_topology() emit on a real box "
            "of this shape, so what this artefact asserts cannot drift from "
            "what the script writes.",
    "machine": _fx("discrete", "Intel(R) Arc(TM) B580 Graphics", 0, 65536,
                   5120, backend="openvino", ram_channels=2,
                   os="Windows-10-10.0.26200-SP0", arch="AMD64",
                   provenance={
                       "memory_topology": {
                           "how": "DERIVED: Win32_VideoController names "
                                  "'Intel(R) Arc(TM) B580 Graphics', a "
                                  "Battlemage desktop card, beside the "
                                  "integrated 'Intel(R) Arc(TM) B390 "
                                  "Graphics'. The board is the discrete part "
                                  "and is the one a campaign runs on."},
                       "gpu_name": {
                           "how": "FIXTURE: the Win32_VideoController name of "
                                  "the board. detect-machine.py fills "
                                  "gpu_name from nvidia-smi or rocm-smi only, "
                                  "so a real box of this shape records "
                                  "gpu_name null."},
                       "board_total_mib": {
                           "how": "DERIVED: " + _BOARD_ZERO_NO_TOOL,
                           "warning": _BOARD_ZERO_ON_DISCRETE},
                       "igpu_share_limit_mib": {
                           "how": "UNKNOWN",
                           "why": "not applicable on a discrete board"},
                       "spec_bandwidth_gbs": {
                           "how": "UNKNOWN",
                           "why": "no published bandwidth on file for this "
                                  "part, and detect-machine.py measures none. "
                                  "Rule 10's decode estimate needs one: pass "
                                  "--spec-bandwidth-gbs N --bandwidth-source "
                                  "before publishing a scaled row for it"},
                       "desktop_reserve_mib": {
                           "how": "UNKNOWN",
                           "why": "reading board VRAM already in use needs a "
                                  "vendor tool that reports it, and "
                                  "nvidia-smi is the only one this script "
                                  "has. On an Intel board the reserve is "
                                  "unmeasured, so the fit refuses rather than "
                                  "fencing against a constant (rule 14)"},
                   }),
}

TOPO_FIXTURES["shared-igpu-radeon"] = {
    "expect": "shared-igpu",
    "what": "A Ryzen box on Windows with nothing in the PCIe slot: the APU's "
            "integrated Radeon, mapping a share of 32 GiB of DDR5. rocm-smi "
            "is not on PATH here, which is the ordinary state of a Windows "
            "AMD box, so the adapter NAME is the whole of the evidence -- and "
            "the name has a trademark mark where the pattern wanted a space.",
    "inputs": dict(gpu_name=None, board_mib=0, host_total_mib=32768, drm=[],
                   win_gpus=[dict(_WIN_RADEON_IGPU)], dt_model=None,
                   have_nvidia=False, have_rocm=False),
    "note": "CONSTRUCTED. Until 2026-08-30 the iGPU pattern read `radeon\\s+"
            "graphics`, which does not match `AMD Radeon(TM) Graphics`, so "
            "this box classified 'system' -- a GPU box profiled as a CPU box, "
            "priced against the wrong pool, with nothing in the artefact "
            "looking wrong. igpu_share_limit_mib is null on purpose: no "
            "driver here publishes the mappable share to an unprivileged "
            "process, MemTotal over-promises it by about 2x, and the fit is "
            "meant to REFUSE until the number is read rather than assume one.",
    "machine": _fx("shared-igpu", "AMD Radeon(TM) Graphics", 0, 32768, 3072,
                   backend="vulkan", ram_channels=2, spec_bandwidth_gbs=89.6,
                   os="Windows-10-10.0.26200-SP0", arch="AMD64",
                   provenance={
                       "memory_topology": {
                           "how": "DERIVED: Win32_VideoController names 'AMD "
                                  "Radeon(TM) Graphics', an APU's integrated "
                                  "part, and no adapter here is an Intel or "
                                  "AMD add-in board."},
                       "gpu_name": {
                           "how": "FIXTURE: the Win32_VideoController name. "
                                  "detect-machine.py fills gpu_name from "
                                  "nvidia-smi or rocm-smi only, so a real box "
                                  "of this shape records gpu_name null and "
                                  "carries this string in the topology "
                                  "evidence instead."},
                       "board_total_mib": {
                           "how": "DERIVED: " + _BOARD_ZERO_NO_TOOL,
                           "note": _BOARD_ZERO_ON_SHARED},
                       "igpu_share_limit_mib": {
                           "how": "UNKNOWN",
                           "why": "no driver here publishes the mappable "
                                  "share to an unprivileged process. Read it "
                                  "from dxdiag's 'Shared Memory' or from "
                                  "`clinfo` CL_DEVICE_GLOBAL_MEM_SIZE, then "
                                  "pass --igpu-share-limit-mib N"},
                       "spec_bandwidth_gbs": {
                           "how": "DERIVED: 2 channels x 8 B x 5600 MT/s / "
                                  "1000 = 89.6 GB/s (DDR5-5600), the memory "
                                  "controller's theoretical peak and not a "
                                  "measurement. One channel, or slower RAM, "
                                  "halves it."},
                       "desktop_reserve_mib": {
                           "how": "UNKNOWN",
                           "why": "not applicable: there is no board VRAM. "
                                  "The desktop's footprint is inside "
                                  "host_reserve_mib"},
                   }),
}

TOPO_FIXTURES["discrete-radeon"] = {
    "expect": "discrete",
    "what": "The Ryzen desktop with a card in the slot: an RX 7900 XTX beside "
            "the APU's integrated Radeon, 64 GiB of DDR5, and no rocm-smi. "
            "Both adapters are Radeon-branded, so the board is told from the "
            "iGPU by `RX` and its model number and by nothing else -- and the "
            "board is the part the campaign would run on.",
    "inputs": dict(gpu_name=None, board_mib=0, host_total_mib=65536, drm=[],
                   win_gpus=[dict(_WIN_RADEON_IGPU), dict(_WIN_RADEON_BOARD)],
                   dt_model=None, have_nvidia=False, have_rocm=False),
    "note": "CONSTRUCTED, and it pins the AMD half of step 6's ordering. On "
            "2026-08-30 the iGPU pattern was widened to match `AMD Radeon(TM) "
            "Graphics` while the board question was still asked against the "
            "Intel pattern alone, so this box -- every Ryzen desktop with a "
            "Radeon card in it -- answered shared-igpu and named the APU's "
            "iGPU on a machine whose campaign runs on the 24 GiB board. Both "
            "discrete patterns are consulted now. board_total_mib stays 0 "
            "because no AMD vendor tool answers here, which leaves the "
            "topology KNOWN and the board size NOT, and "
            "check-request.py:memory_plan() refuses on that pair rather than "
            "passing: --board-total-mib 24576 closes it in one command.",
    "machine": _fx("discrete", "AMD Radeon(TM) RX 7900 XTX", 0, 65536, 5120,
                   backend="vulkan", ram_channels=2,
                   os="Windows-10-10.0.26200-SP0", arch="AMD64",
                   provenance={
                       "memory_topology": {
                           "how": "DERIVED: Win32_VideoController names 'AMD "
                                  "Radeon(TM) RX 7900 XTX', an add-in board, "
                                  "beside the APU's integrated 'AMD "
                                  "Radeon(TM) Graphics'. The board is the "
                                  "discrete part and is the one a campaign "
                                  "runs on."},
                       "gpu_name": {
                           "how": "FIXTURE: the Win32_VideoController name of "
                                  "the board. detect-machine.py fills "
                                  "gpu_name from nvidia-smi or rocm-smi only, "
                                  "so a real box of this shape records "
                                  "gpu_name null."},
                       "board_total_mib": {
                           "how": "DERIVED: " + _BOARD_ZERO_NO_TOOL,
                           "warning": _BOARD_ZERO_ON_DISCRETE},
                       "igpu_share_limit_mib": {
                           "how": "UNKNOWN",
                           "why": "not applicable on a discrete board"},
                       "spec_bandwidth_gbs": {
                           "how": "UNKNOWN",
                           "why": "no published bandwidth on file for this "
                                  "part, and detect-machine.py measures none. "
                                  "Rule 10's decode estimate needs one: pass "
                                  "--spec-bandwidth-gbs N --bandwidth-source "
                                  "before publishing a scaled row for it"},
                       "desktop_reserve_mib": {
                           "how": "UNKNOWN",
                           "why": "reading board VRAM already in use needs a "
                                  "vendor tool that reports it, and "
                                  "nvidia-smi is the only one this script "
                                  "has. On a Radeon board with no rocm-smi "
                                  "the reserve is unmeasured, so the fit "
                                  "refuses rather than fencing against a "
                                  "constant (rule 14)"},
                   }),
}

TOPO_FIXTURES["system"] = {
    "expect": "system",
    "what": "A dual-socket Xeon with no GPU at all: 512 GiB of DDR5 across 16 "
            "channels. There is no GPU pool, weights are mmapped, and rule "
            "13's ceilings do not describe anything here.",
    "inputs": dict(gpu_name=None, board_mib=0, host_total_mib=524288, drm=[],
                   win_gpus=[], dt_model=None, have_nvidia=False,
                   have_rocm=False),
    "note": "CONSTRUCTED. 16 channels x 8 B x 4800 MT/s = 614.4 GB/s is the "
            "controllers' theoretical peak; rule 10's dual-socket constant "
            "(~0.35) exists because the measured figure is nothing like it.",
    "machine": _fx("system", None, 0, 524288, 8192, backend="cpu",
                   ram_channels=16, spec_bandwidth_gbs=614.4,
                   os="Linux-6.8.0-generic-x86_64", arch="x86_64",
                   provenance={
                       "memory_topology": {
                           "how": "DERIVED: no GPU vendor tool answered, "
                                  "/sys/class/drm lists no card"},
                       "board_total_mib": {
                           "how": "DERIVED: " + _BOARD_ZERO_NO_TOOL,
                           "note": _BOARD_ZERO_ON_SYSTEM},
                       "spec_bandwidth_gbs": {
                           "how": "DERIVED: 16 channels x 8 B x 4800 MT/s / "
                                  "1000 = 614.4 GB/s (theoretical peak)"},
                       "desktop_reserve_mib": {
                           "how": "UNKNOWN",
                           "why": "no GPU, so no board VRAM and no desktop "
                                  "reserve to measure"},
                   }),
}

TOPO_FIXTURES["unknown"] = {
    "expect": None,
    "what": "An accelerator this script has never heard of, reporting 96 GiB "
            "against a 102 GiB host. 94% of the host's memory is not a board; "
            "it is one pool counted twice. The classifier refuses, and every "
            "fit downstream refuses with it.",
    "inputs": dict(gpu_name="Acme XPU 96G", board_mib=98304,
                   host_total_mib=104448, drm=[], win_gpus=[], dt_model=None,
                   have_nvidia=False, have_rocm=False),
    "note": "CONSTRUCTED, and the point of it is the refusal: an UNPROVEN fit "
            "is a plan, a wrong PASS is a wasted day.",
    "machine": _fx(None, "Acme XPU 96G", 98304, 104448, None,
                   backend=None, os="Linux-6.8.0-generic-x86_64",
                   arch="x86_64",
                   provenance={
                       "memory_topology": {
                           "how": "UNKNOWN",
                           "why": "the GPU reports 98,304 MiB of memory "
                                  "against 104,448 MiB of system RAM -- 94% "
                                  "of it. Too large a share to read as a "
                                  "discrete board. Pass --topology.",
                           "board_over_host_ratio": 0.941},
                   }),
}


# Every fixture's memory_topology provenance is the classifier's OWN sentence
# for those inputs, taken from classify_topology() here rather than written out
# again beside it. A hand-copied paraphrase is the same defect as a hand-copied
# board_total_mib provenance: it reads as the artefact a real box emits while
# saying something the code does not, and it goes on saying it after the branch
# it describes has been rewritten -- which is what both Arc fixtures did inside
# one day of being written. What is NOT reproduced here is the evidence block a
# real machine.json carries beside the sentence (drm_cards,
# windows_video_controllers, board_over_host_ratio and the rest of `ev`); the
# "inputs" entry beside each fixture is that evidence, in the form the
# classifier reads it.
for _name in TOPO_FIXTURES:
    _prov = TOPO_FIXTURES[_name]["machine"]["provenance"]["memory_topology"]
    _verdict = classify_topology(**TOPO_FIXTURES[_name]["inputs"])
    if _verdict[0]:
        _prov["how"] = "DERIVED: " + _verdict[1]
        _prov.pop("why", None)
    else:
        _prov["how"] = "UNKNOWN"
        _prov["why"] = _verdict[1]


def self_test(out):
    """Run classify_topology over every fixture and print the decision table."""
    out.write("\ntopology classifier self-test  (%d fixtures)\n\n"
              % len(TOPO_FIXTURES))
    bad = 0
    for name in TOPO_FIXTURES:
        fx = TOPO_FIXTURES[name]
        got, how, _ = classify_topology(**fx["inputs"])
        ok = (got == fx["expect"])
        bad += 0 if ok else 1
        out.write("  %-24s expect %-12s got %-12s %s\n"
                  % (name, fx["expect"] or "REFUSE", got or "REFUSE",
                     "ok" if ok else "*** MISMATCH ***"))
        # The verdict and the artefact beside it are two different objects,
        # and the artefact is the one a planner gets pointed at. A fixture
        # whose machine.json disagrees with its own classifier verdict is a
        # decision table that documents a decision nothing makes.
        written = fx["machine"].get("memory_topology")
        if written != got:
            bad += 1
            out.write("      *** the machine.json beside it records "
                      "memory_topology %r ***\n" % written)
        for chunk in _wrap_text(how, 74):
            out.write("      %s\n" % chunk)
        out.write("\n")
    out.write("  %d fixture(s), %d mismatch(es)\n\n"
              % (len(TOPO_FIXTURES), bad))
    return 1 if bad else 0


def _wrap_text(text, width):
    words, line, lines = (text or "").split(), "", []
    for w in words:
        if line and len(line) + 1 + len(w) > width:
            lines.append(line)
            line = w
        else:
            line = (line + " " + w).strip()
    if line:
        lines.append(line)
    return lines or [""]


def write_fixtures(out):
    """results/fixture-topo-*/machine.json, so the fit can be run on each."""
    root = os.path.join(paths.repo_root(), "results")
    made = []
    for name in TOPO_FIXTURES:
        fx = TOPO_FIXTURES[name]
        slug = FIXTURE_PREFIX + name
        d = os.path.join(root, slug)
        if os.path.isfile(os.path.join(d, "campaign.md")):
            out.write("REFUSED %s: it has a campaign.md, so it is a real "
                      "campaign\n" % slug)
            continue
        if not os.path.isdir(d):
            os.makedirs(d)
        rec = dict(fx["machine"])
        rec["slug"] = slug
        rec["_fixture_note"] = fx["note"]
        with open(os.path.join(d, "machine.json"), "w", encoding="utf-8",
                  newline="\n") as fh:
            json.dump(rec, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
        with open(os.path.join(d, "FIXTURE.md"), "w", encoding="utf-8",
                  newline="\n") as fh:
            fh.write("# %s -- FIXTURE, not a campaign\n\n%s\n\n%s\n\n"
                     "Written by `python scripts/detect-machine.py "
                     "--write-fixtures`. Remove with `--clean-fixtures`.\n"
                     % (slug, fx["what"], fx["note"]))
        # A fit table needs a model profile as well as a machine. Borrow one
        # from whatever fixture campaign already has a REAL header read, rather
        # than inventing a second set of model numbers here.
        n_models = 0
        for src in sorted(glob.glob(os.path.join(
                root, "fixture-qwen38-27b", "model-*.json"))):
            shutil.copy2(src, os.path.join(d, os.path.basename(src)))
            n_models += 1
        out.write("wrote results/%s/  (machine.json%s)\n"
                  % (slug, ", %d model-*.json copied from "
                           "results/fixture-qwen38-27b/" % n_models
                     if n_models else "; no model profile -- run "
                     "scripts/fixtures/plan-campaign-fixtures.py --write "
                     "--only fixture-qwen38-27b first, then re-run this"))
        made.append(slug)
    return made


def clean_fixtures(out):
    root = os.path.join(paths.repo_root(), "results")
    for name in TOPO_FIXTURES:
        slug = FIXTURE_PREFIX + name
        d = os.path.join(root, slug)
        if not os.path.isdir(d):
            continue
        if not os.path.isfile(os.path.join(d, "FIXTURE.md")):
            out.write("REFUSED %s: no FIXTURE.md, so this script did not write "
                      "it\n" % slug)
            continue
        shutil.rmtree(d)
        out.write("removed results/%s/\n" % slug)


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
    ap.add_argument("--topology", choices=TOPOLOGIES,
                    help="state the memory topology when the evidence here "
                         "cannot settle it (recorded as CITED). It decides "
                         "WHICH fit arithmetic is right: discrete subtracts a "
                         "desktop reserve from a board, the other three price "
                         "against system memory.")
    ap.add_argument("--igpu-share-limit-mib", type=int, metavar="N",
                    help="how much system RAM the driver will let an "
                         "integrated GPU map (recorded as CITED). Read it with "
                         "`clinfo | grep -i 'global memory size'`; it is NOT "
                         "MemTotal, and assuming MemTotal over-promises by ~2x")
    ap.add_argument("--spec-bandwidth-gbs", type=float, metavar="GBS",
                    help="published memory bandwidth in GB/s, for rule 10's "
                         "decode estimate (recorded as CITED; requires "
                         "--bandwidth-source)")
    ap.add_argument("--bandwidth-source", metavar="TEXT",
                    help="where --spec-bandwidth-gbs came from. Rule 1: a "
                         "number without a provenance is refused, not recorded")
    ap.add_argument("--self-test", action="store_true",
                    help="run the topology classifier against every recorded "
                         "topology fixture and print the decision table; "
                         "measures nothing, writes nothing")
    ap.add_argument("--write-fixtures", action="store_true",
                    help="write results/fixture-topo-*/machine.json for every "
                         "recorded topology fixture, so the planner and the "
                         "Stage-0 gate can be exercised on each")
    ap.add_argument("--clean-fixtures", action="store_true",
                    help="remove exactly the fixture campaigns --write-"
                         "fixtures created, and nothing else")
    ap.add_argument("--no-pl-test", action="store_true",
                    help="skip the power-limit writability probe (it sets the "
                         "limit to the value already in force)")
    args = ap.parse_args(argv)

    # progress on stderr so `--json | jq` stays clean
    log = (lambda msg: sys.stderr.write(msg + "\n")) if args.json else print

    # These three measure nothing and touch no card, so they run before every
    # check below and never acquire anything.
    if args.clean_fixtures or args.write_fixtures or args.self_test:
        rc = 0
        if args.clean_fixtures:
            clean_fixtures(sys.stdout)
        if args.write_fixtures:
            made = write_fixtures(sys.stdout)
            if made:
                print("\nrun the fit on each:")
                for slug in made:
                    print("  python scripts/plan-campaign.py --slug %s "
                          "--no-network" % slug)
        if args.self_test:
            rc = self_test(sys.stdout)
        return rc

    if args.bandwidth_source and args.spec_bandwidth_gbs is None:
        ap.error("--bandwidth-source without --spec-bandwidth-gbs: there is no "
                 "number for it to be the source of")
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
