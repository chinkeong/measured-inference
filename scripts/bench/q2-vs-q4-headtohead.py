"""Replication of the published drafter pair: is UD-Q2_K_XL faster than UD-IQ4_XS?

    python q2-vs-q4-headtohead.py [--n-max 10] [--p-min 0.5] [--tag NAME]

WHY THIS EXISTS. A reader argued from memory bandwidth that UD-Q2_K_XL must be
faster: it is 9.154 GiB against UD-IQ4_XS's 13.274, so 31% fewer bytes read per
token. The published pair says the opposite once speculation is on - 77.01 t/s
against 86.91 - and explains it by the draft head being quantised too.

HOW THE FIRST VERSION OF THIS SCRIPT GOT IT WRONG, recorded because the mistake
is the useful part. It was written as a "replication" WITHOUT first reading the
script that produced the published numbers. Four conditions silently differed:
`-fa on` was missing, `--reasoning off` was replaced by a `reasoning_effort`
request field, `--load-mode none` was added, and the prompt was a different
program. Three of four arms still matched, so the one that did not looked like a
failure to reproduce - when it was simply a different measurement. A replication
that has not read the original's conditions is not a replication, and this
campaign's own rule 3 says to state them.

Everything below is taken VERBATIM from
results/qwen38-27b-blind/work/drafter-at-2bit.ps1, which produced the published
table: the prompt, the server flags, the request body, the probe protocol and
its sleeps. The only intentional difference is the language, because the harness
is moving to Linux and new instruments are written in Python.

PROTOCOL, from the original and from this campaign's law:
  rule 12 - one warmup probe per arm, DISCARDED, then three settled probes.
  rule 11 - acceptance is reported, but MEAN DRAFT LENGTH is the throughput
      predictor. Content decides both, which is why the prompt must match.
  rule 25 - the drafter-on arms default to n-max 10 / p-min 0.5, which is what
      the published pair used. serve-qwen.bat ships that on one pick and
      n-max 4 / p-min 0.75 on four, so the setting is a flag here rather than a
      constant: the two are not interchangeable, and neither should be called
      "the shipped" setting on its own.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import refarm   # Sampler, smi(), quiet_report()
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

SERVER = os.environ.get("LLAMA_SERVER", r"E:\AI\llama.cpp\llama-server.exe")
MODELS = os.environ.get(
    "QWEN_DIR", os.environ.get("MODEL_DIR", r"C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF"))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "..", "results", "qwen38-27b-blind", "data", "register")
PORT = 1237
BASE = "http://127.0.0.1:%d" % PORT

FILES = [("UD-IQ4_XS", "Qwen3.8-27B-UD-IQ4_XS.gguf", 13.274),
         ("UD-Q2_K_XL", "Qwen3.8-27B-UD-Q2_K_XL.gguf", 9.154)]

# VERBATIM from drafter-at-2bit.ps1. Its own comment: "A novel coding prompt:
# textbook algorithms inflate a draft head's hit rate, so this is the same class
# of prompt round 2's matched sweep used."
PROMPT = "\n".join([
    "Write a single self-contained JavaScript module that implements a fixed-window",
    "rate limiter with a pluggable clock, a per-key limit, and an eviction sweep that",
    "runs at most once per window. Include JSDoc on every exported symbol and a short",
    "usage example at the end. Do not explain the code outside the module.",
])

CTX, NPREDICT, SETTLED = 32768, 700, 3
NMAX, PMIN = 10, 0.5          # the published pair's setting

PUBLISHED = {("UD-IQ4_XS", False): 42.34, ("UD-IQ4_XS", True): 86.91,
             ("UD-Q2_K_XL", False): 45.66, ("UD-Q2_K_XL", True): 77.01}


def post(path, payload, timeout=900):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def start(model_path, drafter):
    # VERBATIM flag set from drafter-at-2bit.ps1 lines 79-80.
    #
    # CORRECTED 2026-08-25: an earlier version of this comment said `-fa on` and
    # `--reasoning off` were BOTH load-bearing. Only the second one is.
    # `-fa` defaults to `auto`, and auto resolves to enabled here - the server
    # log reads "enabling flash_attn since it is required for quantized V cache"
    # for the target context, because `-ctk/-ctv q8_0` forces it. So Flash
    # Attention was already on in the runs that read low. The whole gap is
    # `--reasoning off`, which changes what the model emits and therefore what
    # the drafter has to guess: acceptance moved 0.523 -> 0.611.
    args = [SERVER, "-m", model_path, "--alias", "qwen/qwen3.8-27b",
            "-ngl", "99", "-c", str(CTX), "-fa", "on", "--parallel", "1",
            "-ctk", "q8_0", "-ctv", "q8_0", "--jinja", "--reasoning", "off"]
    if drafter:
        args += ["--spec-type", "draft-mtp",
                 "--spec-draft-n-max", str(NMAX), "--spec-draft-p-min", str(PMIN)]
    else:
        args += ["--spec-type", "none"]
    args += ["--host", "127.0.0.1", "--port", str(PORT)]
    return gpu_lock.serve(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait(proc, timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(BASE + "/health", timeout=2) as r:
                if json.loads(r.read().decode()).get("status") == "ok":
                    return True
        except Exception:
            pass
        time.sleep(2)
    return False


def stop(p):
    if p and p.poll() is None:
        p.terminate()
        try:
            p.wait(timeout=30)
        except subprocess.TimeoutExpired:
            p.kill()
    # wait for the card to actually release rather than assuming four seconds
    for _ in range(20):
        time.sleep(1)
        try:
            if float(refarm.smi("memory.used")) < 2500:
                return
        except Exception:
            pass


GPU = None   # a refarm.Sampler, started in main()


def probe():
    """Matches Invoke-Probe in scripts/quant-ladder/ladder-lib.ps1: greedy by
    construction, no cache_prompt field, no chat-template kwargs.

    GPU COLUMNS, added 2026-08-25. This script's headline is a t/s delta
    between FOUR SEPARATE SERVER LOADS, and it recorded nothing about the
    machine those loads ran on. That is the exact gap that left
    sampling-bridge.py's 64.32 t/s permanently undiagnosable. Host CPU load
    alone costs 5.4% of decode - 24% at worst - while the SM clock RISES, so a
    cross-load delta of a few per cent is inside the error of an unrecorded
    machine (`scripts/bench/cpu-contention.py`)."""
    t0 = time.time()
    r = post("/v1/chat/completions", {
        "model": "qwen/qwen3.8-27b", "temperature": 0, "top_k": 1,
        "max_tokens": NPREDICT,
        "messages": [{"role": "user", "content": PROMPT}]})
    t1 = time.time()
    win = [x for x in GPU.rows if t0 <= x[0] <= t1] if GPU else []
    t = r.get("timings", {})
    dn, da = t.get("draft_n"), t.get("draft_n_accepted")
    pn = t.get("predicted_n")
    return {
        "decode_tps": round(t.get("predicted_per_second", 0), 2),
        "predicted_n": pn, "prompt_n": t.get("prompt_n"),
        "draft_n": dn, "draft_accepted": da,
        "acceptance": round(da / dn, 3) if dn else None,
        # rule 11: mean draft length. Each verify pass emits one non-drafted
        # token, so passes = predicted_n - accepted and length = drafted/passes.
        "draft_len": (round(dn / (pn - da), 2)
                      if dn and pn and da is not None and (pn - da) > 0 else None),
        "sm_mhz": round(sum(x[1] for x in win) / len(win)) if win else None,
        "temp": round(sum(x[2] for x in win) / len(win), 1) if win else None,
        "watt": round(sum(x[3] for x in win) / len(win), 1) if win else None,
    }


def run_arm(label, model_path, drafter):
    print("\n=== %-12s drafter %-3s ===" % (label, "ON" if drafter else "off"))
    p = start(model_path, drafter)
    if not wait(p):
        print("  SERVER FAILED")
        stop(p)
        return None
    try:
        w = probe()                       # rule 12: warmup, discarded
        print("  warmup (discarded): %.2f t/s" % w["decode_tps"])
        time.sleep(5)                     # the original waits 5 s after the discard
        rows = []
        for i in range(SETTLED):
            if i:
                time.sleep(3)             # and 3 s between settled probes
            r = probe()
            rows.append(r)
            print("  probe %d: %6.2f t/s  acceptance %-7s draft_len %s"
                  % (i + 1, r["decode_tps"], r["acceptance"], r["draft_len"]))
    finally:
        stop(p)
    tps = [r["decode_tps"] for r in rows]
    acc = [r["acceptance"] for r in rows if r["acceptance"] is not None]
    dl = [r["draft_len"] for r in rows if r["draft_len"] is not None]
    mean = sum(tps) / len(tps)
    return {"file": label, "drafter": bool(drafter), "mean_tps": round(mean, 2),
            "spread_pct": round((max(tps) - min(tps)) / mean * 100, 1),
            "acceptance": round(sum(acc) / len(acc), 3) if acc else None,
            "draft_len": round(sum(dl) / len(dl), 2) if dl else None,
            "warmup_tps": w["decode_tps"], "probes": rows}


def main():
    global GPU
    GPU = refarm.Sampler()
    GPU.start()
    # rule 27: a speed measurement requires a quiet machine, and a report
    # that cannot say the machine was quiet cannot defend its levels.
    q = refarm.quiet_report()
    print("host: %s (cpu probe %.4f s, %sx idle)"
          % (q["status"], q["cpu_probe_s"], q.get("ratio", "?")))
    if q["status"] == "BUSY":
        print("  " + q["detail"])
    global NMAX, PMIN
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-max", type=int, default=NMAX)
    ap.add_argument("--p-min", type=float, default=PMIN)
    ap.add_argument("--tag", default="")
    opts = ap.parse_args()
    NMAX, PMIN = opts.n_max, opts.p_min
    print("REPLICATION of results/qwen38-27b-blind/work/drafter-at-2bit.ps1")
    print("drafter setting: n-max %d / p-min %s" % (NMAX, PMIN))
    print("flags: -ngl 99 -c %d -fa on --parallel 1 -ctk q8_0 -ctv q8_0 "
          "--jinja --reasoning off" % CTX)
    if not os.path.exists(SERVER):
        sys.exit("no llama-server at %s" % SERVER)

    arms = []
    for label, fn, gib in FILES:
        path = os.path.join(MODELS, fn)
        if not os.path.exists(path):
            sys.exit("missing model %s" % path)
        for drafter in (False, True):
            a = run_arm(label, path, drafter)
            if a:
                a["gib"] = gib
                arms.append(a)

    matched = (NMAX, PMIN) == (10, 0.5)
    print("\n%-12s %-8s %-9s %-10s %-9s %-11s %s"
          % ("file", "drafter", "mean t/s", "published", "delta", "acceptance", "draft_len"))
    for a in arms:
        pub = PUBLISHED.get((a["file"], a["drafter"])) if matched else None
        delta = (a["mean_tps"] - pub) / pub * 100 if pub else None
        print("%-12s %-8s %-9s %-10s %-9s %-11s %s"
              % (a["file"], "ON" if a["drafter"] else "off", a["mean_tps"],
                 pub if pub else "-",
                 ("%+.1f%%" % delta) if delta is not None else "-",
                 a["acceptance"], a["draft_len"]))
    if not matched:
        print("  (published column blank: it was measured at n10/p0.5, not this setting)")

    def get(f, d):
        return next((a for a in arms if a["file"] == f and a["drafter"] == d), None)

    print("\n---- the question ----")
    for d, name in ((False, "drafter OFF"), (True, "drafter ON ")):
        q4, q2 = get("UD-IQ4_XS", d), get("UD-Q2_K_XL", d)
        if q4 and q2:
            diff = (q2["mean_tps"] - q4["mean_tps"]) / q4["mean_tps"] * 100
            print("  %-13s %6.2f vs %6.2f  ->  UD-Q2_K_XL is %s by %.1f%%"
                  % (name, q2["mean_tps"], q4["mean_tps"],
                     "FASTER" if diff > 0 else "SLOWER", abs(diff)))

    os.makedirs(OUT, exist_ok=True)
    out = os.path.join(OUT, "q2-vs-q4-headtohead%s.json" % (opts.tag or ""))
    json.dump({"date": time.strftime("%Y-%m-%d %H:%M"), "ctx": CTX,
        "toolchain": (_prov.toolchain(SERVER) if _prov else
                      "NOT RECORDED: provenance module unavailable"),
               "spec_n_max": NMAX, "spec_p_min": PMIN,
               "replicates": "results/qwen38-27b-blind/work/drafter-at-2bit.ps1",
               "flags": "-ngl 99 -c 32768 -fa on --parallel 1 -ctk q8_0 -ctv q8_0 "
                        "--jinja --reasoning off",
               "prompt": PROMPT,
               "published": {"%s|%s" % k: v for k, v in PUBLISHED.items()},
               "arms": arms}, open(out, "w", encoding="utf-8"), indent=1)
    print("\n-> %s" % out)


main()
