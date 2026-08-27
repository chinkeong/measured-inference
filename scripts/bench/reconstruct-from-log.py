#!/usr/bin/env python3
"""Rebuild a scored result artefact from a bench.py progress log.

    reconstruct-from-log.py --log <path> --dataset GPQA-Diamond --out <path.json>

WHY THIS EXISTS. bench.py checkpoints after every DATASET:

    # persist after every dataset so an interrupted run loses at most
    # the dataset in flight, never the finished ones

That is real protection for a seven-dataset suite and NONE AT ALL for a run of
one dataset, which is the shape every anchor run takes. A 198-question GPQA run
stopped at question 100 would write nothing, and ten hours of measurement would
survive only as console text.

The console text is in fact enough. Every prompt prints its own outcome:

    prompt 31/198: 11277 tok, 55.7 tok/s, accept_len 2.38, CORRECT
    prompt 29/198: 30000 tok, 52.4 tok/s, accept_len 2.38, wrong (truncated)

so the score, the token distribution, the truncation count and the acceptance
rate can all be recovered exactly. What CANNOT be recovered from the log is the
condition block - sampler, context, server flags, effort - so this script takes
those as arguments and records them explicitly rather than inventing them. A
reconstructed artefact is marked as reconstructed, and names the log it came
from, so it is never mistaken for one the harness wrote itself.

TRUNCATION IS REPORTED SEPARATELY AND NOT ABSORBED. bench.py scores a truncated
response 0.0, which is correct - an answer that ran out of context is not a
right answer - but it means a run against a small context window carries a
penalty that is not a quality signal. Both figures are emitted: the score as
scored, and the score over the subset that was not truncated.
"""
import argparse, io, json, os, re, statistics as st, sys, time

LINE = re.compile(
    r"prompt (\d+)/(\d+):\s*(\d+) tok,\s*([0-9.]+) tok/s"
    r"(?:,\s*accept_len ([0-9.]+))?,\s*(CORRECT|wrong)(\s*\(truncated\))?",
    re.IGNORECASE)


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0, 0.0)
    p = k / float(n)
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4.0 * n * n)) ** 0.5) / d
    return (100 * p, 100 * max(0.0, c - h), 100 * min(1.0, c + h))


def parse(path):
    rows = []
    for ln in io.open(path, encoding="utf-8", errors="replace"):
        m = LINE.search(ln)
        if not m:
            continue
        rows.append({
            "index": int(m.group(1)),
            "planned_n": int(m.group(2)),
            "tokens": int(m.group(3)),
            "tok_s": float(m.group(4)),
            "accept_len": float(m.group(5)) if m.group(5) else None,
            "correct": m.group(6).upper() == "CORRECT",
            "truncated": bool(m.group(7)),
        })
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True)
    ap.add_argument("--dataset", default="GPQA-Diamond")
    ap.add_argument("--out", required=True)
    ap.add_argument("--model-label", default="Qwen3.8-27B-UD-IQ4_XS")
    ap.add_argument("--published", type=float, default=None,
                    help="a published figure to compare against, e.g. 89.2")
    ap.add_argument("--conditions", default=None,
                    help="JSON object of the run's conditions; recorded verbatim")
    a = ap.parse_args()

    rows = parse(a.log)
    if not rows:
        sys.exit("no prompt lines matched in %s - nothing to reconstruct" % a.log)

    n = len(rows)
    k = sum(1 for r in rows if r["correct"])
    trunc = [r for r in rows if r["truncated"]]
    kept = [r for r in rows if not r["truncated"]]
    k_kept = sum(1 for r in kept if r["correct"])
    tok = [r["tokens"] for r in rows]
    acc = [r["accept_len"] for r in rows if r["accept_len"]]

    p, lo, hi = wilson(k, n)
    pk, lok, hik = wilson(k_kept, len(kept))

    out = {
        "reconstructed": True,
        "reconstructed_from": os.path.abspath(a.log),
        "reconstructed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "why": "bench.py checkpoints once per DATASET; a single-dataset run "
               "writes nothing until the last question, so an interrupted run "
               "survives only in its log",
        "model_label": a.model_label,
        "dataset": a.dataset,
        "planned_n": rows[0]["planned_n"],
        "completed_n": n,
        "partial": n < rows[0]["planned_n"],
        "score": {
            "correct": k, "n": n, "pct": round(p, 2),
            "wilson95": [round(lo, 2), round(hi, 2)],
        },
        # The same score with truncated questions removed. Truncation is a
        # context-window artefact, not a quality signal, so both are published
        # and neither is presented alone.
        "score_excluding_truncated": {
            "correct": k_kept, "n": len(kept), "pct": round(pk, 2),
            "wilson95": [round(lok, 2), round(hik, 2)],
        },
        "truncated_n": len(trunc),
        "truncated_pct": round(100.0 * len(trunc) / n, 2),
        "truncated_indices": [r["index"] for r in trunc],
        "tokens": {
            "mean": round(st.mean(tok), 1),
            "median": st.median(tok),
            "min": min(tok), "max": max(tok),
        },
        "accept_len_mean": round(st.mean(acc), 3) if acc else None,
        "tok_s_mean": round(st.mean([r["tok_s"] for r in rows]), 2),
        "rows": rows,
    }
    if a.conditions:
        out["conditions"] = json.loads(a.conditions)
    if a.published is not None:
        out["published_reference"] = {
            "value": a.published,
            "inside_wilson95": lo <= a.published <= hi,
            "note": "a published figure this run can be compared against. It "
                    "detects a BROKEN harness; it does not validate one - the "
                    "option order is the mirror's, the published value is "
                    "vendor self-reported, and this rig serves a fraction of "
                    "the model's native context.",
        }

    io.open(a.out, "w", encoding="utf-8").write(
        json.dumps(out, indent=1, ensure_ascii=False))

    print("reconstructed %d of %d questions from %s"
          % (n, out["planned_n"], os.path.basename(a.log)))
    print("  score              %d/%d = %.1f%%   95%% CI %.1f - %.1f"
          % (k, n, p, lo, hi))
    print("  excluding truncated %d/%d = %.1f%%   95%% CI %.1f - %.1f"
          % (k_kept, len(kept), pk, lok, hik))
    print("  truncated          %d (%.1f%%) at indices %s"
          % (len(trunc), out["truncated_pct"], out["truncated_indices"][:12]))
    print("  tokens             mean %.0f, median %.0f, max %d"
          % (out["tokens"]["mean"], out["tokens"]["median"], out["tokens"]["max"]))
    if a.published is not None:
        verdict = ("INSIDE" if out["published_reference"]["inside_wilson95"]
                   else "OUTSIDE")
        print("  published %.1f is %s the 95%% interval" % (a.published, verdict))
    print("wrote %s" % a.out)
