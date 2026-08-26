"""Register entry 10: what does capping the board's power actually cost?

    python power-cap-arms.py

WHY IT WAS OPEN. This entry sat unmeasured for the whole campaign for one
reason: `nvidia-smi -pl` needs an elevated shell, and the probe that tried it
returned "insufficient permissions". Everything else in the energy chapter is
measured; this row said "not measured on this machine" because of a privilege,
not a hardware limit.

WHAT IT ANSWERS. Every energy figure on the page is at the stock 350 W cap, and
the page's own finding is that nothing it tested lowers wattage - the drafter
saves energy purely by finishing sooner, at the same draw. The power cap is the
one knob that lowers the draw directly. The question is what it costs:

  if throughput falls LESS than power does, capping is an efficiency win
  if throughput falls MORE than power does, capping is worse than useless

THREE ARMS: 350 W (stock), 300 W, 250 W. Same model, same flags, same prompt,
one server load per arm, minutes apart.

WHAT IS SAMPLED. Board power every 250 ms across the whole request, plus the
server's own timings so decode is separated from prefill. The prompt is short
on purpose (~60 tokens) so prefill is a rounding error and the energy figure is
a DECODE figure rather than a blend. SM clock and temperature are sampled too,
because a cap works by lowering clocks and the mechanism should be visible
rather than inferred.

SAFETY. The cap is a PERSISTENT hardware setting: it outlives this process, and
leaving the card at 250 W would silently degrade every later measurement on this
machine and everything else the user runs. The default is read BEFORE anything
changes and restored in a finally block, and the restore is VERIFIED by reading
the value back rather than trusted from an exit code.
"""

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

SERVER = os.environ.get("LLAMA_SERVER", r"E:\AI\llama.cpp\llama-server.exe")
LMS = r"C:\Users\chink\.lmstudio\models"
MODEL = os.path.join(LMS, r"unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-IQ4_XS.gguf")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "..", "results", "qwen38-27b-blind", "data", "register")
PORT = 1243
BASE = "http://127.0.0.1:%d" % PORT

CAPS = [350, 300, 250]
CTX, NPREDICT, SETTLED = 32768, 700, 3

PROMPT = ("Write a single self-contained JavaScript module that implements a "
          "fixed-window rate limiter with a pluggable clock, a per-key limit, and "
          "an eviction sweep that runs at most once per window. Include JSDoc on "
          "every exported symbol. Code only, no explanation.")


def smi(query):
    o = subprocess.run(["nvidia-smi", "--query-gpu=" + query,
                        "--format=csv,noheader,nounits"],
                       capture_output=True, text=True, timeout=15).stdout
    return o.strip().splitlines()[0]


def set_cap(w):
    r = subprocess.run(["nvidia-smi", "-pl", str(w)],
                       capture_output=True, text=True, timeout=30)
    time.sleep(1)
    got = float(smi("power.limit").split(",")[0])
    msg = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
    return abs(got - w) < 1.0, got, (msg[0] if msg else "")


class Sampler(threading.Thread):
    """Power, clock and temperature every 250 ms. A cap works by lowering
    clocks, so sampling them shows the mechanism instead of inferring it."""

    def __init__(self):
        super().__init__(daemon=True)
        self.rows, self.stop = [], False

    def run(self):
        while not self.stop:
            try:
                v = smi("power.draw,clocks.sm,clocks.mem,temperature.gpu,"
                        "utilization.gpu,utilization.memory,"
                        "clocks_event_reasons.active").split(",")
                p, sm, mem, t, u, um = [float(x) for x in v[:6]]
                # The mask is the whole point of a cap experiment: it is the
                # only field that says whether the cap actually BOUND during
                # an arm. Without it a cap that never engaged and a cap that
                # engaged constantly produce the same table.
                try:
                    mask = int(v[6].strip(), 16)
                except Exception:
                    mask = -1
                self.rows.append((time.time(), p, sm, mem, t, u, um, mask))
            except Exception:
                pass
            time.sleep(0.25)


