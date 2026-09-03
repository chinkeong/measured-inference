#!/usr/bin/env python3
"""What cap would GPQA-Diamond actually have needed? A censored-data estimate.

    ./.venv/bin/python results/ornith-1.5-9b-mtp/work/appetite-censored.py

WHY THIS EXISTS. The GPQA anchor ran at a 30,000-token cap and 43 of 198
questions hit it exactly. Rule 7's remedy is "raise the cap and rerun that arm",
and the honest objection to spending 8-16 GPU hours on that is that nobody has
said what cap to raise it TO. Twice now the appetite was guessed and twice it
was wrong: the recipe lock said 5,407 (Stage 4's measured max x 1.5) and a
two-question pilot broke it at question 2; the amendment said 30,000 and 21.7 %
of the run exceeded it.

The third guess does not have to be a guess. Those 43 rows are not missing data,
they are RIGHT-CENSORED observations: each one says "this question needed more
than 30,000 tokens" and the 155 others say exactly how many they needed. That is
a survival-analysis shape, and it is already on disk. Zero GPU cost.

WHAT THIS CAN AND CANNOT SAY, stated before the numbers because the limit is the
finding. Every censored point sits at the SAME value, and the largest uncensored
observation (29,989) is below it. So:

  * The Kaplan-Meier estimate is exact up to 30,000 and UNDEFINED above it.
    Non-parametrically, the data say "21.7 % need more than 30k" and not one
    thing about how much more. That is already known and buys nothing.
  * Any cap recommendation is therefore an EXTRAPOLATION, and the whole tail
    rests on one constraint - S(30000) = 43/198 - plus the shape assumed by
    whichever distribution family is fitted.
  * So the useful output is not one number. It is the SPREAD ACROSS FAMILIES.
    If four defensible families agree on a cap, the extrapolation is doing
    little work and the number is usable. If they disagree by 3x, the honest
    answer is that the data cannot price the re-run, which is itself a decision.

METHOD. Maximum likelihood with right-censoring, loc fixed at 0:

    log L = SUM_uncensored log f(t_i) + n_censored * log S(30000)

fitted for lognormal, Weibull, log-logistic and gamma; compared by AIC; and
bootstrapped (resampling all 198 rows) for an interval on each recommended cap.
Cost is projected at the run's own measured effective rate, not a nominal one.
"""

import json
import math
import os
import sys

import numpy as np
from scipy import optimize, stats

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "data", "gpqa-format-decomposition.json")

# Measured on the run itself, not a spec sheet: 2,236,867 generated tokens over
# elapsed_s 28,525.4. This is the rate that includes prefill, grading and every
# other real cost, which is what a projection has to be priced at.
TOTAL_TOKENS_OBSERVED = 2_236_867
ELAPSED_S_OBSERVED = 28_525.4

FAMILIES = {
    "lognormal":    (stats.lognorm,    lambda t: (max(np.std(np.log(t)), 0.1), np.exp(np.mean(np.log(t))))),
    "weibull":      (stats.weibull_min, lambda t: (1.0, float(np.mean(t)))),
    "loglogistic":  (stats.fisk,       lambda t: (1.5, float(np.median(t)))),
    "gamma":        (stats.gamma,      lambda t: (1.0, float(np.mean(t)))),
}


def load():
    with open(SRC) as fh:
        rows = json.load(fh)["rows"]
    unc = np.array([r["tokens"] for r in rows if not r["truncated"]], dtype=float)
    cen = np.array([r["tokens"] for r in rows if r["truncated"]], dtype=float)
    if len(set(cen.tolist())) != 1:
        sys.exit("expected a single censoring value, got %s" % sorted(set(cen)))
    return unc, cen, float(cen[0]), len(rows)


def kaplan_meier(unc, cap, n_cen):
    """Non-parametric survival. Exact to the censoring point, then it stops."""
    events = np.sort(unc)
    n = len(events) + n_cen
    surv, at_risk, out = 1.0, n, []
    for t in np.unique(events):
        d = int((events == t).sum())
        surv *= (1 - d / at_risk)
        at_risk -= d
        out.append((float(t), surv))
    return out


