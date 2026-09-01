#!/usr/bin/env python3
"""Re-take the Stage-1 floors, BOTH samplers, in ONE sweep.

WHY. The repaired rule-20 scan says the published floors were timed on
degenerate generations: Q8_0 LOOP (n4_worst_ttr 0.2833), Q4_K_M and IQ2_M hint,
at 83.37 / 118.96 / 131.28 t/s -- the published 78.30 / 118.38 / 131.30. Rule 20
puts that check before the timings are trusted; it had never run.

DESIGN, and why it is not just "measure it again":

  BOTH SAMPLERS IN ONE SWEEP (rule 30). greedy (temp 0 / top_k 1) is what
  produced the loop; the card's preset (temp 1.0 / top_p 0.95 / top_k 20 /
  presence_penalty 1.5) carries the anti-repetition term that should suppress
  it. Measuring them in separate sweeps would make the comparison illegal --
  this rig has two throughput levels ~13% apart and nothing predicts which. Same
  server, same load, alternating, so the pair is comparable even if the absolute
  level is not.

  DISCARD THE FIRST PROBE PER LOAD (rule 12). Ramping clocks read up to 45% low.

  ALTERNATE ARM ORDER (rule 30) so position in the sweep cannot be mistaken for
  a property of the arm.

  RECORD THE HOST WITH EVERY PROBE (rule 27, rule 3). This box is NOT quiet --
  Steam, Chrome, a second Claude session and a foreign 3.9 GB test binary are
  resident, and the operator has accepted that. Rule 27's penalty was measured
  for a busy HOST, not a busy GPU, so it applies here even with the card idle.
  A number whose conditions are recorded is publishable as a labelled best/worst
  case (rule 2); a number whose conditions were not written down is not
  recoverable at any price (rule 28). So every probe carries SM clock, board
  power, temperature and the 1-minute load average.
"""
import json, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "scripts", "lib"))
sys.path.insert(0, os.path.join(REPO, "scripts", "bench"))
import runner as R                                              # noqa: E402
import importlib.util                                           # noqa: E402

spec = importlib.util.spec_from_file_location(
    "loopdet", os.path.join(REPO, "scripts", "bench", "loop-detect.py"))
loopdet = importlib.util.module_from_spec(spec); spec.loader.exec_module(loopdet)

GREEDY = {"temperature": 0.0, "top_p": 1.0, "top_k": 1, "presence_penalty": 0.0}
CARD = {"temperature": 1.0, "top_p": 0.95, "top_k": 20, "presence_penalty": 1.5}
SAMPLERS = [("greedy", GREEDY), ("card", CARD)]
ARMS = ["Q8_0", "Q4_K_M", "IQ2_M"]
REPS = 4                      # first is discarded (rule 12)
OUT = os.path.join(REPO, "results", "ornith-1.5-9b-mtp", "data",
                   "floor-sampler-pair.json")


