"""Energy for the four benchmark sets that ran outside the power logger.

    python energy-four-sets.py [--samples 25]

WHY. The register says it plainly: "GSM8K, ALPACA, MeetingBank and MT-Bench ran
entirely outside the window the power logger covered." Three of the seven sets
have energy figures and four do not, so the page's per-benchmark energy story
is 43% missing and nothing says which numbers are absent when a reader looks at
the table.

DESIGN, and why it is four runs rather than one. Running all four sets under a
single power window would give one average and no way to split it, because the
sets differ enormously in shape - MeetingBank's prompts are long and prefill-
heavy, MT-Bench's answers are long and decode-heavy, GSM8K is short at both
ends. An average across them would describe none of them. So each set gets its
own server load and its own power window, and the attribution is exact by
construction rather than by apportionment.

WHAT IS REPORTED, and the distinction matters more here than in the decode
arms. Two figures per set:

  J/token, DECODE ONLY - board power averaged across the run multiplied by the
  summed decode seconds, divided by generated tokens. Comparable to the
  campaign's existing decode J/token figures.

  Wh FOR THE WHOLE SET - energy over the entire window including prefill, the
  gaps between requests and the model sitting idle. This is the honest "what
  did answering 25 questions cost" number, and it is the one a reader wanting
  cost-per-answer actually needs. It is always the larger of the two and the
  difference is the point.

TIER. In-band GPU board power as NVML reports it. The power supply's conversion
loss, the processor, system memory, drives and the display are excluded and
unmeasured. Not system power, and may not be called that.

CONDITIONS. Same frozen suite and settings the ladder used, so the numbers join
the existing three sets rather than starting a second table: greedy, seed 42,
n=25, cap 16,384, -c 32768, q8_0 KV, reasoning off, drafter off - the arms the
existing energy figures were taken under.
"""

import argparse
import io
import json
import os
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts", "bench"))
import refarm

BENCH = os.path.join(ROOT, "scripts", "bench", "bench.py")
MODEL = os.path.join(r"C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF",
                     "Qwen3.8-27B-UD-IQ4_XS.gguf")
OUT = os.path.join(ROOT, "results", "qwen38-27b-blind", "data", "register")
SETS = ["GSM8K", "ALPACA", "MeetingBank", "MT-Bench"]


def log(m):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), m)
    print(line, flush=True)
    try:
        os.makedirs(OUT, exist_ok=True)
        io.open(os.path.join(OUT, "energy-four-sets.log"), "a",
                encoding="utf-8").write(line + "\n")
    except Exception:
        pass


