"""The reference arm: one fixed configuration, re-loaded beside every comparison.

    python refarm.py --calibrate 16     establish the between-load band
    python refarm.py                    take one reading

WHY THIS EXISTS.

On 2026-08-25 `resolution-floor.py` measured this machine's stability WITHIN a
single server load: 100 consecutive probes of one deterministic arm gave
mean 74.79 t/s, sd 0.236, CV 0.32%, no drift, SM clock steady at 1670-1733 MHz.
Three probes of that arm resolve a true difference of 0.5%. The instrument,
within a load, is excellent.

BETWEEN loads it is not, and nobody knows why. Three runs of the same
deterministic arm - same script, same prompt, same flags, and demonstrably the
same generated content (acceptance 0.926 / 0.924 / 0.926, mean draft length
2.54 / 2.54 / 2.54) - read 64.32, 74.08 and 65.25 t/s. Two tight, one 13.5%
excursion. Content, sampler, drafter behaviour, thermal drift and within-load
scatter are all ruled out by the measurement above; the difference is a
property of the LOAD.

The campaign's older published band - "about +/-25% of clock-state noise",
derived from 18.27 / 18.82 / 19.21 / 26.60 t/s - has the same shape: three
readings clustering within 5%, one sitting 41.7% above them. It was attributed
to clock state. Today's clocks say otherwise. The band was real; its stated
cause was not.

WHAT A REFERENCE ARM IS FOR.

Most of this campaign's comparisons cannot share a load: a quant ladder must
reload to change the file, a context series must reload to change -c. Their
arms therefore sit in different loads, and carry an unknown between-load risk
that no amount of within-load averaging touches.

So the arms are not compared to each other alone. One fixed configuration -
this one, never varying, never tuned, never "improved" - is loaded and probed
alongside them. If the reference reads the same in every load, the loads were
in the same state and the comparison stands. If the reference moves, the
comparison is VOID, and no amount of care in the arms themselves rescues it.

This is the oldest trick in measurement and the campaign should have been
doing it from the first day: you do not compare samples to each other, you
interleave a known standard.

THE STANDARD MUST NOT DRIFT. Changing the model, the prompt, the flags or the
probe count makes every earlier reading incomparable. If this configuration
ever has to change, the new one is calibrated from scratch and the old
readings are retired, not converted.

WHAT IS KNOWN, AND WHAT IS NOT.

  within-load, n=100, one load, 2026-08-25:  74.79 t/s, sd 0.236, CV 0.32%
  between-load band:                          measured by --calibrate

Until --calibrate has run, this module reports readings and REFUSES to issue a
pass/fail verdict, because a threshold with no measured distribution behind it
is a guess wearing a decimal point.
"""

import argparse
import json
import math
import os
import subprocess
import sys
import threading
import time
import urllib.request

SERVER = os.environ.get("LLAMA_SERVER", r"E:\AI\llama.cpp\llama-server.exe")
LMS = r"C:\Users\chink\.lmstudio\models"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "..", "results", "qwen38-27b-blind", "data", "register")

# ---------------------------------------------------------------------------
# THE STANDARD. Do not edit. See "THE STANDARD MUST NOT DRIFT" above.
# ---------------------------------------------------------------------------
REF_MODEL = os.path.join(LMS, r"unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-IQ4_XS.gguf")
REF_CTX = 32768
REF_PORT = 1247
REF_NPREDICT = 700
REF_PROBES = 3          # settled probes kept
REF_WARMUP = 1          # discarded, rule 12

REF_PROMPT = ("Write a single self-contained JavaScript module that implements a "
              "fixed-window rate limiter with a pluggable clock, a per-key limit, and "
              "an eviction sweep that runs at most once per window. Include JSDoc on "
              "every exported symbol, plus a short usage example. Code only.")

REF_FLAGS = ["-ngl", "99", "-c", str(REF_CTX), "--parallel", "1",
             "-ctk", "q8_0", "-ctv", "q8_0",
             "--spec-type", "draft-mtp", "--spec-draft-n-max", "4",
             "--spec-draft-p-min", "0.75",
             "--jinja", "--reasoning", "off"]

WITHIN_LOAD = {"date": "2026-08-25", "n": 100, "mean": 74.79, "sd": 0.236, "cv_pct": 0.32}

BASE = "http://127.0.0.1:%d" % REF_PORT

# load-time decisions worth diffing when two loads disagree
FINGERPRINT_KEYS = ("using device", "CUDA graph", "KV self size", "KV buffer size",
                    "compute buffer size", "model buffer size", "n_batch", "n_ubatch",
                    "flash_attn", "offloaded", "graph reuse", "n_ctx ", "type_k",
                    "type_v", "draft", "warning", "failed", "fallback")


