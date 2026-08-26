#!/usr/bin/env python3
"""Ranked sensitivity chart: which lever actually moves the outcome.

Every number in _LEVERS below was MEASURED in this campaign on one machine
(RTX 3090 24 GB, i5-13600KF, Windows 11, llama.cpp build 10502). Nothing here
is modelled, extrapolated or taken from a vendor sheet. Where a lever's effect
on the other metric was never measured, the row carries an explicit
"not measured" marker instead of a zero-length bar, because a reader must be
able to tell "measured as no effect" from "nobody measured it".

Two axes, deliberately NOT shared: throughput is tokens per second and energy
is joules per token. They have opposite polarity (more throughput is better,
fewer joules is better), so they are drawn in separate panels, each labelled
with which direction is the good one.
"""
import os
import sys

import matplotlib
matplotlib.use("Agg")            # REQUIRED - never an interactive backend
import matplotlib.pyplot as plt
import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.dirname(_HERE) not in sys.path:
    sys.path.insert(0, os.path.dirname(_HERE))
import archdata as A                                    # noqa: E402

TITLE = "Which lever moves the outcome"

# ---------------------------------------------------------------- palette
# Okabe-Ito. Polarity is encoded the SAME way in both panels - blue is the
# better outcome, orange the worse one - and it is also carried by the side of
# zero and by the printed value, so colour is never the only distinction.
_C_GOOD = "#0072B2"      # blue
_C_BAD = "#E69F00"       # orange
_C_RANGE = "#56B4E9"     # light blue: a measured RANGE, not a point estimate
_C_UNRES = "#8C8C8C"     # grey bar: measured, but inside the rig's noise band
_C_NM = "#5A5A5A"        # grey mark: never measured at all
_C_BAND = "#C7C7C7"      # instrument noise band
_INK = "#1a1a1a"

# ------------------------------------------------- measured instrument floor
# Both are measurements of the rig, not of a lever, and they decide which of
# the bars below mean anything at all.
_TPUT_BAND = 1.1   # % total range, one fixed arm reloaded 16 times (refarm.py)
_JTOK_BAND = 2.9   # % noise floor on J/token, B1/C1/D2 triplicate