def neg_loglik(theta, dist, unc, cap, n_cen):
    shape, scale = theta
    if shape <= 0 or scale <= 0 or not np.isfinite(shape) or not np.isfinite(scale):
        return 1e12
    try:
        lpdf = dist.logpdf(unc, shape, loc=0, scale=scale)
        lsf = dist.logsf(cap, shape, loc=0, scale=scale)
    except (ValueError, FloatingPointError):
        return 1e12
    if not np.all(np.isfinite(lpdf)) or not np.isfinite(lsf):
        return 1e12
    return -(float(lpdf.sum()) + n_cen * float(lsf))


def fit(name, unc, cap, n_cen):
    dist, start = FAMILIES[name]
    x0 = np.array(start(unc), dtype=float)
    best = None
    for scale_mult in (0.5, 1.0, 2.0):
        for shape_mult in (0.5, 1.0, 2.0):
            guess = np.array([x0[0] * shape_mult, x0[1] * scale_mult])
            res = optimize.minimize(neg_loglik, guess, args=(dist, unc, cap, n_cen),
                                    method="Nelder-Mead",
                                    options={"maxiter": 8000, "xatol": 1e-8, "fatol": 1e-8})
            if res.success and (best is None or res.fun < best.fun):
                best = res
    if best is None:
        return None
    k = 2
    return {
        "name": name, "dist": dist, "shape": best.x[0], "scale": best.x[1],
        "nll": float(best.fun), "aic": 2 * k + 2 * float(best.fun),
    }


def cap_for(f, target_trunc):
    """Cap at which a fraction target_trunc of questions would still truncate."""
    return float(f["dist"].ppf(1 - target_trunc, f["shape"], loc=0, scale=f["scale"]))


def expected_min(f, cap, grid=4000):
    """E[min(T, cap)] = integral of S(t) from 0 to cap. Cost per question."""
    t = np.linspace(0, cap, grid)
    s = f["dist"].sf(t, f["shape"], loc=0, scale=f["scale"])
    return float(np.trapezoid(s, t))


def bootstrap_caps(unc, cap, n_cen, name, target, reps=400, seed=20260904):
    rng = np.random.default_rng(seed)
    pooled = np.concatenate([unc, np.full(n_cen, cap)])
    flags = np.concatenate([np.zeros(len(unc), bool), np.ones(n_cen, bool)])
    out = []
    for _ in range(reps):
        idx = rng.integers(0, len(pooled), len(pooled))
        bu = pooled[idx][~flags[idx]]
        bc = int(flags[idx].sum())
        if len(bu) < 20 or bc == 0:
            continue
        f = fit(name, bu, cap, bc)
        if f:
            c = cap_for(f, target)
            if np.isfinite(c) and c < 1e9:
                out.append(c)
    return np.array(out)