def smi(q):
    o = subprocess.run(["nvidia-smi", "--query-gpu=" + q,
                        "--format=csv,noheader,nounits"],
                       capture_output=True, text=True, timeout=15).stdout
    return o.strip().splitlines()[0]


class Sampler(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.rows, self.stop = [], False

    def run(self):
        while not self.stop:
            try:
                v = smi("clocks.sm,temperature.gpu,power.draw")
                sm, t, p = [float(x) for x in v.split(",")]
                self.rows.append((time.time(), sm, t, p))
            except Exception:
                pass
            time.sleep(0.5)


def post(payload, timeout=1800):
    req = urllib.request.Request(BASE + "/v1/chat/completions",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def start(logpath):
    args = [SERVER, "-m", REF_MODEL, "--alias", "qwen/qwen3.8-27b"] + REF_FLAGS + \
           ["--host", "127.0.0.1", "--port", str(REF_PORT)]
    lf = open(logpath, "w", encoding="utf-8", errors="replace")
    return subprocess.Popen(args, stdout=lf, stderr=subprocess.STDOUT), lf


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


def stop_srv(p, lf):
    if p and p.poll() is None:
        p.terminate()
        try:
            p.wait(timeout=30)
        except subprocess.TimeoutExpired:
            p.kill()
    try:
        lf.close()
    except Exception:
        pass
    # wait for VRAM to actually come back, do not just hope
    for _ in range(20):
        time.sleep(1)
        try:
            if float(smi("memory.used")) < 2500:
                return
        except Exception:
            pass


def fingerprint(logpath):
    """Load-time decisions, so two disagreeing loads can be diffed at once."""
    try:
        txt = open(logpath, encoding="utf-8", errors="replace").read()
    except Exception:
        return []
    out = []
    for ln in txt.splitlines():
        s = ln.strip()
        if any(k in s for k in FINGERPRINT_KEYS):
            out.append(s)
    return out


def probe(sampler):
    t0 = time.time()
    r = post({"model": "qwen/qwen3.8-27b", "temperature": 0, "top_k": 1,
              "max_tokens": REF_NPREDICT, "cache_prompt": True,
              "messages": [{"role": "user", "content": REF_PROMPT}]})
    t1 = time.time()
    t = r.get("timings", {})
    win = [x for x in sampler.rows if t0 <= x[0] <= t1]
    dn, da = t.get("draft_n"), t.get("draft_n_accepted")
    pn = t.get("predicted_n")
    return {"decode_tps": round(t.get("predicted_per_second", 0), 3),
            "predicted_n": pn,
            "acceptance": round(da / dn, 3) if dn else None,
            "draft_len": round(dn / (pn - da), 2) if dn and pn and (pn - da) else None,
            "sm_mhz": round(sum(x[1] for x in win) / len(win)) if win else None,
            "temp": round(sum(x[2] for x in win) / len(win), 1) if win else None,
            "watt": round(sum(x[3] for x in win) / len(win), 1) if win else None}


def read_reference(logpath, tag=""):
    """One reading: its own server load, warmup discarded, REF_PROBES kept."""
    vram_before = None
    try:
        vram_before = float(smi("memory.used"))
    except Exception:
        pass
    t_load0 = time.time()
    p, lf = start(logpath)
    ok = wait(p)
    load_s = round(time.time() - t_load0, 1)
    if not ok:
        stop_srv(p, lf)
        return {"tag": tag, "ok": False, "error": "server failed to come up"}
    s = Sampler()
    s.start()
    try:
        for _ in range(REF_WARMUP):
            probe(s)
        rows = [probe(s) for _ in range(REF_PROBES)]
    finally:
        s.stop = True
        s.join(timeout=2)
        stop_srv(p, lf)
    v = [r["decode_tps"] for r in rows]
    m = sum(v) / len(v)
    return {"tag": tag, "ok": True,
            "mean_tps": round(m, 2),
            "probes": v,
            "spread_pct": round((max(v) - min(v)) / m * 100, 2),
            "acceptance": rows[0]["acceptance"],
            "draft_len": rows[0]["draft_len"],
            "sm_mhz": rows[0]["sm_mhz"], "temp": rows[0]["temp"], "watt": rows[0]["watt"],
            "vram_used_before_load": vram_before,
            "load_seconds": load_s,
            "fingerprint": fingerprint(logpath),
            "rows": rows}


def cpu_probe(iters=400000):
    """Seconds to run a fixed CPU-bound loop. Higher means a busier host.

    There is no CPU-utilisation number in the standard library, and the thing
    that actually matters is not the machine's load average but how much CPU
    THIS process can get - which is what a fixed loop measures directly.

    It matters because host load is the largest single error source on this rig
    and the only one invisible to every other log: with 18 busy processes
    running, decode fell 5.4% on average and 24.0% at worst while the SM clock
    ROSE 0.9% and temperature and acceptance did not move
    (`scripts/bench/cpu-contention.py`, 2026-08-25).
    """
    t0 = time.time()
    x = 0
    for _ in range(iters):
        x = (x * 1103515245 + 12345) % 2147483648
    return round(time.time() - t0, 4)


def quiet_report(baseline=None, tol=1.35):
    """Is the machine quiet enough to measure on? Records rather than blocks.

    `baseline` is the idle cpu_probe() time; without one this reports the
    reading and declines to judge, on the same principle as verdict().
    """
    v = min(cpu_probe() for _ in range(3))     # min: least-contended sample
    if baseline is None:
        b = band() or {}
        baseline = b.get("cpu_probe_idle")
    if not baseline:
        return {"cpu_probe_s": v, "status": "UNCALIBRATED",
                "detail": "no idle baseline recorded; run refarm.py --calibrate"}
    ratio = v / baseline
    return {"cpu_probe_s": v, "baseline_s": baseline, "ratio": round(ratio, 2),
            "status": "QUIET" if ratio <= tol else "BUSY",
            "detail": ("host looks quiet" if ratio <= tol else
                       "HOST IS BUSY (%.2fx idle): speed readings taken now may "
                       "run several per cent low with the GPU at full clock, and "
                       "with several times the usual scatter" % ratio)}


def band():
    """The between-load band, or None if --calibrate has never run."""
    f = os.path.join(OUT, "refarm-calibration.json")
    if not os.path.exists(f):
        return None
    try:
        return json.load(open(f, encoding="utf-8")).get("band")
    except Exception:
        return None


def verdict(readings):
    """VALID / VOID / UNCALIBRATED for a set of reference readings.

    Refuses to judge without a measured band. A threshold invented on the spot
    is exactly the failure this whole module exists to stop.
    """
    v = [r["mean_tps"] for r in readings if r.get("ok")]
    if len(v) < 2:
        return {"status": "INSUFFICIENT", "detail": "need a reference in >=2 loads"}
    obs = (max(v) - min(v)) / (sum(v) / len(v)) * 100
    b = band()
    if b is None:
        return {"status": "UNCALIBRATED", "observed_spread_pct": round(obs, 2),
                "detail": "reference spread recorded but not judged: "
                          "run `python refarm.py --calibrate 16` to measure the band"}
    tol = b["tolerance_pct"]
    return {"status": "VALID" if obs <= tol else "VOID",
            "observed_spread_pct": round(obs, 2), "tolerance_pct": tol,
            "detail": ("reference held across loads; the arms are comparable"
                       if obs <= tol else
                       "the reference MOVED between loads: this comparison is void, "
                       "the arms are not comparable and must be re-run")}


def stats(v):
    n = len(v)
    m = sum(v) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in v) / (n - 1)) if n > 1 else 0.0
    s = sorted(v)
    return {"n": n, "mean": round(m, 2), "sd": round(sd, 3),
            "cv_pct": round(sd / m * 100, 2), "min": round(s[0], 2),
            "max": round(s[-1], 2), "range_pct": round((s[-1] - s[0]) / m * 100, 1)}


