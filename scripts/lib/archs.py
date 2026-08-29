#!/usr/bin/env python3
"""What THIS llama.cpp build can actually load — read out of the binary.

    python scripts/lib/archs.py            # what this build supports, and why
    python scripts/lib/archs.py --json     # the same, machine-readable

WHY THIS FILE EXISTS. `scripts/check-request.py` ran six checks — SLUG,
LISTING, QUANTS, ACCESS, FIT, DISK — and not one of them read the model's
declared architecture. A coverage audit of a 44-model catalogue found the hole
with a real repo:

    $ python scripts/check-request.py Abiray/ZAYA1-8B-GGUF
      [1/6] SLUG     OK      zaya1-8b
      [2/6] LISTING  OK      6 GGUF candidates (35.96 GiB total)
      [4/6] ACCESS   OK      range request served real bytes  magic GGUF ok

Five green lights on a model that cannot be loaded at all: every ZAYA1 GGUF on
the Hub declares `general.architecture = "zaya"`, no llama.cpp build here has a
`zaya` entry in `LLM_ARCH_NAMES`, and the load aborts with
`unknown model architecture: 'zaya'`. The cost of finding that out at Stage 1
instead of Stage 0 is about 9 GiB of download and a probe slot — spent after
rule 27 has closed the interview and made asking illegal.

WHY IT READS BYTES INSTEAD OF RUNNING SOMETHING. The obvious implementation is
to ask the binary, or just attempt the load. Neither is available here.
`bin/llama.cpp/INSTALL.json` records what is installed:

    {"tag":"d7bd3bf","flavor":"cuda","os":"linux","built_from_source":true,
     "cuda_arch":"86","host":"wsl2-ubuntu-24.04"}

Linux ELF objects, built under WSL2, in a checkout that agents drive from the
Windows side — `paths._unusable()` exists to refuse to hand them to a caller
for exactly this reason. A Stage-0 gate that only answers on the Linux half of
one machine is not a gate. So this module never execs anything: it opens the
shared library and reads the string table.

WHAT IT READS, AND THE TWO WAYS IT IS WRONG. Both rosters are
`static const std::map<enum, const char *>` initialisers, and the compiler lays
their string literals down as one contiguous NUL-separated run in `.rodata`:

    libllama.so   LLM_ARCH_NAMES        "clip\\0llama\\0llama4\\0deci\\0falcon\\0..."
    libmtmd.so    PROJECTOR_TYPE_NAMES  "ldp\\0ldpv2\\0resampler\\0adapter\\0..."

Nothing points at those literals — the maps are built by code, with the
pointers materialised by `lea`, and `.rela.dyn` holds no relocation into the
run — so the pointer array cannot be walked and the run itself is the only
handle. It is found by anchoring on names that have been in llama.cpp for
years (`llama`, `falcon`, `gpt2`, `mpt`, `bloom`, ...) and expanding in both
directions while each NUL-separated token still looks like a name.

That scan can be wrong in two ways, and they are NOT symmetric:

  * too LONG — a neighbouring literal gets swept in. Harm: a GGUF declaring
    `general.architecture = "mtmd_get_cap_from_file"` would be waved through.
    No such GGUF exists. This is the cheap failure.
  * too SHORT — real architectures fall off the list. Harm: the gate rejects a
    model this build loads fine and the campaign re-picks for nothing. This is
    the expensive failure, and it is SILENT: a short list looks exactly like a
    correct one.

So every guard here is tuned to make "short" impossible to mistake for
"correct": a floor on the count, a requirement that most anchors survive inside
the run, and — when either fails — `RosterUnknown` rather than a partial set.
UNKNOWN is a supported answer. A short list is not. It is also why
`supported_archs()` RAISES instead of returning `set()`: `name in set()` is
False for every model on the Hub, so a caller who forgot to handle the unknown
case would reject everything and never see a traceback.

THE TAIL-MERGE TRAP, which cost this module its first draft. GNU ld merges
mergeable string literals by SUFFIX, so any roster entry that happens to be the
tail of a longer literal never gets its own copy. In the installed build that
silently removes five real architectures from the contiguous run:

    qwen2   lives inside  rwkv6qwen2      bert   lives inside  modern-bert
    rwkv7   lives inside  arwkv7          qwen   lives inside  deepseek-r1-qwen
    glm4    lives inside  chatglm4

`qwen2` is one of the most common architectures on the Hub. A gate that
rejected it would be worse than no gate. They are recovered by a second,
independent signal (rule 4): the C++ ABI puts a `llama_model_<arch>` class name
in the mangled vtable/typeinfo symbols, and a name is only restored when BOTH
agree — a `_ZTV…llama_model_<n>` symbol exists AND the literal is found in
`.rodata` as the tail of another *name-shaped* string. The container test is
what keeps the junk out: `base` is only ever the tail of `%s.rope.freq_base`,
and `openai_moe` only of the RTTI string `22llama_model_openai_moe`, so
neither is restored. Every restored name is listed separately, in the CLI and
in ARCHS.json, so the recovery is auditable rather than magic.

CACHING. `<lib dir>/ARCHS.json`, keyed by `INSTALL.json`'s tag AND the size of
the file that was scanned, so a rebuild or a swapped binary invalidates it.
Absent, stale or corrupt: rescan. Unwritable directory: skip the cache and say
so. The scan costs ~7 MB of reads and about a tenth of a second, so the cache
is a courtesy, never a dependency.

Stdlib only. Python 3.8+. Linux, macOS and Windows — including Windows reading
Linux ELF objects it cannot execute, which is the case this repository is in.
"""
import argparse
import glob
import itertools
import json
import os
import re
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import paths  # noqa: E402


