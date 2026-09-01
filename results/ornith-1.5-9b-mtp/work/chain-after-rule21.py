#!/usr/bin/env python3
"""Wait for the rule-21 suite, then RE-RUN task A1 with the loop scan repaired.

WHY A1 HAS TO RUN AGAIN. A1's own docstring says it exists because Stage 1 saved
only 400 chars per floor, so the floors could not be loop-checked from what was
written down. Its fix then reproduced the disease: ask() read only the
response's `content`, llama.cpp --jinja had routed the whole generation into
`reasoning_content`, and the detector was handed the empty string. All three
work/a1-floor-*.txt were written 0 bytes and loop-scan.json recorded
`chars: 0, verdict: clean` for Q8_0, Q4_K_M and IQ2_M.

That is not a passing check, it is no check. And it matters here specifically:
the SAME file scored LOOP on all six spec-sweep transcripts, at the same
temp 0 / top_k 1 sampler the Stage-1 floors used. Rule 20 requires a long greedy
generation be spot-read for repetition before its tokens or timings are trusted,
and the three published floors -- 78.30, 118.38, 131.30 t/s -- have never
actually had that check applied to them.

Argv-position matching only: `pgrep -f <name>` matches any shell whose command
line MENTIONS the name, including this waiter's own, which cost this campaign 26
minutes of idle card once already.
"""
import json, os, time

REPO = "/root/Workspace/measured-inference"
SLUG = "ornith-1.5-9b-mtp"
STATE = os.path.join(REPO, "results", SLUG, "data", "runner-state.json")
PY = os.path.join(REPO, ".venv/bin/python")


def suite_alive():
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            a = open("/proc/%s/cmdline" % pid, "rb").read().decode("latin-1").split("\x00")
        except Exception:
            continue
        if len(a) >= 2 and a[0].endswith("python") and a[1].endswith("scripts/bench/bench.py"):
            return True
    return False


while suite_alive():
    time.sleep(60)
time.sleep(30)

# Clear A1 so the runner does not skip it. Everything else stays done -- this is
# a targeted re-run of one task, not a re-do of the campaign (rule 7's shape:
# raise the cap and rerun THAT ARM only).
s = json.load(open(STATE))
s["done"] = [t for t in s.get("done", []) if t != "A1"]
s.setdefault("reruns", []).append(
    {"task": "A1", "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
     "why": "loop scan read `content` only; --jinja put the generation in "
            "`reasoning_content`, so the detector judged an empty string and "
            "returned clean for all three floor arms"})
json.dump(s, open(STATE, "w"), indent=1)

os.execv(PY, [PY, os.path.join(REPO, "results", SLUG, "work", "runner.py")])
