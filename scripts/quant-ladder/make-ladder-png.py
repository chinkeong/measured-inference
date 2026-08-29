# -*- coding: utf-8 -*-
"""The shareable PNG of the quantisation ladder, rendered FROM THE MEASUREMENTS.

    python scripts/quant-ladder/make-ladder-png.py
    python scripts/quant-ladder/make-ladder-png.py --check     # draw nothing
    python scripts/quant-ladder/make-ladder-png.py --out other.png
    python scripts/quant-ladder/make-ladder-png.py --self-test  # --out cases

WHAT THIS IS, AND WHAT IT IS NOT. This writes
E:\\chinkeong.github.io\\qwen-27b\\quant-ladder.png, the standalone image that
can be posted somewhere other than the guide page. It is NOT
scripts/quant-ladder/make-ladder-chart.py - that one emits the inline SVG
<figure> the guide page itself carries. Two artifacts, two places, two files.

WHY IT EXISTS AT ALL. The PNG went into the site repo as a binary on
2026-08-25 (commit fa22f86) and its renderer was never committed: it was left
in a session scratchpad under Temp/claude/ and would have vanished with the
temp tree. That scratchpad copy was recovered and rebuilt on 2026-08-27; its
output was byte-identical to the published file (md5 4b6ae433...), which is
what proved it was the real renderer. This file replaces it, in the repo, with
an ABSOLUTE output path, so nobody has to guess again.

NOTHING HAPPENS WHEN THIS FILE IS IMPORTED, as of 2026-08-30. Every load, every
cross-check and the drawing itself sit inside main() behind an argument parser,
and the figure is written on the last line of a run somebody asked for. Before
that the whole body was module level, and that is not a style point:
scripts/verify/probe-smoke-test.py imports every tracked script to prove it
LOADS, a file with no main() and no parser is exactly what that checker calls a
library module, and so the cheap pre-check rewrote the published 280,937-byte
figure every time it ran - measured 2026-08-29 and named in that checker's own
header. `--check` runs every guard below and draws nothing, which is the form
for a machine whose published figure must not move; `--out` sends the figure
somewhere else, as $LADDER_PNG_OUT already did. `--out` with a BARE FILENAME -
the third line above - crashed until 2026-08-30, after every source had been
read and the figure drawn, because os.makedirs("") raises rather than doing
nothing; `--self-test` is the four cases that would have caught it, and
scripts/verify/run-all.py runs them.

AND IT READS ITS NUMBERS. The recovered renderer hard-coded every value with
no file reads at all, which is how the picture drifted from the sources: by
2026-08-27 it was still drawing eight files when nine had been measured, and
still asserting a census - "Eight files" - in its own subtitle. Every value
below is now loaded from the artifact that produced it and cross-checked; the
script raises rather than draws if a source is missing or disagrees.

THREE CLAIMS THE OLD PICTURE MADE THAT THE DATA DOES NOT SUPPORT, all fixed
here, all found by audit rather than by re-reading the chart:

  1. "empty answers - exactly zero above 2.48" was wrong twice over. 2.481 is
     itself above 2.48, so the sentence included UD-IQ2_S, which has two; and
     QAT-Q2_0 at 2.595 bpw has one. It now reads "exactly zero down to 2.912
     bits", which is what was measured.

  2. The step the chart leant on as an early warning - 0 of 75 at 2.912
     against 2 of 75 at 2.481 - is Fisher exact p = 0.4966. The campaign
     computed that itself (scripts/quant-ladder/overnight.py). An unresolved
     step must not be drawn as a threshold, so the label says it is not
     resolved.

  3. "Four different tests" and "independent witnesses" cannot both be true.
     Every empty answer in every arm is ALSO scored as a failure - checked
     here, nine arms, zero exceptions - so the empty series is a strict SUBSET
     of the accuracy series, off the same 75 greedy generations. Three
     independent instruments, not four: perplexity on wikitext, the scored
     75-item suite (with the empty count as a component of its losses), and
     the execute probe on a separate prompt.

TWO LATER CORRECTIONS, 2026-08-27, neither of which moves the boundary:

  4. The "did the code it wrote run?" row drew QAT-Q2_0 as a diamond. That row
     is the only binary thing on the chart and it had three symbols in it, so
     a reader had to stop and look for a third meaning that is not there. It
     is now the ordinary pass dot. The diamonds stay in the plot above, where
     they distinguish an off-ladder file from the ladder's polylines.

  5. The empty-answer column is measured with greedy decoding - temperature 0,
     top_k 1 - so a repeat of the run is identical. Nobody runs the model that
     way. The one rung re-counted at the sampling the model card recommends,
     over 300 fresh generations, gave an order of magnitude fewer empties than
     its column entry, and the red label now says so. Only that rung is
     quoted: the same artifact holds an unfinished row for another file, and
     read_empty_power() refuses to read it.

TWO CHANGES OF PRESENTATION, 2026-08-27. Neither moves a number; both are about
how much of a reader's attention a side note is allowed to take.

  6. QAT-Q2_0 carried a five-row block in the open middle of the plot: a
     heading, a subtitle, and three rows arguing that its KL divergence is
     2.3x what this ladder predicts AT ITS OWN BIT RATE - a figure obtained by
     INTERPOLATING the PTQ curve between the two rungs it sits between. That
     is the fairest form of the point and it is also the most technical thing
     on the canvas, defending a claim almost no reader had come to check; at
     five rows it read as a second headline rather than as a footnote. It is
     now one sentence on two rows, tucked under its own diamonds, making the
     one comparison that needs no model at all: it carries more bits per
     weight than the IQ2_S file below it and still diverges further from the
     4-bit reference (0.297 against 0.141, both measured). The interpolated
     form is still computed and still printed to stdout. Its markers are
     untouched - three hollow diamonds in the plot, an ordinary pass dot in
     the execute row.

     Worth recording, because it is why the wording is "diverges further" and
     not "scores worse": on the three series this chart actually draws,
     QAT-Q2_0 is not worse than the IQ2_S file below it. Accuracy is an exact
     tie (68 of 75 each), it has one empty answer against IQ2_S's two, and its
     perplexity is slightly the better of the pair (+13.71% against +14.44%).
     KL divergence is the only instrument on which the extra 0.115 bits per
     weight visibly fail to pay, which is exactly why the note names it.

  7. The empty-answer caveat threw three ratios at the reader in one breath -
     one in 300, at most one in 100, and 3 of 75 - so none of them landed, and
     it spent two of its five rows paraphrasing greedy decoding as "decoding
     fixed to always pick the likeliest next word" for an audience that has
     the word. It now names the decoding, names both temperatures, and states
     the contrast once. The rule-of-three upper bound moved to stdout; the
     guard that it stays below the plotted rate did not move, and a new guard
     requires the sampled rate to be several times smaller, which is what
     makes "mostly disappear" a measurement rather than an impression.

Nothing about the central finding changed, and it is better supported than it
was: the functional boundary is still between 2.481 and 2.153 bits per weight,
still with two witnesses that share no machinery - the accuracy cliff and a
JavaScript parser. Correction 5 qualifies ONE series and touches neither
witness; the checks beside it refuse to draw if it ever starts to.
"""

