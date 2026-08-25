"""The last gate: does the wide drafter still fit with an IMAGE in flight at depth?

    python drafter-vision-peak.py

WHY THIS RUN EXISTS. A deep fill showed n10/p0.5 with the vision projector holds
122,880 tokens at 22,800 MiB, leaving 1,776 MiB - clear of this page's
1,308 MiB desktop reserve by 468 MiB. On that evidence the card should ship the
wider drafter on its default pick.

But that fill was TEXT. The pick being changed is the VISION recipe, and the
reader's stated workload is text-and-image agentic coding. An image is encoded
by the CLIP tower and prefilled; if that costs transient VRAM, 468 MiB is a
margin it could plausibly erase, and the failure mode would be a silent spill
into system memory rather than an error - the worst kind, and one this page
already documents.

So this sends a real 1440p screenshot at 112k of depth and watches board VRAM
across the whole request rather than only before and after. If the peak still
clears the reserve, the recommendation is safe for the workload it is actually
being recommended for. If it does not, the card keeps the conservative drafter
on the vision pick and the wide one belongs only on the text-only picks - which
is what it already does.

Sampled every 0.5 s during the request, because a transient peak between two
end-point reads is exactly what a load-and-depth pair cannot see.
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

SERVER = os.environ.get("LLAMA_SERVER", r"E:\AI\llama.cpp\llama-server.exe")
LMS = r"C:\Users\chink\.lmstudio\models"
MODEL = os.path.join(LMS, r"unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-IQ4_XS.gguf")
MMPROJ = os.path.join(LMS, r"lmstudio-community\Qwen3.8-27B-GGUF\mmproj-Qwen3.8-27B-BF16.gguf")
IMG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "vision", "detail-target.png")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "..", "results", "qwen38-27b-blind", "data", "register")
PORT = 1241
BASE = "http://127.0.0.1:%d" % PORT
CTX, BOARD, RESERVE = 122880, 24576, 1308
FILL_TOKENS = 100000          # leave room for the image's ~10.5k on top
TAG = ""


def filler(lines):
    out = ["Reference notes. Read them, then answer the question at the end."]
    for i in range(1, lines + 1):
        frag = format((i * 48271) % 1048573, "x")
        out.append("Note %d: subsystem alpha-%d reported latency %d ms on shard %d, "
                   "retry budget %d, digest fragment %s, remark: threshold crossed only "
                   "when the moving median over window %d exceeded baseline by %d percent."
                   % (i, (i * 7) % 97, (17 * i) % 993, i % 13, (3 * i) % 29, frag,
                      (5 * i) % 47, (11 * i) % 83))
    return "\n".join(out)


def vram():
    try:
        o = subprocess.run(["nvidia-smi", "--query-gpu=memory.used",
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10).stdout
        return int(o.strip().splitlines()[0])
    except Exception:
        return None


class Sampler(threading.Thread):
    """A load-and-depth pair cannot see a transient peak between its two reads."""
    def __init__(self):
        super().__init__(daemon=True)
        self.samples, self.stop = [], False

    def run(self):
        while not self.stop:
            v = vram()
            if v:
                self.samples.append(v)
            time.sleep(0.5)


def main():
    global CTX, FILL_TOKENS, TAG
    DRAFT_KV = ""
    MODEL_PATH = MODEL
    SPEC = "n10p05"
    ap = argparse.ArgumentParser()
    ap.add_argument("--ctx", type=int, default=CTX)
    ap.add_argument("--tag", default="")
    ap.add_argument("--ctkd", default="", help="quantise the DRAFT cache too")
    ap.add_argument("--model", default=MODEL, help="which GGUF to serve")
    ap.add_argument("--spec", default="n10p05",
                    choices=["n10p05", "n4p075", "none"],
                    help="drafter setting, or none")
    ap.add_argument("--fill-frac", type=float, default=0.85)
    o = ap.parse_args()
    CTX, TAG = o.ctx, o.tag
    DRAFT_KV = o.ctkd
    MODEL_PATH = o.model
    SPEC = o.spec
    # fill to ~85% of whatever window is under test, leaving room for the image
    FILL_TOKENS = int(CTX * o.fill_frac) - 11000
    for p, w in ((SERVER, "llama-server"), (MODEL_PATH, "model"), (MMPROJ, "mmproj"), (IMG, "image")):
        if not os.path.exists(p):
            sys.exit("missing %s: %s" % (w, p))

    args = [SERVER, "-m", MODEL_PATH, "--alias", "qwen/qwen3.8-27b",
            "-ngl", "99", "-c", str(CTX), "--parallel", "1",
            "-ctk", "q8_0", "-ctv", "q8_0",
            "--mmproj", MMPROJ, "--image-min-tokens", "1024", "--image-max-tokens", "10580",
            "--jinja", "--reasoning", "off", "--host", "127.0.0.1", "--port", str(PORT)]
    if SPEC == "n10p05":
        args += ["--spec-type", "draft-mtp", "--spec-draft-n-max", "10", "--spec-draft-p-min", "0.5"]
    elif SPEC == "n4p075":
        args += ["--spec-type", "draft-mtp", "--spec-draft-n-max", "4", "--spec-draft-p-min", "0.75"]
    else:
        args += ["--spec-type", "none"]
    print("  model %s | drafter %s" % (os.path.basename(MODEL_PATH), SPEC))
    if DRAFT_KV:
        # -ctk/-ctv apply to the TARGET context only; the draft context has its
        # own pair and defaults to f16. No recipe on the page sets these.
        args += ["-ctkd", DRAFT_KV, "-ctvd", DRAFT_KV]
        print("  draft cache quantised to %s (-ctkd/-ctvd)" % DRAFT_KV)
    logdir = os.path.join(OUT, "drafter-window-logs")
    os.makedirs(logdir, exist_ok=True)
    lf = open(os.path.join(logdir, "vision-peak%s.log" % (TAG or "")), "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(args, stdout=lf, stderr=subprocess.STDOUT)

    t0 = time.time()
    up = False
    while time.time() - t0 < 900:
        if proc.poll() is not None:
            break
        try:
            with urllib.request.urlopen(BASE + "/health", timeout=2) as r:
                if json.loads(r.read().decode()).get("status") == "ok":
                    up = True
                    break
        except Exception:
            pass
        time.sleep(2)
    if not up:
        print("SERVER FAILED"); proc.kill(); lf.close(); sys.exit(1)

    at_load = vram()
    print("vision + n10/p0.5 @ -c %d" % CTX)
    print("  VRAM at load: %d MiB   slack %d" % (at_load, BOARD - at_load))

    b64 = base64.b64encode(open(IMG, "rb").read()).decode("ascii")
    text = filler(int(FILL_TOKENS / 58.7)) + (
        "\n\nQUESTION: using the screenshot above, what is the LATENCY value for the "
        "row labelled SHARD-07? Reply with the number of milliseconds only.")
    payload = {"model": "qwen/qwen3.8-27b", "temperature": 0, "top_k": 1,
               "max_tokens": 200,
               "messages": [{"role": "user", "content": [
                   {"type": "image_url",
                    "image_url": {"url": "data:image/png;base64," + b64}},
                   {"type": "text", "text": text}]}]}

    s = Sampler(); s.start()
    print("  sending a 1440p image on top of ~%d tokens of fill..." % FILL_TOKENS)
    req = urllib.request.Request(BASE + "/v1/chat/completions",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    t1 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=3600) as r:
            resp = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        s.stop = True; proc.kill(); lf.close(); sys.exit("request failed: %s" % e)
    wall = time.time() - t1
    s.stop = True; s.join(timeout=3)

    tm = resp.get("timings", {})
    ans = (resp["choices"][0]["message"].get("content") or "").strip()
    peak = max(s.samples) if s.samples else at_load
    slack = BOARD - peak
    print("  prompt_n %s (image + fill)   %.0fs wall   decode %.2f t/s"
          % (tm.get("prompt_n"), wall, tm.get("predicted_per_second", 0)))
    print("  answer: %r   (ground truth 207)" % ans[:40])
    print("  VRAM samples: %d   PEAK %d MiB   slack at peak %d MiB"
          % (len(s.samples), peak, slack))
    print("  clears the %d MiB desktop reserve at peak: %s"
          % (RESERVE, "YES" if slack >= RESERVE else "NO"))

    proc.terminate()
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
    lf.close()

    os.makedirs(OUT, exist_ok=True)
    json.dump({"date": time.strftime("%Y-%m-%d %H:%M"), "ctx": CTX, "board": BOARD,
               "model": os.path.basename(MODEL_PATH), "spec": SPEC,
               "reserve": RESERVE, "vram_load": at_load, "vram_peak": peak,
               "slack_at_peak": slack, "clears": slack >= RESERVE,
               "prompt_n": tm.get("prompt_n"), "decode_tps": tm.get("predicted_per_second"),
               "answer": ans[:80], "truth": "207", "samples": len(s.samples)},
              open(os.path.join(OUT, "drafter-vision-peak%s.json" % (TAG or "")), "w", encoding="utf-8"), indent=1)


main()
