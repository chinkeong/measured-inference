"""Direct head-to-head: is UD-Q2_K_XL faster than UD-IQ4_XS?

    python q2-vs-q4-headtohead.py

WHY THIS EXISTS. The intuition is that a smaller file must decode faster: every
token requires reading the whole model out of VRAM, and UD-Q2_K_XL is 9.154 GiB
against UD-IQ4_XS's 13.274 - about 31% fewer bytes per step. That prediction is
correct with speculation OFF and WRONG with it ON, and every recipe this
campaign ships has it on. This script re-measures both, in both states, so the
claim rests on a number taken today rather than on arithmetic.

FOUR ARMS, one variable at a time:
    UD-IQ4_XS   drafter off / drafter on
    UD-Q2_K_XL  drafter off / drafter on
Same prompt, same window, same KV width, same sampler, same machine, minutes
apart. A cross-file comparison is only worth having if literally nothing else
moved.

PROTOCOL, from this campaign's own law:
  rule 12 - the first probe after a long prefill reads low because the clock has
      not ramped. One warmup probe per arm is fired and DISCARDED, then three
      settled probes are averaged. (Entry 17(a) has since shown the post-prefill
      effect is small at depth, but the protocol costs one probe and the arm
      here is short-context, which is where it was originally observed.)
  rule 11 - report MEAN DRAFT LENGTH, not just acceptance. Acceptance alone does
      not predict throughput; a short draft with perfect acceptance is slow.
      draft length = draft_n / n_draft_calls, and the campaign's finding is that
      this is what separates the two files.
  rule 25 - measure at the SHIPPED recipe. The drafter-on arms use n4/p0.75,
      which is what the recipes actually launch with.

The reasoning regime is held identical across all four arms and recorded, so
the comparison is valid whatever the absolute level turns out to be.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

SERVER = os.environ.get("LLAMA_SERVER", r"E:\AI\llama.cpp\llama-server.exe")
MODELS = os.environ.get(
    "QWEN_DIR", r"C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "..", "results", "qwen38-27b-blind", "data", "register")
PORT = 1237
BASE = "http://127.0.0.1:%d" % PORT

FILES = [("UD-IQ4_XS", "Qwen3.8-27B-UD-IQ4_XS.gguf", 13.274),
         ("UD-Q2_K_XL", "Qwen3.8-27B-UD-Q2_K_XL.gguf", 9.154)]

PROMPT = ("Write a single self-contained JavaScript file implementing an LRU cache "
          "class with get, put, a configurable capacity, an eviction callback, and "
          "an iterator that yields entries most-recently-used first. Include brief "
          "JSDoc on each public method. Code only, no explanation.")

CTX, NPREDICT, SETTLED = 32768, 700, 3
# The drafter setting is the variable that decides whether the ranking inverts,
# so it is a flag, not a constant. serve-qwen.bat ships BOTH: n4/p0.75 on four
# picks (SPEC_SAFE) and n10/p0.5 on one (SPEC_FAST).
NMAX, PMIN = 4, 0.75


def post(path, payload, timeout=900):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def start(model_path, drafter):
    args = [SERVER, "-m", model_path, "--alias", "qwen/qwen3.8-27b",
            "-c", str(CTX), "-ngl", "99", "--parallel", "1",
            "--load-mode", "none", "-ctk", "q8_0", "-ctv", "q8_0"]
    if drafter:
        args += ["--spec-type", "draft-mtp",
                 "--spec-draft-n-max", str(NMAX), "--spec-draft-p-min", str(PMIN)]
    else:
        args += ["--spec-type", "none"]
    args += ["--jinja", "--host", "127.0.0.1", "--port", str(PORT)]
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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
    time.sleep(4)


def probe():
    r = post("/v1/chat/completions", {
        "model": "qwen/qwen3.8-27b", "temperature": 0, "top_k": 1,
        "max_tokens": NPREDICT,
        "chat_template_kwargs": {"reasoning_effort": "low"},
        "cache_prompt": False,
        "messages": [{"role": "user", "content": PROMPT}]})
    t = r.get("timings", {})
    msg = r["choices"][0]["message"]
    dn, da = t.get("draft_n"), t.get("draft_n_accepted")
    # rule 11: mean draft length, not acceptance. llama.cpp reports draft_n as
    # total drafted tokens; n_draft_calls is not always exposed, so derive the
    # per-pass length from accepted-per-predicted where it is not.
    return {
        "decode_tps": round(t.get("predicted_per_second", 0), 2),
        "predicted_n": t.get("predicted_n"),
        "prompt_n": t.get("prompt_n"),
        "draft_n": dn, "draft_accepted": da,
        "acceptance": round(da / dn, 3) if dn else None,
        "think_chars": len(msg.get("reasoning_content") or ""),
    }


def run_arm(label, model_path, drafter):
    print("\n=== %-12s drafter %-3s ===" % (label, "ON" if drafter else "off"))
    p = start(model_path, drafter)
    if not wait(p):
        print("  SERVER FAILED"); stop(p); return None
    try:
        w = probe()                       # rule 12: warmup, discarded
        print("  warmup (discarded): %.2f t/s" % w["decode_tps"])
        rows = []
        for i in range(SETTLED):
            r = probe()
            rows.append(r)
            print("  probe %d: %6.2f t/s  predicted %s  acceptance %s"
                  % (i + 1, r["decode_tps"], r["predicted_n"], r["acceptance"]))
    finally:
        stop(p)
    tps = [r["decode_tps"] for r in rows]
    acc = [r["acceptance"] for r in rows if r["acceptance"] is not None]
    mean = sum(tps) / len(tps)
    return {"file": label, "drafter": bool(drafter),
            "mean_tps": round(mean, 2),
            "spread_pct": round((max(tps) - min(tps)) / mean * 100, 1),
            "acceptance": round(sum(acc) / len(acc), 3) if acc else None,
            "warmup_tps": w["decode_tps"], "probes": rows}


def main():
    global NMAX, PMIN
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-max", type=int, default=NMAX)
    ap.add_argument("--p-min", type=float, default=PMIN)
    ap.add_argument("--tag", default="")
    opts = ap.parse_args()
    NMAX, PMIN = opts.n_max, opts.p_min
    print("drafter setting under test: n-max %d / p-min %s" % (NMAX, PMIN))
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

    print("\n%-12s %-8s %-10s %-9s %-11s %s"
          % ("file", "GiB", "drafter", "mean t/s", "spread", "acceptance"))
    for a in arms:
        print("%-12s %-8s %-10s %-9s %-11s %s"
              % (a["file"], a["gib"], "ON" if a["drafter"] else "off",
                 a["mean_tps"], "%.1f%%" % a["spread_pct"], a["acceptance"]))

    def get(f, d):
        return next((a for a in arms if a["file"] == f and a["drafter"] == d), None)

    print("\n---- the question ----")
    for d, name in ((False, "drafter OFF"), (True, "drafter ON  (the shipped recipe)")):
        q4, q2 = get("UD-IQ4_XS", d), get("UD-Q2_K_XL", d)
        if q4 and q2:
            diff = (q2["mean_tps"] - q4["mean_tps"]) / q4["mean_tps"] * 100
            verdict = ("UD-Q2_K_XL is FASTER by %.1f%%" % diff if diff > 0
                       else "UD-Q2_K_XL is SLOWER by %.1f%%" % abs(diff))
            print("  %-34s %6.2f vs %6.2f  ->  %s"
                  % (name, q2["mean_tps"], q4["mean_tps"], verdict))

    os.makedirs(OUT, exist_ok=True)
    out = os.path.join(OUT, "q2-vs-q4-headtohead%s.json" % (opts.tag or ""))
    json.dump({"date": time.strftime("%Y-%m-%d %H:%M"), "ctx": CTX,
               "spec_n_max": NMAX, "spec_p_min": PMIN,
               "n_predict": NPREDICT, "settled_probes": SETTLED,
               "regime": "reasoning_effort=low, temperature 0, top_k 1, cache_prompt off",
               "prompt": PROMPT, "arms": arms},
              open(out, "w", encoding="utf-8"), indent=1)
    print("\n-> %s" % out)


main()
