"""Determinism check for a rule-7 raised-cap re-run.

    python rule21-determinism.py <base_transcripts.json> <rerun_transcripts.json>

Greedy decoding at a fixed seed should make a raised cap and a bigger -c
irrelevant to every prompt that did NOT hit the old cap: same prompt, same
weights, same sampler -> same tokens. This compares the two runs prompt by
prompt and reports any drift.

That is what licenses re-running only the datasets that truncated instead of a
whole arm: if the untruncated prompts reproduce exactly here, the untouched
datasets would have reproduced exactly too.
"""

import json
import sys

OLD_CAP = 16384


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)["generations"]


def main():
    base, rerun = load(sys.argv[1]), load(sys.argv[2])
    total_same = total_cmp = 0
    for ds in rerun:
        if ds not in base:
            continue
        b = {r["index"]: r for r in base[ds]}
        same = differ = freed = 0
        drift = []
        for r in rerun[ds]:
            o = b.get(r["index"])
            if o is None:
                continue
            if o["tokens"] >= OLD_CAP:
                freed += 1                      # was truncated: must differ
                continue
            total_cmp += 1
            if o["tokens"] == r["tokens"] and o["response"] == r["response"]:
                same += 1
                total_same += 1
            else:
                differ += 1
                drift.append((r["index"], o["tokens"], r["tokens"]))
        print("%-11s identical %2d/%-2d | previously truncated %d | drifted %s"
              % (ds, same, same + differ, freed,
                 drift if drift else "none"))
    print("\nnon-truncated prompts reproduced byte-identically: %d/%d"
          % (total_same, total_cmp))
    print("VERDICT:", "PASS - raising -c and the cap changed nothing else"
          if total_same == total_cmp else "FAIL - generations drifted")


main()
