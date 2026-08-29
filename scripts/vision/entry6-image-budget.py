"""Negative-register entry 6: what does --image-max-tokens 1024 cost in what the
model can SEE, and does it see anything at all?

    python entry6-image-budget.py [--server PATH] [--model PATH] [--mmproj PATH]

WRITTEN IN PYTHON, DELIBERATELY. The rest of this campaign's orchestration is
PowerShell and does not run on Linux. New instruments go in Python so the
harness survives the move to Ubuntu; the only platform-specific things here are
default paths, and every one of them is overridable by flag or environment.

THE THREE ARMS, and why the third is the one that makes the other two mean
anything:

  FULL     --image-max-tokens 10580   the shipped recipe's budget
  REDUCED  --image-max-tokens 1024    the flag the recipes currently omit
  BLIND    no image attached at all   the control

Without BLIND this is not a perception measurement. A model asked "what is the
unit serial" can emit a plausible serial from priors alone, and a lucky hit is
indistinguishable from reading. Every answer in the target is deliberately
unguessable - random three-digit latencies, a random hex serial - so BLIND
should score at or near zero. If BLIND scores well on a question, that question
is measuring the model's prior, not its eyes, and it is thrown out.

THE POSITIVE CONTROL IS INSIDE THE IMAGE. Two questions ask about type rendered
at 96 px and 54 px, which survives any plausible downsampling; five ask about
type at 12-15 px, which should not survive a 3.6x cut. So:

  coarse holds, fine collapses  -> a RESOLUTION result. The flag costs sight.
  both hold                     -> the cut is cheaper than feared, and the
                                   recipes should stop omitting the flag.
  both collapse                 -> a PLUMBING result, not a resolution one.
                                   Something about the low budget breaks the
                                   image path entirely, and that is a different
                                   finding that must not be reported as acuity.

Scoring is string equality after light normalisation, because the target was
generated and every answer is known exactly. No judge, no noise floor, no cost.
"""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "..", "bench"))
import gpu_lock

HERE = os.path.dirname(os.path.abspath(__file__))
PNG = os.path.join(HERE, "detail-target.png")
TRUTH = os.path.join(HERE, "detail-target.json")
OUTDIR = os.path.join(HERE, "..", "..", "results", "qwen38-27b-blind", "data", "register")

D_SERVER = os.environ.get("LLAMA_SERVER", r"E:\AI\llama.cpp\llama-server.exe")
D_MODEL = os.environ.get(
    "QWEN_MODEL",
    r"C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-IQ4_XS.gguf")
D_MMPROJ = os.environ.get(
    "QWEN_MMPROJ",
    r"C:\Users\chink\.lmstudio\models\lmstudio-community\Qwen3.8-27B-GGUF\mmproj-Qwen3.8-27B-BF16.gguf")
PORT = 1236
BASE = "http://127.0.0.1:%d" % PORT


