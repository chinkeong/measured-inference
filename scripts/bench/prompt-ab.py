"""Two prompts, ONE server load, interleaved. Which one is the odd number?

    python prompt-ab.py

WHY. Two scripts measure what should be the same arm - UD-IQ4_XS, drafter
n4/p0.75, greedy, -c 32768, 700 predicted tokens, byte-identical server flags -
and disagree:

    refarm.py         74.36 t/s   over 16 separate loads, range 1.1%
    sampling-bridge   64.32 t/s   acceptance 0.926, mean draft length 2.53

15.6% apart. Sixteen loads of the reference say the machine is not the
variable: between-load scatter is 0.26%. The remaining difference between the
two scripts is the PROMPT TEXT, and nothing else.

But the obvious mechanism does not fit. Rule 11 says mean draft length predicts
throughput, and the two agree on it: 2.54 against 2.53. Accepted-per-pass is
0.899 x 2.54 = 2.28 against 0.926 x 2.53 = 2.34, which predicts the
sampling-bridge prompt should be about 2% FASTER, not 15% slower.

So either rule 11 has a limit nobody has mapped, or one of the two readings was
taken under a condition its script does not record. Guessing between those from
existing logs is how this campaign has previously talked itself into two wrong
mechanisms in one message. This measures instead.

DESIGN. One load. Both prompts. Alternating A B A B so any drift in the load
hits both equally, which no cross-script comparison can claim. n=8 each after
one discarded warmup per prompt. Everything except the prompt string is shared
by construction - same process, same flags, same sampler, same probe function.

If A and B differ here, the prompt causes it and rule 11 needs an amendment.
If they do not, the 64.32 was a condition neither script recorded, and the
finding is about the harness rather than the machine.
"""

import json
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import refarm
import gpu_lock

PORT = 1249
BASE = "http://127.0.0.1:%d" % PORT
NPREDICT = 700
N = 8

# A: the reference arm's prompt, the one reading 74.36 over 16 loads
A = refarm.REF_PROMPT


def bridge_prompt():
    """Read B out of sampling-bridge.py rather than retyping it.

    A retyped prompt is a different prompt, and that is the whole variable
    under test here.
    """
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sampling-bridge.py")
    src = open(p, encoding="utf-8").read()
    i = src.index("\nPROMPT = ") + 1
    j = src.index("\n\n", i)
    ns = {}
    exec(compile(src[i:j], "<prompt>", "exec"), ns)
    return ns["PROMPT"]


B = bridge_prompt()