# ---------------------------------------------------------------------------
# what a name looks like
# ---------------------------------------------------------------------------

# Every architecture and projector name llama.cpp has shipped is lower case and
# drawn from this set. The dot is here for the projectors -- `qwen2.5vl_merger`
# and `qwen2.5o` are real PROJECTOR_TYPE_NAMES entries -- and costs nothing on
# the arch side, because that table is terminated by "(unknown)", whose
# parenthesis is not in the set and stops the walk before the GGUF metadata
# keys ("general.type", "general.architecture", ...) that follow it.
_NAME = re.compile(rb"[a-z0-9][a-z0-9._+-]*\Z")

# A token this long is not a name, it is the neighbouring literal: the two that
# actually abut these tables in the installed build are
# `llama_adapter_lora_init` (23) and `mtmd_get_cap_from_file` (22). The longest
# real names are 16 (`gemma4-assistant`, `wavtokenizer-dec`, `pockettts_spkenc`),
# so 20 buys four characters of headroom. If a future name exceeds it the run
# splits there, the count drops, and the floor below turns that into UNKNOWN --
# the safe direction.
_MIN_LEN, _MAX_LEN = 2, 20

# llama.cpp's spellings of "I do not recognise this". `(unknown)` is
# LLM_ARCH_UNKNOWN's own name and terminates the arch table (its parenthesis
# also stops the walk); `unknown` is an unrelated literal that happens to sit
# immediately before `clip`. Neither is a loadable architecture, and treating
# either as one would green-light a GGUF whose metadata is broken in exactly
# the way this check exists to catch.
_SENTINELS = frozenset((b"unknown", b"(unknown)", b"none", b"unspecified"))

# Mangled C++ names: _ZTV / _ZTI / _ZTS, optionally nested (N...E), then a
# decimal length and the identifier. The length prefix is load-bearing --
# without it `_ZTVN22llama_model_hunyuan_vl5graphE` reads as the class
# "hunyuan_vl5graph".
_MANGLED = re.compile(rb"_ZT[VIS]N?(\d{1,4})([A-Za-z_])")


class _Table(object):
    def __init__(self, kind, symbol, stem, anchors, floor, klass, error,
                 error_note):
        self.kind = kind
        self.symbol = symbol          # the C++ identifier, for the citation
        self.stem = stem              # library basename to look for
        self.anchors = tuple(anchors)
        self.floor = floor
        self.klass = klass            # mangled class prefix, or None
        self.error = error            # the load-failure literal, verbatim
        self.error_note = error_note