def post(payload, timeout=1800):
    req = urllib.request.Request(BASE + "/v1/chat/completions",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def start(logpath):
    args = [SERVER, "-m", MODEL, "--alias", "qwen/qwen3.8-27b",
            "-ngl", "99", "-c", str(CTX), "--parallel", "1",
            "-ctk", "q8_0", "-ctv", "q8_0",
            "--spec-type", "draft-mtp", "--spec-draft-n-max", "4",
            "--spec-draft-p-min", "0.75",
            "--jinja", "--reasoning", "off",
            "--host", "127.0.0.1", "--port", str(PORT)]
    lf = open(logpath, "w", encoding="utf-8", errors="replace")
    return subprocess.Popen(args, stdout=lf, stderr=subprocess.STDOUT), lf


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


def probe():
    t0 = time.time()
    r = post({"model": "qwen/qwen3.8-27b", "temperature": 0, "top_k": 1,
              "max_tokens": NPREDICT,
              "messages": [{"role": "user", "content": PROMPT}]})
    wall = time.time() - t0
    t = r.get("timings", {})
    return {"decode_tps": round(t.get("predicted_per_second", 0), 2),
            "predicted_n": t.get("predicted_n"), "prompt_n": t.get("prompt_n"),
            "prompt_ms": t.get("prompt_ms"), "predicted_ms": t.get("predicted_ms"),
            "wall_s": round(wall, 2), "t_start": t0, "t_end": t0 + wall}


def main():
    if not os.path.exists(MODEL):
        sys.exit("missing model: %s" % MODEL)
    default_w = float(smi("power.default_limit").split(",")[0])
    print("card: %s" % smi("name"))
    print("default limit %.0f W, currently %.0f W"
          % (default_w, float(smi("power.limit").split(",")[0])))
    print("arms: %s W\n" % ", ".join(str(c) for c in CAPS))
    os.makedirs(OUT, exist_ok=True)
    logdir = os.path.join(OUT, "powercap-logs")
    os.makedirs(logdir, exist_ok=True)

    rows = []
    try:
        for cap in CAPS:
            ok, got, msg = set_cap(cap)
            print("=== cap %d W ===  set ok=%s, card reads %.0f W" % (cap, ok, got))
            if not ok:
                rows.append({"cap": cap, "failed": "could not set: %s" % msg})
                continue
            p, lf = start(os.path.join(logdir, "cap%d.log" % cap))
            if not wait(p):
                print("  SERVER FAILED TO START")
                stop_srv(p, lf)
                rows.append({"cap": cap, "failed": "server"})
                continue
            got_probes = []
            try:
                probe()                       # rule 12: warmup, discarded
                time.sleep(4)
                for i in range(SETTLED):
                    if i:
                        time.sleep(3)
                    s = Sampler()
                    s.start()
                    r = probe()
                    time.sleep(0.4)
                    s.stop = True
                    s.join(timeout=2)
                    win = [x for x in s.rows if r["t_start"] <= x[0] <= r["t_end"]]
                    if win:
                        r["mean_w"] = round(sum(x[1] for x in win) / len(win), 1)
                        r["peak_w"] = round(max(x[1] for x in win), 1)
                        r["mean_sm_mhz"] = round(sum(x[2] for x in win) / len(win))
                        r["mean_temp"] = round(sum(x[4] for x in win) / len(win), 1)
                        r["mean_util_mem"] = round(sum(x[6] for x in win) / len(win), 1)
                        # Record what BOUND during the arm, not just what it
                        # drew. A cap arm whose mask never shows SwPowerCap did
                        # not test a cap at all - it tested a workload that
                        # stayed under it, which is exactly how this campaign's
                        # published cap curve came to describe a regime the
                        # real workload is not in.
                        # Busy is decided on UTILISATION (x[5]), not on the
                        # mask. NVML's ClocksEventReasonNone is 0x0 - busy and
                        # unconstrained - so `mask > 0` would throw away every
                        # sample where the cap did NOT bind, pinning
                        # pct_power_capped at 100.0 and making it impossible
                        # for this script to report the one outcome it exists
                        # to detect: an arm whose cap never engaged.
                        busy = [x for x in win
                                if x[7] >= 0 and not x[7] & 0x0001 and x[5] > 5.0]
                        if busy:
                            nb = float(len(busy))
                            r["n_busy"] = len(busy)
                            r["pct_power_capped"] = round(
                                100.0 * sum(1 for x in busy if x[7] & 0x0004) / nb, 1)
                            # Software and hardware thermal slowdown are kept
                            # apart: the software bit is a driver-managed clock
                            # step, the hardware bit means the part protected
                            # itself. Merging them would report a benign
                            # condition and an alarming one as one number.
                            r["pct_thermal_sw"] = round(
                                100.0 * sum(1 for x in busy if x[7] & 0x0020) / nb, 1)
                            r["pct_thermal_hw"] = round(
                                100.0 * sum(1 for x in busy if x[7] & 0x0040) / nb, 1)
                            r["pct_unconstrained"] = round(
                                100.0 * sum(1 for x in busy if x[7] == 0) / nb, 1)
                        r["samples"] = len(win)
                        dec_s = (r["predicted_ms"] or 0) / 1000.0
                        r["j_per_tok"] = round(
                            r["mean_w"] * dec_s / max(r["predicted_n"] or 1, 1), 3)
                    got_probes.append(r)
                    print("  probe %d: %6.2f t/s  %6.1f W  %4s MHz  %4s C  %s J/tok"
                          % (i + 1, r["decode_tps"], r.get("mean_w", 0),
                             r.get("mean_sm_mhz", "?"), r.get("mean_temp", "?"),
                             r.get("j_per_tok", "?")))
            finally:
                stop_srv(p, lf)
            vals = lambda k: [x[k] for x in got_probes if x.get(k) is not None]
            mean = lambda k: (round(sum(vals(k)) / len(vals(k)), 3) if vals(k) else None)
            # The constraint fields are aggregated to arm level too. They were
            # computed per probe and left there on first writing, so the
            # summary table and every consumer that reads `rows` saw a J/token
            # with no statement of what limited it - which is the defect the
            # mask was added to close. An arm whose cap never bound is the
            # single most important thing this script can report.
            rows.append({"cap": cap, "mean_tps": mean("decode_tps"),
                         "mean_w": mean("mean_w"),
                         "peak_w": (max(vals("peak_w")) if vals("peak_w") else None),
                         "mean_sm_mhz": mean("mean_sm_mhz"),
                         "mean_temp": mean("mean_temp"),
                         "mean_util_mem": mean("mean_util_mem"),
                         "pct_power_capped": mean("pct_power_capped"),
                         "pct_thermal_sw": mean("pct_thermal_sw"),
                         "pct_thermal_hw": mean("pct_thermal_hw"),
                         "pct_unconstrained": mean("pct_unconstrained"),
                         "cap_bound": (None if mean("pct_power_capped") is None
                                       else mean("pct_power_capped") >= 50.0),
                         "j_per_tok": mean("j_per_tok"), "probes": got_probes})
            pc = mean("pct_power_capped")
            if pc is not None:
                print("  arm %s W: power-capped %.1f%% of busy samples, "
                      "unconstrained %.1f%%, mem util %.0f%%%s"
                      % (cap, pc, mean("pct_unconstrained") or 0.0,
                         mean("mean_util_mem") or 0.0,
                         "" if pc >= 50.0 else
                         "   <-- THE CAP DID NOT BIND: this arm did not test a cap"))
    finally:
        ok, got, _ = set_cap(int(default_w))
        print("\nRESTORE to default: ok=%s, card now reads %.0f W (default %.0f)"
              % (ok, got, default_w))
        if not ok:
            print("*** WARNING: cap NOT restored. Run: nvidia-smi -pl %d"
                  % int(default_w))

    good = [r for r in rows if not r.get("failed")]
    if len(good) >= 2:
        base = good[0]
        print("\n%-7s %-9s %-8s %-9s %-7s %-9s %s"
              % ("cap W", "decode", "mean W", "SM MHz", "temp", "J/token", "against stock"))
        for r in good:
            d_t = (r["mean_tps"] - base["mean_tps"]) / base["mean_tps"] * 100
            d_w = (r["mean_w"] - base["mean_w"]) / base["mean_w"] * 100
            d_j = (r["j_per_tok"] - base["j_per_tok"]) / base["j_per_tok"] * 100
            print("%-7s %-9s %-8s %-9s %-7s %-9s %+.1f%% t/s | %+.1f%% W | %+.1f%% J/tok"
                  % (r["cap"], r["mean_tps"], r["mean_w"], r["mean_sm_mhz"],
                     r["mean_temp"], r["j_per_tok"], d_t, d_w, d_j))
        print("\n  A cap is worth taking when the throughput cost is SMALLER than")
        print("  the power saving - that is what the J/token column decides.")

    out = os.path.join(OUT, "power-cap-arms.json")
    json.dump({"date": time.strftime("%Y-%m-%d %H:%M"), "card": smi("name"),
               "default_limit_w": default_w, "ctx": CTX, "npredict": NPREDICT,
               "settled": SETTLED, "prompt": PROMPT, "arms": rows},
              open(out, "w", encoding="utf-8"), indent=1)
    print("\n-> %s" % out)


main()
