"""How wide is the speed band a REAL user sees? Greedy vs the shipped sampler.

    python sampler-band.py

WHY. Every noise band this campaign publishes for speed was measured with
repeated probes of FIXED content: five cooled probes, two probes per server,
100 greedy probes at temperature 0. Those give 0.32% to 3%, and the published
page states that range correctly.

But nobody runs this model at temperature 0. The shipped recipe is
temperature 1.0, top_p 0.95, top_k 20 - and it ships WITH the MTP drafter on.
Under sampling the content differs on every request, and rule 11 says content
is what decides acceptance and mean draft length, which is what decides
speculative throughput. So the band a reader actually experiences may be far
wider than any band on the page, and for a reason the page does not mention.

There is already a hint. In the 2026-08-25 sampling-bridge run, one server load
at n4/p0.75 served 49 requests of 700 tokens:

    requests 1-9   (greedy)    mean 66.06   cv 3.03%   64.4 - 70.9
    requests 10-49 (shipped)   mean 67.88   cv 8.86%   54.6 - 83.2

and the drafter-OFF load in the same run spanned only 4.4% across 46 requests.
That points at speculation amplifying content variance into throughput
variance. But that run recorded no clocks, no power and no temperature, its
greedy arm reads 9 t/s below what the same configuration reads today, and its
numbers are the ones this whole investigation started by distrusting. A band
published off it would be a band published off the least trustworthy run in the
campaign.

So this measures it properly instead: ONE load, drafter on at the shipped
n4/p0.75, greedy and shipped sampler ALTERNATING so any drift hits both
equally, n=25 each, 700 tokens, with SM clock, power and temperature recorded
per probe and acceptance and mean draft length kept for every request.

WHAT IT DECIDES. If the shipped sampler's band is much wider than greedy's,
then every speed figure this campaign publishes from greedy probes understates
the spread a reader will see, and the page needs a fifth band naming the
sampler. If the bands match, the sampling-bridge spread was that run's own
problem and nothing on the page changes.

Either answer is publishable. The one thing that would not be publishable is
carrying the sampling-bridge number forward without checking it.
"""

import json
import math
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import refarm
import gpu_lock

PORT = 1250
BASE = "http://127.0.0.1:%d" % PORT
NPREDICT = 700
N = 25
SEED_BASE = 42

SAMPLERS = [
    ("greedy", {"temperature": 0, "top_k": 1}),
    ("shipped", {"temperature": 1.0, "top_p": 0.95, "top_k": 20, "min_p": 0.0}),
]

# a pair is KEPT only if both its probes ran on a quiet host
QUIET_MAX = 1.35
MAX_PAIRS = 60
IDLE = (refarm.band() or {}).get("cpu_probe_idle")


