# -*- coding: utf-8 -*-
"""The shareable PNG of the quantisation ladder, rendered FROM THE MEASUREMENTS.

    python scripts/quant-ladder/make-ladder-png.py

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

Nothing about the central finding changed, and it is better supported than it
was: the functional boundary is still between 2.481 and 2.153 bits per weight,
still with two witnesses that share no machinery - the accuracy cliff and a
JavaScript parser.
"""

import glob
import json
import math
import os
import re

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
from scipy.stats import binomtest, fisher_exact

ROOT = r"E:\AI\measured-inference\results\qwen38-27b-blind"
QL   = os.path.join(ROOT, "data", "quant-ladder")
OUT  = r"E:\chinkeong.github.io\qwen-27b\quant-ladder.png"

REFERENCE = "UD-IQ4_XS"
N_ITEMS   = 75

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


# ------------------------------------------------------------------ statistics
def wilson(k, n, z=1.96):
    p = k / float(n)
    d = 1.0 + z * z / n
    centre = (p + z * z / (2.0 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4.0 * n * n)) / d
    return (centre - half) * 100.0, (centre + half) * 100.0


def interp(x, x0, y0, x1, y1):
    return y0 + (x - x0) / (x1 - x0) * (y1 - y0)


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


BPW, PPL, BYTES = read_bpw_and_ppl()
PASS, EMPTY, EMPTY_THAT_PASSED, ITEMS = read_arms()
RUNS, SHAPE = read_execute()
KLD = read_kld()
ARMS = load(os.path.join(ROOT, "data", "compare-arms.json"))
IQ1S_TRUNC = read_truncations("qwen-iq1s")

# Claim 3, settled by counting rather than by argument. If a single empty
# answer ever scored a pass, the empty series would carry information the
# accuracy series does not, and the "independent instruments" wording would be
# defensible. None did.
if EMPTY_THAT_PASSED:
    die("%d empty answers scored as passes - the subtitle's 'three independent "
        "instruments' is wrong and must be re-checked" % EMPTY_THAT_PASSED)

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

# The point QAT-Q2_0 makes, in the fairest form available: not "worse than the
# file below it" but "worse than the ladder predicts AT ITS OWN BIT RATE".
# Interpolate the PTQ KLD curve between the two rungs it sits between.
kld_qat = KLD[OFF_LADDER][0]
kld_hat = interp(QX, BPW["UD-Q2_K_XL"], KLD["UD-Q2_K_XL"][0],
                 BPW["UD-IQ2_S"],  KLD["UD-IQ2_S"][0])
kld_x   = kld_qat / kld_hat
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
# Both annotations use the words "ties" and "exact tie". If either paired test
# ever stops being a tie the words have to change, so they are checked, not
# assumed.
for what, p in (("UD-Q2_K_XL vs the reference", P_PICK),
                ("QAT-Q2_0 vs UD-IQ2_S", P_QAT)):
    if p < 0.995:
        die("%s is p=%.4f - the chart calls it a tie" % (what, p))
if PASS[OFF_LADDER] != PASS["UD-IQ2_S"]:
    die("QAT-Q2_0 %d/75 and UD-IQ2_S %d/75 - the chart says 'each'"
        % (PASS[OFF_LADDER], PASS["UD-IQ2_S"]))
if BPW[OFF_LADDER] <= BPW["UD-IQ2_S"]:
    die("QAT-Q2_0 no longer carries MORE bits than UD-IQ2_S")

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

ax.plot(bpw, ppl, color=MUTED, lw=2.0, ls=(0, (1.6, 2.4)), zorder=3, solid_capstyle='round')
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
def rlabel(y, color, title, subs):
    yy = AXB + AXH * (1 - y / YMAX)
    fig.text(R + 0.016, yy, title, ha='left', va='center', fontname=SANS,
             fontsize=13, color=color, fontweight='bold')
    for i, s in enumerate(subs):
        fig.text(R + 0.016, yy - 0.025 - i * 0.021, s, ha='left', va='center',
                 fontname=SANS, fontsize=10.5, color=MUTED)


rlabel(62.0, ACC, "accuracy lost", [
    "a paired statistical tie down to %.2f" % BPW["UD-IQ2_S"],
    "on %d items the 95%% interval is %d\u2013%d points"
    % (N_ITEMS, round(min(widths)), round(max(widths)))])
rlabel(45.0, BAD, "empty answers", [
    "exactly zero down to %.3f bits" % BPW[ZERO_FLOOR],
    "%d of %d vs %d of %d: not resolved, p=%.2f"
    % (EMPTY[ZERO_FLOOR], N_ITEMS, EMPTY[FIRST_NONZERO], N_ITEMS, P_EMPTY),
    "every empty answer is also a failed one"])
rlabel(30.0, MUTED, "worse at predicting text", [
    "perplexity, on fixed Wikipedia prose"])

for x, ok in zip(bpw, runs):
    if ok:
        strip.scatter([x], [0.55], s=115, color=ACC, zorder=6,
                      edgecolor='white', linewidth=1.6)
    else:
        for a_, b_ in ((0.30, 0.80), (0.80, 0.30)):
            strip.plot([x - 0.030, x + 0.030], [a_, b_], color=BAD, lw=2.7,
                       solid_capstyle='round', zorder=6)
# QAT-Q2_0's code RUNS, so it gets a pass marker in the pass colour. A cross
# would be false. Diamond, not dot, only to keep one visual language with its
# markers above; the colour carries the verdict and the verdict is a pass.
strip.scatter([QX], [0.55], s=112, marker='D', color=ACC, zorder=6,
              edgecolor='white', linewidth=1.6)
