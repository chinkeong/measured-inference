#!/usr/bin/env python3
"""The anchor sweep: Qwen3.5-9B and Ornith-1.5-9B, ONE sweep, fully crossed.

WHY IT HAS TO BE ONE SWEEP. This rig has two throughput levels about 13% apart
and nothing recorded predicts which one a run lands on (rule 30, seven candidate
causes tested and eliminated). Ornith's numbers were taken across two days and a
dozen server loads; quoting them beside a fresh Qwen number would be comparing
sweeps, not models. So both arms are measured here, alternating, against one
server-load discipline, and the ANCHOR's own absolute is published so a later
sweep can form ratios against it (COMPARISON-SPEC).

FULLY CROSSED, 2 models x 2 samplers. The sampler cannot be held at "each
model's own recommended preset" for a SPEED comparison -- this campaign already
measured that the card preset costs a near-constant ~0.70 ms per token over
greedy, which is larger than most differences anyone runs a comparison to find.
Crossing it instead means the model effect and the sampler effect are separable
inside one sweep rather than confounded.

DISCIPLINE, all of it from the rules this repo already carries:
  rule 12  the first probe after each load is DISCARDED (ramping clocks read
           up to 45% low)
  rule 30  arm order ALTERNATES, so position in the sweep cannot be mistaken
           for a property of an arm
  rule 27  every probe records SM clock, board power, temperature and load1 --
           this box is not quiet and the operator has accepted that
  rule 20  one server at a time, through gpu_lock, torn down in a finally
  rule 3   the identical prompt, cap and context for every arm

WHAT THIS DELIBERATELY DOES NOT MEASURE. KLD across the two models is not run:
KL divergence answers "how far is this quant from ITS OWN unquantised weights",
and pointing it at two different models compares distributions that were never
meant to agree. The tokenizer gate that would make it legal is a necessary
condition, not a sufficient one. Model-vs-model quality belongs to the scored
benchmarks, which run separately against a matching suite hash.
"""
import json, os, subprocess, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "scripts", "lib"))
sys.path.insert(0, os.path.join(REPO, "scripts", "bench"))
import paths, gpu_lock                                          # noqa: E402
import importlib.util                                           # noqa: E402
spec = importlib.util.spec_from_file_location(
    "ld", os.path.join(REPO, "scripts", "bench", "loop-detect.py"))
ld = importlib.util.module_from_spec(spec); spec.loader.exec_module(ld)

MODELS = os.path.join(REPO, "models")
DATA = os.path.join(REPO, "results", "qwen35-9b-family", "data")
WORK = os.path.join(REPO, "results", "qwen35-9b-family", "work")
SERVER = paths.llama_bin("llama-server")
PORT = 18097
CTX = 32768
OUT = os.path.join(DATA, "anchor-sweep.json")

ARMS = [("Qwen3.5-9B", "Qwen3.5-9B-MTP-Q8_0.gguf"),
        ("Ornith-1.5-9B", "Ornith-1.5-9B-MTP-Q8_0.gguf")]
GREEDY = {"temperature": 0.0, "top_p": 1.0, "top_k": 1, "presence_penalty": 0.0}
CARD = {"temperature": 1.0, "top_p": 0.95, "top_k": 20, "presence_penalty": 1.5}
SAMPLERS = [("greedy", GREEDY), ("card", CARD)]
REPS = 4                       # first discarded, rule 12
PROMPT = ("Implement a red-black tree in Python with insert, delete and "
          "in-order traversal. Include a short docstring on each method.")
