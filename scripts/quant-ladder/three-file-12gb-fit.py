"""What actually fits on a 12 GB card: UD-Q2_K_XL vs QAT-Q2_0 vs UD-IQ2_S.

    python three-file-12gb-fit.py

WHY. A reader with an RTX 3060 asked how the QAT file compares. The quality
answer is measured and settled - it lands on UD-IQ2_S, not on UD-Q2_K_XL - but
that is not what decides anything for somebody choosing a file to fit in 12 GB.
What decides it is how many MiB each one needs at a usable window, and whether
the drafter survives.

The published 12 GB block measures UD-Q2_K_XL at 11,396 MiB at -c 32768 with
the drafter OFF, leaving 892 MiB against a 12,288 MiB card, and says plainly
that if the card also draws your desktop then no window works - because Windows
holds 1,179-1,669 MiB of it. The two smaller files are 1,020 and 1,390 MiB
lighter in weights, which is larger than that entire margin. So the question is
not academic: they may move the verdict from "you need a second card for your
display" to "this works on the one card you own".

WHY THIS IS MEASURED AND NOT SUBTRACTED. The arithmetic is easy and this
campaign has already been burned by it: a documented VRAM prediction here came
in ~1,213 MiB under what the card actually allocated, and the same mistake was
repeated in this very session. The margin under test is 892 MiB. An error of
that documented size is larger than the answer. Weights are not the only term -
compute buffers and the KV allocation move with the model's own shapes - so the
only honest way to fill this table is to load all three and read the meter.

WHAT TRANSFERS AND WHAT DOES NOT. Allocation is a fact about the configuration:
llama.cpp reserves the same weights, KV and compute buffers on any CUDA card,
so a 3060 owner can subtract their own desktop reserve from 12,288 MiB. SPEED
does not transfer - it is measured here on a 3090 and any 3060 figure is
DERIVED by memory bandwidth (360 against 936 GB/s) and labelled so, and prefill
will be worse than that ratio suggests because prefill is compute-bound.
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

UNSLOTH = os.environ.get("MODEL_DIR", r"C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF")
FILES = [
    ("UD-Q2_K_XL", os.path.join(UNSLOTH, "Qwen3.8-27B-UD-Q2_K_XL.gguf"), 2.912),
    ("QAT-Q2_0", r"C:\Users\chink\.lmstudio\models\sdkyuan\qwen3.8-27B-qat-q2_0-gguf\qwen38-27b-qat-q2_0.gguf", 2.595),
    ("UD-IQ2_S", os.path.join(UNSLOTH, "Qwen3.8-27B-UD-IQ2_S.gguf"), 2.481),
]

# the published 12 GB block's configuration, and the two questions around it
CONFIGS = [
    ("c32768 drafter off", 32768, ["--spec-type", "none"]),
    ("c32768 drafter on", 32768, ["--spec-type", "draft-mtp",
                                  "--spec-draft-n-max", "4",
                                  "--spec-draft-p-min", "0.75"]),
    ("c65536 drafter off", 65536, ["--spec-type", "none"]),
]

PORT = 1255
BASE = "http://127.0.0.1:%d" % PORT
OUT = os.path.join(ROOT, "results", "qwen38-27b-blind", "data", "quant-ladder",
                   "12gb-fit")
CARD = 12288
DESKTOP_LIGHT, DESKTOP_HEAVY = 1179, 1669     # measured on this rig
BW_3090, BW_3060 = 936.0, 360.0
NPREDICT = 300
PROMPT = ("Write a single self-contained Python function that merges two sorted "
          "lists into one sorted list without using sort(). Docstring plus three "
          "example calls. Code only.")


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
    print("host: %s" % refarm.quiet_report()["status"])
    base = smi()
    print("idle VRAM baseline on this rig: %.0f MiB" % base)
    print("card under test: %d MiB; desktop measured at %d-%d MiB\n"
          % (CARD, DESKTOP_LIGHT, DESKTOP_HEAVY))

    rows = []
    for label, ctx, extra in CONFIGS:
        print("=== %s ===" % label)
        for name, path, bpw in FILES:
            if not os.path.exists(path):
                print("  %-12s MISSING" % name)
                continue
            args = [refarm.SERVER, "-m", path, "--alias", "m", "-ngl", "99",
                    "-c", str(ctx), "--parallel", "1", "-fa", "on",
                    "--load-mode", "none", "-ctk", "q8_0", "-ctv", "q8_0",
                    "--jinja", "--reasoning", "off",
                    "--host", "127.0.0.1", "--port", str(PORT)] + extra
            lf = open(os.path.join(OUT, "%s-%s.log" % (name, ctx)), "a",
                      encoding="utf-8", errors="replace")
            p = subprocess.Popen(args, stdout=lf, stderr=subprocess.STDOUT)
            loaded = wait(p)
            peak = smi() if loaded else None
            tps = []
            try:
                if loaded:
                    post({"model": "m", "temperature": 0, "top_k": 1,
                          "max_tokens": NPREDICT, "cache_prompt": True,
                          "messages": [{"role": "user", "content": PROMPT}]})
                    peak = max(peak, smi())
                    for _ in range(3):
                        r = post({"model": "m", "temperature": 0, "top_k": 1,
                                  "max_tokens": NPREDICT, "cache_prompt": True,
                                  "messages": [{"role": "user", "content": PROMPT}]})
                        tps.append(r.get("timings", {}).get("predicted_per_second", 0))
                        peak = max(peak, smi())
            except Exception as e:
                print("  %-12s probe failed: %s" % (name, e))
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
            if not loaded:
                print("  %-12s FAILED TO LOAD" % name)
                rows.append({"config": label, "file": name, "loaded": False})
                continue
            alloc = round(peak - base)
            m = sum(tps) / len(tps) if tps else 0
            rows.append({"config": label, "file": name, "bpw": bpw, "loaded": True,
                         "alloc_mib": alloc, "free_on_12gb": CARD - alloc,
                         "tps_3090": round(m, 2),
                         "tps_3060_derived": round(m * BW_3060 / BW_3090, 1),
                         "probes": [round(x, 2) for x in tps]})
            print("  %-12s %6d MiB   %5d MiB free of 12288   %6.2f t/s (3090)"
                  % (name, alloc, CARD - alloc, m))
        print()

    print("=== VERDICT FOR A 12 GB CARD ===")
    print("%-20s %-12s %8s %8s %14s %12s"
          % ("config", "file", "needs", "free", "iGPU display", "own display"))
    for r in rows:
        if not r.get("loaded"):
            print("%-20s %-12s %8s" % (r["config"], r["file"], "FAILED"))
            continue
        free = r["free_on_12gb"]
        print("%-20s %-12s %7d %8d %14s %12s"
              % (r["config"], r["file"], r["alloc_mib"], free,
                 "YES" if free >= 300 else "no",
                 "YES" if free >= DESKTOP_HEAVY else
                 ("tight" if free >= DESKTOP_LIGHT else "no")))
    print("\n'own display' = the card also draws Windows, which measured")
    print("%d-%d MiB on this rig. 'tight' means a light desktop fits and a"
          % (DESKTOP_LIGHT, DESKTOP_HEAVY))
    print("browser full of tabs does not - it will spill to system RAM and")
    print("the speed collapses.")
    print("\nSpeed on a 3060 is DERIVED by bandwidth (%.3f) and is an estimate."
          % (BW_3060 / BW_3090))

    json.dump({"date": time.strftime("%Y-%m-%d %H:%M"), "baseline_mib": base,
               "card_mib": CARD, "desktop_mib": [DESKTOP_LIGHT, DESKTOP_HEAVY],
               "bandwidth": {"rtx3090": BW_3090, "rtx3060": BW_3060},
               "rows": rows},
              open(os.path.join(OUT, "three-file-12gb-fit.json"), "w",
                   encoding="utf-8"), indent=1)
    print("\n-> %s" % os.path.join(OUT, "three-file-12gb-fit.json"))


main()
