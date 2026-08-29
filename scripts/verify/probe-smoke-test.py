#!/usr/bin/env python3
"""Can every probe in this repository actually START?

    py scripts/verify/probe-smoke-test.py [--fail] [--baseline FILE]

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

THE BASELINE, because red lines that are always there get scrolled past, and
that is the exact amount of noise that gets a real failure ignored. Known
failures are written down - one row each in
`scripts/verify/smoke-baseline.json`, with the reason, the bucket and the date
- and reported apart from NEW. The exit code follows NEW alone; `--fail` still
fails on any failure at all.

The baseline is EMPTY as of 2026-08-29, and that is the state to keep. It held
18 of 83 that morning; 16 were scripts with no argument parser, so `--help` did
not get answered, it got RUN - and the missing llama-server was only where they
happened to stop. On a machine where setup has built one, `--help` would have
launched a real job. All 18 were fixed rather than re-baselined, and the
`cleared` block in the baseline records what each one was. A row that starts
passing is reported as STALE, because a baseline nobody prunes becomes the
thing it was written to prevent.

Nothing is skipped and nothing is suppressed. Every check still runs on every
file and every failure is still printed; the baseline decides only which of
them you have to think about. A row whose probe starts passing is printed as
PASSES NOW, because a stale baseline is its own defect, and a baseline nobody
prunes is where failures go to be forgotten.

WHAT THIS CHECKER DOES TO THE TREE, which you are owed before you run it on a
machine mid-campaign. A script with no argument parser does not ANSWER --help,
it runs - the count is printed at the end of every run - so this checker starts
those probes. One of them has already destroyed a result:
`scripts/quant-ladder/three-file-12gb-fit.py` overwrote its own JSON with an
empty one under a smoke test, which is why it now tests `sys.argv` by hand.
Two nets are in place and neither is complete:

  * MEASURED_INFERENCE_DRY_RUN=1 is set for BOTH subprocesses, the import and
    the --help, so nothing started here can take the card. Until 2026-08-29 it
    was set for the import only.
  * The working tree is compared before and after, so a file written during the
    run is named in this output instead of found days later in `git status`.
    It compares `git status --porcelain` lines, so it catches a file that
    APPEARS and a tracked file that becomes modified; a file that was already
    dirty and gets rewritten keeps its line and passes unseen.

Measured 2026-08-29: one run wrote the campaign's 280,937-byte quant-ladder
figure at the IMPORT stage, from scripts/quant-ladder/make-ladder-png.py -
a module whose whole body is top level, which the runnable test below calls a
library module and imports.
"""
import argparse
import ast
import io
import json
import os
import re
import subprocess
import sys
import textwrap

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASELINE = os.path.join(REPO, "scripts", "verify", "smoke-baseline.json")

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


def answers_help(src):
    """Could this script answer --help, or would --help just run it?

    argparse handles it; so does a hand-written `if "--help" in sys.argv`. With
    neither, `python probe.py --help` executes the probe, which is how a smoke
    test came to overwrite a published result.

    The test is for the LITERAL, quoted, as code would write it - a usage line
    in a docstring mentions --help without handling it.
    """
    return ("argparse" in src or "print_help" in src
            or '"--help"' in src or "'--help'" in src
            or '"-h"' in src or "'-h'" in src)


# One hint per failure family, printed under a NEW failure so the reader is not
# sent to grep for the fix. Both are sourced from files in this repository.
HINTS = (
    (re.compile(r"No module named '(numpy|matplotlib|scipy)'"),
     "publish-side dependency: setup.sh installs requirements-min.txt unless "
     "you pass --publish (requirements.txt adds numpy, matplotlib, scipy)"),
    (re.compile(r"llama-server"),
     "no llama.cpp build on this box: scripts/setup.sh --cuda, or set "
     "LLAMA_SERVER / LLAMA_DIR (see scripts/lib/paths.py)"),
)

# A baseline row states WHY a probe fails, and a reason that has stopped being
# true is not a baseline, it is cover. Where the stated cause is checkable from
# the source without running anything, it is rechecked on every run.
CAUSE_CHECKS = {
    "no-argparse": lambda src: "argparse" not in src,
}


def shortpath(path):
    """Path relative to the repo, or absolute when it is not under it.

    os.path.relpath raises on Windows when the two paths sit on different
    drives, which is exactly where a --baseline on another volume lands.
    """
    try:
        rel = os.path.relpath(path, REPO)
    except ValueError:
        return path
    if rel.startswith(".."):
        return path
    return rel.replace("\\", "/")


def tracked_py():
    out = subprocess.run(["git", "ls-files"] + [r + "/*.py" for r in ROOTS],
                         cwd=REPO, capture_output=True, text=True, timeout=60)
    return sorted(f for f in out.stdout.splitlines() if f.strip())


