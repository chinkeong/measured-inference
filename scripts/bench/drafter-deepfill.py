"""Does the wide drafter still fit once the window is actually FULL?

    python drafter-deepfill.py

WHY THIS RUN EXISTS. A shallow measurement said the wide drafter (n-max 10 /
p-min 0.5) is +33% faster than the shipped n4/p0.75 at the same 122,880 window,
with 2,023 MiB of board VRAM still free. On that evidence the card's
recommendation looks wrong.

But VRAM AT LOAD IS NOT VRAM AT DEPTH, and this page has already published that
mistake once and corrected it: 196,608 shipped with "~3 GiB of slack" read at
load, and filled properly it leaves 415 MiB. A ~2.6 GiB collapse. Arm B's
2,023 MiB of load-time slack is inside the range that collapse would erase, so
the shallow result cannot license a recommendation on its own.

This fills both configurations to about 90% of their window with real tokens and
reads board VRAM there - rule 13b, the deep-fill probe. The question is narrow
and falsifiable:

    does n10/p0.5 with the vision projector still clear this page's
    desktop reserve at 122,880 tokens of REAL depth?

RESERVE CORRECTED AFTER THIS RUN. It executed against 1,308 MiB and reported
arm B clearing with 1,776. An audit then showed the reserve was built on a
desktop maximum of 1,181 MiB that was not the maximum - a direct no-server
reading measures 1,669 - so the threshold is now 1,796. Against that, arm B's
1,776 FAILS BY 20 MiB. The run's verdict did not survive its own threshold
moving, which is worth knowing before reading its printed output.

If yes, the card should offer the wide drafter on this pick and the reader was
right to push. If no, the card is correct, and the reason it is correct is
depth - which is a better reason than the one currently printed, and one the
page can then state in code terms rather than reasoning terms.

Decode at depth is recorded too, because the +33% was measured on an empty
window and speculation's value moves with depth.
"""

import io
import json
import os
import subprocess
import sys
import time
import urllib.request
import gpu_lock

SERVER = os.environ.get("LLAMA_SERVER", r"E:\AI\llama.cpp\llama-server.exe")
LMS = r"C:\Users\chink\.lmstudio\models"
MODEL = os.path.join(LMS, r"unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-IQ4_XS.gguf")
MMPROJ = os.path.join(LMS, r"lmstudio-community\Qwen3.8-27B-GGUF\mmproj-Qwen3.8-27B-BF16.gguf")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "..", "results", "qwen38-27b-blind", "data", "register")
PORT = 1240
BASE = "http://127.0.0.1:%d" % PORT

CTX = 122880
TARGET_FILL = int(CTX * 0.90)          # rule 13b: ~90% of the window, real tokens
BOARD, RESERVE = 24576, 1796
NPREDICT, SETTLED = 400, 2

ARMS = [("A shipped  n4/p0.75", 4, 0.75), ("B wide     n10/p0.5", 10, 0.5)]

TASK = ("TASK: Write a single self-contained JavaScript module implementing a "
        "fixed-window rate limiter with a pluggable clock and a per-key limit. "
        "Code only, no explanation.")


def filler(lines):
    out = ["Reference notes for the task below. Read them, then do the task at the end."]
    for i in range(1, lines + 1):
        frag = format((i * 48271) % 1048573, "x")
        out.append(
            "Note %d: subsystem alpha-%d reported latency %d ms on shard %d, retry "
            "budget %d, digest fragment %s, remark: threshold crossed only when the "
            "moving median over window %d exceeded baseline by %d percent."
            % (i, (i * 7) % 97, (17 * i) % 993, i % 13, (3 * i) % 29, frag,
               (5 * i) % 47, (11 * i) % 83))
    out.append(TASK)
    return "\n".join(out)


def post(payload, timeout=3600):
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


def start(nmax, pmin, logpath):
    args = [SERVER, "-m", MODEL, "--alias", "qwen/qwen3.8-27b",
            "-ngl", "99", "-c", str(CTX), "--parallel", "1",
            "-ctk", "q8_0", "-ctv", "q8_0",
            "--mmproj", MMPROJ, "--image-min-tokens", "1024",
            "--image-max-tokens", "10580",
            "--spec-type", "draft-mtp",
            "--spec-draft-n-max", str(nmax), "--spec-draft-p-min", str(pmin),
            "--jinja", "--reasoning", "off",
            "--host", "127.0.0.1", "--port", str(PORT)]
    lf = open(logpath, "w", encoding="utf-8", errors="replace")
    return gpu_lock.serve(args, stdout=lf, stderr=subprocess.STDOUT), lf


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


