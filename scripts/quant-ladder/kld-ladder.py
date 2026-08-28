"""Agreement-with-the-anchor for every rung: KL divergence and "Same top p".

    python kld-ladder.py --probe          measure the disk cost, decide, stop
    python kld-ladder.py --run            save the base, then score the ladder

WHY. A reader of the published page objected that raw perplexity is the wrong
instrument and that Unsloth's "Same top p" is better. He is substantially
right, and this campaign already had its own evidence for the same point:
perplexity could not separate UD-IQ2_XXS from UD-IQ1_M (1.67% apart at 1.7
sigma), which is the reason the accuracy ladder was built at all.

WHAT "Same top p" ACTUALLY IS, since the name collides with a sampler flag and
the two are unrelated. `--top-p 0.95` is nucleus SAMPLING and belongs to the
recipes. "Same top p" is an output line of `llama-perplexity --kl-divergence`,
verified present in this build's llama-perplexity-impl.dll alongside Mean KLD,
Maximum KLD, RMS delta-p and the PPL ratios. It reports how often the quantised
model's most likely next token matches the reference model's, over the same
corpus - agreement per token rather than one average over a corpus.

WHY IT IS MORE SENSITIVE. Perplexity is a single scalar and two files can share
one while behaving differently. Agreement compares distributions token by
token, so a file that is good on average and bad in specific places has nowhere
to hide.

WHAT IT CANNOT DO, and the reason this ADDS a column rather than replacing one.
Agreement measures faithfulness to the reference, not usefulness. A file can
match the reference on 93% of tokens and still emit JavaScript that does not
run - which is exactly what the execute probe on this page catches and what no
agreement metric can see. Three instruments, three questions: how faithful
(KLD), how correct (scored accuracy), does it work (execute).

THE BASE MODEL PROBLEM, stated rather than hidden. Properly this is measured
against the unquantised FP16 weights, which are ~54 GB and are not on this
machine. Instead the base is **UD-IQ4_XS**, the file the ladder already treats
as its anchor for accuracy. Every number this produces is therefore
AGREEMENT-WITH-THE-ANCHOR and not agreement-with-FP16, it cannot be compared
against anybody else's KLD table, and it must never be labelled as though it
could. What it does do is rank this ladder's rungs against each other, which is
what the ladder is for.

DISK. `--save-all-logits` writes the reference distribution for every scored
token, and the corpus is 297,193 tokens against a 151,936-token vocabulary, so
the file can be enormous. --probe measures the real rate on five chunks and
extrapolates before anything commits to it.
"""

import argparse
import io
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
PPL = r"E:\AI\llama.cpp\llama-perplexity.exe"
UNS = os.environ.get("MODEL_DIR", r"C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF")
CORPUS = os.path.join(ROOT, "corpora", "wikitext-2-raw-test.raw")
OUT = os.path.join(ROOT, "results", "qwen38-27b-blind", "data", "quant-ladder")
BASEFILE = os.path.join(OUT, "kld-base-iq4xs.dat")

ANCHOR = ("UD-IQ4_XS", os.path.join(UNS, "Qwen3.8-27B-UD-IQ4_XS.gguf"))
RUNGS = [
    ("UD-Q3_K_XL", 3.895), ("UD-IQ3_XXS", 3.240), ("UD-Q2_K_XL", 2.912),
    ("UD-IQ2_S", 2.481), ("UD-IQ2_XXS", 2.153), ("UD-IQ1_M", 1.994),
    ("UD-IQ1_S", 1.835),
]
QAT = ("QAT-Q2_0", 2.595,
       r"C:\Users\chink\.lmstudio\models\sdkyuan\qwen3.8-27B-qat-q2_0-gguf\qwen38-27b-qat-q2_0.gguf")

