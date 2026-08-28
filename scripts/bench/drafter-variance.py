#!/usr/bin/env python3
"""How much does ONE speculative-decoding arm vary from probe to probe?

    drafter-variance.py --model <path.gguf> [--probes 20]

WHY THIS EXISTS. Every speed probe in this campaign has been n=3, and on
2026-08-28 that turned out to matter. Re-running the archived head-to-head
script unmodified reproduced the plain-decode arms within 1-3% of their
published values and missed the SPECULATIVE arms by 7-11%:

    UD-IQ4_XS  drafter off   41.85 today   42.34 published   -1.2%
    UD-IQ4_XS  drafter ON    80.50 today   86.91 published   -7.4%
    UD-Q2_K_XL drafter off   44.47 today   45.66 published   -2.6%
    UD-Q2_K_XL drafter ON    68.84 today   77.01 published  -10.6%

A machine, driver or thermal cause would move both kinds of arm together. It
did not. The build is ruled out: all 18 ggml compute libraries are dated
2026-08-19, before the sweep that published those numbers and unchanged since.

The scatter points at the answer. Across three probes the drafter arms spread
8.9 to 10.0% while the plain arms spread 3.0 to 3.7% - one drafter probe read
77.59 and another 85.79 inside the same arm - and the published 86.91 sits just
above today's highest single probe. So the "gap" may be substantially the
drafter arm's own run-to-run variance, which nobody has ever measured, because
three probes cannot see a distribution.

WHAT THIS MEASURES. One configuration, many probes, nothing else moving:
UD-IQ4_XS, n-max 10 / p-min 0.5, -c 32768, q8_0 KV, -ngl 99, --parallel 1,
-fa on, reasoning off, greedy, 700 predicted tokens, the same prompt the
archived sweep used. One server, held up for the whole run so that no arm
inherits another's load; a discarded warmup (rule 12); then N settled probes
back to back with no cooling gap, which the pacing probe showed is the faster
and more honest regime.

WHAT IT SETTLES. If the published 86.91 falls inside the distribution this
measures, then the drafter numbers on this page carry a much wider band than
they have been printed with, and the honest fix is to publish that band. If it
falls outside, the drift is real and something changed that nothing recorded -
which would be a second finding, not a smaller one.

Acceptance and mean draft length are recorded per probe, because rule 11 says
mean draft length is the throughput predictor, and if throughput wanders while
draft length holds still then the cause is not the drafter's behaviour.
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import provenance as _prov
except Exception:                                        # pragma: no cover
    _prov = None

SERVER = os.environ.get("LLAMA_SERVER", r"E:\AI\llama.cpp\llama-server.exe")
PORT = 1295
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(REPO, "results", "qwen38-27b-blind", "data", "followup",
                   "drafter-variance.json")

COMMON = ["--alias", "qwen", "--host", "127.0.0.1", "-ngl", "99",
          "--parallel", "1", "-fa", "on", "--jinja", "--reasoning", "off",
          "--metrics"]
SPEC = ["--spec-type", "draft-mtp",
        "--spec-draft-n-max", "10", "--spec-draft-p-min", "0.5"]
CTX, NPREDICT = "32768", 700

# The archived sweep's prompt, verbatim, because content decides acceptance and
# therefore decides the thing being measured.
PROMPT = "\n".join([
    "Write a single self-contained JavaScript module that implements a fixed-window",
    "rate limiter with a pluggable clock, a per-key limit, and an eviction sweep that",
    "runs at most once per window. Include JSDoc on every exported symbol and a short",
    "usage example at the end. Do not explain the code outside the module.",
])

PUBLISHED = 86.91          # UD-IQ4_XS, drafter on, this configuration


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


def spec_counters():
    try:
        with urllib.request.urlopen(
                "http://127.0.0.1:%d/metrics" % PORT, timeout=10) as r:
            txt = r.read().decode()
    except Exception:
        return {}
    out = {}
    for line in txt.split("\n"):
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split()
        if len(parts) >= 2 and "spec" in parts[0]:
            try:
                key = parts[0].split("{")[0]
                # Strip the exporter prefix. Storing "llamacpp:spec_decode_x"
                # and reading "spec_decode_x" is how this probe lost its
                # acceptance column on twenty consecutive probes.
                if ":" in key:
                    key = key.split(":", 1)[1]
                out[key] = float(parts[-1])
            except ValueError:
                pass
    return out


def probe():
    body = json.dumps({
        "model": "qwen",
        "messages": [{"role": "user", "content": PROMPT}],
        "temperature": 0.0, "top_k": 1, "max_tokens": NPREDICT,
    }).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:%d/v1/chat/completions" % PORT, data=body,
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=900) as r:
        d = json.loads(r.read().decode())
    wall = time.time() - t0
    t = d.get("timings", {}) or {}
    n, ms = t.get("predicted_n") or 0, t.get("predicted_ms") or 0
    return {"decode_tps": (n / (ms / 1000.0)) if ms else None,
            "predicted_n": n, "wall_s": round(wall, 2), "clocks": clocks()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--probes", type=int, default=20)
    ap.add_argument("--tag", default="",
                    help="artefact suffix. Without one a second run"
                         " overwrites the first, and two runs of this"
                         " probe 15 minutes apart produced"
                         " non-overlapping distributions - so the second"
                         " destroying the first is a real loss.")
    a = ap.parse_args()

    if cap_ok() is False:
        sys.exit("REFUSING: power.limit != power.default_limit. "
                 "nvidia-smi -pl 350 first.")

    out_path = (OUT if not a.tag else
                OUT.replace(".json", "-%s.json" % a.tag))
    logdir = os.path.dirname(out_path)
    if not os.path.isdir(logdir):
        os.makedirs(logdir)
    log = os.path.join(logdir, "drafter-variance%s-server.log"
                       % (("-" + a.tag) if a.tag else ""))

    rows = []
    with io.open(log, "w", encoding="utf-8", errors="replace") as lf:
        p = subprocess.Popen(
            [SERVER, "-m", a.model] + COMMON +
            ["-c", CTX, "-ctk", "q8_0", "-ctv", "q8_0",
             "--port", str(PORT)] + SPEC,
            stdout=lf, stderr=subprocess.STDOUT)
        try:
            if not wait_ready(p):
                sys.exit("server never became ready; see %s" % log)
            probe()                                  # rule 12: discarded
            prev = spec_counters()
            for i in range(a.probes):
                r = probe()
                cur = spec_counters()
                dd = (cur.get("spec_decode_num_drafts_total", 0)
                      - prev.get("spec_decode_num_drafts_total", 0))
                dt = (cur.get("spec_decode_num_draft_tokens_total", 0)
                      - prev.get("spec_decode_num_draft_tokens_total", 0))
                da = (cur.get("spec_decode_num_accepted_tokens_total", 0)
                      - prev.get("spec_decode_num_accepted_tokens_total", 0))
                prev = cur
                r["accept_rate"] = round(da / dt, 4) if dt else None
                r["mean_draft_len"] = round(dt / dd, 3) if dd else None
                rows.append(r)
                c = r.get("clocks") or {}
                print("  probe %2d: %6.2f t/s  accept %-6s len %-6s "
                      "%s MHz %s C"
                      % (i + 1, r["decode_tps"] or 0, r["accept_rate"],
                         r["mean_draft_len"], c.get("sm_mhz"),
                         c.get("temp_c")), flush=True)
        finally:
            p.terminate()
            try:
                p.wait(timeout=60)
            except Exception:
                p.kill()

    tps = [r["decode_tps"] for r in rows if r["decode_tps"]]
    if not tps:
        sys.exit("no probe produced a throughput reading")
    mean = statistics.mean(tps)
    sd = statistics.stdev(tps) if len(tps) > 1 else 0.0
    lo, hi = min(tps), max(tps)
    out = {
        "date": time.strftime("%Y-%m-%d %H:%M"),
        "question": "how wide is ONE speculative-decoding arm's own "
                    "distribution, and does the published 86.91 t/s fall "
                    "inside it?",
        "toolchain": (_prov.toolchain(SERVER, a.model) if _prov else
                      "NOT RECORDED: provenance module unavailable"),
        "conditions": "UD-IQ4_XS, n-max 10 / p-min 0.5, -c 32768, "
                      "-ctk/-ctv q8_0, -ngl 99, --parallel 1, -fa on, "
                      "reasoning off, greedy (temp 0 / top_k 1), 700 "
                      "predicted tokens, ONE server held up for the whole "
                      "run, one warmup discarded (rule 12), probes back to "
                      "back with no cooling gap, quiet machine (rule 27)",
        "prompt": PROMPT,
        "n_probes": len(tps),
        "mean_tps": round(mean, 2),
        "sd_tps": round(sd, 3),
        "cv_pct": round(sd / mean * 100, 2) if mean else None,
        "min_tps": round(lo, 2), "max_tps": round(hi, 2),
        "range_pct": round((hi - lo) / mean * 100, 2) if mean else None,
        "published_reference": PUBLISHED,
        "published_inside_range": bool(lo <= PUBLISHED <= hi),
        "published_z": (round((PUBLISHED - mean) / sd, 2) if sd else None),
        "reading": ("If the published figure lies inside this range, the "
                    "drafter numbers on this page need a band rather than a "
                    "point. If it lies outside, something changed that "
                    "nothing recorded, and that is a separate finding."),
        "probes": rows,
    }
    io.open(out_path, "w", encoding="utf-8").write(
        json.dumps(out, indent=2, ensure_ascii=False))
    print("\n n=%d  mean %.2f  sd %.3f  cv %.2f%%  range %.2f-%.2f (%.2f%%)"
          % (len(tps), mean, sd, out["cv_pct"], lo, hi, out["range_pct"]))
    print(" published %.2f is %s the observed range%s"
          % (PUBLISHED, "INSIDE" if out["published_inside_range"] else "OUTSIDE",
             ("  (z = %+.2f)" % out["published_z"]) if out["published_z"] else ""))
    print("wrote %s" % out_path)


if __name__ == "__main__":
    main()
