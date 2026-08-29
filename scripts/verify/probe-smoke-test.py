#!/usr/bin/env python3
"""Can every probe in this repository actually START?

    py scripts/verify/probe-smoke-test.py [--fail]

WHY THIS EXISTS, and it is a defect this repository shipped rather than a
precaution. On 2026-08-28 a provenance-recording block was wired into five
probes. In four it landed after the imports. In ts-pick-probe.py it landed
ABOVE the module docstring and above `import sys`, so the file used `sys` and
`os` before importing them.

The file PARSED CLEANLY - it is valid Python, just wrong - so
`ast.parse` said yes, and that was the only check being run. The probe would
have died on its first line the moment anyone launched it, after a human had
already decided to spend an hour of GPU time on it. It was caught by running
`--help` on a hunch.

That is the whole idea here: PARSING IS NOT LOADING. A syntax check proves the
text is Python. It does not prove the module's top level runs, that its imports
resolve, or that its argument parser can build its own help text - and each of
those has failed in this repository at least once. The percent sign in a help
string that argparse tries to interpret as a format specifier is the second
example, found the same day.

WHAT THIS CHECKS, cheapest first, no GPU and no model:

  1. the file parses            - ast.parse
  2. the module top level RUNS  - imported by path in a subprocess, so a
                                  probe that mutates global state cannot
                                  affect the checker or the next probe
  3. --help builds and exits 0  - which exercises the whole argument parser,
                                  including every help string's formatting

A probe that fails any of these cannot measure anything, and finding out
before the run rather than after is worth the four seconds this takes.

WHAT IT DOES NOT CHECK. That the probe measures the right thing, that its
artefact is correct, or that its conditions are honest. This is a smoke test.
It answers one question - would this start? - and claims nothing else.
"""
import argparse
import ast
import io
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Directories holding runnable probes. results/**/work/ is excluded on purpose:
# those are archived scripts kept as the record of a past run, not tools anyone
# is expected to launch again.
ROOTS = (# The top level itself. Omitting it left scripts/arms.py - the sweep
         # runner every stage from 2 on goes through - and
         # scripts/detect-machine.py unchecked: `git ls-files "scripts/*.py"`
         # returned 76 files and this checker saw 74. A git pathspec glob
         # matches across directory separators, so this entry alone is a
         # superset of the ones below; they stay because they are the map of
         # where probes are expected to live, and because a checker that
         # silently stopped covering a directory is the failure this file is
         # about.
         "scripts",
         "scripts/bench", "scripts/power", "scripts/verify", "scripts/agentic",
         "scripts/vision", "scripts/quant-ladder", "scripts/report",
         # scripts/lib is not a probe directory, but every probe now imports
         # from it to find the server, the weights and the card. A library that
         # fails to import takes every probe down with it, so it is checked
         # here rather than discovered one probe at a time.
         "scripts/lib")

# A probe is a script with a main() or an argparse call. A library module has
# neither and is exercised by the import check alone.
def looks_runnable(src):
    return ("argparse" in src or "def main(" in src
            or '__name__ == "__main__"' in src)


def tracked_py():
    out = subprocess.run(["git", "ls-files"] + [r + "/*.py" for r in ROOTS],
                         cwd=REPO, capture_output=True, text=True, timeout=60)
    return sorted(f for f in out.stdout.splitlines() if f.strip())


def _calls(node):
    """Names invoked by a top-level expression, unwrapping print()/sys.exit()."""
    out = []
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
        stack = [node.value]
        while stack:
            c = stack.pop()
            f = c.func
            if isinstance(f, ast.Name):
                out.append(f.id)
            elif isinstance(f, ast.Attribute):
                out.append(f.attr)
            for a in c.args:
                if isinstance(a, ast.Call):
                    stack.append(a)
    return out


