#!/usr/bin/env python3
"""The quant ladder, measured in BLOCKS so every rung carries an error bar.

    kld-blocks.py [--blocks 4] [--chunks-per-block 50] [--dry-run]

WHY BLOCKS RATHER THAN ONE LONG PASS. The existing ladder runs 200 chunks in a
single pass per file and reports one mean KL divergence per rung with no
uncertainty attached at all. That is the campaign's central quality table, and
every accuracy claim rests on numbers that cannot say how much they would move
if a different 200 chunks of text had been chosen.

Splitting the same 200 chunks into 4 blocks of 50 costs only the extra model
loads and yields four independent estimates per rung. The standard error across
blocks IS the corpus-sampling uncertainty - exactly the error bar the table
needs. For estimating a mean, k blocks and one pass of the same total size have
the same standard error; the difference is that k blocks also MEASURE the
spread, and one pass cannot.

The same argument is why this campaign's speed probes have always been run in
threes rather than once at triple length. It had simply never been applied to
the quality ladder.

AND IT IS CHEAPER ON DISK, which was the original constraint. --kl-divergence
needs a base-logits file from the anchor, and at 200 chunks against a
151,936-token vocabulary that file is about 23.6 GiB. Processed block by block,
only one block's base exists at a time: peak disk falls to about 5.9 GiB. The
base is deleted before the next block begins.

WHAT THE BLOCKS ARE. The corpus is split into equal byte ranges and the first
`--chunks-per-block` chunks of each range are used, so the blocks sample
different regions of the text rather than four passes over the same words.
Blocks are therefore independent draws from the corpus, which is what makes
their spread meaningful.
"""
import argparse, io, json, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
PPL = r"E:\AI\llama.cpp\llama-perplexity.exe"
UNS = r"C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF"
CORPUS = os.path.join(ROOT, "corpora", "wikitext-2-raw-test.raw")
OUT = os.path.join(ROOT, "results", "qwen38-27b-blind", "data", "quant-ladder")
WORK = os.path.join(OUT, "blocks-work")

ANCHOR = ("UD-IQ4_XS", os.path.join(UNS, "Qwen3.8-27B-UD-IQ4_XS.gguf"))
RUNGS = [
    ("UD-Q3_K_XL", 3.895), ("UD-IQ3_XXS", 3.240), ("UD-Q2_K_XL", 2.912),
    ("UD-IQ2_S", 2.481), ("UD-IQ2_XXS", 2.153), ("UD-IQ1_M", 1.994),
    ("UD-IQ1_S", 1.835),
]
# Identical to the single-pass ladder. If these diverge the two tables stop
# being comparable, which is the whole point of keeping the older numbers.
FLAGS = ["-ngl", "99", "-c", "512", "-fa", "on", "--load-mode", "mmap"]

METRICS = {
    "mean_kld": r"Mean KLD:\s*([0-9.eE+-]+)",
    "max_kld": r"Maximum KLD:\s*([0-9.eE+-]+)",
    "same_top_p_pct": r"Same top p:\s*([0-9.]+)",
    "ppl_ratio": r"PPL ratio:\s*([0-9.]+)",
    "rms_dp": r"RMS Δp:\s*([0-9.]+)|RMS delta p:\s*([0-9.]+)",
}


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def shard(nblocks):
    """Split the corpus into equal byte ranges, on line boundaries.

    Line boundaries matter: cutting mid-line would hand the tokenizer a
    fragment and shift every chunk after it, so the blocks would not be
    comparable to each other or to the single-pass run.
    """
    os.makedirs(WORK, exist_ok=True)
    lines = io.open(CORPUS, encoding="utf-8", errors="replace").readlines()
    per = len(lines) // nblocks
    paths = []
    for b in range(nblocks):
        lo = b * per
        hi = len(lines) if b == nblocks - 1 else (b + 1) * per
        p = os.path.join(WORK, "block-%d.raw" % b)
        io.open(p, "w", encoding="utf-8").writelines(lines[lo:hi])
        paths.append(p)
    return paths


