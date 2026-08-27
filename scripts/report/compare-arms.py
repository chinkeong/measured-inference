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
    # Confidence interval on the PAIRED difference, printed whether or not the
    # test is significant. A p-value alone lets a null read as an equivalence,
    # and this interval is the only thing that says how large a real difference
    # could still be hiding.
    #
    # An earlier version printed the rule of three (3/n) here. That is the
    # bound for ZERO discordant pairs and is simply the wrong instrument once
    # there are any: with 59 discordant pairs on 223 it claimed 1.3 points
    # where the true interval is about five times wider. Understating
    # uncertainty is the one direction this campaign must never round.
    n = len(common)
    d = (c_only - b_only) / float(n)          # B minus A, as a proportion
    if b_only + c_only > 0:
        var = (b_only + c_only - (c_only - b_only) ** 2 / float(n)) / float(n * n)
        se = math.sqrt(max(var, 0.0))
        lo95, hi95 = 100.0 * (d - 1.96 * se), 100.0 * (d + 1.96 * se)
        print("  paired difference (B - A): %+.1f points, 95%% CI %+.1f to %+.1f"
              % (100.0 * d, lo95, hi95))
        if p >= 0.05:
            print("  NOT significant, and NOT equivalence: a true difference")
            print("  anywhere in that interval is consistent with this data.")

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

    # ENERGY IS COMPARED ONLY WHERE BOTH ARMS HAVE IT.
    #
    # An arm whose telemetry started after the benchmark has power data for a
    # SUBSET of its exercises. An earlier version of this block averaged each
    # arm's energy over whatever it happened to have - 132 exercises for one
    # arm against 222 for the other - and divided tokens over a THIRD set, all
    # solved exercises. Three denominators in one table. It reported 1.515x
    # where the paired figure is 1.319x: the direction survived, the magnitude
    # did not. Every column below is computed over the same exercises.
    energy_set = [k for k in common
                  if "j" in A_["by"][k] and "j" in B_["by"][k]]
    print()
    print("ENERGY AND TIME, paired on the %d exercises where BOTH arms have"
          % len(energy_set))
    print("power data (an arm's telemetry may start after its benchmark did)")
    for tag, arm in ((args.a, A_), (args.b, B_)):
        have = sum(1 for k in common if "j" in arm["by"][k])
        print("  %-16s power data on %3d of %d paired exercises"
              % (tag, have, len(common)))
    rows = []
    if energy_set:
        for tag, arm in ((args.a, A_), (args.b, B_)):
            es = [arm["by"][k] for k in energy_set]
            row = {"arm": tag, "n_energy_paired": len(es),
                   "kj_total": sum(e["j"] for e in es) / 1000.0,
                   "s_total": sum(e["busy_s"] for e in es),
                   "tokens_total": sum(e["completion"] for e in es)}
            rows.append(row)
            print("  %-16s %8.1f kJ | %7.0f s GPU-busy | %8d completion tok"
                  % (tag, row["kj_total"], row["s_total"], row["tokens_total"]))
        print("  energy ratio B/A on the SAME exercises: %.3fx"
              % (rows[1]["kj_total"] / max(rows[0]["kj_total"], 1e-9)))
        per = sorted(B_["by"][k]["j"] / A_["by"][k]["j"]
                     for k in energy_set if A_["by"][k]["j"] > 0)
        if per:
            print("  per-exercise energy ratio: %s" % fmt_ratio(per))

        # The both-solved subset is the cleanest statement, and usually the
        # smallest - its size is printed because it bounds what can be claimed.
        sb = [k for k in energy_set
              if A_["by"][k]["passed"] and B_["by"][k]["passed"]]
        if sb:
            ja = sum(A_["by"][k]["j"] for k in sb) / len(sb)
            jb = sum(B_["by"][k]["j"] for k in sb) / len(sb)
            ta = sum(A_["by"][k]["completion"] for k in sb) / len(sb)
            tb = sum(B_["by"][k]["completion"] for k in sb) / len(sb)
            print("  restricted to the %d BOTH-SOLVED exercises in that set:"
                  % len(sb))
            print("    energy per solved  %.1f kJ vs %.1f kJ  -> %.3fx"
                  % (ja / 1000.0, jb / 1000.0, jb / max(ja, 1e-9)))
            print("    tokens per solved  %.0f vs %.0f  -> %.3fx"
                  % (ta, tb, tb / max(ta, 1e-9)))
            rows[0]["j_per_solved"], rows[1]["j_per_solved"] = ja, jb
            rows[0]["n_both_solved"] = rows[1]["n_both_solved"] = len(sb)
        print("  NOTE: board power only, and while the part is pinned at its")
        print("        power cap this ratio largely restates the time ratio")
        print("        rather than measuring efficiency separately.")
    else:
        print("  no exercise has power data in BOTH arms - energy not compared")

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