# ------------------------------------------------------------------- levers
# tput / jtok are percent change caused by moving the lever in the named
# direction. None means the campaign never measured it. tput_range is a
# measured interval where no single point estimate exists.
_LEVERS = [
    dict(
        name="Speculative decoding (MTP)\ndraft head off -> on",
        tput=119.4, tput_lab="+119.4%",
        jtok=-60.4, jtok_lab="-60.4%",
        note="45.2 -> 99.16 t/s = 2.19x, UD-IQ4_XS, mean accepted\n"
             "length 3.55. Energy is a SEPARATE arm: 8.104 -> 3.210\n"
             "J per decode token (2.52x). Decode watts are flat\n"
             "(344.6 -> 341.0 W), so the energy win IS the speed win.",
    ),
    dict(
        name="Quantisation format\nIQ2_S -> Q2_0, equal size",
        tput=30.0, tput_lab="+30%",
        jtok=None,
        note="Q2_0 62.92 t/s vs IQ2_S 47.76 t/s, drafter off in both,\n"
             "separate server loads (ratio 1.32; published as +30%).\n"
             "Q2_0 is also 70 MiB SMALLER: 9,437 vs 9,507 MiB.\n"
             "IQ codebook lookups cost compute per weight.",
    ),
    dict(
        name="ngram-mod drafter\n(files with no MTP layers)",
        tput=None, tput_range=(10.0, 48.0),
        tput_lab="+10% to +48% (measured range)",
        jtok=None,
        note="Six content types, one load each: 1.10x (AVL tree) to\n"
             "1.48x (refactor). No point estimate exists, so the bar\n"
             "is the measured range. MTP beats it 1.81-2.39x on\n"
             "everything except prose - this is the fallback lever.",
    ),
    dict(
        name="Power cap\n350 -> 250 W",
        tput=-12.8, tput_lab="-12.8%",
        jtok=-13.7, jtok_lab="-13.7%",
        note="Board power -24.8%, SM clock -22.1%, 75.61 -> 65.90 t/s.\n"
             "CAVEAT: measured on synthetic decode that never reached\n"
             "the 350 W cap (305.4 W mean). Agentic work sits AT the\n"
             "cap, so this curve is not shown to transfer to it.",
    ),
    dict(
        name="Host CPU contention\nquiet -> 18 busy processes",
        tput=-5.4, tput_lab="-5.4%", tput_whisker=-24.0,
        tput_whisker_lab="worst pair -24.0%",
        jtok=None,
        note="73.77 -> 69.78 t/s, 12 of 12 pairs negative (sign test\n"
             "p = 0.00024), scatter CV 0.97% -> 6.09%. The SM clock\n"
             "ROSE 0.9% and temperature did not move: this loss is\n"
             "invisible to every GPU log this campaign keeps.",
    ),
    dict(
        name="Power cap\n350 -> 300 W",
        tput=-5.0, tput_lab="-5.0%",
        jtok=-6.5, jtok_lab="-6.5%",
        note="Board power -11.2%, SM clock -5.8%, 75.61 -> 71.82 t/s.\n"
             "Throughput falls about half as fast as power does, which\n"
             "is the efficiency win. Same synthetic-decode caveat as\n"
             "the 250 W row above.",
    ),
    dict(
        name="Sampler\ngreedy -> model-card recommended",
        tput=-2.5, tput_lab="-2.5%",
        jtok=None,
        note="NOT a speed lever - a VARIANCE lever. 25 alternating\n"
             "pairs in one load: CV 0.76% -> 5.61%, spread 3.4% ->\n"
             "24.7% (59.0-76.8 t/s). The -2.5% mean (95% CI 0.2-3.5%)\n"
             "is barely outside the rig's own 1.1% band.",
    ),
    dict(
        name="Host RAM mode\n--load-mode mmap -> none",
        tput=-0.9, tput_lab="-0.9%",
        jtok=None,
        note="43.39 -> 43.02 t/s: INSIDE the instrument band, i.e. no\n"
             "throughput cost was resolvable. What it buys is not on\n"
             "this chart: 12,205 MiB less resident host RAM, paid for\n"
             "with 4 s more load time (6.5 -> 10.6 s).",
    ),
    dict(
        name="KV cache precision\nf16 -> q4_0",
        tput=None, jtok=None,
        note="Never paired for speed or energy on this rig, so both\n"
             "bars are absent rather than zero. What WAS measured is\n"
             "retrieval: 5/5 at 119,435 tokens against 3,600\n"
             "distractors, f16 and q4_0 alike, plus the cache saving.",
    ),
]

_FOOT = (
    "Conditions: one RTX 3090 24 GB (350 W stock cap), i5-13600KF host, "
    "Windows 11, llama.cpp build 10502, Qwen3.8-27B GGUF, single GPU, "
    "-ngl 99.\n"
    "Power is in-band GPU BOARD power as NVML reports it. Wall power, PSU "
    "loss, CPU, system memory, drives and display are excluded and were "
    "never measured (no meter on this rig).\n"
    "Each row was measured in its own arm with its own file, flags and "
    "prompt. These rows are not a factorial sweep and their effects are not "
    "shown to compose."
)


