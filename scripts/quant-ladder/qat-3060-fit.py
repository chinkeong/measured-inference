"""Can a 12 GB RTX 3060 actually run the QAT Q2_0 file, and how fast?

    python qat-3060-fit.py

WHY. A reader with an RTX 3060 asked how this file compares to the rest. The
quality answer is already measured - it performs like the 2.48-bpw PTQ file -
but that is not what decides anything for them. What decides it is whether the
file FITS, at what context, and how fast it then runs. This campaign has one
VRAM reading for the file (10,476 MiB total at -c 8192) and no speed reading at
all, which is not enough to tell somebody to download 8.16 GB.

THE HARD PART IS THAT THE CARD IS NOT HERE. This rig has a 3090. Two different
kinds of number come out of that, and they must not be mixed:

  MEASURED, and transfers honestly: VRAM ALLOCATION. llama.cpp allocates the
  same weights, KV cache and compute buffers regardless of which CUDA card it
  is on, so "this configuration needs N MiB" is a fact about the configuration,
  not about the 3090. A 3060 owner can subtract their own desktop reserve from
  12,288 MiB and compare.

  DERIVED, and must be labelled so (rule 10): SPEED. Decode is bandwidth-bound,
  and the 3060 has 360 GB/s against the 3090's 936 - a ratio of 0.385. A
  measured 3090 figure scaled by that is an estimate, not a measurement, and
  prefill will NOT scale that way because prefill is compute-bound.

WHAT IT MEASURES. One load per context size, drafter off, q8_0 KV - the
configuration a VRAM-constrained reader should actually use - recording
allocation above an idle baseline and settled decode speed. Then the card's own
recommended drafter (`--spec-type ngram-mod`) at one size, because the
publisher recommends it and it costs almost no memory, so it may be free speed.

THE 8 GB QUESTION ANSWERS ITSELF and is worth stating plainly: the weights
alone are 8.16 GiB = 8,357 MiB. An 8 GB card cannot hold them at any context,
with any KV setting. No measurement needed, but the reader deserves the
sentence.
"""

import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts", "bench"))
import refarm
import gpu_lock

MODEL = r"C:\Users\chink\.lmstudio\models\sdkyuan\qwen3.8-27B-qat-q2_0-gguf\qwen38-27b-qat-q2_0.gguf"
SRV = refarm.SERVER
PORT = 1254
BASE = "http://127.0.0.1:%d" % PORT
OUT = os.path.join(ROOT, "results", "qwen38-27b-blind", "data", "quant-ladder",
                   "qat-q2_0")

WEIGHTS_MIB = 8759266208 / 1024 ** 2          # 8,353 MiB of weights
CARD_3060_MIB = 12288
CARD_3060_8G_MIB = 8192
BW_3090, BW_3060 = 936.0, 360.0

PROMPT = ("Write a single self-contained Python function that merges two sorted "
          "lists into one sorted list without using sort(). Include a docstring "
          "and three example calls. Code only.")
NPREDICT = 400

# (label, ctx, extra flags)
ARMS = [
    ("c4096  no drafter", 4096, []),
    ("c8192  no drafter", 8192, []),
    ("c16384 no drafter", 16384, []),
    ("c32768 no drafter", 32768, []),
    ("c65536 no drafter", 65536, []),
    ("c8192  ngram-mod", 8192, ["--spec-type", "ngram-mod",
                                "--spec-ngram-mod-n-match", "24",
                                "--spec-ngram-mod-n-min", "48",
                                "--spec-ngram-mod-n-max", "64"]),
]


def smi():
    return float(subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        capture_output=True, text=True).stdout.strip().splitlines()[0])