import argparse
import ast
import glob
import json
import math
import os
import re
import textwrap

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
from scipy.stats import binomtest, fisher_exact

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
ROOT = os.path.join(REPO, "results", "qwen38-27b-blind")
QL   = os.path.join(ROOT, "data", "quant-ladder")
# The published PNG lands in the site repo, which is NOT this repository and is
# not on every machine. $LADDER_PNG_OUT names it; without one the figure is
# written beside the campaign's other figures, where it can always be written.
OUT  = os.environ.get("LADDER_PNG_OUT",
                      os.path.join(ROOT, "figures", "quant-ladder.png"))

REFERENCE = "UD-IQ4_XS"
N_ITEMS   = 75
# The one rung that has been re-counted under sampling, and the ONLY one the
# empty-answer caveat is allowed to quote. empties-power.json also carries an
# unfinished row for a second file; an unfinished count must never reach a
# caption, so read_empty_power() refuses to read it.
POWER_FILE = "UD-IQ2_XXS"

# The eight Unsloth rungs, biggest first. One publisher, one production
# method, so a line through them is meaningful.
LADDER = ["UD-IQ4_XS", "UD-Q3_K_XL", "UD-IQ3_XXS", "UD-Q2_K_XL",
          "UD-IQ2_S", "UD-IQ2_XXS", "UD-IQ1_M", "UD-IQ1_S"]
# The ninth file: sdkyuan/qwen3.8-27B-qat-q2_0-gguf. Quantisation-aware
# TRAINING, not post-training quantisation of the same recipe, so it is drawn
# off the lines - joining it to its neighbours would assert the one thing this
# ladder cannot show, that bits per weight explains where a file lands.
OFF_LADDER = "QAT-Q2_0"

# arm transcript prefix -> ladder name. The cap-32k reruns are excluded: for
# every arm that has one the score is identical, and decisive.txt records the
# 16,384-cap arm as the published result.
ARM_PREFIX = {
    "arm-qwen-iq4xs-anchor-": "UD-IQ4_XS",
    "arm-qwen-q3kxl-":        "UD-Q3_K_XL",
    "arm-qwen-iq3xxs-":       "UD-IQ3_XXS",
    "arm-qwen-q2kxl-":        "UD-Q2_K_XL",
    "arm-qwen-iq2s-Q":        "UD-IQ2_S",
    "arm-qwen-iq2xxs-Q":      "UD-IQ2_XXS",
    "arm-qwen-iq1m-":         "UD-IQ1_M",
    "arm-qwen-iq1s-Q":        "UD-IQ1_S",
    "arm-qwen-qat-q2_0-q":    "QAT-Q2_0",
}


def die(msg):
    raise SystemExit("make-ladder-png: " + msg)


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------- bpw and PPL
def read_bpw_and_ppl():
    """data/quant-ladder/results.txt RESULT rows, plus the QAT file's own two
    artifacts. The QAT bpw is taken from bpw_ladder_convention, NOT from the
    GGUF's true parameter count: the ladder fixes the denominator at 27e9 for
    every rung, and mixing conventions would move this file 0.01 bpw for no
    measurement reason."""
    bpw, ppl, size = {}, {}, {}
    txt = os.path.join(QL, "results.txt")
    for line in open(txt, encoding="utf-8"):
        if not line.startswith("RESULT "):
            continue
        fields = [f.strip() for f in line.split("|")]
        name = fields[0][len("RESULT "):].strip()
        if name not in LADDER:
            continue
        kv = dict(f.split("=", 1) for f in fields[1:] if "=" in f)
        if kv.get("ppl_comparable") != "yes":
            die("%s in results.txt is not marked ppl_comparable" % name)
        bpw[name] = float(kv["bpw"])
        ppl[name] = float(kv["PPL"].replace(",", ""))
        size[name] = int(kv["bytes"])

    v = load(os.path.join(QL, "qat-q2_0", "verify.json"))
    p = load(os.path.join(QL, "qat-q2_0", "ppl.json"))
    t = load(os.path.join(QL, "qat-q2_0", "tokens.json"))
    bpw[OFF_LADDER] = float(v["bpw_ladder_convention"])
    ppl[OFF_LADDER] = float(p["ppl"])
    size[OFF_LADDER] = int(v["bytes"])
    # Rule 6 by measurement, not assumption: a perplexity comparison across
    # files is only legitimate on an identical tokenization of an identical
    # corpus. Both are checked here rather than asserted in a caption.
    ref_tokens = None
    for line in open(txt, encoding="utf-8"):
        if line.startswith("RESULT " + REFERENCE + " "):
            kv = dict(f.split("=", 1) for f in
                      (x.strip() for x in line.split("|")[1:]) if "=" in f)
            ref_tokens = int(kv["tokens"])
    if int(t["tokens"]) != ref_tokens:
        die("QAT tokenizes the corpus to %s tokens, reference to %s - the "
            "perplexity comparison is not legitimate" % (t["tokens"], ref_tokens))
    if v["corpus_md5"] != p["corpus_md5"]:
        die("QAT verify/ppl disagree on the corpus md5")

    missing = [n for n in LADDER + [OFF_LADDER] if n not in bpw]
    if missing:
        die("no bits-per-weight for " + ", ".join(missing))
    return bpw, ppl, size