def telemetry():
    try:
        q = subprocess.run(
            ["nvidia-smi", "--query-gpu=clocks.sm,power.draw,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10).stdout.strip().split(",")
        sm, pw, tp = float(q[0]), float(q[1]), float(q[2])
    except Exception:
        sm = pw = tp = None
    try:
        load1 = float(open("/proc/loadavg").read().split()[0])
    except Exception:
        load1 = None
    return {"clocks_sm_mhz": sm, "power_w": pw, "temp_c": tp, "load1": load1}


def ask(sampler, max_tokens=700):
    import json as _j, urllib.request
    body = {"model": "x", "messages": [{"role": "user", "content": R.CODE}],
            "max_tokens": max_tokens, "stream": False, "cache_prompt": False}
    body.update(sampler)
    req = urllib.request.Request(
        "http://127.0.0.1:%d/v1/chat/completions" % R.PORT,
        data=_j.dumps(body).encode(), headers={"Content-Type": "application/json"})
    resp = _j.load(urllib.request.urlopen(req, timeout=3600))
    ch = (resp.get("choices") or [{}])[0]
    msg = ch.get("message", {}) or {}
    content, reasoning = msg.get("content") or "", msg.get("reasoning_content") or ""
    return {"text": content, "reasoning": reasoning,
            "full": (reasoning + "\n\n" + content) if reasoning else content,
            "finish": ch.get("finish_reason"), "timings": resp.get("timings") or {}}


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def main():
    out = {"_schema": "floor-sampler-pair v1",
           "why": ("the published floors were timed on generations the repaired "
                   "rule-20 scan calls LOOP (Q8_0) and hint (Q4_K_M, IQ2_M); "
                   "this re-takes them with BOTH samplers in one sweep"),
           "host_not_quiet": ("accepted by the operator 2026-09-01: Steam, "
                              "Chrome, a second Claude session and a foreign "
                              "3.9 GB test binary resident; GPU itself idle. "
                              "Rule 27's -5.4% mean / -24.0% worst was measured "
                              "for a busy HOST, so it applies. Per-probe SM "
                              "clock, power, temperature and load1 recorded."),
           "protocol": {"reps": REPS, "first_discarded": "rule 12",
                        "order": "alternating (rule 30)",
                        "samplers": {"greedy": GREEDY, "card": CARD}},
           "arms": {}}
    if os.path.exists(OUT):
        try:
            out = json.load(open(OUT))
        except Exception:
            pass
    for i, label in enumerate(ARMS):
        if out["arms"].get(label, {}).get("done"):
            log("%s already done -- skipping" % label); continue
        gguf = R.paths.model_path(label)
        p, fh = R.serve(gguf, R.SPEC_OFF, "a1b-%s" % label)
        if not p:
            out["arms"][label] = {"error": "server never healthy"}; continue
        rec = {"probes": [], "done": False}
        try:
            # alternate which sampler leads, by arm index (rule 30)
            order = SAMPLERS if i % 2 == 0 else SAMPLERS[::-1]
            for rep in range(REPS):
                for sname, s in order:
                    tel = telemetry()
                    r = ask(s)
                    sig = loopdet.signals(r["full"])
                    v = loopdet.verdict(sig)
                    rec["probes"].append({
                        "rep": rep, "sampler": sname,
                        "discarded": rep == 0,
                        "t_s": r["timings"].get("predicted_per_second"),
                        "predicted_n": r["timings"].get("predicted_n"),
                        "finish": r["finish"], "chars": len(r["full"]),
                        "reasoning_chars": len(r["reasoning"]),
                        "content_chars": len(r["text"]),
                        "verdict": v, "signals": {k: round(x, 4) for k, x in sig.items()},
                        "telemetry": tel})
                    log("  %s rep%d %-6s %.2f t/s  %-7s  sm=%s load=%s%s" % (
                        label, rep, sname, r["timings"].get("predicted_per_second") or 0,
                        v[0], tel["clocks_sm_mhz"], tel["load1"],
                        "  (discarded, rule 12)" if rep == 0 else ""))
                    if rep == REPS - 1 and sname == order[-1][0]:
                        open(os.path.join(HERE, "a1b-floor-%s-%s.txt" % (label, sname)),
                             "w").write(r["full"])
            rec["done"] = True
        finally:
            R.stop(p, fh)
        # summarise the kept probes, per sampler
        for sname, _ in SAMPLERS:
            kept = [q for q in rec["probes"]
                    if q["sampler"] == sname and not q["discarded"] and q["t_s"]]
            if kept:
                ts = sorted(q["t_s"] for q in kept)
                rec.setdefault("summary", {})[sname] = {
                    "n": len(ts), "min": round(ts[0], 2), "max": round(ts[-1], 2),
                    "median": round(ts[len(ts) // 2], 2),
                    "verdicts": sorted({q["verdict"][0] for q in kept})}
        out["arms"][label] = rec
        json.dump(out, open(OUT, "w"), indent=1)
    json.dump(out, open(OUT, "w"), indent=1)
    log("wrote %s" % OUT)
    for label, rec in out["arms"].items():
        for sname, sm in (rec.get("summary") or {}).items():
            log("%-8s %-6s median %.2f t/s (n=%d, %.2f-%.2f)  %s" % (
                label, sname, sm["median"], sm["n"], sm["min"], sm["max"],
                ",".join(sm["verdicts"])))


if __name__ == "__main__":
    main()