def post(path, payload, timeout=900):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def wait_ready(proc, timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(BASE + "/health", timeout=2) as r:
                if json.loads(r.read().decode("utf-8")).get("status") == "ok":
                    return True
        except Exception:
            pass
        time.sleep(2)
    return False


def start(server, model, mmproj, max_image_tokens):
    args = [server, "-m", model, "--alias", "qwen/qwen3.8-27b",
            "-c", "32768", "-ngl", "99", "--parallel", "1",
            "--load-mode", "none", "-ctk", "q8_0", "-ctv", "q8_0",
            "--mmproj", mmproj,
            "--image-min-tokens", "64",
            "--image-max-tokens", str(max_image_tokens),
            "--jinja", "--host", "127.0.0.1", "--port", str(PORT)]
    p = gpu_lock.serve(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return p


def stop(p):
    if p and p.poll() is None:
        p.terminate()
        try:
            p.wait(timeout=30)
        except subprocess.TimeoutExpired:
            p.kill()
    time.sleep(3)


def norm(s):
    """Light normalisation only - never enough to make two different values equal."""
    s = (s or "").strip().split("\n")[-1] if "\n" in (s or "") else (s or "")
    s = s.strip().strip(".").strip()
    s = re.sub(r"^(the\s+|answer[:\s]+|it\s+is\s+)", "", s, flags=re.I).strip()
    s = s.strip('"').strip("'").strip("*").strip()
    s = re.sub(r"\s*(ms|milliseconds)$", "", s, flags=re.I).strip()
    s = s.replace(",", "")
    return s.upper()


def ask(q, b64):
    """One question.

    THE CAP AND THE EFFORT ARE BOTH LOAD-BEARING, and the first version of this
    script got them wrong in the way this campaign has already documented once.
    Qwen3.8 emits reasoning tokens before its answer. With a 64-token cap the
    reasoning consumed the whole budget and `content` came back EMPTY for 20 of
    21 questions - which reads exactly like a perception failure and is nothing
    of the kind. That is self-correction #1 of this campaign repeated verbatim:
    "a 700-token cap never reaches the answer at the default effort."

    So: effort forced to `low`, a cap of 800, and the reasoning length recorded
    on every row. An empty answer beside a large `think_n` is a harness failure
    and must never be scored as a wrong answer.
    """
    content = [{"type": "text", "text": q}]
    if b64:
        content.insert(0, {"type": "image_url",
                           "image_url": {"url": "data:image/png;base64," + b64}})
    r = post("/v1/chat/completions", {
        "model": "qwen/qwen3.8-27b", "temperature": 0, "top_k": 1,
        "max_tokens": 800,
        "chat_template_kwargs": {"reasoning_effort": "low"},
        "messages": [{"role": "user", "content": content}]})
    msg = r["choices"][0]["message"]
    think = msg.get("reasoning_content") or ""
    fin = r["choices"][0].get("finish_reason")
    t = r.get("timings", {})
    return (msg.get("content") or ""), {
        "prompt_n": t.get("prompt_n"), "predicted_n": t.get("predicted_n"),
        "think_chars": len(think), "finish": fin}


def run_arm(name, questions, b64, server, model, mmproj, budget):
    print("\n=== %s ===" % name)
    p = start(server, model, mmproj, budget)
    if not wait_ready(p):
        print("  SERVER FAILED"); stop(p); return None
    out = []
    for q in questions:
        try:
            raw, meta = ask(q["q"], b64)
        except Exception as e:
            raw, meta = "", {"error": str(e)}
        blank = not raw.strip()
        ok = (not blank) and norm(raw) == norm(q["a"])
        out.append({"id": q["id"], "class": q["class"], "expected": q["a"],
                    "raw": raw.strip()[:160], "correct": ok, "blank": blank,
                    **meta})
        print("  %-16s %-8s expect %-16s got %-24s %s"
              % (q["id"], q["class"], q["a"],
                 (raw.strip().replace("\n", " ")[:24] or "<BLANK>"),
                 "OK" if ok else ("HARNESS?" if blank else "x")))
    stop(p)
    return out


def summarise(rows):
    if not rows:
        return {}
    d = {}
    for cls in ("coarse", "fine"):
        sub = [r for r in rows if r["class"] == cls]
        d[cls] = {"correct": sum(1 for r in sub if r["correct"]), "n": len(sub),
                  "blank": sum(1 for r in sub if r.get("blank"))}
    d["all"] = {"correct": sum(1 for r in rows if r["correct"]), "n": len(rows),
                "blank": sum(1 for r in rows if r.get("blank"))}
    # image tokens actually spent, which is the thing the flag controls
    pn = [r["prompt_n"] for r in rows if r.get("prompt_n")]
    d["prompt_n_median"] = sorted(pn)[len(pn) // 2] if pn else None
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default=D_SERVER)
    ap.add_argument("--model", default=D_MODEL)
    ap.add_argument("--mmproj", default=D_MMPROJ)
    a = ap.parse_args()

    for path, what in ((a.server, "llama-server"), (a.model, "model"),
                       (a.mmproj, "mmproj"), (PNG, "target image"),
                       (TRUTH, "ground truth")):
        if not os.path.exists(path):
            sys.exit("missing %s: %s" % (what, path))

    truth = json.load(open(TRUTH, encoding="utf-8"))
    qs = truth["questions"]
    b64 = base64.b64encode(open(PNG, "rb").read()).decode("ascii")
    print("target %dx%d, %.0f KB, %d questions (%d coarse / %d fine)"
          % (truth["size"][0], truth["size"][1], len(b64) * 0.75 / 1024, len(qs),
             sum(1 for q in qs if q["class"] == "coarse"),
             sum(1 for q in qs if q["class"] == "fine")))

    arms = {}
    arms["FULL 10580"] = run_arm("FULL  --image-max-tokens 10580", qs, b64,
                                 a.server, a.model, a.mmproj, 10580)
    arms["REDUCED 1024"] = run_arm("REDUCED  --image-max-tokens 1024", qs, b64,
                                   a.server, a.model, a.mmproj, 1024)
    arms["BLIND"] = run_arm("BLIND  no image attached (control)", qs, None,
                            a.server, a.model, a.mmproj, 10580)

    print("\n%-14s %-10s %-10s %-10s %-8s %s"
          % ("arm", "coarse", "fine", "all", "blank", "prompt_n"))
    result = {"entry": "6", "date": time.strftime("%Y-%m-%d %H:%M"),
              "target": os.path.basename(PNG), "arms": {}}
    for k, rows in arms.items():
        s = summarise(rows)
        result["arms"][k] = {"rows": rows, "summary": s}
        if s:
            print("%-14s %-10s %-10s %-10s %-8s %s"
                  % (k, "%d/%d" % (s["coarse"]["correct"], s["coarse"]["n"]),
                     "%d/%d" % (s["fine"]["correct"], s["fine"]["n"]),
                     "%d/%d" % (s["all"]["correct"], s["all"]["n"]),
                     s["all"]["blank"], s["prompt_n_median"]))
    if any(v["summary"].get("all", {}).get("blank") for v in result["arms"].values()):
        print("\nWARNING: blank answers present. A blank is a HARNESS result, not a "
              "perception result, and must not be scored as a wrong answer.")

    os.makedirs(OUTDIR, exist_ok=True)
    out = os.path.join(OUTDIR, "entry6-image-budget.json")
    json.dump(result, open(out, "w", encoding="utf-8"), indent=1)
    print("\n-> %s" % out)


if __name__ == "__main__":
    main()
