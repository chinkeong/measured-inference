"""Telemetry aimed at hardware questions, not at reader-facing throughput.

    python silicon-telemetry.py --collect <tag> [--server-log PATH]
    python silicon-telemetry.py --analyse <tag> --model-bytes N

WHY THIS IS DIFFERENT FROM THE POWER SCRIPTS ALREADY HERE. `power-cap-arms.py`
and `close-three.py` answer "what does a token cost", which is a reader's
question. This answers "what is the machine actually limited BY", which is a
designer's question, and the two want different numbers. A reader needs joules
per token. A designer needs to know whether spending transistors on compute,
bandwidth, or power delivery would change anything at all.

THE FIRST SAMPLE ALREADY SETTLED THAT FOR THIS WORKLOAD, and it is why this
file exists. During agentic code repair on an RTX 3090:

    pviol 73%    sw_power_cap ACTIVE    sm 87-100%    mem controller 24-60%
    mclk pinned 9501 MHz    pclk sagging 1635-1680

**Power-limited, not bandwidth-limited, and not thermally limited.** The memory
controller is HALF IDLE while the SM sits near 100% and the clock is being
pulled down by the power cap. That inverts the usual local-inference story,
where decode is bandwidth-bound - because agentic work is prefill-heavy, and
prefill is compute-bound.

WHAT IS COLLECTED, and why each one earns its place:

  pwr, pviol, tviol   power draw, and the FRACTION OF TIME clipped by the power
                      cap or by thermals. pviol is the single most useful
                      number here: if it is high, more compute buys nothing.
  sm %, mem %         SM busy against MEMORY CONTROLLER busy. Their ratio is
                      what separates a compute-bound phase from a bandwidth-
                      bound one, and it moves within a single request as
                      prefill gives way to decode.
  pclk, mclk          where the clocks actually sit, as opposed to their spec.
  rxpci, txpci        host transfer pressure. Near zero here, which says the
                      PCIe link is not a design constraint for this workload -
                      worth recording precisely because it is a null.
  fb                  framebuffer occupancy over time.
  sbecc, dbecc        ECC events. Expected zero; a non-zero is a story.
  throttle bitmask    nvidia-smi's reason flags, sampled alongside, because
                      pviol says THAT it clipped and the bitmask says WHY.

DERIVED IN --analyse, joined against llama-server's own per-request log:

  achieved bandwidth  decode re-reads the weights once per token, so
                      file_bytes x decode_tok/s is real traffic. Against the
                      card's 936 GB/s spec that gives ROOFLINE OCCUPANCY, and
                      how far a bigger memory system could move the answer.
  phase split         prefill ms against decode ms across a real workload, not
                      a synthetic probe. Agentic work is prompt-heavy and the
                      split is the reason the power picture inverts.
  energy by phase     joules per prefill token against joules per decode token.
  speculation gain    MTP verifies several tokens per weight pass, so it
                      converts a bandwidth-bound phase into a partly compute-
                      bound one. Mean accepted length is the multiplier.

TIER, unchanged and not negotiable: in-band GPU board power as NVML reports it.
The power supply's conversion loss, the CPU, system memory, drives and the
display are excluded and unmeasured. Not system power.
"""

import argparse
import io
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(ROOT, "results", "qwen38-27b-blind", "data", "telemetry")

DMON_FIELDS = "pucvmet"
SPEC_BW_GBS = 936.0          # RTX 3090 quoted memory bandwidth
# Throttle reasons, plus the four fields dmon does NOT carry. They are
# APPENDED so that a file written before 2026-08-27 still parses on its first
# two columns, which is all any reader of this file uses.
#
#   fan.speed             the cooling solution's actual output. Measured at
#                         100% on the reference part while thermal throttling
#                         fires on only ~3% of busy samples: the part is not
#                         thermally limited, but it is holding that operating
#                         point with nothing in reserve. A designer reading
#                         only "thermal throttle 3%" would conclude there is
#                         headroom; the fan curve says it has already been
#                         spent. Acoustics are a product constraint.
#   pstate                the coarse DVFS state, for residency
#   enforced.power.limit  the cap actually in force, so board power can be
#                         expressed as a FRACTION of the limit rather than as
#                         a bare number that means nothing on another part
#
# NOT collected, and checked rather than assumed: clocks.applications.graphics
# returns "[Requested functionality has been deprecated]" on this driver, and
# temperature.memory returns N/A on this part. Recording either would put an
# error string or a null into a column that later reads as data.
THROTTLE_Q = ("clocks_throttle_reasons.active,"
              "clocks_throttle_reasons.sw_power_cap,"
              "clocks_throttle_reasons.hw_slowdown,"
              "clocks_throttle_reasons.sw_thermal_slowdown,"
              "clocks_throttle_reasons.hw_thermal_slowdown,"
              "fan.speed,"
              "pstate,"
              "enforced.power.limit")


