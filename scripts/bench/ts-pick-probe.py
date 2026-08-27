#!/usr/bin/env python3
"""Is there a FASTER pick than [2], and does [2]'s own recipe survive its window?

    ts-pick-probe.py --model <path.gguf> [--probes 3]

THE READER'S QUESTION, verbatim: "We don't have THE T/S PICK? We can shrinking
the -c and add more speed for people looking for speed?"

The intuition is that a smaller context window decodes faster. Our own data
says it does not, and says so from an angle that is easy to miss - so the first
job of this probe is to test the thing the data cannot answer rather than the
thing it already did.

WHAT THE CAMPAIGN ALREADY MEASURED. The eight-row MTP grid (campaign.md, Phase
3) crosses BOTH drafter variables and brackets the winner on both sides:

    --spec-type none          42.61 t/s
    n-max 3,  p-min 0         81.97
    n-max 4,  p-min 0.75      80.99      acceptance 89.9%  <- the shipped safe pair
    n-max 6,  p-min 0.5       80.18
    n-max 10, p-min 0         87.31
    n-max 10, p-min 0.5       87.39      acceptance 59.2%  <- the peak
    n-max 10, p-min 0.75      80.32
    n-max 16, p-min 0.5       80.32      falls back: the peak is bracketed

EVERY ROW ABOVE WAS MEASURED AT -c 32768. That is the fact that answers the
reader. The fastest configuration this campaign has ever recorded was recorded
at a SMALL window, and pick [2] already ships those exact flags - so a
small-window pick would ship the same flags for the same speed. Shrinking -c
does not buy throughput; it forecloses DEPTH, and depth is the thing that
actually costs (86.3 t/s at 1.5k, 80.2 at 28k, 64.8 at 91k, answer tokens).
A small window is a guard rail against the depth curve, not an accelerator.

CORRECTION THIS PROBE EXISTS TO RECORD. Earlier today I told the user that
p-min was "the untested variable", reasoning from two rows quoted in
serve-qwen.bat's header rather than from the grid above. It is not untested. At
n-max 10 the grid holds p-min 0 (87.31), 0.5 (87.39) and 0.75 (80.32); 0.5 is
already the peak and pick [2] already ships it. There is about 8% of spread in
the whole grid and the shipped pick sits at the top of it.

SO WHAT IS ACTUALLY LEFT. Three things, and only one of them is about -c:

  A  -c 32768   q8_0 KV   n10/p0.5   the grid's own conditions - the baseline,
                                     and a re-measurement of a 2026-08-22
                                     number on today's build
  B  -c 32768   f16  KV   n10/p0.5   THE UNTESTED SPEED VARIABLE. Every pick
                                     here quantises the KV cache to q8_0, which
                                     halves cache bandwidth and adds a dequant
                                     on every attention read. Which of those
                                     wins has never been measured on this rig,
                                     and at a 32k window the f16 cache is
                                     affordable for the first time. If f16 is
                                     faster, THAT is the t/s pick, and it is a
                                     quality improvement as well as a speed one.
  C  -c 180224  q8_0 KV   n10/p0.5   PICK [2] EXACTLY AS SHIPPED, at the same
                                     fill depth as A. The entire drafter
                                     recommendation was derived at 32k and is
                                     shipped at 180k, and nobody has checked
                                     that allocation is free. Theory says the
                                     attention kernel is passed the USED cache
                                     length, not the allocated one, so A and C
                                     should tie. If they do not tie, pick [2]'s
                                     published 93.9 t/s does not describe pick
                                     [2] and the card is wrong.
  D  -c 32768   q8_0 KV   n10/p0.5 + ngram-mod
                                     --spec-type takes a COMMA-SEPARATED LIST,
                                     so the draft head and the n-gram matcher
                                     can run together. Measured separately here
                                     (MTP 1.90-2.05x, ngram-mod 1.10-1.48x) and
                                     never together.

WHAT WOULD MAKE A NEW PICK. B or D beating A by more than the arms' own
scatter. A and C differing at all is a defect report against the published
card, not a new pick.

CONDITIONS. Same model, same prompt, same predicted-token budget, so every arm
sits at the same fill depth and the -c comparison is about allocation alone.
Fresh server per arm. rule 12: one warmup probe discarded, three settled probes
averaged. rule 27: refuses to run on a busy machine - host load alone moves
decode 5.4% on this rig, which is most of the effect being looked for. Board
VRAM is sampled after load and after the probes, because an arm that wins on
speed and does not leave the 1,796 MiB desktop reserve cannot ship.
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")
OUT = os.path.join(ROOT, "results", "qwen38-27b-blind", "data", "followup")
SERVER = r"E:\AI\llama.cpp\llama-server.exe"
PORT = 1293

# The desktop's own share of the board with no server loaded, measured directly
# 2026-08-25 (1,669 MiB observed + 127 load-to-load variation). An arm that
# leaves less than this cannot hold a graphical session.
DESKTOP_RESERVE_MIB = 1796

COMMON = ["--alias", "qwen", "--host", "127.0.0.1", "-ngl", "99",
          "--parallel", "1", "-fa", "on", "--jinja", "--reasoning", "off",
          "--metrics"]

# n10/p0.5 on every arm: the grid's peak, held fixed so the arms differ only in
# the one variable each is named for.
SPEC_PEAK = ["--spec-type", "draft-mtp",
             "--spec-draft-n-max", "10", "--spec-draft-p-min", "0.5"]

ARMS = [
    {"id": "A-32k-q8", "ctx": "32768", "kv": "q8_0", "spec": SPEC_PEAK,
     "what": "grid conditions, the baseline"},
    {"id": "B-32k-f16", "ctx": "32768", "kv": "f16", "spec": SPEC_PEAK,
     "what": "unquantised KV cache - the untested speed variable"},
    {"id": "C-180k-q8", "ctx": "180224", "kv": "q8_0", "spec": SPEC_PEAK,
     "what": "pick [2] as shipped, same fill depth as A"},
    {"id": "D-32k-ngram", "ctx": "32768", "kv": "q8_0",
     "spec": ["--spec-type", "draft-mtp,ngram-mod",
              "--spec-draft-n-max", "10", "--spec-draft-p-min", "0.5"],
     "what": "draft head AND n-gram matcher together"},
    # Added 2026-08-27 from a stranger's llama-server log on r/LocalLLM. They
    # run this same file, window and KV width on a 16 GB mobile 4090 and set NO
    # --spec-draft-p-min, so it takes llama.cpp's default of 0.00. At n-max 4
    # that reported acceptance ~73% with MEAN DRAFT LENGTH 3.93, against this
    # rig's 85.9% and 2.71 at the same n-max with p-min 0.75. Rule 11 on this
    # page says mean draft length - not acceptance - is what predicts
    # throughput, and 3.93 against 2.71 is 45% longer drafts. So the shipped
    # recipe may be leaving speed on the table at its OWN n-max, and the
    # eight-row grid never tested this cell: it holds n3/p0 and n10/p0 but no
    # n4/p0.
    {"id": "E-32k-n4-p0", "ctx": "32768", "kv": "q8_0",
     "spec": ["--spec-type", "draft-mtp",
              "--spec-draft-n-max", "4", "--spec-draft-p-min", "0.0"],
     "what": "the shipped n-max with llama.cpp's DEFAULT p-min, never tested here"},
]

# Novel code: the content where speculation pays best, so a drafter change has
# its strongest case here. The same prompt on every arm, which is what makes
# the fill depth equal and the -c comparison honest.
PROMPT = ("Write a single self-contained JavaScript module that implements a "
          "fixed-window rate limiter with a pluggable clock, a per-key limit, "
          "and an eviction sweep that runs at most once per window. Include "
          "JSDoc on every exported symbol.")


def vram_used_mib():
    try:
        o = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total",
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10).stdout
        used, total = [int(x) for x in o.strip().splitlines()[0].split(",")]
        return used, total
    except Exception:
        return None, None


def wait_ready(proc, timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/health" % PORT,
                                        timeout=4) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(2)
    return False


def probe(max_tokens=400):
    body = json.dumps({
        "model": "qwen",
        "messages": [{"role": "user", "content": PROMPT}],
        # Greedy. A sampler adds 5.68% run-to-run variation against greedy's
        # 0.77%, which is wider than the effect being measured.
        "temperature": 0.0, "top_k": 1, "max_tokens": max_tokens,
    }).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:%d/v1/chat/completions" % PORT, data=body,
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=900) as r:
        d = json.loads(r.read().decode("utf-8"))
    wall = time.time() - t0
    tim = d.get("timings") or {}
    return {"decode_tps": tim.get("predicted_per_second"),
            "prompt_tps": tim.get("prompt_per_second"),
            "predicted_n": tim.get("predicted_n"),
            "prompt_n": tim.get("prompt_n"),
            "wall_s": round(wall, 2)}


def spec_counters():
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/metrics" % PORT,
                                    timeout=6) as r:
            body = r.read().decode("utf-8", "replace")
    except Exception:
        return {}
    out, pos = {}, {}
    for ln in body.splitlines():
        if ln.startswith("#") or not ln.strip():
            continue
        m = re.match(r"llamacpp:spec_decode_num_accepted_tokens_per_pos_total"
                     r'\{position="(\d+)"\}\s+([0-9.]+)', ln)
        if m:
            pos[int(m.group(1))] = float(m.group(2))
            continue
        m = re.match(r"llamacpp:(spec_decode_\w+)\s+([0-9.]+)", ln)
        if m:
            out[m.group(1)] = float(m.group(2))
    out["per_pos"] = pos
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--probes", type=int, default=3)
    ap.add_argument("--only", nargs="*", help="arm ids to run (default all)")
    a = ap.parse_args()

    if not os.path.exists(a.model):
        sys.exit("model not found: %s" % a.model)
    os.makedirs(OUT, exist_ok=True)

    # rule 27. This probe looks for a few percent and host load alone moves
    # decode by 5.4%, so a busy machine measures the other work.
    try:
        busy = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu",
                               "--format=csv,noheader,nounits"],
                              capture_output=True, text=True, timeout=10).stdout
        if int(busy.strip().splitlines()[0]) > 20:
            sys.exit("GPU is %s%% busy - this probe needs a quiet machine "
                     "(host load alone moves decode 5.4%%)" % busy.strip())
    except ValueError:
        pass

    arms = [x for x in ARMS if not a.only or x["id"] in a.only]
    rows = []
    for arm in arms:
        print("\n=== %s : %s ===" % (arm["id"], arm["what"]), flush=True)
        print("    -c %s  KV %s  %s" % (arm["ctx"], arm["kv"],
                                        " ".join(arm["spec"])), flush=True)
        log = os.path.join(OUT, "tspick-%s-server.log" % arm["id"])
        lf = io.open(log, "w", encoding="utf-8", errors="replace")
        p = subprocess.Popen(
            [SERVER, "-m", a.model] + COMMON +
            ["-c", arm["ctx"], "-ctk", arm["kv"], "-ctv", arm["kv"],
             "--port", str(PORT)] + arm["spec"],
            stdout=lf, stderr=subprocess.STDOUT)
        try:
            if not wait_ready(p):
                # An arm that will not load is a RESULT, not a gap: f16 KV at a
                # large window is expected to fail this way, and the failure is
                # the finding. Recorded with its server log so the reason is
                # recoverable.
                print("  server never became ready - recorded as a failure",
                      flush=True)
                rows.append({"arm": arm["id"], "ctx": int(arm["ctx"]),
                             "kv": arm["kv"], "spec": " ".join(arm["spec"]),
                             "FAILED": "server not ready", "log": log})
                continue
            used, total = vram_used_mib()
            probe(120)                       # warmup, discarded (rule 12)
            time.sleep(2)
            got = []
            for i in range(a.probes):
                r = probe()
                got.append(r)
                print("  probe %d: %6.2f t/s decode  %7.1f t/s prefill  "
                      "%4s tok  %.1fs"
                      % (i + 1, r["decode_tps"] or 0, r["prompt_tps"] or 0,
                         r["predicted_n"], r["wall_s"]), flush=True)
                time.sleep(2)
            peak_used, _ = vram_used_mib()
            sc = spec_counters()
            tps = [g["decode_tps"] for g in got if g["decode_tps"]]
            mean = sum(tps) / len(tps) if tps else None
            # Spread across the settled probes, so a reader can separate an arm
            # difference from this arm's own scatter without being told.
            spread = (max(tps) - min(tps)) / mean * 100 if tps and mean else None
            drafts = sc.get("spec_decode_num_drafts_total") or 0
            acc = sc.get("spec_decode_num_accepted_tokens_total") or 0
            dr = sc.get("spec_decode_num_draft_tokens_total") or 0
            slack = (total - peak_used) if (total and peak_used) else None
            rows.append({
                "arm": arm["id"], "what": arm["what"], "ctx": int(arm["ctx"]),
                "kv": arm["kv"], "spec": " ".join(arm["spec"]),
                "mean_tps": round(mean, 2) if mean else None,
                "spread_pct": round(spread, 2) if spread is not None else None,
                "probes": got,
                "vram_after_load_mib": used, "vram_after_probes_mib": peak_used,
                "board_total_mib": total, "slack_mib": slack,
                "clears_desktop_reserve":
                    (slack >= DESKTOP_RESERVE_MIB) if slack is not None else None,
                "accept_rate": round(acc / dr, 4) if dr else None,
                "mean_accepted_len": round(acc / drafts, 3) if drafts else None,
                "per_pos_rate": {k: round(v / drafts, 4)
                                 for k, v in sorted(sc.get("per_pos", {}).items())}
                if drafts else {},
                "log": log,
            })
            warn = ("" if slack is None or slack >= DESKTOP_RESERVE_MIB
                    else "  <- UNDER the %d MiB reserve" % DESKTOP_RESERVE_MIB)
            print("  mean %.2f t/s (spread %.2f%%) | accept %s | slack %s MiB%s"
                  % (mean or 0, spread or 0,
                     ("%.1f%%" % (100 * acc / dr)) if dr else "n/a",
                     slack, warn), flush=True)
        finally:
            p.terminate()
            try:
                p.wait(timeout=60)
            except Exception:
                p.kill()
            lf.close()
            time.sleep(5)

    path = os.path.join(OUT, "ts-pick-probe.json")
    with io.open(path, "w", encoding="utf-8") as f:
        json.dump({"model": a.model, "probes_per_arm": a.probes,
                   "prompt": PROMPT,
                   "desktop_reserve_mib": DESKTOP_RESERVE_MIB,
                   "conditions": ("greedy, temp 0 / top_k 1, 400 predicted "
                                  "tokens, -ngl 99, --parallel 1, -fa on, "
                                  "reasoning off, fresh server per arm, one "
                                  "warmup discarded, quiet machine (rule 27)"),
                   "arms": rows}, f, indent=2)
    print("\nwrote %s" % path)

    ok = [r for r in rows if r.get("mean_tps")]
    base = next((r for r in ok if r["arm"] == "A-32k-q8"), None)
    if ok:
        print("\n  %-14s %9s %8s %9s %8s" % ("arm", "t/s", "spread", "slack",
                                             "vs A"))
        for r in ok:
            rel = ("%+.1f%%" % (100 * (r["mean_tps"] - base["mean_tps"])
                                / base["mean_tps"])) if base else "-"
            print("  %-14s %9.2f %7.2f%% %8s %8s"
                  % (r["arm"], r["mean_tps"], r["spread_pct"] or 0,
                     r["slack_mib"], rel))
    c = next((r for r in ok if r["arm"] == "C-180k-q8"), None)
    if base and c:
        d = 100 * (c["mean_tps"] - base["mean_tps"]) / base["mean_tps"]
        scatter = max(base["spread_pct"] or 0, c["spread_pct"] or 0)
        # The claim under test, stated so the output cannot be read as agreeing
        # with it when it does not.
        print("\n  ALLOCATION: -c 180224 reads %+.1f%% against -c 32768 at the "
              "same fill depth," % d)
        print("  against %.2f%% of within-arm scatter. %s"
              % (scatter,
                 "Allocation is free, and pick [2] keeps its published number."
                 if abs(d) <= scatter else
                 "LARGER than either arm's own scatter - the card's 93.9 t/s "
                 "was derived at 32k and does not describe pick [2] at 180k. "
                 "Fix the card."))
