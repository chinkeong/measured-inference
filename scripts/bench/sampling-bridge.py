"""Register entry 1: are this page's speed numbers usable at the sampling it ships?

    python sampling-bridge.py

THE PROBLEM, in the register's own words. Every speed number on this page was
taken at `temperature 0 / top_k 1`, while the recipes leave sampling to the
client and ship the model card's `temperature 1.0 / top_p 0.95 / top_k 20`.
Acceptance is a property of which token the drafter has to guess, and sampling
changes which token that is - so sampling moves acceptance directly. **Every
speculative band on this page is therefore greedy-only and, as the entry puts
it, non-transferable.** That is a large caveat sitting under most of the speed
chapter.

WHAT CLOSES IT. The drafting sweep plus one depth point, re-run at the shipped
sampling, reported against the greedy band as a TRANSFER FACTOR - a single
multiplier a reader can apply to any greedy figure on the page.

THE DESIGN, and the one thing that makes it cheap. Sampling is a REQUEST
parameter, not a load-time flag: the same server answers both ways. Only the
drafter needs a reload. So three server loads cover six arms:

    drafter off        greedy | shipped sampling
    n4/p0.75           greedy | shipped sampling
    n10/p0.5           greedy | shipped sampling

plus one deep-filled arm, because acceptance rises with depth on this model and
a shallow-only transfer factor would not be safe to apply to the depth figures.

n DEPENDS ON THE SAMPLER, RAISED AFTER THE FIRST RUN. Greedy is deterministic and
three probes measure the machine; temperature 1.0 is not. The first run at n=3
produced sampled arms spreading 15-25% - 54.5, 60.5 and 69.7 t/s on one of them,
with every probe hitting the token cap, so it is genuine run-to-run variance and
not an outlier or an answer-length artefact. At temperature 1.0 the model writes
DIFFERENT TEXT each time and different text drafts differently. Every effect
being measured was smaller than that spread, so n=3 could not resolve any of
them. Fifteen brings the standard error near 2-3% of the mean, which is below
the effects in question.

WHAT IS REPORTED. Decode t/s, acceptance and mean draft length for each cell,
then sampled/greedy as a ratio per drafter setting. If the ratio is flat across
drafter settings, one number transfers the whole page. If it is not, the entry
closes with a table instead of a factor - which is still an answer, and a more
honest one than the caveat it replaces.
"""

import json
import math
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import refarm   # the reference arm: Sampler, smi()
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
PORT = 1244
BASE = "http://127.0.0.1:%d" % PORT

CTX, NPREDICT = 32768, 700
# n depends on the SAMPLER, because only one of them is non-deterministic.
# The first run's own standard deviations say greedy resolves at n=1-5 and the
# sampled arms need up to 39 for a 2% standard error. Running greedy 40 times
# would be pure waste, so each sampler gets the n it actually needs.
N_BY_SAMPLER = {"greedy": 5, "shipped": 40}
DEEP_FILL = 28000          # the page's own middle depth point

PROMPT = ("Write a single self-contained JavaScript module that implements a "
          "fixed-window rate limiter with a pluggable clock, a per-key limit, and "
          "an eviction sweep that runs at most once per window. Include JSDoc on "
          "every exported symbol. Code only, no explanation.")

# greedy is what the page measured; shipped is what the recipes actually run
SAMPLERS = [
    ("greedy", {"temperature": 0, "top_k": 1}),
    ("shipped", {"temperature": 1.0, "top_p": 0.95, "top_k": 20, "min_p": 0.0}),
]
DRAFTERS = [
    ("none", ["--spec-type", "none"]),
    ("n4/p0.75", ["--spec-type", "draft-mtp", "--spec-draft-n-max", "4",
                  "--spec-draft-p-min", "0.75"]),
    ("n10/p0.5", ["--spec-type", "draft-mtp", "--spec-draft-n-max", "10",
                  "--spec-draft-p-min", "0.5"]),
]


