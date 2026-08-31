#!/usr/bin/env python3
"""Where things are on THIS machine — resolved at call time, never assumed.

    python scripts/lib/paths.py            # print what resolves here, and why

WHY THIS FILE EXISTS. Every measurement in this repository was taken on one
machine, and about fifty scripts said so out loud:

    SERVER  = os.environ.get("LLAMA_SERVER", r"E:\\AI\\llama.cpp\\llama-server.exe")
    BOARD, RESERVE = 24576, 1796

The first line is merely unportable — on a second machine it fails at the first
launch, loudly, and someone edits the file. The second line is the dangerous
one. `BOARD = 24576` is a claim about the CARD, and on a 12 GB card

    slack = BOARD - used

still returns a comfortable positive number. The rule-13b deep-fill probe — the
only mechanism in this repository for catching a window that is falsely labelled
fully resident — then stamps PASS on a configuration that is spilling to host
RAM. Nothing crashes. A wrong number gets published, with the conditions block
that makes it look measured. That is the failure this module exists to make
impossible: a machine constant is read from `machine.json` or the run STOPS.

THE RULE FOR CALLERS, and it is the whole reason these are functions rather
than module constants: **resolve at the point of use, never at import.**

    SERVER = paths.llama_bin("llama-server")     # NO - runs at import
    def server_bin(): return paths.llama_bin("llama-server")   # yes

A module-level call makes `--help` require a toolchain, makes
`scripts/verify/probe-smoke-test.py` fail on a machine that simply has not run
`setup.sh` yet, and turns "this campaign has no machine.json" into a syntax-
error-shaped traceback at import time. Everything here raises SystemExit with
an actionable message instead — but only the caller can decide WHEN it is fair
to ask.

WHAT IS AUTHORITATIVE HERE. `results/<slug>/campaign.json` describes the
campaign (where its toolchain and weights live). `results/<slug>/machine.json`
describes the box (what the card actually is). Neither is invented, guessed or
defaulted: a missing campaign.json degrades to the environment and PATH,
because those are still honest answers to "where is llama-server"; a missing
machine.json is fatal, because there is no honest answer to "how big is the
card" other than measuring it.

Stdlib only. Python 3.10+. Linux, macOS and Windows.
"""
import json
import os
import shutil
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))

# The environment variable that pins the campaign when more than one exists.
SLUG_ENV = "MEASURED_INFERENCE_SLUG"


def repo_root():
    """The repository root, derived from this file — never from the cwd."""
    return os.path.dirname(os.path.dirname(_HERE))


# --------------------------------------------------------------------------
# campaign.json / machine.json
# --------------------------------------------------------------------------

def _results_dir():
    return os.path.join(repo_root(), "results")


def _slug_for(filename, slug=None):
    """Which results/<slug>/ owns `filename`, or None if nothing does.

    Order: the explicit argument, then $MEASURED_INFERENCE_SLUG, then the one
    campaign directory that actually contains the file. "The one" is literal:
    two candidates is an ambiguity this module refuses to resolve by picking,
    because picking the wrong campaign's machine.json is exactly the silent
    wrong-number failure this file exists to prevent.
    """
    if slug:
        return slug
    env = os.environ.get(SLUG_ENV)
    if env:
        return env
    try:
        entries = sorted(os.listdir(_results_dir()))
    except OSError:
        return None
    have = [d for d in entries
            if os.path.isfile(os.path.join(_results_dir(), d, filename))]
    if len(have) == 1:
        return have[0]
    if len(have) > 1:
        raise SystemExit(
            "%d campaigns have a %s (%s).\nName the one you mean: pass "
            "--slug, or set %s=<slug>."
            % (len(have), filename, ", ".join(have), SLUG_ENV))
    # Nothing has it yet. Fall back to the single campaign directory so the
    # caller's error can name the exact file it wanted, with its real path.
    dirs = [d for d in entries
            if os.path.isfile(os.path.join(_results_dir(), d, "campaign.md"))]
    return dirs[0] if len(dirs) == 1 else None


def _json_path(filename, slug=None):
    """Absolute path the file WOULD have, and the slug it belongs to."""
    s = _slug_for(filename, slug)
    if not s:
        return None, None
    return os.path.join(_results_dir(), s, filename), s


