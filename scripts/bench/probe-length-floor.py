"""How much of a probe's scatter is just the probe being short?

    python probe-length-floor.py

WHY. `resolution-floor.py` measured this machine at 0.32% CV and published a
resolution table off it. That table was measured with 700-token probes, and it
was quietly assumed to describe the campaign's measurements generally. It does
not.

The depth series - the one behind every "decode declines with loaded context"
row, and behind the UD-Q3_K_XL-leads-UD-IQ4_XS ordering - probes with
`MaxTokens 80`. Its replication run recorded within-load spreads of 9.4% and
11.7% on two of three arms, against 1.7% on the third. Those are not consistent
with a 0.32% instrument, and the arithmetic says why: 80 tokens at ~35 t/s is
2.3 seconds of decode, so a fifth of a second of timing wobble is 9% of the
reading. At 700 tokens the same wobble is 2%.

If that is the whole story, then probe length alone decides how blunt the
instrument is, and a large part of this campaign was measured with the blunt
end. That would mean some published orderings rest on scatter, and it would
mean the fix is nearly free: predict more tokens.

WHAT THIS MEASURES. One server load, one configuration, one prompt - identical
to the reference arm so the numbers join up - and the SAME probe repeated at
four lengths:

    80 tokens     the depth series' length
    200 tokens
    700 tokens    the resolution-floor length, for continuity
    3000 tokens   the long end

Interleaved in rotation rather than run in blocks, so any slow drift in the
load hits every length equally instead of landing on whichever block ran last.

WHAT IT REPORTS. CV per length, and the resolution table per length: the
smallest true difference each probe length can resolve at n = 2, 3, 5, 10.
The n=2 column matters most - the original window-ceiling sweep used it.
"""

import json
import math
import os
import subprocess
import sys
import threading
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import refarm  # the standard: same model, same flags, same prompt
import gpu_lock

OUT = refarm.OUT
PORT = 1248
BASE = "http://127.0.0.1:%d" % PORT

LENGTHS = [(80, 40), (200, 40), (700, 40), (3000, 15)]
ROUNDS = max(n for _, n in LENGTHS)


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


def probe(npredict, sampler):
    t0 = time.time()
    r = post({"model": "qwen/qwen3.8-27b", "temperature": 0, "top_k": 1,
              "max_tokens": npredict, "cache_prompt": True,
              "messages": [{"role": "user", "content": refarm.REF_PROMPT}]})
    t1 = time.time()
    t = r.get("timings", {})
    win = [x for x in sampler.rows if t0 <= x[0] <= t1]
    dn, da, pn = t.get("draft_n"), t.get("draft_n_accepted"), t.get("predicted_n")
    return {"decode_tps": round(t.get("predicted_per_second", 0), 3),
            "predicted_n": pn,
            "decode_seconds": round(t.get("predicted_ms", 0) / 1000.0, 3),
            "wall_seconds": round(t1 - t0, 3),
            "acceptance": round(da / dn, 3) if dn else None,
            "sm_mhz": round(sum(x[1] for x in win) / len(win)) if win else None,
            "temp": round(sum(x[2] for x in win) / len(win), 1) if win else None}


