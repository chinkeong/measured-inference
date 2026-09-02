#!/usr/bin/env python3
"""2x2 template crossover, scoped to MATH-500 + MBPP.

Two new arms only -- the diagonal is already measured:
  qwen weights   + ORNITH template
  ornith weights + QWEN   template

Everything else is held: same frozen suite hash, same greedy sampler, same
16,384 cap, same -c 32768, same box. Only the template moves.
"""
import json, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
os.environ.setdefault("MEASURED_INFERENCE_SLUG", "qwen35-9b-family")
PY = os.path.join(REPO, ".venv", "bin", "python")
SUITE = os.path.join(REPO, "scripts", "bench", "suites", "rule21-n25.json")
TPL = os.path.join(HERE, "templates")
STATE = os.path.join(REPO, "results", "qwen35-9b-family", "data", "crossover-state.json")

ARMS = [
    ("qwenW-ornithT", "Qwen3.5-9B-MTP-Q8_0.gguf",   "ornith.jinja"),
    ("ornithW-qwenT", "Ornith-1.5-9B-MTP-Q8_0.gguf", "qwen.jinja"),
]


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {"done": []}


def main():
    for name, gguf, tpl in ARMS:
        s = state()
        if name in s["done"]:
            log("%s already done" % name); continue
        log("=== %s  (%s + %s) ===" % (name, gguf, tpl))
        lp = os.path.join(HERE, "crossover-%s.log" % name)
        cmd = [PY, os.path.join(REPO, "scripts", "bench", "bench.py"),
               "--model", os.path.join(REPO, "models", gguf),
               "--rule21", "--suite", SUITE,
               "--datasets", "MATH-500,MBPP",
               "--transcripts", "--ctx", "32768",
               "--server-args",
               "-ngl 99 --jinja --chat-template-file %s" % os.path.join(TPL, tpl)]
        with open(lp, "w") as fh:
            rc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT,
                                cwd=REPO, env=dict(os.environ)).returncode
        if rc != 0:
            log("%s FAILED rc=%s -- see %s" % (name, rc, lp)); return 1
        s = state(); s["done"].append(name)
        json.dump(s, open(STATE, "w"), indent=1)
        subprocess.run(["git", "add", "-A"], cwd=REPO)
        subprocess.run(["git", "commit", "-q", "-m",
                        "crossover: %s complete" % name], cwd=REPO)
        log("%s OK" % name)
    log("CROSSOVER COMPLETE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
