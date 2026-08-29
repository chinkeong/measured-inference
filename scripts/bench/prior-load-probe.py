#!/usr/bin/env python3
"""Does what ran BEFORE a session set its throughput?

    prior-load-probe.py --model <path.gguf> [--sessions 5]

THE QUESTION. Fifteen sessions of one configuration were measured on
2026-08-28. Fourteen landed in 75.71-78.65 t/s, a 3.8% band. One reached
88.76. The recipe card publishes 86.91 for these flags, so the card's figure
was reproduced in 1 of 15 attempts.

Everything that could plausibly differ has been ruled out. The workload is
bit-identical (greedy, fixed prompt: the same tokens, the same drafts, the same
acceptance, probe for probe, in every session). The llama.cpp build has not
changed since 2026-08-19. The core clock moves the wrong way - one session ran
49 MHz faster and 12.9% slower. Board temperature spans 75-83 C in every
session alike. The memory clock is pinned at 9501 MHz in every probe ever
recorded.

ONE THING SEPARATES THE OUTLIER, and it is not a property of the session
itself: the 88.76 session began immediately after a sustained heavy run (a
four-arm head-to-head that had the card at 97% for several minutes). Every
session since began after the card had been idle.

So the hypothesis is that the state a session INHERITS decides its throughput,
not anything the session does. This probe tests exactly that and nothing else.

THE DESIGN. Paired, alternating, one variable:

  COLD  the card is left idle for --idle seconds, then a fresh server is
        started and five probes are taken.
  HOT   a sustained burn runs first - continuous decode on a separate server
        until --burn seconds have passed - the burn server is torn down, and
        then a fresh server is started and five probes are taken.

Arms alternate COLD, HOT, COLD, HOT... so any drift over the evening falls on
both arms equally rather than on whichever ran later. The burn uses the same
model but a DIFFERENT prompt, so nothing it computes can be reused: what
carries over, if anything, is machine state and not a cache of this prompt's
answer.

WHAT WOULD FALSIFY THE HYPOTHESIS. HOT and COLD arms overlapping. If prior load
does not lift throughput, the outlier remains unexplained and the honest thing
is to publish the reproduction rate as a measurement and stop guessing at a
cause - which is what this campaign did twice today with mechanisms that did
not survive contact with the next measurement.
"""
import argparse
import io
import json
import os
import statistics
import subprocess
import sys
import time
import urllib.request
import gpu_lock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "lib"))
import paths

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import provenance as _prov
except Exception:                                        # pragma: no cover
    _prov = None

def server_bin():
    """llama-server, resolved when a run needs it - never at import.

    $LLAMA_SERVER still overrides; paths.llama_bin honours it and exits with
    an actionable message when nothing resolves. Deliberately not a module
    constant: --help must not require a toolchain to be installed.
    """
    return paths.llama_bin("llama-server")


PORT = 1296
BURN_PORT = 1297
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(REPO, "results", "qwen38-27b-blind", "data", "followup",
                   "prior-load-probe.json")

COMMON = ["--alias", "qwen", "--host", "127.0.0.1", "-ngl", "99",
          "--parallel", "1", "-fa", "on", "--jinja", "--reasoning", "off",
          "--metrics"]
SPEC = ["--spec-type", "draft-mtp",
        "--spec-draft-n-max", "10", "--spec-draft-p-min", "0.5"]
CTX, NPREDICT = "32768", 700

PROMPT = "\n".join([
    "Write a single self-contained JavaScript module that implements a fixed-window",
    "rate limiter with a pluggable clock, a per-key limit, and an eviction sweep that",
    "runs at most once per window. Include JSDoc on every exported symbol and a short",
    "usage example at the end. Do not explain the code outside the module.",
])

# Deliberately different work, so the burn cannot prime a cache of the measured
# prompt's own answer. What survives it is machine state or nothing.
BURN_PROMPT = ("Explain, in careful detail and with worked arithmetic, how a "
               "B-tree of order 64 stores one million keys: the height, the "
               "fanout at each level, the number of node reads for a point "
               "lookup, and how a split propagates to the root.")

PUBLISHED = 86.91