def main():
    unc, cen, cap, n_total = load()
    n_cen = len(cen)
    rate = TOTAL_TOKENS_OBSERVED / ELAPSED_S_OBSERVED

    print("=" * 78)
    print("APPETITE FROM CENSORED DATA - GPQA-Diamond, Ornith-1.5-9B-MTP-Q8_0")
    print("=" * 78)
    print("questions            %d   (%d finished, %d censored at %,.0f)"
          .replace("%,.0f", "{:,.0f}").format(n_total, len(unc), n_cen, cap)
          if False else
          "questions            %d   (%d finished, %d censored at %s)"
          % (n_total, len(unc), n_cen, format(int(cap), ",")))
    print("largest finished     %s   (below the censoring point: the tail is unobserved)"
          % format(int(unc.max()), ","))
    print("observed rate        %.2f tok/s  (%s tokens / %.1f s, all overhead included)"
          % (rate, format(TOTAL_TOKENS_OBSERVED, ","), ELAPSED_S_OBSERVED))

    print("\n" + "-" * 78)
    print("1. NON-PARAMETRIC (Kaplan-Meier) - what the data say with no assumption")
    print("-" * 78)
    km = kaplan_meier(unc, cap, n_cen)
    for q in (0.25, 0.5, 0.75, 0.9):
        hit = next((t for t, s in km if s <= 1 - q), None)
        print("  %-5s of questions finish by %s tokens"
              % ("%.0f%%" % (q * 100), format(int(hit), ",") if hit else "> 30,000 (unreachable)"))
    print("  S(30,000) = %.3f   -> %.1f%% need MORE than the cap, and KM stops here."
          % (n_cen / n_total, 100 * n_cen / n_total))
    print("  Everything below this line is extrapolation.")

    print("\n" + "-" * 78)
    print("2. PARAMETRIC FITS (MLE, right-censored)")
    print("-" * 78)
    fits = [f for f in (fit(n, unc, cap, n_cen) for n in FAMILIES) if f]
    fits.sort(key=lambda f: f["aic"])
    best_aic = fits[0]["aic"]
    print("  %-12s %10s %10s %8s   %s" % ("family", "shape", "scale", "dAIC", "implied median"))
    for f in fits:
        med = f["dist"].ppf(0.5, f["shape"], loc=0, scale=f["scale"])
        print("  %-12s %10.4f %10.1f %8.1f   %s"
              % (f["name"], f["shape"], f["scale"], f["aic"] - best_aic, format(int(med), ",")))
    print("  observed median of the finished set: %s" % format(int(np.median(unc)), ","))

    print("\n" + "-" * 78)
    print("3. CAP REQUIRED FOR A TARGET TRUNCATION RATE - the spread IS the answer")
    print("-" * 78)
    targets = (0.10, 0.05, 0.01, 0.001)
    print("  %-12s %s" % ("family", "".join("%14s" % ("%.1f%% trunc" % (t * 100)) for t in targets)))
    table = {}
    for f in fits:
        caps = [cap_for(f, t) for t in targets]
        table[f["name"]] = caps
        print("  %-12s %s" % (f["name"], "".join("%14s" % format(int(min(c, 9.9e8)), ",") for c in caps)))
    for i, t in enumerate(targets):
        col = [table[f["name"]][i] for f in fits]
        print("  %-12s %s" % ("spread x" if i == 0 else "",
                              "%14.1fx" % (max(col) / min(col)) if i == 0 else ""), end="")
        break
    print()
    for i, t in enumerate(targets):
        col = np.array([table[f["name"]][i] for f in fits])
        print("    %.1f%% target: %s .. %s  (%.1fx spread across families)"
              % (t * 100, format(int(col.min()), ","), format(int(col.max()), ","),
                 col.max() / col.min()))

    print("\n" + "-" * 78)
    print("4. WHAT EACH CAP WOULD COST, at the run's own measured rate")
    print("-" * 78)
    best = fits[0]
    print("  priced with the best-AIC family (%s); other families move the tail,"
          % best["name"])
    print("  but E[min(T,cap)] is dominated by the bulk, so cost is far more stable than cap.")
    print("  %-14s %16s %14s %12s" % ("cap", "E[tokens]/question", "total tokens", "GPU hours"))
    for c in (30_000, 60_000, 100_000, 150_000, 200_000):
        em = expected_min(best, c)
        tot = em * n_total
        print("  %-14s %16s %14s %12.1f"
              % (format(c, ","), format(int(em), ","), format(int(tot), ","), tot / rate / 3600))
    print("  for reference, the run that actually happened: %s tokens, %.1f h"
          % (format(TOTAL_TOKENS_OBSERVED, ","), ELAPSED_S_OBSERVED / 3600))

    print("\n" + "-" * 78)
    print("5. HOW UNCERTAIN IS THE RECOMMENDATION? (bootstrap, 400 resamples)")
    print("-" * 78)
    for target in (0.05, 0.01):
        bs = bootstrap_caps(unc, cap, n_cen, best["name"], target)
        if len(bs) < 50:
            print("  %.0f%% target: bootstrap did not converge often enough to report"
                  % (target * 100))
            continue
        lo, med, hi = np.percentile(bs, [2.5, 50, 97.5])
        print("  %.0f%% truncation target, %s fit: median %s, 95%% CI [%s .. %s]  (%.1fx wide)"
              % (target * 100, best["name"], format(int(med), ","),
                 format(int(lo), ","), format(int(hi), ","), hi / lo))

    print("\n" + "-" * 78)
    print("6. IS A SINGLE DISTRIBUTION EVEN THE RIGHT SHAPE?")
    print("-" * 78)
    below = int((unc < 2500).sum())
    mid = int(((unc >= 2500) & (unc < 20000)).sum())
    high = int((unc >= 20000).sum())
    print("  finished-set buckets:  <2,500: %d    2,500-20,000: %d    >=20,000: %d"
          % (below, mid, high))
    print("  plus %d censored at 30,000." % n_cen)
    ks = stats.kstest(unc, lambda x: best["dist"].cdf(x, best["shape"], loc=0, scale=best["scale"])
                      / best["dist"].cdf(cap, best["shape"], loc=0, scale=best["scale"]))
    print("  KS of the %s fit against the finished set (conditioned on T<=30,000):"
          % best["name"])
    print("     D = %.4f, p = %.4f  %s"
          % (ks.statistic, ks.pvalue,
             "-> fit is NOT rejected" if ks.pvalue > 0.05 else "-> fit IS rejected; the tail number inherits that"))
    print("=" * 78)




