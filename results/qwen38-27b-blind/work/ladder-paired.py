"""Paired arm-vs-arm test for the accuracy ladder (McNemar, exact binomial).

Rule 8 and the judge-panel precedent both require arm-against-arm claims to be
PAIRED: every arm answered the identical 25 prompts per benchmark, so the
comparison is per-item, not mean-against-mean. Unpaired standard errors throw
away most of the power and invite exactly the misreading this test exists to
prevent - reading a 2.7-point gap between adjacent rungs as "better".

McNemar counts only the DISCORDANT items: b = A right where B wrong, c = B
right where A wrong. Concordant items carry no information about a difference.
The exact two-sided binomial on (b, c) needs no normal approximation, which
matters because these counts are small.

Zero GPU. Reads the saved transcripts only.
"""

import glob
import itertools
import json
import os
from math import comb

BENCH = (r"E:\AI\measured-inference\results\qwen38-27b-blind"
         r"\data\quant-ladder\bench")

# file tag -> (display name, bits/weight, perplexity)
ARMS = [
    ("iq4xs-anchor", "UD-IQ4_XS",  4.223, 6.5956),
    ("q3kxl",        "UD-Q3_K_XL", 3.895, 6.7691),
    ("iq3xxs",       "UD-IQ3_XXS", 3.240, 6.9187),
    ("q2kxl",        "UD-Q2_K_XL", 2.912, 6.9957),
    ("iq2s",         "UD-IQ2_S",   2.481, 7.5481),
    ("iq2xxs",       "UD-IQ2_XXS", 2.153, 8.0079),
    ("iq1m",         "UD-IQ1_M",   1.994, 8.1418),
    ("iq1s",         "UD-IQ1_S",   1.835, 8.9265),
]


def load(tag):
    """Per-item correctness, keyed (dataset, index). Prefers the raised-cap
    re-run when one exists, because that is the arm rule 7 licenses."""
    pats = [os.path.join(BENCH, "arm-qwen-%s-cap32k-*_transcripts.json" % tag),
            os.path.join(BENCH, "arm-qwen-%s-*_transcripts.json" % tag)]
    f = None
    for p in pats:
        hits = [h for h in sorted(glob.glob(p)) if "cap32k" in h or "cap32k" not in p]
        if hits:
            f = hits[-1]
            break
    if not f:
        return None, None
    j = json.load(open(f, encoding="utf-8"))
    out = {}
    for ds, items in j.get("generations", {}).items():
        for it in items:
            s = it.get("score")
            if s is None:
                continue
            out[(ds, it["index"])] = 1 if float(s) >= 50.0 else 0
    return out, os.path.basename(f)


def exact_p(b, c):
    """Two-sided exact binomial on the discordant pairs, p=0.5."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(comb(n, i) for i in range(0, k + 1)) / (2.0 ** n)
    return min(1.0, 2.0 * tail)


def main():
    data, names = {}, {}
    for tag, disp, bpw, ppl in ARMS:
        d, f = load(tag)
        if d:
            data[tag] = d
            names[tag] = (disp, bpw, ppl, f)
    print("arms loaded: %d\n" % len(data))
    for tag in [a[0] for a in ARMS if a[0] in data]:
        disp, bpw, ppl, f = names[tag]
        n_ok = sum(data[tag].values())
        print("  %-11s %5.3f bpw  PPL %-7.4f  %2d/%2d correct   %s"
              % (disp, bpw, ppl, n_ok, len(data[tag]), f[:52]))
    print()
    print("PAIRED McNEMAR - every pair, on the items both arms answered")
    print("  b = left correct & right wrong,  c = right correct & left wrong")
    print("  a difference is claimed only when the exact two-sided p < 0.05\n")
    order = [a[0] for a in ARMS if a[0] in data]
    for x, y in itertools.combinations(order, 2):
        keys = sorted(set(data[x]) & set(data[y]))
        b = sum(1 for k in keys if data[x][k] and not data[y][k])
        c = sum(1 for k in keys if data[y][k] and not data[x][k])
        p = exact_p(b, c)
        dx, dy = names[x][0], names[y][0]
        gap = (sum(data[x][k] for k in keys) - sum(data[y][k] for k in keys)) \
            * 100.0 / len(keys)
        verdict = "DIFFERENT" if p < 0.05 else "tie"
        print("  %-11s vs %-11s  n=%d  b=%2d c=%2d  gap=%+5.1f pts  p=%.4f  %s"
              % (dx, dy, len(keys), b, c, gap, p, verdict))


main()
