"""Does the full 262,144-token window do work that half of it cannot?

    python needle-at-depth.py --ctx 262144 --tag _262k

THE QUESTION, and why it gates a recommendation. This page ships windows up to
180,224 tokens and is about to be asked whether to add a file so a reader can
have the full native 262,144 WITH vision. Register entry 2 says plainly what is
wrong with that: every shipped window beyond 8k is **speed-verified and
quality-unverified at depth**. No retrieval probe was ever run. A window that
holds tokens but cannot find them is a number, not a capability - and the only
long-context evidence on the page is CITED, not measured, and says that about
half of models claiming a window do not really have it.

So this measures the thing the recommendation actually depends on: **can the
model still retrieve a specific fact from a specific depth?**

THE DESIGN, and the trick that makes it affordable. The register prices a full
needle grid at ~12 h of GPU because prefill dominates. This costs one prefill
per window:

  - the filler carries SEVERAL needles at known fractions of the fill
    (10 / 30 / 50 / 70 / 90 %), each an unguessable value
  - the whole thing is prefilled ONCE
  - then each needle is asked for in its own small request, which hits the
    server's prefix cache and costs almost nothing

That turns N deep probes into one deep prefill plus N cheap questions.

WHY THE NEEDLES LOOK LIKE THE FILLER. A needle that reads differently from its
surroundings is found by shape rather than by attention - the model can spot the
odd sentence out without understanding anything. These use the same "Note N:"
sentence frame as the filler and differ only in carrying a key, so retrieving
one means actually locating the right note among tens of thousands.

WHAT MAKES A RESULT MEAN SOMETHING. Compare the SAME relative depths across two
windows. If 90 % of 131,072 retrieves and 90 % of 262,144 does not, the extra
context is nominal and the bigger window buys nothing but memory pressure. If
both retrieve, the window is real and worth recommending.

Scored on exact match of an unguessable key, so a wrong answer cannot be a lucky
guess, and a control question with no needle catches confabulation.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import gpu_lock

SERVER = os.environ.get("LLAMA_SERVER", r"E:\AI\llama.cpp\llama-server.exe")
LMS = r"C:\Users\chink\.lmstudio\models"
DEFAULT_MODEL = os.path.join(LMS, r"unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-Q2_K_XL.gguf")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "..", "results", "qwen38-27b-blind", "data", "register")
PORT = 1242
BASE = "http://127.0.0.1:%d" % PORT

DEPTHS = [10, 30, 50, 70, 90]          # per cent of the fill
SECTORS = ["GAMMA-17", "DELTA-42", "SIGMA-08", "OMEGA-23", "KAPPA-91"]
KEYS = ["4823-XQ", "9176-BT", "5304-ZM", "2758-VK", "6091-LR"]
CONTROL_SECTOR = "THETA-55"            # never planted: catches confabulation


def build(fill_tokens):
    """Filler with needles wearing the same sentence frame as everything else."""
    lines = ["Operations log. Read it, then answer the question at the end."]
    n_lines = int(fill_tokens / 58.7)
    plant = {int(n_lines * d / 100.0): i for i, d in enumerate(DEPTHS)}
    for i in range(1, n_lines + 1):
        if i in plant:
            k = plant[i]
            lines.append(
                "Note %d: subsystem %s reported latency %d ms on shard %d, retry "
                "budget %d, calibration key %s, remark: threshold crossed only when "
                "the moving median over window %d exceeded baseline by %d percent."
                % (i, SECTORS[k], (17 * i) % 993, i % 13, (3 * i) % 29, KEYS[k],
                   (5 * i) % 47, (11 * i) % 83))
        else:
            frag = format((i * 48271) % 1048573, "x")
            lines.append(
                "Note %d: subsystem alpha-%d reported latency %d ms on shard %d, retry "
                "budget %d, digest fragment %s, remark: threshold crossed only when the "
                "moving median over window %d exceeded baseline by %d percent."
                % (i, (i * 7) % 97, (17 * i) % 993, i % 13, (3 * i) % 29, frag,
                   (5 * i) % 47, (11 * i) % 83))
    return "\n".join(lines)


def post(payload, timeout=3600):
    req = urllib.request.Request(BASE + "/v1/chat/completions",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def ask(body, question):
    r = post({"model": "qwen/qwen3.8-27b", "temperature": 0, "top_k": 1,
              "max_tokens": 120, "cache_prompt": True,
              "messages": [{"role": "user", "content": body + "\n\nQUESTION: " + question}]})
    t = r.get("timings", {})
    return (r["choices"][0]["message"].get("content") or "").strip(), t.get("prompt_n"), t.get("prompt_ms")


def norm(s):
    s = (s or "").strip().split("\n")[-1].strip().strip(".").strip()
    s = re.sub(r"^(the\s+|answer[:\s]+|it\s+is\s+|calibration key[:\s]+)", "", s, flags=re.I)
    return s.strip().strip('"').strip("'").strip("*").upper()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ctx", type=int, default=262144)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--fill-frac", type=float, default=0.90)
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    for p, w in ((SERVER, "llama-server"), (a.model, "model")):
        if not os.path.exists(p):
            sys.exit("missing %s: %s" % (w, p))

    fill = int(a.ctx * a.fill_frac)
    print("model %s | -c %d | filling to ~%d tokens (%.0f%%)"
          % (os.path.basename(a.model), a.ctx, fill, a.fill_frac * 100))
    print("needles at %s%% of the fill, same sentence frame as the filler"
          % "/".join(str(d) for d in DEPTHS))

    args = [SERVER, "-m", a.model, "--alias", "qwen/qwen3.8-27b",
            "-ngl", "99", "-c", str(a.ctx), "--parallel", "1",
            "-ctk", "q8_0", "-ctv", "q8_0", "--spec-type", "none",
            "--jinja", "--reasoning", "off",
            "--host", "127.0.0.1", "--port", str(PORT)]
    logdir = os.path.join(OUT, "needle-logs")
    os.makedirs(logdir, exist_ok=True)
    lf = open(os.path.join(logdir, "needle%s.log" % (a.tag or "")), "w",
              encoding="utf-8", errors="replace")
    proc = gpu_lock.serve(args, stdout=lf, stderr=subprocess.STDOUT)
    t0 = time.time()
    up = False
    while time.time() - t0 < 1200:
        if proc.poll() is not None:
            break
        try:
            with urllib.request.urlopen(BASE + "/health", timeout=2) as r:
                if json.loads(r.read().decode()).get("status") == "ok":
                    up = True; break
        except Exception:
            pass
        time.sleep(2)
    if not up:
        print("SERVER FAILED"); proc.kill(); lf.close(); sys.exit(1)

    body = build(fill)
    rows = []
    try:
        # first request pays the whole prefill; the rest reuse the prefix cache
        q0 = ("What is the calibration key reported for subsystem %s? "
              "Reply with the key only." % SECTORS[0])
        t1 = time.time()
        ans, pn, pms = ask(body, q0)
        print("  prefill %s tokens in %.0fs" % (pn, (pms or 0) / 1000.0))
        ok = norm(ans) == norm(KEYS[0])
        rows.append({"depth_pct": DEPTHS[0], "sector": SECTORS[0], "expected": KEYS[0],
                     "got": ans[:60], "correct": ok, "prompt_n": pn})
        print("  %3d%%  %-9s expect %-9s got %-16s %s"
              % (DEPTHS[0], SECTORS[0], KEYS[0], ans[:16].replace("\n", " "), "OK" if ok else "MISS"))

        for d, sec, key in zip(DEPTHS[1:], SECTORS[1:], KEYS[1:]):
            q = ("What is the calibration key reported for subsystem %s? "
                 "Reply with the key only." % sec)
            ans, pn, pms = ask(body, q)
            ok = norm(ans) == norm(key)
            rows.append({"depth_pct": d, "sector": sec, "expected": key,
                         "got": ans[:60], "correct": ok, "prompt_n": pn})
            print("  %3d%%  %-9s expect %-9s got %-16s %s"
                  % (d, sec, key, ans[:16].replace("\n", " "), "OK" if ok else "MISS"))

        # control: a sector that was never planted
        ans, _, _ = ask(body, "What is the calibration key reported for subsystem %s? "
                              "Reply with the key only, or say NONE if it is absent."
                              % CONTROL_SECTOR)
        confab = not re.search(r"\bnone\b|not (present|found|mention)|no .*key|absent",
                               ans, re.I)
        rows.append({"depth_pct": None, "sector": CONTROL_SECTOR, "expected": "NONE",
                     "got": ans[:60], "correct": not confab, "control": True})
        print("  ctrl  %-9s expect NONE      got %-16s %s"
              % (CONTROL_SECTOR, ans[:16].replace("\n", " "),
                 "OK" if not confab else "CONFABULATED"))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
        lf.close()

    found = [r for r in rows if not r.get("control")]
    hit = sum(1 for r in found if r["correct"])
    print("\n  RETRIEVED %d of %d needles at -c %d" % (hit, len(found), a.ctx))
    os.makedirs(OUT, exist_ok=True)
    out = os.path.join(OUT, "needle%s.json" % (a.tag or ""))
    json.dump({"date": time.strftime("%Y-%m-%d %H:%M"), "ctx": a.ctx,
               "model": os.path.basename(a.model), "fill_target": fill,
               "retrieved": hit, "of": len(found), "rows": rows},
              open(out, "w", encoding="utf-8"), indent=1)
    print("  -> %s" % out)


if __name__ == "__main__":
    main()
