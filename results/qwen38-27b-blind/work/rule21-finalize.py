"""Re-grade every rule-21 arm from its saved transcripts with the CURRENT
scorers, and relabel each arm by its effort level for the comparison table.

    python rule21-finalize.py <run.json> <transcripts.json> <label> <out.json>

Two reasons this exists:

1. The MATH-500 normalization fix landed after the `low` arm had already run.
   Re-grading all three arms offline from transcripts — instead of only the one
   that ran on the old code — guarantees every cell in the table came out of
   the same scorer. Greedy decoding means the generations themselves are
   untouched, so this costs no GPU time.
2. render_table.py keys comparison columns on `model_label`, and all three arms
   are the same GGUF. Without a relabel the table renders three identically
   named columns.

Scores, truncation counts and the composite Mean are recomputed; timings,
machine fingerprint, suite hash and settings are carried over untouched.
"""

import json
import os
import sys

BENCH = r"E:\AI\measured-inference\scripts\bench"
sys.path.insert(0, BENCH)

import datasets_io as D  # noqa: E402


def main():
    run_path, tr_path, label, out_path = sys.argv[1:5]
    suite_path = os.path.join(BENCH, "suites", "rule21-n25.json")
    with open(run_path, encoding="utf-8") as f:
        run = json.load(f)
    with open(tr_path, encoding="utf-8") as f:
        tr = json.load(f)
    with open(suite_path, encoding="utf-8") as f:
        suite = json.load(f)

    max_tokens = run["settings"]["max_tokens"]
    opts = D.ScoreOptions(exec_enabled=True, judge=None)
    changed = []

    for ds, recs in tr["generations"].items():
        if ds not in run["results"] or not D.is_scored(ds, opts):
            continue
        scores, trunc = [], 0
        for r in recs:
            truncated = r["tokens"] >= max_tokens
            trunc += truncated
            ref = suite["answers"][ds][r["index"]]
            sc = 0.0 if truncated else D.score_response(
                ds, r["response"], ref, prompt=r.get("prompt"), opts=opts)
            if sc is not None:
                scores.append(sc)
        if not scores:
            continue
        m = run["results"][ds]
        old = m.get("score")
        m["accuracy"] = sum(scores) / len(scores)
        m["score"] = round(m["accuracy"] * 100, 1)
        m["graded_n"] = len(scores)
        m["truncated_n"] = trunc
        m["scorer"] = D.scorer_name(ds, opts)
        if old is not None and abs(old - m["score"]) > 0.05:
            changed.append("%s %.1f -> %.1f" % (ds, old, m["score"]))

    order = [d for d in run["datasets"] if d in run["results"]]
    run["composite"] = D.composite_index(
        {d: m["score"] for d, m in run["results"].items() if "score" in m},
        order=order,
        excluded={d: m["unscored_reason"] for d, m in run["results"].items()
                  if "unscored_reason" in m})
    run["model_label"] = label
    run["regraded"] = {
        "from_transcripts": os.path.basename(tr_path),
        "why": "all arms re-graded offline with one scorer version "
               "(MATH-500 LaTeX normalization fix); generations untouched",
        "score_changes": changed or "none",
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(run, f, indent=2)
    print("%-8s Mean %.1f  changes: %s" % (label, run["composite"]["mean"],
                                           changed or "none"))
    print("  wrote", out_path)


main()