def collect(tag, seconds):
    os.makedirs(OUT, exist_ok=True)
    dmon_path = os.path.join(OUT, "%s-dmon.csv" % tag)
    thr_path = os.path.join(OUT, "%s-throttle.csv" % tag)
    print("collecting -> %s" % dmon_path, flush=True)

    df = io.open(dmon_path, "w", encoding="utf-8")
    tf = io.open(thr_path, "w", encoding="utf-8")
    tf.write("t,active_mask,sw_power_cap,hw_slowdown,sw_thermal,hw_thermal\n")

    p = subprocess.Popen(["nvidia-smi", "dmon", "-s", DMON_FIELDS],
                         stdout=subprocess.PIPE, text=True,
                         encoding="utf-8", errors="replace", bufsize=1)
    t0 = time.time()
    last_thr = 0.0
    try:
        for line in p.stdout:
            df.write("%.3f,%s" % (time.time(), ",".join(line.split())) + "\n")
            df.flush()
            now = time.time()
            if now - last_thr >= 5.0:
                last_thr = now
                try:
                    o = subprocess.run(
                        ["nvidia-smi", "--query-gpu=" + THROTTLE_Q,
                         "--format=csv,noheader"],
                        capture_output=True, text=True, timeout=10).stdout.strip()
                    tf.write("%.3f,%s\n" % (now, o.replace(", ", ",")))
                    tf.flush()
                except Exception:
                    pass
            if seconds and (now - t0) > seconds:
                break
    except KeyboardInterrupt:
        pass
    finally:
        try:
            p.terminate()
        except Exception:
            pass
        df.close()
        tf.close()
    print("collected %.1f minutes" % ((time.time() - t0) / 60.0))


def _num(x):
    try:
        return float(x)
    except Exception:
        return None