# ---------------------------------------------------------------------------
# SECTION 7, added after section 6 rejected the single-family fit (KS p=0.0002).
# The bucket counts say why: 84 finished answers under 2,500 tokens and 15 over
# 20,000, with a thin middle. That is two modes - a "short answer" population
# and a "long reasoning" one - and no single lognormal spans both. The 43
# censored rows are all in the long mode by construction.
#
# A two-component lognormal mixture is the obvious alternative. It cannot
# remove the fundamental limit (every censored point sits at one value, so the
# long mode's tail is still pinned only by S(30000) = 0.217), but it CAN say
# whether the misspecification was driving the cap estimate.

def mix_sf(t, w, m1, s1, m2, s2):
    t = np.asarray(t, dtype=float)
    return w * stats.lognorm.sf(t, s1, loc=0, scale=math.exp(m1)) \
        + (1 - w) * stats.lognorm.sf(t, s2, loc=0, scale=math.exp(m2))


def mix_neg_loglik(theta, unc, cap, n_cen):
    lw, m1, ls1, m2, ls2 = theta
    w = 1 / (1 + math.exp(-lw))
    s1, s2 = math.exp(ls1), math.exp(ls2)
    if not all(map(np.isfinite, (w, m1, s1, m2, s2))) or s1 <= 0 or s2 <= 0:
        return 1e12
    pdf = w * stats.lognorm.pdf(unc, s1, loc=0, scale=math.exp(m1)) \
        + (1 - w) * stats.lognorm.pdf(unc, s2, loc=0, scale=math.exp(m2))
    sf = float(mix_sf(cap, w, m1, s1, m2, s2))
    if np.any(pdf <= 0) or sf <= 0:
        return 1e12
    return -(float(np.log(pdf).sum()) + n_cen * math.log(sf))