# The anchors are deliberately ANCIENT names, not interesting ones. An anchor's
# only job is to find the run, and a name added last month is a name that can
# be removed next month -- at which point the anchor stops matching and a
# perfectly good scan starts reporting UNKNOWN for no reason.
TABLES = {
    "archs": _Table(
        kind="archs",
        symbol="LLM_ARCH_NAMES",
        stem="libllama",
        anchors=(b"llama", b"falcon", b"gpt2", b"mpt", b"bloom", b"gemma",
                 b"phi2", b"qwen2moe", b"starcoder", b"mamba"),
        # 143 in the contiguous run of the installed build, and every llama.cpp
        # for years has had well over a hundred. 40 is far below any plausible
        # real roster and far above what a broken scan returns.
        floor=40,
        klass=b"llama_model_",
        error=b"unknown model architecture: '",
        error_note="llama.cpp composes this with the arch and aborts the load",
    ),
    "projectors": _Table(
        kind="projectors",
        symbol="PROJECTOR_TYPE_NAMES",
        stem="libmtmd",
        anchors=(b"ldp", b"ldpv2", b"resampler", b"pixtral", b"idefics3",
                 b"internvl", b"ultravox", b"qwen2vl_merger"),
        floor=20,
        # PROJECTOR_TYPE is a plain enum with no per-type class, so there is no
        # second signal here and nothing is ever recovered for projectors. A
        # tail-merged projector type therefore surfaces as PRESENT (unproven),
        # not as supported. Said out loud because the asymmetry is real.
        klass=None,
        error=b"unknown projector type: %s",
        error_note="mtmd's clip loader prints this and rejects the mmproj",
    ),
}

# lookup() states, worst to best.
ABSENT, PRESENT, RECOVERED, IN_TABLE = "absent", "present", "recovered", "table"


# ---------------------------------------------------------------------------
# outcomes
# ---------------------------------------------------------------------------

class RosterUnknown(Exception):
    """This build's roster could not be established.

    Deliberately an exception and not an empty set -- see the module docstring.
    """

    def __init__(self, kind, reason, tried=None):
        Exception.__init__(self, reason)
        self.kind = kind
        self.reason = reason
        self.tried = list(tried or [])


class Roster(object):
    """One extracted table, with everything needed to audit the extraction."""

    def __init__(self, kind, table, recovered, source, source_bytes, offset,
                 symbol, install_tag, dropped, cached, note=None):
        self.kind = kind
        self.table = list(table)            # the contiguous run, in file order
        self.recovered = dict(recovered)    # name -> evidence, tail-merged
        self.names = frozenset(self.table) | frozenset(self.recovered)
        self.source = source
        self.source_bytes = source_bytes
        self.offset = offset
        self.symbol = symbol
        self.install_tag = install_tag
        self.dropped = list(dropped)
        self.cached = bool(cached)
        self.note = note

    def __contains__(self, name):
        return name in self.names

    def __len__(self):
        return len(self.names)

    def __iter__(self):
        return iter(sorted(self.names))

    def where(self):
        """One line naming the file the answer came from -- rule 1's citation."""
        extra = ("%d + %d recovered" % (len(self.table), len(self.recovered))
                 if self.recovered else "%d" % len(self.table))
        return "%s (%s, %s names%s)" % (
            os.path.basename(self.source), self.symbol, extra,
            ", cached" if self.cached else "")

    def as_dict(self):
        return {"kind": self.kind, "count": len(self.names),
                "table_count": len(self.table),
                "source": self.source, "source_bytes": self.source_bytes,
                "offset": self.offset, "symbol": self.symbol,
                "install_tag": self.install_tag, "cached": self.cached,
                "dropped": self.dropped, "note": self.note,
                "names": self.table, "recovered": self.recovered}


# ---------------------------------------------------------------------------
# finding the binary
# ---------------------------------------------------------------------------

# A file smaller than this is not a shared library. It is, on Windows, what a
# POSIX symlink checked out of git looks like: bin/llama.cpp/libllama.so links
# to libllama.so.0, and on the Windows side of this very clone it stats as
# neither a link nor a file. Skipping small candidates keeps the concrete
# libllama.so.0.3.0 as the one that gets read on both halves of the machine.
_MIN_LIB_BYTES = 64 * 1024

_SUFFIXES = ("", ".so", ".so.*", ".dylib", "*.dylib", ".dll")

# Statically linked builds have no libllama at all; the table is inside the
# executable. Scanning an ELF or a PE is the same operation either way -- we
# never run it -- so a static build degrades to "slower to read", not UNKNOWN.
_EMBEDDERS = ("llama-server", "llama-cli", "llama-bench", "llama-perplexity")


