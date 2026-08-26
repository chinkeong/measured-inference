#!/usr/bin/env python3
"""Joules per token for an agentic run, by joining aider's per-exercise token
counts to the GPU power trace.

    agentic-cost.py --tag iq4xs-agentic --run 2026-08-26-14-57-05--iq4xs-full

WHY IT IS A JOIN AND NOT A MEASUREMENT. The first full agentic run recorded a
complete GPU power trace and complete pass rates, and could produce no
joules-per-token from either: the server was launched without `--metrics` and
its log stayed empty, so token counts were never written on the GPU side. They
survived on the CLIENT side, because aider writes prompt_tokens and
completion_tokens into every exercise's .aider.results.json.

HOW THE WINDOW IS CHOSEN, which is the whole correctness of this script.
The obvious window - [mtime - duration, mtime] - is WRONG, and was used here
until an adversarial review on 2026-08-27 measured what it cost. In aider's
benchmark.py, `dur += time.time() - start` accumulates only around
`coder.run()`; `run_unit_tests()` and the rmtree cleanup of target/debug,
build/ and node_modules/ run AFTERWARDS, and the results file is written after
all of them. So `duration` is a sum of DISJOINT model-call segments while
`mtime` is stamped at the end of a test-and-cleanup tail (measured median
1.6 s, p90 7.1 s, max 180.2 s). The window therefore had the right length in
the wrong place: it billed compile and test time and missed the model work it
named. Consequences measured on the live trace: the cheapest exercise was
published at 0.417 J/token against a true 5.830, and the campaign's headline
"30x spread between exercises" collapsed to 3.0x once placed correctly.

What is used instead: exercises run sequentially (--threads 1, verified - no
inter-mtime gap is shorter than its own duration), so the interval between two
consecutive results-file mtimes belongs to exactly one exercise. Integrating
only the GPU-BUSY samples inside that interval charges each exercise the model
work that actually ran in it and drops the test-time idle. The result is
insensitive to the busy threshold because the power distribution is strongly
bimodal - roughly 25-50 W idle against 325-350 W busy, with little between.

WHAT IT STILL CANNOT SAY. It gives whole-request energy: prefill and decode
together, because aider records one duration per exercise and no phase split.
That is NOT comparable with a decode-only J/token from a synthetic probe. And
while board power sits pinned near the cap, J/token is close to a restatement
of throughput rather than an independent measurement of it.
"""
import argparse, io, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEL = os.path.join(HERE, "..", "..", "results", "qwen38-27b-blind", "data", "telemetry")

BUSY_SM_PCT = 5.0   # a sample counts as model work above this SM utilisation


def power_trace(tag, gpu=0):
    """(t, watts, sm_pct) from the dmon csv, for ONE gpu index.

    The index filter matters: on a multi-GPU host an unfiltered parse
    interleaves several cards into one time series and the trapezoid
    integration silently returns nonsense.
    """
    path = os.path.join(TEL, "%s-dmon.csv" % tag)
    if not os.path.exists(path):
        sys.exit("no dmon telemetry at %s" % path)
    out = []
    for ln in io.open(path, encoding="utf-8", errors="replace"):
        p = ln.strip().split(",")
        if len(p) > 6 and p[1].isdigit() and int(p[1]) == gpu:
            try:
                out.append((float(p[0]), float(p[2]), float(p[5])))
            except ValueError:
                pass
    out.sort()
    return out


def joules(tr, t0, t1, busy_only=True):
    """Trapezoidal energy over [t0, t1].

    Edges are interpolated rather than truncated: integrating only the samples
    strictly inside the window loses up to one sampling period at each end,
    which on a short exercise is a real fraction of the answer.
    """
    if t1 <= t0:
        return 0.0, 0.0
    j = busy_s = 0.0
    for i in range(1, len(tr)):
        ta, wa, sa = tr[i - 1]
        tb, wb, sb = tr[i]
        if tb <= t0 or ta >= t1:
            continue
        span = tb - ta
        if span <= 0:
            continue
        ca, cb = max(ta, t0), min(tb, t1)
        pa = wa + (wb - wa) * ((ca - ta) / span)
        pb = wa + (wb - wa) * ((cb - ta) / span)
        if busy_only and max(sa, sb) <= BUSY_SM_PCT:
            continue
        dt = cb - ca
        j += (pa + pb) / 2.0 * dt
        busy_s += dt
    return j, busy_s


