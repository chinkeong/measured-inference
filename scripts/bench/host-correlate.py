"""Does the host-load index actually track the throughput excursions?

    python host-correlate.py

WHY. `cpu-contention.py` proved that SYNTHETIC host load slows decode: 18 busy
processes cost 5.4% on average and 24.0% at worst, with the SM clock rising.
That is a controlled result, and controlled results have to be checked against
the wild ones they claim to explain.

The wild one arrived unbidden. `sampler-band.py` ran 25 alternating pairs on a
machine nobody was deliberately loading, and its GREEDY arm - deterministic,
temperature 0, top_k 1, fixed prompt, one server load - read CV 6.44% with a
range of 63.4 to 74.4 t/s. It went 64 -> 74 -> 64 over about seven minutes.
This is the same 64-versus-74 bimodality that began this investigation, and it
carried the same tell: the SLOW readings ran at 1747-1778 MHz and the FAST ones
at 1685-1699 MHz. Higher clock, lower throughput.

If host contention is the mechanism, then `refarm.quiet_report()`'s CPU index -
the time a fixed busy loop takes, which measures how much CPU THIS process can
get - must rise exactly when throughput falls. If it does not, the mechanism is
wrong and something else is moving this machine.

DESIGN. One load, one fixed greedy probe repeated, and immediately before each
probe a cpu_probe() reading. Both series recorded per probe alongside SM clock,
temperature and power. Then the correlation between them.

A detector that fires on synthetic load but not on the real excursion is not a
detector. This is the check that decides which one it is.
"""

import json
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import refarm
import gpu_lock

PORT = 1252
BASE = "http://127.0.0.1:%d" % PORT
NPREDICT = 700
N = 45


def post(payload, timeout=1800):
    req = urllib.request.Request(BASE + "/v1/chat/completions",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def start(logpath):
    args = [refarm.server_bin(), "-m", refarm.ref_model(), "--alias", "qwen/qwen3.8-27b"] + \
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


def corr(x, y):
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / (sxx * syy) ** 0.5


def main():
    os.makedirs(refarm.OUT, exist_ok=True)
    logdir = os.path.join(refarm.OUT, "hostcorr-logs")
    os.makedirs(logdir, exist_ok=True)
    base = (refarm.band() or {}).get("cpu_probe_idle")
    print("ONE load, one greedy probe repeated %d times." % N)
    print("Before each probe: a fixed CPU busy loop, timed.")
    print("idle baseline %s s\n" % base)

    p, lf = start(os.path.join(logdir, "hostcorr.log"))
    if not wait(p):
        print("SERVER FAILED")
        refarm.stop_srv(p, lf)
        sys.exit(1)
    s = refarm.Sampler()
    s.start()
    rows = []
    try:
        # discarded warmup
        post({"model": "qwen/qwen3.8-27b", "temperature": 0, "top_k": 1,
              "max_tokens": NPREDICT, "cache_prompt": True,
              "messages": [{"role": "user", "content": refarm.REF_PROMPT}]})
        for i in range(N):
            cpu = min(refarm.cpu_probe() for _ in range(2))
            t0 = time.time()
            r = post({"model": "qwen/qwen3.8-27b", "temperature": 0, "top_k": 1,
                      "max_tokens": NPREDICT, "cache_prompt": True,
                      "messages": [{"role": "user", "content": refarm.REF_PROMPT}]})
            t1 = time.time()
            t = r.get("timings", {})
            win = [x for x in s.rows if t0 <= x[0] <= t1]
            dn, da, pn = t.get("draft_n"), t.get("draft_n_accepted"), t.get("predicted_n")
            row = {"i": i + 1, "cpu_probe_s": cpu,
                   "cpu_ratio": round(cpu / base, 2) if base else None,
                   "decode_tps": round(t.get("predicted_per_second", 0), 2),
                   "acceptance": round(da / dn, 3) if dn else None,
                   "sm_mhz": round(sum(x[1] for x in win) / len(win)) if win else None,
                   "temp": round(sum(x[2] for x in win) / len(win), 1) if win else None,
                   "watt": round(sum(x[3] for x in win) / len(win), 1) if win else None}
            rows.append(row)
            print("  %2d/%d  %6.2f t/s   cpu %.4f s (%.2fx)   %4s MHz  %4s C  %5s W"
                  % (i + 1, N, row["decode_tps"], cpu, row["cpu_ratio"] or 0,
                     row["sm_mhz"], row["temp"], row["watt"]))
    finally:
        s.stop = True
        s.join(timeout=2)
        refarm.stop_srv(p, lf)

    v = [r["decode_tps"] for r in rows]
    c = [r["cpu_probe_s"] for r in rows]
    k = [r["sm_mhz"] for r in rows]
    tp = [r["temp"] for r in rows]
    st = refarm.stats(v)
    r_cpu = corr(c, v)
    r_clk = corr(k, v)
    r_tmp = corr(tp, v)

    print("\nthroughput: mean %.2f  sd %.3f  cv %.2f%%  range %.1f%% (%.1f-%.1f)"
          % (st["mean"], st["sd"], st["cv_pct"], st["range_pct"], st["min"], st["max"]))
    print("\ncorrelation of decode t/s with:")
    print("  host cpu probe time   r = %s   <- negative means a busier host is slower"
          % (round(r_cpu, 3) if r_cpu is not None else "n/a"))
    print("  SM clock              r = %s"
          % (round(r_clk, 3) if r_clk is not None else "n/a"))
    print("  temperature           r = %s"
          % (round(r_tmp, 3) if r_tmp is not None else "n/a"))

    rep = {"date": time.strftime("%Y-%m-%d %H:%M"), "n": N, "npredict": NPREDICT,
           "idle_baseline_s": base, "stats": st,
           "r_tps_vs_cpu_probe": round(r_cpu, 3) if r_cpu is not None else None,
           "r_tps_vs_sm_mhz": round(r_clk, 3) if r_clk is not None else None,
           "r_tps_vs_temp": round(r_tmp, 3) if r_tmp is not None else None,
           "rows": rows}

    if st["range_pct"] < 3:
        print("\nNO EXCURSION this run (range %.1f%%), so there was nothing for the"
              % st["range_pct"])
        print("  index to track. Inconclusive - not a refutation. Re-run when the")
        print("  machine misbehaves, which is exactly what the index is for.")
        rep["verdict"] = "no excursion to explain"
    elif r_cpu is not None and r_cpu <= -0.5:
        print("\nCONFIRMED IN THE WILD: throughput fell when this process could get")
        print("  less CPU, r = %.3f, on a machine nobody was deliberately loading."
              % r_cpu)
        print("  The index fires on the real excursion, not only on synthetic load,")
        print("  so refarm.quiet_report() is a usable gate before any speed probe.")
        rep["verdict"] = "confirmed: host contention tracks the excursion"
    else:
        print("\nNOT EXPLAINED: throughput moved %.1f%% but the host index does not"
              % st["range_pct"])
        print("  track it (r = %s). Host contention is NOT the whole story, and the"
              % (round(r_cpu, 3) if r_cpu is not None else "n/a"))
        print("  campaign should say so rather than carry a tidy mechanism it has")
        print("  not earned.")
        rep["verdict"] = "host index does not track the excursion"

    f = os.path.join(refarm.OUT, "host-correlate.json")
    json.dump(rep, open(f, "w", encoding="utf-8"), indent=1)
    print("\n-> %s" % f)


if __name__ == "__main__":
    main()
