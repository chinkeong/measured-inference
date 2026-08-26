#!/usr/bin/env python3
"""Compare two agentic arms on the SAME exercises: quality, tokens, energy, time.

    compare-arms.py --a iq4xs-agentic --a-run <dir> --b q2kxl-agentic --b-run <dir>

WHY THIS EXISTS IN THIS FORM. A comparison of two quantisations that reports
only pass rates answers half the question. The half it drops is the one a user
actually feels: a smaller file that decodes faster per token but needs MORE
tokens to reach the same answer is not faster, and a table of tokens-per-second
will never say so.

TOKEN OVERHEAD, and the credit for it. Quesma's August 2026 quantisation study
(quesma.com/blog/qwen38-27b-quantizations-benchmarked) reports "~1.25x output
tokens on same solved tasks" for a 2-bit model against BF16. That single metric
is better than anything this campaign had for connecting quality to cost, and
it is measured here in a stronger form than a bare ratio: PAIRED, over the
exercises BOTH arms solved, so it cannot be moved by one arm solving an easier
subset. An arm that solves fewer tasks and spends fewer tokens doing it would
otherwise look efficient.

DERIVED METRICS THIS CAMPAIGN ADDS. Once tokens and energy are both known per
exercise, the figures a buyer actually needs fall out, and none of them is a
tokens-per-second number:
    joules per SOLVED exercise    quality and speed and power in one figure
    seconds per SOLVED exercise   the wall-clock rule, applied to outcomes
    tokens per SOLVED exercise    the overhead above, in absolute terms
A rung of the quant ladder that halves memory, costs 6 points of pass rate and
needs 25% more tokens per solved task is a different proposition from one that
costs 6 points and needs the same tokens - and only these columns tell them
apart.

PAIRING IS THE POINT. Both arms run the identical 225-exercise suite in the
identical order, so every comparison here is paired: McNemar on the discordant
exercises rather than two independent proportions, and per-exercise token and
energy ratios rather than ratios of sums. Paired tests are strictly more
sensitive on the same data, which matters because the difference being looked
for is a few points on a couple of hundred items.
"""
import argparse, io, json, math, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import archdata as A  # noqa: E402


def wilson(k, n, z=1.96):
    """Wilson score interval. Used rather than the normal approximation
    because at these sample sizes and near-extreme rates the normal interval
    can run past 0 or 1, which is not a confidence interval, it is a bug."""
    if n == 0:
        return (0.0, 0.0, 0.0)
    p = k / float(n)
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4.0 * n * n)) / d
    return (100.0 * p, 100.0 * max(0.0, c - h), 100.0 * min(1.0, c + h))


def mcnemar(b, c):
    """Exact two-sided binomial McNemar on the discordant pairs (b, c).

    b = solved by A only, c = solved by B only. Concordant pairs carry no
    information about a difference and are correctly ignored: reporting them
    would only dilute the test.
    """
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / float(2 ** n)
    return min(1.0, 2.0 * tail)


def load_arm(tag, run):
    ex = A.load_exercises(run)
    by = {}
    for e in ex:
        # A case name is unique within a language, not across languages.
        by[(e["lang"], e["case"])] = e
    try:
        dmon = A.load_dmon(tag)
    except Exception:
        dmon = None
    return {"tag": tag, "run": run, "ex": ex, "by": by, "dmon": dmon}


def charge(arm):
    """Energy and wall time per exercise, by interval attribution.

    Each exercise owns the interval since the PREVIOUS exercise finished, and
    only GPU-busy samples in it are integrated. NOT [t_end - duration, t_end]:
    the recorded duration covers only model calls while the timestamp is
    stamped after the unit tests and the build cleanup, so that window has the
    right length in the wrong place and bills test-time idle to the model. It
    produced a tenfold error in a published figure before it was caught.
    """
    if arm["dmon"] is None:
        return
    lo, hi = arm["dmon"]["t"][0], arm["dmon"]["t"][-1]
    seq = sorted(arm["ex"], key=lambda e: e["t_end"])
    for i in range(1, len(seq)):
        t0, t1 = seq[i - 1]["t_end"], seq[i]["t_end"]
        if t0 < lo or t1 > hi or (t1 - t0) < seq[i]["dur"] - 1.0:
            continue
        j, bs = A.energy(arm["dmon"], t0, t1, busy_only=True)
        seq[i]["j"] = j
        seq[i]["busy_s"] = bs
        seq[i]["span_s"] = t1 - t0


