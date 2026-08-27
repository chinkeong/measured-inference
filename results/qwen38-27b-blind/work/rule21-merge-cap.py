"""Build one arm's raised-cap result by merging the rule-7 re-run into it.

    python rule21-merge-cap.py <base_regraded.json> <rerun.json> <label> <out.json>

The re-run covers only the datasets that truncated at 16,384. The rest are
carried over from the 16,384 arm unchanged — which the determinism check
licenses: every non-truncated prompt reproduced byte-identically when the cap
and -c were raised, so re-running the untouched datasets would only have
reproduced the same numbers at the cost of hours of GPU time.

The result records, per dataset, which cap produced it.
"""

import json
import sys

BENCH = r"E:\AI\measured-inference\scripts\bench"
sys.path.insert(0, BENCH)

import datasets_io as D  # noqa: E402


def main():
    base_path, rerun_path, label, out_path = sys.argv[1:5]
    with open(base_path, encoding="utf-8") as f:
        base = json.load(f)
    with open(rerun_path, encoding="utf-8") as f:
        rerun = json.load(f)

    caps, changes = {}, []
    for ds, m in base["results"].items():
        caps[ds] = base["settings"]["max_tokens"]
    for ds, m in rerun["results"].items():
        old = base["results"].get(ds, {}).get("score")
        base["results"][ds] = m
        caps[ds] = rerun["settings"]["max_tokens"]
        if old is not None and "score" in m and abs(old - m["score"]) > 0.05:
            changes.append("%s %.1f -> %.1f" % (ds, old, m["score"]))

    order = [d for d in base["datasets"] if d in base["results"]]
    base["composite"] = D.composite_index(
        {d: m["score"] for d, m in base["results"].items() if "score" in m},
        order=order,
        excluded={d: m["unscored_reason"] for d, m in base["results"].items()
                  if "unscored_reason" in m})
    base["model_label"] = label
    base["settings"]["max_tokens"] = "16384/32768 (see max_tokens_by_dataset)"
    base["max_tokens_by_dataset"] = caps
    base["rule7_rerun"] = {
        "rerun_datasets": sorted(rerun["results"]),
        "rerun_ctx": rerun["backend"]["ctx"],
        "rerun_max_tokens": rerun["settings"]["max_tokens"],
        "score_changes": changes or "none",
        "note": "datasets not listed were carried over from the 16384-cap arm; "
                "the determinism check showed non-truncated prompts reproduce "
                "byte-identically when the cap and -c are raised",
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(base, f, indent=2)
    trunc = sum(m.get("truncated_n", 0) for m in base["results"].values())
    print("%-16s Mean %.1f | still truncated: %d | changes: %s"
          % (label, base["composite"]["mean"], trunc, changes or "none"))


main()
