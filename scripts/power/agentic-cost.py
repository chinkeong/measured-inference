#!/usr/bin/env python3
"""Joules per token for an agentic run, by joining aider's per-exercise token
counts to the GPU power trace.

    agentic-cost.py --tag iq4xs-agentic --run 2026-08-26-14-57-05--iq4xs-full

WHY IT IS A JOIN AND NOT A MEASUREMENT. The first full agentic run recorded a
complete GPU power trace and complete pass rates, and could not produce a
joules-per-token figure from either: the server was launched without
`--metrics` and its log stayed empty, so the token counts were never written
down on the GPU side of the machine. They exist on the CLIENT side, because
aider writes prompt_tokens and completion_tokens into every exercise's
.aider.results.json. This joins the two by wall-clock time.

WHAT THE JOIN CAN AND CANNOT SAY. It can give energy per exercise and per
token over the window the power sampler actually covered. It CANNOT split
prefill from decode - aider records one duration per exercise, not a phase
breakdown - so a J/token from here is a whole-request figure and must be
labelled as one. It is not comparable with a decode-only J/token from a
synthetic probe, and this campaign has been bitten before by numbers that
looked alike and were measured under different conditions.

ONLY exercises that finished INSIDE the telemetry window are counted. Run 1's
sampler was started after the benchmark, so its window is partial; counting an
exercise whose work happened before sampling began would charge its tokens
against energy that was never measured.
"""
import argparse, io, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEL = os.path.join(HERE, "..", "..", "results", "qwen38-27b-blind", "data", "telemetry")


def power_trace(tag):
    """(t, watts) from the dmon csv."""
    path = os.path.join(TEL, "%s-dmon.csv" % tag)
    if not os.path.exists(path):
        sys.exit("no dmon telemetry at %s" % path)
    out = []
    for ln in io.open(path, encoding="utf-8", errors="replace"):
        p = ln.strip().split(",")
        if len(p) > 3 and p[1].isdigit():
            try:
                out.append((float(p[0]), float(p[2])))
            except ValueError:
                pass
    return out


def joules(tr, t0, t1):
    w = [x for x in tr if t0 <= x[0] <= t1]
    if len(w) < 2:
        return None
    j = 0.0
    for i in range(1, len(w)):
        j += (w[i][1] + w[i - 1][1]) / 2.0 * (w[i][0] - w[i - 1][0])
    return j


def exercises(run):
    """Every finished exercise, with its completion time taken from the mtime
    of its results file. WSL holds them, so ask WSL."""
    cmd = ("find ~/bench/aider/tmp.benchmarks/%s -name .aider.results.json "
           "-printf '%%T@ %%p\n' 2>/dev/null" % run)
    o = subprocess.run(["wsl", "-e", "bash", "-lc", cmd],
                       capture_output=True, text=True, timeout=180).stdout
    out = []
    for ln in o.strip().splitlines():
        if not ln.strip():
            continue
        mt, path = ln.split(" ", 1)
        cat = subprocess.run(["wsl", "-e", "bash", "-lc",
                              "cat '%s'" % path.strip()],
                             capture_output=True, text=True, timeout=60).stdout
        try:
            r = json.loads(cat)
        except Exception:
            continue
        if isinstance(r, list):
            r = r[-1] if r else {}
        if not r.get("completion_tokens"):
            continue
        out.append({"t_end": float(mt), "dur": r.get("duration", 0.0),
                    "prompt": r.get("prompt_tokens", 0),
                    "completion": r.get("completion_tokens", 0),
                    "case": r.get("testcase", "?")})
    return sorted(out, key=lambda x: x["t_end"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--run", required=True)
    a = ap.parse_args()

    tr = power_trace(a.tag)
    lo, hi = tr[0][0], tr[-1][0]
    ex = exercises(a.run)
    print("power trace   %.1f min, %d samples" % ((hi - lo) / 60.0, len(tr)))
    print("exercises     %d finished with token counts" % len(ex))

    inside = [e for e in ex if e["t_end"] - e["dur"] >= lo and e["t_end"] <= hi]
    print("inside window %d  (the rest ran before sampling started)" % len(inside))
    if not inside:
        sys.exit("\nno exercise falls entirely inside the telemetry window - "
                 "nothing can be costed without charging unmeasured energy")

    tot_j = tot_c = tot_p = 0.0
    per = []
    for e in inside:
        j = joules(tr, e["t_end"] - e["dur"], e["t_end"])
        if j is None:
            continue
        tot_j += j
        tot_c += e["completion"]
        tot_p += e["prompt"]
        per.append((j / max(e["completion"], 1), e["case"], j, e["completion"]))

    print()
    print("energy        %.1f kJ  (%.3f kWh) over %d exercises"
          % (tot_j / 1000.0, tot_j / 3.6e6, len(per)))
    print("tokens        %d completion, %d prompt" % (tot_c, tot_p))
    print()
    print("J per completion token   %.3f" % (tot_j / max(tot_c, 1)))
    print("J per token (all tokens) %.3f" % (tot_j / max(tot_c + tot_p, 1)))
    print("J per exercise           %.0f" % (tot_j / max(len(per), 1)))
    per.sort()
    print()
    print("cheapest  %-22s %.3f J/tok" % (per[0][1], per[0][0]))
    print("dearest   %-22s %.3f J/tok" % (per[-1][1], per[-1][0]))
    print()
    print("NOTE: whole-request energy (prefill + decode together). Not")
    print("      comparable with a decode-only J/token from a synthetic probe.")
