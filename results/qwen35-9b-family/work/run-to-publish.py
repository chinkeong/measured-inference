#!/usr/bin/env python3
"""Run every remaining measurement, unattended, up to the edge of Stage 7.

SCOPE, set deliberately. Ornith-1.5-9B is the subject of this work and is
measured exhaustively in results/ornith-1.5-9b-mtp/. Qwen3.5-9B is the ANCHOR:
it exists to make the Ornith numbers comparable to something, and it needs only
what a legal comparison requires -- not a second full field guide. So:

  A  the paired anchor sweep      both arms, ONE sweep, ratios to the anchor
                                  (rule 30; COMPARISON-SPEC's anchor rule)
  B  the rule-21 suite on Qwen    the same frozen suite hash the Ornith arm and
                                  the qwen38-27b-blind campaign ran, so the
                                  Means are comparable by construction (rule 23)

That is the whole set. GPQA is NOT queued: it cost 7h55m on Ornith, its value
there was harness validation against a published figure, and re-spending a day
on the anchor buys a number this comparison does not need. Recorded as a
deliberate omission rather than left to look like an oversight.

RESUMABLE AND SERIALISED. State lives in data/chain-state.json; a step already
marked done is skipped, so a crash costs only the step in flight. Every child
takes the GPU lock itself, so rule 20 holds without this script knowing anything
about the card. A heartbeat is written before and after each step, because a
detached pipeline that stops writing is the one failure an idle-trigger cannot
see (rule 20's liveness protocol).
"""
import json, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SLUG = "qwen35-9b-family"
DATA = os.path.join(REPO, "results", SLUG, "data")
WORK = os.path.join(REPO, "results", SLUG, "work")
STATE = os.path.join(DATA, "chain-state.json")
HB = os.path.join(WORK, "heartbeat.json")
PY = os.path.join(REPO, ".venv", "bin", "python")
MODEL = os.path.join(REPO, "models", "Qwen3.5-9B-MTP-Q8_0.gguf")
URL = ("https://huggingface.co/unsloth/Qwen3.5-9B-MTP-GGUF/resolve/main/"
       "Qwen3.5-9B-Q8_0.gguf")


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {"done": [], "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def save(s):
    json.dump(s, open(STATE, "w"), indent=1)


def beat(step, note):
    json.dump({"_schema": "heartbeat v1", "slug": SLUG, "in_flight": step,
               "note": note, "pid": os.getpid(),
               "written_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
              open(HB, "w"), indent=1)


def remote_size():
    try:
        r = subprocess.run(["curl", "-sIL", URL], capture_output=True,
                           text=True, timeout=120)
        n = None
        for line in r.stdout.splitlines():
            if line.lower().startswith("content-length:"):
                n = int(line.split(":", 1)[1].strip())
        return n
    except Exception:
        return None


def wait_for_download():
    """Complete means size == Content-Length, never 'big enough' -- the gate
    that accepted any file over a gigabyte as finished is a fixed defect in this
    tree (reference/failure-library.md) and is not being reintroduced here."""
    want = remote_size()
    for _ in range(360):                      # up to 2 h
        have = os.path.getsize(MODEL) if os.path.exists(MODEL) else 0
        if want and have == want:
            log("download complete and VERIFIED: %d bytes == Content-Length" % have)
            return True
        if not want and have > 9.5e9:
            log("download looks complete (%d bytes) but Content-Length was "
                "unavailable: size UNVERIFIED" % have)
            return True
        beat("download", "%s / %s bytes" % (have, want))
        time.sleep(20)
    log("download did not complete")
    return False


def run(step, cmd, logname):
    s = state()
    if step in s["done"]:
        log("%s already done -- skipping" % step)
        return True
    beat(step, "running")
    log("=== %s ===" % step)
    lp = os.path.join(WORK, logname)
    with open(lp, "w") as fh:
        rc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT,
                            cwd=REPO).returncode
    if rc == 0:
        s = state(); s["done"].append(step); save(s)
        log("%s OK" % step)
        subprocess.run(["git", "add", "-A"], cwd=REPO)
        subprocess.run(["git", "commit", "-q", "-m",
                        "qwen35-9b-family: %s complete" % step], cwd=REPO)
        beat(None, "%s complete" % step)
        return True
    log("%s FAILED rc=%s (see %s) -- stopping so the failure is visible rather "
        "than carried into the next step" % (step, rc, logname))
    beat(None, "%s failed rc=%s" % (step, rc))
    return False


def main():
    os.makedirs(DATA, exist_ok=True)
    save(state())
    if not wait_for_download():
        return 1
    steps = [
        ("A-anchor-sweep",
         [PY, os.path.join(WORK, "anchor-sweep.py")], "A-anchor-sweep.log"),
        ("B-rule21-qwen",
         [PY, os.path.join(REPO, "scripts", "bench", "bench.py"),
          "--model", MODEL,
          "--rule21", "--suite",
          os.path.join(REPO, "scripts", "bench", "suites", "rule21-n25.json"),
          "--transcripts", "--ctx", "32768",
          "--server-args", "-ngl 99 --jinja"], "B-rule21-qwen.log"),
    ]
    for step, cmd, logname in steps:
        if not run(step, cmd, logname):
            return 1
    beat(None, "chain complete -- everything before Stage 7 is measured")
    log("CHAIN COMPLETE. Remaining before publish: the judge panel over Qwen's "
        "ALPACA/MT-Bench transcripts (needs blind seats, not a subprocess), "
        "then Stage 7 writing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