def main():
    os.makedirs(OUT, exist_ok=True)
    logdir = os.path.join(OUT, "probelen-logs")
    os.makedirs(logdir, exist_ok=True)
    print("ONE load, ONE config (the reference arm), four probe lengths interleaved.")
    print("%-8s %s\n" % ("lengths:", ", ".join("%d tok x%d" % (a, b) for a, b in LENGTHS)))

    p, lf = start(os.path.join(logdir, "probelen.log"))
    if not wait(p):
        print("SERVER FAILED")
        refarm.stop_srv(p, lf)
        sys.exit(1)
    s = refarm.Sampler()
    s.start()
    got = {n: [] for n, _ in LENGTHS}
    try:
        for n, _ in LENGTHS:          # one discarded warmup at each length
            probe(n, s)
        for rnd in range(ROUNDS):
            for npred, count in LENGTHS:
                if len(got[npred]) >= count:
                    continue
                got[npred].append(probe(npred, s))
            done = sum(len(v) for v in got.values())
            total = sum(c for _, c in LENGTHS)
            if (rnd + 1) % 5 == 0 or rnd == 0:
                print("  round %2d/%d  (%d/%d probes)  %s"
                      % (rnd + 1, ROUNDS, done, total,
                         "  ".join("%dt:%.1f" % (n, got[n][-1]["decode_tps"])
                                   for n, _ in LENGTHS if got[n])))
    finally:
        s.stop = True
        s.join(timeout=2)
        refarm.stop_srv(p, lf)

    print("\n%-8s %-5s %-9s %-8s %-8s %-9s %s"
          % ("tokens", "n", "mean t/s", "sd", "cv", "decode s", "range"))
    rep = {"date": time.strftime("%Y-%m-%d %H:%M"), "config": "reference arm",
           "ctx": refarm.REF_CTX, "lengths": {}}
    for npred, _ in LENGTHS:
        rows = got[npred]
        if len(rows) < 2:
            continue
        v = [r["decode_tps"] for r in rows]
        st = refarm.stats(v)
        ds = sum(r["decode_seconds"] for r in rows) / len(rows)
        st["mean_decode_seconds"] = round(ds, 2)
        # if scatter is pure timing wobble, cv x decode_seconds is constant
        st["implied_wobble_seconds"] = round(st["cv_pct"] / 100.0 * ds, 4)
        rep["lengths"][str(npred)] = {"stats": st, "probes": rows}
        print("%-8s %-5s %-9s %-8s %-8s %-9s %s"
              % (npred, st["n"], st["mean"], st["sd"], "%.2f%%" % st["cv_pct"],
                 "%.2f" % ds, "%.1f%%" % st["range_pct"]))

    print("\n=== RESOLUTION BY PROBE LENGTH ===")
    print("    smallest true difference detectable = 2 sqrt(2) cv / sqrt(n)")
    print("%-8s %s" % ("tokens", "  ".join("n=%-6d" % n for n in (2, 3, 5, 10))))
    for npred, _ in LENGTHS:
        k = str(npred)
        if k not in rep["lengths"]:
            continue
        cv = rep["lengths"][k]["stats"]["cv_pct"]
        cells = ["%.1f%%   " % (2 * math.sqrt(2) * cv / math.sqrt(n))
                 for n in (2, 3, 5, 10)]
        rep["lengths"][k]["mde_pct"] = {
            str(n): round(2 * math.sqrt(2) * cv / math.sqrt(n), 2) for n in (2, 3, 5, 10)}
        print("%-8s %s" % (npred, "  ".join(cells)))

    w = [rep["lengths"][str(n)]["stats"]["implied_wobble_seconds"]
         for n, _ in LENGTHS if str(n) in rep["lengths"]]
    if len(w) >= 2:
        spread = (max(w) - min(w)) / (sum(w) / len(w)) * 100
        rep["wobble_seconds"] = w
        rep["wobble_agreement_pct"] = round(spread, 1)
        print("\nimplied timing wobble per length: %s seconds"
              % ", ".join("%.3f" % x for x in w))
        if spread < 60:
            print("  These agree to %.0f%%, so the scatter really is a roughly FIXED\n"
                  "  per-probe time cost. A short probe is not noisier because it is\n"
                  "  harder; it is noisier because the same wobble is a bigger share\n"
                  "  of a smaller number. Predicting more tokens fixes it for free."
                  % spread)
        else:
            print("  These disagree (%.0f%% apart), so a fixed timing wobble does NOT\n"
                  "  explain the pattern and something length-dependent is going on."
                  % spread)

    f = os.path.join(OUT, "probe-length-floor.json")
    json.dump(rep, open(f, "w", encoding="utf-8"), indent=1)
    print("\n-> %s" % f)


main()