def _runs_on_import(tree):
    """(lineno, source-ish) of a module-level call to main()/run(), else None."""
    defined = {n.name for n in tree.body
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    guarded = any(isinstance(n, ast.If) and "__name__" in ast.dump(n.test)
                  for n in tree.body)
    if guarded:
        return None
    for n in tree.body:
        for name in _calls(n):
            if name in defined and name in ("main", "run"):
                return (n.lineno, "%s()" % name)
    return None


def check(rel):
    """Return (ok, stage, detail). Stops at the first failing stage."""
    path = os.path.join(REPO, rel)
    try:
        src = io.open(path, encoding="utf-8", errors="replace").read()
    except Exception as exc:
        return False, "read", "%s: %s" % (type(exc).__name__, exc)

    try:
        ast.parse(src, path)
    except SyntaxError as exc:
        return False, "parse", "line %s: %s" % (exc.lineno, exc.msg)

    # A probe must not DO anything when imported. This check exists because the
    # smoke test loads every module's top level: a bare main() at module level
    # turns the cheap pre-check into a real GPU job, and once left an orphaned
    # llama-perplexity holding 13.79 GB of the card.
    bad = _runs_on_import(ast.parse(src, path))
    if bad:
        return (False, "guard",
                'line %d: `%s` runs at module level. Wrap it as '
                'if __name__ == "__main__": %s'
                % (bad[0], bad[1], bad[1]))

    # Import the module's top level in a SUBPROCESS. In-process would let a
    # probe's imports and globals leak into the next check, and one that calls
    # sys.exit at import time would kill the checker.
    loader = (
        "import importlib.util,sys,os;"
        "sys.path.insert(0, os.path.dirname(r'%s'));"
        "spec=importlib.util.spec_from_file_location('probe_under_test',r'%s');"
        "m=importlib.util.module_from_spec(spec);"
        "spec.loader.exec_module(m)" % (path, path))
    try:
        # MEASURED_INFERENCE_DRY_RUN makes gpu_lock refuse to take the card.
        # The __main__ guards should mean nothing tries; this is the net for
        # when one regresses, so a smoke test can never launch a real job.
        env = dict(os.environ, MEASURED_INFERENCE_DRY_RUN="1")
        p = subprocess.run([sys.executable, "-c", loader], env=env,
                           capture_output=True, text=True, timeout=25)
    except subprocess.TimeoutExpired:
        return (False, "import",
                "did not finish importing in 25 s - this module does "
                "WORK at import time, which means anything that merely "
                "reads it pays for that work")
    if p.returncode != 0:
        tail = (p.stderr or p.stdout or "").strip().splitlines()
        return False, "import", tail[-1] if tail else "exit %d" % p.returncode

    if not looks_runnable(src):
        return True, "import", "library module: imported, no CLI to check"

    try:
        q = subprocess.run([sys.executable, path, "--help"],
                           capture_output=True, text=True, timeout=25)
    except subprocess.TimeoutExpired:
        return (False, "--help",
                "--help did not return in 25 s; a help request must "
                "never start work")
    if q.returncode != 0:
        tail = (q.stderr or q.stdout or "").strip().splitlines()
        return False, "--help", tail[-1] if tail else "exit %d" % q.returncode

    return True, "--help", "starts and builds its help"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fail", action="store_true",
                    help="exit non-zero if any probe fails, for a hook or CI")
    a = ap.parse_args()

    files = tracked_py()
    bad = []
    print("=" * 74)
    print("PROBE SMOKE TEST - would each of these actually start?")
    print("=" * 74)
    print("%d tracked scripts under %s\n" % (len(files), ", ".join(ROOTS)))

    for rel in files:
        ok, stage, detail = check(rel)
        if ok:
            print("  ok      %-46s %s" % (rel, stage))
        else:
            print("  FAIL    %-46s %s" % (rel, stage))
            print("          %s" % detail[:160])
            bad.append((rel, stage, detail))

    print()
    print("=" * 74)
    if bad:
        print("%d of %d FAILED. Each one cannot measure anything, and would "
              "have failed\nAFTER a human committed GPU time to it."
              % (len(bad), len(files)))
    else:
        print("All %d start. Parsing is not loading; this checked loading."
              % len(files))
    print("=" * 74)

    if a.fail and bad:
        sys.exit(1)


if __name__ == "__main__":
    main()