def post(payload, timeout=1800):
    req = urllib.request.Request(BASE + "/v1/chat/completions",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def start(logpath):
    args = [refarm.SERVER, "-m", refarm.REF_MODEL, "--alias", "qwen/qwen3.8-27b"] + \
        refarm.REF_FLAGS + ["--host", "127.0.0.1", "--port", str(PORT)]
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


def probe(prompt, sampler):
    t0 = time.time()
    r = post({"model": "qwen/qwen3.8-27b", "temperature": 0, "top_k": 1,
              "max_tokens": NPREDICT, "cache_prompt": True,
              "messages": [{"role": "user", "content": prompt}]})
    t1 = time.time()
    t = r.get("timings", {})
    win = [x for x in sampler.rows if t0 <= x[0] <= t1]
    dn, da, pn = t.get("draft_n"), t.get("draft_n_accepted"), t.get("predicted_n")
    return {"decode_tps": round(t.get("predicted_per_second", 0), 3),
            "predicted_n": pn, "prompt_n": t.get("prompt_n"),
            "prefill_ms": round(t.get("prompt_ms", 0), 1),
            "decode_ms": round(t.get("predicted_ms", 0), 1),
            "draft_n": dn, "draft_accepted": da,
            "acceptance": round(da / dn, 3) if dn else None,
            "draft_len": round(dn / (pn - da), 2) if dn and pn and (pn - da) else None,
            "accepted_per_pass": round(da / (pn - da), 2) if pn and da and (pn - da) else None,
            "sm_mhz": round(sum(x[1] for x in win) / len(win)) if win else None,
            "temp": round(sum(x[2] for x in win) / len(win), 1) if win else None,
            "finish": (r.get("choices") or [{}])[0].get("finish_reason")}


def main():
    os.makedirs(refarm.OUT, exist_ok=True)
    logdir = os.path.join(refarm.OUT, "promptab-logs")
    os.makedirs(logdir, exist_ok=True)
    print("ONE load. Two prompts. Alternating. Everything else identical.\n")
    print("A (refarm)         ...%s" % A[-60:])
    print("B (sampling-bridge)...%s" % B[-60:])
    print("A == B ? %s\n" % (A == B))

    p, lf = start(os.path.join(logdir, "promptab.log"))
    if not wait(p):
        print("SERVER FAILED")
        refarm.stop_srv(p, lf)
        sys.exit(1)
    s = refarm.Sampler()
    s.start()
    rows = {"A": [], "B": []}
    try:
        probe(A, s)                      # one discarded warmup each
        probe(B, s)
        for i in range(N):
            for tag, pr in (("A", A), ("B", B)):
                r = probe(pr, s)
                rows[tag].append(r)
            print("  %d/%d   A %6.2f t/s (acc %.3f len %.2f pn %s)   "
                  "B %6.2f t/s (acc %.3f len %.2f pn %s)"
                  % (i + 1, N,
                     rows["A"][-1]["decode_tps"], rows["A"][-1]["acceptance"] or 0,
                     rows["A"][-1]["draft_len"] or 0, rows["A"][-1]["predicted_n"],
                     rows["B"][-1]["decode_tps"], rows["B"][-1]["acceptance"] or 0,
                     rows["B"][-1]["draft_len"] or 0, rows["B"][-1]["predicted_n"]))
    finally:
        s.stop = True
        s.join(timeout=2)
        refarm.stop_srv(p, lf)

    rep = {"date": time.strftime("%Y-%m-%d %H:%M"), "npredict": NPREDICT, "n": N,
           "prompt_a": A, "prompt_b": B, "rows": rows, "summary": {}}
    print()
    for tag in ("A", "B"):
        v = [r["decode_tps"] for r in rows[tag]]
        st = refarm.stats(v)
        acc = [r["acceptance"] for r in rows[tag] if r["acceptance"]]
        dl = [r["draft_len"] for r in rows[tag] if r["draft_len"]]
        app = [r["accepted_per_pass"] for r in rows[tag] if r["accepted_per_pass"]]
        pn = [r["predicted_n"] for r in rows[tag] if r["predicted_n"]]
        st["acceptance"] = round(sum(acc) / len(acc), 3) if acc else None
        st["draft_len"] = round(sum(dl) / len(dl), 2) if dl else None
        st["accepted_per_pass"] = round(sum(app) / len(app), 2) if app else None
        st["predicted_n"] = round(sum(pn) / len(pn)) if pn else None
        st["prompt_n"] = rows[tag][0]["prompt_n"]
        st["finish"] = rows[tag][0]["finish"]
        rep["summary"][tag] = st
        print("%-3s n=%-3s %7.2f t/s  sd %-6s cv %-7s acceptance %-6s draft_len %-5s "
              "acc/pass %-5s prompt_n %-5s predicted_n %-5s finish %s"
              % (tag, st["n"], st["mean"], st["sd"], "%.2f%%" % st["cv_pct"],
                 st["acceptance"], st["draft_len"], st["accepted_per_pass"],
                 st["prompt_n"], st["predicted_n"], st["finish"]))

    a, b = rep["summary"]["A"], rep["summary"]["B"]
    gap = (a["mean"] - b["mean"]) / b["mean"] * 100
    rep["gap_pct"] = round(gap, 2)
    print("\nA - B = %+.2f t/s (%+.1f%%)" % (a["mean"] - b["mean"], gap))
    print("cross-script gap that prompted this: refarm 74.36 vs bridge 64.32 = +15.6%")
    if abs(gap) < 2:
        print("\nVERDICT: the two prompts are the SAME SPEED in one load.")
        print("  The prompt does not explain the 15.6%. Whatever produced 64.32 is")
        print("  a condition the sampling-bridge run did not record, and the")
        print("  reference arm's 74.36 over 16 loads is the trustworthy number.")
    else:
        print("\nVERDICT: the prompt alone moves this arm by %+.1f%% inside one load."
              % gap)
        if a["draft_len"] and b["draft_len"] and \
                abs(a["draft_len"] - b["draft_len"]) / b["draft_len"] < 0.05:
            print("  And it does it at EQUAL mean draft length (%.2f vs %.2f), which"
                  % (a["draft_len"], b["draft_len"]))
            print("  rule 11 does not predict. Rule 11 needs an amendment naming what")
            print("  else moves with content.")

    f = os.path.join(refarm.OUT, "prompt-ab.json")
    json.dump(rep, open(f, "w", encoding="utf-8"), indent=1)
    print("\n-> %s" % f)


if __name__ == "__main__":
    main()
