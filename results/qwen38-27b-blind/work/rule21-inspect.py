"""Inspect one rule-21 arm's transcripts: extraction sanity + offline re-scoring.

    python rule21-inspect.py <transcripts.json> <out.txt> [suite.json]

Re-runs every scorer from the saved generations and compares the result with
the score bench.py recorded at run time. That is the offline path rule 21 asks
for: a scorer bug can be fixed and the arm re-graded without re-running the
model. Also reports, per dataset: truncations, empty answers, whether the
answer marker the scorer needs was present at all, and what it extracted.
"""

import io
import json
import os
import sys

BENCH = r"E:\AI\measured-inference\scripts\bench"
sys.path.insert(0, BENCH)

import datasets_io as D  # noqa: E402

MAX_TOKENS = 16384          # overridden by argv[4] for the raised-cap re-runs


def show(s, n=220):
    s = (s or "").replace("\n", "\\n")
    return s[:n] + ("..." if len(s) > n else "")


def main():
    global MAX_TOKENS
    tpath, opath = sys.argv[1], sys.argv[2]
    suite_path = sys.argv[3] if len(sys.argv) > 3 else os.path.join(
        BENCH, "suites", "rule21-n25.json")
    if len(sys.argv) > 4:
        MAX_TOKENS = int(sys.argv[4])
    with open(tpath, encoding="utf-8") as f:
        tr = json.load(f)
    with open(suite_path, encoding="utf-8") as f:
        suite = json.load(f)
    answers = suite["answers"]
    opts = D.ScoreOptions(exec_enabled=True, judge=None)
    out = io.open(opath, "w", encoding="utf-8")

    def w(*a):
        out.write(" ".join(str(x) for x in a) + "\n")

    w("transcripts:", tpath)
    w("suite hash :", tr.get("suite_hash"), "| model:", tr.get("model_label"))
    w("")
    summary = []
    for ds, recs in tr["generations"].items():
        refs = answers.get(ds)
        trunc = empty = 0
        marker_missing = []
        rescored, mismatch = [], []
        w("=" * 78)
        w("### %s  (n=%d)" % (ds, len(recs)))
        for r in recs:
            i, text, toks = r["index"], r["response"], r["tokens"]
            if toks >= MAX_TOKENS:
                trunc += 1
            if not (text or "").strip():
                empty += 1
            ref = refs[i] if refs else None
            stripped = D.strip_think(text)
            if ds == "GSM8K":
                hashes = text.count("####")
                pred = (text.rsplit("####", 1)[-1].strip().splitlines() or [""])[0] \
                    if "####" in text else "(fallback: last number)"
                if hashes == 0:
                    marker_missing.append((i, "no #### at all"))
                elif not D._norm_answer(pred).replace("-", "").replace(".", "").isdigit():
                    marker_missing.append((i, "text after last ####: %r" % show(pred, 60)))
            elif ds == "MATH-500":
                if "\\boxed{" not in text:
                    marker_missing.append((i, "no \\boxed{} in the answer"))
            elif ds in ("HumanEval", "MBPP"):
                code = D.extract_code(text)
                fenced = "```" in stripped
                looks_code = bool(code and any(
                    k in code for k in ("def ", "class ", "import ", "lambda ")))
                if not looks_code:
                    marker_missing.append((i, "extracted no code-like block; fenced=%s; got %r"
                                           % (fenced, show(code, 120))))
                elif not fenced:
                    marker_missing.append((i, "UNFENCED answer, extractor fell back to "
                                              "the whole reply (%d chars)" % len(code)))
            # offline re-score. The truncation-zero only applies to a dataset
            # that HAS a scorer here — a truncated ALPACA answer is unscored,
            # not a zero (bench.py gates this the same way).
            if not D.is_scored(ds, opts):
                sc = None
            elif toks >= MAX_TOKENS:
                sc = 0.0
            else:
                sc = D.score_response(ds, text, ref, prompt=r.get("prompt"), opts=opts)
            if sc is not None:
                rescored.append(sc)
                was = r.get("score")
                if was is not None and abs(was - sc * 100) > 0.05:
                    mismatch.append((i, was, round(sc * 100, 1)))
        w("truncated at %d tok : %d" % (MAX_TOKENS, trunc))
        w("empty content      : %d" % empty)
        w("mean output tokens : %.0f" % (sum(r["tokens"] for r in recs) / len(recs)))
        if rescored:
            mean = 100.0 * sum(rescored) / len(rescored)
            w("offline re-score   : %.1f/100 over n=%d" % (mean, len(rescored)))
            summary.append((ds, round(mean, 1), len(rescored), trunc, empty))
        else:
            w("offline re-score   : (unscored here)")
            summary.append((ds, None, 0, trunc, empty))
        w("re-score mismatches: %s" % (mismatch or "none (offline == run-time)"))
        w("EXTRACTION WARNINGS: %d" % len(marker_missing))
        for i, why in marker_missing:
            w("   [%2d] %s" % (i, why))
        out.flush()
    w("=" * 78)
    w("SUMMARY  dataset / offline score / graded n / truncated / empty")
    for ds, sc, n, t, e in summary:
        w("  %-12s %-8s n=%-3d trunc=%-3d empty=%d"
          % (ds, ("%.1f" % sc) if sc is not None else "-", n, t, e))
    scored = [s for _, s, _, _, _ in summary if s is not None]
    if scored:
        w("  Mean over %d scored sets: %.1f" % (len(scored), sum(scored) / len(scored)))
    out.close()
    print("wrote", opath)


main()
