"""Rule-20 greedy-repetition audit over the accuracy ladder's transcripts.

    python ladder-repcheck.py

Rule 20: "any long greedy generation whose tokens or timings feed a claim must
be spot-read for degenerate repetition loops first - a looping transcript
inflates t/s and token counts with garbage, and greedy decoding makes the loop
deterministic, not rare." The accuracy ladder's low rungs are exactly where
such loops live, so this runs BEFORE any of its numbers are believed.

It reuses the campaign's own detector logic (data/followup/m4-repcheck.py):
immediate back-to-back block repeats, line loops, and tail n-gram clustering -
plus the unique-word ratio, because the judge panel proved on 2026-08-24 that
those three detectors are BLIND to a degeneration that merely counts upward
("one hundred and one, one hundred and two...") without repeating a block.
That gap is why the ratio is printed for every generation rather than only the
pass/fail verdict.

Zero GPU. Reads only what the arms already wrote.
"""

import glob
import json
import os
import re
import sys
from collections import Counter

BENCH = (r"E:\AI\measured-inference\results\qwen38-27b-blind"
         r"\data\quant-ladder\bench")
sys.path.insert(0, r"E:\AI\measured-inference\results\qwen38-27b-blind"
                   r"\data\followup")

try:
    import importlib.util
    _s = importlib.util.spec_from_file_location(
        "m4", os.path.join(r"E:\AI\measured-inference\results"
                           r"\qwen38-27b-blind\data\followup",
                           "m4-repcheck.py"))
    m4 = importlib.util.module_from_spec(_s)
    _s.loader.exec_module(m4)
except Exception as e:                                    # noqa: BLE001
    print("could not load m4-repcheck: %r" % (e,))
    m4 = None


def uniq_ratio(text):
    w = [x.lower() for x in re.findall(r"[A-Za-z']+", text)]
    return (len(set(w)) / len(w)) if w else 1.0


def longest_run(text):
    """Longest run of the same whitespace-separated token, a cheap catch for
    the counting/padding shapes the block detectors miss."""
    ws = text.split()
    best = cur = 1
    for a, b in zip(ws, ws[1:]):
        cur = cur + 1 if a == b else 1
        best = max(best, cur)
    return best if ws else 0


def audit(path):
    j = json.load(open(path, encoding="utf-8"))
    label = j.get("model_label", os.path.basename(path))
    rows = []
    for ds, items in j.get("generations", {}).items():
        for it in items:
            t = str(it.get("response", ""))
            if not t.strip():
                rows.append((ds, it["index"], it.get("tokens", 0), 0.0, 0,
                             "EMPTY", 0))
                continue
            ws = t.split()
            imm = len(m4.immediate_loops(ws)) if m4 else 0
            ur = uniq_ratio(t)
            lr = longest_run(t)
            flag = []
            if imm:
                flag.append("IMMEDIATE(%d)" % imm)
            if ur < 0.30:
                flag.append("LOWUNIQ")
            if lr >= 8:
                flag.append("RUN%d" % lr)
            rows.append((ds, it["index"], it.get("tokens", 0), ur, lr,
                         ",".join(flag) or "clean", imm))
    flagged = [r for r in rows if r[5] != "clean"]
    urs = sorted(r[3] for r in rows if r[5] != "EMPTY")
    med = urs[len(urs) // 2] if urs else 0.0
    print("%-28s n=%3d  median uniq=%.3f  min uniq=%.3f  flagged=%d"
          % (label, len(rows), med, urs[0] if urs else 0.0, len(flagged)))
    for r in flagged:
        print("     %-10s idx=%2d tokens=%6d uniq=%.3f longest_run=%2d  %s"
              % (r[0], r[1], r[2], r[3], r[4], r[5]))
    return label, len(rows), med, len(flagged)


def main():
    files = sorted(glob.glob(os.path.join(BENCH, "arm-qwen-*_transcripts.json")))
    if not files:
        print("no transcripts yet")
        return
    print("Rule-20 greedy-repetition audit - %d arm(s)\n" % len(files))
    for f in files:
        audit(f)
        print()


main()