MAXTOK = 700


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def telemetry():
    try:
        q = subprocess.run(["nvidia-smi",
                            "--query-gpu=clocks.sm,power.draw,temperature.gpu",
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10).stdout.strip().split(",")
        sm, pw, tp = float(q[0]), float(q[1]), float(q[2])
    except Exception:
        sm = pw = tp = None
    try:
        load1 = float(open("/proc/loadavg").read().split()[0])
    except Exception:
        load1 = None
    return {"clocks_sm_mhz": sm, "power_w": pw, "temp_c": tp, "load1": load1}


def ask(sampler):
    body = {"model": "x", "messages": [{"role": "user", "content": PROMPT}],
            "max_tokens": MAXTOK, "stream": False, "cache_prompt": False}
    body.update(sampler)
    req = urllib.request.Request(
        "http://127.0.0.1:%d/v1/chat/completions" % PORT,
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    r = json.load(urllib.request.urlopen(req, timeout=1800))
    ch = (r.get("choices") or [{}])[0]
    m = ch.get("message", {}) or {}
    c, rz = m.get("content") or "", m.get("reasoning_content") or ""
    return {"text": c, "reasoning": rz, "full": (rz + "\n\n" + c) if rz else c,
            "finish": ch.get("finish_reason"), "timings": r.get("timings") or {},
            "usage": r.get("usage") or {}}


def main():
    os.makedirs(DATA, exist_ok=True)
    out = {"_schema": "anchor-sweep v1", "slug": "qwen35-9b-family",
           "anchor": "Qwen3.5-9B",
           "why_one_sweep": ("rule 30: this rig has two throughput levels ~13% "
                             "apart and nothing predicts which; arms compare "
                             "only inside one sweep"),
           "protocol": {"reps": REPS, "first_discarded": "rule 12",
                        "order": "alternating (rule 30)", "ctx": CTX,
                        "max_tokens": MAXTOK,
                        "samplers": {"greedy": GREEDY, "card": CARD}},
           "arms": {}}
    if os.path.exists(OUT):
        try:
            out = json.load(open(OUT))
        except Exception:
            pass
    for i, (label, fname) in enumerate(ARMS):
        if out["arms"].get(label, {}).get("done"):
            log("%s already done -- skipping" % label); continue
        g = os.path.join(MODELS, fname)
        if not os.path.exists(g):
            out["arms"][label] = {"error": "missing %s" % fname}; continue
        gpu_lock.acquire("anchor-%s" % label)
        cmd = [SERVER, "-m", g, "-c", str(CTX), "-ngl", "99", "--parallel", "1",
               "--jinja", "--host", "127.0.0.1", "--port", str(PORT)]
        fh = open(os.path.join(WORK, "anchor-%s.log" % label), "w")
        p = gpu_lock.serve(cmd, tag="anchor-%s" % label, stdout=fh,
                           stderr=subprocess.STDOUT)
        rec = {"file": fname, "size_bytes": os.path.getsize(g),
               "probes": [], "done": False}
        try:
            for _ in range(600):
                if p.poll() is not None:
                    raise RuntimeError("server exited rc=%s" % p.returncode)
                try:
                    urllib.request.urlopen("http://127.0.0.1:%d/health" % PORT, timeout=5)
                    break
                except Exception:
                    pass
                time.sleep(2)
            else:
                raise RuntimeError("server never healthy")
            order = SAMPLERS if i % 2 == 0 else SAMPLERS[::-1]
            for rep in range(REPS):
                for sname, s in order:
                    tel = telemetry()
                    r = ask(s)
                    sig = ld.signals(r["full"]); v = ld.verdict(sig)
                    rec["probes"].append({
                        "rep": rep, "sampler": sname, "discarded": rep == 0,
                        "t_s": r["timings"].get("predicted_per_second"),
                        "predicted_n": r["timings"].get("predicted_n"),
                        "prompt_tokens": r["usage"].get("prompt_tokens"),
                        "finish": r["finish"], "chars": len(r["full"]),
                        "reasoning_chars": len(r["reasoning"]),
                        "content_chars": len(r["text"]),
                        "verdict": v, "signals": {k: round(x, 4) for k, x in sig.items()},
                        "telemetry": tel})
                    log("  %-14s rep%d %-6s %7.2f t/s  %-8s sm=%s load=%s%s" % (
                        label, rep, sname, r["timings"].get("predicted_per_second") or 0,
                        v[0], tel["clocks_sm_mhz"], tel["load1"],
                        "  (discarded)" if rep == 0 else ""))
            rec["done"] = True
        finally:
            try:
                p.terminate(); p.wait(timeout=30)
            except Exception:
                try: p.kill()
                except Exception: pass
            fh.close()
            gpu_lock.release()
        for sname, _ in SAMPLERS:
            kept = [q for q in rec["probes"]
                    if q["sampler"] == sname and not q["discarded"] and q["t_s"]]
            if kept:
                ts = sorted(q["t_s"] for q in kept)
                rec.setdefault("summary", {})[sname] = {
                    "n": len(ts), "min": round(ts[0], 2), "max": round(ts[-1], 2),
                    "median": round(ts[len(ts) // 2], 2),
                    "verdicts": sorted({q["verdict"][0] for q in kept}),
                    "median_predicted_n": sorted(
                        q["predicted_n"] or 0 for q in kept)[len(kept) // 2]}
        out["arms"][label] = rec
        json.dump(out, open(OUT, "w"), indent=1)
    # RATIOS TO THE ANCHOR, which is the only cross-sweep-legal currency
    anc = out["arms"].get("Qwen3.5-9B", {}).get("summary") or {}
    for label, rec in out["arms"].items():
        sm = rec.get("summary") or {}
        for sname in sm:
            if anc.get(sname, {}).get("median"):
                sm[sname]["ratio_to_anchor"] = round(
                    sm[sname]["median"] / anc[sname]["median"], 4)
    json.dump(out, open(OUT, "w"), indent=1)
    log("wrote %s" % OUT)
    for label, rec in out["arms"].items():
        for sname, s in (rec.get("summary") or {}).items():
            log("%-14s %-6s median %7.2f t/s  x anchor %.4f  (n=%d, %.2f-%.2f)  %s"
                % (label, sname, s["median"], s.get("ratio_to_anchor") or 0,
                   s["n"], s["min"], s["max"], ",".join(s["verdicts"])))


if __name__ == "__main__":
    main()