def analyse(tag, model_bytes, server_log):
    dmon_path = os.path.join(OUT, "%s-dmon.csv" % tag)
    if not os.path.exists(dmon_path):
        sys.exit("no telemetry at %s" % dmon_path)
    rows = []
    for ln in io.open(dmon_path, encoding="utf-8", errors="replace"):
        parts = ln.strip().split(",")
        if len(parts) < 14 or parts[1].startswith("#") or parts[1] == "gpu":
            continue
        rows.append(parts)
    if not rows:
        sys.exit("no usable samples")

    # dmon -s pucvmet column order after the timestamp we prepend:
    # t,gpu,pwr,gtemp,mtemp,sm,mem,enc,dec,jpg,ofa,mclk,pclk,pviol,tviol,fb,...
    def col(r, i):
        return _num(r[i]) if i < len(r) else None

    pwr = [col(r, 2) for r in rows if col(r, 2) is not None]
    smu = [col(r, 5) for r in rows if col(r, 5) is not None]
    memu = [col(r, 6) for r in rows if col(r, 6) is not None]
    mclk = [col(r, 11) for r in rows if col(r, 11) is not None]
    pclk = [col(r, 12) for r in rows if col(r, 12) is not None]
    pviol = [col(r, 13) for r in rows if col(r, 13) is not None]
    tviol = [col(r, 14) for r in rows if col(r, 14) is not None]

    def m(v):
        return sum(v) / len(v) if v else None

    dur = float(rows[-1][0]) - float(rows[0][0])
    joules = m(pwr) * dur if pwr else None

    rep = {
        "tag": tag, "samples": len(rows), "seconds": round(dur, 1),
        "tier": "in-band GPU board power (NVML); PSU, CPU, RAM, drives and "
                "display excluded. NOT system power.",
        "board_watts_mean": round(m(pwr), 1) if pwr else None,
        "board_watts_max": max(pwr) if pwr else None,
        "board_joules_total": round(joules, 0) if joules else None,
        "board_wh_total": round(joules / 3600.0, 3) if joules else None,
        "sm_busy_pct_mean": round(m(smu), 1) if smu else None,
        "mem_controller_pct_mean": round(m(memu), 1) if memu else None,
        "sm_over_mem_ratio": round(m(smu) / m(memu), 2) if (smu and memu and m(memu)) else None,
        "sm_clock_mhz_mean": round(m(pclk)) if pclk else None,
        "mem_clock_mhz_mean": round(m(mclk)) if mclk else None,
        "power_violation_pct_mean": round(m(pviol), 1) if pviol else None,
        "thermal_violation_pct_mean": round(m(tviol), 1) if tviol else None,
        "samples_power_capped": sum(1 for v in pviol if v and v > 0) if pviol else None,
        "fraction_of_time_power_capped": round(
            sum(1 for v in pviol if v and v > 0) / len(pviol), 3) if pviol else None,
    }

    # llama-server's own accounting, if its log was captured
    if server_log and os.path.exists(server_log):
        txt = io.open(server_log, encoding="utf-8", errors="replace").read()
        acc = [(float(a), float(b), float(c)) for a, b, c in re.findall(
            r"acceptance = ([0-9.]+) \(\s*(\d+) accepted /\s*(\d+) generated", txt)]
        tg = [float(x) for x in re.findall(r"tg =\s*([0-9.]+) t/s", txt)]
        mlen = [float(x) for x in re.findall(r"mean len =\s*([0-9.]+)", txt)]
        if tg:
            bw = model_bytes * m(tg) / 1e9 if model_bytes else None
            rep["decode_tps_mean"] = round(m(tg), 2)
            rep["decode_tps_samples"] = len(tg)
            if bw:
                rep["achieved_read_bandwidth_gbs"] = round(bw, 1)
                rep["roofline_occupancy_pct"] = round(bw / SPEC_BW_GBS * 100, 1)
                rep["spec_bandwidth_gbs"] = SPEC_BW_GBS
        if acc:
            rep["draft_acceptance_mean"] = round(m([a for a, _, _ in acc]), 3)
            rep["draft_samples"] = len(acc)
        if mlen:
            rep["draft_mean_len"] = round(m(mlen), 2)
            rep["effective_tokens_per_weight_pass"] = round(m(mlen), 2)

    os.makedirs(OUT, exist_ok=True)
    f = os.path.join(OUT, "%s-summary.json" % tag)
    json.dump(rep, io.open(f, "w", encoding="utf-8"), indent=1)

    print("=" * 66)
    print("SILICON TELEMETRY  %s   (%d samples over %.1f min)"
          % (tag, rep["samples"], rep["seconds"] / 60.0))
    print("=" * 66)
    print("  board power            %s W mean, %s W peak"
          % (rep["board_watts_mean"], rep["board_watts_max"]))
    print("  energy                 %s Wh" % rep["board_wh_total"])
    print("  SM busy                %s %%" % rep["sm_busy_pct_mean"])
    print("  memory controller busy %s %%" % rep["mem_controller_pct_mean"])
    print("  SM : memory ratio      %s" % rep["sm_over_mem_ratio"])
    print("  SM clock               %s MHz     memory clock %s MHz"
          % (rep["sm_clock_mhz_mean"], rep["mem_clock_mhz_mean"]))
    print("  POWER-CAPPED           %s %% of samples, mean violation %s %%"
          % (round(100 * (rep["fraction_of_time_power_capped"] or 0), 1),
             rep["power_violation_pct_mean"]))
    print("  thermally throttled    %s %%" % rep["thermal_violation_pct_mean"])
    if "roofline_occupancy_pct" in rep:
        print("  achieved read bandwidth %s GB/s of %s spec  (%s %% of roofline)"
              % (rep["achieved_read_bandwidth_gbs"], SPEC_BW_GBS,
                 rep["roofline_occupancy_pct"]))
    if "draft_mean_len" in rep:
        print("  speculation            %s tokens per weight pass, acceptance %s"
              % (rep["draft_mean_len"], rep.get("draft_acceptance_mean")))
    print()
    print("  READ IT LIKE THIS: a high power-capped fraction with the memory")
    print("  controller well under the SM means the part is limited by POWER")
    print("  DELIVERY, not by bandwidth and not by heat - so a wider memory bus")
    print("  would buy nothing here, and more compute would only be clipped.")
    print("-> %s" % f)


def main():
    ap = argparse.ArgumentParser()
    # --tag is the interface every other collector in this campaign uses.
    # This script alone took --collect, and a launcher that passed --tag got an
    # argparse exit(2) into a hidden window: no file, no message, no clue. The
    # pre-flight guard caught it, but only after a model load. One spelling.
    ap.add_argument("--collect", "--tag", dest="collect", metavar="TAG")
    ap.add_argument("--analyse", metavar="TAG")
    ap.add_argument("--seconds", type=float, default=0)
    ap.add_argument("--model-bytes", type=float, default=0)
    ap.add_argument("--server-log", default=None)
    a = ap.parse_args()
    if a.collect:
        collect(a.collect, a.seconds)
    elif a.analyse:
        analyse(a.analyse, a.model_bytes, a.server_log)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