def fit_mixture(unc, cap, n_cen):
    lo, hi = np.log(unc[unc < 2500]), np.log(unc[unc >= 2500])
    starts = [
        (0.0, float(lo.mean()), math.log(max(lo.std(), .2)), float(hi.mean()), math.log(max(hi.std(), .2))),
        (0.5, 7.0, math.log(.6), 10.0, math.log(.8)),
        (-0.5, 7.5, math.log(.9), 10.5, math.log(.5)),
    ]
    best = None
    for x0 in starts:
        r = optimize.minimize(mix_neg_loglik, np.array(x0), args=(unc, cap, n_cen),
                              method="Nelder-Mead",
                              options={"maxiter": 40000, "maxfev": 40000,
                                       "xatol": 1e-9, "fatol": 1e-9})
        if best is None or r.fun < best.fun:
            best = r
    lw, m1, ls1, m2, ls2 = best.x
    return {"w": 1 / (1 + math.exp(-lw)), "m1": m1, "s1": math.exp(ls1),
            "m2": m2, "s2": math.exp(ls2), "nll": float(best.fun),
            "aic": 2 * 5 + 2 * float(best.fun)}


def mix_cap_for(p, target):
    f = lambda t: mix_sf(t, p["w"], p["m1"], p["s1"], p["m2"], p["s2"]) - target
    lo_b, hi_b = 1e2, 1e10
    if f(lo_b) < 0:
        return float("nan")
    while f(hi_b) > 0 and hi_b < 1e14:
        hi_b *= 10
    return float(optimize.brentq(f, lo_b, hi_b, maxiter=500))


def section7():
    unc, cen, cap, n_total = load()
    n_cen = len(cen)
    single = [f for f in (fit(n, unc, cap, n_cen) for n in FAMILIES) if f]
    single.sort(key=lambda f: f["aic"])
    best1 = single[0]
    p = fit_mixture(unc, cap, n_cen)

    print("\n" + "-" * 78)
    print("7. TWO-COMPONENT MIXTURE - does the bimodality change the answer?")
    print("-" * 78)
    print("  short mode: weight %.3f, median %s tokens (sigma %.2f)"
          % (p["w"], format(int(math.exp(p["m1"])), ","), p["s1"]))
    print("  long  mode: weight %.3f, median %s tokens (sigma %.2f)"
          % (1 - p["w"], format(int(math.exp(p["m2"])), ","), p["s2"]))
    print("  AIC  mixture %.1f  vs  best single (%s) %.1f   -> dAIC %+.1f"
          % (p["aic"], best1["name"], best1["aic"], p["aic"] - best1["aic"]))

    ks = stats.kstest(unc, lambda x: (1 - mix_sf(x, p["w"], p["m1"], p["s1"], p["m2"], p["s2"]))
                      / (1 - float(mix_sf(cap, p["w"], p["m1"], p["s1"], p["m2"], p["s2"]))))
    print("  KS against the finished set: D = %.4f, p = %.4f  %s"
          % (ks.statistic, ks.pvalue,
             "-> NOT rejected" if ks.pvalue > 0.05 else "-> still rejected"))

    print("\n  cap implied by the mixture, against the single-family range:")
    for t in (0.10, 0.05, 0.01):
        col = [cap_for(f, t) for f in single]
        mc = mix_cap_for(p, t)
        print("    %.0f%% truncation: mixture %s   (single-family range %s .. %s)"
              % (t * 100, format(int(mc), ",") if np.isfinite(mc) else "diverges",
                 format(int(min(col)), ","), format(int(max(col)), ",")))
    print("\n  cost at the mixture's own 10%% cap, measured rate %.2f tok/s:"
          % (TOTAL_TOKENS_OBSERVED / ELAPSED_S_OBSERVED))
    c10 = mix_cap_for(p, 0.10)
    t = np.linspace(0, c10, 6000)
    em = float(np.trapezoid(mix_sf(t, p["w"], p["m1"], p["s1"], p["m2"], p["s2"]), t))
    print("    cap %s -> E[tokens]/q %s, total %s, %.1f GPU hours"
          % (format(int(c10), ","), format(int(em), ","), format(int(em * n_total), ","),
             em * n_total / (TOTAL_TOKENS_OBSERVED / ELAPSED_S_OBSERVED) / 3600))
    print("=" * 78)


if __name__ == "__main__":
    main()
    section7()