def post(payload, timeout=1800):
    req = urllib.request.Request(BASE + "/v1/chat/completions",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def wait(p, timeout=600):
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


def main():
    os.makedirs(OUT, exist_ok=True)
    q = refarm.quiet_report()
    print("host: %s   (rule 27: speed needs a quiet machine)" % q["status"])
    base = smi()
    print("idle VRAM baseline: %.0f MiB" % base)
    print("weights alone     : %.0f MiB\n" % WEIGHTS_MIB)

    rows = []
    for label, ctx, extra in ARMS:
        args = [SRV, "-m", MODEL, "--alias", "qat", "-ngl", "99",
                "-c", str(ctx), "--parallel", "1", "-fa", "on",
                "-ctk", "q8_0", "-ctv", "q8_0", "--jinja", "--reasoning", "off",
                "--host", "127.0.0.1", "--port", str(PORT)] + extra
        lf = open(os.path.join(OUT, "fit-%s.log" % ctx), "a", encoding="utf-8",
                  errors="replace")
        p = gpu_lock.serve(args, stdout=lf, stderr=subprocess.STDOUT)
        if not wait(p):
            print("%-20s SERVER FAILED TO LOAD" % label)
            rows.append({"label": label, "ctx": ctx, "loaded": False})
            try:
                p.kill()
            except Exception:
                pass
            lf.close()
            continue
        peak = smi()
        tps = []
        try:
            post({"model": "qat", "temperature": 0, "top_k": 1,
                  "max_tokens": NPREDICT, "cache_prompt": True,
                  "messages": [{"role": "user", "content": PROMPT}]})   # warmup
            after = smi()
            peak = max(peak, after)
            for _ in range(3):
                r = post({"model": "qat", "temperature": 0, "top_k": 1,
                          "max_tokens": NPREDICT, "cache_prompt": True,
                          "messages": [{"role": "user", "content": PROMPT}]})
                tps.append(r.get("timings", {}).get("predicted_per_second", 0))
                peak = max(peak, smi())
        finally:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    p.kill()
            lf.close()
            for _ in range(25):
                time.sleep(1)
                if smi() < base + 800:
                    break
        alloc = peak - base
        m = sum(tps) / len(tps) if tps else 0
        rows.append({"label": label, "ctx": ctx, "loaded": True,
                     "peak_mib": peak, "alloc_mib": round(alloc),
                     "tps_3090": round(m, 2),
                     "tps_3060_derived": round(m * BW_3060 / BW_3090, 1),
                     "probes": [round(x, 2) for x in tps]})
        print("%-20s alloc %6.0f MiB   %6.2f t/s (3090)   ~%.0f t/s (3060, DERIVED)"
              % (label, alloc, m, m * BW_3060 / BW_3090))

    print("\n=== WHAT FITS ON AN RTX 3060 ===")
    print("A 12 GB 3060 has %d MiB. Windows desktop on this rig reserves about"
          % CARD_3060_MIB)
    print("1,796 MiB; a headless or iGPU-driven machine reserves far less.\n")
    print("%-20s %10s %14s %14s"
          % ("config", "needs", "12GB + desktop", "12GB headless"))
    for r in rows:
        if not r.get("loaded"):
            print("%-20s %10s %14s %14s" % (r["label"], "FAILED", "-", "-"))
            continue
        a = r["alloc_mib"]
        print("%-20s %7d MiB %14s %14s"
              % (r["label"], a,
                 "YES" if a + 1796 <= CARD_3060_MIB else "no",
                 "YES" if a + 200 <= CARD_3060_MIB else "no"))
    print("\n8 GB card: NO, at any context. The weights alone are %.0f MiB,"
          % WEIGHTS_MIB)
    print("which exceeds %d MiB before a single KV byte is allocated."
          % CARD_3060_8G_MIB)
    print("\nSpeed for the 3060 is DERIVED by memory bandwidth (360 vs 936 GB/s,")
    print("ratio %.3f) and is an estimate, not a measurement. Prefill is"
          % (BW_3060 / BW_3090))
    print("compute-bound and does NOT scale this way - a 3060 will feel slower")
    print("on long prompts than this ratio suggests.")

    json.dump({"date": time.strftime("%Y-%m-%d %H:%M"),
               "baseline_mib": base, "weights_mib": round(WEIGHTS_MIB),
               "bandwidth": {"rtx3090": BW_3090, "rtx3060": BW_3060},
               "npredict": NPREDICT, "rows": rows},
              open(os.path.join(OUT, "qat-3060-fit.json"), "w", encoding="utf-8"),
              indent=1)
    print("\n-> %s" % os.path.join(OUT, "qat-3060-fit.json"))


if __name__ == "__main__":
    main()