def fmt_ratio(vals):
    if not vals:
        return "n/a"
    vals = sorted(vals)
    n = len(vals)
    med = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2.0
    return "%.3fx (median of %d paired exercises, IQR %.3f-%.3f)" % (
        med, n, vals[int(n * .25)], vals[int(n * .75)])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True)
    ap.add_argument("--a-run", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--b-run", required=True)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    A_ = load_arm(args.a, args.a_run)
    B_ = load_arm(args.b, args.b_run)
    charge(A_)
    charge(B_)

    common = sorted(set(A_["by"]) & set(B_["by"]))
    print("arm A  %-16s %d exercises" % (args.a, len(A_["ex"])))
    print("arm B  %-16s %d exercises" % (args.b, len(B_["ex"])))
    print("paired on %d exercises present in BOTH arms" % len(common))
    if len(common) < len(A_["ex"]) or len(common) < len(B_["ex"]):
        print("  (an arm still running is compared only on what both have "
              "finished - the figure below is not the final one)")
    if not common:
        sys.exit("no overlap yet")

    ka = sum(1 for k in common if A_["by"][k]["passed"])
    kb = sum(1 for k in common if B_["by"][k]["passed"])
    pa, la, ua = wilson(ka, len(common))
    pb, lb, ub = wilson(kb, len(common))
    print()
    print("PASS RATE on the paired set")
    print("  %-16s %5.1f%%  (95%% CI %.1f-%.1f)  %d/%d"
          % (args.a, pa, la, ua, ka, len(common)))
    print("  %-16s %5.1f%%  (95%% CI %.1f-%.1f)  %d/%d"
          % (args.b, pb, lb, ub, kb, len(common)))

    b_only = sum(1 for k in common
                 if A_["by"][k]["passed"] and not B_["by"][k]["passed"])
    c_only = sum(1 for k in common
                 if B_["by"][k]["passed"] and not A_["by"][k]["passed"])
    p = mcnemar(b_only, c_only)
    print()
    print("PAIRED TEST (McNemar, exact two-sided)")
    print("  solved by %s only: %d" % (args.a, b_only))
    print("  solved by %s only: %d" % (args.b, c_only))
    print("  concordant pairs carry no information and are excluded")
    print("  p = %.4f  -> %s" % (p, "a real difference" if p < 0.05 else
                                 "NOT distinguishable at this sample size"))
    if p >= 0.05 and b_only + c_only > 0:
        # Rule of three: with n discordant pairs and no significant split, the
        # true difference can still be as large as this. Silence about it would
        # let a null read as an equivalence.
        print("  the data does NOT establish equivalence - with %d discordant"
              % (b_only + c_only))
        print("  pairs a difference of up to ~%.1f points remains consistent"
              % (100.0 * 3.0 / max(len(common), 1)))

    both = [k for k in common
            if A_["by"][k]["passed"] and B_["by"][k]["passed"]]
    print()
    print("TOKEN OVERHEAD on the %d exercises BOTH arms solved" % len(both))
    print("  (paired: an arm cannot look cheap by solving an easier subset)")
    tok = [B_["by"][k]["completion"] / float(A_["by"][k]["completion"])
           for k in both if A_["by"][k]["completion"]]
    print("  completion tokens, %s vs %s: %s" % (args.b, args.a, fmt_ratio(tok)))
    ta = sum(A_["by"][k]["completion"] for k in both)
    tb = sum(B_["by"][k]["completion"] for k in both)
    if ta:
        print("  in total: %d vs %d tokens (%.3fx)" % (tb, ta, tb / float(ta)))

    dur = [B_["by"][k]["dur"] / A_["by"][k]["dur"]
           for k in both if A_["by"][k].get("dur")]
    print("  model wall time: %s" % fmt_ratio(dur))

    print()
    print("COST PER SOLVED EXERCISE  (the figure a user actually pays)")
    rows = []
    for tag, arm in ((args.a, A_), (args.b, B_)):
        soln = [arm["by"][k] for k in common if arm["by"][k]["passed"]]
        withj = [e for e in soln if "j" in e]
        n = len(soln)
        row = {"arm": tag, "solved": n}
        if n:
            row["tokens_per_solved"] = sum(e["completion"] for e in soln) / n
        if withj:
            row["j_per_solved"] = sum(e["j"] for e in withj) / len(withj)
            row["s_per_solved"] = sum(e["busy_s"] for e in withj) / len(withj)
            row["n_with_energy"] = len(withj)
        rows.append(row)
        print("  %-16s solved %3d | %s | %s | %s"
              % (tag, n,
                 ("%7.0f tok" % row["tokens_per_solved"]) if n else "      -",
                 ("%8.1f kJ" % (row["j_per_solved"] / 1000.0))
                 if "j_per_solved" in row else "        -",
                 ("%6.0f s GPU-busy" % row["s_per_solved"])
                 if "s_per_solved" in row else "       -"))
    if len(rows) == 2 and all("j_per_solved" in r for r in rows):
        print("  energy per solved exercise, B vs A: %.3fx"
              % (rows[1]["j_per_solved"] / rows[0]["j_per_solved"]))
        print("  NOTE: energy here is board power only, and while the part is")
        print("        pinned at its power cap this ratio largely restates the")
        print("        time ratio rather than measuring efficiency separately.")

    print()
    print("BY LANGUAGE (paired)")
    langs = sorted(set(k[0] for k in common))
    print("  %-12s %-18s %-18s" % ("language", args.a, args.b))
    for lg in langs:
        ks = [k for k in common if k[0] == lg]
        xa = sum(1 for k in ks if A_["by"][k]["passed"])
        xb = sum(1 for k in ks if B_["by"][k]["passed"])
        print("  %-12s %3d/%3d  %5.1f%%    %3d/%3d  %5.1f%%"
              % (lg, xa, len(ks), 100.0 * xa / len(ks),
                 xb, len(ks), 100.0 * xb / len(ks)))

    if args.json:
        json.dump({"a": args.a, "b": args.b, "paired_n": len(common),
                   "a_pass": pa, "b_pass": pb, "mcnemar_p": p,
                   "a_only": b_only, "b_only": c_only,
                   "token_ratio_median": (sorted(tok)[len(tok) // 2]
                                          if tok else None),
                   "cost": rows},
                  io.open(args.json, "w", encoding="utf-8"), indent=1)
        print("\nwrote %s" % args.json)
