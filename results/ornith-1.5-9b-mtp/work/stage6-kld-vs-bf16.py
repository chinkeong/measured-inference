#!/usr/bin/env python3
"""Is Q4_K_M's low perplexity FIDELITY, or a sharpened distribution?

Perplexity only asks: what probability did the model put on the token that
actually came next? A quant whose distribution is SHARPER than its source scores
better on that question over predictable text -- it is more confident, and on
wikitext most next-tokens are easy -- while being further from the original
model, not closer. The same sharpening is what makes greedy decoding fall into
repetition, which is what this campaign measured at Q4_K_M and did not measure
at BF16.

KL-divergence answers the question perplexity cannot: how far is the whole
distribution from the original's? llama-perplexity computes it directly, against
a logit dump from the unquantised model. Q8_0 is the control -- it sits 0.1 sigma
from BF16 on perplexity, so if the instrument is working, Q8_0's KLD must be
near zero and Q4_K_M's must not.

The .dat base is BULK (tens of GB) and is deleted at the end: every number
derived from it lands in the JSON beside this file (rule 29 -- an ignore rule is
a claim about re-creatability, and this one is true: one command remakes it).
"""
import json, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "scripts", "lib"))
sys.path.insert(0, os.path.join(REPO, "scripts", "bench"))
import paths, gpu_lock                                        # noqa: E402

CAMP = paths.load_campaign(); SLUG = CAMP["slug"]
OUT = os.path.join(REPO, "results", SLUG, "data", "kld-vs-bf16.json")
WORK = os.path.join(REPO, "results", SLUG, "work")
PPL = paths.llama_bin("llama-perplexity")
CORPUS = os.path.join(REPO, CAMP["corpus"])
BASE_DAT = os.path.join(REPO, "models", "kld-base-bf16.dat")
CTX, CHUNKS, NGL = 8192, 4, 99          # 32,768 positions; the .dat scales with this

ARMS = [("Q8_0", "Ornith-1.5-9B-MTP-Q8_0.gguf"),      # control: must be ~0
        ("Q4_K_M", "Ornith-1.5-9B-MTP-Q4_K_M.gguf"),  # the anomaly
        ("IQ2_M", "Ornith-1.5-9B-MTP-IQ2_M.gguf")]

NUM = r"([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)"
PATS = {
    "mean_kld":        re.compile(r"Mean\s+KLD\s*[:=]\s*" + NUM, re.I),
    "median_kld":      re.compile(r"Median\s+KLD\s*[:=]\s*" + NUM, re.I),
    "mean_ppl_ratio":  re.compile(r"Mean\s+PPL\s*ratio\s*[:=]\s*" + NUM, re.I),
    "same_top_pct":    re.compile(r"Same\s+top\s+p\s*[:=]\s*" + NUM, re.I),
    "mean_dp":         re.compile(r"Mean\s+Delta\s*p\s*[:=]\s*" + NUM, re.I),
}


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def run(cmd, logp):
    with open(logp, "w") as fh:
        p = gpu_lock.serve(cmd, tag="kld", stdout=fh, stderr=subprocess.STDOUT)
        rc = p.wait()
    return rc, open(logp, errors="replace").read()


def main():
    gpu_lock.acquire("stage6-kld")
    out = {"_schema": "kld-vs-bf16 v1", "slug": SLUG, "ctx": CTX, "chunks": CHUNKS,
           "token_positions": CTX * CHUNKS,
           "base": "Ornith-1.5-9B BF16 (vendor), unquantised",
           "question": ("is a low perplexity fidelity, or a sharpened "
                        "distribution? KLD answers what PPL cannot."),
           "control": "Q8_0 sits 0.1 sigma from BF16 on PPL; its KLD must be ~0",
           "arms": {}}
    if not os.path.exists(BASE_DAT):
        log("dumping BF16 base logits (%d positions) -- this is the big one" %
            (CTX * CHUNKS))
        rc, _ = run([PPL, "-m", paths.model_path("vendor-Ornith-1.5-9B-BF16.gguf"),
                     "-f", CORPUS, "-c", str(CTX), "--chunks", str(CHUNKS),
                     "-ngl", str(NGL), "--kl-divergence-base", BASE_DAT],
                    os.path.join(WORK, "kld-base-bf16.log"))
        log("base dump rc=%s  size=%.1f GB" % (rc, os.path.getsize(BASE_DAT) / 1e9))
    out["base_dat_bytes"] = os.path.getsize(BASE_DAT)
    for label, fname in ARMS:
        logp = os.path.join(WORK, "kld-%s.log" % label)
        log("KLD %s vs BF16" % label)
        rc, text = run([PPL, "-m", paths.model_path(fname), "-f", CORPUS,
                        "-c", str(CTX), "--chunks", str(CHUNKS), "-ngl", str(NGL),
                        "--kl-divergence", "--kl-divergence-base", BASE_DAT], logp)
        rec = {"rc": rc, "log": os.path.relpath(logp, REPO)}
        for k, pat in PATS.items():
            m = pat.search(text)
            if m:
                rec[k] = float(m.group(1))
        if not any(k in rec for k in PATS):
            rec["log_tail"] = text[-2500:]
        out["arms"][label] = rec
        log("  %s -> %s" % (label, {k: v for k, v in rec.items()
                                    if k in PATS}))
        json.dump(out, open(OUT, "w"), indent=1)
    json.dump(out, open(OUT, "w"), indent=1)
    try:
        os.remove(BASE_DAT); log("deleted the base .dat (bulk, one command remakes it)")
    except OSError:
        pass
    log("wrote %s" % OUT)


if __name__ == "__main__":
    main()