# ---------------------------------------------------------------- helpers
def _live_anchor(ctx):
    """One line of live telemetry so the chart is anchored to a real run.
    Returns a string; never raises, whatever is missing or NaN."""
    if not ctx:
        return "Live reference run: no telemetry context was supplied."
    tag = ctx.get("tag") or "(tag not supplied)"
    run = ctx.get("run") or "(run not supplied)"
    bits = []
    present = False          # was ANY telemetry source handed to us at all?
    try:
        dm = ctx.get("dmon")
        present = present or dm is not None
        if dm is not None and len(dm.get("t", ())) > 1:
            sm = np.asarray(dm["sm"], dtype=float)
            pw = np.asarray(dm["pwr"], dtype=float)
            busy = (sm > A.BUSY_SM_PCT) & np.isfinite(pw)
            if busy.sum() > 0:
                w = pw[busy]
                m = float(np.mean(w))
                cv = 100.0 * float(np.std(w)) / m if m else float("nan")
                bits.append("board power %.0f W mean, %.1f%% CV, over %d busy "
                            "samples (SM > %.0f%%)"
                            % (m, cv, int(busy.sum()), A.BUSY_SM_PCT))
    except Exception:
        pass
    try:
        sl = ctx.get("slots")
        present = present or sl is not None
        if sl is not None and len(sl.get("t", ())) > 2:
            _t, r = A.decode_rate(sl, smooth=1)
            r = np.asarray(r, dtype=float)
            r = r[np.isfinite(r)]
            if len(r):
                bits.append("decode %.1f t/s median over %d intervals"
                            % (float(np.median(r)), len(r)))
    except Exception:
        pass
    if not bits:
        # The distinction this campaign insists on, applied to the figure's
        # own footer: absent instrument, or present instrument reading idle.
        if not present:
            return ("Live reference run %s / %s: NO GPU or slots telemetry "
                    "was supplied to this figure, so it carries no live "
                    "anchor. The lever rows above are unaffected - they are "
                    "prior measurements, not readings from this run."
                    % (tag, run))
        return ("Live reference run %s / %s: telemetry was supplied but "
                "contains no busy samples (SM > %.0f%%) to summarise - the "
                "GPU was idle across it, which is measured, not missing."
                % (tag, run, A.BUSY_SM_PCT))
    return ("Live reference run this figure ships with - %s / %s, drafter ON "
            "at the stock 350 W cap:\n"
            "%s.\n"
            "That is real agentic traffic with prompt processing and decode "
            "interleaved, not the synthetic single-prompt probe the lever "
            "rows above were measured on."
            % (tag, run, "; ".join(bits)))


def _bar_panel(ax, ys, key, lab_key, xlim, good_is_positive, band, nm_side):
    """Draw one metric's bars, its measured ranges and its absences.

    band     the rig's own noise for this metric, in percent. A bar inside it
             was NOT resolved by the instrument and is drawn neutral grey.
    nm_side  which side of zero the "not measured" note goes on, so it never
             collides with the neighbouring panel.
    """
    span = xlim[1] - xlim[0]
    pad = 0.010 * span
    for y, lv in zip(ys, _LEVERS):
        rng = lv.get("tput_range") if key == "tput" else None
        if rng is not None:
            lo, hi = rng
            ax.barh(y, hi - lo, left=lo, height=0.52, color=_C_RANGE,
                    edgecolor=_C_GOOD, linewidth=0.9, zorder=3)
            ax.text(hi + pad, y, lv[lab_key], va="center", ha="left",
                    fontsize=8.3, color=_INK, zorder=5)
            continue
        v = lv.get(key)
        if v is None:
            if nm_side == "left":
                x = -(band + pad * 1.4)
                ha = "right"
            else:
                x = band + pad * 1.4
                ha = "left"
            ax.text(x, y, "not measured", va="center", ha=ha, fontsize=8.0,
                    style="italic", color=_C_NM, zorder=5)
            continue
        if abs(v) <= band:
            # Measured, but the rig cannot resolve it. Drawn neutral, and
            # outlined so it stays visible against the band it sits inside.
            ax.barh(y, v, height=0.52, color=_C_UNRES, edgecolor="#3f3f3f",
                    linewidth=0.8, zorder=3)
        else:
            good = (v > 0) if good_is_positive else (v < 0)
            ax.barh(y, v, height=0.52, color=_C_GOOD if good else _C_BAD,
                    edgecolor="none", zorder=3)
        if key == "tput" and lv.get("tput_whisker") is not None:
            w = lv["tput_whisker"]
            ax.plot([v, w], [y, y], color=_INK, lw=1.0, zorder=4)
            ax.plot([w], [y], marker="|", ms=8, mew=1.2, color=_INK, zorder=4)
            ax.text(w, y + 0.37, lv["tput_whisker_lab"], va="center",
                    ha="left", fontsize=7.2, color="#444444", zorder=5)
        if v >= 0:
            ax.text(v + pad, y, lv[lab_key], va="center", ha="left",
                    fontsize=8.3, color=_INK, zorder=5)
        else:
            ax.text(v - pad, y, lv[lab_key], va="center", ha="right",
                    fontsize=8.3, color=_INK, zorder=5)


