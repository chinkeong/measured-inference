# -*- coding: utf-8 -*-
"""Combine the two halves of the GPQA-Diamond anchor into the full 198.

WHY THIS EXISTS. The anchor was run in two pieces: questions 1-100 on
2026-08-27, then 101-198 on 2026-08-28 after bench.py gained --offset. Neither
half is a sample of the file. The frozen file is subject-ORDERED - 106 adjacent
same-subject pairs against 48.1 expected under random order, permutation
p < 0.00005 over 20,000 shuffles - so the prefix answered every biology question
and three of twenty-one quantum ones, and the tail answered the reverse. Either
half alone measures a subject mix, not the benchmark.

Together they are the whole file, and the ordering stops mattering: a union of
complementary halves covers every row exactly once. That is the only reason this
number may be quoted without the subject-bias caveat that both halves carry.

WHAT IS AND IS NOT POOLABLE. The halves ran on the same model file, the same
flags, the same card, the same seed and the same ceiling, twelve hours apart.
Accuracy pools because every question is answered once and scored the same way.
Throughput does NOT pool into a single mean here - the halves differ in generated
length (mean 10,166 against 10,860 tokens) and the board met them at different
temperatures - so per-half speed is reported separately and never averaged.

THE CEILING IS A CONDITION, NOT A DETAIL. 32 of 198 answers hit the
30,000-token limit and were scored wrong. That is a property of this harness at
this budget, not of the model's knowledge, and the two halves are not alike in
it: 13 of 100 against 19 of 98. The score excluding truncated answers is
reported beside the headline, and it is an UPPER bound - it silently assumes a
truncated answer would have been right.
"""
import io
import json
import math
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def wilson(k, n, z=1.96):
    if not n:
        return (0.0, 0.0)
    p = k / float(n)
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (round(100 * (c - h) / d, 1), round(100 * (c + h) / d, 1))


def two_prop_z(k1, n1, k2, n2):
    """Do the two halves differ by more than sampling noise? They are different
    QUESTIONS, so a difference is a statement about the file's two halves, not
    about the machine."""
    p1, p2 = k1 / float(n1), k2 / float(n2)
    p = (k1 + k2) / float(n1 + n2)
    se = math.sqrt(p * (1 - p) * (1.0 / n1 + 1.0 / n2))
    if se == 0:
        return 0.0, 1.0
    z = (p1 - p2) / se
    # two-sided normal tail
    pv = math.erfc(abs(z) / math.sqrt(2))
    return round(z, 3), round(pv, 4)


USAGE = """\
Combine the two halves of the GPQA-Diamond anchor - questions 1-100 and
questions 101-198 - into the full 198, the only form of this number that
carries no subject-ordering caveat.

    python scripts/bench/combine-gpqa-halves.py

Positional arguments: none. Both halves are named in this file, and the
combination REFUSES unless they total exactly 198, because two halves that do
not cover the frozen file exactly once are a sample, not the benchmark.

No environment variables. No server, no model, no GPU - this reads two JSON
files, does arithmetic, and writes a third.

Example:
  python scripts/bench/combine-gpqa-halves.py

Reads results/qwen38-27b-blind/data/gpqa-anchor-iq4xs.json and
gpqa-anchor-iq4xs-tail.json. Writes gpqa-anchor-iq4xs-full198.json beside them
and prints the pooled score, the excluding-truncated upper bound, and both
half-against-half tests.
"""


