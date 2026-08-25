"""Is `--spec-draft-n-max 4` the right card recommendation for a speed-seeker?

    python drafter-vs-window.py

THE QUESTION, as a reader put it: the vision recipe ships the conservative
drafter (n-max 4 / p-min 0.75). Someone who wants maximum speed and would
accept a smaller context window - is n4 still the right advice for them?

WHY THE ANSWER IS NOT OBVIOUS FROM THE PAGE. The card already carries a fast
pick, but it reaches it by DROPPING VISION rather than by shrinking the window:
pick 2 is text-only at -c 180224 with n10/p0.5, a LARGER window than pick 1's
122,880, because the projector's 1,138 MiB is more than the 898 MiB the wider
drafter costs. So the page never answers the case the reader is actually in -
keep vision, keep the drafter wide, and pay for it in window.

THE ARMS. All with the vision projector loaded, which is the whole point:

  A  n4/p0.75  @ -c 122880   the shipped pick 1, the baseline
  B  n10/p0.5  @ -c 122880   same window, wider drafter - does it even FIT?
  C  n10/p0.5  @ -c 98304    the reader's trade: buy the drafter with window

If B fits with a usable desktop margin, then there is no trade to make and the
card should simply offer the wider drafter on this pick - C is unnecessary and
the recommendation is wrong. If B does not fit, C measures what the window has
to shrink to, and whether the speed gained is worth the context lost.

WHAT IS MEASURED. Board VRAM at load (the projector and drafter are both VRAM
costs, and the desktop's own share is inside this figure), and decode on a
novel-code prompt - the content where speculation pays best and therefore where
the wider drafter has its strongest case. rule 12: one warmup probe discarded,
three settled probes averaged.

THIS IS A SHALLOW-WINDOW MEASUREMENT. VRAM is read at load, which is what
decides whether a configuration fits at all; the campaign's own law says a
window must be deep-filled before its speed is trusted, so the decode figures
here rank the drafter settings against each other and are not depth figures.
"""

import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

SERVER = os.environ.get("LLAMA_SERVER", r"E:\AI\llama.cpp\llama-server.exe")
LMS = r"C:\Users\chink\.lmstudio\models"
MODEL = os.path.join(LMS, r"unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-IQ4_XS.gguf")
MMPROJ = os.path.join(LMS, r"lmstudio-community\Qwen3.8-27B-GGUF\mmproj-Qwen3.8-27B-BF16.gguf")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "..", "results", "qwen38-27b-blind", "data", "register")
PORT = 1239
BASE = "http://127.0.0.1:%d" % PORT

PROMPT = "\n".join([
    "Write a single self-contained JavaScript module that implements a fixed-window",
    "rate limiter with a pluggable clock, a per-key limit, and an eviction sweep that",
    "runs at most once per window. Include JSDoc on every exported symbol and a short",
    "usage example at the end. Do not explain the code outside the module.",
])

NPREDICT, SETTLED = 700, 3
ARMS = [
    ("A shipped   n4/p0.75  @122880", 4, 0.75, 122880),
    ("B wide      n10/p0.5  @122880", 10, 0.5, 122880),
    ("C wide+trim n10/p0.5  @98304", 10, 0.5, 98304),
]
DESKTOP_RESERVE = 1796      # this page's own reserve, MiB
BOARD = 24576


