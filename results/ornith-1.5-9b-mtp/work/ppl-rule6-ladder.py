#!/usr/bin/env python3
"""The rule-6 quant ranking: perplexity over 294,912 token positions — the third input to the early pruning gate.

stage-1.md: "a short PPL screen -- the same small fixed set of wikitext-2-raw
chunks for every file (4 x 8,192 tokens is enough), identical chunks across
files". IDENTICAL is the whole point: -c 8192 --chunks 4 walks the same first
32,768 token positions of the same frozen corpus for every arm, so the three
numbers are comparable to each other even though none of them is publishable.

THE SCREEN RANKS NOTHING PUBLISHABLE. Rule 6 ranks quants over 294,912 token
positions; this is 32,768, one ninth of it, and it exists only to answer the
gate's question -- is any file both SLOWER and WORSE than another, in which case
it cannot win on an axis a reader cares about and is dropped here rather than
after it has eaten hours.

Rule 20: llama-perplexity is a GPU job like any other. It goes through
gpu_lock, which is also the thing that stops it racing a server -- and note that
gpu_lock could not SEE llama-perplexity on Linux until 2026-08-31, because
/proc/<pid>/comm truncates the 16-character name to llama-perplexit.
Resumable: an arm whose result is already in the JSON is skipped, so a crash
costs only the arm in flight.
"""
import json, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "scripts", "lib"))
sys.path.insert(0, os.path.join(REPO, "scripts", "bench"))
import paths            # noqa: E402
import gpu_lock         # noqa: E402

CAMP = paths.load_campaign()
SLUG = CAMP["slug"]
OUT = os.path.join(REPO, "results", SLUG, "data", os.environ.get("PPL_OUT","ppl-rule6-ladder.json"))
WORK = os.path.join(REPO, "results", SLUG, "work")
CORPUS = os.path.join(REPO, CAMP.get("corpus", "corpora/wikitext-2-raw-test.raw"))
PPL = paths.llama_bin("llama-perplexity")

CTX = int(os.environ.get("PPL_CTX", 8192))
CHUNKS = int(os.environ.get("PPL_CHUNKS", 4))                      # 4 x 8,192 = 32,768 token positions, identical per arm
NGL = 99                        # rule 15

# PPL_ARMS="label=file.gguf,label2=file2.gguf" overrides the roster, so the
# same instrument can ladder a cross-check file from another lineage without a
# second copy of this script drifting away from it (rule 4).
_env = os.environ.get("PPL_ARMS")
if _env:
    ARMS = [tuple(x.split("=", 1)) for x in _env.split(",") if "=" in x]
else:
    ARMS = [("Q8_0", "Ornith-1.5-9B-MTP-Q8_0.gguf"),
            ("Q4_K_M", "Ornith-1.5-9B-MTP-Q4_K_M.gguf"),
            ("IQ2_M", "Ornith-1.5-9B-MTP-IQ2_M.gguf")]

FINAL = re.compile(r"Final estimate:\s*PPL\s*=\s*([0-9.]+)\s*\+/-\s*([0-9.]+)")
EST = re.compile(r"\[(\d+)\]\s*([0-9.]+)")


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def load():
    if os.path.exists(OUT):
        try:
            return json.load(open(OUT))
        except Exception:
            pass
    return {"_schema": "stage1-ppl-screen v1", "slug": SLUG,
            "corpus": os.path.relpath(CORPUS, REPO),
            "corpus_bytes": os.path.getsize(CORPUS),
            "ctx": CTX, "chunks": CHUNKS, "ngl": NGL,
            "token_positions": CTX * CHUNKS,
            "publishable": True,
            "rule": ("rule 6: quants are ranked by perplexity over 294,912 token "
                     "positions. 36 chunks x 8,192 = 294,912 exactly, the same "
                     "chunks of the same frozen corpus for every arm."),
            "arms": {}}


def main():
    out = load()
    gpu_lock.acquire("stage1-ppl-screen")
    for label, fname in ARMS:
        if label in out["arms"] and out["arms"][label].get("ppl"):
            log("%s already screened (%.4f) -- skipping" % (label, out["arms"][label]["ppl"]))
            continue
        gguf = paths.model_path(fname)
        logp = os.path.join(WORK, "ppl-rule6-%s.log" % label)
        cmd = [PPL, "-m", gguf, "-f", CORPUS, "-c", str(CTX),
               "--chunks", str(CHUNKS), "-ngl", str(NGL)]
        log("PPL screen: %s (%d x %d positions)" % (label, CHUNKS, CTX))
        t0 = time.time()
        with open(logp, "w") as fh:
            p = gpu_lock.serve(cmd, tag="ppl-%s" % label, stdout=fh,
                               stderr=subprocess.STDOUT)
            rc = p.wait()
        dt = time.time() - t0
        text = open(logp, errors="replace").read()
        m = FINAL.search(text)
        rec = {"file": os.path.basename(gguf),
               "size_bytes": os.path.getsize(gguf),
               "rc": rc, "seconds": round(dt, 1),
               "log": os.path.relpath(logp, REPO),
               "cmd": cmd}
        if m:
            rec["ppl"] = float(m.group(1))
            rec["ppl_stderr"] = float(m.group(2))
            rec["how"] = "MEASURED: llama-perplexity Final estimate"
        else:
            rec["how"] = "FAILED"
            rec["log_tail"] = text[-1500:]
        out["arms"][label] = rec
        json.dump(out, open(OUT, "w"), indent=1)     # rule 28: write as it happens
        log("%s -> PPL %s (%.0f s)" % (label, rec.get("ppl"), dt))
    out["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    json.dump(out, open(OUT, "w"), indent=1)
    log("wrote %s" % OUT)


if __name__ == "__main__":
    main()
