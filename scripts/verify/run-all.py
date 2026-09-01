#!/usr/bin/env python3
"""Every check this repository can run without a GPU, in one command.

    python scripts/verify/run-all.py
    python scripts/verify/run-all.py --list
    python scripts/verify/run-all.py --only arms --verbose

WHY THIS EXISTS. The checks were there and the command was not. This runner has
seven members, each answering a different question with no card, no weights and
no network - four of them in `scripts/verify/`, three beside the instrument each
one checks - and until 2026-08-30 the only way to run them was to know all seven
file names, so an agent on a fresh clone ran the one it had been told about and
shipped past the other six. `scripts/verify/test-arms.py` was named in no
markdown file in the repository at all: the lane that proves the sweep runner
still records, resumes, discards, orders and stops the way the rules require
existed for exactly as long as somebody remembered it. The list below is the
whole membership and `--list` prints it; where a check lives decides nothing,
and two more no-GPU programs are left out ON PURPOSE, named at the end with the
reason.

WHAT IT RUNS, cheapest first, and the question each one answers:

  detect-machine   does the memory-topology classifier still read every
                   recorded box shape the same way? Its own `--self-test`,
                   fixtures only, no hardware and nothing written: that
                   verdict decides whether a model is priced against board
                   memory or against system RAM (rules 13, 14)
  openvino-quant   is the arithmetic behind every bpw_effective right? Replays
                   the 600 per-tensor records in results/openvino-groundtruth/
                   through scripts/lib/openvino_quant.py (rules 1 and 3)
  ladder-png       can the renderer of the published quant-ladder figure still
                   be pointed somewhere else? Four --out cases in a temporary
                   directory; loads no source and draws nothing. It needs
                   matplotlib and scipy, which `probe-smoke` already needs in
                   order to import that file at all
  bench-selftest   does the benchmark harness still agree with rule 21 - the
                   seven-set suite, the cap, the -c sizing?
  instrument-guard does anything published lean on a file git does not have?
                   (rule 29: an ignore rule is a claim about re-creatability)
  probe-smoke      would every probe in the tree actually START? Parses,
                   imports and asks --help of all of them (rule 25: cheap
                   probes before expensive hours)
  arms-lane        does scripts/arms.py still record, resume, discard, order
                   and stop the way a sweep depends on? Real subprocesses
                   against a stub server (rules 7, 12, 20, 25, 28, 30)

ALL OF THEM RUN, ALWAYS. A runner that stops at the first failure reports one
problem and hides the rest, and the ones it hides are the ones nobody looks for
after the first red line. The exit code is 1 if any check failed and 0
otherwise; `--fail-fast` is there for a hook that wants the other behaviour and
is not the default.

WHAT IT DOES NOT RUN, and why, because a list of exclusions nobody wrote down
becomes a list of checks nobody runs:

  scripts/verify/portability-audit.py   a REPORT, not a verdict. It exits 0
        with 70 blockers listed and only fails under --fail-on-blocker, so
        putting it here would add a member that cannot go red. Run it by hand
        before taking this repository to a machine it has not run on.
  scripts/verify/condition-check.py     needs a target document, and the only
        one here is the closed worked example. A runner that always checks one
        shipped page is checking that page, not the tree.
  scripts/verify/close-three.py         measures. It launches a server and
        reads RAM and watts, which is a GPU job under rule 20.
  scripts/verify/energy-four-sets.py    measures. Four benchmark runs.
  scripts/verify/fake-llama-server.py   a fixture, exercised by arms-lane.

`instrument-guard` IS THE MEMBER MOST LIKELY TO GO RED ON YOUR MACHINE, and
that is the check working rather than noise. It compares what tracked files NAME
against what git HAS and what is on your disk, so its verdict depends on files a
checkout may or may not carry. It failed here on 2026-08-30 on two files, and
each was closed the way this check demands - by adding the file, or by writing
down how it is remade - rather than by dropping the member:

  results/qwen38-27b-blind/data/overnight/overnight.log   the transcript of the
        overnight measurement queue in scripts/quant-ladder/overnight.py, which
        wrote four of the five tracked JSONs beside it. It carries the per-probe
        readings and the host state each was taken under, and re-running the
        queue measures the card again rather than remaking the file, so it is
        in git. `*.log` at .gitignore:21 names it, so the scoped negation that
        keeps a plain `git add` honest belongs beside the
        `!results/openvino-groundtruth/*.log` one, for the same stated reason
        (rule 29). The guard reaches it by BASENAME, through PROMPTS.md's
        overnight recipe - which names a DIFFERENT file,
        results/<SLUG>/work/overnight.log, the detached sweep's stdout, and
        PROMPTS.md:1250 is right that that one is a working file
  results/qwen38-27b-blind/figures/quant-ladder.png       a derived figure, and
        the one case the allow-list is for: `python scripts/quant-ladder/
        make-ladder-png.py` remakes it byte-identically - md5
        11159d63745bb9e3267516d93b5e165d, two fresh renders against the copy on
        disk, measured 2026-08-30 - so it is allow-listed with that sentence
        rather than committed as 280,937 bytes

WHETHER A CLEAN CLONE OF THE SAME COMMIT IS GREEN IS NOT ESTABLISHED. The
figure is absent from a checkout that has never run anything, which would turn
its row into the "named but nowhere on disk" warning the same check prints
without failing - but the clone taken to confirm that did not check out on this
filesystem, so it is an expectation and not a reading. Read the names the check
prints before deciding a row is not yours, and clear one by adding the file or
by writing in `scripts/verify/instrument-guard-allow.txt` how it would be
remade - never by dropping the member.

ONE GPU JOB AT A TIME STILL APPLIES (rule 20). Nothing here takes the card, but
`arms-lane` launches stub servers through the same `gpu_lock` a real sweep uses,
so it refuses to start while a live sweep holds the lock and says so. Check with
`python scripts/bench/gpu_lock.py status` before reading that failure as a
defect in the lane.

Stdlib only. Each check runs as its own subprocess with this interpreter, from
the repository root, WITH THE ENVIRONMENT PASSED THROUGH UNCHANGED, because each
member already decides what its own children see: `arms-lane` STRIPS
MEASURED_INFERENCE_DRY_RUN (scripts/verify/test-arms.py:225) since it wants a
real stub launch, and arms.py refuses at argument-parse time when that variable
is set without --dry-run (scripts/arms.py:1971) - before any launch, and so
before gpu_lock is ever consulted; and `probe-smoke` SETS it for both of its
own subprocesses so that nothing it starts can reach the card. Neither of them
cares what you exported; running this under MEASURED_INFERENCE_DRY_RUN=1 changes
no member's verdict.
"""