def probe(prompt):
    r = post({"model": "qwen/qwen3.8-27b", "temperature": 0, "top_k": 1,
              "max_tokens": NPREDICT,
              "messages": [{"role": "user", "content": prompt}]})
    t = r.get("timings", {})
    dn, da = t.get("draft_n"), t.get("draft_n_accepted")
    return {"decode_tps": round(t.get("predicted_per_second", 0), 2),
            "prompt_n": t.get("prompt_n"),
            "prefill_s": round(t.get("prompt_ms", 0) / 1000, 1),
            "acceptance": round(da / dn, 3) if dn else None}


def main():
    for path, what in ((SERVER, "llama-server"), (MODEL, "model"), (MMPROJ, "mmproj")):
        if not os.path.exists(path):
            sys.exit("missing %s: %s" % (what, path))
    logdir = os.path.join(OUT, "drafter-window-logs")
    os.makedirs(logdir, exist_ok=True)

    # ~58.7 tokens per filler line, measured on this filler shape
    prompt = filler(int(TARGET_FILL / 58.7))
    print("target fill ~%d tokens of a %d window (%.0f%%)"
          % (TARGET_FILL, CTX, 100.0 * TARGET_FILL / CTX))

    rows = []
    for label, nmax, pmin in ARMS:
        print("\n=== %s | vision loaded | -c %d ===" % (label, CTX))
        lp = os.path.join(logdir, "deepfill-n%d.log" % nmax)
        p, lf = start(nmax, pmin, lp)
        if not wait(p):
            print("  SERVER FAILED TO START")
            stop(p, lf)
            rows.append({"arm": label, "failed": True})
            continue
        at_load = vram()
        print("  VRAM at load : %s MiB  (slack %s)" % (at_load, BOARD - at_load))
        try:
            w = probe(prompt)          # this one does the deep fill; rule 12 discards it
            at_depth = vram()
            print("  filled %s tokens in %ss -> VRAM at DEPTH: %s MiB  (slack %s)"
                  % (w["prompt_n"], w["prefill_s"], at_depth, BOARD - at_depth))
            got = []
            for i in range(SETTLED):
                time.sleep(3)
                r = probe(prompt)
                got.append(r)
                print("  probe %d: %6.2f t/s at depth   acceptance %s"
                      % (i + 1, r["decode_tps"], r["acceptance"]))
            peak = vram()
        finally:
            stop(p, lf)
        tps = [r["decode_tps"] for r in got]
        mean = sum(tps) / len(tps) if tps else 0
        slack = BOARD - max(at_depth or 0, peak or 0)
        rows.append({"arm": label, "nmax": nmax, "ctx": CTX,
                     "vram_load": at_load, "vram_depth": at_depth, "vram_peak": peak,
                     "slack_depth": slack, "clears_reserve": slack >= RESERVE,
                     "filled_tokens": w["prompt_n"], "prefill_s": w["prefill_s"],
                     "mean_tps_at_depth": round(mean, 2),
                     "acceptance": got[0]["acceptance"] if got else None,
                     "probes": got})

    print("\n%-22s %-10s %-11s %-11s %-13s %s"
          % ("arm", "load MiB", "depth MiB", "slack", "clears 1308?", "decode at depth"))
    for r in rows:
        if r.get("failed"):
            print("%-22s %s" % (r["arm"], "*** FAILED ***")); continue
        print("%-22s %-10s %-11s %-11s %-13s %s"
              % (r["arm"], r["vram_load"], r["vram_depth"], r["slack_depth"],
                 "YES" if r["clears_reserve"] else "NO", r["mean_tps_at_depth"]))

    ok = [r for r in rows if not r.get("failed")]
    if len(ok) == 2:
        a, b = ok
        d = (b["mean_tps_at_depth"] - a["mean_tps_at_depth"]) / a["mean_tps_at_depth"] * 100
        print("\n---- the verdict at real depth ----")
        print("  wide drafter is %+.1f%% at depth (shallow said +33.2%%)" % d)
        print("  slack collapse from load to depth: %s MiB (A), %s MiB (B)"
              % (a["vram_depth"] - a["vram_load"], b["vram_depth"] - b["vram_load"]))
        print("  wide drafter clears the 1,308 MiB desktop reserve at depth: %s"
              % ("YES - the card should offer it" if b["clears_reserve"]
                 else "NO - the card is right, and depth is the reason"))

    os.makedirs(OUT, exist_ok=True)
    out = os.path.join(OUT, "drafter-deepfill.json")
    json.dump({"date": time.strftime("%Y-%m-%d %H:%M"), "ctx": CTX,
               "target_fill": TARGET_FILL, "board_mib": BOARD,
               "desktop_reserve_mib": RESERVE, "vision": True, "arms": rows},
              open(out, "w", encoding="utf-8"), indent=1)
    print("\n-> %s" % out)


main()