def post(payload, timeout=1800):
    req = urllib.request.Request(BASE + "/v1/chat/completions",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def start(logpath):
    args = [refarm.SERVER, "-m", refarm.REF_MODEL, "--alias", "qwen/qwen3.8-27b"] + \
        refarm.REF_FLAGS + ["--host", "127.0.0.1", "--port", str(PORT)]
    lf = open(logpath, "w", encoding="utf-8", errors="replace")
    return gpu_lock.serve(args, stdout=lf, stderr=subprocess.STDOUT), lf


def wait(p, timeout=900):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if p.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(BASE + "/health", timeout=2) as r:
                if json.loads(r.read().decode()).get("status") == "ok":
                    return True
        except Exception:
            pass
        time.sleep(2)
    return False


def probe(sampler_kw, seed, s):
    # Host state BEFORE the request, so a contaminated probe can be identified
    # and dropped rather than averaged in. Hoping the machine stays quiet for
    # nine minutes is not a method: the first attempt at this measurement was
    # ruined by an excursion nobody triggered.
    cpu = min(refarm.cpu_probe() for _ in range(2))
    t0 = time.time()
    body = {"model": "qwen/qwen3.8-27b", "max_tokens": NPREDICT,
            "cache_prompt": True, "seed": seed,
            "messages": [{"role": "user", "content": refarm.REF_PROMPT}]}
    body.update(sampler_kw)
    r = post(body)
    t1 = time.time()
    t = r.get("timings", {})
    win = [x for x in s.rows if t0 <= x[0] <= t1]
    dn, da, pn = t.get("draft_n"), t.get("draft_n_accepted"), t.get("predicted_n")
    return {"decode_tps": round(t.get("predicted_per_second", 0), 3),
            "cpu_probe_s": cpu,
            "cpu_ratio": round(cpu / IDLE, 2) if IDLE else None,
            "predicted_n": pn,
            "acceptance": round(da / dn, 3) if dn else None,
            "draft_len": round(dn / (pn - da), 2) if dn and pn and (pn - da) else None,
            "accepted_per_pass": round(da / (pn - da), 2) if pn and da and (pn - da) else None,
            "sm_mhz": round(sum(x[1] for x in win) / len(win)) if win else None,
            "temp": round(sum(x[2] for x in win) / len(win), 1) if win else None,
            "watt": round(sum(x[3] for x in win) / len(win), 1) if win else None}


def corr(x, y):
    n = len(x)
    if n < 3:
        return None
    mx, my = sum(x) / n, sum(y) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    if sxx <= 0 or syy <= 0:
        return None
    return round(sxy / (sxx * syy) ** 0.5, 3)


def main():
    os.makedirs(refarm.OUT, exist_ok=True)
    logdir = os.path.join(refarm.OUT, "samplerband-logs")
    os.makedirs(logdir, exist_ok=True)
    print("ONE load, drafter ON at the shipped n4/p0.75.")
    print("greedy vs shipped sampler, ALTERNATING, n=%d each, %d tokens.\n" % (N, NPREDICT))

    p, lf = start(os.path.join(logdir, "samplerband.log"))
    if not wait(p):
        print("SERVER FAILED")
        refarm.stop_srv(p, lf)
        sys.exit(1)
    s = refarm.Sampler()
    s.start()
    rows = {k: [] for k, _ in SAMPLERS}
    try:
        for name, kw in SAMPLERS:            # one discarded warmup each
            probe(kw, SEED_BASE, s)
        seed, tries, dropped = SEED_BASE, 0, 0
        while len(rows["greedy"]) < N and tries < MAX_PAIRS:
            tries += 1
            # a fresh seed per shipped request: that is what a real user gets.
            # greedy ignores the seed, which is the point of the contrast.
            pair = {name: probe(kw, seed, s) for name, kw in SAMPLERS}
            seed += 1
            busy = [p["cpu_ratio"] for p in pair.values()
                    if p["cpu_ratio"] and p["cpu_ratio"] > QUIET_MAX]
            if busy:
                dropped += 1
                print("    pair %2d DROPPED - host at %.2fx idle during it"
                      % (tries, max(busy)))
                continue
            for name in pair:
                rows[name].append(pair[name])
            i = len(rows["greedy"])
            if i % 5 == 0 or i == 1:
                print("  %2d/%d   greedy %6.2f (acc %.3f len %.2f)   "
                      "shipped %6.2f (acc %.3f len %.2f)   %4s MHz  host %.2fx"
                      % (i, N,
                         pair["greedy"]["decode_tps"],
                         pair["greedy"]["acceptance"] or 0,
                         pair["greedy"]["draft_len"] or 0,
                         pair["shipped"]["decode_tps"],
                         pair["shipped"]["acceptance"] or 0,
                         pair["shipped"]["draft_len"] or 0,
                         pair["shipped"]["sm_mhz"],
                         pair["shipped"]["cpu_ratio"] or 0))
        print("\n%d clean pairs kept, %d dropped for host load, %d attempts"
              % (len(rows["greedy"]), dropped, tries))
    finally:
        s.stop = True
        s.join(timeout=2)
        refarm.stop_srv(p, lf)

    rep = {"date": time.strftime("%Y-%m-%d %H:%M"), "npredict": NPREDICT, "n": N,
           "drafter": "draft-mtp n4/p0.75", "ctx": refarm.REF_CTX,
           "samplers": {k: v for k, v in SAMPLERS},
           "prompt": refarm.REF_PROMPT, "rows": rows, "summary": {}}

    print("\n%-9s %-4s %-9s %-7s %-8s %-9s %-11s %-10s %s"
          % ("sampler", "n", "mean t/s", "sd", "cv", "range", "acceptance",
             "draft_len", "min-max"))
    for name, _ in SAMPLERS:
        v = [r["decode_tps"] for r in rows[name]]
        st = refarm.stats(v)
        acc = [r["acceptance"] for r in rows[name] if r["acceptance"]]
        dl = [r["draft_len"] for r in rows[name] if r["draft_len"]]
        st["acceptance_mean"] = round(sum(acc) / len(acc), 3) if acc else None
        st["draft_len_mean"] = round(sum(dl) / len(dl), 2) if dl else None
        st["draft_len_min"] = round(min(dl), 2) if dl else None
        st["draft_len_max"] = round(max(dl), 2) if dl else None
        st["r_tps_vs_draftlen"] = corr(dl, v) if len(dl) == len(v) else None
        st["r_tps_vs_acceptance"] = corr(acc, v) if len(acc) == len(v) else None
        st["r_tps_vs_clock"] = corr([r["sm_mhz"] for r in rows[name]], v) \
            if all(r["sm_mhz"] for r in rows[name]) else None
        rep["summary"][name] = st
        print("%-9s %-4s %-9s %-7s %-8s %-9s %-11s %-10s %.1f-%.1f"
              % (name, st["n"], st["mean"], st["sd"], "%.2f%%" % st["cv_pct"],
                 "%.1f%%" % st["range_pct"], st["acceptance_mean"],
                 st["draft_len_mean"], st["min"], st["max"]))

    g, sh = rep["summary"]["greedy"], rep["summary"]["shipped"]

    # PAIRED mean: alternation means each pair shares a host state, so the
    # difference cancels it. This is the one thing a contaminated run still
    # supports, and it is why the arms alternate rather than run in blocks.
    gv = [r["decode_tps"] for r in rows["greedy"]]
    sv = [r["decode_tps"] for r in rows["shipped"]]
    dif = [b - a for a, b in zip(gv, sv)]
    dm = sum(dif) / len(dif)
    dsd = math.sqrt(sum((x - dm) ** 2 for x in dif) / (len(dif) - 1))
    se = dsd / math.sqrt(len(dif))
    rep["paired"] = {"mean_diff": round(dm, 2), "sd": round(dsd, 2),
                     "se": round(se, 2), "t": round(dm / se, 2) if se else None,
                     "ci95": [round(dm - 1.96 * se, 2), round(dm + 1.96 * se, 2)],
                     "pct_of_greedy": round(dm / g["mean"] * 100, 1)}
    print("\nPAIRED mean difference (shipped minus greedy, host cancelled):")
    print("  %+.2f t/s = %+.1f%%   95%% CI %+.2f to %+.2f   t = %.2f"
          % (dm, rep["paired"]["pct_of_greedy"], dm - 1.96 * se, dm + 1.96 * se,
             dm / se if se else 0))

    # VARIANCE: a CV RATIO is the wrong test here. Host contention adds a large
    # COMMON component to both arms, and a ratio against a fixed threshold
    # systematically understates whatever sampling adds on top of it. Subtract
    # the variances instead, and report how much of each arm is shared.
    gsd = g["sd"]
    ssd = sh["sd"]
    excess = math.sqrt(max(ssd ** 2 - gsd ** 2, 0.0))
    excess_pct = excess / sh["mean"] * 100
    r_arms = corr(gv, sv)
    rep["excess_sd_from_sampling"] = round(excess, 2)
    rep["excess_pct_from_sampling"] = round(excess_pct, 2)
    rep["r_between_arms"] = r_arms
    print("\ngreedy cv %.2f%%   shipped cv %.2f%%" % (g["cv_pct"], sh["cv_pct"]))
    print("  correlation between the arms across pairs: r = %s" % r_arms)
    if r_arms is not None and r_arms > 0.4:
        print("  ^ a large COMMON factor is moving both arms together (the host).")
        print("    The variance comparison below is therefore NOT clean, however")
        print("    many probes were taken. Re-run it on a gated quiet machine.")
    print("  excess sd attributable to sampling: %.2f t/s = %.2f%% of mean"
          % (excess, excess_pct))
    print("published page band for a cooled repeat probe: 0.4% to 3%")

    # SAVE BEFORE INTERPRETING. Twice on 2026-08-25 this script completed its
    # measurement and then died in the paragraph that explains it - once on a
    # missing `import math`, once on a stale variable - and both times the
    # probes were lost because json.dump() sat below the prose. The data is
    # expensive and the commentary is free; the expensive thing gets written
    # first.
    f = os.path.join(refarm.OUT, "sampler-band.json")
    json.dump(rep, open(f, "w", encoding="utf-8"), indent=1)
    print("\n-> %s" % f)

    if excess_pct >= 3.0:
        print("\nVERDICT: the sampler widens the speed band well beyond anything")
        print("  the page publishes. Every speed band on that page was measured")
        print("  on FIXED content and none of them names a sampler. A reader on")
        print("  the model card's recommended settings sees a %.1f%% range, not"
              % sh["range_pct"])
        print("  the %.1f%% greedy shows. The page needs a band naming the sampler."
              % g["range_pct"])
        print("  mean draft length under sampling ranged %s to %s - rule 11's"
              % (sh["draft_len_min"], sh["draft_len_max"]))
        print("  mechanism, and t/s correlates with draft length at r = %s"
              % sh["r_tps_vs_draftlen"])
    else:
        print("\nVERDICT: sampling adds only %.2f%% - inside the published band."
              % excess_pct)
        print("  Nothing on the page changes.")


if __name__ == "__main__":
    main()