def calibrate(n):
    """Load, probe, unload. n times. THIS is the number nobody has.

    Everything else about the between-load effect is anecdote until this runs:
    three observations is not a distribution, and the excursion may be one load
    in three or one in thirty. The difference decides whether the campaign's
    published cross-load deltas are fine or need re-running.
    """
    logdir = os.path.join(OUT, "refarm-logs")
    os.makedirs(logdir, exist_ok=True)
    print("REFERENCE ARM CALIBRATION - %d separate server loads" % n)
    print("UD-IQ4_XS, n4/p0.75, greedy, -c %d, %d probes/load after %d discarded\n"
          % (REF_CTX, REF_PROBES, REF_WARMUP))
    print("within-load floor for this exact arm (n=100, one load): "
          "%.2f t/s, cv %.2f%%\n" % (WITHIN_LOAD["mean"], WITHIN_LOAD["cv_pct"]))

    # the idle baseline for quiet_report(), captured before the card is busy
    idle = min(cpu_probe() for _ in range(5))
    print("host cpu probe, idle baseline: %.4f s\n" % idle)

    reads = []
    for i in range(n):
        lp = os.path.join(logdir, "refarm-%02d.log" % (i + 1))
        r = read_reference(lp, tag="load-%02d" % (i + 1))
        reads.append(r)
        if r.get("ok"):
            print("  load %2d/%d   %6.2f t/s   probes %s   spread %4.2f%%   "
                  "%4s MHz  %4s C  %5s W   load %4.1fs"
                  % (i + 1, n, r["mean_tps"],
                     " ".join("%.1f" % x for x in r["probes"]), r["spread_pct"],
                     r["sm_mhz"], r["temp"], r["watt"], r["load_seconds"]))
        else:
            print("  load %2d/%d   FAILED: %s" % (i + 1, n, r.get("error")))

    ok = [r for r in reads if r.get("ok")]
    if len(ok) < 2:
        print("\nnot enough successful loads to calibrate")
        return

    v = [r["mean_tps"] for r in ok]
    st = stats(v)
    within_cv = WITHIN_LOAD["cv_pct"]
    # a reference reading is the mean of REF_PROBES, so within-load noise on it
    # is cv/sqrt(REF_PROBES); anything beyond that is genuinely between-load
    expected = within_cv / math.sqrt(REF_PROBES)
    excess = math.sqrt(max(st["cv_pct"] ** 2 - expected ** 2, 0.0))

    print("\n%-24s %s" % ("between-load, n=%d loads:" % st["n"],
                          "mean %.2f  sd %.3f  cv %.2f%%  range %.1f%% (%.1f-%.1f)"
                          % (st["mean"], st["sd"], st["cv_pct"], st["range_pct"],
                             st["min"], st["max"])))
    print("%-24s %.2f%%   (within-load cv %.2f%% over sqrt(%d) probes)"
          % ("expected from within-load:", expected, within_cv, REF_PROBES))
    print("%-24s %.2f%%   <- this is the between-load effect, isolated"
          % ("excess, in quadrature:", excess))

    tol = round(3 * st["cv_pct"], 1)
    print("\nTOLERANCE: a comparison's reference readings must span <= %.1f%% "
          "(3 sd of the\n           between-load distribution). Wider than that "
          "and the loads were\n           not in the same state, and the arms are "
          "not comparable." % tol)

    lo, hi = min(v), max(v)
    if st["range_pct"] > 5:
        cold = [r for r in ok if r["mean_tps"] < (lo + hi) / 2]
        warm = [r for r in ok if r["mean_tps"] >= (lo + hi) / 2]
        print("\nEXCURSION SEEN: %d load(s) low (%.1f-%.1f), %d high (%.1f-%.1f)."
              % (len(cold), min(x["mean_tps"] for x in cold),
                 max(x["mean_tps"] for x in cold), len(warm),
                 min(x["mean_tps"] for x in warm),
                 max(x["mean_tps"] for x in warm)))
        fa = set(tuple(cold[0]["fingerprint"]))
        fb = set(tuple(warm[0]["fingerprint"]))
        d = sorted(fa ^ fb)
        if d:
            print("  load-time decisions that DIFFER between a low and a high load:")
            for ln in d[:40]:
                print("    %s" % ln[:150])
        else:
            print("  load-time fingerprints are IDENTICAL between a low and a high "
                  "load.\n  Whatever moves is not visible in what the server prints "
                  "at startup.")
    else:
        print("\nNo excursion in %d loads: every reference within %.1f%%."
              % (st["n"], st["range_pct"]))
        print("  The 13.5%% spread seen on 2026-08-25 is therefore either rarer "
              "than 1 in %d\n  loads, or was caused by something not present "
              "here. Not yet explained." % st["n"])

    rep = {"date": time.strftime("%Y-%m-%d %H:%M"),
           "arm": {"model": os.path.basename(REF_MODEL), "ctx": REF_CTX,
                   "flags": REF_FLAGS, "prompt": REF_PROMPT,
                   "probes": REF_PROBES, "warmup_discarded": REF_WARMUP,
                   "npredict": REF_NPREDICT},
           "within_load": WITHIN_LOAD,
           "between_load": st,
           "expected_from_within_load_pct": round(expected, 2),
           "excess_between_load_pct": round(excess, 2),
           "band": {"mean": st["mean"], "cv_pct": st["cv_pct"],
                    "tolerance_pct": tol,
                    "cpu_probe_idle": idle,
                    "basis": "3 sd of %d separate server loads" % st["n"]},
           "readings": reads}
    os.makedirs(OUT, exist_ok=True)
    f = os.path.join(OUT, "refarm-calibration.json")
    json.dump(rep, open(f, "w", encoding="utf-8"), indent=1)
    print("\n-> %s" % f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--calibrate", type=int, metavar="N",
                    help="run the reference in N separate loads and measure the band")
    a = ap.parse_args()
    if not os.path.exists(REF_MODEL):
        sys.exit("missing reference model: %s" % REF_MODEL)
    if a.calibrate:
        calibrate(a.calibrate)
    else:
        os.makedirs(os.path.join(OUT, "refarm-logs"), exist_ok=True)
        r = read_reference(os.path.join(OUT, "refarm-logs", "refarm-single.log"),
                           tag="single")
        print(json.dumps({k: v for k, v in r.items() if k != "rows"}, indent=1))
        b = band()
        print("\nband: %s" % (b if b else
                              "UNCALIBRATED - run --calibrate 16 first"))


if __name__ == "__main__":
    main()