import argparse
import os
import subprocess
import sys
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# (name, script relative to the repo, extra argv, timeout seconds, one line
# saying what a failure MEANS). Ordered cheapest first, measured 2026-08-30 on
# Windows 11 / Python 3.11: 0.1, 0.1, 0.7, 2.3, 2.9, 20.8 and 23.5 s, 50 s the
# whole way through. Order is a courtesy only - every member runs regardless.
# `scripts/setup.sh` on POSIX, `scripts/setup.ps1` on Windows -- the two write
# the same bin/llama.cpp/INSTALL.json, and naming the wrong one is a dead end
# for whoever reads it. Picked the way scripts/lib/paths.py already picks it.
SETUP_HINT = (r"scripts\setup.ps1" if os.name == "nt" else "./scripts/setup.sh")


# requirements-min.txt is COLLECTION ONLY and is what plain setup.sh installs;
# requirements.txt adds the publishing three and needs --publish. A borrowed
# box that only collects is CORRECTLY configured without matplotlib, so a check
# that needs one must not be able to turn this gate red on it. See MIN_PKGS.
MIN_PKGS = ("requests", "PIL", "Pillow")
PUBLISH_PKGS = ("numpy", "matplotlib", "scipy")


def _installs(mod):
    """The command that would supply `mod`, or None if we do not ship it."""
    if mod in MIN_PKGS:
        return "%s            (requirements-min.txt)" % SETUP_HINT
    if mod in PUBLISH_PKGS:
        return "%s --publish  (requirements.txt)" % SETUP_HINT
    return None


def _missing_module(out):
    """The module name in a ModuleNotFoundError, or None.

    A check that dies importing matplotlib has not found a defect; it has
    found a box that has not run setup. The two read identically in an exit
    code and must not read identically in the report.
    """
    lines = [x.rstrip() for x in (out or "").splitlines()]
    lines = [x for x in lines if x.strip()]
    if not lines:
        return None
    # ONLY the last line. A check that DIED on an import ends on the error; a
    # check that merely REPORTS one -- probe-smoke names every script in this
    # tree that cannot import, which is its whole job -- ends on its own
    # summary. Scanning the whole output confuses the two and would let this
    # runner skip the very check that exists to catch a probe that cannot
    # start, on the machine where that matters most.
    last = lines[-1].strip()
    if last.startswith("ModuleNotFoundError: No module named"):
        return last.split("named", 1)[1].strip().strip("'\"")
    return None