def _load_json(filename, slug=None):
    """Parse results/<slug>/<filename>. {} when absent — never on bad JSON.

    A file that exists but does not parse is a defect, not an absence: silently
    treating it as "no configuration" would fall back to the environment and
    produce numbers under conditions nobody chose.
    """
    path, _ = _json_path(filename, slug)
    if not path or not os.path.isfile(path):
        return {}
    try:
        # utf-8-sig, not utf-8: PowerShell 5.1's Out-File -Encoding utf8 and
        # Windows Notepad both write a BOM, and json.load rejects it. That is
        # the exact bug gpu_lock.holder() carries a comment about, where a
        # BOM'd lockfile read as "no lock" and let two servers start at once.
        with open(path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except ValueError as exc:
        raise SystemExit("%s is not valid JSON: %s" % (path, exc))
    if not isinstance(data, dict):
        raise SystemExit("%s must contain a JSON object, got %s"
                         % (path, type(data).__name__))
    return data


def load_campaign(slug=None):
    """results/<slug>/campaign.json as a dict; {} when there isn't one.

    Absence is not fatal HERE. campaign.json is one link in the resolution
    chain for a binary or a weight file, and $LLAMA_SERVER or PATH is an
    equally honest answer. The functions that cannot degrade — board_total_mib,
    desktop_reserve_mib — do their own refusing.
    """
    return _load_json("campaign.json", slug)


def load_machine(slug=None):
    """results/<slug>/machine.json as a dict; {} when there isn't one."""
    return _load_json("machine.json", slug)


# --------------------------------------------------------------------------
# the toolchain
# --------------------------------------------------------------------------

def _exists(p):
    return bool(p) and os.path.isfile(p)


def _unusable(path):
    """Why this file cannot be exec'd here, or None if it can.

    Existing is not the same as runnable, and both ways it can differ are live
    in this repository RIGHT NOW: bin/llama.cpp/ currently holds a llama.cpp
    built under WSL (INSTALL.json: "os": "linux"), whose binaries are ELF --
    unrunnable on the Windows side of the same clone -- and which arrived
    mode 644, so on the Ubuntu side they are not executable either. Returning
    such a path is precisely the "default that usually works" this module
    refuses to produce: the caller discovers it as "Exec format error" or
    "not a valid Win32 application" after committing to a run.

    Only a CONFIDENT mismatch is reported. A POSIX shebang wrapper is neither
    ELF nor PE and is left alone.
    """
    try:
        with open(path, "rb") as fh:
            magic = fh.read(4)
    except OSError as exc:
        return "unreadable: %s" % (exc.strerror or exc)
    if os.name == "nt":
        if magic[:4] == b"\x7fELF":
            return "a Linux ELF binary, which cannot run on Windows"
        return None
    if magic[:2] == b"MZ":
        return "a Windows PE binary, which cannot run on this OS"
    if not os.access(path, os.X_OK):
        return "not executable -- chmod +x it"
    return None


def _in_dir(directory, tool):
    """Candidate paths for `tool` inside a llama.cpp directory.

    Both the release layout (<dir>/llama-server) and the cmake layout
    (<dir>/build/bin/llama-server) are checked, because scripts/setup.sh
    documents building into the second and copying into the first, and a
    campaign that skipped the copy is otherwise mystifying to debug.
    """
    out = []
    for base in (directory, os.path.join(directory, "build", "bin")):
        out.append(os.path.join(base, tool))
        out.append(os.path.join(base, tool + ".exe"))
    return out


def llama_bin(tool, explicit=None):
    """Absolute path to a llama.cpp tool, e.g. llama_bin("llama-server").

    Resolution order, lifted from scripts/bench/bench.py find_server():

        1. the explicit argument      (a --server-bin flag, say)
        2. campaign.json "llama_dir"  (this campaign's pinned toolchain)
        3. the environment            LLAMA_SERVER for llama-server, a full
                                      path to the binary; LLAMA_DIR for any
                                      tool, a directory holding them
        4. PATH
        5. <repo>/bin/llama.cpp/      what scripts/setup.sh bootstraps into

    and then SystemExit. There is deliberately no sixth step: a default that
    "usually works" is how E:\\AI\\llama.cpp ended up in fifty files, and a
    path that does not exist is better discovered here, in a millisecond, than
    by a run that has already committed an hour.
    """
    tool = tool[:-4] if tool.endswith(".exe") else tool
    tried = []

    def take(cands):
        for c in cands:
            if not c:
                continue
            if not _exists(c):
                tried.append(c)
                continue
            why = _unusable(c)
            if why:
                # keep looking: a usable build further down the chain still
                # wins, and if none is found the list below names this one and
                # says exactly what is wrong with it
                tried.append("%s   <-- SKIPPED: %s" % (c, why))
                continue
            tried.append(c)
            return os.path.abspath(c)
        return None

    # 1. explicit
    hit = take([explicit])
    if hit:
        return hit

    # 2. this campaign's pinned toolchain
    llama_dir = load_campaign().get("llama_dir")
    if llama_dir:
        hit = take(_in_dir(os.path.expanduser(llama_dir), tool))
        if hit:
            return hit

    # 3. environment: a binary for the server, a directory for anything
    if tool == "llama-server":
        hit = take([os.environ.get("LLAMA_SERVER")])
        if hit:
            return hit
    env_dir = os.environ.get("LLAMA_DIR")
    if env_dir:
        hit = take(_in_dir(os.path.expanduser(env_dir), tool))
        if hit:
            return hit

    # 4. PATH
    hit = take([shutil.which(tool)])
    if hit:
        return hit

    # 5. what setup.sh / setup.ps1 bootstraps
    hit = take(_in_dir(os.path.join(repo_root(), "bin", "llama.cpp"), tool))
    if hit:
        return hit

    setup = "scripts\\setup.ps1" if os.name == "nt" else "scripts/setup.sh"
    raise SystemExit(
        "%s not found. Any one of these fixes it:\n"
        "  %s                     bootstraps llama.cpp into <repo>/bin/llama.cpp/\n"
        "  set LLAMA_DIR=<dir>            a directory holding the llama.cpp tools\n"
        "  set LLAMA_SERVER=<file>        the llama-server binary itself\n"
        '  "llama_dir": "<dir>"           in results/<slug>/campaign.json\n'
        "Looked in:\n  %s"
        % (tool, setup, "\n  ".join(tried) or "(nowhere — no candidates)"))


# --------------------------------------------------------------------------
# the weights
# --------------------------------------------------------------------------

def model_path(name_or_path, slug=None):
    """Absolute path to a .gguf, given a path or a bare name.

    A path that exists is returned as given — callers that already know where
    their file is pay nothing. A bare name ("Qwen3.8-27B-UD-IQ4_XS.gguf", or
    the same without the extension) is looked up in, in order:

        1. campaign.json "models"      the campaign's own list of files; a
                                       {name: path} map is accepted as well
        2. campaign.json "model_dir"
        3. $MODEL_DIR                  the variable the older scripts already
                                       honoured, kept so nobody relearns
        4. <repo>/models/              gitignored, per AGENTS.md's LAYOUT

    Directories are searched one level deep as well, because a model directory
    of the shape <dir>/<repo-name>/<file>.gguf is the normal download layout.
    """
    raw = os.path.expanduser(str(name_or_path))
    if os.path.isfile(raw):
        return os.path.abspath(raw)

    camp = load_campaign(slug)
    tried = [raw]

    # campaign.json "models" is a LIST of files (results/TEMPLATE-campaign.json
    # documents it that way, and the arm runner iterates it). A {name: path}
    # object is accepted too, because it reads better when a campaign pins a
    # short alias to a long path. A list reaching .get() would raise
    # AttributeError -- a traceback where this module promises a SystemExit
    # naming the fix -- so both shapes are handled here, deliberately.
    base = os.path.basename(raw)
    listed = camp.get("models") or []
    if isinstance(listed, dict):
        entries = [listed.get(base)]
    elif isinstance(listed, (list, tuple)):
        entries = [e for e in listed if isinstance(e, str)
                   and os.path.basename(os.path.expanduser(e))
                   in (base, base + ".gguf")]
    else:
        entries = []
    for mapped in entries:
        if isinstance(mapped, str):
            cand = os.path.expanduser(mapped)
            tried.append(cand)
            if os.path.isfile(cand):
                return os.path.abspath(cand)

    # What the "models" map RESOLVED TO is searched under the roots as well, not
    # just the name that was asked for. The map's documented shape is
    # {"alias": "/full/path.gguf"}, and an absolute path is already answered by
    # the loop above -- but a campaign that writes the natural thing,
    # {"Q4_K_M": "Ornith-1.5-9B-MTP-Q4_K_M.gguf"}, got a bare name, which
    # os.path.isfile() resolves against the CWD and therefore never finds. It
    # then fell through to here and searched the roots for the ALIAS
    # ("models/Q4_K_M.gguf"), which does not exist either, so the file was
    # unfindable by any means and the error listed the correct filename among
    # the things it had "Looked at" without ever having joined it to a root.
    # Measured 2026-09-01: arms.py died on exactly this in a live campaign.
    # A mapped bare name is now searched under every root, ahead of the alias.
    names = []
    for mapped in entries:
        if isinstance(mapped, str):
            mb = os.path.basename(os.path.expanduser(mapped))
            if mb and mb not in names:
                names.append(mb)
    asked = os.path.basename(raw)
    if asked not in names:
        names.append(asked)
    if not asked.endswith(".gguf") and asked + ".gguf" not in names:
        names.append(asked + ".gguf")

    roots = [camp.get("model_dir"), os.environ.get("MODEL_DIR"),
             os.path.join(repo_root(), "models")]
    for root in roots:
        if not root:
            continue
        root = os.path.expanduser(root)
        for name in names:
            cand = os.path.join(root, name)
            tried.append(cand)
            if os.path.isfile(cand):
                return os.path.abspath(cand)
        # one level down: <root>/<publisher-or-repo>/<file>.gguf
        try:
            subs = sorted(os.listdir(root))
        except OSError:
            continue
        for sub in subs:
            for name in names:
                cand = os.path.join(root, sub, name)
                if os.path.isfile(cand):
                    return os.path.abspath(cand)

    raise SystemExit(
        "model %r not found. Any one of these fixes it:\n"
        "  set MODEL_DIR=<dir>            a directory holding the .gguf files\n"
        '  "model_dir": "<dir>"           in results/<slug>/campaign.json\n'
        '  "models": {"%s": "<file>"}\n'
        "                                 in results/<slug>/campaign.json\n"
        "  put the file in <repo>/models/\n"
        "Looked at:\n  %s"
        % (name_or_path, os.path.basename(raw), "\n  ".join(tried)))


# --------------------------------------------------------------------------
# the card — measured, or the run stops
# --------------------------------------------------------------------------

_MACHINE_SCHEMA = """results/%s/machine.json needs:

    {
      "board_total_mib": 24576,
      "desktop_reserve_mib": {"min": 412, "max": 1796, "n": 9,
                              "date": "2026-08-27"}
    }

board_total_mib is the card's TOTAL board memory, as nvidia-smi reports it
(nvidia-smi --query-gpu=memory.total --format=csv,noheader).

desktop_reserve_mib is measured, not assumed: sample board VRAM with NO server
loaded, over a working desktop, n times. "max" is the fence every fit check is
held to — the worst case the card must never evict — so it carries the
load-to-load variation you measured, not just the highest single reading. On
the reference 3090 that is 1,796 MiB: a 1,669 MiB desktop worst case plus 127
MiB of load-to-load variation."""


def _machine_field(key, slug=None):
    path, s = _json_path("machine.json", slug)
    data = load_machine(slug)
    if not data:
        raise SystemExit(
            "no machine.json%s — and this measurement is about the CARD, so "
            "there is no safe default.\nA board size guessed from the "
            "reference rig reads as comfortable slack on a smaller card and "
            "stamps PASS on a window that is spilling (rule 13).\n\n%s"
            % (" at " + path if path else "", _MACHINE_SCHEMA % (s or "<slug>")))
    if key not in data:
        raise SystemExit("%s has no %r.\n\n%s"
                         % (path, key, _MACHINE_SCHEMA % (s or "<slug>")))
    if data[key] is None:
        # detect-machine.py writes the key with a null value when it could not
        # measure the field, and records WHY under "provenance". Quoting that
        # here is the difference between "the schema wants an integer" and
        # "nvidia-smi was not available, so nothing read the board" - the
        # second tells the operator what to actually do.
        why = ((data.get("provenance") or {}).get(key) or {})
        why = why.get("how") or why.get("why") or ""
        raise SystemExit(
            "%s records %r as UNMEASURED (null).%s\n\nMeasure it and re-run:\n"
            "    python scripts/detect-machine.py --slug %s\n\n%s"
            % (path, key, ("\n  " + why) if why else "", s or "<slug>",
               _MACHINE_SCHEMA % (s or "<slug>")))
    return data[key], path, s


def board_total_mib(slug=None):
    """Total board memory of this machine's card, in MiB. Measured or fatal."""
    val, path, s = _machine_field("board_total_mib", slug)
    if not isinstance(val, int) or isinstance(val, bool) or val <= 0:
        raise SystemExit("%s: board_total_mib must be a positive integer "
                         "number of MiB, got %r.\n\n%s"
                         % (path, val, _MACHINE_SCHEMA % (s or "<slug>")))
    return val


def desktop_reserve_mib(slug=None):
    """The measured desktop reserve: {"min", "max", "n", "date"}.

    "max" is the anti-spill fence (rule 14). The other three fields travel with
    it so a caller can record HOW it was measured beside every number that was
    held to it — a fence without its sample size and date is exactly the
    unfalsifiable number rule 3 forbids.
    """
    val, path, s = _machine_field("desktop_reserve_mib", slug)
    if not isinstance(val, dict):
        raise SystemExit("%s: desktop_reserve_mib must be an object with "
                         "min/max/n/date, got %s.\n\n%s"
                         % (path, type(val).__name__,
                            _MACHINE_SCHEMA % (s or "<slug>")))
    missing = [k for k in ("min", "max", "n", "date") if k not in val]
    if missing:
        raise SystemExit("%s: desktop_reserve_mib is missing %s.\n\n%s"
                         % (path, ", ".join(missing),
                            _MACHINE_SCHEMA % (s or "<slug>")))
    for k in ("min", "max", "n"):
        if not isinstance(val[k], int) or isinstance(val[k], bool):
            raise SystemExit("%s: desktop_reserve_mib[%r] must be an integer, "
                             "got %r.\n\n%s"
                             % (path, k, val[k],
                                _MACHINE_SCHEMA % (s or "<slug>")))
    return {"min": val["min"], "max": val["max"], "n": val["n"],
            "date": str(val["date"])}


# --------------------------------------------------------------------------

def _report():
    """Print what resolves on this machine, and say so when nothing does."""
    print("repo_root      %s" % repo_root())
    for filename, loader in (("campaign.json", load_campaign),
                             ("machine.json", load_machine)):
        path, s = _json_path(filename, None)
        try:
            data = loader()
        except SystemExit as exc:
            print("%-14s %s" % (filename, exc))
            continue
        print("%-14s %s" % (filename,
                            "%s (%d keys)" % (path, len(data)) if data
                            else "absent%s" % (" — would be " + path
                                               if path else "")))
    for tool in ("llama-server", "llama-perplexity", "llama-tokenize"):
        try:
            print("%-14s %s" % (tool, llama_bin(tool)))
        except SystemExit:
            print("%-14s NOT FOUND (see the message this raises when a run "
                  "needs it)" % tool)
    for label, fn in (("board", board_total_mib),
                      ("desktop", desktop_reserve_mib)):
        try:
            print("%-14s %s" % (label, fn()))
        except SystemExit:
            print("%-14s unavailable — no machine.json" % label)
    return 0


USAGE = """\
Where things are on THIS machine - repo root, campaign.json, machine.json, the
llama.cpp binaries, the card - resolved at call time and never assumed. Run
with no arguments it prints the RESOLUTION REPORT: what resolves here, what
does not, and why. stage-0 and PROMPTS.md name that report as the readiness
check, so it stays the no-argument behaviour.

    python scripts/lib/paths.py          # the resolution report
    python scripts/lib/paths.py --help   # this text

Positional arguments: none. --help and -h are the only words this reads;
anything else is ignored and the report prints.

Environment, all optional:
  MEASURED_INFERENCE_SLUG   pin the campaign when results/ holds more than one
  LLAMA_SERVER              exact path to one llama.cpp binary
  LLAMA_DIR                 directory holding the llama.cpp binaries
  MODEL_DIR                 directory holding the .gguf weights

No server, no model, no GPU, and no file written - the report goes to stdout.
A resolver that finds nothing raises SystemExit carrying the message that says
what to do about it, so the report prints NOT FOUND per tool instead of dying
at the first one.

Example:
  python scripts/lib/paths.py

Imported as a library, this module runs nothing at import time. Resolve at the
point of use - paths.llama_bin(), paths.model_path(), paths.board_total_mib() -
never into a module-level constant.
"""


if __name__ == "__main__":
    # --help DESCRIBES the report; it does not run it. The report stays what a
    # bare invocation prints, because that is the readiness check stage-0 tells
    # the operator to run.
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        print(USAGE.rstrip())
        sys.exit(0)
    sys.exit(_report())