def _search_dirs(explicit=None):
    """Where a llama.cpp build might be, most specific first.

    Deliberately the same chain as paths.llama_bin(), minus PATH's binary-only
    step and plus the bootstrap directory, so "the tools this campaign runs"
    and "the roster this campaign is held to" cannot come from different
    builds.
    """
    out = []

    def add(d):
        if not d:
            return
        d = os.path.abspath(os.path.expanduser(d))
        for cand in (d, os.path.join(d, "build", "bin"), os.path.join(d, "lib")):
            if cand not in out:
                out.append(cand)

    if explicit:
        # An explicit directory PINS the build. Falling through to the rest of
        # the chain would answer a question about one llama.cpp with the roster
        # of another, which is worse than answering UNKNOWN.
        add(explicit)
        return out
    try:
        add(paths.load_campaign().get("llama_dir"))
    except SystemExit:
        # load_campaign() refuses to pick between two campaigns. That is the
        # right call for a machine constant and the wrong one here: four other
        # candidate directories are still ahead of us, and the roster is a
        # property of the BUILD, not of the campaign.
        pass
    add(os.environ.get("LLAMA_DIR"))
    server = os.environ.get("LLAMA_SERVER")
    if server:
        add(os.path.dirname(server))
    add(os.path.join(paths.repo_root(), "bin", "llama.cpp"))
    return out


def _sized_files(patterns):
    hits = {}
    for pat in patterns:
        for p in glob.glob(pat):
            try:
                size = os.path.getsize(p)
            except OSError:
                continue
            if os.path.isfile(p) and size >= _MIN_LIB_BYTES:
                hits[os.path.abspath(p)] = size
    return [p for p, _ in sorted(hits.items(), key=lambda kv: -kv[1])]


def _candidates(directory, stem):
    """Concrete library files for `stem` in `directory`, largest first."""
    pats = [os.path.join(directory, stem + s) for s in _SUFFIXES]
    if stem.startswith("lib"):      # Windows drops the prefix: mtmd.dll
        pats.append(os.path.join(directory, stem[3:] + ".dll"))
    return _sized_files(pats)


def _embedders(directory):
    pats = []
    for tool in _EMBEDDERS:
        pats.append(os.path.join(directory, tool))
        pats.append(os.path.join(directory, tool + ".exe"))
    return _sized_files(pats)


