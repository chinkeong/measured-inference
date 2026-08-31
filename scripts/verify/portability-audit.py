#!/usr/bin/env python3
"""Would this repository run on somebody else's machine?

    py scripts/verify/portability-audit.py [--fail-on-blocker]

WHY THIS EXISTS. The campaign's whole claim is that its numbers are
reproducible. Reproducible BY WHOM was never tested: every measurement here has
only ever run on the machine that wrote the scripts, where E:\\AI\\llama.cpp and
one particular home directory happen to exist. A clean clone of this repository
is the only honest test of the claim, and until 2026-08-28 nobody had taken one.

What the first clean clone found: 51 of 81 Python scripts carry an absolute
path, and about 21 of them name one user's home directory. On any other machine
those scripts do not fail loudly - they fail at the first file open, often after
loading a model, which is the expensive kind of failure.

WHAT COUNTS AS WHAT.

  BLOCKER   an absolute path to something the repository does not ship and
            cannot derive: a model file, a server binary, another user's home.
            A new user hits this and the script cannot continue.

  PLATFORM  a line that cannot EXECUTE on the reader's operating system: a
            Windows drive or a WSL `/mnt/<letter>/` mount inside a POSIX shell
            script, or a `wsl` / `powershell` / `taskkill` process launched from
            a .py or .sh with nothing branching on the host. Not a path that is
            merely somewhere else - a path, or a program, that is NOWHERE on a
            Linux box. Stops a new user exactly as hard as a BLOCKER does.

  FRAGILE   an absolute path INTO this repository. It works today only because
            the repository sits at that path. Deriving it from __file__ costs
            one line and removes the dependency entirely.

  OK        already environment-overridable, or derived from __file__.

The audit reports the FIX for each finding, not just the finding, because a
list of complaints is not a repair plan.

WHY PLATFORM WAS ADDED, 2026-08-31. This repository shipped a check named
"portability" that could not see the defect which broke its own first bare-metal
Ubuntu run: `scripts/verify/ubuntu-dryrun.sh` defaulted its clone source to
`SRC="${MI_SRC:-/mnt/e/AI/measured-inference}"`, a path that exists only when
"Ubuntu" is WSL under a Windows host, and step 1 died with CLONE FAILED before
one thing about the box had been proved. Two causes, both fixed here:

  1. ABS anchors a path literal to the quote in front of it, because that is how
     Python and PowerShell spell one. A POSIX shell does not: `cd /mnt/e/AI/x`,
     `MODEL=/mnt/c/...` and the parameter expansion above all put something
     between the quote and the path, and the audit saw none of them. Measured on
     a scratch clone with that exact line restored: 0 findings. SH_ABS reads .sh
     without the quote anchor.

  2. Even seen, it would have been called OK, because MI_SRC is an environment
     override and env_aware() answers "can this be pointed elsewhere". The
     override existed on 2026-08-31 and the box still died: nobody exports an
     override for a default they have not yet been told is wrong. PLATFORM asks
     the other question - does the DEFAULT exist at all on a POSIX box - and a
     WSL drive mount never does.

The same blindness covered processes. `subprocess.run(["wsl", "-e", "bash",
"-lc", cmd])` and a bare `["powershell", ...]` raise FileNotFoundError on this
box, and three scripts carried one with no host branch; close-three.py's took a
run down AFTER the rule-20 lock was held and a server was launched, which is GPU
time spent to learn nothing. Those are PLATFORM findings now.

WHAT IS DELIBERATELY NOT A FINDING, because an audit that cries wolf gets
ignored: .ps1 and .bat, which ARE the Windows path and are the reference
platform this repository must not regress; a pattern inside a comment; and a
call that already branches on the host (`os.name == "nt"`, `sys.platform`,
`platform.system()`, `shutil.which()`, a `_WINDOWS` flag) or that handles the
missing program by name (`except OSError` / `FileNotFoundError`) and returns "no
number" rather than dying. A bare `except Exception:` around it is NOT a guard -
that is the shape that drew a six-language figure in one colour and said nothing
(rule 2: no reader measures less than promised).

A `.exe` SUFFIX IS NOT CHECKED, and that is a measurement rather than an
oversight. 45 lines under tracked .py and .sh contain ".exe" on 2026-08-31 and
almost every one of them is correct cross-platform code: `os.path.join(base,
tool + ".exe")` in paths.py, `SERVER_NAMES = ... for e in ("", ".exe")` in
gpu_lock.py, `[ -x "$vpy" ] || vpy="$ROOT/.venv/Scripts/python.exe"` in
setup.sh - the repository's convention is to try both names, so a .exe rule
would fire hardest on the files that already got this right. (A naive substring
also matches `sys.executable` and `spec.loader.exec_module`, which is how the
first draft found 45 of them.) A Windows-only PROGRAM is caught by name in
WIN_TOOLS instead, and a Windows-only PATH by its drive letter.

There is deliberately NO allow-list file. Every PLATFORM finding this tree
produces on 2026-08-31 is true - one unguarded `taskkill` in an archived
Windows-era work script - so an allow-list would ship with nothing in it, and a
silencing mechanism nobody has ever had to use is a mechanism nobody has tested.
If a genuinely Windows-only .py ever has to be excused, add it the way
`scripts/verify/instrument-guard-allow.txt` does: one path per line, then '#',
then the sentence saying why - never by widening a pattern until the finding
disappears, which also deletes the next one.

Exit code is 0 unless --fail-on-blocker is passed, so this can be read by a
person before it is enforced by a hook. That flag now covers PLATFORM as well,
because a program that is not installed and a path that is not there stop the
same reader on the same line.
"""
import argparse
import io
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# An absolute Windows path, or a WSL mount, or a POSIX home.
ABS = re.compile(r"""(['"])((?:[A-Za-z]:\\|/mnt/[a-z]/|/home/|/Users/)[^'"\n]{2,})\1""")

