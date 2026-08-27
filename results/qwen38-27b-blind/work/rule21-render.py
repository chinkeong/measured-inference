"""Render the rule-21 effort sweep: comparison PNG + the markdown score table.

    python rule21-render.py <out.png> <out.md> <label>=<regraded.json> ...

Column order follows the order the arms are given on the command line.
"""

import json
import os
import sys

BENCH = r"E:\AI\measured-inference\scripts\bench"
sys.path.insert(0, BENCH)

import render_table  # noqa: E402

ORDER = ["GSM8K", "MATH-500", "HumanEval", "MBPP", "ALPACA", "MeetingBank",
         "MT-Bench"]
SCORED = ["GSM8K", "MATH-500", "HumanEval", "MBPP", "MeetingBank"]


def cell(m):
    if not m or "score" not in m:
        return "unscored"
    s = m["score"]
    txt = "%.0f%%" % s if m.get("scorer") in ("exact match", "execution pass@1") \
        else "%.1f" % s
    if m.get("truncated_n"):
        txt += " (%d trunc)" % m["truncated_n"]
    return txt


def main():
    png, md = sys.argv[1], sys.argv[2]
    arms = []
    for spec in sys.argv[3:]:
        label, path = spec.split("=", 1)
        with open(path, encoding="utf-8") as f:
            run = json.load(f)
        wall_path = os.path.join(os.path.dirname(path), "arm-%s-wall.json" % label)
        wall = None
        if os.path.exists(wall_path):
            with open(wall_path, encoding="utf-8") as f:
                wall = json.load(f)
        arms.append((label, run, wall))

    render_table.render_runs([r for _, r, _ in arms], out_path=png)

    L = []
    L.append("| Benchmark | Scorer | " + " | ".join(l for l, _, _ in arms) + " |")
    L.append("|---|---|" + "---|" * len(arms))
    for ds in ORDER:
        scorer = next((r["results"][ds].get("scorer") for _, r, _ in arms
                       if ds in r["results"] and r["results"][ds].get("scorer")),
                      None)
        if scorer is None:
            scorer = "judge 1-10 - **no judge: unscored**"
        L.append("| %s | %s | %s |" % (
            ds, scorer,
            " | ".join(cell(r["results"].get(ds)) for _, r, _ in arms)))
    L.append("| **Mean (composite, 5 scored sets)** | - | %s |" % " | ".join(
        "**%.1f**" % r["composite"]["mean"] for _, r, _ in arms))
    L.append("")
    L.append("| Per-arm | " + " | ".join(l for l, _, _ in arms) + " |")
    L.append("|---|" + "---|" * len(arms))
    L.append("| Wall time | %s |" % " | ".join(
        ("%.2f h" % w["wall_h"]) if w else "-" for _, _, w in arms))
    L.append("| Truncated at cap (of 175) | %s |" % " | ".join(
        str(sum(m.get("truncated_n", 0) for m in r["results"].values()))
        for _, r, _ in arms))
    L.append("| Mean output tokens (all 7 sets) | %s |" % " | ".join(
        "%.0f" % (sum(m["tokens"] for m in r["results"].values())
                  / len(r["results"])) for _, r, _ in arms))
    L.append("| Decode tok/s (mean) | %s |" % " | ".join(
        "%.1f" % (sum(m["tok_s"] for m in r["results"].values())
                  / len(r["results"])) for _, r, _ in arms))
    with open(md, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("wrote", png)
    print("wrote", md)
    print("\n".join(L))


main()
