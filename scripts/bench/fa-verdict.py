"""Should the recipes set -fa? Measure it, at the recipe they ship.

    python fa-verdict.py [--ctx 32768] [--tag NAME]

THE QUESTION. None of the eight published recipes passes `-fa`, and neither does
serve-qwen.bat. This build documents `-fa, --flash-attn [on|off|auto]` with
**default 'auto'** - so the recipes are not running with Flash Attention off,
they are running with it UNDECIDED. Meanwhile several of the campaign's own
measurement scripts pass `-fa on` explicitly. If auto does not resolve to on,
every published speed figure was measured under a flag the recipes do not set,
and a reader following the recipe would not reproduce the page.

THREE ARMS, one flag:
    auto   -fa not passed at all - exactly what every recipe does today
    on     -fa on            - what the measurement scripts pass
    off    -fa off           - the floor, and the thing to check for a trap

WHY 'off' IS MEASURED EVEN THOUGH NOBODY WANTS IT. Every recipe also ships
`-ctk q8_0 -ctv q8_0`. Quantised KV historically REQUIRED Flash Attention in
llama.cpp, and there is a widely repeated claim that a quantised cache without
FA is slower because it is dequantised on every attention op. If that is true
here, the recipes have a hidden dependency: the KV setting they ship only works
because of a flag they never set. A recipe that silently degrades is worse than
one that errors, so 'off' is measured to find out which this is.

TWO DEPTHS, because Flash Attention is about attention memory traffic and its
benefit grows with the length of what is being attended over. A shallow probe
alone would understate it, and shallow is not how anyone uses a 27B model with a
131k window.

WHAT IS RECORDED PER ARM. Decode t/s (warmup discarded per rule 12, three
settled probes), prefill t/s, draft acceptance, board VRAM at load, and - the
single most valuable line if it exists - whatever the SERVER ITSELF prints about
its resolved flash-attention state. `auto` is only a mystery until the server
says what it chose.
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
MODEL = os.environ.get(
    "QWEN_MODEL",
    r"C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-IQ4_XS.gguf")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "..", "results", "qwen38-27b-blind", "data", "register")
LOGDIR = os.path.join(OUT, "fa-logs")
PORT = 1238
BASE = "http://127.0.0.1:%d" % PORT

SHORT = "\n".join([
    "Write a single self-contained JavaScript module that implements a fixed-window",
    "rate limiter with a pluggable clock, a per-key limit, and an eviction sweep that",
    "runs at most once per window. Include JSDoc on every exported symbol and a short",
    "usage example at the end. Do not explain the code outside the module.",
])


def deep_prompt(lines):
    """Filler in the same shape the campaign's other depth probes use."""
    out = ["Reference notes for the task below. Read them, then do the task at the end."]
    for i in range(1, lines + 1):
        frag = format((i * 48271) % 1048573, "x")
        out.append(
            "Note %d: subsystem alpha-%d reported latency %d ms on shard %d, retry "
            "budget %d, digest fragment %s, remark: threshold crossed only when the "
            "moving median over window %d exceeded baseline by %d percent."
            % (i, (i * 7) % 97, (17 * i) % 993, i % 13, (3 * i) % 29, frag,
               (5 * i) % 47, (11 * i) % 83))
    out.append("TASK: " + SHORT)
    return "\n".join(out)


NPREDICT, SETTLED = 700, 3
ARMS = [("auto", None), ("on", "on"), ("off", "off")]


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


def start(fa, ctx, logpath):
    # The SHIPPED recipe's flags, plus the drafter setting the published pair
    # used. -fa is the only thing that varies.
    args = [SERVER, "-m", MODEL, "--alias", "qwen/qwen3.8-27b",
            "-ngl", "99", "-c", str(ctx), "--parallel", "1",
            "-ctk", "q8_0", "-ctv", "q8_0",
            "--spec-type", "draft-mtp", "--spec-draft-n-max", "10",
            "--spec-draft-p-min", "0.5",
            "--jinja", "--reasoning", "off",
            "--host", "127.0.0.1", "--port", str(PORT)]
    if fa:
        args += ["-fa", fa]
    lf = open(logpath, "w", encoding="utf-8", errors="replace")
    p = gpu_lock.serve(args, stdout=lf, stderr=subprocess.STDOUT)
    return p, lf


def wait(proc, timeout=900):
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


def fa_from_log(path):
    """The server's own word on what it resolved. Worth more than any inference."""
    hits = []
    try:
        for line in open(path, encoding="utf-8", errors="replace"):
            if re.search(r"flash[_ ]?attn|flash attention", line, re.I):
                hits.append(line.strip()[:160])
    except OSError:
        pass
    return hits


def probe(prompt):
    r = post({"model": "qwen/qwen3.8-27b", "temperature": 0, "top_k": 1,
              "max_tokens": NPREDICT,
              "messages": [{"role": "user", "content": prompt}]})
    t = r.get("timings", {})
    dn, da = t.get("draft_n"), t.get("draft_n_accepted")
    return {"decode_tps": round(t.get("predicted_per_second", 0), 2),
            "prefill_tps": round(t.get("prompt_per_second", 0), 1),
            "prompt_n": t.get("prompt_n"), "predicted_n": t.get("predicted_n"),
            "acceptance": round(da / dn, 3) if dn else None}