def filler(target):
    lines = ["Reference notes. Read them, then do the task at the end."]
    for i in range(1, int(target / 58.7) + 1):
        frag = format((i * 48271) % 1048573, "x")
        lines.append(
            "Note %d: subsystem alpha-%d reported latency %d ms on shard %d, retry "
            "budget %d, digest fragment %s, remark: threshold crossed only when the "
            "moving median over window %d exceeded baseline by %d percent."
            % (i, (i * 7) % 97, (17 * i) % 993, i % 13, (3 * i) % 29, frag,
               (5 * i) % 47, (11 * i) % 83))
    lines.append("TASK: " + PROMPT)
    return "\n".join(lines)


def post(payload, timeout=1800):
    req = urllib.request.Request(BASE + "/v1/chat/completions",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def start(flags, logpath):
    args = [server_bin(), "-m", model_file(), "--alias", "qwen/qwen3.8-27b",
            "-ngl", "99", "-c", str(CTX), "--parallel", "1",
            "-ctk", "q8_0", "-ctv", "q8_0", "--jinja", "--reasoning", "off",
            "--host", "127.0.0.1", "--port", str(PORT)] + flags
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


def stop(p, lf):
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
    # wait for the card to actually release, rather than assuming four seconds
    # was enough: the next load starts either way, and a load that starts while
    # the previous one is still holding VRAM is a condition nothing records.
    for _ in range(20):
        time.sleep(1)
        try:
            if float(refarm.smi("memory.used")) < 2500:
                return
        except Exception:
            pass


GPU = None   # a refarm.Sampler, started in main()


def probe(sampler, prompt):
    """One request, with the machine state it ran under.

    WHY THE GPU COLUMNS EXIST NOW. On 2026-08-25 this script reported 64.32 t/s
    for an arm that `refarm.py` reads at 74.36 over sixteen separate loads and
    that `prompt-ab.py` reads at 75.53 on this script's own prompt. Nothing has
    reproduced the 64.32, and nothing can now diagnose it either, because this
    was the one script in scripts/bench that recorded no clock, no power and no
    temperature. Every other script here samples nvidia-smi per probe; this one
    slept instead. A reading without its machine state is not a measurement,
    it is an anecdote with a decimal point.
    """
    t0 = time.time()
    body = {"model": "qwen/qwen3.8-27b", "max_tokens": NPREDICT,
            "cache_prompt": True,
            "messages": [{"role": "user", "content": prompt}]}
    body.update(sampler)
    r = post(body)
    t1 = time.time()
    t = r.get("timings", {})
    dn, da, pn = t.get("draft_n"), t.get("draft_n_accepted"), t.get("predicted_n")
    win = [x for x in GPU.rows if t0 <= x[0] <= t1] if GPU else []
    return {"decode_tps": round(t.get("predicted_per_second", 0), 2),
            "predicted_n": pn, "prompt_n": t.get("prompt_n"),
            "acceptance": round(da / dn, 3) if dn else None,
            # rule 11: draft length, not acceptance, is the throughput predictor
            "draft_len": (round(dn / (pn - da), 2)
                          if dn and pn and da is not None and (pn - da) > 0 else None),
            "sm_mhz": round(sum(x[1] for x in win) / len(win)) if win else None,
            "temp": round(sum(x[2] for x in win) / len(win), 1) if win else None,
            "watt": round(sum(x[3] for x in win) / len(win), 1) if win else None}


def settle(sampler, prompt, tol=2.0, need=3, cap=12):
    """Probe until the reading stops climbing, and report how long that took.

    CASE STUDY, 2026-08-25 - THE EXPLANATION IN THIS DOCSTRING WAS WRONG.
    It used to read: "A first run of this script read 64.32 t/s for a
    DETERMINISTIC arm that a later run read 74.08 - 15% apart ... The difference
    was how much work the card had done beforehand: 6 probes against 45 ...
    after a fresh SERVER LOAD the card needs far longer."

    That was inferred, not measured, and measurement refuted it. `refarm.py`
    loaded the identical arm sixteen times and read 74.8 / 74.3 / 74.0 / 74.1 /
    74.4 / 74.8 / 74.6 / 74.6 / 74.4 / 74.4 / 74.3 / 74.2 / 74.1 / 74.3 / 74.3 /
    74.3 - a range of 1.1%, with the FIRST kept probe of each load already at
    full speed. `resolution-floor.py` read 75.96 on probe one of a hundred.
    There is no long post-load warm-up on this machine. The 64.32 has never
    reproduced, and the condition that produced it went unrecorded because this
    script logged no clock, power or temperature - which is what the GPU columns
    added to probe() on the same day are for.

    So settling is kept, but for the honest reason: it costs little and it
    RECORDS how many probes the reading took to stop moving, which is a
    measurement rather than an assumption. It is not here because a fresh load
    is known to be slow.

    So this does not guess a number. It probes until `need` consecutive readings
    sit within `tol` per cent of each other, and returns the count so the
    settling time itself becomes a measured quantity rather than an assumption.
    """
    hist = []
    for i in range(cap):
        r = probe(sampler, prompt)
        hist.append(r["decode_tps"])
        if len(hist) >= need:
            w = hist[-need:]
            if (max(w) - min(w)) / (sum(w) / len(w)) * 100 <= tol:
                return i + 1, hist
        time.sleep(1)
    return cap, hist


def cell(sname, sampler, prompt, label, settled_after=None):
    n = N_BY_SAMPLER[sname]
    if settled_after is None:
        k, hist = settle(sampler, prompt)
        print("    settling: %d probes to stabilise  (%s)"
              % (k, " ".join("%.1f" % x for x in hist)))
    time.sleep(2)
    got = []
    for i in range(n):
        if i:
            time.sleep(1)
        got.append(probe(sampler, prompt))
    tps = [g["decode_tps"] for g in got]
    acc = [g["acceptance"] for g in got if g["acceptance"] is not None]
    dl = [g["draft_len"] for g in got if g["draft_len"] is not None]
    mean = sum(tps) / len(tps)
    sd = (math.sqrt(sum((x - mean) ** 2 for x in tps) / (len(tps) - 1))
          if len(tps) > 1 else 0.0)
    se = sd / math.sqrt(len(tps))
    row = {"sampler": sname, "arm": label, "n": n, "mean_tps": round(mean, 2),
           "sd": round(sd, 2), "se": round(se, 3),
           "se_pct": round(se / mean * 100, 2),
           "spread_pct": round((max(tps) - min(tps)) / mean * 100, 1),
           "acceptance": round(sum(acc) / len(acc), 3) if acc else None,
           "draft_len": round(sum(dl) / len(dl), 2) if dl else None,
           "probes": got}
    print("    %-8s n=%-3d %7.2f t/s  +/-%.2f SE (%.1f%%)  spread %4.1f%%  "
          "acceptance %-6s draft_len %s"
          % (sname, n, mean, se, row["se_pct"], row["spread_pct"],
             row["acceptance"], row["draft_len"]))
    return row


USAGE = """\
Are this page's speed numbers usable at the sampling it ships? Three drafters
by two samplers, plus one deep-filled arm, reported as a transfer factor.

    python scripts/bench/sampling-bridge.py

Positional arguments: none. The conditions are pinned in this file - UD-IQ4_XS
at -c 32768, 700 predicted tokens, drafters none / n4-p0.75 / n10-p0.5,
samplers greedy (n=5) and shipped temperature 1.0 / top_p 0.95 / top_k 20
(n=40), and one arm deep-filled to 28,000 tokens.

Environment, all optional:
  LLAMA_SERVER / LLAMA_DIR       where llama-server is (scripts/lib/paths.py)
  MODEL_DIR                      directory holding the .gguf weights
  MEASURED_INFERENCE_DRY_RUN=1   gpu_lock refuses the card, so nothing loads
  MEASURED_INFERENCE_MEM_CAP_GB  per-job commit cap (gpu_lock)
  MEASURED_INFERENCE_LOCK        the one-job lockfile (gpu_lock)

Takes the card: one llama-server per drafter through gpu_lock.serve.
Writes results/qwen38-27b-blind/data/register/sampling-bridge.json.
"""


def main():
    # A help request must never start work. This script has no argument parser,
    # so without this line --help falls through and loads a model (rule 20).
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        print(USAGE.rstrip())
        return

    global GPU
    GPU = refarm.Sampler()
    GPU.start()
    os.makedirs(OUT, exist_ok=True)
    logdir = os.path.join(OUT, "sampling-logs")
    os.makedirs(logdir, exist_ok=True)
    deep = filler(DEEP_FILL)
    rows = []

    for dname, dflags in DRAFTERS:
        print("\n=== drafter %s | shallow ===" % dname)
        p, lf = start(dflags, os.path.join(logdir, "d-%s.log" % dname.replace("/", "-")))
        if not wait(p):
            print("  SERVER FAILED"); stop(p, lf); continue
        try:
            first = True
            for sname, sampler in SAMPLERS:
                rows.append(dict(cell(sname, sampler, PROMPT, dname,
                                      settled_after=None if first else True),
                                 depth="shallow"))
                first = False
        finally:
            stop(p, lf)

    # one depth point, because acceptance rises with depth on this model and a
    # shallow-only factor would not be safe to apply to the depth figures
    print("\n=== drafter n4/p0.75 | deep (~%d tokens) ===" % DEEP_FILL)
    p, lf = start(DRAFTERS[1][1], os.path.join(logdir, "deep.log"))
    if wait(p):
        try:
            first = True
            for sname, sampler in SAMPLERS:
                rows.append(dict(cell(sname, sampler, deep, "n4/p0.75",
                                      settled_after=None if first else True),
                                 depth="deep"))
                first = False
        finally:
            stop(p, lf)
    else:
        print("  SERVER FAILED"); stop(p, lf)

    print("\n%-12s %-8s %-10s %-10s %-11s %s"
          % ("arm", "depth", "greedy", "shipped", "transfer", "acceptance g->s"))
    factors = []
    for dname, _ in DRAFTERS:
        for depth in ("shallow", "deep"):
            g = next((r for r in rows if r["arm"] == dname and r["sampler"] == "greedy"
                      and r["depth"] == depth), None)
            s = next((r for r in rows if r["arm"] == dname and r["sampler"] == "shipped"
                      and r["depth"] == depth), None)
            if not (g and s):
                continue
            f = s["mean_tps"] / g["mean_tps"]
            # combined standard error of the difference, which is the right
            # yardstick - not either arm's SE on its own
            comb = math.sqrt(g["se"] ** 2 + s["se"] ** 2)
            diff = abs(s["mean_tps"] - g["mean_tps"])
            sigmas = diff / comb if comb else 0
            resolved = sigmas >= 2.0
            factors.append((dname, depth, f, resolved, sigmas))
            print("%-12s %-8s %-10s %-10s %-11s %-6s %s"
                  % (dname, depth, g["mean_tps"], s["mean_tps"], "%.3fx" % f,
                     "%.1f sd" % sigmas,
                     "RESOLVED" if resolved else "not resolved (inside noise)"))

    if factors:
        vals = [f for _, _, f, _, _ in factors]
        lo, hi = min(vals), max(vals)
        print("\n  transfer factor spans %.3f to %.3f across %d cells" % (lo, hi, len(vals)))
        if (hi - lo) / (sum(vals) / len(vals)) < 0.05:
            print("  -> FLAT within 5%%: one factor of %.3fx transfers the whole page."
                  % (sum(vals) / len(vals)))
        else:
            print("  -> NOT flat. The entry closes with a table, not a single factor,")
            print("     which is a more honest answer than the caveat it replaces.")

    out = os.path.join(OUT, "sampling-bridge.json")
    json.dump({"date": time.strftime("%Y-%m-%d %H:%M"), "ctx": CTX,
               "npredict": NPREDICT, "n_by_sampler": N_BY_SAMPLER,
               "deep_fill_target": DEEP_FILL,
               "samplers": {k: v for k, v in SAMPLERS}, "prompt": PROMPT,
               "rows": rows,
               "factors": [{"arm": a, "depth": d, "factor": round(f, 4),
                            "resolved": bool(r), "sigmas": round(sg, 2)}
                           for a, d, f, r, sg in factors]},
              open(out, "w", encoding="utf-8"), indent=1)
    print("\n-> %s" % out)


if __name__ == "__main__":
    main()
