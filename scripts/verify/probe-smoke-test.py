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
before the run rather than after is worth the seconds this costs against the
GPU hour it protects.

WHAT IT DOES NOT CHECK. That the probe measures the right thing, that its
artefact is correct, or that its conditions are honest. This is a smoke test.
It answers one question - would this start? - and claims nothing else.

THE BASELINE, because red lines that are always there get scrolled past, and
that is the exact amount of noise that gets a real failure ignored. Known
failures are written down - one row each in
`scripts/verify/smoke-baseline.json`, with the reason, the bucket and the date
- and reported apart from NEW. The exit code follows NEW alone; `--fail` still
fails on any failure at all.

0 known failures, on a roster this run counts for itself and prints above the
results, and an empty baseline is the state to keep. It held 18 of 83 on the
morning of 2026-08-29; 16 were scripts with no argument parser, so `--help`
did not get answered, it got RUN - and the missing llama-server was only where
they happened to stop. On a machine where setup has built one, `--help` would
have launched a real job. All 18 were fixed rather than re-baselined, and the
`cleared` block in the baseline records what each one was. A row that starts
passing is reported as STALE, because a baseline nobody prunes becomes the
thing it was written to prevent.

THE ROSTER MOVES, so the only trustworthy count is the one this run prints -
the `N tracked scripts under ...` line above the results, recounted from `git
ls-files` every time. It was 83 on 2026-08-29 and larger the next day, because
other work in the same tree adds checkers, and that is why no roster size is
written down in this header at all: a sentence that names one is quoting the
day it was typed and starts lying on the day after. `18 of 83` carries its
date for the same reason, and is in addition the reading from BEFORE those
eighteen were fixed.

Nothing is skipped and nothing is suppressed. Every check still runs on every
file and every failure is still printed; the baseline decides only which of
them you have to think about. A row whose probe starts passing is printed as
PASSES NOW, because a stale baseline is its own defect, and a baseline nobody
prunes is where failures go to be forgotten.

WHAT THIS CHECKER DOES TO THE TREE, which you are owed before you run it on a
machine mid-campaign. A script with no argument parser does not ANSWER --help,
it runs - every one of them is NAMED at the end of every run - so this checker
starts those files. One of them has already destroyed a result:
`scripts/quant-ladder/three-file-12gb-fit.py` overwrote its own JSON with an
empty one under a smoke test, which is why it now tests `sys.argv` by hand.
Three nets are in place:

  * MEASURED_INFERENCE_DRY_RUN=1 is set for BOTH subprocesses, the import and
    the --help, so nothing started here can take the card. Until 2026-08-29 it
    was set for the import only.
  * The working tree is compared before and after the whole run, so a file
    written during it is named in this output instead of found days later in
    `git status`. It compares `git status --porcelain` lines, so it catches a
    file that APPEARS and a tracked file that becomes modified; a file that was
    already dirty and gets rewritten keeps its line and passes unseen.
  * The tree is compared around EACH SUBPROCESS, one file at a time - the
    import, and the --help where there is one - and the closing blocks print
    what each stage wrote. The whole-run diff can only say that something
    moved; this says which file moved it and which of its two stages did.
    Until 2026-08-30 the import stage was not watched, which is the wrong
    subprocess for the incident below: that write happened at IMPORT, from a
    file that answered no --help at all.

WHAT `--help` COSTS IS NOT ONE ANSWER, which is why the closing block names the
files instead of counting them. `scripts/lib/` is on the roster because a
library that fails to import takes every probe down with it, not because
anything there is launched by a stage; a `__main__` block in one of those that
prints a table and exits is not the failure mode this file is about, and
reporting it in the same breath as a probe that would have taken the card is
how a real warning gets scrolled past. The line says which directory each file
lives in, and what it did to the tree when this checker ran it.

Measured 2026-08-29 and fixed 2026-08-30: one run wrote the campaign's
280,937-byte quant-ladder figure at the IMPORT stage, from
scripts/quant-ladder/make-ladder-png.py, whose whole body was module level - so
the runnable test below called it a library module and imported it, and the
cheap pre-check rewrote a published figure. That file now carries a main(), an
argument parser and a --check that draws nothing; importing it reads no file
and writes none, and it is checked at the --help stage like any other script.
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

# Of those, the ones that are NOT probe directories. Nothing under here is
# launched by a stage file; these modules are on the roster because every probe
# imports them, so one that fails to import takes every probe down with it.
# The distinction is used in exactly one place - the closing block, where "this
# file runs when you ask it for --help" means something very different for a
# library that prints a table than for a probe that would take the card.
LIBRARY_ROOTS = ("scripts/lib",)


def is_library_path(rel):
    return rel.startswith(tuple(r + "/" for r in LIBRARY_ROOTS))


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


def _stage_delta(before):
    """(the tree now, the lines that APPEARED since `before`).

    None for the lines when nothing could be compared - `before` unknown, or
    git unable to answer - which is not the same as the empty list: [] is a
    measurement that this stage wrote nothing, and the closing blocks say so
    in those words. The state is returned as well as the delta so that the
    next stage, and the next FILE, can be compared against it: the checks are
    serial and nothing else runs in between, so one `git status` per stage
    serves as both the after of one and the before of the next.
    """
    after = tree_state()
    if before is None or after is None:
        return after, None
    return after, sorted(after - before)


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