def smi(q):
    try:
        o = subprocess.run(["nvidia-smi", "--query-gpu=" + q,
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10)
        return [x.strip() for x in o.stdout.strip().split(",")]
    except Exception:
        return []


def cap_ok():
    v = smi("power.limit,power.default_limit")
    if len(v) != 2:
        return None
    try:
        return abs(float(v[0]) - float(v[1])) < 1.0
    except ValueError:
        return None


def clocks():
    v = smi("clocks.sm,clocks.mem,temperature.gpu,power.draw")
    if len(v) != 4:
        return {}
    try:
        return {"sm_mhz": float(v[0]), "mem_mhz": float(v[1]),
                "temp_c": float(v[2]), "watts": float(v[3])}
    except ValueError:
        return {}


def wait_ready(proc, port, timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(
                    "http://127.0.0.1:%d/health" % port, timeout=4) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(2)
    return False


def ask(port, prompt, max_tokens):
    body = json.dumps({
        "model": "qwen",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0, "top_k": 1, "max_tokens": max_tokens,
    }).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:%d/v1/chat/completions" % port, data=body,
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=900) as r:
        d = json.loads(r.read().decode())
    wall = time.time() - t0
    t = d.get("timings", {}) or {}
    n, ms = t.get("predicted_n") or 0, t.get("predicted_ms") or 0
    return {"decode_tps": (n / (ms / 1000.0)) if ms else None,
            "predicted_n": n, "wall_s": round(wall, 2), "clocks": clocks()}


def start(model, port, log_path):
    lf = io.open(log_path, "w", encoding="utf-8", errors="replace")
    p = gpu_lock.serve(
        [server_bin(), "-m", model] + COMMON +
        ["-c", CTX, "-ctk", "q8_0", "-ctv", "q8_0", "--port", str(port)] + SPEC,
        stdout=lf, stderr=subprocess.STDOUT)
    return p, lf


def stop(p, lf):
    try:
        p.terminate()
        p.wait(timeout=60)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass
    try:
        lf.close()
    except Exception:
        pass


def burn(model, seconds, logdir):
    """Hold the card under sustained decode on DIFFERENT work, then let it go."""
    log = os.path.join(logdir, "prior-load-burn-server.log")
    p, lf = start(model, BURN_PORT, log)
    t0 = time.time()
    try:
        if not wait_ready(p, BURN_PORT):
            return {"burned_s": 0.0, "note": "burn server never became ready"}
        while time.time() - t0 < seconds:
            try:
                ask(BURN_PORT, BURN_PROMPT, 700)
            except Exception:
                break
    finally:
        stop(p, lf)
    return {"burned_s": round(time.time() - t0, 1),
            "clocks_at_burn_end": clocks()}


def session(model, probes, logdir, tag):
    log = os.path.join(logdir, "prior-load-%s-server.log" % tag)
    p, lf = start(model, PORT, log)
    rows = []
    try:
        if not wait_ready(p, PORT):
            return {"FAILED": "server never became ready", "probes": []}
        ask(PORT, PROMPT, NPREDICT)                  # rule 12: discarded
        for _ in range(probes):
            rows.append(ask(PORT, PROMPT, NPREDICT))
    finally:
        stop(p, lf)
    t = [r["decode_tps"] for r in rows if r["decode_tps"]]
    return {"probes": rows,
            "mean_tps": round(statistics.mean(t), 2) if t else None,
            "min_tps": round(min(t), 2) if t else None,
            "max_tps": round(max(t), 2) if t else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--sessions", type=int, default=5,
                    help="sessions PER ARM; arms alternate COLD, HOT, ...")
    ap.add_argument("--probes", type=int, default=5)
    ap.add_argument("--burn", type=int, default=180)
    ap.add_argument("--idle", type=int, default=180)
    a = ap.parse_args()

    if cap_ok() is False:
        sys.exit("REFUSING: power.limit != power.default_limit.")

    logdir = os.path.dirname(OUT)
    if not os.path.isdir(logdir):
        os.makedirs(logdir)

    arms = []
    for i in range(a.sessions):
        for kind in ("COLD", "HOT"):
            tag = "%s-%d" % (kind.lower(), i + 1)
            print("\n=== %s session %d  %s" % (kind, i + 1,
                                               time.strftime("%H:%M:%S")),
                  flush=True)
            pre = None
            if kind == "COLD":
                print("  idling %d s ..." % a.idle, flush=True)
                time.sleep(a.idle)
            else:
                print("  burning %d s on different work ..." % a.burn,
                      flush=True)
                pre = burn(a.model, a.burn, logdir)
                print("  burn done: %s" % pre, flush=True)
            s = session(a.model, a.probes, logdir, tag)
            s.update({"arm": kind, "index": i + 1, "pre": pre})
            arms.append(s)
            print("  %s %d: mean %s  range %s-%s"
                  % (kind, i + 1, s.get("mean_tps"), s.get("min_tps"),
                     s.get("max_tps")), flush=True)

    cold = [x["mean_tps"] for x in arms
            if x["arm"] == "COLD" and x.get("mean_tps")]
    hot = [x["mean_tps"] for x in arms
           if x["arm"] == "HOT" and x.get("mean_tps")]
    out = {
        "date": time.strftime("%Y-%m-%d %H:%M"),
        "question": "does sustained prior load raise a session's throughput? "
                    "The one session in fifteen that reached the published "
                    "86.91 t/s followed a heavy run; every other followed idle.",
        "toolchain": (_prov.toolchain(server_bin(), a.model) if _prov else
                      "NOT RECORDED: provenance module unavailable"),
        "conditions": "UD-IQ4_XS, n-max 10 / p-min 0.5, -c 32768, "
                      "-ctk/-ctv q8_0, -ngl 99, --parallel 1, -fa on, "
                      "reasoning off, greedy, 700 predicted tokens, fresh "
                      "server per session, one warmup discarded, arms "
                      "ALTERNATED so drift falls on both equally; the burn "
                      "uses a DIFFERENT prompt so it cannot prime this "
                      "prompt's own answer",
        "burn_seconds": a.burn, "idle_seconds": a.idle,
        "probes_per_session": a.probes,
        "published_reference": PUBLISHED,
        "cold_means": cold, "hot_means": hot,
        "arms": arms,
    }
    if cold and hot:
        out["cold_mean"] = round(statistics.mean(cold), 2)
        out["hot_mean"] = round(statistics.mean(hot), 2)
        out["hot_minus_cold_pct"] = round(
            (statistics.mean(hot) - statistics.mean(cold))
            / statistics.mean(cold) * 100, 2)
        out["overlap"] = not (min(hot) > max(cold) or min(cold) > max(hot))
        out["reading"] = (
            "If the arms overlap, prior load is not the cause and the outlier "
            "stays unexplained - in which case publish the reproduction rate "
            "as a measurement and name no mechanism.")
    io.open(OUT, "w", encoding="utf-8").write(
        json.dumps(out, indent=2, ensure_ascii=False))
    print("\nCOLD means: %s" % cold)
    print("HOT  means: %s" % hot)
    if cold and hot:
        print("cold %.2f   hot %.2f   hot-cold %+.2f%%   overlap: %s"
              % (out["cold_mean"], out["hot_mean"],
                 out["hot_minus_cold_pct"], out["overlap"]))
    print("wrote %s" % OUT)


if __name__ == "__main__":
    main()
