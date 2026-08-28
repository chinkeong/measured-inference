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

  FRAGILE   an absolute path INTO this repository. It works today only because
            the repository sits at that path. Deriving it from __file__ costs
            one line and removes the dependency entirely.

  OK        already environment-overridable, or derived from __file__.

The audit reports the FIX for each finding, not just the finding, because a
list of complaints is not a repair plan.

Exit code is 0 unless --fail-on-blocker is passed, so this can be read by a
person before it is enforced by a hook.
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


def env_aware(line):
    return "os.environ" in line or "getenv" in line


def classify(path_literal, line):
    low = path_literal.lower()
    for needle in INTERNAL_HINTS:
        if needle in low:
            return ("FRAGILE",
                    "an absolute path into this repository; derive it from "
                    "__file__ instead: "
                    "os.path.dirname(os.path.abspath(__file__))")
    for needle, what, var in EXTERNAL:
        if needle in low:
            if env_aware(line):
                return ("OK", "already overridable by %s" % var)
            return ("BLOCKER",
                    "names %s this repository does not ship. Read it from "
                    "the %s environment variable, keeping this value as the "
                    "documented default." % (what, var))
    if env_aware(line):
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fail-on-blocker", action="store_true")
    a = ap.parse_args()

    findings = {"BLOCKER": [], "FRAGILE": [], "OK": []}
    scanned = 0
    for rel in tracked_py():
        p = os.path.join(REPO, rel)
        try:
            src = io.open(p, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        scanned += 1
        for i, line in enumerate(src.split("\n"), 1):
            if line.lstrip().startswith("#"):
                continue
            for m in ABS.finditer(line):
                lit = m.group(2)
                kind, fix = classify(lit, line)
                findings[kind].append((rel, i, lit, fix))

    print("=" * 78)
    print("PORTABILITY AUDIT - would a clean clone run somewhere else?")
    print("=" * 78)
    print("repo            %s" % REPO)
    print("files scanned   %d" % scanned)
    for k in ("BLOCKER", "FRAGILE", "OK"):
        print("%-15s %d" % (k.lower(), len(findings[k])))
    print()

    for kind, headline in (
            ("BLOCKER", "STOPS A NEW USER - names something not shipped here"),
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

    if a.fail_on_blocker and nb:
        sys.exit(1)


if __name__ == "__main__":
    main()
