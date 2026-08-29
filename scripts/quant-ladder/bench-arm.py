"""Run ONE arm of the quant-ladder decisive (equal-budget) benchmark.

    python -u bench-arm.py <tag> <model-gguf> <family: qwen|gemma>

The equal-budget question: at ~6.5 GiB of weights, does a 12B trained for 4-bit
(gemma-4-12B-it-QAT-Q4_0) beat a 27B crushed down to the same file size?
Perplexity cannot answer it - the two tokenizers cut the corpus differently, so
raw PPL compares nothing across the families (METHODOLOGY rule 6). Scored
benchmarks can: they are tokenizer-independent.

Conditions (identical for every arm unless noted):
    --greedy --score --seed 42 --samples 25 --max-tokens 16384
    --datasets GSM8K,HumanEval,MBPP
    --suite  scripts/bench/suites/rule21-n25.json   (hash 1cdf54f8eb9d3f8f,
             the same frozen prompts the published effort sweep used - rule 23)
    -c 32768 so the 16,384-token cap can never be clipped by the window (rule 16)

NOT a rule-21 run: rule 21 is the identical SEVEN-benchmark suite and its Mean
is a composite index over all seven. This is a three-benchmark arm and is
labelled as such; `--rule21` is deliberately NOT passed so nothing stamps the
rule-21 protocol name into the result JSON.

Per-family server args:
    qwen  : -ctk q8_0 -ctv q8_0, reasoning_effort=low, NO MTP drafter - exactly
            the prior harness runs. The JSON in --chat-template-kwargs is why
            this is Python: PowerShell 5.1 mangles it on a command line
            (reference/platform-notes.md), subprocess' list2cmdline does not.
    gemma : its own defaults. No effort knob, no KV override. Recorded as a
            deliberate conditions difference, not a fair-fight claim.
"""

import datetime
import json
import os
import shutil
import sys
import time

BENCH = r"E:\AI\measured-inference\scripts\bench"
OUT = r"E:\AI\measured-inference\results\qwen38-27b-blind\data\quant-ladder\bench"
SRV = os.environ.get("LLAMA_SERVER",
                              r"E:\AI\llama.cpp\llama-server.exe")
PORT = "1236"
DATASETS = "GSM8K,HumanEval,MBPP"

# The cap lives in the SUITE file, not on the command line: bench.py overwrites
# --samples / --max-tokens / --seed from suite["settings"] whenever --suite is
# given. So a rule-7 cap raise means swapping in the raised-cap copy of the same
# frozen prompts - identical hash 1cdf54f8eb9d3f8f, identical prompts, only
# max_tokens differs. This is the same pair the published effort sweep used.
SUITES = {
    "16384": (os.path.join(BENCH, "suites", "rule21-n25.json"), "32768"),
    "32768": (r"E:\AI\measured-inference\results\qwen38-27b-blind\work"
              r"\rule21-n25-cap32768.json", "65536"),
}

try:
    sys.stdout.reconfigure(line_buffering=True)
except AttributeError:
    pass


def main():
    if len(sys.argv) < 4:
        sys.exit("usage: bench-arm.py <tag> <model-gguf> <qwen|gemma> [max_tokens]")
    tag, model, family = sys.argv[1], sys.argv[2], sys.argv[3].lower()
    max_tokens = sys.argv[4] if len(sys.argv) > 4 else "16384"
    if max_tokens not in SUITES:
        sys.exit("cap must be one of %s (each has its own frozen suite copy)"
                 % sorted(SUITES))
    suite, ctx = SUITES[max_tokens]
    if not os.path.exists(model):
        sys.exit("model not found: %s" % model)
    if not os.path.exists(suite):
        sys.exit("suite not found: %s" % suite)

    if family == "qwen":
        sargs = ('-ctk q8_0 -ctv q8_0 --chat-template-kwargs '
                 '{"reasoning_effort":"low"}')
    elif family == "gemma":
        sargs = ""
    else:
        sys.exit("family must be qwen or gemma")

    os.chdir(BENCH)
    sys.path.insert(0, BENCH)
    resdir = os.path.join(BENCH, "results")
    os.makedirs(resdir, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    before = set(os.listdir(resdir))

    sys.argv = ["bench.py",
                "--model", model,
                "--server-bin", SRV,
                "--suite", suite,
                "--datasets", DATASETS,
                "--ctx", ctx,
                "--greedy",
                "--score",
                "--transcripts",
                "--port", PORT]
    if sargs:
        sys.argv += ["--server-args", sargs]

    print("=== DECISIVE ARM %s ===" % tag)
    print("model       : %s" % model)
    print("family      : %s" % family)
    print("datasets    : %s (three-benchmark arm, NOT the rule-21 seven)" % DATASETS)
    print("suite       : %s" % suite)
    print("server-args : %s" % (sargs or "(model defaults)"))
    print("cap         : %s   window: -c %s" % (max_tokens, ctx))
    print("started     : %s" % datetime.datetime.now().isoformat(timespec="seconds"))

    import bench
    t0 = time.time()
    try:
        bench.main()
    except SystemExit as e:
        print("bench.main() exited: %s" % e)
    except BaseException as e:                      # noqa: BLE001
        print("bench.main() raised: %r" % (e,))
        raise
    finally:
        wall = time.time() - t0
        print("wall_s=%.1f  (%.2f h)" % (wall, wall / 3600.0))
        for f in sorted(set(os.listdir(resdir)) - before):
            shutil.copy2(os.path.join(resdir, f),
                         os.path.join(OUT, "arm-%s-%s" % (tag, f)))
            print("copied %s" % f)
        log = os.path.join(resdir, "llama-server.log")
        if os.path.exists(log):
            shutil.copy2(log, os.path.join(OUT, "arm-%s-llama-server.log" % tag))
        meta = {"arm": tag, "family": family, "model": model,
                "datasets": DATASETS, "samples": 25, "seed": 42,
                "max_tokens": int(max_tokens), "ctx": int(ctx),
                "greedy": True, "suite": suite, "server_args": sargs,
                "wall_s": round(wall, 1), "wall_h": round(wall / 3600.0, 3),
                "finished": datetime.datetime.now().isoformat(timespec="seconds")}
        with open(os.path.join(OUT, "arm-%s-wall.json" % tag), "w",
                  encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        print("ARM %s DONE" % tag)


if __name__ == "__main__":
    main()