def main():
    # A help request must never start work. This script has no argument parser,
    # so without this line --help falls through and REWRITES the published
    # full-198 artefact - the smoke test answering a question by taking a
    # measurement.
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        print(USAGE.rstrip())
        return

    d = os.path.join(REPO, "results", "qwen38-27b-blind", "data")
    a = json.load(io.open(os.path.join(d, "gpqa-anchor-iq4xs.json"), encoding="utf-8"))
    b = json.load(io.open(os.path.join(d, "gpqa-anchor-iq4xs-tail.json"), encoding="utf-8"))

    na, ka = a["score"]["n"], a["score"]["correct"]
    nb, kb = b["score"]["n"], b["score"]["correct"]
    ta, tb = a["truncated_n"], b["truncated_n"]

    n, k = na + nb, ka + kb
    if n != 198:
        sys.exit("REFUSING: halves total %d, not 198 - they are not complementary" % n)

    # Excluding truncated. Both halves scored every truncated answer wrong, so
    # the untruncated correct count equals the correct count.
    nu, ku = (na - ta) + (nb - tb), ka + kb
    z, pv = two_prop_z(ka, na, kb, nb)
    zt, pvt = two_prop_z(ta, na, tb, nb)

    out = {
        "combined": True,
        "why": "the two halves are complementary and together cover the frozen "
               "file exactly once, which is what removes the subject-ordering "
               "bias that neither half can escape alone",
        "halves": [
            {"span": "questions 1-100", "date": "2026-08-27",
             "source": "gpqa-anchor-iq4xs.json", "n": na, "correct": ka,
             "pct": round(100.0 * ka / na, 1), "truncated": ta,
             "tok_s_mean": a.get("tok_s_mean"), "tokens_mean": a["tokens"]["mean"]},
            {"span": "questions 101-198", "date": "2026-08-28",
             "source": "gpqa-anchor-iq4xs-tail.json", "n": nb, "correct": kb,
             "pct": round(100.0 * kb / nb, 1), "truncated": tb,
             "tok_s_mean": b.get("tok_s_mean"), "tokens_mean": b["tokens"]["mean"]},
        ],
        "score": {"correct": k, "n": n, "pct": round(100.0 * k / n, 1),
                  "wilson95": wilson(k, n)},
        "score_excluding_truncated": {
            "correct": ku, "n": nu, "pct": round(100.0 * ku / nu, 1),
            "wilson95": wilson(ku, nu),
            "this_is_an_upper_bound": "it assumes every truncated answer would "
                                      "have been correct, which is the most "
                                      "generous assumption available",
        },
        "truncated": {
            "n": ta + tb, "pct": round(100.0 * (ta + tb) / n, 1),
            "first_half": "%d of %d" % (ta, na),
            "second_half": "%d of %d" % (tb, nb),
            "halves_differ": {"z": zt, "p": pvt},
            "note": "the ceiling is a harness condition at max_tokens 30000, "
                    "not a property of the model's knowledge",
        },
        "halves_differ_in_accuracy": {
            "z": z, "p": pv,
            "reading": "a difference here is a statement about the two halves "
                       "of a subject-ordered file, not about run-to-run noise: "
                       "the halves contain different questions",
        },
        "throughput_not_pooled": "per-half only. The halves differ in generated "
                                 "length and in the board temperature they met, "
                                 "so a single mean would describe neither.",
        "subject_bias": "REMOVED. Each half covers what the other misses "
                        "(prefix: biology 16 of 16, quantum 3 of 21; tail: "
                        "biology 0 of 16, quantum 18 of 21). The union is every "
                        "row exactly once.",
        "conditions": a.get("conditions"),
        "published_reference": a.get("published_reference"),
    }
    p = os.path.join(d, "gpqa-anchor-iq4xs-full198.json")
    io.open(p, "w", encoding="utf-8").write(
        json.dumps(out, indent=2, ensure_ascii=False))
    print("FULL 198  %d/%d = %.1f%%  95%% CI %s-%s" % (
        k, n, 100.0 * k / n, out["score"]["wilson95"][0], out["score"]["wilson95"][1]))
    print("  excl truncated %d/%d = %.1f%% (upper bound)" % (ku, nu, 100.0 * ku / nu))
    print("  halves %d/%d vs %d/%d   z=%s p=%s" % (ka, na, kb, nb, z, pv))
    print("  truncated %d of %d (%d vs %d)  z=%s p=%s" % (ta + tb, n, ta, tb, zt, pvt))
    print("wrote", p)


if __name__ == "__main__":
    main()