# Things the repository does not ship. Hitting one of these stops a new user.
EXTERNAL = (
    ("llama.cpp", "the llama.cpp build", "LLAMA_SERVER"),
    (".lmstudio", "a model directory", "MODEL_DIR"),
    ("models", "a model directory", "MODEL_DIR"),
    (".gguf", "a model file", "MODEL_DIR"),
)

# Paths pointing back into this repository: fragile, not blocking.
INTERNAL_HINTS = ("measured-inference",)

# The same absolute path, written the way a SHELL writes one - no quote in
# front of it. ABS above anchors on the quote deliberately: without that anchor
# it also matches "version:\s*(\S+)" and "Looked in:\n  %s", where the drive
# letter is the last letter of an ordinary word. The anchor is therefore kept
# for .py and .ps1, where every path literal is quoted anyway, and dropped only
# for .sh, where a bare word IS a path. A drive letter here must be preceded by
# a non-word character and followed by two path-safe characters, which is what
# keeps `%s:\n` out of the results.
SH_ABS = re.compile(
    r"""(?<![\w'"])((?:[A-Za-z]:[\\/][A-Za-z0-9_.$~-]{2,}|/mnt/[a-z]/|/home/|/Users/)"""
    r"""[^\s'"();|&{}<>]*)""")

# A path that is not merely somewhere else but NOWHERE on a POSIX box: a DOS
# drive, or the /mnt/<letter>/ mount that exists only when Linux is running
# under a Windows host. Scoped by file kind at the call site - a drive path in a
# .py is already a BLOCKER by the model/binary/home rules above and renaming it
# would move 69 findings that reference/platform-notes.md counts by name, so
# only the WSL mount is claimed there, and no tracked .py carries one today
# (measured 2026-08-31).
WIN_ONLY = re.compile(r"^(?:[A-Za-z]:[\\/]|/mnt/[a-z]/)")

# Programs that exist only on Windows, or only inside WSL on a Windows host.
# Kept to names that mean nothing else: `wsl` on this Ubuntu box is not a
# command that does something different, it is a command that is not there.
WIN_TOOLS = ("wsl", "powershell", "pwsh", "cmd", "taskkill", "tasklist",
             "wmic", "schtasks", "cscript", "reg")
_TOOLS = "|".join(WIN_TOOLS)

# Python: argv[0] of a list literal, which is how every process in this
# repository is launched - subprocess.run(["wsl", "-e", ...]). Matching only
# that position is what keeps the guarded sites out: the correct ones resolve
# the host first (`host = shutil.which("pwsh") or shutil.which("powershell")`)
# and pass a VARIABLE as argv[0], so they carry no literal here to match.
PY_TOOL = re.compile(r"""[\[(]\s*(['"])(%s)(?:\.exe)?\1\s*,""" % _TOOLS, re.I)

