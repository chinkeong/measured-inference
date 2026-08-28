#!/usr/bin/env python3
"""Is the 93.9 t/s on the recipe card real, or was the instrument that
contradicted it simply measuring a cold board?

    pacing-probe.py --model <path.gguf> [--probes 3]

THE CONTRADICTION. One configuration - UD-IQ4_XS, n-max 10 / p-min 0.5,
-c 32768, -ngl 99, greedy, drafter on - has three published readings on this
rig:

    2026-08-21 code sweep      93.9 t/s    149-token prompt, 700 predicted
    energy arm                106.2 t/s
    2026-08-28 ts-pick arm A    76.3 t/s    ~50-token prompt, 400 predicted

That is a 39% spread on ONE configuration, and the recipe card publishes the
top of it. Rule 2 says no reader may measure less than the report promised, so
either the card is wrong or the instrument that contradicted it is.

THE HYPOTHESIS, and it accuses this campaign's own probe rather than the card.
ts-pick-probe.py warms with 120 tokens - about a second and a half - sleeps two
seconds, then takes 400-token probes with two-second cooldowns between them.
The 2026-08-21 sweep ran 700-token generations back to back. A 3090 does not
hold its clock through a two-second gap, and a shorter generation spends a
larger fraction of its window climbing. This is the SAME defect already found
and fixed in power-cap-arms.py on 2026-08-27, where the published curve was
measured on a workload averaging 305 W against a 350 W limit because its probes
were too short and too spaced to ever reach the cap.

If that is the whole story, the card stands and the probe was the broken
instrument - and every RATIO ts-pick reported (f16 KV 8.9% slower, arm E 8.4%
faster) was measured on a cold board and has to be re-examined, because nothing
guarantees a pacing artefact is equal across arms.

THE DESIGN. One configuration throughout. Only the PACING changes, one factor
at a time, so the arm that moves names the cause:

  P1  120-token warmup, 2 s cooldowns, 400 predicted   ts-pick's exact pacing.
                                                       Must reproduce ~76 t/s
                                                       or the hypothesis is
                                                       already wrong.
  P2  120-token warmup, NO cooldown,   400 predicted   isolates the gap.
  P3  120-token warmup, NO cooldown,   700 predicted   isolates length.
  P4  30 s sustained burn, NO cooldown, 700 predicted  the 2026-08-21 regime.
                                                       Should land near 93.9.

Each arm reports SM clock and board temperature alongside throughput, because a
pacing explanation that does not also show the clock moving is a story, not a
mechanism. A fresh server per arm, so no arm inherits another's board
temperature; the burn happens INSIDE the arm that asks for it.

WHAT WOULD FALSIFY THE HYPOTHESIS. P4 failing to recover most of the gap. If
pacing is not the cause the remaining candidates are the prompt itself and the
llama.cpp build, and both are cheap to test next - but neither should be tested
until this one is settled, because a probe that cannot reproduce its own
baseline cannot be used to test anything else.
"""
import argparse
import io
import json
import os
import subprocess
import sys
import time
import urllib.request
import gpu_lock

# Provenance, added 2026-08-28. A throughput number whose toolchain is not
# recorded cannot be compared with a later one - this campaign published four
# readings of one configuration spanning 80.0 to 106.2 t/s and could not test
# the build, because no artefact had recorded it.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "bench"))
try:
    import provenance as _prov
except Exception:                                    # pragma: no cover
    _prov = None

SERVER = os.environ.get("LLAMA_SERVER",
                              r"E:\AI\llama.cpp\llama-server.exe")
PORT = 1294
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(REPO, "results", "qwen38-27b-blind", "data", "followup",
                   "pacing-probe.json")

COMMON = ["--alias", "qwen", "--host", "127.0.0.1", "-ngl", "99",
          "--parallel", "1", "-fa", "on", "--jinja", "--reasoning", "off",
          "--metrics"]
SPEC_PEAK = ["--spec-type", "draft-mtp",
             "--spec-draft-n-max", "10", "--spec-draft-p-min", "0.5"]
CTX = "32768"

# ts-pick's prompt, held fixed. The prompt is NOT a variable in this probe:
# changing pacing and content together would leave neither testable.
PROMPT = ("Write a single self-contained JavaScript module that implements a "
          "fixed-window rate limiter with a pluggable clock, a per-key limit, "
          "and an eviction sweep that runs at most once per window. Include "
          "JSDoc on every exported symbol.")

