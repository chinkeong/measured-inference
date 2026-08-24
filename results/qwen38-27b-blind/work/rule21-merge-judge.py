"""Fold the judge panel's ALPACA and MT-Bench scores into each effort arm.

    python rule21-merge-judge.py

Rule 21's Mean is a composite index over the SEVEN-benchmark suite. Until now
this campaign could only publish a five-of-seven Mean, because rule 21 gates
ALPACA and MT-Bench behind an independent judge and none was configured. The
judge exists now (scripts/bench/judge-panel.py, a blind three-seat Claude
Opus 5 panel), so this script produces the arm JSONs that carry the full
seven-benchmark Mean beside the five-benchmark one.

BOTH MEANS ARE KEPT. Rule 21: "Two reports' Means are comparable only when
their scored sets AND suite hashes match." The five-benchmark Mean is what
every earlier number on this page compares against; the seven-benchmark Mean
is what rule 21 actually specifies. Dropping either would silently break one
comparison or the other.

PROVENANCE, recorded per dataset: the judged pair's generations come from the
ORIGINAL 16,384-cap arms. The cap-32k re-runs covered only the datasets that
truncated (MATH-500 / HumanEval / MBPP), so ALPACA and MT-Bench were never
regenerated at the raised cap - and did not need to be, since only xhigh
ALPACA ever hit a cap at all.
"""

import json
import os
import sys

BENCH = r"E:\AI\measured-inference\scripts\bench"
R21 = r"E:\AI\measured-inference\results\qwen38-27b-blind\data\rule21"
JUDGE = r"E:\AI\measured-inference\results\qwen38-27b-blind\data\judge\judge-scores.json"
sys.path.insert(0, BENCH)

import datasets_io as D  # noqa: E402

ARMS = ["low", "medium", "xhigh"]
PAIR = ["ALPACA", "MT-Bench"]


def main():
    js = json.load(open(JUDGE, encoding="utf-8"))
    print("judge: %s | seats %s | rated %d/%d"
          % (js["judge"], js["seats"], js["answers_rated"], js["answers_total"]))
    if js["missing"] or js["partial"]:
        print("  REFUSING: %d unrated, %d partially rated - every answer needs "
              "all seats before a score publishes (rule 7: no filtering)"
              % (len(js["missing"]), len(js["partial"])))
        return 1

    for arm in ARMS:
        base_path = os.path.join(R21, "arm-%s-cap32k-merged.json" % arm)
        base = json.load(open(base_path, encoding="utf-8"))
        five = base["composite"]["mean"]
        caps = dict(base.get("max_tokens_by_dataset", {}))

        provisional = []
        for ds in PAIR:
            j = js["arms"][arm][ds]
            base["results"][ds] = {
                "score": j["score_0_100"],
                "graded_n": j["n"],
                "scorer": "judge 1-10 (Claude Opus 5, 3 blind seats), "
                          "normalized (r-1)/9*100",
                "mean_rating_1_10": j["mean_rating_1_10"],
                "sd_across_items": j["sd_across_items"],
                "mean_seat_spread": j["mean_seat_spread"],
                "max_seat_spread": j["max_seat_spread"],
                "at_cap_items": j["at_cap_items"],
                "provisional": j["provisional"],
            }
            base["results"][ds].pop("unscored_reason", None)
            caps[ds] = 16384
            if j["provisional"]:
                provisional.append("%s (at-cap items %s: rule-7 re-run pending)"
                                   % (ds, j["at_cap_items"]))

        order = [d for d in base["datasets"] if d in base["results"]]
        base["composite_5"] = dict(base["composite"])
        base["composite_5"]["note"] = (
            "the five-benchmark Mean this campaign published before a judge "
            "was configured - kept because every earlier comparison on the "
            "page is against it")
        base["composite"] = D.composite_index(
            {d: m["score"] for d, m in base["results"].items() if "score" in m},
            order=order,
            excluded={d: m["unscored_reason"] for d, m in base["results"].items()
                      if "unscored_reason" in m})
        base["max_tokens_by_dataset"] = caps
        base["model_label"] = "%s (7-benchmark, judged)" % base["model_label"]
        base["judge_panel"] = {
            "protocol": js["protocol"],
            "judge": js["judge"],
            "rubric": js["rubric"],
            "normalization": js["normalization"],
            "seats": js["seats"],
            "blinding": "opaque salted ids; arm identity sealed in "
                        "key-SEALED.json, which no seat reads; per-seat "
                        "shuffle seeds so ordering effects do not correlate",
            "known_condition": "a seat sees several answers to the same "
                               "question inside one shuffled batch - this is "
                               "not a clean-room single-answer protocol",
            "independence_limit": "the answers were written by Qwen, so no "
                                  "model grades its own output (rule 21's "
                                  "scoring gate is satisfied); the judge and "
                                  "this report's author are both Claude "
                                  "models, which is a correlated instrument "
                                  "and is disclosed with every number",
            "pair_generation_cap": 16384,
            "provisional": provisional or "none",
        }
        out = os.path.join(R21, "arm-%s-judged.json" % arm)
        json.dump(base, open(out, "w", encoding="utf-8"), indent=2)
        seven = base["composite"]["mean"]
        print("%-7s  5-bench %.1f -> 7-bench %.1f   ALPACA %.1f  MT-Bench %.1f%s"
              % (arm, five, seven,
                 base["results"]["ALPACA"]["score"],
                 base["results"]["MT-Bench"]["score"],
                 "  [PROVISIONAL: %s]" % "; ".join(provisional) if provisional else ""))
    return 0


sys.exit(main())
