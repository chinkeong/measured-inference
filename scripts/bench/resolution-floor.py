"""What can this machine actually measure? The instrument's own noise floor.

    python resolution-floor.py

WHY THIS EXISTS, and why it comes before any more register entries.

Three runs of the same DETERMINISTIC arm - UD-IQ4_XS, n4/p0.75, greedy,
temperature 0, top_k 1, nothing random anywhere - read 64.32, 74.08 and 65.25
t/s. Thirteen and a half per cent apart. The 74.08 run had a TIGHT internal
spread (1.8%), so it was not noise within that run: the card was in a different
state for it. A settling trace from the third run shows the shape:

    65.0  65.0  70.9  67.2  66.0  64.8  65.3

an 8.4% excursion at fixed settings that never trends, just bounces.

This campaign publishes speed figures taken from ONE discarded warmup probe and
three settled probes. If the card's own probe-to-probe variance is larger than
the effects being compared, then some of those comparisons are reporting the
card's mood. That is a question about the instrument, and it has to be answered
before the instrument is used again.

WHAT THIS MEASURES. One configuration, one server load, one prompt, nothing
varying but time:

  - 100 SHORT probes (700 predicted tokens), the length this campaign uses
  - 30 LONG probes (3,000 predicted tokens), to test whether a longer probe
    averages the excursions away or simply contains more of them

Per probe it records decode t/s alongside SM clock, temperature and board power,
because the difference between "thermal drift" and "boost lottery" is visible in
those and invisible in throughput alone.

WHAT IT REPORTS, and this is the deliverable:

  - the distribution: mean, sd, min, max, and the middle 90%
  - whether the variation DRIFTS with time or is memoryless - split-half means
    and a first-vs-last comparison. Drift is fixable by settling; memoryless
    scatter is only fixable by averaging more.
  - a RESOLUTION TABLE: the smallest true difference detectable at n = 3, 5, 10,
    20, 40 for each probe length. That table is what tells a future measurement
    whether it is worth running at all.

A campaign that knows its own noise floor can say "no difference detected" and
mean it. One that does not can only ever say "the numbers differed".
"""

import json
import math
import os
import subprocess
import sys
import threading
import time
import urllib.request
import gpu_lock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "lib"))
import paths


MODEL_NAME = "Qwen3.8-27B-UD-IQ4_XS.gguf"


def model_file():
    """The weights, resolved when a run needs them - never at import.

    paths.model_path searches campaign.json's models/model_dir, $MODEL_DIR and
    <repo>/models/, and exits naming all four when the file is on none of
    them. The literal it replaces was one user's LM Studio directory.
    """
    return paths.model_path(MODEL_NAME)


def server_bin():
    """llama-server, resolved when a run needs it - never at import.

    $LLAMA_SERVER still overrides; paths.llama_bin honours it and exits with
    an actionable message when nothing resolves. Deliberately not a module
    constant: --help must not require a toolchain to be installed.
    """
    return paths.llama_bin("llama-server")


OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "..", "results", "qwen38-27b-blind", "data", "register")
PORT = 1245
BASE = "http://127.0.0.1:%d" % PORT

CTX = 32768
RUNS = [("short", 700, 100), ("long", 3000, 30)]

PROMPT = ("Write a single self-contained JavaScript module that implements a "
          "fixed-window rate limiter with a pluggable clock, a per-key limit, and "
          "an eviction sweep that runs at most once per window. Include JSDoc on "
          "every exported symbol, plus a short usage example. Code only.")


def smi(q):
    o = subprocess.run(["nvidia-smi", "--query-gpu=" + q,
                        "--format=csv,noheader,nounits"],
                       capture_output=True, text=True, timeout=15).stdout
    return o.strip().splitlines()[0]