def make(ctx, outdir):
    """ctx has keys: tag, run, dmon, slots, host, throttle, requests,
    exercises (any may be None if that source is absent - degrade gracefully,
    never crash). Returns a list of (png_path, caption_string)."""
    ctx = ctx or {}
    if not os.path.isdir(outdir):
        os.makedirs(outdir, exist_ok=True)

    n = len(_LEVERS)
    ys = np.arange(n, dtype=float)

    fig = plt.figure(figsize=(13.2, 9.0), dpi=140, facecolor="white")
    gs = fig.add_gridspec(1, 3, width_ratios=[3.05, 2.05, 3.30],
                          left=0.178, right=0.997, top=0.845, bottom=0.265,
                          wspace=0.075)
    ax_t = fig.add_subplot(gs[0, 0])
    ax_e = fig.add_subplot(gs[0, 1])
    ax_n = fig.add_subplot(gs[0, 2])

    # The throughput axis is LINEAR AND UNBROKEN on purpose: eight levers
    # being slivers beside speculation is the result, not a rendering fault.
    XT = (-34.0, 145.0)
    XE = (-74.0, 11.0)

    for ax, xlim in ((ax_t, XT), (ax_e, XE), (ax_n, (0.0, 1.0))):
        ax.set_xlim(*xlim)
        ax.set_ylim(-0.75, n - 0.25)
        ax.invert_yaxis()
        ax.set_facecolor("white")
        for i in range(n):                    # zebra, to read across panels
            if i % 2 == 0:
                ax.axhspan(i - 0.5, i + 0.5, color="#000000", alpha=0.035,
                           lw=0, zorder=0)

    # instrument noise bands - measured properties of the rig, not of a lever
    ax_t.axvspan(-_TPUT_BAND, _TPUT_BAND, color=_C_BAND, alpha=0.6, lw=0,
                 zorder=1)
    ax_e.axvspan(-_JTOK_BAND, _JTOK_BAND, color=_C_BAND, alpha=0.6, lw=0,
                 zorder=1)

    for ax in (ax_t, ax_e):
        ax.axvline(0, color=_INK, lw=1.0, zorder=2)
        ax.grid(axis="x", alpha=0.3, zorder=0)
        ax.set_axisbelow(True)
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.spines["bottom"].set_color("#888888")
        ax.tick_params(axis="x", labelsize=8.5, colors="#333333")

    _bar_panel(ax_t, ys, "tput", "tput_lab", XT, good_is_positive=True,
               band=_TPUT_BAND, nm_side="right")
    _bar_panel(ax_e, ys, "jtok", "jtok_lab", XE, good_is_positive=False,
               band=_JTOK_BAND, nm_side="left")

    ax_t.set_yticks(ys)
    ax_t.set_yticklabels([lv["name"] for lv in _LEVERS], fontsize=8.6,
                         color=_INK)
    ax_t.tick_params(axis="y", length=0)
    ax_e.set_yticks([])

    ax_t.set_title("THROUGHPUT\nchange in decode rate (%, tokens/s)",
                   fontsize=9.6, color=_INK, pad=9)
    ax_e.set_title("EFFICIENCY\nchange in energy per token (%, J/token)",
                   fontsize=9.6, color=_INK, pad=9)
    ax_n.set_title("what was measured, and under what conditions",
                   fontsize=9.6, color=_INK, pad=9, loc="left")

    # The two marks that are not bars are labelled where they occur rather
    # than in a legend box: "not measured" is written on its own row, and each
    # noise band is explained on the axis it belongs to.
    ax_t.set_xlabel("percent change in tokens/s\n"
                    "RIGHT is faster\n"
                    "grey band = this rig's own %.1f%% throughput noise\n"
                    "(one fixed arm, reloaded 16 times)" % _TPUT_BAND,
                    fontsize=8.4, color=_INK, labelpad=7)
    ax_e.set_xlabel("percent change in J/token\n"
                    "(GPU board power only)\n"
                    "LEFT is more efficient\n"
                    "grey band = %.1f%% J/token noise floor" % _JTOK_BAND,
                    fontsize=8.4, color=_INK, labelpad=7)

    for i, lv in enumerate(_LEVERS):
        ax_n.text(0.005, i, lv["note"], va="center", ha="left", fontsize=6.95,
                  color="#2b2b2b", linespacing=1.26, zorder=5)
    ax_n.set_xticks([])
    ax_n.set_yticks([])
    for s in ("top", "right", "left", "bottom"):
        ax_n.spines[s].set_visible(False)

    fig.suptitle("Ship a draft head first: 2.2x on the same silicon, and no "
                 "other measured lever reaches 1.5x",
                 fontsize=13.5, color=_INK, x=0.008, ha="left", y=0.983)
    fig.text(0.008, 0.958,
             "Energy was measured for only three of these nine levers, and a "
             "bar that stays inside the grey noise band was not resolved by "
             "this rig - those are drawn neutral grey.\n"
             "The throughput axis is linear and unbroken: eight levers being "
             "slivers beside speculation is the result, not a rendering "
             "choice.",
             fontsize=9.0, color="#444444", ha="left", va="top",
             linespacing=1.5)

    fig.text(0.008, 0.086, _live_anchor(ctx), fontsize=7.6, color="#333333",
             ha="left", va="bottom", linespacing=1.5)
    fig.text(0.008, 0.008, _FOOT, fontsize=7.0, color="#555555", ha="left",
             va="bottom", linespacing=1.5)

    png = os.path.join(outdir, "tornado-levers.png")
    fig.savefig(png, dpi=140, facecolor="white")
    plt.close(fig)

    cap = (
        "Ranked sensitivity of every lever this campaign measured, on one "
        "RTX 3090 24 GB (stock 350 W cap) with an i5-13600KF host, Windows 11, "
        "llama.cpp build 10502, Qwen3.8-27B GGUF at -ngl 99. LEFT PANEL is "
        "throughput: percent change in decode tokens per second, right is "
        "faster. MIDDLE PANEL is efficiency: percent change in joules per "
        "token, left is more efficient. The two panels are NOT on a shared "
        "axis - they carry different units and opposite polarity, and a bar "
        "in one says nothing about the other. The grey vertical bands are the "
        "rig's own measured noise: 1.1 percent total range for one fixed arm "
        "reloaded 16 times on throughput, and a 2.9 percent triplicate floor "
        "on joules per token. A bar that stays inside its band was not "
        "resolved by this instrument and is drawn neutral grey rather than "
        "as a win or a loss - the --load-mode row is the only one of those. "
        "Six of the nine levers were never "
        "paired for energy and carry an explicit 'not measured' mark rather "
        "than a zero-length bar. The ngram-mod row is drawn as a measured "
        "range (1.10x to 1.48x across six content types) because no single "
        "point estimate exists for it. Speculation's two bars come from "
        "different arms - throughput from the UD-IQ4_XS 45.2 to 99.16 t/s "
        "pair, energy from the power matrix at 8.104 to 3.210 joules per "
        "decode token - which is why 2.19x and 2.52x do not match exactly; "
        "decode-phase board power is flat across that pair (344.6 to "
        "341.0 W), so the energy saving is the throughput gain restated. Both "
        "power-cap rows were measured on synthetic decode whose 305.4 W mean "
        "never reached the 350 W cap, while agentic coding sits at the cap on "
        "about 97 percent of busy samples, so those two rows are not shown to "
        "transfer to this workload. NOT MEASURED ANYWHERE ON THIS FIGURE: "
        "wall or system power (board power only - there is no meter on this "
        "rig), memory junction temperature (NVML returns N/A for mtemp on "
        "this part), per-process GPU attribution (nvidia-smi pmon reports '-' "
        "for every process under Windows WDDM), and any interaction between "
        "levers - each row is its own arm with its own file, flags and "
        "prompt, and the rows are not a factorial sweep."
    )
    return [(png, cap)]
