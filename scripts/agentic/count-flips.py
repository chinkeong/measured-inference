#!/usr/bin/env python3
"""How many exercises change verdict when NOTHING changes but the run?

    count-flips.py --run-a <telemetry-a.json> --run-b <telemetry-b.json>
                   [--out <path.json>]

WHY THIS NUMBER IS THE ONE MISSING NUMBER. This campaign published that the
2-bit and 4-bit files solved different subsets of aider's polyglot benchmark:
sixty of 225 exercises were solved by exactly one of them, thirty by each. It
has never been able to say how much of that sixty is the QUANTISATION and how
much is the BENCHMARK, because each arm was run once and a benchmark that gives
a model a second attempt at its own failing tests is not deterministic.

So sixty has only ever been publishable as a CEILING. Every document that
quotes it says so, and says that no share of it may be attributed to the
quantisation until this measurement exists.

This is that measurement: the same file, the same flags, the same machine, run
twice. Whatever flips here flipped for no reason at all.

PAIRING, and why it is by NAME and not by position. aider's benchmark.py does:

    random.shuffle(test_dnames)
    if num_tests > 0:
        test_dnames = test_dnames[:num_tests]

The shuffle is UNSEEDED - benchmark.py imports random and never calls
random.seed - so `--num-tests 113` draws a different random 113 every run, not
the first 113 of a stable list. A comparison written as "the first N of each
run" would silently pair unrelated exercises and report their disagreements as
flips.

What makes the comparison sound instead is that the reference run covered ALL
225 exercises. Every exercise a shorter run can draw therefore has a counterpart
in it, and pairing on (case, language) is exact. This script REFUSES to run if
that is not true of the files it is given, rather than quietly dropping the
unmatched ones - a dropped exercise is a deleted measurement, and this campaign
has already been bitten once by a loader that dropped failures from one arm
only.

WHAT A FLIP IS. One exercise, run twice, passing once and failing once. The
direction is recorded but the rate is what matters: it is the noise floor that
any two-arm comparison on this benchmark has to clear before a difference can
be called real.
"""
import argparse
import io
import json
import os
import sys


def wilson(k, n, z=1.96):
    """Wilson score interval. A normal approximation puts the lower bound below
    zero at small counts, which is not a possible flip rate."""
    if n == 0:
        return (0.0, 0.0, 0.0)
    p = k / float(n)
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4.0 * n * n)) ** 0.5) / d
    return (100 * p, 100 * max(0.0, c - h), 100 * min(1.0, c + h))