# ------------------------------------------- scored accuracy and empty counts
def read_arms():
    """Real counts of 75, from the stored transcripts - not the ARM ledger's
    rounded mean. Also settles, rather than assumes, whether the empty count
    is an independent instrument: it counts how many empty answers were
    nonetheless scored as passes."""
    passes, empties, empty_pass, items = {}, {}, 0, {}
    bench = os.path.join(QL, "bench")
    for prefix, name in ARM_PREFIX.items():
        hits = [f for f in glob.glob(os.path.join(bench, "arm-qwen-*_transcripts.json"))
                if os.path.basename(f).startswith(prefix)]
        if len(hits) != 1:
            die("expected one transcript for %s, found %d" % (name, len(hits)))
        gen = load(hits[0])["generations"]
        k = e = n = 0
        per_item = {}
        for suite, rows in gen.items():
            for it in rows:
                n += 1
                ok = bool(it.get("score"))
                k += ok
                per_item[(suite, it["index"])] = ok
                if not str(it.get("response", "")).strip():
                    e += 1
                    empty_pass += ok
        if n != N_ITEMS:
            die("%s graded %d items, expected %d" % (name, n, N_ITEMS))
        passes[name], empties[name], items[name] = k, e, per_item
    return passes, empties, empty_pass, items


def mcnemar(items, a, b):
    """Exact paired test on the SAME 75 items. This is the test every p-value
    on the chart quotes, and it is far more powerful than comparing two
    unpaired rates - which is exactly why the accuracy uncertainty is written
    as a caveat rather than drawn as an unpaired band."""
    x = items[a]
    y = items[b]
    if set(x) != set(y):
        die("%s and %s were not graded on the same items" % (a, b))
    a_only = sum(1 for k in x if x[k] and not y[k])
    b_only = sum(1 for k in x if y[k] and not x[k])
    if a_only + b_only == 0:
        return a_only, b_only, 1.0
    return a_only, b_only, binomtest(min(a_only, b_only),
                                     a_only + b_only, 0.5).pvalue


# ---------------------------------------------------------- the execute probe
def read_execute():
    """data/quant-ladder/execute-probe.json. RUNS is the verdict; `shape` is
    how the model continued the prompt and is NOT a verdict. QAT-Q2_0's shape
    is RE-EMITTED - it repeated the prompt's last line before carrying on,
    which made the harness's own concatenation look like a syntax error. That
    was a splice bug in the probe, fixed; the program runs. So the shape is
    read for the record and the RESULT field decides the marker."""
    probe = load(os.path.join(QL, "execute-probe.json"))
    runs, shape = {}, {}
    for row in probe["results"]:
        runs[row["file"]] = (row["result"] == "RUNS")
        shape[row["file"]] = row["shape"]
    for n in LADDER + [OFF_LADDER]:
        if n not in runs:
            die("no execute-probe result for " + n)
    return runs, shape


# --------------------------------------------------------------- KL divergence
def read_kld():
    """data/quant-ladder/kld-errorbars.json. Agreement with the UD-IQ4_XS
    ANCHOR, not with FP16 - never comparable against anyone else's KLD table,
    which is why it is quoted only as a ratio between files measured here."""
    return {r["file"]: (r["kld"], r["kld_se"])
            for r in load(os.path.join(QL, "kld-errorbars.json"))}


# ------------------------------------- what the empty count is worth, and why
def read_samplers():
    """scripts/quant-ladder/overnight.py names the two decoding settings that
    produced the two empty counts the chart now compares. The caveat calls one
    of them "greedy decoding (temperature 0)" and the other "the sampling the
    model card recommends", and PRINTS BOTH TEMPERATURES from this dict, so
    the numbers on the canvas come from the runner that produced the counts
    rather than from memory. If either stops being what the caveat says it is,
    this raises."""
    src = open(os.path.join(HERE, "overnight.py"), encoding="utf-8").read()
    out = {}
    for name in ("GREEDY", "SHIPPED"):
        m = re.search(r"^%s\s*=\s*(\{[^}]*\})" % name, src, re.M)
        if not m:
            die("overnight.py no longer defines " + name)
        out[name] = ast.literal_eval(m.group(1))
    if out["GREEDY"].get("temperature") != 0 or out["GREEDY"].get("top_k") != 1:
        die("the ladder arms are no longer decoded greedily (%r) - the "
            "empty-answer caveat says greedy decoding, temperature 0"
            % out["GREEDY"])
    if not out["SHIPPED"].get("temperature"):
        die("the better-powered rerun is no longer sampled (%r) - the "
            "empty-answer caveat contrasts it with greedy decoding"
            % out["SHIPPED"])
    return out


def read_empty_power():
    """data/overnight/empties-power.json: the better-powered re-count of empty
    answers under the publisher's own sampling settings. Only a COMPLETED row
    is accepted, and only for POWER_FILE. The recorded rate is cross-checked
    against its own counts so a stale rate_pct cannot reach the caption."""
    doc = load(os.path.join(ROOT, "data", "overnight", "empties-power.json"))
    rows = {r["file"]: r for r in doc.get("rows", [])}
    if doc.get("in_progress", {}).get("file") == POWER_FILE:
        die("%s is still in progress in empties-power.json - an unfinished "
            "count must not be drawn" % POWER_FILE)
    if POWER_FILE not in rows:
        die("no completed empties-power row for " + POWER_FILE)
    r = rows[POWER_FILE]
    got = r["empty"] / float(r["generations"]) * 100.0
    if abs(got - r["rate_pct"]) > 0.01:
        die("empties-power %s records rate_pct %.2f but %d of %d is %.2f%%"
            % (POWER_FILE, r["rate_pct"], r["empty"], r["generations"], got))
    if r["rule_of_three_upper_pct"] <= r["rate_pct"]:
        die("empties-power %s upper bound %.2f%% is not above its own rate"
            % (POWER_FILE, r["rule_of_three_upper_pct"]))
    return r


# ------------------------------------------------------------------ statistics
def wilson(k, n, z=1.96):
    p = k / float(n)
    d = 1.0 + z * z / n
    centre = (p + z * z / (2.0 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4.0 * n * n)) / d
    return (centre - half) * 100.0, (centre + half) * 100.0


def interp(x, x0, y0, x1, y1):
    return y0 + (x - x0) / (x1 - x0) * (y1 - y0)


WORDS = {0: "no", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
         6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}


def word(n):
    """Small counts read as words in a sentence and as digits in a table. The
    caveat is a sentence, so it gets the words - and it gets them from the
    count, not from a literal spelled out by hand."""
    return WORDS.get(n, "%d" % n)


def temp(v):
    """A temperature as this audience writes it: 0, or 1.0."""
    return ("%.1f" % v) if v else "0"


# =============================================================== load and check
def read_truncations(arm):
    """decisive.txt ARM ledger. UD-IQ1_S's score is published WITH its 20
    truncations of 75 reported (the rule-7 cap-32k rerun was killed and never
    produced a result), so the footnote says so rather than plotting it as an
    ordinary point."""
    hit = None
    for line in open(os.path.join(QL, "decisive.txt"), encoding="utf-8"):
        if line.startswith("ARM " + arm + " ") and "truncations=" in line:
            hit = int(re.search(r"truncations=(\d+)", line).group(1))
    if hit is None:
        die("no truncation count for arm " + arm)
    return hit