strip.text(XMIN + 0.045, 0.55, "did the code\nit wrote run?", ha='right', va='center',
           fontname=SANS, fontsize=10.5, color=MUTED, linespacing=1.25, clip_on=False)

for x, lb, n in zip(bpw, labs, order):
    p = (x == PICKX)
    fig.text(xc(x), 0.232, lb, ha='center', va='top', fontname=MONO,
             fontsize=13, color=PICK if p else INK)
    fig.text(xc(x), 0.206, n.replace("UD-", ""), ha='center', va='top', fontname=MONO,
             fontsize=9.5, color=PICK if p else MUTED)

# The off-ladder block, right-aligned against the drop line, in the empty
# quadrant under the curves.
QT = 2.655
for y, size, colour, weight, text in (
        (36.0, 11.5, INK, 'bold',
         "QAT-Q2_0  \u00b7  %.3f bits  \u00b7  not an Unsloth rung" % QX),
        (39.4, 10.0, MUTED, 'normal',
         "a vendor quantisation-aware-trained build, drawn off the lines"),
        (44.2, 10.0, INK, 'normal',
         "%.3f MORE bits per weight than IQ2_S below it, and it buys nothing:"
         % bits_more),
        (47.4, 10.0, INK, 'normal',
         "an exact tie on accuracy (%d of %d each, p=%.2f), and %.1f\u00d7 the KL"
         % (PASS[OFF_LADDER], N_ITEMS, P_QAT, kld_x)),
        (50.6, 10.0, INK, 'normal',
         "divergence this ladder predicts at its bit rate (%.3f against %.3f)"
         % (kld_qat, kld_hat))):
    ax.text(QT, y, text, ha='right', va='center', fontname=SANS,
            fontsize=size, color=colour, fontweight=weight, zorder=8)

fig.text(L - 0.046, 0.963, "Qwen3.8-27B: where the quant ladder actually breaks",
         ha='left', va='top', fontname=SANS, fontsize=23, color=INK, fontweight='bold')
fig.text(L - 0.046, 0.919,
         "Nine files of one model, three independent instruments, all measured against "
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
         "%.2f GB \u00b7 ties the 4-bit file, p=%.2f \u00b7 zero empties \u00b7 code runs"
         % (BYTES["UD-Q2_K_XL"] / 1e9, P_PICK),
         ha='center', va='center', fontname=SANS, fontsize=11, color=PICK)
fig.text(xc(PICKX), 0.828,
         "the same tie over %d agentic coding tasks \u2014 but at %d\u2013%d%% more "
         "tokens and %d%% more energy per solved task"
         % (ARMS["paired_n"], round((tok_med - 1) * 100), round((tok_tot - 1) * 100),
            round((j_ratio - 1) * 100)),
         ha='center', va='center', fontname=SANS, fontsize=10.5, color=PICK)
ax.annotate("", xy=(PICKX, 0.4), xytext=(PICKX, -2.4), annotation_clip=False,
            arrowprops=dict(arrowstyle='-|>', color=PICK, lw=1.5, shrinkA=0, shrinkB=0))

# Two things the drawing shows and never labelled. The accuracy series is not
# monotone below the cliff, and the bottom rung's score comes from a run that
# stopped answering rather than answering badly.
fig.text(L - 0.046, 0.075,
         "At %.2f bits and below, the ranking is noise: the %.2f-bit file scores ABOVE the "
         "%.2f-bit one (%d and %d of %d, paired p=%.2f), and the %.2f-bit score "
         "carries %d truncated answers of %d."
         % (BPW["UD-IQ2_XXS"], BPW["UD-IQ1_M"], BPW["UD-IQ2_XXS"],
            PASS["UD-IQ1_M"], PASS["UD-IQ2_XXS"], N_ITEMS, P_BUMP,
            BPW["UD-IQ1_S"], IQ1S_TRUNC, N_ITEMS),
         ha='left', va='center', fontname=SANS, fontsize=9.5, color=MUTED)

fig.text(L - 0.046, 0.043,
         "Measured 2026-08-21\u201327 \u00b7 RTX 3090, driver 596.36, llama.cpp build 10502",
         ha='left', va='center', fontname=SANS, fontsize=10, color=MUTED)
fig.text(0.972, 0.043, "chinkeong.github.io/qwen-27b",
         ha='right', va='center', fontname=SANS, fontsize=10, color=MUTED)

fig.savefig(OUT, facecolor='white')
print("wrote %s" % OUT)
print("  9 files, reference %s = %d/%d, PPL %.4f" % (REFERENCE, REF_PASS, N_ITEMS, REF_PPL))
print("  %s: %.4f bpw, PPL %.4f (+%.2f%%), %d/75, %d empty, execute %s (shape %s)"
      % (OFF_LADDER, QX, PPL[OFF_LADDER], qat_ppl, PASS[OFF_LADDER],
         EMPTY[OFF_LADDER], "RUNS" if RUNS[OFF_LADDER] else "FAILS", SHAPE[OFF_LADDER]))
print("  KLD %.4f against %.4f interpolated = %.2fx; %d empty answers scored a pass"
      % (kld_qat, kld_hat, kld_x, EMPTY_THAT_PASSED))
print("  Wilson widths %.1f to %.1f points; agentic tokens x%.3f median / x%.3f total,"
      " energy x%.3f" % (min(widths), max(widths), tok_med, tok_tot, j_ratio))
print("  paired p: pick %.4f, QAT tie %.4f, 1.99-vs-2.15 bump %.4f; empty step"
      " Fisher %.4f (%s %d vs %s %d)"
      % (P_PICK, P_QAT, P_BUMP, P_EMPTY, ZERO_FLOOR, EMPTY[ZERO_FLOOR],
         FIRST_NONZERO, EMPTY[FIRST_NONZERO]))