CHECKS = (
    ("detect-machine", "scripts/detect-machine.py", ("--self-test",), 300,
     "the memory-topology classifier changed its mind about a recorded box "
     "shape, so plan-campaign.py would price a model against the wrong "
     "memory pool"),
    ("openvino-quant", "scripts/verify/test-openvino-quant.py", (), 300,
     "a published bits-per-weight for an OpenVINO run is computed from a "
     "table that no longer matches the run that checked it"),
    ("ladder-png", "scripts/quant-ladder/make-ladder-png.py", ("--self-test",),
     300,
     "the renderer of the published quant-ladder figure cannot draw it "
     "from the sources in this tree, so the figure a reader is shown and "
     "the data under it have stopped agreeing"),
    ("bench-selftest", "scripts/bench/selftest.py", (), 300,
     "the benchmark harness and rule 21 disagree about what the suite is"),
    ("instrument-guard", "scripts/verify/instrument-guard.py", (), 300,
     "something tracked names a file git does not have, so a published claim "
     "is one disk wipe from unreproducible (rule 29) - read the names it "
     "prints, they may be yours"),
    ("probe-smoke", "scripts/verify/probe-smoke-test.py", (), 900,
     "a probe in this tree cannot start, and it would have failed AFTER a "
     "human committed GPU hours to it"),
    ("arms-lane", "scripts/verify/test-arms.py", (), 900,
     "the sweep runner stopped recording, resuming, discarding, ordering or "
     "stopping the way results/ depends on"),
    ("watchdog-state", "scripts/verify/test-watchdog-state.sh", (), 120,
     "the campaign watchdog reports the wrong GPU state, so an idle card "
     "reads as busy and hours of card time are lost with the log silent"),
)


def _tee_stderr(stream, keep):
    """Echo the child's stderr line by line as it arrives, and keep a copy.

    Run on a thread so nothing is held back: the operator watching a 900 s
    check sees each line the moment the child writes it, and run_check still
    has the text afterwards to classify the exit by.
    """
    for line in iter(stream.readline, ""):
        sys.stderr.write(line)
        sys.stderr.flush()
        keep.append(line)


def run_check(name, rel, extra, timeout, verbose):
    """(ok, seconds, exit code, output). Never raises.

    `output` is what main()'s skip filter reads to tell an absent dependency
    from a defect, so it has to carry the child's diagnostics in BOTH modes.
    """
    # DISPATCH ON EXTENSION. This built every command as [sys.executable, ...],
    # so the suite could hold Python checks and nothing else -- a shell probe
    # registered here died with a SyntaxError that read like a broken check
    # rather than a wrong interpreter. The tree already ships shell probes
    # (scripts/verify/ubuntu-dryrun.sh); they belong in the same gate.
    target = os.path.join(REPO, *rel.split("/"))
    launcher = ["bash"] if rel.endswith(".sh") else [sys.executable]
    cmd = launcher + [target] + list(extra)
    t0 = time.time()
    try:
        if verbose:
            # Straight to the terminal, unbuffered, so a long check can be
            # watched rather than waited on.
            #
            # Until 2026-08-31 this branch returned out="" and threw the
            # child's diagnostics away. Measured that day on this Ubuntu box,
            # same absent matplotlib both times: `--only ladder-png` printed
            # "1 skipped for a missing dependency (ladder-png)" and exited 0,
            # while `--only ladder-png --verbose` printed "1 of 1 FAILED" and
            # exited 1 -- because _missing_module("") is None, so the row could
            # never be classified as SKIPPED and voted as a failure instead.
            # That is the outcome _missing_module's own docstring says must not
            # happen, reached through the flag an operator reaches for when the
            # box is slow, in the lane AGENTS.md makes the gate before any GPU
            # time.
            #
            # So: STDOUT still goes straight to the terminal, inherited, never
            # a pipe -- a Python child block-buffers a pipe and its output
            # would arrive in lumps at the end, which is the one thing
            # --verbose exists to prevent; answering this defect by capturing
            # everything would fix the verdict by breaking the flag. Only
            # stderr is piped, and it is TEED rather than captured: echoed as
            # it arrives (Python line-buffers stderr even into a pipe, and
            # detect-machine.py:2819 deliberately puts progress there) and kept
            # as well. An import that kills a check writes its traceback to
            # stderr, which is the line the classifier needs, and it is the
            # same text the non-verbose branch already classifies by -- that
            # one appends stderr last and _missing_module reads only the last
            # line -- so the two modes now reach the same verdict by the same
            # evidence.
            keep = []
            with subprocess.Popen(cmd, cwd=REPO, stderr=subprocess.PIPE,
                                  text=True, errors="replace") as p:
                pump = threading.Thread(target=_tee_stderr,
                                        args=(p.stderr, keep))
                pump.start()
                try:
                    rc = p.wait(timeout=timeout)
                except BaseException:
                    # What subprocess.call did on timeout, kept: kill the child
                    # rather than leave it running behind a runner that has
                    # stopped waiting for it. Join the pump before the `with`
                    # closes the pipe it is still reading, then re-raise into
                    # the TimeoutExpired handler below.
                    p.kill()
                    p.wait()
                    pump.join()
                    raise
                pump.join()
            return rc == 0, time.time() - t0, rc, "".join(keep)
        p = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True,
                           errors="replace", timeout=timeout)
        return (p.returncode == 0, time.time() - t0, p.returncode,
                (p.stdout or "") + (p.stderr or ""))
    except subprocess.TimeoutExpired:
        return (False, time.time() - t0, None,
                "did not finish in %d s. A no-GPU check that hangs is a check "
                "nobody will keep running; find out what it is waiting for."
                % timeout)
    except OSError as exc:
        return False, time.time() - t0, None, "could not start: %s" % exc