def ensure_out_dir(path):
    """Create the directory `path` is written into. Returns it, or "" for none.

    `--out other.png` - the invocation the usage block at the top of this file
    documents - has no directory component. `os.path.dirname` of it is "", and
    `os.makedirs("")` is not a no-op: it raises FileNotFoundError [WinError 3
    on Windows]. Until 2026-08-30 this was one unguarded line at the end of
    main(), so that form died with every source already read and the whole
    figure already drawn, which is the most expensive place a path bug can
    live. `--self-test` runs the cases.
    """
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    return d


def self_test():
    """Exercise --out handling, the one branch here that draws nothing.

    Four cases in a temporary directory, each one a shape a caller has already
    typed: the bare filename from line 6 of this file, a relative directory
    that does not exist yet, an absolute one that does not either, and the
    same call twice. Case 1 is the regression: it raised FileNotFoundError on
    2026-08-30 and this is what would have caught it before a user did.
    Registered as `ladder-png` in scripts/verify/run-all.py.
    """
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp(prefix="ladder-png-selftest-")
    cwd = os.getcwd()
    done = []
    try:
        os.chdir(tmp)

        # 1. A BARE FILENAME - the crash. "" is not a directory to create, and
        #    the write that follows still has to land.
        if ensure_out_dir("bare.png") != "":
            raise AssertionError("a bare filename names no directory to create")
        open("bare.png", "w").close()
        done.append("bare filename: no directory made, file written")

        # 2. A relative directory that does not exist yet.
        rel = os.path.join("sub", "deeper", "fig.png")
        if ensure_out_dir(rel) != os.path.join("sub", "deeper"):
            raise AssertionError("wrong directory for %r" % rel)
        if not os.path.isdir(os.path.join(tmp, "sub", "deeper")):
            raise AssertionError("relative --out directory was not created")
        done.append("relative directory: created")

        # 3. An absolute one that does not exist yet.
        absdir = os.path.join(tmp, "abs", "figures")
        ensure_out_dir(os.path.join(absdir, "fig.png"))
        if not os.path.isdir(absdir):
            raise AssertionError("absolute --out directory was not created")
        done.append("absolute directory: created")

        # 4. Twice. exist_ok, so a second run into the same place is not a
        #    failure - which is what every re-render of the published figure is.
        ensure_out_dir(os.path.join(absdir, "fig.png"))
        done.append("existing directory: no error on the second call")
    finally:
        os.chdir(cwd)
        shutil.rmtree(tmp, ignore_errors=True)

    for line in done:
        print("  ok   %s" % line)
    print("self-test: %d --out case(s) passed. Nothing loaded, nothing drawn."
          % len(done))
    return 0