def check(rel, tree_before=None):
    """Return (ok, stage, detail, wrote, tree). Stops at the first failing stage.

    `wrote` maps each STAGE THAT RAN A SUBPROCESS - "import", "--help" - to the
    `git status --porcelain` lines that appeared around that one subprocess.
    Both are watched, and the import one is not decoration: the write this
    block exists to name, the 280,937-byte figure rewritten on 2026-08-29, was
    an IMPORT-stage write by a file with no parser at all. Until 2026-08-30
    only the --help stage was measured, so the net was around the wrong
    subprocess for the incident printed at the top of this file.

    `tree` is the state this call leaves behind, for the next file to be
    compared against - the checks are serial and nothing runs in between, so
    one `git status` per stage is both the after of one and the before of the
    next. That is one or two per file, ~30 ms each on the machine this was
    written on, measured 2026-08-30.
    """
    tree = tree_before
    wrote = {}
    path = os.path.join(REPO, rel)
    try:
        src = io.open(path, encoding="utf-8", errors="replace").read()
    except Exception as exc:
        return False, "read", "%s: %s" % (type(exc).__name__, exc), wrote, tree

    try:
        ast.parse(src, path)
    except SyntaxError as exc:
        return False, "parse", "line %s: %s" % (exc.lineno, exc.msg), wrote, tree

    # A probe must not DO anything when imported. This check exists because the
    # smoke test loads every module's top level: a bare main() at module level
    # turns the cheap pre-check into a real GPU job, and once left an orphaned
    # llama-perplexity holding 13.79 GB of the card.
    bad = _runs_on_import(ast.parse(src, path))
    if bad:
        return (False, "guard",
                'line %d: `%s` runs at module level. Wrap it as '
                'if __name__ == "__main__": %s'
                % (bad[0], bad[1], bad[1]), wrote, tree)

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
        tree, wrote["import"] = _stage_delta(tree)
        return (False, "import",
                "did not finish importing in 25 s - this module does "
                "WORK at import time, which means anything that merely "
                "reads it pays for that work", wrote, tree)
    # The tree, immediately before and immediately after THIS file's import.
    # Nothing else runs in between - the checks are serial - so anything that
    # appears here was written by this one subprocess.
    tree, wrote["import"] = _stage_delta(tree)
    if p.returncode != 0:
        tail = (p.stderr or p.stdout or "").strip().splitlines()
        return (False, "import",
                tail[-1] if tail else "exit %d" % p.returncode, wrote, tree)

    if not looks_runnable(src):
        return (True, "import", "library module: imported, no CLI to check",
                wrote, tree)

    try:
        q = subprocess.run([sys.executable, path, "--help"], env=env,
                           capture_output=True, text=True, timeout=25)
    except subprocess.TimeoutExpired:
        tree, wrote["--help"] = _stage_delta(tree)
        return (False, "--help",
                "--help did not return in 25 s; a help request must "
                "never start work", wrote, tree)
    tree, wrote["--help"] = _stage_delta(tree)
    if q.returncode != 0:
        tail = (q.stderr or q.stdout or "").strip().splitlines()
        return (False, "--help",
                tail[-1] if tail else "exit %d" % q.returncode, wrote, tree)

    return True, "--help", "starts and builds its help", wrote, tree


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

    known, new, ok_paths, runs_instead, on_import = [], [], [], [], []
    tree = before
    for rel in files:
        src = io.open(os.path.join(REPO, rel), encoding="utf-8",
                      errors="replace").read()
        # For this file, is `--help` a question or a launch? check() measures
        # the tree around every subprocess either way, so the closing blocks
        # can say what THIS file wrote and at which stage rather than that
        # something somewhere did; this decides which block it is named in.
        launches_on_help = looks_runnable(src) and not answers_help(src)

        ok, stage, detail, wrote, tree = check(rel, tree_before=tree)
        if launches_on_help:
            runs_instead.append((rel, ok, wrote.get("--help")))
        if wrote.get("import"):
            on_import.append((rel, wrote["import"]))
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
        print("%s no argument parser and no --help test, so `--help` does not get"
              % ("1 of the %d has" % len(files) if len(runs_instead) == 1
                 else "%d of the %d have" % (len(runs_instead), len(files))))
        print("answered, it gets RUN. DRY_RUN keeps all of them off the GPU. It does")
        print("not keep them from writing their files, so each one is NAMED with what")
        print("it is and with what it did to the tree while this checker ran it:")
        for rel, ok, wrote in runs_instead:
            kind = ("LIBRARY, not a probe: %s is on the roster because every "
                    "probe imports from it, not because a stage launches it"
                    % os.path.dirname(rel)) if is_library_path(rel) else (
                   "PROBE: `--help` launched it, and on a box where setup has "
                   "built a llama-server it would reach the loader")
            print("")
            print("  %s" % rel)
            print(textwrap.fill(kind, width=84,
                                initial_indent=" " * 8, subsequent_indent=" " * 8))
            if not ok:
                print("        it FAILED, and the failure is listed above")
            elif wrote is None:
                print("        exited 0; what it wrote was not measured (git "
                      "could not answer)")
            elif wrote:
                print("        exited 0 AND WROTE %d path(s) - this is the "
                      "damage this block" % len(wrote))
                print("        exists to name:")
                for line in wrote:
                    print("            %s" % line)
            else:
                print("        exited 0 and wrote nothing: `git status "
                      "--porcelain` is unchanged")
                print("        across its --help, measured around that one "
                      "subprocess")

    if on_import:
        print("")
        print("%s WROTE TO THE TREE WHEN MERELY IMPORTED, which is the stage"
              % ("1 FILE" if len(on_import) == 1
                 else "%d FILES" % len(on_import)))
        print("this checker cannot avoid: it loads every module's top level, and so")
        print("does anything else that reads one of them for a single constant. The")
        print("280,937-byte published figure named at the top of this file was")
        print("rewritten at exactly this stage on 2026-08-29. It does not change the")
        print("exit code - naming it is the point:")
        for rel, lines in on_import:
            print("")
            print("  %s" % rel)
            for line in lines:
                print("            %s" % line)

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