# ...and that list of names has to be one something is LAUNCHING. Without this
# the check reported its own WIN_TOOLS tuple: a tuple of program names is
# indistinguishable from an argv list to a regex, and what separates them is
# what the surrounding line does with it. Two lines either side, because this
# repository writes the launcher on the argv line itself or one line off it.
LAUNCH = re.compile(r"subprocess|Popen|check_output|check_call|os\.system"
                    r"|os\.spawn|os\.execv")

# Shell: the tool as a command word - at the start of a line, of a pipeline
# segment, of a substitution.
SH_TOOL = re.compile(r"""(?:^|[;&|(`]|\$\()\s*(%s)(?:\.exe)?\b""" % _TOOLS)

# What makes a Windows-only call legitimate. Four are host tests; the fifth is
# the contract that the program may be absent and its reader returns "no
# number" instead of taking the run down (rule 2). A bare `except Exception:`
# is NOT here on purpose: it converts a missing program into a silently smaller
# result, which is the failure rule 2 and rule 19 both name.
PY_GUARD = re.compile(
    r"""os\.name\s*[!=]=\s*['"]nt['"]"""
    r"""|sys\.platform"""
    r"""|platform\.system\s*\("""
    r"""|shutil\.which\s*\("""
    r"""|\b(?:_WINDOWS|IS_WINDOWS|ON_WINDOWS|_WIN32|IS_NT)\b"""
    r"""|except[^\n]*\b(?:OSError|FileNotFoundError|WindowsError)\b""")

# The shell equivalents. `command -v wsl` before calling it is the same promise
# as shutil.which(), and it has to NAME the tool: a bare `\bwhich\b` was tried
# first and it silenced findings from ten lines of ordinary English - "which is
# where the repo sits when Ubuntu is WSL" is a sentence this repository actually
# contains, eight lines above the defect that started all of this. A guard
# pattern that matches prose does not reduce false positives, it manufactures
# false negatives, and those are the ones nobody ever finds.
SH_GUARD = re.compile(
    r"""\buname\b|\$\{?OSTYPE|/proc/version|\bWSL_DISTRO_NAME\b|\bMSYSTEM\b"""
    r"""|\bwslpath\b|(?:command -v|which)\s+(?:%s)\b""" % _TOOLS)

# .ps1 and .bat ARE the Windows path. This repository's reference platform is
# Windows and a regression there is worse than the Linux bug being fixed, so
# they are exempt from the platform check entirely rather than allow-listed one
# by one. Their absolute paths are still audited exactly as before.
PORTABLE_EXT = (".py", ".sh")

# A guard rarely sits on the same line as the call it protects - `if _WINDOWS:`
# is one line up, `except OSError:` three or four lines down, and the docstring
# that documents a Windows-only reader is above both. Ten lines back and six
# forward covers every guarded site in this tree as of 2026-08-31 without
# reaching into the next function.
GUARD_BACK, GUARD_FWD = 10, 6


def env_aware(line, window=""):
    """Is this path overridable from the environment?

    The override is often NOT on the same line as the literal. PowerShell in
    this repo writes the default first and the override immediately after:

        $model = 'C:\\...\\Qwen3.8-27B-Q4_K_M.gguf'
        if ($env:PROBE_MODEL) { $model = $env:PROBE_MODEL }

    Checking only the literal's own line called that a blocker when it is
    already portable. A portability audit that cries wolf gets ignored, and an
    ignored audit is worse than none - so the check reads a few lines either
    side, which is where an override realistically lives.
    """
    hay = line + "\n" + window
    return ("os.environ" in hay or "getenv" in hay or "$env:" in hay
            or "${env:" in hay)


def platform_path(lit, ext):
    """Does this literal name a place that is NOWHERE on the reader's box?

    Not "somewhere else" - env_aware() and the FRAGILE class already cover a
    path that merely moves. `/mnt/e/...` is a Windows drive as WSL mounts it and
    a bare-metal Ubuntu box has no /mnt/e at all, so no value of MI_SRC that the
    reader has not been told to set makes ubuntu-dryrun.sh's default work; that
    is why this returns a verdict BEFORE env_aware() is ever consulted, unlike
    every other class here.

    Scope, and it is deliberately narrow. A DOS drive is claimed only in a .sh,
    where it cannot even be opened: in a .py the same literal is already a
    BLOCKER by the model / binary / home rules, and reclassifying it would move
    69 findings that reference/platform-notes.md cites by count and by file. The
    WSL mount is claimed in both, because it means the same thing in every
    language - and no tracked .py carries one today, measured 2026-08-31, so
    nothing moves between classes on this tree either.
    """
    if ext not in PORTABLE_EXT or not WIN_ONLY.match(lit):
        return False
    return lit.startswith("/mnt/") or ext == ".sh"


