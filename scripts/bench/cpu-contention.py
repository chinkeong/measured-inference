"""Does host CPU load slow GPU decode? The last suspect standing.

    python cpu-contention.py

WHY. Every other explanation for this campaign's speed excursions has now been
measured and killed:

  clock state    refuted. probe-length-floor.py caught a 9% excursion at
                 1693-1723 MHz - at or ABOVE the clock of the fast probes
                 either side of it.
  temperature    refuted. 80.7-80.9 C during the excursion, 80.8-81.1 C
                 outside it. Identical.
  content        refuted. acceptance 0.882 / 0.893 during, 0.882 / 0.893
                 outside. Identical, alternating with the two prompts.
  the prompt     refuted. prompt-ab.py, two prompts in one load: 1.4% apart.
  between loads  refuted. refarm.py, 16 separate loads: 1.1% range.
  within a load  refuted. resolution-floor.py, 100 probes: 0.32% CV.
  probe length   refuted. 80 / 200 / 700 / 885 tokens on a shared window:
                 0.58 / 0.32 / 0.32 / 0.40% CV.

What remains is the host. The excursion in probe-length-floor.py landed while
this machine was running a 137-agent workflow, and llama.cpp's decode loop is
not purely a GPU affair: sampling, draft acceptance and token bookkeeping all
run on the CPU, and with a draft model each verify pass does more of it. A
starved host would slow decode with the card at full boost, which is exactly
the signature observed.

If that is right it explains the reading that started all of this - 64.32 t/s
from sampling-bridge.py, against 74.36 over sixteen loads and 75.53 on that
script's own prompt - because that run was competing with other work on this
machine and recorded nothing about it.

DESIGN. One load. Probes ALTERNATE between two conditions: idle host, and host
loaded with N busy processes. Alternating rather than blocked, so any drift
hits both equally. SM clock, temperature and power recorded per probe, because
the whole point is to show throughput moving while they do not.

WHAT IT DECIDES. If loaded probes are materially slower at equal clock, then
"nothing else may run on this machine during a measurement" is a rule, the
campaign's unexplained excursions have a cause, and every published speed
number needs to state whether the machine was quiet. If they match, the
excursion was something else again and this file records a clean negative.
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

PORT = 1251
BASE = "http://127.0.0.1:%d" % PORT
NPREDICT = 700
N = 12
WORKERS = max(2, (os.cpu_count() or 8) - 2)

BURN = ("import time\n"
        "t=time.time()+%d\n"
        "x=0\n"
        "while time.time()<t:\n"
        "    x=(x*1103515245+12345)%%2147483648\n")


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


def burners(seconds):
    """N busy CPU processes that exit on their own, so nothing can be orphaned."""
    out = []
    for _ in range(WORKERS):
        out.append(subprocess.Popen([sys.executable, "-c", BURN % seconds],
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL))
    return out


def probe(s):
    t0 = time.time()
    r = post({"model": "qwen/qwen3.8-27b", "temperature": 0, "top_k": 1,
              "max_tokens": NPREDICT, "cache_prompt": True,
              "messages": [{"role": "user", "content": refarm.REF_PROMPT}]})
    t1 = time.time()
    t = r.get("timings", {})
    win = [x for x in s.rows if t0 <= x[0] <= t1]
    dn, da, pn = t.get("draft_n"), t.get("draft_n_accepted"), t.get("predicted_n")
    return {"decode_tps": round(t.get("predicted_per_second", 0), 3),
            "predicted_n": pn,
            "acceptance": round(da / dn, 3) if dn else None,
            "draft_len": round(dn / (pn - da), 2) if dn and pn and (pn - da) else None,
            "sm_mhz": round(sum(x[1] for x in win) / len(win)) if win else None,
            "temp": round(sum(x[2] for x in win) / len(win), 1) if win else None,
            "watt": round(sum(x[3] for x in win) / len(win), 1) if win else None}


def main():
    os.makedirs(refarm.OUT, exist_ok=True)
    logdir = os.path.join(refarm.OUT, "cpu-logs")
    os.makedirs(logdir, exist_ok=True)
    print("ONE load. Probes alternate: quiet host vs %d busy CPU processes." % WORKERS)
    print("cpu_count=%s, %d predicted tokens, n=%d per condition.\n"
          % (os.cpu_count(), NPREDICT, N))

    p, lf = start(os.path.join(logdir, "cpu.log"))
    if not wait(p):
        print("SERVER FAILED")
        refarm.stop_srv(p, lf)
        sys.exit(1)
    s = refarm.Sampler()
    s.start()
    rows = {"quiet": [], "loaded": []}
    try:
        probe(s)                                  # discarded warmup
        for i in range(N):
            rows["quiet"].append(probe(s))
            bs = burners(30)                      # outlives one probe, then exits
            time.sleep(1.5)                       # let the load actually land
            try:
                rows["loaded"].append(probe(s))
            finally:
                for b in bs:
                    if b.poll() is None:
                        b.terminate()
            time.sleep(1.5)
            q, l = rows["quiet"][-1], rows["loaded"][-1]
            print("  %2d/%d  quiet %6.2f t/s (%4s MHz %4s C)   "
                  "loaded %6.2f t/s (%4s MHz %4s C)   %+.1f%%"
                  % (i + 1, N, q["decode_tps"], q["sm_mhz"], q["temp"],
                     l["decode_tps"], l["sm_mhz"], l["temp"],
                     (l["decode_tps"] - q["decode_tps"]) / q["decode_tps"] * 100))
    finally:
        s.stop = True
        s.join(timeout=2)
        refarm.stop_srv(p, lf)

    rep = {"date": time.strftime("%Y-%m-%d %H:%M"), "workers": WORKERS,
           "cpu_count": os.cpu_count(), "npredict": NPREDICT, "n": N,
           "rows": rows, "summary": {}}
    print("\n%-8s %-4s %-9s %-7s %-8s %-9s %-8s %s"
          % ("host", "n", "mean t/s", "sd", "cv", "sm_mhz", "temp", "acceptance"))
    for k in ("quiet", "loaded"):
        v = [r["decode_tps"] for r in rows[k]]
        st = refarm.stats(v)
        st["sm_mhz"] = round(sum(r["sm_mhz"] for r in rows[k]) / len(rows[k]))
        st["temp"] = round(sum(r["temp"] for r in rows[k]) / len(rows[k]), 1)
        acc = [r["acceptance"] for r in rows[k] if r["acceptance"]]
        st["acceptance"] = round(sum(acc) / len(acc), 3) if acc else None
        rep["summary"][k] = st
        print("%-8s %-4s %-9s %-7s %-8s %-9s %-8s %s"
              % (k, st["n"], st["mean"], st["sd"], "%.2f%%" % st["cv_pct"],
                 st["sm_mhz"], st["temp"], st["acceptance"]))

    q, l = rep["summary"]["quiet"], rep["summary"]["loaded"]
    eff = (l["mean"] - q["mean"]) / q["mean"] * 100
    dclk = (l["sm_mhz"] - q["sm_mhz"]) / q["sm_mhz"] * 100
    rep["effect_pct"] = round(eff, 2)
    rep["clock_delta_pct"] = round(dclk, 2)
    print("\nhost load costs %+.1f%% of decode, while SM clock moves %+.1f%%"
          % (eff, dclk))
    if eff < -2:
        print("\nCONFIRMED: a busy host slows GPU decode with the card at full clock.")
        print("  This is a CPU-side cost in the decode loop, not a GPU effect, and")
        print("  no amount of clock or temperature logging would reveal it.")
        print("  RULE: a speed measurement requires a quiet machine, and a report")
        print("  that cannot say the machine was quiet cannot defend its levels.")
        print("  It also explains 64.32 t/s from sampling-bridge.py: that run")
        print("  competed with other work and recorded nothing about it.")
    else:
        print("\nNOT CONFIRMED: host load does not materially move decode here")
        print("  (%+.1f%%). The probe-length excursion had some other cause, and" % eff)
        print("  this is a clean negative rather than an explanation.")

    f = os.path.join(refarm.OUT, "cpu-contention.json")
    json.dump(rep, open(f, "w", encoding="utf-8"), indent=1)
    print("\n-> %s" % f)


if __name__ == "__main__":
    main()
