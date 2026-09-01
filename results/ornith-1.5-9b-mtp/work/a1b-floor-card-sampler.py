#!/usr/bin/env python3
"""Re-measure the Stage-1 floors under the model card's sampler.

WHY. The repaired rule-20 loop scan (task A1, re-run 2026-09-01) says the
greedy floors were taken from degenerate generations:

    Q8_0    LOOP   n4_worst_ttr 0.2833   83.37 t/s
    Q4_K_M  hint   n4_worst_ttr 0.3250  118.96 t/s
    IQ2_M   hint   n4_worst_ttr 0.3333  131.28 t/s

Rule 20: spot-read long greedy output for repetition BEFORE trusting its tokens
or timings. The published floors -- 78.30 / 118.38 / 131.30 -- are those
timings. A number taken from a looping generation is not a speed measurement of
anything a reader will do, which is what loop-scan.json's own `why` field says.

The fix is not to delete the greedy numbers. It is to measure the SAME probe
under the sampler the model card actually recommends and publish both, labelled
(rule 2: a best case ships labelled as one, with the condition that produced
it). The card's preset is temp 1.0 / top_p 0.95 / top_k 20 / presence_penalty
1.5 -- and presence_penalty is precisely the anti-repetition knob, which is why
this pair is the right comparison rather than an arbitrary second sampler.

Same prompt, same cap, same server flags as A1, one probe per arm. Cheap.
"""
import json, os, sys, time

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

CARD = {"temperature": 1.0, "top_p": 0.95, "top_k": 20, "presence_penalty": 1.5}
OUT = os.path.join(REPO, "results", "ornith-1.5-9b-mtp", "data",
                   "floor-card-sampler.json")


def main():
    out = {"_schema": "floor-card-sampler v1",
           "why": ("the greedy floors were measured on generations the repaired "
                   "rule-20 scan calls LOOP (Q8_0) and hint (Q4_K_M, IQ2_M); "
                   "this is the same probe under the card's own sampler"),
           "sampler": CARD, "arms": {}}
    for label in ("Q8_0", "Q4_K_M", "IQ2_M"):
        gguf = R.paths.model_path(label)
        p, fh = R.serve(gguf, R.SPEC_OFF, "a1b-%s" % label)
        if not p:
            out["arms"][label] = {"error": "server never healthy"}
            continue
        try:
            r = R.ask(R.CODE, 700, **CARD) if _accepts_kwargs() else _ask(R, CARD)
            s = loopdet.signals(r["full"])
            out["arms"][label] = {
                "t_s": r["timings"].get("predicted_per_second"),
                "predicted_n": r["timings"].get("predicted_n"),
                "finish": r["finish"], "chars": len(r["full"]),
                "reasoning_chars": len(r["reasoning"]),
                "content_chars": len(r["text"]),
                "verdict": loopdet.verdict(s),
                "signals": {k: round(v, 4) for k, v in s.items()}}
            open(os.path.join(HERE, "a1b-floor-%s.txt" % label), "w").write(r["full"])
            print("[%s] %s: %.2f t/s  %s" % (
                time.strftime("%H:%M:%S"), label,
                r["timings"].get("predicted_per_second") or 0,
                loopdet.verdict(s)), flush=True)
        finally:
            R.stop(p, fh)
        json.dump(out, open(OUT, "w"), indent=1)
    json.dump(out, open(OUT, "w"), indent=1)
    print("wrote %s" % OUT)


def _accepts_kwargs():
    return False


def _ask(R, sampler):
    """A1's ask() hard-codes greedy in its body; issue the same request with the
    card's sampler instead, through the same endpoint and timeout."""
    import json as _j, urllib.request
    body = {"model": "x", "messages": [{"role": "user", "content": R.CODE}],
            "max_tokens": 700, "stream": False, "cache_prompt": False}
    body.update(sampler)
    req = urllib.request.Request(
        "http://127.0.0.1:%d/v1/chat/completions" % R.PORT,
        data=_j.dumps(body).encode(), headers={"Content-Type": "application/json"})
    resp = _j.load(urllib.request.urlopen(req, timeout=3600))
    ch = (resp.get("choices") or [{}])[0]
    msg = ch.get("message", {}) or {}
    content = msg.get("content") or ""
    reasoning = msg.get("reasoning_content") or ""
    return {"text": content, "reasoning": reasoning,
            "full": (reasoning + "\n\n" + content) if reasoning else content,
            "finish": ch.get("finish_reason"),
            "timings": resp.get("timings") or {}}


if __name__ == "__main__":
    main()
