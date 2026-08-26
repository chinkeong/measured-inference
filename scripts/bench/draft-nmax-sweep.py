#!/usr/bin/env python3
"""Is speculation limited by the draft head, or by the flag that caps it?

    draft-nmax-sweep.py --model <path.gguf> [--nmax 4 6 8] [--probes 3]

WHY THIS PROBE EXISTS. The shipped recipe sets --spec-draft-n-max 4 and the
measured mean accepted length is 3.55 - 89% of the cap. That alone does not say
whether raising the cap would help: a draft head that has run out of confidence
would sit just under the cap too.

The per-position acceptance counters settle it. Measured over a full agentic
arm (1,082 requests, 237,809 drafts) on UD-Q2_K_XL:

    position 0   229,547 accepted   96.5% of drafts
    position 1   188,364            79.2%
    position 2   160,556            67.5%
    position 3   140,374            59.0%   <- the LAST position the cap allows

Acceptance at the final permitted position is still 59%. The drafter is not
exhausted when it is cut off - the flag cuts it off. So the cap is binding and
raising it should buy throughput, up to the point where the marginal cost of
each extra speculated token overtakes the weight pass it shares.

This measures where that point is, rather than modelling it. A two-point cost
model fitted earlier predicted about +24% at length 6; a model through two
points is not a measurement and this probe exists to replace it.

CONDITIONS. Everything except --spec-draft-n-max is the shipped recipe, and the
sweep is run on a QUIET machine with no benchmark in flight - decode throughput
on this rig moves 5.4% under host load while the GPU clock RISES, so a sweep
run alongside other work measures the other work.
"""
import argparse, io, json, os, re, subprocess, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")
OUT = os.path.join(ROOT, "results", "qwen38-27b-blind", "data", "followup")
SERVER = r"E:\AI\llama.cpp\llama-server.exe"
PORT = 1291

BASE_FLAGS = ["--alias", "qwen", "--host", "127.0.0.1", "-ngl", "99",
              "-c", "32768", "--parallel", "1", "-fa", "on",
              "-ctk", "q8_0", "-ctv", "q8_0", "--jinja",
              "--reasoning", "off", "--spec-type", "draft-mtp",
              "--spec-draft-p-min", "0.75", "--metrics"]

PROMPT = ("Write a complete, self-contained Python implementation of a "
          "priority queue backed by a binary heap. Include push, pop, peek, "
          "and a heapify classmethod, with docstrings and type hints. Then "
          "write a short main() that demonstrates each operation.")


def wait_ready(proc, timeout=420):
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
        # Greedy. A sampler would add 5.68% run-to-run variation against
        # greedy's 0.77%, which is wider than the effect being measured.
        "temperature": 0.0, "top_k": 1, "max_tokens": max_tokens,
    }).encode()
    req = urllib.request.Request("http://127.0.0.1:%d/v1/chat/completions" % PORT,
                                 data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.loads(r.read().decode("utf-8"))
    wall = time.time() - t0
    tim = d.get("timings") or {}
    return {"decode_tps": tim.get("predicted_per_second"),
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
    ap.add_argument("--nmax", type=int, nargs="+", default=[4, 6, 8])
    ap.add_argument("--probes", type=int, default=3)
    a = ap.parse_args()

    if not os.path.exists(a.model):
        sys.exit("model not found: %s" % a.model)
    os.makedirs(OUT, exist_ok=True)

    # Refuse to run against a busy machine: this probe measures a few percent
    # and host load moves decode by more than that.
    try:
        busy = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu",
                               "--format=csv,noheader,nounits"],
                              capture_output=True, text=True, timeout=10).stdout
        if int(busy.strip().splitlines()[0]) > 20:
            sys.exit("GPU is %s%% busy - this probe needs a quiet machine "
                     "(host load alone moves decode 5.4%%)" % busy.strip())
    except ValueError:
        pass

    rows = []
    for nmax in a.nmax:
        print("\n=== --spec-draft-n-max %d ===" % nmax, flush=True)
        log = os.path.join(OUT, "nmax-%d-server.log" % nmax)
        lf = io.open(log, "w", encoding="utf-8", errors="replace")
        p = subprocess.Popen(
            [SERVER, "-m", a.model] + BASE_FLAGS +
            ["--port", str(PORT), "--spec-draft-n-max", str(nmax)],
            stdout=lf, stderr=subprocess.STDOUT)
        try:
            if not wait_ready(p):
                print("  server never became ready - skipping", flush=True)
                rows.append({"nmax": nmax, "FAILED": "server not ready"})
                continue
            probe(120)                      # warmup, discarded (rule 12)
            time.sleep(2)
            got = []
            for i in range(a.probes):
                r = probe()
                got.append(r)
                print("  probe %d: %6.2f t/s  %4s tok  %.1fs"
                      % (i + 1, r["decode_tps"] or 0, r["predicted_n"],
                         r["wall_s"]), flush=True)
                time.sleep(2)
            sc = spec_counters()
            tps = [g["decode_tps"] for g in got if g["decode_tps"]]
            mean = sum(tps) / len(tps) if tps else None
            drafts = sc.get("spec_decode_num_drafts_total") or 0
            acc = sc.get("spec_decode_num_accepted_tokens_total") or 0
            dr = sc.get("spec_decode_num_draft_tokens_total") or 0
            row = {"nmax": nmax, "mean_tps": round(mean, 2) if mean else None,
                   "probes": got,
                   "accept_rate": round(acc / dr, 4) if dr else None,
                   "mean_accepted_len": round(acc / drafts, 3) if drafts else None,
                   "per_pos_rate": {k: round(v / drafts, 4)
                                    for k, v in sorted(sc.get("per_pos", {}).items())}
                   if drafts else {}}
            rows.append(row)
            print("  mean %.2f t/s | accept %.1f%% | mean len %.2f"
                  % (mean or 0, 100 * (row["accept_rate"] or 0),
                     row["mean_accepted_len"] or 0), flush=True)
            if row["per_pos_rate"]:
                print("  per-position acceptance: " + "  ".join(
                    "p%d %.0f%%" % (k, 100 * v)
                    for k, v in row["per_pos_rate"].items()), flush=True)
        finally:
            try:
                p.terminate()
                p.wait(timeout=30)
            except Exception:
                p.kill()
            lf.close()
            time.sleep(4)

    print("\n=== SUMMARY (shipped recipe, only --spec-draft-n-max varies) ===")
    base = next((r for r in rows if r.get("nmax") == a.nmax[0]
                 and r.get("mean_tps")), None)
    for r in rows:
        if not r.get("mean_tps"):
            print("  n-max %-2d  FAILED (%s)" % (r["nmax"], r.get("FAILED", "?")))
            continue
        rel = ("%+.1f%%" % (100.0 * (r["mean_tps"] / base["mean_tps"] - 1))
               ) if base else "-"
        print("  n-max %-2d  %6.2f t/s  %7s   accept %.1f%%  mean len %.2f"
              % (r["nmax"], r["mean_tps"], rel,
                 100 * (r["accept_rate"] or 0), r["mean_accepted_len"] or 0))
    json.dump({"date": time.strftime("%Y-%m-%d %H:%M"),
               "model": os.path.basename(a.model),
               "note": "shipped recipe; only --spec-draft-n-max varies; "
                       "greedy; quiet machine",
               "rows": rows},
              io.open(os.path.join(OUT, "draft-nmax-sweep.json"), "w",
                      encoding="utf-8"), indent=1)
    print("\nwrote %s" % os.path.join(OUT, "draft-nmax-sweep.json"))