def _head_and_tail(out, n):
    """The first n and last n lines, with one line saying what was dropped.

    A failing checker states its findings first and its verdict last, so a tail
    alone prints the verdict of a list the reader cannot see - which is what
    the first version of this runner did to instrument-guard's output.
    """
    lines = out.rstrip().splitlines()
    if len(lines) <= 2 * n:
        return lines
    return (lines[:n]
            + ["    ... %d line(s) not shown; --verbose runs it with its own "
               "output" % (len(lines) - 2 * n)]
            + lines[-n:])


def _summary_line(out):
    """The last line of a passing check that says anything.

    These checkers close with a rule of `=` characters, so the literal last
    line is a separator on every one of them.
    """
    for line in reversed(out.splitlines()):
        if any(ch.isalnum() for ch in line):
            return line.strip()
    return ""


def main():
    ap = argparse.ArgumentParser(
        description="Run every no-GPU check in this repository, in order, and "
                    "exit non-zero if any of them fails.")
    ap.add_argument("--only", metavar="SUBSTRING", default=None,
                    help="run only checks whose name contains this")
    ap.add_argument("--list", action="store_true",
                    help="list the checks, their scripts and what a failure "
                         "means, and run nothing")
    ap.add_argument("--verbose", action="store_true",
                    help="let each check write straight to this terminal "
                         "instead of capturing it (the default prints the "
                         "tail of a failing check and the last line of a "
                         "passing one)")
    ap.add_argument("--lines", type=int, default=20, metavar="N",
                    help="lines to print from EACH END of a failing check's "
                         "output (default: %(default)s; the whole of it with "
                         "--verbose). Both ends, because a checker states its "
                         "findings at the top and its verdict at the bottom, "
                         "and a tail alone shows the verdict of a list you "
                         "cannot see")
    ap.add_argument("--fail-fast", action="store_true",
                    help="stop at the first failure. NOT the default: a "
                         "runner that stops at the first red line reports one "
                         "problem and hides the rest")
    a = ap.parse_args()

    chosen = [c for c in CHECKS if not a.only or a.only in c[0]]
    if a.list:
        for name, rel, extra, timeout, why in CHECKS:
            print("%-17s %s %s" % (name, rel, " ".join(extra)))
            print("%-17s failure means: %s" % ("", why))
        return 0
    if not chosen:
        print("no check matches %r. Known: %s"
              % (a.only, ", ".join(c[0] for c in CHECKS)))
        return 2

    print("=" * 78)
    print("NO-GPU VERIFICATION LANE - %d check(s), cheapest first" % len(chosen))
    print("=" * 78)
    print("python : %s" % sys.executable)
    print("repo   : %s" % REPO)
    print("Nothing here takes the card. arms-lane goes through gpu_lock all the")
    print("same, so it refuses while a live sweep holds it (rule 20).\n")

    results, t_all = [], time.time()
    for name, rel, extra, timeout, why in chosen:
        sys.stdout.write("  running %-17s %s ... " % (name, rel))
        sys.stdout.flush()
        if a.verbose:
            print("")
        ok, secs, rc, out = run_check(name, rel, extra, timeout, a.verbose)
        results.append((name, rel, ok, secs, rc, out, why))
        if a.verbose:
            print("  %-9s %-17s %6.1fs" % ("ok" if ok else "FAILED", name, secs))
        elif ok:
            print("ok   %6.1fs  %s" % (secs, _summary_line(out)[:64]))
        else:
            print("FAILED %4.1fs  exit %s" % (secs, rc))
        if not ok and a.fail_fast:
            print("\n--fail-fast: stopping here. %d check(s) not run."
                  % (len(chosen) - len(results)))
            break

    # A check that died importing one of the PUBLISHING three never ran, so it
    # found nothing. Counting it as a failure would make this gate permanently
    # red on exactly the machine it exists for: a borrowed box that collects
    # and never publishes. It is reported loudly and separately, and it does
    # not vote.
    #
    # PUBLISH_PKGS AND NOTHING ELSE. Until 2026-08-31 the test here was "names
    # a module, and that module is not in MIN_PKGS", which downgraded EVERY
    # other absent import to a non-voting SKIP. Measured that day on this box:
    # a synthetic "No module named openvino_quant" -- a broken import inside
    # this repository -- and "No module named distutils" -- a stdlib module
    # deleted in 3.12, and the interpreter here is 3.14, two releases past the
    # 3.11 this lane was timed on -- both classified as skipped, both with a
    # None install hint, so the report said "a dependency this box does not
    # have. Not a defect" about a defect and printed no command that could
    # ever fix it. Those are the failures this gate exists to catch. The three
    # names the paragraph above is actually about are PUBLISH_PKGS; a missing
    # requests or Pillow means setup never ran at all and has always voted;
    # anything else votes as the failure it is.
    skipped = [r for r in results
               if not r[2] and _missing_module(r[5]) in PUBLISH_PKGS]
    skipped_names = set(r[0] for r in skipped)
    failed = [r for r in results if not r[2] and r[0] not in skipped_names]

    if skipped:
        print("")
        print("-" * 78)
        print("SKIPPED - a dependency this box does not have. Not a defect.")
        for name, rel, ok, secs, rc, out, why in skipped:
            mod = _missing_module(out)
            print("  %-17s no %s" % (name, mod))
            fix = _installs(mod)
            if fix:
                print("  %-17s install: %s" % ("", fix))
        print("-" * 78)

    if failed and not a.verbose:
        for name, rel, ok, secs, rc, out, why in failed:
            print("")
            print("-" * 78)
            print("FAILED  %s  (exit %s, %.1f s)" % (name, rc, secs))
            missing = _missing_module(out)
            if missing and _installs(missing):
                # The line below is the one place this tool could confidently
                # mislead. Every `why` in CHECKS describes a DEFECT, and on a
                # tree that has not run setup the cause is not a defect at all
                # -- it is an absent dependency. Printing the defect story here
                # sends a reader after a bug that is not there, on their first
                # command after a clone, which is the exact failure this
                # checker exists to prevent.
                #
                # `and _installs(missing)` since 2026-08-31, for the mirror
                # image of that mistake: a module NEITHER requirements file
                # ships -- an import broken inside this repository, or a stdlib
                # module a newer Python removed -- is not an environment and
                # setup.sh will never supply it, so telling a reader to run
                # setup is the same confident misdirection pointed the other
                # way. Only a name _installs() has a command for gets the
                # environment story; the rest get theirs.
                print("what it means: NOT A DEFECT, an environment: this box "
                      "has no %s. The check never ran." % missing)
                print("the fix:       %s   (then re-run this)" % SETUP_HINT)
            else:
                print("what it means: %s" % why)
                if missing:
                    print("               it died importing %s, which neither "
                          "requirements file installs - that import is the "
                          "finding, not this box." % missing)
            print("re-run it alone: python %s" % rel)
            print("-" * 78)
            for line in _head_and_tail(out, a.lines):
                print("    %s" % line)

    print("")
    print("=" * 78)
    tail = ""
    if skipped:
        # Say it in the headline. A green line over a silently skipped check is
        # how a gate stops meaning anything.
        tail = ", %d skipped for a missing dependency (%s)" % (
            len(skipped), ", ".join(sorted(skipped_names)))
    if failed:
        print("%d of %d FAILED in %.0f s: %s%s"
              % (len(failed), len(results), time.time() - t_all,
                 ", ".join(r[0] for r in failed), tail))
    else:
        print("%d of %d passed in %.0f s%s. No GPU, no weights, no network."
              % (len(results) - len(skipped), len(results),
                 time.time() - t_all, tail))
    print("=" * 78)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