def exercises(run):
    """Every finished exercise with tokens, ordered by completion time."""
    cmd = ("find ~/bench/aider/tmp.benchmarks/" + run +
           " -name .aider.results.json -printf '%T@ %p\\n' 2>/dev/null")
    o = subprocess.run(["wsl", "-e", "bash", "-lc", cmd],
                       capture_output=True, text=True, timeout=300).stdout
    items = []
    for ln in o.strip().splitlines():
        if not ln.strip():
            continue
        mt, path = ln.split(" ", 1)
        items.append((float(mt), path.strip()))
    items.sort()
    out = []
    for mt, path in items:
        cat = subprocess.run(["wsl", "-e", "bash", "-lc", "cat " + json.dumps(path)],
                             capture_output=True, text=True, timeout=60).stdout
        try:
            r = json.loads(cat)
        except Exception:
            continue
        if isinstance(r, list):
            r = r[-1] if r else {}
        if not r.get("completion_tokens"):
            continue
        out.append({"t_end": mt, "dur": r.get("duration", 0.0),
                    "prompt": r.get("prompt_tokens", 0),
                    "completion": r.get("completion_tokens", 0),
                    "case": r.get("testcase", "?")})
    return out


def slots_decoded(tag, t0, t1):
    """Server-side decoded tokens in [t0, t1], if a /slots trace exists.

    A CROSS-CHECK on the denominator, not a replacement for it. aider counts
    the tokens it accounted for; the server also serves chat-history
    summarisation requests - the benchmark passes no weak model, so the
    summariser talks to this same server through a path that does no token
    accounting. Those consume energy that lands in the numerator with no
    tokens in the denominator, so the two counts are EXPECTED to disagree and
    the size of the gap is worth printing rather than hiding.
    """
    path = os.path.join(TEL, "%s-slots.csv" % tag)
    if not os.path.exists(path):
        return None
    tasks, lo, hi = {}, None, None
    for i, ln in enumerate(io.open(path, encoding="utf-8", errors="replace")):
        if i == 0:
            continue
        p = ln.strip().split(",")
        if len(p) != 7:
            continue
        try:
            t, tid, nd = float(p[0]), int(p[1]), int(p[6])
        except ValueError:
            continue
        lo = t if lo is None else min(lo, t)
        hi = t if hi is None else max(hi, t)
        if tid < 0 or not (t0 <= t <= t1):
            continue
        tasks[tid] = max(tasks.get(tid, 0), nd)
    if not tasks:
        return None
    return {"requests": len(tasks), "decoded": sum(tasks.values()),
            "lo": lo, "hi": hi}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--gpu", type=int, default=0)
    a = ap.parse_args()

    tr = power_trace(a.tag, a.gpu)
    if len(tr) < 2:
        sys.exit("power trace too short")
    lo, hi = tr[0][0], tr[-1][0]
    ex = exercises(a.run)
    print("power trace   %.1f min, %d samples (gpu %d)"
          % ((hi - lo) / 60.0, len(tr), a.gpu))
    print("exercises     %d finished with token counts" % len(ex))

    # Each exercise owns the interval since the previous one finished. The
    # first has no predecessor, so it is dropped rather than guessed at.
    charged, skipped = [], 0
    for i in range(1, len(ex)):
        t0, t1 = ex[i - 1]["t_end"], ex[i]["t_end"]
        if t0 < lo or t1 > hi:
            continue
        if t1 - t0 < ex[i]["dur"] - 1.0:
            # Would mean two exercises overlapped, which --threads 1 forbids:
            # report it as a data problem rather than absorbing it.
            skipped += 1
            continue
        j, bs = joules(tr, t0, t1, True)
        j_all, _ = joules(tr, t0, t1, False)
        e = dict(ex[i])
        e.update({"t0": t0, "j": j, "j_all": j_all, "busy_s": bs,
                  "span_s": t1 - t0})
        charged.append(e)

    print("charged       %d  (interval-attributed, GPU-busy samples only)"
          % len(charged))
    if skipped:
        print("              %d skipped: interval shorter than duration" % skipped)
    if not charged:
        sys.exit("\nno exercise interval falls inside the telemetry window")

    tot_j = sum(e["j"] for e in charged)
    tot_all = sum(e["j_all"] for e in charged)
    tot_c = sum(e["completion"] for e in charged)
    tot_p = sum(e["prompt"] for e in charged)
    tot_busy = sum(e["busy_s"] for e in charged)
    tot_span = sum(e["span_s"] for e in charged)

    print()
    print("energy        %.1f kJ busy  (%.1f kJ including idle) = %.3f kWh"
          % (tot_j / 1000.0, tot_all / 1000.0, tot_j / 3.6e6))
    print("time          %.0f s GPU-busy of %.0f s wall  (%.1f%% busy)"
          % (tot_busy, tot_span, 100.0 * tot_busy / max(tot_span, 1e-9)))
    print("tokens        %d completion, %d prompt (aider-accounted)"
          % (tot_c, tot_p))
    print()
    print("J per completion token   %.3f" % (tot_j / max(tot_c, 1)))
    print("J per token (all tokens) %.3f" % (tot_j / max(tot_c + tot_p, 1)))
    print("J per exercise           %.0f" % (tot_j / len(charged)))

    # The cross-check MUST run over a window both sources cover. The /slots
    # collector was started after the benchmark, so comparing its totals to
    # aider's across the whole charged span measures the missing prefix of the
    # trace, not any disagreement between the two counters - it reported a
    # -19.5% "gap" that was entirely window mismatch.
    probe = slots_decoded(a.tag, lo, hi)
    sd = None
    if probe and probe["lo"] is not None:
        common = [e for e in charged
                  if e["t0"] >= probe["lo"] and e["t_end"] <= probe["hi"]]
        if common:
            sd = slots_decoded(a.tag, common[0]["t0"], common[-1]["t_end"])
            tot_c_common = sum(e["completion"] for e in common)
            tot_j_common = sum(e["j"] for e in common)
    if sd:
        gap = 100.0 * (sd["decoded"] - tot_c_common) / max(tot_c_common, 1)
        print()
        print("cross-check vs server  over the %d exercises both sources cover"
              % len(common))
        print("                       server %d decoded over %d requests"
              % (sd["decoded"], sd["requests"]))
        print("                       aider accounts for %d, a %+.1f%% gap"
              % (tot_c_common, gap))
        tot_c, tot_j = tot_c_common, tot_j_common
        if gap > 2.0:
            print("                       => the J/completion-token above is an")
            print("                          UPPER bound: the server decoded tokens")
            print("                          aider does not count (summarisation),")
            print("                          so the real figure is lower.")
            print("                       server-denominated: %.3f J/token"
                  % (tot_j / max(sd["decoded"], 1)))

    per = sorted((e["j"] / max(e["completion"], 1), e["case"]) for e in charged)
    print()
    print("cheapest  %-22s %.3f J/tok" % (per[0][1], per[0][0]))
    print("dearest   %-22s %.3f J/tok" % (per[-1][1], per[-1][0]))
    print("spread    %.1fx" % (per[-1][0] / max(per[0][0], 1e-9)))
    print()
    print("NOTE: whole-request energy (prefill + decode together). Not")
    print("      comparable with a decode-only J/token from a synthetic probe.")
    print("      With board power pinned near the cap, J/token is close to a")
    print("      restatement of throughput rather than an independent measure.")