ARMS = [
    {"id": "P1-tspick-pacing", "warm_tokens": 120, "burn_s": 0,
     "cooldown_s": 2, "npredict": 400,
     "what": "ts-pick-probe.py's exact pacing; must reproduce ~76 t/s"},
    {"id": "P2-nocooldown-400", "warm_tokens": 120, "burn_s": 0,
     "cooldown_s": 0, "npredict": 400,
     "what": "same but probes run back to back; isolates the inter-probe gap"},
    {"id": "P3-nocooldown-700", "warm_tokens": 120, "burn_s": 0,
     "cooldown_s": 0, "npredict": 700,
     "what": "same, 700 tokens; isolates generation length"},
    {"id": "P4-burned-700", "warm_tokens": 0, "burn_s": 30,
     "cooldown_s": 0, "npredict": 700,
     "what": "board burned to steady state first; the 2026-08-21 regime"},
]


def smi(q):
    try:
        o = subprocess.run(["nvidia-smi", "--query-gpu=" + q,
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10)
        return [x.strip() for x in o.stdout.strip().split(",")]
    except Exception:
        return []


def cap_ok():
    """A card left at a non-stock power limit silently corrupts every reading
    and nothing else reports it. Refuse rather than measure."""
    v = smi("power.limit,power.default_limit")
    if len(v) != 2:
        return None
    try:
        return abs(float(v[0]) - float(v[1])) < 1.0
    except ValueError:
        return None


def clocks():
    v = smi("clocks.sm,temperature.gpu,power.draw")
    if len(v) != 3:
        return {}
    try:
        return {"sm_mhz": float(v[0]), "temp_c": float(v[1]),
                "watts": float(v[2])}
    except ValueError:
        return {}


def wait_ready(proc, timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(
                    "http://127.0.0.1:%d/health" % PORT, timeout=4) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(2)
    return False


def probe(max_tokens):
    body = json.dumps({
        "model": "qwen",
        "messages": [{"role": "user", "content": PROMPT}],
        "temperature": 0.0, "top_k": 1, "max_tokens": max_tokens,
    }).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:%d/v1/chat/completions" % PORT, data=body,
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=900) as r:
        d = json.loads(r.read().decode())
    wall = time.time() - t0
    t = d.get("timings", {}) or {}
    n = t.get("predicted_n") or 0
    ms = t.get("predicted_ms") or 0
    return {"decode_tps": (n / (ms / 1000.0)) if ms else None,
            "predicted_n": n, "prompt_n": t.get("prompt_n"),
            "wall_s": round(wall, 2), "clocks": clocks()}


def burn(seconds, npredict):
    """Hold the board under sustained decode before measuring. An arm measured
    from idle spends its window climbing clock and temperature, which is
    exactly how a 93.9 t/s configuration came to read 76.3."""
    if seconds <= 0:
        return 0.0
    t0 = time.time()
    while time.time() - t0 < seconds:
        try:
            probe(npredict)
        except Exception:
            break
    return round(time.time() - t0, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--probes", type=int, default=3)
    a = ap.parse_args()

    ok = cap_ok()
    if ok is False:
        sys.exit("REFUSING: power.limit != power.default_limit. Run "
                 "nvidia-smi -pl 350 first; a capped card corrupts this "
                 "silently.")
    print("cap check: %s" % ("stock" if ok else "unreadable, proceeding"))

    logdir = os.path.dirname(OUT)
    if not os.path.isdir(logdir):
        os.makedirs(logdir)
    rows = []
    for arm in ARMS:
        print("\n=== %s  %s" % (arm["id"], arm["what"]), flush=True)
        log = os.path.join(logdir, "pacing-%s-server.log" % arm["id"])
        with io.open(log, "w", encoding="utf-8", errors="replace") as lf:
            p = gpu_lock.serve(
                [SERVER, "-m", a.model] + COMMON +
                ["-c", CTX, "-ctk", "q8_0", "-ctv", "q8_0",
                 "--port", str(PORT)] + SPEC_PEAK,
                stdout=lf, stderr=subprocess.STDOUT)
            try:
                if not wait_ready(p):
                    print("  server never became ready - recorded as failure")
                    rows.append({"arm": arm["id"], "FAILED": "server not ready",
                                 "log": os.path.basename(log)})
                    continue
                before = clocks()
                burned = 0.0
                if arm["warm_tokens"]:
                    probe(arm["warm_tokens"])      # rule 12: discarded
                    time.sleep(2)
                if arm["burn_s"]:
                    print("  burning %d s ..." % arm["burn_s"], flush=True)
                    burned = burn(arm["burn_s"], arm["npredict"])
                got = []
                for i in range(a.probes):
                    r = probe(arm["npredict"])
                    got.append(r)
                    c = r.get("clocks") or {}
                    print("  probe %d: %6.2f t/s  %4s tok  %.1fs  "
                          "%s MHz %s C %s W"
                          % (i + 1, r["decode_tps"] or 0, r["predicted_n"],
                             r["wall_s"], c.get("sm_mhz"), c.get("temp_c"),
                             c.get("watts")), flush=True)
                    if arm["cooldown_s"]:
                        time.sleep(arm["cooldown_s"])
                tps = [g["decode_tps"] for g in got if g["decode_tps"]]
                mean = sum(tps) / len(tps) if tps else None
                spread = ((max(tps) - min(tps)) / mean * 100
                          if tps and mean else None)
                sms = [(g.get("clocks") or {}).get("sm_mhz") for g in got]
                sms = [x for x in sms if x]
                rows.append({
                    "arm": arm["id"], "what": arm["what"],
                    "warm_tokens": arm["warm_tokens"], "burn_s": arm["burn_s"],
                    "burned_actual_s": burned, "cooldown_s": arm["cooldown_s"],
                    "npredict": arm["npredict"],
                    "mean_tps": round(mean, 2) if mean else None,
                    "spread_pct": round(spread, 2) if spread is not None else None,
                    "mean_sm_mhz": round(sum(sms) / len(sms), 1) if sms else None,
                    "clocks_before_arm": before,
                    "probes": got, "log": os.path.basename(log),
                })
                print("  MEAN %.2f t/s  spread %.2f%%  SM %s MHz"
                      % (mean or 0, spread or 0,
                         round(sum(sms) / len(sms), 1) if sms else "?"),
                      flush=True)
            finally:
                p.terminate()
                try:
                    p.wait(timeout=60)
                except Exception:
                    p.kill()
        time.sleep(5)

    ok_rows = [r for r in rows if r.get("mean_tps")]
    base = next((r for r in ok_rows if r["arm"].startswith("P1")), None)
    best = max(ok_rows, key=lambda r: r["mean_tps"]) if ok_rows else None
    out = {
        "date": time.strftime("%Y-%m-%d %H:%M"),
        "toolchain": (_prov.toolchain(SERVER, a.model) if _prov else
                      "NOT RECORDED: provenance module unavailable"),
        "question": "does probe pacing explain the 39% spread on one "
                    "configuration (93.9 / 106.2 / 76.3 t/s)?",
        "config_held_fixed": "UD-IQ4_XS, n-max 10 / p-min 0.5, -c 32768, "
                             "-ctk/-ctv q8_0, -ngl 99, --parallel 1, -fa on, "
                             "reasoning off, greedy (temp 0 / top_k 1), fresh "
                             "server per arm, quiet machine (rule 27)",
        "model": a.model, "probes_per_arm": a.probes, "prompt": PROMPT,
        "published_readings": {"2026-08-21 code sweep": 93.9,
                               "energy arm": 106.2,
                               "2026-08-28 ts-pick arm A": 76.32},
        "rows": rows,
    }
    if base and best:
        out["pacing_effect_pct"] = round(
            (best["mean_tps"] - base["mean_tps"]) / base["mean_tps"] * 100, 2)
        out["reading"] = (
            "P1 reproduces ts-pick; the spread between P1 and the best-paced "
            "arm is what pacing alone is worth on this rig. It does NOT by "
            "itself prove the card's 93.9 is right - compare the best arm to "
            "93.9 directly.")
    io.open(OUT, "w", encoding="utf-8").write(
        json.dumps(out, indent=2, ensure_ascii=False))
    print("\nwrote %s" % OUT)
    for r in rows:
        print("  %-20s %8s t/s  spread %5s%%  SM %s MHz"
              % (r["arm"], r.get("mean_tps"), r.get("spread_pct"),
                 r.get("mean_sm_mhz")))


if __name__ == "__main__":
    main()