def classify(path_literal, line, window="", ext=""):
    low = path_literal.lower()
    if platform_path(path_literal, ext):
        return ("PLATFORM",
                "a Windows drive or WSL mount, in a file that has to run on "
                "the reader's OS. Derive it from the script's own location - "
                "SELF_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\" "
                "in shell, os.path.dirname(os.path.abspath(__file__)) in "
                "Python - and keep the environment variable as an override, "
                "never as the only thing between a default and a box where "
                "that default does not exist.")
    for needle in INTERNAL_HINTS:
        if needle in low:
            return ("FRAGILE",
                    "an absolute path into this repository; derive it from "
                    + ("$BASH_SOURCE instead: SELF_DIR=\"$(cd \"$(dirname "
                       "\"${BASH_SOURCE[0]}\")\" && pwd)\""
                       if ext == ".sh" else
                       "__file__ instead: "
                       "os.path.dirname(os.path.abspath(__file__))"))
    for needle, what, var in EXTERNAL:
        if needle in low:
            if env_aware(line, window):
                return ("OK", "already overridable by %s" % var)
            return ("BLOCKER",
                    "names %s this repository does not ship. Read it from "
                    "the %s environment variable, keeping this value as the "
                    "documented default." % (what, var))
    if env_aware(line, window):
        return ("OK", "environment-overridable")
    return ("FRAGILE",
            "absolute path with no environment override; a second machine "
            "will not have it")


def tracked_py():
    try:
        out = subprocess.run(["git", "ls-files", "*.py", "*.ps1", "*.sh"],
                             cwd=REPO, capture_output=True, text=True,
                             timeout=60)
        return [f for f in out.stdout.splitlines() if f.strip()]
    except Exception as exc:
        sys.exit("portability-audit: cannot list tracked files: %s" % exc)


def win_tool(line, ext):
    """The Windows-only program this line launches, or None.

    argv[0] of a list literal in Python, a command word in shell. Both are
    narrow on purpose. The launches that are ALREADY correct in this tree
    resolve the host before using it - `host = shutil.which("pwsh") or
    shutil.which("powershell")`, then `[host, "-NoProfile", ...]` - so argv[0]
    is a variable and there is no literal here to match. Precision beats reach:
    a check that also flagged those would be arguing with the repository's own
    fix, and would be switched off inside a week.
    """
    if ext == ".py":
        m = PY_TOOL.search(line)
    elif ext == ".sh":
        m = SH_TOOL.search(line)
    else:
        return None
    if not m:
        return None
    return m.group(2) if ext == ".py" else m.group(1)