def _install_tag(directory):
    """The tag INSTALL.json records for the build in `directory`, or None."""
    try:
        with open(os.path.join(directory, "INSTALL.json"), "r",
                  encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    tag = data.get("tag") if isinstance(data, dict) else None
    return tag if isinstance(tag, str) and tag else None


# ---------------------------------------------------------------------------
# the scan
# ---------------------------------------------------------------------------

def _plausible(tok):
    return _MIN_LEN <= len(tok) <= _MAX_LEN and _NAME.match(tok) is not None


def _expand(data, start, end):
    """Grow the NUL-separated run around the validated token data[start:end]."""
    names = [data[start:end]]
    pos = end + 1
    while True:
        nul = data.find(b"\x00", pos)
        if nul < 0:
            break
        tok = data[pos:nul]
        if not _plausible(tok):
            break
        names.append(tok)
        pos = nul + 1
    pos = start
    while pos > 0:
        nul = data.rfind(b"\x00", 0, pos - 1)
        if nul < 0:
            break
        tok = data[nul + 1:pos - 1]
        if not _plausible(tok):
            break
        names.insert(0, tok)
        pos = nul + 1
    # `pos` has walked back to the first byte of the first token in the run --
    # the file offset a human needs to check this by hand in a hex editor.
    return names, pos


def scan_table(data, table):
    """(names, offset, dropped) for `table` in `data`, or None if not found.

    Every NUL-delimited occurrence of every anchor is tried and the run holding
    the MOST anchors wins. One anchor is not enough: `llama` appears
    NUL-delimited in several places in libllama, and the wrong one seeds a run
    of eight tokens instead of a hundred and forty-three.
    """
    best = None                                    # (run, offset)
    best_hits = 0
    for anchor in table.anchors:
        for m in re.finditer(b"\x00" + re.escape(anchor) + b"\x00", data):
            start = m.start() + 1
            run, off = _expand(data, start, start + len(anchor))
            hits = sum(1 for a in table.anchors if a in run)
            if best is None or hits > best_hits or (
                    hits == best_hits and len(run) > len(best[0])):
                best, best_hits = (run, off), hits
    if best is None:
        return None
    run, off = best
    if best_hits < max(3, (len(table.anchors) + 1) // 2):
        # The run was found but it is not THE run: too few of the anchors
        # landed inside it for this to be the roster.
        return None
    dropped = [t.decode("ascii") for t in run if t in _SENTINELS]
    names = [t.decode("ascii") for t in run if t not in _SENTINELS]
    return names, off, dropped


# ---------------------------------------------------------------------------
# recovering what the linker's tail merge hid
# ---------------------------------------------------------------------------

def elf_rodata(data):
    """(start, end) of .rodata, or None when this is not an ELF we can read.

    Bounding the search matters: `.dynstr` holds every mangled symbol name, so
    an unbounded `find(b"openai_moe\\0")` hits the RTTI string and "recovers"
    an architecture that does not exist. 40 lines of section-header walk is the
    price of evidence that means something.
    """
    if data[:4] != b"\x7fELF" or len(data) < 0x40:
        return None
    if data[4] != 2 or data[5] != 1:               # ELF64, little-endian only
        return None
    try:
        e_shoff = struct.unpack_from("<Q", data, 0x28)[0]
        e_shentsize, e_shnum, e_shstrndx = struct.unpack_from("<HHH", data, 0x3a)
        if not e_shoff or not e_shnum or e_shstrndx >= e_shnum:
            return None
        base = e_shoff + e_shstrndx * e_shentsize
        shstr = struct.unpack_from("<Q", data, base + 0x18)[0]
        best = None
        for i in range(e_shnum):
            off = e_shoff + i * e_shentsize
            nm, _ty, _fl, _ad, f_off, f_size = struct.unpack_from(
                "<IIQQQQ", data, off)
            end = data.find(b"\x00", shstr + nm)
            name = data[shstr + nm:end].decode("latin-1")
            if name.startswith(".rodata") and f_size:
                span = (f_off, f_off + f_size)
                if best is None or (span[1] - span[0]) > (best[1] - best[0]):
                    best = span
        return best
    except (struct.error, IndexError, ValueError):
        return None


def class_names(data, prefix):
    """Class names from mangled `_ZT*<len><prefix><name>` symbols.

    A regex over the raw bytes, not a symbol-table walk: the mangled names are
    NUL-separated strings in .dynstr and .rodata alike, the length prefix makes
    the identifier self-delimiting, and skipping the ELF parse here means the
    same code works on a .dll that happens to use the Itanium ABI.
    """
    out = set()
    if not prefix:
        return out
    plen = len(prefix)
    for m in _MANGLED.finditer(data):
        try:
            n = int(m.group(1))
        except ValueError:
            continue
        start = m.end() - 1
        if n <= plen or n > 128 or start + n > len(data):
            continue
        ident = data[start:start + n]
        if not ident.startswith(prefix):
            continue
        tail = ident[plen:]
        if re.match(rb"[a-z0-9_]+\Z", tail):
            out.add(tail.decode("ascii"))
    return out


def _spellings(cls):
    """Name spellings a C++ class name could stand for.

    `_` in an identifier is `_`, `-` or `.` in the roster string:
    llama_model_command_r <-> "command-r", llama_model_muse_glimmer <->
    "muse-glimmer". Bounded at four underscores because 3**5 guesses is no
    longer a lookup, and no real name has that many.
    """
    idx = [i for i, ch in enumerate(cls) if ch == "_"]
    if not idx or len(idx) > 4:
        return [cls]
    out = set()
    for combo in itertools.product("_-.", repeat=len(idx)):
        s = list(cls)
        for i, ch in zip(idx, combo):
            s[i] = ch
        out.add("".join(s))
    return sorted(out)


def _container(data, lo, hi, at):
    """The NUL-terminated string that `at` falls inside, as bytes."""
    start = data.rfind(b"\x00", lo, at) + 1
    if start <= lo:
        start = lo
    end = data.find(b"\x00", at, hi)
    return data[start:end if end >= 0 else hi]


def find_literal(data, name, rodata=None):
    """Where `name` occurs as a NUL-terminated string, with its container.

    Returns {"offset", "container", "tail_merged"} or None. When `rodata` is
    given the search is confined to it.
    """
    lo, hi = rodata if rodata else (0, len(data))
    needle = name.encode("ascii", "ignore") + b"\x00"
    at = data.find(needle, lo, hi)
    if at < 0:
        return None
    container = _container(data, lo, hi, at)
    return {"offset": at, "container": container.decode("latin-1"),
            "tail_merged": container != name.encode("ascii", "ignore")}


def recover_merged(data, table_names, table, rodata):
    """Roster entries the linker's suffix merge removed from the run.

    Restored only when two independent signals agree (rule 4): a
    `<prefix><name>` C++ class exists in the mangled symbols, AND the literal
    is in .rodata as the tail of another string that is itself name-shaped.
    The container test is the one that matters -- without it `base` gets
    "recovered" out of `%s.rope.freq_base`.
    """
    out = {}
    if not table.klass or rodata is None:
        return out
    have = set(table_names)
    for cls in sorted(class_names(data, table.klass)):
        spellings = _spellings(cls)
        if any(s in have for s in spellings):
            continue
        for s in spellings:
            hit = find_literal(data, s, rodata)
            if not hit or not hit["tail_merged"]:
                continue
            if not _plausible(hit["container"].encode("latin-1")):
                continue              # the container is RTTI or a format string
            out[s] = {"offset": hit["offset"], "inside": hit["container"],
                      "class": table.klass.decode() + cls}
            break
    return out


def _scan_file(path, table):
    """((table, recovered, offset, dropped, nbytes), None) or (None, why)."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        return None, "unreadable: %s" % (getattr(exc, "strerror", None) or exc)
    hit = scan_table(data, table)
    if hit is None:
        return None, "no %s run found" % table.symbol
    names, off, dropped = hit
    if len(names) < table.floor:
        # The whole point of the floor. A run this short is a broken scan, and
        # publishing it would reject architectures this build supports.
        return None, ("%s scan found only %d names (floor %d) -- reporting "
                      "UNKNOWN rather than a short list"
                      % (table.symbol, len(names), table.floor))
    rodata = elf_rodata(data)
    recovered = recover_merged(data, names, table, rodata)
    return (names, recovered, off, dropped, len(data)), None


# ---------------------------------------------------------------------------
# the cache
# ---------------------------------------------------------------------------

CACHE_NAME = "ARCHS.json"


def cache_path(directory):
    return os.path.join(directory, CACHE_NAME)


def _read_cache(directory, tag):
    """The cached rosters for `tag`, or {} when absent, stale or corrupt."""
    try:
        with open(cache_path(directory), "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("install_tag") != tag:
        return {}
    tables = data.get("tables")
    return tables if isinstance(tables, dict) else {}


def _fresh(entry):
    """A cached table is usable only if the file it came from is unchanged.

    The tag alone is not enough. `built_from_source` builds get reinstalled at
    the same tag, INSTALL.json can be hand-edited, and a swapped .so under an
    unchanged tag is exactly the case where a stale roster does damage.
    """
    if not isinstance(entry, dict):
        return False
    src, names = entry.get("source"), entry.get("names")
    if not src or not isinstance(names, list) or not names:
        return False
    try:
        return os.path.getsize(src) == entry.get("source_bytes")
    except OSError:
        return False


def _write_cache(directory, tag, entries):
    tmp = cache_path(directory) + ".tmp"
    payload = {"install_tag": tag,
               "written_by": "scripts/lib/archs.py",
               "note": "regenerated automatically; delete it to force a rescan",
               "tables": entries}
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=1, sort_keys=True)
            fh.write("\n")
        if os.path.exists(cache_path(directory)):
            os.remove(cache_path(directory))
        os.rename(tmp, cache_path(directory))
        return cache_path(directory)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return None


# ---------------------------------------------------------------------------
# the public answer
# ---------------------------------------------------------------------------

def roster(kind, directory=None, refresh=False):
    """The `kind` roster for the installed build. Raises RosterUnknown.

    `kind` is "archs" or "projectors". `directory` pins one llama.cpp build;
    omitted, the search chain in _search_dirs() decides.
    """
    table = TABLES[kind]
    tried = []
    for d in _search_dirs(directory):
        if not os.path.isdir(d):
            continue
        tag = _install_tag(d)
        if not refresh:
            entry = _read_cache(d, tag).get(kind)
            if _fresh(entry):
                return Roster(kind, entry["names"], entry.get("recovered") or {},
                              entry["source"], entry.get("source_bytes"),
                              entry.get("offset"),
                              entry.get("symbol") or table.symbol, tag,
                              entry.get("dropped") or [], cached=True)
        files = _candidates(d, table.stem) + _embedders(d)
        if not files:
            tried.append("%s   (no %s* and no llama.cpp executable)"
                         % (d, table.stem))
            continue
        for path in files:
            got, why = _scan_file(path, table)
            if got is None:
                tried.append("%s   <-- %s" % (path, why))
                continue
            names, recovered, off, dropped, nbytes = got
            entry = {"source": path, "source_bytes": nbytes, "offset": off,
                     "symbol": table.symbol, "count": len(names),
                     "dropped": dropped, "names": names,
                     "recovered": recovered}
            merged = dict(_read_cache(d, tag))
            merged[kind] = entry
            written = _write_cache(d, tag, merged)
            note = None if written else ("not cached: %s is not writable"
                                         % cache_path(d))
            return Roster(kind, names, recovered, path, nbytes, off,
                          table.symbol, tag, dropped, cached=False, note=note)
    raise RosterUnknown(
        kind,
        "%s could not be read from any llama.cpp build on this machine"
        % table.symbol,
        tried or ["(no candidate directory exists)"])


def supported_archs(directory=None, refresh=False):
    """The architectures this build can load, as a frozenset of str.

    LLM_ARCH_NAMES' contiguous run plus the entries the linker's suffix merge
    hid, each corroborated by a `llama_model_<name>` class symbol. Raises
    RosterUnknown when the table cannot be established -- see RosterUnknown for
    why that is not an empty set.
    """
    return roster("archs", directory, refresh).names


def supported_projectors(directory=None, refresh=False):
    """The mmproj projector types this build can load, as a frozenset of str.

    PROJECTOR_TYPE has no per-type class, so there is no second signal and no
    recovery: a tail-merged projector type is reported by lookup() as PRESENT
    (unproven), never as supported.
    """
    return roster("projectors", directory, refresh).names


def lookup(kind, name, directory=None):
    """Grade one declared name against this build. Raises RosterUnknown.

    Membership in a set is not the whole test, because the extracted set is a
    lower bound (see the tail-merge note in the module docstring). The states,
    best to worst:

      table      in the contiguous run. Supported.
      recovered  suffix-merged out of the run, restored on two agreeing
                 signals. Supported.
      present    the byte string is somewhere in the binary's .rodata but not
                 in the roster and not corroborated by a class. UNPROVEN -- it
                 may be a hidden roster entry or a coincidence (a tensor name,
                 a chat-template name), and this module will not pick.
      absent     the byte string is nowhere in the binary. It cannot be a
                 roster entry, so the load WILL fail. This is the ZAYA1 case.
    """
    r = roster(kind, directory)
    ev = {"name": name, "roster": r}
    if name in r.table:
        ev["state"] = IN_TABLE
        return ev
    if name in r.recovered:
        ev["state"] = RECOVERED
        ev["evidence"] = r.recovered[name]
        return ev
    try:
        with open(r.source, "rb") as fh:
            data = fh.read()
    except OSError:
        # Reachable only from the cache path, where the roster is known but the
        # file it came from has since gone. Refusing to grade is the honest
        # answer: "not in the cached table" is not evidence of absence.
        raise RosterUnknown(kind, "%s is no longer readable, so a name outside "
                                  "the cached table cannot be graded" % r.source)
    hit = find_literal(data, name, elf_rodata(data))
    if hit:
        ev["state"] = PRESENT
        ev["evidence"] = {"offset": hit["offset"], "inside": hit["container"],
                          "tail_merged": hit["tail_merged"]}
        return ev
    ev["state"] = ABSENT
    return ev


def load_error(kind, name, directory=None):
    """The error a user would see, quoted from the installed binary.

    Returns {"text", "literal", "source", "offset", "note"} or None. `text` is
    the literal with the offending name substituted -- DERIVED, and labelled as
    derived by its caller -- because the literal is only the format: llama.cpp
    appends the closing quote from a separate char and mtmd's is a printf
    template. What is MEASURED is that this exact byte string sits in the
    binary that would have loaded the model (rule 1).
    """
    table = TABLES[kind]
    try:
        source = roster(kind, directory).source
    except RosterUnknown:
        return None
    try:
        with open(source, "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    at = data.find(table.error)
    if at < 0:
        return None
    literal = table.error.decode("ascii")
    text = literal.replace("%s", name) if "%s" in literal else literal + name + "'"
    return {"text": text, "literal": literal, "source": source, "offset": at,
            "note": table.error_note}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _report(directory, as_json, refresh):
    out = {"searched": _search_dirs(directory), "tables": {}}
    rc = 0
    for kind in ("archs", "projectors"):
        try:
            r = roster(kind, directory, refresh)
        except RosterUnknown as exc:
            out["tables"][kind] = {"status": "UNKNOWN", "reason": exc.reason,
                                   "tried": exc.tried}
            rc = 2
        else:
            d = r.as_dict()
            d["status"] = "OK"
            out["tables"][kind] = d
    if as_json:
        json.dump(out, sys.stdout, indent=1)
        sys.stdout.write("\n")
        return rc

    w = sys.stdout.write
    w("\narchs.py -- what this llama.cpp build can load, read without running it\n\n")
    for kind in ("archs", "projectors"):
        t = out["tables"][kind]
        if t["status"] != "OK":
            w("  %-11s UNKNOWN  %s\n" % (kind, t["reason"]))
            for line in t["tried"]:
                w("              looked at %s\n" % line)
            w("\n")
            continue
        w("  %-11s OK       %d names (%s: %d in the table%s)\n"
          % (kind, t["count"], TABLES[kind].symbol, t["table_count"],
             " + %d recovered" % len(t["recovered"]) if t["recovered"] else ""))
        w("              file    %s (%s bytes)\n"
          % (t["source"], "{:,}".format(t["source_bytes"] or 0)))
        w("              run     starts 0x%x, %r .. %r\n"
          % (t["offset"] or 0, t["names"][0], t["names"][-1]))
        w("              build   INSTALL.json tag %s%s\n"
          % (t["install_tag"] or "(none recorded)",
             "   [from ARCHS.json cache]" if t["cached"] else ""))
        if t["dropped"]:
            w("              dropped %s   (sentinel, not a loadable name)\n"
              % ", ".join(t["dropped"]))
        if t.get("note"):
            w("              note    %s\n" % t["note"])
        w("\n")
        for i in range(0, len(", ".join(t["names"])), 70):
            w("      %s\n" % ", ".join(t["names"])[i:i + 70])
        if t["recovered"]:
            w("\n      recovered from the linker's suffix merge -- the literal has no\n"
              "      copy of its own, so it is only in the binary as a tail:\n")
            for name in sorted(t["recovered"]):
                e = t["recovered"][name]
                w("        %-16s inside %-18s @0x%x   %s\n"
                  % (name, "'" + e["inside"] + "'", e["offset"], e["class"]))
        w("\n")
    return rc


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="archs.py",
        description="Read LLM_ARCH_NAMES and PROJECTOR_TYPE_NAMES out of the "
                    "installed llama.cpp without executing it.",
        epilog="exit: 0 both rosters read   2 at least one is UNKNOWN\n"
               "An UNKNOWN roster is an answer, not a crash: a SHORT roster "
               "would reject models this build loads, which is worse.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", metavar="DIR",
                    help="a llama.cpp build directory to read, instead of the "
                         "usual search chain")
    ap.add_argument("--name", metavar="NAME", action="append", default=[],
                    help="grade one declared architecture or projector name "
                         "against this build (repeatable)")
    ap.add_argument("--refresh", action="store_true",
                    help="ignore ARCHS.json and rescan the binaries")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable output")
    a = ap.parse_args(argv)
    if a.name:
        res = {}
        for name in a.name:
            row = {}
            for kind in ("archs", "projectors"):
                try:
                    hit = lookup(kind, name, a.dir)
                except RosterUnknown as exc:
                    row[kind] = {"state": "UNKNOWN", "reason": exc.reason}
                    continue
                row[kind] = {"state": hit["state"],
                             "evidence": hit.get("evidence"),
                             "roster": hit["roster"].where()}
            res[name] = row
        if a.json:
            json.dump(res, sys.stdout, indent=1)
            sys.stdout.write("\n")
        else:
            for name, row in res.items():
                for kind, r in row.items():
                    sys.stdout.write("  %-9s %-12s %s\n"
                                     % (kind, name, r["state"]))
                    if r.get("evidence"):
                        sys.stdout.write("            %s\n" % r["evidence"])
        return 0 if all(r["state"] in (IN_TABLE, RECOVERED)
                        for row in res.values() for r in row.values()) else 1
    return _report(a.dir, a.json, a.refresh)


if __name__ == "__main__":
    sys.exit(main())