def run(tag, fa, ctx, prompt, depth_label):
    os.makedirs(LOGDIR, exist_ok=True)
    logpath = os.path.join(LOGDIR, "fa-%s-%s.log" % (fa or "auto", depth_label))
    print("\n=== -fa %-5s | %s | -c %d ===" % (fa or "AUTO (not passed)", depth_label, ctx))
    base = vram()
    p, lf = start(fa, ctx, logpath)
    if not wait(p):
        print("  SERVER FAILED TO START")
        for l in fa_from_log(logpath)[:3]:
            print("   log: %s" % l)
        try:
            tail = open(logpath, encoding="utf-8", errors="replace").read()[-400:]
            print("   tail: %s" % tail.replace("\n", " | ")[-300:])
        except OSError:
            pass
        stop(p, lf)
        return {"fa": fa or "auto", "depth": depth_label, "failed": True,
                "fa_log_lines": fa_from_log(logpath)}
    loaded = vram()
    try:
        w = probe(prompt)
        print("  warmup (discarded): %.2f t/s   prompt_n %s" % (w["decode_tps"], w["prompt_n"]))
        time.sleep(5)
        rows = []
        for i in range(SETTLED):
            if i:
                time.sleep(3)
            r = probe(prompt)
            rows.append(r)
            print("  probe %d: decode %6.2f t/s   prefill %8s t/s   acceptance %s"
                  % (i + 1, r["decode_tps"], r["prefill_tps"], r["acceptance"]))
    finally:
        stop(p, lf)
    hits = fa_from_log(logpath)
    for l in hits[:3]:
        print("  server says: %s" % l)
    tps = [r["decode_tps"] for r in rows]
    mean = sum(tps) / len(tps)
    acc = [r["acceptance"] for r in rows if r["acceptance"] is not None]
    return {"fa": fa or "auto", "depth": depth_label, "ctx": ctx,
            "mean_tps": round(mean, 2),
            "spread_pct": round((max(tps) - min(tps)) / mean * 100, 1),
            "prefill_tps": rows[0]["prefill_tps"], "prompt_n": rows[0]["prompt_n"],
            "acceptance": round(sum(acc) / len(acc), 3) if acc else None,
            "vram_mib": (loaded - base) if (loaded and base) else loaded,
            "vram_total_mib": loaded, "fa_log_lines": hits, "probes": rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ctx", type=int, default=32768)
    ap.add_argument("--deep-lines", type=int, default=380)
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    if not os.path.exists(SERVER):
        sys.exit("no llama-server at %s" % SERVER)
    if not os.path.exists(MODEL):
        sys.exit("no model at %s" % MODEL)

    deep = deep_prompt(a.deep_lines)
    results = []
    for label, fa in ARMS:
        results.append(run(a.tag, fa, a.ctx, SHORT, "shallow"))
    for label, fa in ARMS:
        results.append(run(a.tag, fa, a.ctx, deep, "deep"))

    print("\n%-6s %-9s %-10s %-9s %-11s %-11s %s"
          % ("-fa", "depth", "decode", "spread", "prefill", "acceptance", "VRAM MiB"))
    for r in results:
        if r.get("failed"):
            print("%-6s %-9s %s" % (r["fa"], r["depth"], "*** SERVER FAILED TO START ***"))
            continue
        print("%-6s %-9s %-10s %-9s %-11s %-11s %s"
              % (r["fa"], r["depth"], r["mean_tps"], "%.1f%%" % r["spread_pct"],
                 r["prefill_tps"], r["acceptance"], r["vram_total_mib"]))

    print("\n---- does 'auto' behave like 'on'? ----")
    for depth in ("shallow", "deep"):
        g = {r["fa"]: r for r in results if r["depth"] == depth and not r.get("failed")}
        if "auto" in g and "on" in g:
            d = (g["auto"]["mean_tps"] - g["on"]["mean_tps"]) / g["on"]["mean_tps"] * 100
            print("  %-8s auto %6.2f vs on %6.2f  ->  %+.1f%%" % (depth, g["auto"]["mean_tps"], g["on"]["mean_tps"], d))
        if "off" in g and "on" in g:
            d = (g["off"]["mean_tps"] - g["on"]["mean_tps"]) / g["on"]["mean_tps"] * 100
            print("  %-8s off  %6.2f vs on %6.2f  ->  %+.1f%%" % (depth, g["off"]["mean_tps"], g["on"]["mean_tps"], d))

    os.makedirs(OUT, exist_ok=True)
    out = os.path.join(OUT, "fa-verdict%s.json" % (a.tag or ""))
    json.dump({"date": time.strftime("%Y-%m-%d %H:%M"), "model": os.path.basename(MODEL),
               "ctx": a.ctx, "npredict": NPREDICT, "settled": SETTLED,
               "flags": "-ngl 99 --parallel 1 -ctk q8_0 -ctv q8_0 --spec-type draft-mtp "
                        "--spec-draft-n-max 10 --spec-draft-p-min 0.5 --jinja --reasoning off",
               "arms": results}, open(out, "w", encoding="utf-8"), indent=1)
    print("\n-> %s" % out)


if __name__ == "__main__":
    main()
