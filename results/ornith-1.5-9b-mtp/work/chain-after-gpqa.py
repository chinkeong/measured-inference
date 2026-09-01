#!/usr/bin/env python3
"""Wait for GPQA, then run the format-vs-bpw test. Argv-position matching only:
`pgrep -f <name>` matches any shell whose command line MENTIONS the name --
including this waiter's own -- which is how an earlier chain waited 26 minutes
for itself on an idle card."""
import os, subprocess, sys, time
REPO = "/root/Workspace/measured-inference"

def gpqa_alive():
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

while gpqa_alive():
    time.sleep(60)
time.sleep(30)
os.execv(os.path.join(REPO, ".venv/bin/python"),
         [os.path.join(REPO, ".venv/bin/python"),
          os.path.join(REPO, "results/ornith-1.5-9b-mtp/work/stage6-format-vs-bpw.py")])