def load(path):
    d = json.load(io.open(path, encoding="utf-8"))
    items = d.get("items") or []
    out = {}
    for x in items:
        key = (x.get("case"), x.get("lang"))
        if key in out:
            sys.exit("duplicate exercise %r in %s - cannot pair" % (key, path))
        out[key] = {
            "passed": bool(x.get("passed")),
            # Kept so a flip can be read against its cost. A zero-token record
            # is a real attempt that produced nothing and then failed; it is
            # NOT an empty record and must never be filtered out here.
            "completion": x.get("completion", 0),
            "prompt": x.get("prompt", 0),
            "dur": x.get("duration", x.get("dur", 0.0)),
            "zero_tokens": not x.get("completion"),
        }
    return out, d.get("n_listed", len(items))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-a", required=True, help="the reference run (the larger one)")
    ap.add_argument("--run-b", required=True, help="the repeat")
    ap.add_argument("--out", default=None)
    ap.add_argument("--label-a", default=None)
    ap.add_argument("--label-b", default=None)
    a = ap.parse_args()

    A, na = load(a.run_a)
    B, nb = load(a.run_b)
    la = a.label_a or os.path.basename(a.run_a)
    lb = a.label_b or os.path.basename(a.run_b)

    # Every exercise in the SHORTER run must exist in the reference. If it does
    # not, the two runs are not drawn from the same exercise set and no flip
    # count from them means anything.
    missing = sorted(set(B) - set(A))
    if missing:
        sys.exit(
            "%d exercise(s) in %s have no counterpart in %s, e.g. %r.\n"
            "The runs are not drawn from the same set; a flip count would be "
            "meaningless. Refusing rather than dropping them."
            % (len(missing), lb, la, missing[:5]))

    paired = sorted(set(A) & set(B))
    n = len(paired)
    if not n:
        sys.exit("no exercises in common")

    flips, ab, ba, agree_pass, agree_fail = [], [], [], 0, 0
    for k in paired:
        pa, pb = A[k]["passed"], B[k]["passed"]
        if pa == pb:
            if pa:
                agree_pass += 1
            else:
                agree_fail += 1
        else:
            rec = {"case": k[0], "lang": k[1],
                   "a_passed": pa, "b_passed": pb,
                   "a_completion": A[k]["completion"],
                   "b_completion": B[k]["completion"],
                   "a_zero_tokens": A[k]["zero_tokens"],
                   "b_zero_tokens": B[k]["zero_tokens"]}
            flips.append(rec)
            (ab if pa else ba).append(rec)

    k = len(flips)
    rate, lo, hi = wilson(k, n)
    pa_rate = 100.0 * (agree_pass + len(ab)) / n
    pb_rate = 100.0 * (agree_pass + len(ba)) / n

    out = {
        "what": "test-retest flip count: the same file and flags, run twice",
        "run_a": {"file": os.path.abspath(a.run_a), "label": la, "n_listed": na},
        "run_b": {"file": os.path.abspath(a.run_b), "label": lb, "n_listed": nb},
        "paired_n": n,
        "pass_rate_a_on_paired": round(pa_rate, 2),
        "pass_rate_b_on_paired": round(pb_rate, 2),
        "agree_pass": agree_pass,
        "agree_fail": agree_fail,
        "flips": k,
        "flip_rate_pct": round(rate, 2),
        "flip_rate_wilson95": [round(lo, 2), round(hi, 2)],
        "flipped_pass_to_fail": len(ab),
        "flipped_fail_to_pass": len(ba),
        "flipped_exercises": flips,
        "pairing": "by (case, language). aider shuffles UNSEEDED before "
                   "truncating to --num-tests, so a run is a random subsample "
                   "and not a stable prefix; pairing by position would compare "
                   "unrelated exercises.",
        "how_to_read": "This is the noise floor. Any two-arm difference on this "
                       "benchmark must clear it before it can be called real. "
                       "It does NOT decompose the 60 discordant exercises "
                       "between quantisations into signal and noise - it bounds "
                       "how much of that 60 the benchmark can produce on its "
                       "own.",
    }
    if a.out:
        io.open(a.out, "w", encoding="utf-8").write(
            json.dumps(out, indent=1, ensure_ascii=False))

    print("paired on (case, language): %d exercises" % n)
    print("  %-28s %5.1f%% pass" % (la[:28], pa_rate))
    print("  %-28s %5.1f%% pass" % (lb[:28], pb_rate))
    print()
    print("  agree pass   %3d" % agree_pass)
    print("  agree fail   %3d" % agree_fail)
    print("  FLIPPED      %3d   %.1f%%  (95%% CI %.1f - %.1f)" % (k, rate, lo, hi))
    print("     pass -> fail %3d" % len(ab))
    print("     fail -> pass %3d" % len(ba))
    if flips:
        print()
        print("  flipped exercises:")
        for f in flips[:25]:
            print("     %-26s %-11s %s" % (
                f["case"], f["lang"],
                "pass->fail" if f["a_passed"] else "fail->pass"))
        if len(flips) > 25:
            print("     ... and %d more" % (len(flips) - 25))
    print()
    # Scaling the rate onto the 225-exercise arms is a PROJECTION and is
    # printed as one, because the sixty discordant exercises were counted over
    # 225 and this rate may have been measured over fewer.
    print("  projected onto 225 exercises: %.0f flips (%.0f - %.0f)"
          % (2.25 * rate, 2.25 * lo, 2.25 * hi))
    print("  the two quantisations disagreed on 60 of 225. Read the projection "
          "as how much of that 60\n  this benchmark can produce with nothing "
          "changed at all - not as a subtraction.")
    if a.out:
        print("\nwrote %s" % a.out)