def guarded(window, ext):
    """Does anything near this call test the host, or handle its absence?"""
    return bool((PY_GUARD if ext == ".py" else SH_GUARD).search(window))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fail-on-blocker", action="store_true",
                    help="exit 1 on a BLOCKER or a PLATFORM finding")
    a = ap.parse_args()

    findings = {"BLOCKER": [], "PLATFORM": [], "FRAGILE": [], "OK": []}
    scanned = 0
    for rel in tracked_py():
        p = os.path.join(REPO, rel)
        try:
            src = io.open(p, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        scanned += 1
        ext = os.path.splitext(rel)[1].lower()
        lines = src.split(chr(10))
        in_doc = False
        for i, line in enumerate(lines, 1):
            # A triple-quoted block is prose, not code. This repository
            # documents its own defects at length and quotes the offending line
            # while doing it - the docstring above quotes `["wsl", "-e", ...]`
            # twice - so a check that reads a docstring as code reports the
            # explanation of a bug as the bug, in the one file most likely to
            # contain such an explanation. Only the PLATFORM check honours this:
            # the path check has counted prose since 2026-08-28 and its 69 and
            # 135 are cited by count in reference/platform-notes.md, so it is
            # left reading exactly what it read before.
            was_doc = in_doc
            for q in (chr(34) * 3, chr(39) * 3):
                if line.count(q) % 2:
                    in_doc = not in_doc
            if line.lstrip().startswith("#"):
                continue
            # An override can sit a line or two either side of a default.
            window = chr(10).join(lines[max(0, i - 4):i + 3])
            seen = []
            for m in ABS.finditer(line):
                lit = m.group(2)
                seen.append(lit)
                kind, fix = classify(lit, line, window, ext)
                findings[kind].append((rel, i, lit, fix))
            # Shell writes a path with no quote in front of it, which is how
            # ubuntu-dryrun.sh's WSL-only default walked through this audit
            # until 2026-08-31. Only .sh, and only literals ABS did not already
            # report, so no finding is counted twice and no .py or .ps1 verdict
            # moves (verified: identical counts before and after, same day).
            if ext == ".sh":
                for m in SH_ABS.finditer(line):
                    lit = m.group(1).rstrip("/\\")
                    if any(lit in prev for prev in seen):
                        continue
                    seen.append(lit)
                    kind, fix = classify(lit, line, window, ext)
                    findings[kind].append((rel, i, lit, fix))
            # A program that is not installed stops the reader as hard as a
            # path that is not there. The guard can sit further off than an
            # environment override does, so this window is its own.
            tool = win_tool(line, ext)
            if tool and ext == ".py" and (
                    was_doc or in_doc
                    or not LAUNCH.search(chr(10).join(lines[max(0, i - 3):i + 2]))):
                tool = None
            if tool and not guarded(
                    chr(10).join(lines[max(0, i - 1 - GUARD_BACK):i + GUARD_FWD]),
                    ext):
                findings["PLATFORM"].append((
                    rel, i, line.strip()[:70],
                    "launches `%s`, which exists only on Windows (or only "
                    "inside WSL on a Windows host); on the reader's box this "
                    "raises FileNotFoundError. Branch on the host - argv = "
                    "([...] if os.name == \"nt\" else [...]) - or catch OSError "
                    "and return \"not measured\" rather than taking the run "
                    "down (rule 2)." % tool))

    print("=" * 78)
    print("PORTABILITY AUDIT - would a clean clone run somewhere else?")
    print("=" * 78)
    print("repo            %s" % REPO)
    print("files scanned   %d" % scanned)
    for k in ("BLOCKER", "PLATFORM", "FRAGILE", "OK"):
        print("%-15s %d" % (k.lower(), len(findings[k])))
    print()

    for kind, headline in (
            ("BLOCKER", "STOPS A NEW USER - names something not shipped here"),
            ("PLATFORM", "CANNOT RUN ON THE READER'S OS - Windows or WSL only, "
                         "unguarded"),
            ("FRAGILE", "WORKS ONLY AT THIS PATH - derivable, so derive it")):
        if not findings[kind]:
            continue
        print("-" * 78)
        print("%s (%d)" % (headline, len(findings[kind])))
        print("-" * 78)
        by_file = {}
        for rel, line, lit, fix in findings[kind]:
            by_file.setdefault(rel, []).append((line, lit, fix))
        for rel in sorted(by_file):
            print("\n  %s" % rel)
            for line, lit, fix in by_file[rel][:6]:
                print("    :%-5d %s" % (line, lit[:66]))
                print("            fix  %s" % fix)
            if len(by_file[rel]) > 6:
                print("    ...and %d more in this file"
                      % (len(by_file[rel]) - 6))
        print()

    nb = len(findings["BLOCKER"])
    npf = len(findings["PLATFORM"])
    if nb:
        print("=" * 78)
        print("%d BLOCKER(S). A clean clone cannot run these without editing "
              "them." % nb)
        print("Every one is an absolute path to a model, a server binary or a "
              "home directory.")
        print("=" * 78)
    else:
        print("No blockers: nothing names a model, a binary or a home "
              "directory that a clean clone would not have.")

    # Counted and printed apart from the blockers because it is a different
    # question - not "is this file somewhere else" but "does this line exist on
    # the reader's OS at all". It shares their exit code: on 2026-08-31 a
    # PLATFORM finding is what stopped ubuntu-dryrun.sh at step 1 and what
    # killed close-three.py after the rule-20 lock was taken and a server was
    # already burning GPU time.
    if npf:
        print("%d PLATFORM finding(s): Windows-only or WSL-only lines in files "
              "that a Linux" % npf)
        print("reader executes. Each one is a FileNotFoundError or a missing "
              "directory on that box.")
    else:
        print("No platform findings: nothing outside .ps1/.bat needs Windows "
              "or WSL to run.")

    if a.fail_on_blocker and (nb or npf):
        sys.exit(1)


if __name__ == "__main__":
    main()