class Sampler(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.rows, self.stop = [], False

    def run(self):
        while not self.stop:
            try:
                v = smi("clocks.sm,temperature.gpu,power.draw")
                sm, t, p = [float(x) for x in v.split(",")]
                self.rows.append((time.time(), sm, t, p))
            except Exception:
                pass
            time.sleep(0.5)


def post(payload, timeout=1800):
    req = urllib.request.Request(BASE + "/v1/chat/completions",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def start(logpath):
    args = [server_bin(), "-m", model_file(), "--alias", "qwen/qwen3.8-27b",
            "-ngl", "99", "-c", str(CTX), "--parallel", "1",
            "-ctk", "q8_0", "-ctv", "q8_0",
            "--spec-type", "draft-mtp", "--spec-draft-n-max", "4",
            "--spec-draft-p-min", "0.75",
            "--jinja", "--reasoning", "off",
            "--host", "127.0.0.1", "--port", str(PORT)]
    lf = open(logpath, "w", encoding="utf-8", errors="replace")
    return gpu_lock.serve(args, stdout=lf, stderr=subprocess.STDOUT), lf


def wait(p, timeout=900):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if p.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(BASE + "/health", timeout=2) as r:
                if json.loads(r.read().decode()).get("status") == "ok":
                    return True
        except Exception:
            pass
        time.sleep(2)
    return False


def stop_srv(p, lf):
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


def probe(npredict, sampler):
    t0 = time.time()
    r = post({"model": "qwen/qwen3.8-27b", "temperature": 0, "top_k": 1,
              "max_tokens": npredict, "cache_prompt": True,
              "messages": [{"role": "user", "content": PROMPT}]})
    t1 = time.time()
    t = r.get("timings", {})
    win = [x for x in sampler.rows if t0 <= x[0] <= t1]
    dn, da, pn = t.get("draft_n"), t.get("draft_n_accepted"), t.get("predicted_n")
    return {"t": round(t0, 2), "decode_tps": round(t.get("predicted_per_second", 0), 3),
            "predicted_n": pn,
            "acceptance": round(da / dn, 3) if dn else None,
            "sm_mhz": round(sum(x[1] for x in win) / len(win)) if win else None,
            "temp": round(sum(x[2] for x in win) / len(win), 1) if win else None,
            "watt": round(sum(x[3] for x in win) / len(win), 1) if win else None}


def stats(v):
    n = len(v)
    m = sum(v) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in v) / (n - 1)) if n > 1 else 0.0
    s = sorted(v)
    return {"n": n, "mean": round(m, 2), "sd": round(sd, 3),
            "cv_pct": round(sd / m * 100, 2),
            "min": round(s[0], 2), "max": round(s[-1], 2),
            "p05": round(s[int(0.05 * n)], 2), "p95": round(s[int(0.95 * n)], 2),
            "range_pct": round((s[-1] - s[0]) / m * 100, 1)}


USAGE = """\
What can this machine actually measure? The instrument's own noise floor: one
configuration, one server load, nothing varying but time.

    python scripts/bench/resolution-floor.py

Positional arguments: none. The conditions are pinned in this file -
UD-IQ4_XS, draft-mtp n4/p0.75, greedy, -c 32768, and two probe lengths on that
one load: 100 short probes of 700 tokens and 30 long probes of 3,000.

Environment, all optional:
  LLAMA_SERVER / LLAMA_DIR       where llama-server is (scripts/lib/paths.py)
  MODEL_DIR                      directory holding the .gguf weights
  MEASURED_INFERENCE_DRY_RUN=1   gpu_lock refuses the card, so nothing loads
  MEASURED_INFERENCE_MEM_CAP_GB  per-job commit cap (gpu_lock)
  MEASURED_INFERENCE_LOCK        the one-job lockfile (gpu_lock)

Takes the card: one llama-server through gpu_lock.serve for the whole run.
Writes results/qwen38-27b-blind/data/register/resolution-floor.json: the
distribution, a drift-against-memoryless split, and the resolution table at
n = 3, 5, 10, 20, 40 for each probe length.
"""