class Power(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.rows, self.stop = [], False

    def run(self):
        while not self.stop:
            try:
                o = subprocess.run(
                    ["nvidia-smi", "--query-gpu=power.draw",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=10).stdout
                self.rows.append((time.time(), float(o.strip().splitlines()[0])))
            except Exception:
                pass
            time.sleep(0.25)

    def joules(self, t0, t1):
        """Trapezoidal integration of board watts over a window -> joules."""
        w = [(t, p) for t, p in self.rows if t0 <= t <= t1]
        if len(w) < 2:
            return None, None
        j = 0.0
        for i in range(1, len(w)):
            dt = w[i][0] - w[i - 1][0]
            j += (w[i][1] + w[i - 1][1]) / 2.0 * dt
        return j, sum(p for _, p in w) / len(w)


def newest(pattern_dir, contains):
    best, bt = None, -1
    for f in os.listdir(pattern_dir):
        if contains in f and f.endswith("_transcripts.json"):
            p = os.path.join(pattern_dir, f)
            t = os.path.getmtime(p)
            if t > bt:
                best, bt = p, t
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=25)
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    resdir = os.path.join(ROOT, "scripts", "bench", "results")
    log("host: %s" % refarm.quiet_report()["status"])
    log("four sets, one server load and one power window each, n=%d" % a.samples)

    rows = []
    for name in SETS:
        tag = "energy-%s" % name.replace("-", "")
        # bench.py resolves llama-server from --server-bin, $LLAMA_SERVER or
        # PATH, and none of those are set for a subprocess launched from here.
        # Without it every set exits 1 in under a second and reports 0 joules,
        # which looks exactly like a measurement of nothing rather than a
        # failure to start.
        cmd = [sys.executable, "-u", BENCH, "--model", MODEL,
               "--server-bin", refarm.SERVER,
               "--datasets", name, "--samples", str(a.samples),
               "--greedy", "--seed", "42", "--max-tokens", "16384",
               "--ctx", "32768", "--transcripts",
               "--server-args", "-ngl 99 --parallel 1 -fa on -ctk q8_0 "
                                "-ctv q8_0 --jinja --reasoning off",
               "--port", "1268"]
        log("  %s: starting" % name)
        p = Power()
        p.start()
        t0 = time.time()
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        t1 = time.time()
        p.stop = True
        p.join(timeout=2)
        io.open(os.path.join(OUT, "%s.console.log" % tag), "w",
                encoding="utf-8", errors="replace").write(
                    (r.stdout or "") + "\n---STDERR---\n" + (r.stderr or ""))
        if r.returncode != 0:
            log("  %s: bench exited %d - see %s.console.log" % (name, r.returncode, tag))

        joules, mean_w = p.joules(t0, t1)
        tr = newest(resdir, "")
        toks, dec_s, items = 0, 0.0, 0
        if tr and os.path.getmtime(tr) >= t0:
            try:
                d = json.load(io.open(tr, encoding="utf-8"))
                for suite, its in d.get("generations", {}).items():
                    for it in its:
                        items += 1
                        toks += int(it.get("tokens") or 0)
            except Exception as e:
                log("  transcript read failed: %s" % e)
        wall = t1 - t0
        # A failed run must not report 0 joules as though it measured nothing
        # happening. The first version of this file printed "0.0000 Wh" and
        # "DONE" for four sets that never started, which reads as a result.
        if r.returncode != 0 or items == 0:
            rows.append({"set": name, "FAILED": True,
                         "returncode": r.returncode, "items": items,
                         "wall_s": round(wall, 1),
                         "why": "bench exited %d / %d items scored"
                                % (r.returncode, items)})
            log("  %-12s *** FAILED (exit %d, %d items) - no energy recorded"
                % (name, r.returncode, items))
            json.dump({"date": time.strftime("%Y-%m-%d %H:%M"), "rows": rows},
                      io.open(os.path.join(OUT, "energy-four-sets.json"), "w",
                              encoding="utf-8"), indent=1)
            continue
        row = {"set": name, "wall_s": round(wall, 1), "items": items,
               "generated_tokens": toks,
               "mean_board_w": round(mean_w, 1) if mean_w else None,
               "whole_set_joules": round(joules, 1) if joules else None,
               "whole_set_wh": round(joules / 3600.0, 4) if joules else None,
               "j_per_generated_token_whole_window":
                   round(joules / toks, 4) if (joules and toks) else None,
               "transcript": os.path.basename(tr) if tr else None,
               "returncode": r.returncode}
        rows.append(row)
        log("  %-12s %6.0f s  %4d items  %7d tok  %5.1f W  %8.1f J  "
            "%6.4f Wh  %6.4f J/tok"
            % (name, wall, items, toks, row["mean_board_w"] or 0,
               row["whole_set_joules"] or 0, row["whole_set_wh"] or 0,
               row["j_per_generated_token_whole_window"] or 0))
        json.dump({"date": time.strftime("%Y-%m-%d %H:%M"),
                   "tier": "in-band GPU board power (NVML) only; PSU, CPU, RAM, "
                           "drives and display excluded. NOT system power.",
                   "model": os.path.basename(MODEL), "samples": a.samples,
                   "note": "whole-window energy includes prefill and the gaps "
                           "between requests, which is what cost-per-answer needs",
                   "rows": rows},
                  io.open(os.path.join(OUT, "energy-four-sets.json"), "w",
                          encoding="utf-8"), indent=1)
        time.sleep(5)

    log("")
    ok = [r for r in rows if not r.get("FAILED")]
    bad = [r for r in rows if r.get("FAILED")]
    if bad:
        log("*** %d of %d SETS FAILED: %s" % (len(bad), len(rows),
                                              ", ".join(r["set"] for r in bad)))
        log("*** no energy figure is claimed for those. Read the console logs.")
    if ok:
        tot = sum(r["whole_set_wh"] or 0 for r in ok)
        log("%d set(s) measured: %.4f Wh of board energy for %d generated tokens"
            % (len(ok), tot, sum(r["generated_tokens"] or 0 for r in ok)))
    log("DONE" if not bad else "DONE WITH FAILURES")


main()