def post(payload, timeout=1800):
    req = urllib.request.Request(BASE + "/v1/chat/completions",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def vram():
    try:
        o = subprocess.run(["nvidia-smi", "--query-gpu=memory.used",
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=15).stdout
        return int(o.strip().splitlines()[0])
    except Exception:
        return None


def start(nmax, pmin, ctx, logpath):
    args = [SERVER, "-m", MODEL, "--alias", "qwen/qwen3.8-27b",
            "-ngl", "99", "-c", str(ctx), "--parallel", "1",
            "-ctk", "q8_0", "-ctv", "q8_0",
            "--mmproj", MMPROJ, "--image-min-tokens", "1024",
            "--image-max-tokens", "10580",
            "--spec-type", "draft-mtp",
            "--spec-draft-n-max", str(nmax), "--spec-draft-p-min", str(pmin),
            "--jinja", "--reasoning", "off",
            "--host", "127.0.0.1", "--port", str(PORT)]
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


def stop(p, lf):
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
    time.sleep(4)


def probe():
    r = post({"model": "qwen/qwen3.8-27b", "temperature": 0, "top_k": 1,
              "max_tokens": NPREDICT,
              "messages": [{"role": "user", "content": PROMPT}]})
    t = r.get("timings", {})
    dn, da = t.get("draft_n"), t.get("draft_n_accepted")
    return {"decode_tps": round(t.get("predicted_per_second", 0), 2),
            "acceptance": round(da / dn, 3) if dn else None,
            "predicted_n": t.get("predicted_n")}


def main():
    for path, what in ((SERVER, "llama-server"), (MODEL, "model"), (MMPROJ, "mmproj")):
        if not os.path.exists(path):
            sys.exit("missing %s: %s" % (what, path))
    os.makedirs(OUT, exist_ok=True)
    logdir = os.path.join(OUT, "drafter-window-logs")
    os.makedirs(logdir, exist_ok=True)

    rows = []
    for label, nmax, pmin, ctx in ARMS:
        print("\n=== %s  (vision loaded) ===" % label)
        lp = os.path.join(logdir, "n%d-c%d.log" % (nmax, ctx))
        base = vram()
        p, lf = start(nmax, pmin, ctx, lp)
        if not wait(p):
            print("  SERVER FAILED TO START - this configuration does not fit")
            tail = ""
            try:
                tail = io.open(lp, encoding="utf-8", errors="replace").read()[-300:]
            except OSError:
                pass
            print("   %s" % tail.replace("\n", " | ")[-260:])
            stop(p, lf)
            rows.append({"arm": label, "nmax": nmax, "pmin": pmin, "ctx": ctx,
                         "failed": True})
            continue
        loaded = vram()
        try:
            w = probe()
            print("  VRAM at load: %s MiB   slack %s MiB   warmup %.2f t/s (discarded)"
                  % (loaded, (BOARD - loaded) if loaded else "?", w["decode_tps"]))
            time.sleep(5)
            got = []
            for i in range(SETTLED):
                if i:
                    time.sleep(3)
                r = probe()
                got.append(r)
                print("  probe %d: %6.2f t/s   acceptance %s" % (i + 1, r["decode_tps"], r["acceptance"]))
        finally:
            stop(p, lf)
        tps = [r["decode_tps"] for r in got]
        acc = [r["acceptance"] for r in got if r["acceptance"] is not None]
        mean = sum(tps) / len(tps)
        rows.append({"arm": label, "nmax": nmax, "pmin": pmin, "ctx": ctx,
                     "vram_mib": loaded, "slack_mib": (BOARD - loaded) if loaded else None,
                     "desktop_ok": (BOARD - loaded) >= DESKTOP_RESERVE if loaded else None,
                     "mean_tps": round(mean, 2),
                     "spread_pct": round((max(tps) - min(tps)) / mean * 100, 1),
                     "acceptance": round(sum(acc) / len(acc), 3) if acc else None,
                     "probes": got})

    print("\n%-30s %-9s %-10s %-11s %-9s %s"
          % ("arm", "VRAM MiB", "slack", "desktop ok?", "decode", "acceptance"))
    for r in rows:
        if r.get("failed"):
            print("%-30s %s" % (r["arm"], "*** DID NOT FIT ***"))
            continue
        print("%-30s %-9s %-10s %-11s %-9s %s"
              % (r["arm"], r["vram_mib"], r["slack_mib"],
                 "yes" if r["desktop_ok"] else "NO (<%d)" % DESKTOP_RESERVE,
                 r["mean_tps"], r["acceptance"]))

    ok = [r for r in rows if not r.get("failed")]
    base = next((r for r in ok if r["nmax"] == 4), None)
    if base:
        print("\n---- what the wider drafter buys, against the shipped pick ----")
        for r in ok:
            if r is base:
                continue
            d = (r["mean_tps"] - base["mean_tps"]) / base["mean_tps"] * 100
            dc = r["ctx"] - base["ctx"]
            print("  %-30s %+6.1f%% speed   %+7d tokens of window   slack %s MiB"
                  % (r["arm"], d, dc, r["slack_mib"]))

    out = os.path.join(OUT, "drafter-vs-window.json")
    json.dump({"date": time.strftime("%Y-%m-%d %H:%M"), "board_mib": BOARD,
               "desktop_reserve_mib": DESKTOP_RESERVE, "prompt": PROMPT,
               "vision": True, "arms": rows}, open(out, "w", encoding="utf-8"), indent=1)
    print("\n-> %s" % out)


main()