def main(argv=None):
    """Load every source, run every check above, and draw the figure.

    Guarded, and the guard is the whole point. Until 2026-08-30 this body was
    module level, so scripts/verify/probe-smoke-test.py -- which imports every
    tracked script to prove it LOADS, and which calls a file with no main() a
    library module -- rewrote the published 280,937-byte figure every time it
    ran. Importing this file now reads nothing, draws nothing and writes
    nothing; the figure moves only when somebody types the command.
    """
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=OUT, metavar="PNG",
                    help="where the figure is written (default: %(default)s, "
                         "which $LADDER_PNG_OUT overrides)")
    ap.add_argument("--self-test", action="store_true",
                    help="run the --out path cases in a temporary directory "
                         "and exit; loads no source and draws nothing")
    ap.add_argument("--check", action="store_true",
                    help="load every source and run every cross-check, print "
                         "the diagnostics, and draw nothing and write nothing "
                         "-- the form to run on a machine whose published "
                         "figure must not move")
    # `args`, not the `a` the rest of scripts/quant-ladder/ uses: the drawing
    # below binds `a` twice, in `for a in (ax, strip)`, and a namespace that
    # has to survive to the savefig line cannot be one of them.
    args = ap.parse_args(argv)

    # Before any source is read: the cases below touch nothing this campaign
    # owns, and a run that only wants them should not pay for nine files.
    if args.self_test:
        return self_test()

    BPW, PPL, BYTES = read_bpw_and_ppl()
    PASS, EMPTY, EMPTY_THAT_PASSED, ITEMS = read_arms()
    RUNS, SHAPE = read_execute()
    KLD = read_kld()
    ARMS = load(os.path.join(ROOT, "data", "compare-arms.json"))
    IQ1S_TRUNC = read_truncations("qwen-iq1s")
    POWER = read_empty_power()
    SAMPLERS = read_samplers()

    # Claim 3, settled by counting rather than by argument. If a single empty
    # answer ever scored a pass, the empty series would carry information the
    # accuracy series does not, and the "independent instruments" wording would be
    # defensible. None did.
    if EMPTY_THAT_PASSED:
        die("%d empty answers scored as passes - the subtitle's 'three independent "
            "instruments' is wrong and must be re-checked" % EMPTY_THAT_PASSED)

    # THE CAVEAT ON THE RED SERIES, and what makes it true. Every count in the
    # empty-answer column comes from ONE deterministic pass: temperature 0, top_k
    # 1, so the model always takes the likeliest next word and a repeat is
    # identical. That is not how anyone runs the model, and it is not a small
    # difference. The one rung re-counted under the publisher's own sampling
    # settings - 300 fresh generations - produced an order of magnitude fewer
    # empties. Both halves of that sentence are checked here rather than asserted:
    # the sampled rate must genuinely be the lower one, and it must be lower by
    # enough that the caption's contrast is worth the space it takes.
    POWER_RATE  = POWER["empty"] / float(POWER["generations"]) * 100.0
    GREEDY_RATE = EMPTY[POWER_FILE] / float(N_ITEMS) * 100.0
    if EMPTY[POWER_FILE] == 0:
        die("%s has no empty answers in the plotted column - the caveat contrasts "
            "it with a smaller sampled count" % POWER_FILE)
    if POWER_RATE >= GREEDY_RATE:
        die("%s: sampled %.2f%% is not below the fixed-decoding %.2f%% - the "
            "empty-answer caveat no longer holds" % (POWER_FILE, POWER_RATE,
                                                     GREEDY_RATE))
    if POWER["rule_of_three_upper_pct"] >= GREEDY_RATE:
        die("%s: the sampled upper bound %.2f%% reaches the fixed-decoding rate "
            "%.2f%% - the caveat's 'at most' clause says otherwise"
            % (POWER_FILE, POWER["rule_of_three_upper_pct"], GREEDY_RATE))
    # And the caveat must not be allowed to move the boundary. The break this
    # chart is about sits between UD-IQ2_S and UD-IQ2_XXS and rests on the execute
    # probe and on perplexity, neither of which the empty column touches. If the
    # re-counted file ever stopped being BELOW that break, a caveat about its
    # empty count would be sitting on the recommendation itself.
    if BPW[POWER_FILE] >= BPW["UD-IQ2_S"]:
        die("%s is no longer below the boundary - a caveat about its empty count "
            "would now qualify the recommended side of the chart" % POWER_FILE)
    if RUNS[POWER_FILE] or not RUNS["UD-IQ2_S"]:
        die("the execute probe no longer separates UD-IQ2_S from %s - the "
            "boundary this chart draws does not rest on the empty column alone"
            % POWER_FILE)

    # THE SENTENCE ITSELF. Two counts, one comparison, and both temperatures read
    # out of overnight.py rather than typed here. What it no longer does is quote a
    # third ratio. It used to say "1 empty in 300 answers - at most 1 in 100, not
    # 3 of 75", which is three ratios for one point, and a reader has to hold two
    # of them to use the third. The rule-of-three upper bound is a real number and
    # it is still checked above; it is a stdout line now, because its job is to
    # stop one-in-300 being read as luck, and a reader who has not yet suspected
    # luck does not need it.
    #
    # "mostly disappear" is the one qualitative phrase on this label, so it gets a
    # quantitative guard: the sampled rate has to be several times smaller, not
    # merely smaller. The check above only requires "below".
    EMPTY_PER_100 = GREEDY_RATE
    if abs(EMPTY_PER_100 - round(EMPTY_PER_100)) > 0.005:
        die("%s's plotted empty rate is %.3f in a hundred - the caveat states it "
            "as a whole number and would be rounding a measurement into a claim"
            % (POWER_FILE, EMPTY_PER_100))
    if GREEDY_RATE / POWER_RATE < 3.0:
        die("%s: sampling cuts empties only %.1fx (%.2f%% to %.2f%%) - the caveat "
            "says they 'mostly disappear'"
            % (POWER_FILE, GREEDY_RATE / POWER_RATE, GREEDY_RATE, POWER_RATE))
    CAVEAT = ("Counted with greedy decoding (temperature\u00a0%s). Sampled as the "
              "model card recommends (temperature\u00a0%s), empty answers mostly "
              "disappear: the %.2f-bit file gave %s empty answer%s in %d tries, "
              "against the %s in a hundred shown here."
              % (temp(SAMPLERS["GREEDY"]["temperature"]),
                 temp(SAMPLERS["SHIPPED"]["temperature"]),
                 BPW[POWER_FILE], word(POWER["empty"]),
                 "" if POWER["empty"] == 1 else "s", POWER["generations"],
                 word(int(round(EMPTY_PER_100)))))

    REF_PASS, REF_PPL = PASS[REFERENCE], PPL[REFERENCE]

    order = sorted(LADDER, key=lambda n: -BPW[n])
    bpw  = [BPW[n] for n in order]
    labs = ["%.2f" % BPW[n] for n in order]
    ppl  = [(PPL[n] - REF_PPL) / REF_PPL * 100.0 for n in order]
    emp  = [EMPTY[n] / float(N_ITEMS) * 100.0 for n in order]
    acc  = [(REF_PASS - PASS[n]) / float(REF_PASS) * 100.0 for n in order]
    runs = [RUNS[n] for n in order]

    QX      = BPW[OFF_LADDER]
    qat_ppl = (PPL[OFF_LADDER] - REF_PPL) / REF_PPL * 100.0
    qat_emp = EMPTY[OFF_LADDER] / float(N_ITEMS) * 100.0
    qat_acc = (REF_PASS - PASS[OFF_LADDER]) / float(REF_PASS) * 100.0

    # The point QAT-Q2_0 makes, in two forms. The FAIRER one - "worse than the
    # ladder predicts AT ITS OWN BIT RATE" - interpolates the PTQ KLD curve
    # between the two rungs it sits between, and that is the form the chart used
    # to argue on the canvas over three rows. It is now a stdout diagnostic. The
    # canvas makes the DIRECT comparison instead: two measured numbers, this file
    # against the smaller file immediately below it, no curve in between.
    kld_qat  = KLD[OFF_LADDER][0]
    kld_below = KLD["UD-IQ2_S"][0]
    kld_hat  = interp(QX, BPW["UD-Q2_K_XL"], KLD["UD-Q2_K_XL"][0],
                      BPW["UD-IQ2_S"],  KLD["UD-IQ2_S"][0])
    kld_x    = kld_qat / kld_hat
    kld_vs_below = kld_qat / kld_below
    bits_more = QX - BPW["UD-IQ2_S"]

    # Widths of a 95% Wilson interval on the real counts, for the accuracy label.
    widths = [wilson(PASS[n], N_ITEMS)[1] - wilson(PASS[n], N_ITEMS)[0] for n in order]

    # The three paired tests the chart quotes, computed rather than transcribed.
    _, _, P_PICK = mcnemar(ITEMS, "UD-Q2_K_XL", REFERENCE)      # the green tie
    _, _, P_QAT  = mcnemar(ITEMS, OFF_LADDER, "UD-IQ2_S")       # the QAT tie
    _, _, P_BUMP = mcnemar(ITEMS, "UD-IQ1_M", "UD-IQ2_XXS")     # the non-monotone bump

    # The empty-answer step the old chart leant on as an early warning. Fisher
    # exact on the two counts it compares, against 75 items each.
    ZERO_FLOOR = min((n for n in order if EMPTY[n] == 0), key=lambda n: BPW[n])
    FIRST_NONZERO = max((n for n in order if EMPTY[n] > 0), key=lambda n: BPW[n])
    P_EMPTY = fisher_exact([[EMPTY[ZERO_FLOOR], N_ITEMS - EMPTY[ZERO_FLOOR]],
                            [EMPTY[FIRST_NONZERO],
                             N_ITEMS - EMPTY[FIRST_NONZERO]]])[1]

    # The agentic pair, for the pick annotation.
    a_cost, b_cost = ARMS["cost"]
    tok_med = ARMS["token_ratio_median"]
    tok_tot = b_cost["tokens_total"] / float(a_cost["tokens_total"])
    j_ratio = b_cost["j_per_solved"] / float(a_cost["j_per_solved"])
    if ARMS["mcnemar_p"] < 0.999:
        die("compare-arms McNemar p is %.4f - the annotation says p=1.00"
            % ARMS["mcnemar_p"])
    # The green annotation says "ties" and the QAT tie is asserted in stdout. If
    # either paired test ever stops being a tie the words have to change, so they
    # are checked, not assumed. The QAT one no longer appears on the canvas - the
    # note there was cut to one sentence - but the diagnostics still print it, and
    # a diagnostic that lies is worse than none.
    for what, p, where in (("UD-Q2_K_XL vs the reference", P_PICK, "the chart"),
                           ("QAT-Q2_0 vs UD-IQ2_S", P_QAT, "the diagnostics")):
        if p < 0.995:
            die("%s is p=%.4f - %s calls it a tie" % (what, p, where))
    if PASS[OFF_LADDER] != PASS["UD-IQ2_S"]:
        die("QAT-Q2_0 %d/75 and UD-IQ2_S %d/75 - the diagnostics say 'each'"
            % (PASS[OFF_LADDER], PASS["UD-IQ2_S"]))
    # The two halves of the one sentence the off-ladder file now gets. Both are
    # direct comparisons against the rung immediately below it, and both are
    # checked here so the sentence cannot outlive the measurement.
    if BPW[OFF_LADDER] <= BPW["UD-IQ2_S"]:
        die("QAT-Q2_0 no longer carries MORE bits than UD-IQ2_S")
    if kld_qat <= kld_below:
        die("QAT-Q2_0 KLD %.4f is no longer above UD-IQ2_S's %.4f - the note says "
            "it diverges further from the reference despite the extra bits"
            % (kld_qat, kld_below))

    # --check stops here. Everything above is loading and cross-checking, and
    # everything below is the drawing plus the one file this script writes, so
    # a run that must not touch the published figure still pays for every
    # guard above and still prints every diagnostic below.
    if args.check:
        print("--check: every source loaded and every cross-check passed. "
              "Nothing drawn; %s not written." % args.out)
    else:

        # ===================================================================== drawing
        SANS, MONO = 'Segoe UI', 'Cascadia Mono'
        INK, MUTED, LINE = '#1d1d1f', '#6e6e73', '#d9d9de'
        ACC, BAD, PICK   = '#0071e3', '#d70015', '#12823f'

        fig = plt.figure(figsize=(12.6, 8.4), dpi=160, facecolor='white')
        L, R = 0.118, 0.752
        AXB, AXH = 0.250, 0.545
        ax    = fig.add_axes([L, AXB, R - L, AXH])
        strip = fig.add_axes([L, 0.136, R - L, 0.042])

        XMIN, XMAX, YMAX = 4.42, 1.70, 70.0
        ax.set_xlim(XMIN, XMAX);    ax.set_ylim(YMAX, 0)
        strip.set_xlim(XMIN, XMAX); strip.set_ylim(0, 1)
        xc = lambda v: L + (R - L) * ((XMIN - v) / (XMIN - XMAX))

        CLIFF = (BPW["UD-IQ2_S"] + BPW["UD-IQ2_XXS"]) / 2.0
        PICKX = BPW["UD-Q2_K_XL"]
        for a in (ax, strip):
            a.add_patch(Rectangle((CLIFF, -200), XMAX - CLIFF, 500,
                                  facecolor=BAD, alpha=0.055, ec='none', zorder=0))
            a.add_patch(Rectangle((PICKX + 0.145, -200), -0.29, 500,
                                  facecolor=PICK, alpha=0.075, ec='none', zorder=0))
            a.axvline(CLIFF, color=BAD, lw=1.1, ls=(0, (3, 3)), alpha=0.6, zorder=1)

        for y in range(0, int(YMAX) + 1, 10):
            ax.axhline(y, color=LINE, lw=0.9, zorder=1)
        ax.set_yticks(range(0, int(YMAX) + 1, 10))
        ax.set_yticklabels(["%d%%" % y for y in range(0, int(YMAX) + 1, 10)],
                           fontname=MONO, fontsize=11, color=MUTED)

        # The off-ladder drop line stands in for the x tick QAT-Q2_0 does not get: its
        # neighbours' ticks are a third of an inch apart at this scale and a ninth
        # tick would collide with "2.48". The line localises the column and says "not
        # one of these rungs" in the same stroke.
        ax.plot([QX, QX], [16.5, YMAX], color=MUTED, lw=1.0, ls=(0, (1, 3)),
                alpha=0.55, zorder=2)
        strip.plot([QX, QX], [0, 1], color=MUTED, lw=1.0, ls=(0, (1, 3)),
                   alpha=0.55, zorder=2)
        fig.add_artist(Line2D([xc(QX), xc(QX)], [0.180, 0.248], color=MUTED, lw=1.0,
                              ls=(0, (1, 3)), alpha=0.55, zorder=2))

        ax.plot(bpw, ppl, color=MUTED, lw=2.0, ls=(0, (1.6, 2.4)), zorder=3,
                solid_capstyle='round')
        ax.plot(bpw, emp, color=BAD,   lw=2.1, ls=(0, (6, 3.2)),  zorder=4)
        ax.plot(bpw, acc, color=ACC,   lw=3.0, zorder=5, solid_capstyle='round')
        for ys, c, s in ((ppl, MUTED, 20), (emp, BAD, 20), (acc, ACC, 42)):
            ax.scatter(bpw, ys, s=s, color=c, zorder=6, edgecolor='white', linewidth=1.4)

        # QAT-Q2_0: hollow diamonds, joined to nothing. Series colour says which
        # instrument the value belongs to; the diamond says different kind of file.
        for yv, c in ((qat_ppl, MUTED), (qat_emp, BAD), (qat_acc, ACC)):
            ax.scatter([QX], [yv], s=64, marker='D', facecolor='white', edgecolor=c,
                       linewidth=2.0, zorder=7)

        for a in (ax, strip):
            for sp in a.spines.values():
                sp.set_visible(False)
            a.set_facecolor('none')
        ax.set_xticks([]); ax.tick_params(axis='y', length=0, pad=7)
        strip.set_xticks([]); strip.set_yticks([])


        # WHY THE ACCURACY UNCERTAINTY IS A LABEL AND NOT A SHADED BAND. Two reasons,
        # and the second decided it.
        #  (a) On the real counts a 95% Wilson interval runs from 8.5 points wide at
        #      73 of 75 to 21.1 at 26 of 75. Drawn on a 0-70% axis the widest of those
        #      is a third of the plot's height, and the ribbon would cover the grey
        #      and red series, the green pick annotation and the QAT block.
        #  (b) Wilson is the interval for ONE unpaired rate. This line is a DIFFERENCE
        #      between two files graded on the SAME 75 items, and every p-value the
        #      chart quotes is the paired one (UD-Q2_K_XL against the reference:
        #      discordant 0:1, McNemar p = 1.0000). Unpaired bands would put a wrong
        #      interval on the chart in place of a missing one, which is worse than
        #      stating the resolution in words.
        def rlabel(y, color, title, subs, note=()):
            """`note` is a caveat on the series, not another bullet of it: set a step
            smaller, after a gap, so a reader takes it as a qualification of the lines
            above rather than as one more measured fact of equal standing."""
            yy = AXB + AXH * (1 - y / YMAX)
            fig.text(R + 0.016, yy, title, ha='left', va='center', fontname=SANS,
                     fontsize=13, color=color, fontweight='bold')
            for i, s in enumerate(subs):
                fig.text(R + 0.016, yy - 0.025 - i * 0.021, s, ha='left', va='center',
                         fontname=SANS, fontsize=10.5, color=MUTED)
            base = yy - 0.025 - (len(subs) - 1) * 0.021 - 0.030
            for i, s in enumerate(note):
                fig.text(R + 0.016, base - i * 0.019, s, ha='left', va='center',
                         fontname=SANS, fontsize=9.8, color=MUTED)


        rlabel(62.0, ACC, "accuracy lost", [
            "a paired statistical tie down to %.2f" % BPW["UD-IQ2_S"],
            "on %d items the 95%% interval is %d\u2013%d points"
            % (N_ITEMS, round(min(widths)), round(max(widths)))])
        # The red block carries the caveat, so it is anchored higher than the series
        # it labels would suggest: six extra rows have to land ABOVE the blue block
        # without crowding it. The grey block moves up with it to keep the three
        # stacked in the order the lines finish at the right-hand edge. The wrap width
        # below is load-bearing for that: at 40 columns the sentence needs a seventh
        # row and the seventh lands on "accuracy lost".
        rlabel(32.0, BAD, "empty answers", [
            "exactly zero down to %.3f bits" % BPW[ZERO_FLOOR],
            "%d of %d vs %d of %d: not resolved, p=%.2f"
            % (EMPTY[ZERO_FLOOR], N_ITEMS, EMPTY[FIRST_NONZERO], N_ITEMS, P_EMPTY),
            "every empty answer is also a failed one"],
            note=textwrap.wrap(CAVEAT, 41))
        rlabel(20.0, MUTED, "worse at predicting text", [
            "perplexity, on fixed Wikipedia prose"])

        for x, ok in zip(bpw, runs):
            if ok:
                strip.scatter([x], [0.55], s=115, color=ACC, zorder=6,
                              edgecolor='white', linewidth=1.6)
            else:
                for a_, b_ in ((0.30, 0.80), (0.80, 0.30)):
                    strip.plot([x - 0.030, x + 0.030], [a_, b_], color=BAD, lw=2.7,
                               solid_capstyle='round', zorder=6)
        # QAT-Q2_0's code RUNS, so it gets the ORDINARY pass marker: same dot, same
        # colour, same size as every other file that passed. This row is the only
        # binary thing on the chart - one yes/no question, two symbols - and a third
        # shape in it sends a reader hunting for a third meaning that does not exist.
        # The diamonds are kept where they earn their keep, in the plot above, where
        # they say "this file is not a rung of these polylines". Here there are no
        # polylines and nothing to be off; there is only "did it run", and it did.
        # (Its probe row reads shape RE-EMITTED, which is how the model continued the
        # prompt and not a verdict - the harness's own splice made that look like a
        # syntax error. The RESULT field says RUNS.)
        strip.scatter([QX], [0.55], s=115, color=ACC, zorder=6,
                      edgecolor='white', linewidth=1.6)
        strip.text(XMIN + 0.045, 0.55, "did the code\nit wrote run?", ha='right', va='center',
                   fontname=SANS, fontsize=10.5, color=MUTED, linespacing=1.25, clip_on=False)

        for x, lb, n in zip(bpw, labs, order):
            p = (x == PICKX)
            fig.text(xc(x), 0.232, lb, ha='center', va='top', fontname=MONO,
                     fontsize=13, color=PICK if p else INK)
            fig.text(xc(x), 0.206, n.replace("UD-", ""), ha='center', va='top', fontname=MONO,
                     fontsize=9.5, color=PICK if p else MUTED)

        # The off-ladder note. It was five rows sitting in the open middle of the
        # plot - heading, subtitle, and three rows of argument from an interpolated KL
        # divergence - which is how a footnote turns into a second headline. It is one
        # sentence now, on two rows, and it has moved UP out of the middle to sit
        # directly under its own diamonds, so it reads as a caption on those three
        # markers rather than as a panel of its own. Right-aligned against the drop
        # line, which is what ties it to the column.
        #
        # What it says is what a reader needs and no more: whose file this is, and the
        # one comparison that needs no interpolation - more bits per weight than the
        # rung below it, and further from the 4-bit reference all the same. The
        # interpolated version of that second clause, which is the fairer one, is a
        # stdout line now.
        QT = 2.655
        for y, size, colour, text in (
                (21.5, 10.0, INK,
                 "QAT-Q2_0  \u00b7  %.3f bits  \u00b7  another vendor's QAT build, not an "
                 "Unsloth rung" % QX),
                (24.7, 9.5, MUTED,
                 "%.3f more bits per weight than IQ2_S below it, and %.1f\u00d7 its KL "
                 "divergence" % (bits_more, kld_vs_below))):
            ax.text(QT, y, text, ha='right', va='center', fontname=SANS,
                    fontsize=size, color=colour, zorder=8)

        fig.text(L - 0.046, 0.963, "Qwen3.8-27B: where the quant ladder actually breaks",
                 ha='left', va='top', fontname=SANS, fontsize=23, color=INK, fontweight='bold')
        fig.text(L - 0.046, 0.919,
                 "Nine files of one model, three independent instruments, "
                 "all measured against "
                 "the 4-bit UD-IQ4_XS reference. Same 75 questions, one RTX 3090.",
                 ha='left', va='top', fontname=SANS, fontsize=12.5, color=MUTED)
        fig.text(L - 0.046, 0.866, "% worse than that reference  \u2193",
                 ha='left', va='center', fontname=SANS, fontsize=11, color=MUTED)
        fig.text(L - 0.012, 0.232, "bits per weight", ha='right', va='top',
                 fontname=SANS, fontsize=10.5, color=MUTED)
        fig.text(L - 0.012, 0.206, "smaller file \u2192", ha='right', va='top',
                 fontname=SANS, fontsize=10.5, color=MUTED)

        fig.text(xc(2.06), 0.114, "\u2190 nothing below this line runs",
                 ha='left', va='top', fontname=SANS, fontsize=11.5, color=BAD)
        fig.text(xc(PICKX), 0.878, "UD-Q2_K_XL \u00b7 %.3f real bits" % PICKX,
                 ha='center', va='center', fontname=SANS, fontsize=14, color=PICK,
                 fontweight='bold')
        fig.text(xc(PICKX), 0.851,
                 "%.2f GB \u00b7 ties the 4-bit file, p=%.2f \u00b7 zero "
                 "empties \u00b7 code runs"
                 % (BYTES["UD-Q2_K_XL"] / 1e9, P_PICK),
                 ha='center', va='center', fontname=SANS, fontsize=11, color=PICK)
        fig.text(xc(PICKX), 0.828,
                 "the same tie over %d agentic coding tasks \u2014 but at %d\u2013%d%% more "
                 "tokens and %d%% more energy per solved task"
                 % (ARMS["paired_n"], round((tok_med - 1) * 100), round((tok_tot - 1) * 100),
                    round((j_ratio - 1) * 100)),
                 ha='center', va='center', fontname=SANS, fontsize=10.5, color=PICK)
        ax.annotate("", xy=(PICKX, 0.4), xytext=(PICKX, -2.4), annotation_clip=False,
                    arrowprops=dict(arrowstyle='-|>', color=PICK, lw=1.5,
                                    shrinkA=0, shrinkB=0))

        # Two things the drawing shows and never labelled. The accuracy series is not
        # monotone below the cliff, and the bottom rung's score comes from a run that
        # stopped answering rather than answering badly.
        fig.text(L - 0.046, 0.075,
                 "At %.2f bits and below, the ranking is noise: the "
                 "%.2f-bit file scores ABOVE the "
                 "%.2f-bit one (%d and %d of %d, paired p=%.2f), and the %.2f-bit score "
                 "carries %d truncated answers of %d."
                 % (BPW["UD-IQ2_XXS"], BPW["UD-IQ1_M"], BPW["UD-IQ2_XXS"],
                    PASS["UD-IQ1_M"], PASS["UD-IQ2_XXS"], N_ITEMS, P_BUMP,
                    BPW["UD-IQ1_S"], IQ1S_TRUNC, N_ITEMS),
                 ha='left', va='center', fontname=SANS, fontsize=9.5, color=MUTED)

        fig.text(L - 0.046, 0.043,
                 "Measured 2026-08-21\u201327 \u00b7 RTX 3090, driver "
                 "596.36, llama.cpp build 10502",
                 ha='left', va='center', fontname=SANS, fontsize=10, color=MUTED)
        fig.text(0.972, 0.043, "chinkeong.github.io/qwen-27b",
                 ha='right', va='center', fontname=SANS, fontsize=10, color=MUTED)

        ensure_out_dir(args.out)
        fig.savefig(args.out, facecolor='white')
        print("wrote %s" % args.out)

    print("  9 files, reference %s = %d/%d, PPL %.4f"
          % (REFERENCE, REF_PASS, N_ITEMS, REF_PPL))
    print("  %s: %.4f bpw, PPL %.4f (+%.2f%%), %d/75, %d empty, execute %s (shape %s)"
          % (OFF_LADDER, QX, PPL[OFF_LADDER], qat_ppl, PASS[OFF_LADDER],
             EMPTY[OFF_LADDER], "RUNS" if RUNS[OFF_LADDER] else "FAILS", SHAPE[OFF_LADDER]))
    print("  KLD %.4f vs UD-IQ2_S %.4f = %.2fx (the canvas note); against %.4f "
          "interpolated at its own bit rate = %.2fx (the fairer form, cut from "
          "the canvas 2026-08-27)"
          % (kld_qat, kld_below, kld_vs_below, kld_hat, kld_x))
    print("  QAT-Q2_0 vs UD-IQ2_S on the three DRAWN series: accuracy %d and %d "
          "of %d (paired p=%.2f), empties %d and %d, PPL +%.2f%% and +%.2f%% - "
          "worse on none of them, which is why the note names KLD"
          % (PASS[OFF_LADDER], PASS["UD-IQ2_S"], N_ITEMS, P_QAT,
             EMPTY[OFF_LADDER], EMPTY["UD-IQ2_S"], qat_ppl,
             (PPL["UD-IQ2_S"] - REF_PPL) / REF_PPL * 100.0))
    print("  %d empty answers scored a pass" % EMPTY_THAT_PASSED)
    print("  Wilson widths %.1f to %.1f points; agentic tokens x%.3f median / x%.3f total,"
          " energy x%.3f" % (min(widths), max(widths), tok_med, tok_tot, j_ratio))
    print("  paired p: pick %.4f, QAT tie %.4f, 1.99-vs-2.15 bump %.4f; empty step"
          " Fisher %.4f (%s %d vs %s %d)"
          % (P_PICK, P_QAT, P_BUMP, P_EMPTY, ZERO_FLOOR, EMPTY[ZERO_FLOOR],
             FIRST_NONZERO, EMPTY[FIRST_NONZERO]))
    print("  empties under decoding fixed (%r) vs sampled (%r):"
          % (SAMPLERS["GREEDY"], SAMPLERS["SHIPPED"]))
    print("    %s %d of %d = %.2f%% plotted, against %d of %d = %.2f%% "
          "(rule-of-three upper limit %.2f%%, at most one in %d - checked, cut "
          "from the canvas 2026-08-27) - a factor of %.1f"
          % (POWER_FILE, EMPTY[POWER_FILE], N_ITEMS, GREEDY_RATE, POWER["empty"],
             POWER["generations"], POWER_RATE, POWER["rule_of_three_upper_pct"],
             round(100.0 / POWER["rule_of_three_upper_pct"]),
             GREEDY_RATE / POWER_RATE))
    print("    caveat as drawn: %s" % CAVEAT.replace("\u00a0", " "))
    print("  agentic pair: %d exercises, %.1f%% vs %.1f%%, discordant %d and %d, "
          "McNemar p=%.2f"
          % (ARMS["paired_n"], ARMS["a_pass"], ARMS["b_pass"], ARMS["a_only"],
             ARMS["b_only"], ARMS["mcnemar_p"]))


if __name__ == "__main__":
    main()