def tree_state():
    """`git status --porcelain` as a set of lines, or None if git cannot say.

    Compared before and after the run so that a file a probe writes is named
    here. Other work in the same checkout moves these lines too, so the output
    says the tree CHANGED WHILE this ran and never that this run caused it.
    """
    try:
        out = subprocess.run(["git", "status", "--porcelain"], cwd=REPO,
                             capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            return None
        return set(l for l in out.stdout.splitlines() if l.strip())
    except Exception:
        return None


def load_baseline(path):
    """(rows keyed by path, recorded date, error-or-None)."""
    try:
        with io.open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except IOError:
        return {}, None, "no baseline file at %s - every failure counts as NEW" % path
    except ValueError as exc:
        return {}, None, "%s is not valid JSON (%s) - every failure counts as NEW" % (path, exc)
    rows = {}
    for e in doc.get("entries", []):
        if "path" in e:
            rows[e["path"]] = e
    return rows, doc.get("recorded"), None


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

    # MEASURED_INFERENCE_DRY_RUN makes gpu_lock refuse to take the card. It is
    # set for BOTH subprocesses below: the __main__ guards should mean nothing
    # tries during the import, and a script with no argument parser RUNS on
    # --help rather than answering it, which is a launch on purpose. Neither
    # subprocess may reach the GPU, so a smoke test can never start a real job.
    env = dict(os.environ, MEASURED_INFERENCE_DRY_RUN="1")

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
        q = subprocess.run([sys.executable, path, "--help"], env=env,
                           capture_output=True, text=True, timeout=25)
    except subprocess.TimeoutExpired:
        return (False, "--help",
                "--help did not return in 25 s; a help request must "
                "never start work")
    if q.returncode != 0:
        tail = (q.stderr or q.stdout or "").strip().splitlines()
        return False, "--help", tail[-1] if tail else "exit %d" % q.returncode

    return True, "--help", "starts and builds its help"


def hint_for(detail):
    for pat, text in HINTS:
        if pat.search(detail):
            return text
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fail", action="store_true",
                    help="exit non-zero if ANY probe fails, known or new, "
                         "for a hook or CI (the default fails on NEW only)")
    ap.add_argument("--baseline", default=BASELINE,
                    help="the known-failure file (default: %(default)s)")
    a = ap.parse_args()

    rows, recorded, base_err = load_baseline(a.baseline)
    files = tracked_py()
    before = tree_state()

    print("=" * 74)
    print("PROBE SMOKE TEST - would each of these actually start?")
    print("=" * 74)
    print("%d tracked scripts under %s" % (len(files), ", ".join(ROOTS)))
    if base_err:
        print("BASELINE: %s" % base_err)
    else:
        print("baseline: %s - %d known failures, recorded %s"
              % (shortpath(a.baseline),
                 len(rows), recorded or "undated"))
    print("")

    known, new, ok_paths, runs_instead = [], [], [], []
    for rel in files:
        src = io.open(os.path.join(REPO, rel), encoding="utf-8",
                      errors="replace").read()
        if looks_runnable(src) and not answers_help(src):
            runs_instead.append(rel)

        ok, stage, detail = check(rel)
        if ok:
            ok_paths.append(rel)
            print("  ok      %-46s %s" % (rel, stage))
            continue

        row = rows.get(rel)
        why = None
        if row is None:
            why = "not in the baseline"
        elif row.get("stage") != stage:
            why = ("the baseline records it failing at %s, not %s"
                   % (row.get("stage"), stage))
        elif row.get("cause") in CAUSE_CHECKS and not CAUSE_CHECKS[row["cause"]](src):
            why = ("the baseline reason no longer holds: cause is recorded as "
                   "%s" % row["cause"])

        if why is None:
            known.append((rel, stage, row))
            print("  known   %-46s %s" % (rel, stage))
            print(textwrap.fill(row.get("reason", ""), width=84,
                                initial_indent=" " * 10,
                                subsequent_indent=" " * 10))
        else:
            new.append((rel, stage, detail, why))
            print("  NEW     %-46s %s" % (rel, stage))
            print("          %s" % detail[:160])
            print("          (%s)" % why)
            h = hint_for(detail)
            if h:
                print(textwrap.fill("hint: " + h, width=84,
                                    initial_indent=" " * 10,
                                    subsequent_indent=" " * 16))

    # A row whose probe passes, or whose file has gone, is a stale row. Print
    # it: a baseline that is never pruned stops being a record of anything.
    stale = []
    for path, row in sorted(rows.items()):
        if path not in files:
            stale.append((path, "not a tracked script any more"))
        elif path in ok_paths:
            stale.append((path, "PASSES NOW - delete this row"))

    print("")
    print("=" * 74)
    if new:
        print("%d NEW, %d known, %d start, of %d checked."
              % (len(new), len(known), len(ok_paths), len(files)))
        print("")
        print("A NEW failure cannot measure anything, and would have failed AFTER a")
        print("human committed GPU time to it. If you prove one is older than your")
        print("changes - `git log -1 --format=%cd -- <path>` and read the probe -")
        print("add a row to %s with its reason and"
              % shortpath(a.baseline))
        print("today's date. Never by deleting a check.")
    else:
        print("0 NEW. %d known, %d start, of %d checked."
              % (len(known), len(ok_paths), len(files)))
        print("Parsing is not loading; this checked loading. Every known failure is")
        print("a row in %s with its reason and date."
              % shortpath(a.baseline))

    if stale:
        print("")
        for path, note in stale:
            print("  STALE   %-46s %s" % (path, note))

    if runs_instead:
        print("")
        print("%d of the %d have no argument parser and no --help test, so `--help`"
              % (len(runs_instead), len(files)))
        failing = set(r for r, _s, _row in known) | set(r for r, _s, _d, _w in new)
        print("does not get answered, it gets RUN. %d of those are failures listed"
              % len([r for r in runs_instead if r in failing]))
        print("above; the rest exit 0 because the probe ran to the end. DRY_RUN")
        print("keeps all of them off the GPU. It does not keep them from writing")
        print("their files.")

    after = tree_state()
    if before is not None and after is not None and after != before:
        print("")
        print("THE WORKING TREE CHANGED WHILE THIS RAN. Not proof this run did it -")
        print("anything else touching the checkout moves these lines too - but a")
        print("probe started by the import or --help stage is the usual cause:")
        for line in sorted(after - before):
            print("    %s" % line)

    print("=" * 74)

    if new or (a.fail and known):
        sys.exit(1)


if __name__ == "__main__":
    main()