def main():
    # A help request must never start work. This script has no argument parser,
    # so without this line --help falls through and loads a model (rule 20).
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        print(USAGE.rstrip())
        return

    os.makedirs(OUT, exist_ok=True)
    logdir = os.path.join(OUT, "resolution-logs")
    os.makedirs(logdir, exist_ok=True)
    print("ONE config, ONE server load, nothing varying but time.")
    print("UD-IQ4_XS, n4/p0.75, greedy (temp 0 / top_k 1), -c %d\n" % CTX)

    p, lf = start(os.path.join(logdir, "resolution.log"))
    if not wait(p):
        print("SERVER FAILED"); stop_srv(p, lf); sys.exit(1)
    s = Sampler(); s.start()
    out = {}
    try:
        for name, npred, count in RUNS:
            print("=== %s probes: %d x %d predicted tokens ===" % (name, count, npred))
            rows = []
            for i in range(count):
                r = probe(npred, s)
                rows.append(r)
                if (i + 1) % 10 == 0 or i == 0:
                    print("  %3d/%d  %7.2f t/s  %4s MHz  %4s C  %5s W"
                          % (i + 1, count, r["decode_tps"], r["sm_mhz"],
                             r["temp"], r["watt"]))
            out[name] = rows
    finally:
        s.stop = True
        s.join(timeout=2)
        stop_srv(p, lf)

    report = {"date": time.strftime("%Y-%m-%d %H:%M"), "ctx": CTX,
              "model": os.path.basename(model_file()), "prompt": PROMPT, "runs": {}}
    print("\n%-7s %-6s %-9s %-8s %-8s %-16s %s"
          % ("probe", "n", "mean t/s", "sd", "cv", "min-max", "range"))
    for name, npred, _ in RUNS:
        rows = out.get(name) or []
        if not rows:
            continue
        v = [r["decode_tps"] for r in rows]
        st = stats(v)
        half = len(v) // 2
        drift = (sum(v[half:]) / len(v[half:])) - (sum(v[:half]) / len(v[:half]))
        st["drift_2nd_minus_1st"] = round(drift, 2)
        st["drift_pct"] = round(drift / st["mean"] * 100, 2)
        report["runs"][name] = {"npredict": npred, "stats": st, "probes": rows}
        print("%-7s %-6s %-9s %-8s %-8s %-16s %s"
              % (name, st["n"], st["mean"], st["sd"], "%.2f%%" % st["cv_pct"],
                 "%.1f-%.1f" % (st["min"], st["max"]), "%.1f%%" % st["range_pct"]))
        print("        drift, 2nd half minus 1st: %+.2f t/s (%+.2f%%)  <- %s"
              % (drift, st["drift_pct"],
                 "settling would fix this" if abs(st["drift_pct"]) > 1.0
                 else "memoryless scatter: only averaging fixes it"))

    print("\n=== RESOLUTION TABLE: smallest true difference detectable ===")
    print("    (2 standard errors of a difference between two arms of size n)")
    print("%-8s %s" % ("probe", "  ".join("n=%-7d" % n for n in (3, 5, 10, 20, 40))))
    for name in report["runs"]:
        cv = report["runs"][name]["stats"]["cv_pct"]
        cells = []
        for n in (3, 5, 10, 20, 40):
            mde = 2 * math.sqrt(2) * cv / math.sqrt(n)
            cells.append("%.1f%%    " % mde)
        print("%-8s %s" % (name, "  ".join(cells)))
        report["runs"][name]["mde_pct"] = {
            str(n): round(2 * math.sqrt(2) * cv / math.sqrt(n), 2)
            for n in (3, 5, 10, 20, 40)}
    print("\n  A comparison whose true effect is smaller than its cell cannot be")
    print("  resolved by that design, however many decimal places it prints.")

    f = os.path.join(OUT, "resolution-floor.json")
    json.dump(report, open(f, "w", encoding="utf-8"), indent=1)
    print("\n-> %s" % f)


if __name__ == "__main__":
    main()
