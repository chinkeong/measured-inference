#!/usr/bin/env python3
"""E4 — turn "IQ2_M is dequant-bound" from a RATIO into a COUNTER.

WHAT THIS EXISTS TO SETTLE. Stage 1 back-solved rule 10's efficiency constant
per format: 0.82 (Q8_0), 0.73 (Q4_K_M), 0.54 (IQ2_M) against the 3090's
published 936 GB/s. IQ2_M landing 22% under the bandwidth roofline is the whole
basis for this campaign's claim that at 2 bits the workload stops being
memory-bound and becomes unpack-bound. That claim is currently DERIVED -- it is
a ratio of two measured numbers against a CITED peak bandwidth that
machine.json does not even carry (spec_bandwidth_gbs is null, because
detect-machine.py refuses to assert a figure it can neither measure nor cite).

A ratio is not a counter. Nsight reads the hardware directly: if IQ2_M is
genuinely dequant-bound its Memory Throughput % of peak will be LOW while its
Compute (SM) Throughput % is HIGH, and Q8_0's will be the other way round. If
both come back memory-bound, the campaign's roofline story is wrong and rule
10's constant is moving for some other reason.

WHY THIS IS ONLY POSSIBLE HERE. /proc/driver/nvidia/params reports
RmProfilingAdminOnly: 1 -- NVIDIA gates performance counters behind admin. This
campaign runs elevated, which Stage 0 recorded as a condition with a cost
(pl_writable_without_elevation is permanently null). This is the other side of
that trade: an unelevated campaign cannot run this task at all, and the report
must say so rather than leaving a reader to wonder why the section is missing.

WHAT IS PROFILED, AND WHY NOT THE SERVER. llama-bench, not llama-server: it is
bounded, it separates prefill (pp) from decode (tg) by construction, and it
exits, which a profiler needs. The decode kernels are the ones the roofline
claim is about.

TWO TOOLS, DELIBERATELY:
  nsys -- a timeline. Which kernels own the time, at near-zero overhead. Cheap
          enough to run over the whole benchmark.
  ncu  -- per-kernel counters. It REPLAYS each kernel many times, so it is
          slow and is bounded here by --launch-skip (past warm-up) and
          --launch-count (a steady-state sample), never let loose on the run.
"""
import json, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "scripts", "lib"))
sys.path.insert(0, os.path.join(REPO, "scripts", "bench"))
import paths, gpu_lock                                          # noqa: E402

CAMP = paths.load_campaign(); SLUG = CAMP["slug"]
DATA = os.path.join(REPO, "results", SLUG, "data")
WORK = os.path.join(REPO, "results", SLUG, "work")
OUT = os.path.join(DATA, "ncu-roofline.json")
BENCH = paths.llama_bin("llama-bench")
ARMS = ["Q8_0", "Q4_K_M", "IQ2_M"]

# The rule-10 constants this task exists to test, from Stage 1.
DERIVED_CONSTANT = {"Q8_0": 0.82, "Q4_K_M": 0.73, "IQ2_M": 0.54}
PEAK_GBS = 936.0        # RTX 3090 published spec. CITED, not measured here --
                        # machine.json carries null for exactly this reason.


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def run(cmd, logp, timeout=5400):
    with open(logp, "w") as fh:
        p = gpu_lock.serve(cmd, tag="ncu", stdout=fh, stderr=subprocess.STDOUT)
        try:
            rc = p.wait(timeout=timeout)
        except Exception:
            p.kill(); rc = -9
    return rc, open(logp, errors="replace").read()


def nsys_kernels(label, gguf):
    """Timeline: which kernels own decode time. Low overhead, whole benchmark."""
    rep = os.path.join(WORK, "nsys-%s" % label)
    logp = os.path.join(WORK, "nsys-%s.log" % label)
    rc, _ = run(["nsys", "profile", "-o", rep, "--force-overwrite", "true",
                 "-t", "cuda", "--stats", "false",
                 BENCH, "-m", gguf, "-ngl", "99", "-p", "0", "-n", "128",
                 "-r", "1", "-o", "json"], logp)
    stats_log = os.path.join(WORK, "nsys-%s-stats.log" % label)
    rc2, text = run(["nsys", "stats", "--report", "cuda_gpu_kern_sum",
                     "--format", "csv", rep + ".nsys-rep"], stats_log)
    rows = []
    for line in text.splitlines():
        parts = [c.strip() for c in line.split(",")]
        if len(parts) >= 8 and re.match(r"^[0-9.]+$", parts[0] or "x"):
            try:
                rows.append({"time_pct": float(parts[0]),
                             "total_ns": int(float(parts[1])),
                             "instances": int(float(parts[2])),
                             "name": parts[-1][:90]})
            except Exception:
                pass
    rows.sort(key=lambda r: -r["time_pct"])
    return {"rc_profile": rc, "rc_stats": rc2, "top_kernels": rows[:12],
            "log": os.path.relpath(logp, REPO)}


