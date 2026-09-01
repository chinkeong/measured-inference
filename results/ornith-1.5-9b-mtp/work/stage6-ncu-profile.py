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
  nsys -- DROPPED on this box. The apt nsight-systems (2023.4.4) writes a
          .qdstrm and then reports "The importer binary and its dependencies
          were not found", so no readable report is ever produced. Measured
          2026-09-01; ncu carries the task alone and gives kernel names anyway.
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
    """Per-kernel roofline counters on a bounded sample of decode kernels.

    METRICS BY NAME, not --section. The first attempt asked for --section
    SpeedOfLight and parsed the raw page, and got back dram__cycles_active and
    gpu__compute_memory_throughput -- real metrics, but not the two the roofline
    claim needs. Naming them removes the guess:
      sm__throughput            ... SM throughput, % of peak   -> compute bound
      gpu__dram_throughput      ... DRAM throughput, % of peak -> memory bound
      dram__bytes.sum.per_second . achieved bandwidth, against 936 GB/s peak
      sm__warps_active          ... occupancy
    All four confirmed present via `ncu --query-metrics` on this GPU first.
    """
    metrics = ",".join([
        "sm__throughput.avg.pct_of_peak_sustained_elapsed",
        "gpu__dram_throughput.avg.pct_of_peak_sustained_elapsed",
        "dram__bytes.sum.per_second",
        "sm__warps_active.avg.pct_of_peak_sustained_active",
    ])
    logp = os.path.join(WORK, "ncu-%s.log" % label)
    rc, text = run(["ncu", "--target-processes", "all", "--metrics", metrics,
                    "--launch-skip", "200", "--launch-count", "60",
                    "--csv", BENCH, "-m", gguf, "-ngl", "99", "-p", "0",
                    "-n", "128", "-r", "1", "-o", "json"], logp)
    rec = {"rc": rc, "log": os.path.relpath(logp, REPO)}
    # ncu --csv: a header row, then one row per (kernel, metric). Columns
    # include "Kernel Name", "Metric Name", "Metric Value".
    rows, hdr = [], None
    for line in text.splitlines():
        if '","' not in line:
            continue
        cells = [c.strip().strip('"') for c in line.split('","')]
        if hdr is None and any(c == "Metric Name" for c in cells):
            hdr = cells
            continue
        if hdr and len(cells) == len(hdr):
            rows.append(dict(zip(hdr, cells)))
    agg, per_kernel = {}, {}
    for r in rows:
        name = r.get("Metric Name", "")
        kern = (r.get("Kernel Name") or "")[:60]
        try:
            v = float((r.get("Metric Value") or "").replace(",", ""))
        except Exception:
            continue
        agg.setdefault(name, []).append(v)
        per_kernel.setdefault(kern, {}).setdefault(name, []).append(v)
    rec["metrics"] = {k: {"mean": round(sum(v) / len(v), 3),
                          "max": round(max(v), 3), "n": len(v)}
                      for k, v in agg.items()}
    # The busiest kernels, by how much DRAM traffic they move.
    tops = []
    for kern, m in per_kernel.items():
        b = m.get("dram__bytes.sum.per_second")
        s_ = m.get("sm__throughput.avg.pct_of_peak_sustained_elapsed")
        d_ = m.get("gpu__dram_throughput.avg.pct_of_peak_sustained_elapsed")
        tops.append({"kernel": kern, "n": len(b or s_ or [1]),
                     "dram_bytes_per_s": round(sum(b) / len(b), 1) if b else None,
                     "sm_pct": round(sum(s_) / len(s_), 2) if s_ else None,
                     "dram_pct": round(sum(d_) / len(d_), 2) if d_ else None})
    tops.sort(key=lambda t: -(t.get("dram_bytes_per_s") or 0))
    rec["top_kernels"] = tops[:8]
    rec["kernels_sampled"] = len(per_kernel)
    if not rec["metrics"]:
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
        rec["nsys"] = {"skipped": ("apt nsight-systems 2023.4.4 cannot import "
                                   "its own .qdstrm on this box -- 'The importer "
                                   "binary and its dependencies were not found'. "
                                   "Measured 2026-09-01.")}
        log("  ncu counters (kernel replay -- slow by design)")
        rec["ncu"] = ncu_sol(label, gguf)
        log("  metrics: %s" % list((rec["ncu"].get("metrics") or {}).keys())[:6])
        out["arms"][label] = rec
        json.dump(out, open(OUT, "w"), indent=1)
    json.dump(out, open(OUT, "w"), indent=1)
    log("wrote %s" % OUT)


if __name__ == "__main__":
    main()