FLAGS = ["-ngl", "99", "-c", "512", "-fa", "on", "--load-mode", "mmap"]
DISK_BUDGET_GIB = 40.0


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def run(args, timeout=14400):
    r = subprocess.run(args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return (r.stdout or "") + (r.stderr or ""), r.returncode


def parse_kld(txt):
    """Pull the metrics llama-perplexity prints for --kl-divergence."""
    out = {}
    pats = {
        "mean_kld": r"Mean\s+KLD:\s*([0-9.eE+-]+)",
        "max_kld": r"Maximum\s+KLD:\s*([0-9.eE+-]+)",
        "same_top_p_pct": r"Same top p:\s*([0-9.]+)",
        "ppl_ratio": r"Mean PPL\(Q\)/PPL\(base\)\s*:\s*([0-9.eE+-]+)",
        "ppl_delta": r"Mean PPL\(Q\)-PPL\(base\)\s*:\s*([-0-9.eE+]+)",
        "rms_dp": r"RMS\s+.{0,4}p\s*:\s*([0-9.eE+-]+)",
    }
    for k, p in pats.items():
        m = re.search(p, txt)
        if m:
            try:
                out[k] = float(m.group(1))
            except ValueError:
                pass
    return out


def probe():
    """Five chunks, measure the byte rate, extrapolate, then decide."""
    tmp = BASEFILE + ".probe"
    for f in (tmp,):
        if os.path.exists(f):
            os.remove(f)
    log("disk probe: 5 chunks of %s" % ANCHOR[0])
    t0 = time.time()
    txt, rc = run([PPL, "-m", ANCHOR[1], "-f", CORPUS] + FLAGS +
                  ["--chunks", "5", "--save-all-logits", tmp], timeout=3600)
    el = time.time() - t0
    if not os.path.exists(tmp):
        log("probe produced no file - exit %d" % rc)
        print(txt[-1200:])
        return None
    size = os.path.getsize(tmp)
    per_chunk = size / 5.0
    # NOT parsed from the output: llama-perplexity echoes the --chunks
    # argument, so a regex for "N chunks" matches the 5 we asked for and
    # reports the corpus as 5 chunks long. Derived from the measured token
    # count instead (297,193 for this tokenizer, verified against UD-IQ2_S).
    total_chunks = 297193 // 512
    full = per_chunk * total_chunks
    log("  5 chunks -> %.1f MiB (%.1f MiB/chunk), %.0f s"
        % (size / 1024 ** 2, per_chunk / 1024 ** 2, el))
    log("  corpus is ~%d chunks at -c 512" % total_chunks)
    log("  FULL base file would be ~%.1f GiB" % (full / 1024 ** 3))
    fit = int(DISK_BUDGET_GIB * 1024 ** 3 / per_chunk)
    log("  within a %.0f GiB budget: %d chunks (%.0f%% of the corpus)"
        % (DISK_BUDGET_GIB, min(fit, total_chunks),
           100.0 * min(fit, total_chunks) / total_chunks))
    os.remove(tmp)
    rep = {"date": time.strftime("%Y-%m-%d %H:%M"),
           "bytes_per_chunk": per_chunk, "total_chunks": total_chunks,
           "full_gib": round(full / 1024 ** 3, 2),
           "chunks_within_budget": min(fit, total_chunks),
           "seconds_for_5_chunks": round(el, 1)}
    os.makedirs(OUT, exist_ok=True)
    json.dump(rep, io.open(os.path.join(OUT, "kld-diskprobe.json"), "w",
                           encoding="utf-8"), indent=1)
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--chunks", type=int, default=None)
    a = ap.parse_args()

    if a.probe or not a.run:
        p = probe()
        if p and not a.run:
            log("probe only - pass --run --chunks N to score the ladder")
        return

    chunks = a.chunks
    if not chunks:
        p = probe()
        if not p:
            sys.exit("probe failed")
        chunks = p["chunks_within_budget"]
    log("base: %s over %d chunks" % (ANCHOR[0], chunks))
    if not os.path.exists(BASEFILE):
        t0 = time.time()
        txt, rc = run([PPL, "-m", ANCHOR[1], "-f", CORPUS] + FLAGS +
                      ["--chunks", str(chunks), "--save-all-logits", BASEFILE])
        log("  base saved in %.0f s, %.1f GiB, exit %d"
            % (time.time() - t0, os.path.getsize(BASEFILE) / 1024 ** 3, rc))
    else:
        log("  base already present (%.1f GiB)"
            % (os.path.getsize(BASEFILE) / 1024 ** 3))

    rows = []
    todo = [(n, b, os.path.join(UNS, "Qwen3.8-27B-%s.gguf" % n)) for n, b in RUNGS]
    todo.append(QAT)
    for name, bpw, path in todo:
        if not os.path.exists(path):
            log("  %-12s MISSING" % name)
            continue
        t0 = time.time()
        txt, rc = run([PPL, "-m", path, "-f", CORPUS] + FLAGS +
                      ["--chunks", str(chunks),
                       "--kl-divergence-base", BASEFILE, "--kl-divergence"])
        io.open(os.path.join(OUT, "kld-%s.log" % name), "w",
                encoding="utf-8", errors="replace").write(txt)
        met = parse_kld(txt)
        met.update({"file": name, "bpw": bpw, "chunks": chunks,
                    "seconds": round(time.time() - t0, 1), "returncode": rc})
        rows.append(met)
        log("  %-12s %5.3f bpw  same-top-p %6s%%  mean KLD %8s  PPL ratio %7s"
            % (name, bpw, met.get("same_top_p_pct", "?"),
               met.get("mean_kld", "?"), met.get("ppl_ratio", "?")))
        json.dump({"date": time.strftime("%Y-%m-%d %H:%M"),
                   "base": ANCHOR[0],
                   "base_caveat": "agreement with the UD-IQ4_XS ANCHOR, not with "
                                  "FP16 - not comparable to anyone else's KLD table",
                   "chunks": chunks, "rows": rows},
                  io.open(os.path.join(OUT, "kld-ladder.json"), "w",
                          encoding="utf-8"), indent=1)
    log("DONE")


main()