SOL = {
    "compute_pct": re.compile(r"Compute\s*\(SM\)\s*Throughput.*?([0-9.]+)\s*$", re.M | re.I),
    "memory_pct": re.compile(r"Memory\s*Throughput.*?([0-9.]+)\s*$", re.M | re.I),
    "dram_gbs": re.compile(r"DRAM\s*Throughput.*?([0-9.]+)\s*$", re.M | re.I),
    "achieved_occupancy": re.compile(r"Achieved\s*Occupancy.*?([0-9.]+)\s*$", re.M | re.I),
}


def ncu_sol(label, gguf):
    """Per-kernel counters on a bounded, steady-state sample of decode kernels."""
    logp = os.path.join(WORK, "ncu-%s.log" % label)
    rc, text = run(["ncu", "--target-processes", "all",
                    "--section", "SpeedOfLight",
                    "--section", "Occupancy",
                    "--launch-skip", "400", "--launch-count", "40",
                    "--csv", "--page", "raw",
                    BENCH, "-m", gguf, "-ngl", "99", "-p", "0", "-n", "128",
                    "-r", "1", "-o", "json"], logp)
    rec = {"rc": rc, "log": os.path.relpath(logp, REPO)}
    # ncu --csv --page raw emits a header row then one row per kernel/metric set.
    lines = [l for l in text.splitlines() if l.count('","') > 3]
    if lines:
        hdr = [h.strip('"') for h in lines[0].split('","')]
        vals = {}
        for line in lines[1:]:
            cells = [c.strip('"') for c in line.split('","')]
            for h, c in zip(hdr, cells):
                try:
                    vals.setdefault(h, []).append(float(c.replace(",", "")))
                except Exception:
                    pass
        rec["metrics"] = {}
        for h, series in vals.items():
            if not series:
                continue
            key = h.strip()
            if any(w in key.lower() for w in
                   ("dram", "throughput", "occupancy", "sm__", "gpu__")):
                rec["metrics"][key] = {"mean": round(sum(series) / len(series), 4),
                                       "max": round(max(series), 4),
                                       "n": len(series)}
        rec["kernels_sampled"] = max((len(v) for v in vals.values()), default=0)
    if not rec.get("metrics"):
        rec["log_tail"] = text[-3000:]
    return rec


def main():
    os.makedirs(DATA, exist_ok=True)
    out = {"_schema": "ncu-roofline v1", "slug": SLUG,
           "question": ("is IQ2_M's 0.54 rule-10 constant a DEQUANT bound? "
                        "memory-bound kernels show high Memory Throughput %% and "
                        "low Compute %%; the reverse means compute/unpack-bound."),
           "derived_constant_from_stage1": DERIVED_CONSTANT,
           "peak_bandwidth_gbs": {"value": PEAK_GBS, "how": (
               "CITED, RTX 3090 published specification. machine.json carries "
               "spec_bandwidth_gbs=null because detect-machine.py refuses a "
               "figure it can neither measure nor cite, so this number enters "
               "the campaign HERE and must be re-checked against NVIDIA's page "
               "before publication (rule 1).")},
           "elevation": ("RmProfilingAdminOnly=1: NVIDIA gates performance "
                         "counters behind admin. This task is impossible in an "
                         "unelevated campaign and the report says so."),
           "profiled": "llama-bench tg128 (decode), -r 1, -ngl 99",
           "arms": {}}
    if os.path.exists(OUT):
        try:
            out = json.load(open(OUT))
        except Exception:
            pass
    gpu_lock.acquire("stage6-ncu")
    for label in ARMS:
        if out["arms"].get(label, {}).get("ncu", {}).get("metrics"):
            log("%s already profiled -- skipping" % label)
            continue
        gguf = paths.model_path(label)
        log("=== %s ===" % label)
        rec = out["arms"].get(label, {})
        log("  nsys timeline")
        rec["nsys"] = nsys_kernels(label, gguf)
        top = (rec["nsys"].get("top_kernels") or [{}])[0]
        log("  top kernel: %s  %.1f%%" % (top.get("name", "?"),
                                          top.get("time_pct", 0)))
        log("  ncu counters (kernel replay -- slow by design)")
        rec["ncu"] = ncu_sol(label, gguf)
        log("  metrics: %s" % list((rec["ncu"].get("metrics") or {}).keys())[:6])
        out["arms"][label] = rec
        json.dump(out, open(OUT, "w"), indent=1)
    json.dump(out, open(OUT, "w"), indent=1)
    log("wrote %s" % OUT)


if __name__ == "__main__":
    main()