def run(args, timeout=14400):
    r = subprocess.run(args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return (r.stdout or "") + "\n" + (r.stderr or ""), r.returncode


def parse(txt):
    out = {}
    for k, pat in METRICS.items():
        m = re.search(pat, txt)
        if m:
            v = next((g for g in m.groups() if g), None)
            if v:
                try:
                    out[k] = float(v)
                except ValueError:
                    pass
    return out


def stats(vals):
    """Mean, sample standard deviation and standard error of the mean.

    Sample standard deviation (n-1), not population: these blocks are a SAMPLE
    of possible corpus draws, not the whole population of them.
    """
    n = len(vals)
    if n == 0:
        return {}
    m = sum(vals) / n
    if n == 1:
        return {"mean": m, "sd": None, "sem": None, "n": 1,
                "note": "single block - no spread measurable"}
    var = sum((x - m) ** 2 for x in vals) / (n - 1)
    sd = var ** 0.5
    return {"mean": m, "sd": sd, "sem": sd / (n ** 0.5), "n": n,
            "ci95_lo": m - 1.96 * sd / (n ** 0.5),
            "ci95_hi": m + 1.96 * sd / (n ** 0.5)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--blocks", type=int, default=4)
    ap.add_argument("--chunks-per-block", type=int, default=50)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if not os.path.exists(PPL):
        sys.exit("llama-perplexity not found at %s" % PPL)
    if not os.path.exists(CORPUS):
        sys.exit("corpus not found at %s" % CORPUS)
    os.makedirs(OUT, exist_ok=True)

    paths = shard(a.blocks)
    log("corpus split into %d blocks of ~%d lines each"
        % (a.blocks, sum(1 for _ in io.open(paths[0], encoding='utf-8',
                                            errors='replace'))))
    log("%d chunks per block x %d blocks = %d chunks total (the single-pass "
        "ladder used 200)" % (a.chunks_per_block, a.blocks,
                              a.chunks_per_block * a.blocks))
    if a.dry_run:
        for p in paths:
            log("  %s  %.1f MiB" % (os.path.basename(p),
                                    os.path.getsize(p) / 1048576.0))
        log("dry run - nothing measured")
        sys.exit(0)

    per_rung = {name: [] for name, _ in RUNGS}
    for b, cpath in enumerate(paths):
        base = os.path.join(WORK, "base-block-%d.dat" % b)
        log("=== block %d/%d ===" % (b + 1, a.blocks))
        log("  generating anchor logits (%s)" % ANCHOR[0])
        txt, rc = run([PPL, "-m", ANCHOR[1], "-f", cpath] + FLAGS +
                      ["--chunks", str(a.chunks_per_block),
                       "--save-all-logits", base])
        if rc != 0 or not os.path.exists(base):
            log("  anchor FAILED (rc=%d) - block skipped, and said so rather "
                "than quietly shrinking the sample" % rc)
            continue
        log("  base is %.1f GiB" % (os.path.getsize(base) / 1073741824.0))
        try:
            for name, bpw in RUNGS:
                f = os.path.join(UNS, "Qwen3.8-27B-%s.gguf" % name)
                if not os.path.exists(f):
                    log("  %-12s file missing - skipped" % name)
                    continue
                t0 = time.time()
                txt, rc = run([PPL, "-m", f, "-f", cpath] + FLAGS +
                              ["--chunks", str(a.chunks_per_block),
                               "--kl-divergence-base", base, "--kl-divergence"])
                met = parse(txt)
                if rc != 0 or "mean_kld" not in met:
                    log("  %-12s FAILED rc=%d" % (name, rc))
                    continue
                met.update({"block": b, "bpw": bpw,
                            "seconds": round(time.time() - t0, 1)})
                per_rung[name].append(met)
                log("  %-12s KLD %.5f  top1 %.2f%%  (%.0f s)"
                    % (name, met["mean_kld"],
                       met.get("same_top_p_pct", float('nan')),
                       met["seconds"]))
        finally:
            # Delete before the next block: holding all four bases at once
            # would put peak disk back where blocking was meant to reduce it.
            try:
                os.remove(base)
            except OSError:
                pass

    log("=== ladder with error bars ===")
    rows = []
    print("  %-12s %6s  %-26s  %-22s" % ("file", "bpw",
                                         "mean KLD +/- sd (n)", "top-1 agreement %"))
    for name, bpw in RUNGS:
        got = per_rung[name]
        if not got:
            print("  %-12s %6.3f  no successful block" % (name, bpw))
            continue
        k = stats([g["mean_kld"] for g in got])
        t = stats([g["same_top_p_pct"] for g in got if "same_top_p_pct" in g])
        rows.append({"file": name, "bpw": bpw, "blocks": len(got),
                     "mean_kld": k, "same_top_p_pct": t, "raw": got})
        ksd = ("+/- %.5f" % k["sd"]) if k.get("sd") is not None else "(1 block)"
        tsd = ("+/- %.2f" % t["sd"]) if t.get("sd") is not None else ""
        print("  %-12s %6.3f  %.5f %-14s (%d)  %.2f %s"
              % (name, bpw, k["mean"], ksd, k["n"],
                 t.get("mean", float('nan')), tsd))

    json.dump({"date": time.strftime("%Y-%m-%d %H:%M"),
               "anchor": ANCHOR[0],
               "anchor_caveat": "agreement with the UD-IQ4_XS ANCHOR, not with "
                                "FP16 - not comparable to anyone else's KLD table",
               "blocks": a.blocks, "chunks_per_block": a.chunks_per_block,
               "flags": FLAGS, "rows": rows},
              io.open(os.path.join(OUT, "kld-blocks.json"), "w",
                      encoding="utf-8"), indent=1)
    log("wrote %s" % os.path.join(OUT, "kld-blocks.json"))
    for p in paths:
        try:
            os.remove(p)
        except OSError:
            pass
