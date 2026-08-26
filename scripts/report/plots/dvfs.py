#!/usr/bin/env python3
"""The frequency/power operating point this part actually chooses under load.

TWO FIGURES:
  1. The effective voltage/frequency operating curve: SM clock against board
     power, coloured by SM utilisation and split by workload phase, with the
     memory clock drawn on the same power axis underneath it.
  2. Clock residency: how much wall time each clock domain spent at each
     frequency, in seconds, over busy samples - with the memory traffic that
     clock was serving inset beside it.

THE FINDING BOTH FIGURES ARE BUILT TO MAKE UNMISSABLE. The board power cap
binds almost continuously during speculative decode, and the entire cost of it
is taken out of the SM clock. The memory clock does not participate: it sits at
one single frequency for essentially every busy sample, DURING A PHASE IN WHICH
the memory controller is busy only a little over half the time. Power is being
spent holding a clock the workload is not using.

WHY THIS IS AN OPPORTUNITY AND NOT A RESULT. Nothing in this campaign varied
the memory clock. llama.cpp has no way to express a clock policy, no clock
offset or lock was applied, and NVML on this part reports one board-power
number with no per-rail breakdown - so the watts held by the memory clock are
NOT measured and the size of any saving is unknown. The figures show that the
lever exists and is untouched. They do not show what pulling it would buy. Both
figures say so on their face so the reader cannot mistake one for the other.

TWO TRAPS THIS MODULE IS WRITTEN AROUND.

Correlation sign flips with the conditioning set. Across every busy sample,
board power and SM clock correlate strongly and POSITIVELY - which reads like
"more power buys more clock" and is an artefact of the light samples, where
both fall together. Restricted to samples in the top memory P-state, that is to
say to the workload actually running, the correlation is slightly NEGATIVE: the
board is pinned at its ceiling and the clock is the variable that gives. Both
numbers are computed and BOTH are printed, because the unconditioned one is the
one a reader would compute by reflex and it supports the opposite conclusion.

A dmon sample outside the /slots trace has NO phase, which is not the same as
idle. The telemetry collector starts before the benchmark and stops after it,
so a plain join would label a long head and tail of samples "idle" and drag
every phase statistic toward it. Those samples are drawn in grey under a
"no /slots coverage" label and are excluded from every phase number.
"""
import os
import subprocess

import matplotlib
matplotlib.use("Agg")            # REQUIRED - never an interactive backend
import matplotlib.pyplot as plt
import numpy as np

try:
    import archdata as A
except ImportError:              # standalone use, outside build-report.py
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))
    import archdata as A

TITLE = "Where the power cap is paid from"

# Okabe-Ito. Colourblind-safe, and no pair in use here is told apart by hue
# alone - every series also carries its own marker, axis or panel.
_MEM = "#0072B2"        # memory clock, everywhere in this module
_TRAF = "#D55E00"       # memory traffic / controller busy fraction
_SM = "#44546A"         # SM clock, where it is not carrying the colourmap
_INK = "#1b1b1b"
_GREY = "#5a5a5a"
_FAINT = "#9aa3b2"
_CMAP = "viridis"       # perceptually uniform, safe under all three CVD types
_PANEL = "#f4f6f8"
_LEVERBG = "#fff4e3"
_LEVEREC = "#c07a10"

_PART = "NVIDIA RTX 3090 (GA102, 24 GB GDDR6X, 350 W enforced board limit)"
_WORKLOAD = ("aider polyglot exercises, Qwen3-Coder-30B IQ4_XS on llama.cpp, "
             "MTP speculative decoding on")
_NOTMEAS = ("NOT measured: system or wall power (this is GPU board power from "
            "NVML only - no PSU loss, CPU, RAM, fans or display); per-rail "
            "power (NVML gives one board number on this part, so the watts "
            "held by the memory clock cannot be separated out); memory "
            "junction temperature (not exposed by NVML on this part, the field "
            "is NULL in every sample); and the memory-for-SM clock trade "
            "itself, which nothing in this run varied.")

_SMI_MEMO = {}


# --------------------------------------------------------------------------
def _smi_limits():
    """Read-only NVML query for the enforced power limit and the maximum clock
    P-state of each domain. These are firmware facts the telemetry cannot show:
    a trace can only report the clocks that were USED, and the gap to the ones
    the part is willing to run is the whole point of the figure.

    Best effort, and read-only: no -pl, no -pm, no -lgc, nothing that writes.
    On any failure the caller falls back to the maxima observed in the trace
    and relabels the reference lines accordingly, because a line called "the
    hardware maximum" that is really "the highest we happened to see" is a
    worse figure than no line at all.
    """
    if "v" in _SMI_MEMO:
        return _SMI_MEMO["v"]
    out = {}
    try:
        o = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=power.limit,clocks.max.sm,clocks.max.memory",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=8).stdout
        f = [p.strip() for p in o.strip().splitlines()[0].split(",")]
        out = {"cap_w": float(f[0]), "max_sm": float(f[1]),
               "max_mem": float(f[2])}
    except Exception:
        out = {}
    _SMI_MEMO["v"] = out
    return out


def _sample_seconds(t):
    """Wall seconds each sample stands for, so a residency histogram carries a
    real unit instead of a sample count. Each sample owns the interval to the
    next one; the last owns a median interval. Clipped at five medians so a
    collector stall cannot pile minutes into whichever bin happened to precede
    it."""
    n = len(t)
    if n == 0:
        return np.zeros(0)
    if n == 1:
        return np.ones(1)
    d = np.diff(t)
    pos = d[d > 0]
    med = float(np.median(pos)) if pos.size else 1.0
    dur = np.empty(n)
    dur[:-1] = d
    dur[-1] = med
    return np.clip(dur, 0.0, med * 5.0)


def _join_phase(dmon, slots, tol=2.0):
    """Per-dmon-sample phase from the /slots trace: 2 decode, 1 prompt
    processing, 0 idle, -1 NO COVERAGE. The -1 class is the one that matters:
    it keeps the collector's head and tail, where /slots was not being polled,
    out of every per-phase statistic instead of silently counting as idle."""
    n = len(dmon["t"])
    if slots is None or len(slots.get("t", [])) < 2:
        return np.full(n, -1)
    ph = A.phase_of(slots)
    st, dt = slots["t"], dmon["t"]
    idx = np.clip(np.searchsorted(st, dt), 1, len(st) - 1)
    lo, hi = idx - 1, idx
    pick = np.where(np.abs(st[lo] - dt) <= np.abs(st[hi] - dt), lo, hi)
    out = np.full(n, -1)
    ok = np.abs(st[pick] - dt) <= tol
    out[ok] = ph[pick][ok]
    return out


def _stats(dmon, slots):
    """Every number either figure prints, computed once so the two cannot
    disagree with each other."""
    sm, pclk, mclk = dmon["sm"], dmon["pclk"], dmon["mclk"]
    s = {}
    s["busy"] = busy = np.isfinite(sm) & (sm > A.BUSY_SM_PCT)
    s["phase"] = ph = _join_phase(dmon, slots)
    s["m_dec"] = ph == 2
    s["m_ppr"] = ph == 1
    s["m_idl"] = ph == 0
    s["m_unk"] = ph == -1
    s["dur"] = dur = _sample_seconds(dmon["t"])

    # The phase the finding is about. Fall back to "every busy sample" when the
    # /slots trace is missing, and record which one was used so the figure can
    # name it rather than implying a decode measurement it did not make.
    if np.count_nonzero(s["m_dec"]) >= 30:
        s["focus"] = s["m_dec"]
        s["focus_name"] = "decode"
        s["focus_desc"] = "decode samples (n_decoded advancing)"
    else:
        s["focus"] = busy
        s["focus_name"] = "busy"
        s["focus_desc"] = ("busy samples (SM > %g%%; no /slots trace, so "
                           "decode could not be separated)" % A.BUSY_SM_PCT)
    f = s["focus"]
    s["n_focus"] = int(np.count_nonzero(f))
    s["focus_sec"] = float(dur[f].sum())

    lim = _smi_limits()
    s["from_nvml"] = bool(lim)
    obs_sm = float(np.nanmax(pclk)) if np.isfinite(pclk).any() else 0.0
    obs_mem = float(np.nanmax(mclk)) if np.isfinite(mclk).any() else 0.0
    s["obs_sm"] = obs_sm
    s["obs_mem"] = obs_mem
    s["max_sm"] = lim.get("max_sm", obs_sm)
    s["max_mem"] = lim.get("max_mem", obs_mem)
    s["cap_w"] = lim.get("cap_w", float(np.nanmax(dmon["pwr"]))
                         if np.isfinite(dmon["pwr"]).any() else 0.0)

    for k, arr in (("pclk", pclk), ("mclk", mclk), ("pwr", dmon["pwr"]),
                   ("mem", dmon["mem"]), ("smu", sm),
                   ("pviol", dmon["pviol"])):
        v = arr[f]
        v = v[np.isfinite(v)]
        if not v.size:
            for suf in ("_med", "_mean", "_p5", "_p95", "_p1", "_p99"):
                s[k + suf] = np.nan
            continue
        s[k + "_med"] = float(np.median(v))
        s[k + "_mean"] = float(np.mean(v))
        s[k + "_p5"] = float(np.percentile(v, 5))
        s[k + "_p95"] = float(np.percentile(v, 95))
        s[k + "_p1"] = float(np.percentile(v, 1))
        s[k + "_p99"] = float(np.percentile(v, 99))

    # The single frequency the memory clock lives at during the focus phase.
    mv = mclk[f]
    mv = mv[np.isfinite(mv)]
    if mv.size:
        u, c = np.unique(mv, return_counts=True)
        s["mclk_top"] = float(u[np.argmax(c)])
        s["mclk_top_pct"] = 100.0 * float(c.max()) / mv.size
    else:
        s["mclk_top"] = np.nan
        s["mclk_top_pct"] = np.nan

    # Memory P-states the part is capable of, evidenced from the trace itself.
    allm = mclk[np.isfinite(mclk)]
    s["mclk_states"] = sorted(float(x) for x in np.unique(allm))

    # The correlation trap, both ways round. See the module docstring.
    b = busy & np.isfinite(pclk) & np.isfinite(dmon["pwr"])
    s["r_busy"] = s["r_top"] = np.nan
    s["n_top"] = 0
    if np.count_nonzero(b) > 30:
        s["r_busy"] = float(np.corrcoef(dmon["pwr"][b], pclk[b])[0, 1])
    if np.isfinite(s["mclk_top"]):
        b2 = b & (mclk == s["mclk_top"])
        if np.count_nonzero(b2) > 30:
            s["r_top"] = float(np.corrcoef(dmon["pwr"][b2], pclk[b2])[0, 1])
            s["n_top"] = int(np.count_nonzero(b2))
    return s


def _throttle_mix(throttle):
    """NVML clock-limit reason over NON-IDLE samples. Idle is a state, not a
    limit, and folding it in would dilute the percentage that matters."""
    if throttle is None or not len(throttle.get("t", [])):
        return {}
    _, lab = A.throttle_series(throttle)
    lab = [l for l in lab if l not in ("Idle", "no data")]
    if not lab:
        return {}
    tot = float(len(lab))
    return {k: 100.0 * lab.count(k) / tot for k in set(lab)}


def _refline_label(s, which):
    """Name a reference line by what it actually is. NVML's maximum P-state and
    "the highest clock we happened to see" are different claims and must not
    share a label."""
    if s["from_nvml"]:
        return ("max %s clock P-state, %.0f MHz (NVML)"
                % (which, s["max_sm"] if which == "SM" else s["max_mem"]))
    return ("highest %s clock OBSERVED here, %.0f MHz - NVML maximum "
            "unavailable" % (which,
                             s["obs_sm"] if which == "SM" else s["obs_mem"]))


def _footer(fig, extra=""):
    fig.text(0.007, 0.010,
             "Part: %s.   Workload: %s.\n%s%s"
             % (_PART, _WORKLOAD, _NOTMEAS, ("  " + extra) if extra else ""),
             fontsize=6.6, color=_GREY, va="bottom", ha="left", wrap=True)


def _band_frac(v, w, lo, hi):
    m = (v >= lo) & (v <= hi)
    return 100.0 * float(w[m].sum()) / max(float(w.sum()), 1e-9)


def _phase_scatter(ax, s, x, y, c, sizes=(11, 24, 30), unk=5, alpha=0.6):
    """The one scatter every panel uses: marker carries the workload phase,
    colour carries SM utilisation. Colour is never the only thing separating
    two classes."""
    if np.count_nonzero(s["m_unk"]):
        ax.scatter(x[s["m_unk"]], y[s["m_unk"]], s=unk, c=_FAINT, marker=".",
                   alpha=0.5, linewidths=0, zorder=2)
    sc = None
    for m, mk, sz, z in ((s["m_dec"], "o", sizes[0], 3),
                         (s["m_ppr"], "^", sizes[1], 4),
                         (s["m_idl"], "X", sizes[2], 4)):
        if not np.count_nonzero(m):
            continue
        sc = ax.scatter(x[m], y[m], c=c[m], cmap=_CMAP, vmin=0, vmax=100,
                        s=sz, marker=mk, alpha=alpha, linewidths=0, zorder=z)
    if sc is None:                      # no phase labels available at all
        b = s["busy"]
        sc = ax.scatter(x[b], y[b], c=c[b], cmap=_CMAP, vmin=0, vmax=100,
                        s=sizes[0], alpha=alpha, linewidths=0, zorder=3)
    return sc


# --------------------------------------------------------------------------
def _fig_operating_point(dmon, s, throttle, outdir):
    pwr, pclk, mclk = dmon["pwr"], dmon["pclk"], dmon["mclk"]
    smu, mem = dmon["sm"], dmon["mem"]

    # Column 2 is an empty spacer, and it is load-bearing: the colorbar's label
    # and the twinned right-hand axis of the lower panel both live outside
    # their own gridspec cell, and without reserved space they land on top of
    # the text column.
    fig = plt.figure(figsize=(13.4, 8.3))
    gs = fig.add_gridspec(2, 4, width_ratios=[46, 1.4, 7.5, 23],
                          height_ratios=[3.0, 2.15], hspace=0.22, wspace=0.035)
    ax1 = fig.add_subplot(gs[0, 0])
    cax = fig.add_subplot(gs[0, 1])
    ax2 = fig.add_subplot(gs[1, 0], sharex=ax1)
    axT = fig.add_subplot(gs[0, 3])
    axL = fig.add_subplot(gs[1, 3])
    axT.axis("off")
    axL.axis("off")

    xmax = max(s["cap_w"], float(np.nanmax(pwr))) * 1.055
    ymax = max(s["max_sm"], s["obs_sm"]) * 1.10
    gap = s["max_sm"] - s["pclk_med"]

    # ---- upper: the V/F cloud. shape = phase, colour = SM utilisation ------
    sc = _phase_scatter(ax1, s, pwr, pclk, smu)
    cb = fig.colorbar(sc, cax=cax)
    cb.set_label("SM utilisation (%)", fontsize=8.5)
    cb.ax.tick_params(labelsize=8)

    ax1.axhline(s["max_sm"], color=_GREY, ls="--", lw=1.1, zorder=5)
    ax1.text(xmax * 0.015, s["max_sm"] + ymax * 0.012, _refline_label(s, "SM"),
             fontsize=7.6, color=_GREY, va="bottom")
    ax1.axvline(s["cap_w"], color=_INK, ls=":", lw=1.3, zorder=5)
    ax1.text(s["cap_w"] - xmax * 0.011, ymax * 0.035,
             ("enforced board-power limit, %.0f W" % s["cap_w"])
             if s["from_nvml"] else
             ("highest board power OBSERVED, %.0f W" % s["cap_w"]),
             fontsize=7.6, color=_INK, rotation=90, ha="right", va="bottom")
    ax1.axhline(s["pclk_med"], color=_TRAF, ls="-", lw=1.2, alpha=0.9,
                zorder=5)
    ax1.text(xmax * 0.015, s["pclk_med"] + ymax * 0.012,
             "%s median SM clock, %.0f MHz" % (s["focus_name"], s["pclk_med"]),
             fontsize=7.8, color=_TRAF, va="bottom", fontweight="bold")

    xa = s["cap_w"] * 0.66
    ax1.annotate("", xy=(xa, s["max_sm"]), xytext=(xa, s["pclk_med"]),
                 arrowprops=dict(arrowstyle="<->", color=_INK, lw=1.4),
                 zorder=6)
    ax1.text(xa - xmax * 0.012, (s["max_sm"] + s["pclk_med"]) / 2.0,
             "%.0f MHz of SM clock\nnever asked for\n(%.0f%% of the maximum)"
             % (gap, 100.0 * gap / max(s["max_sm"], 1.0)),
             fontsize=8.6, color=_INK, va="center", ha="right",
             fontweight="bold", zorder=6,
             bbox=dict(boxstyle="round,pad=0.28", fc="white", ec="none",
                       alpha=0.78))

    ax1.set_ylabel("SM (graphics) clock (MHz)", fontsize=9.5)
    ax1.set_ylim(0, ymax)
    ax1.set_xlim(0, xmax)
    ax1.grid(alpha=0.3)
    ax1.tick_params(labelsize=8.5, labelbottom=False)
    ax1.set_title("SM clock: held %.0f MHz below the part's ceiling by a cap\n"
                  "that cuts clocks on %.0f%% of the sample period"
                  % (gap, s["pviol_mean"]), fontsize=10.5, color=_INK, pad=6)

    # The whole workload lives in the top-right corner of the full envelope, so
    # the corner is drawn again at a readable size. The parent axes keep the
    # full range: an architect must be able to see the idle arm of the curve,
    # not just the piece that supports the argument.
    zx0, zx1 = s["pwr_p1"] - 6.0, s["cap_w"] * 1.012
    zy0, zy1 = s["pclk_p1"] - 45.0, s["pclk_p99"] + 45.0
    if zx1 > zx0 and zy1 > zy0:
        axz = ax1.inset_axes([0.315, 0.125, 0.415, 0.395])
        _phase_scatter(axz, s, pwr, pclk, smu, sizes=(9, 20, 26), unk=4,
                       alpha=0.55)
        axz.axhline(s["pclk_med"], color=_TRAF, ls="-", lw=1.1, zorder=5)
        axz.axvline(s["cap_w"], color=_INK, ls=":", lw=1.1, zorder=5)
        axz.set_xlim(zx0, zx1)
        axz.set_ylim(zy0, zy1)
        axz.grid(alpha=0.25)
        axz.tick_params(labelsize=6.8)
        axz.set_xlabel("board power (W)", fontsize=6.6, labelpad=1)
        axz.set_ylabel("SM clock (MHz)", fontsize=6.6, labelpad=1)
        axz.set_title("the working corner, magnified", fontsize=7.4,
                      color=_INK, pad=3)
        for sp in axz.spines.values():
            sp.set_color(_INK)
        ax1.indicate_inset_zoom(axz, edgecolor=_INK, alpha=0.55, lw=0.9)

    # The legend lives in the text column, not on the axes: every corner of the
    # upper panel is either data, the magnified inset, or one of the two
    # reference lines' labels, and a legend box on top of any of them would be
    # hiding samples to explain samples.
    hands = [plt.Line2D([], [], ls="", marker=mk, color=_GREY, ms=ms,
                        label=lab)
             for mk, ms, lab in (
                 ("o", 5, "decode"),
                 ("^", 6, "prompt processing"),
                 ("X", 6, "idle (slot not processing)"),
                 (".", 7, "no /slots coverage:\nphase unknown, NOT idle"))]
    axT.legend(handles=hands, fontsize=7.2, loc="lower left",
               bbox_to_anchor=(0.0, -0.02), frameon=True, framealpha=0.95,
               title="marker = workload phase", title_fontsize=7.2,
               borderpad=0.5, labelspacing=0.45, handletextpad=0.6)

    # ---- lower: the memory domain, clock against the traffic it serves -----
    mmax = max(s["max_mem"], s["obs_mem"]) * 1.06
    ax2.scatter(pwr, mclk, s=9, c=_MEM, marker="s", alpha=0.5, linewidths=0,
                zorder=3)
    ax2.axhline(s["max_mem"], color=_GREY, ls="--", lw=1.1, zorder=2)
    ax2.text(xmax * 0.015, s["max_mem"] + mmax * 0.015,
             _refline_label(s, "memory"), fontsize=7.6, color=_GREY,
             va="bottom")
    ax2.axvline(s["cap_w"], color=_INK, ls=":", lw=1.3, zorder=2)

    ax2b = ax2.twinx()
    fm = s["focus"]
    ax2b.scatter(pwr[fm], mem[fm], s=15, facecolors="none", edgecolors=_TRAF,
                 alpha=0.30, linewidths=0.7, zorder=4)
    ax2b.axhline(s["mem_med"], color=_TRAF, ls="-", lw=1.3, zorder=5)
    ax2b.set_ylim(0, 100)
    ax2b.set_ylabel("memory-controller busy\n(%% of the sample period, %s "
                    "samples; axis 0-100%%)" % s["focus_name"], fontsize=8.4,
                    color=_TRAF)
    ax2b.tick_params(axis="y", labelsize=8.5, colors=_TRAF)

    ax2.set_ylim(0, mmax)
    ax2.set_ylabel("memory clock (MHz)\n(axis 0 to the %.0f MHz maximum)"
                   % s["max_mem"], fontsize=8.4, color=_MEM)
    ax2.tick_params(axis="y", labelsize=8.5, colors=_MEM)
    ax2.tick_params(axis="x", labelsize=8.5)
    ax2.set_xlabel("GPU board power (W, NVML total board draw - NOT system or "
                   "wall power)", fontsize=9.5)
    ax2.grid(alpha=0.3)
    ax2.set_title("Memory clock: one frequency, %.0f MHz, on %.1f%% of %s "
                  "samples\nwhile its controller is busy only %.0f%% of the "
                  "time"
                  % (s["mclk_top"], s["mclk_top_pct"], s["focus_name"],
                     s["mem_med"]), fontsize=10.5, color=_INK, pad=6)

    ax2.annotate("clock pinned here at every power level",
                 xy=(s["cap_w"] * 0.72, s["mclk_top"]),
                 xytext=(xmax * 0.045, mmax * 0.855), fontsize=8.4,
                 color=_MEM, fontweight="bold", va="center",
                 arrowprops=dict(arrowstyle="->", color=_MEM, lw=1.2))
    traf_y = s["mem_med"] / 100.0 * mmax
    ax2.annotate("traffic it is serving sits at %.0f%% (median)"
                 % s["mem_med"], xy=(s["cap_w"] * 0.90, traf_y),
                 xytext=(xmax * 0.045, traf_y + mmax * 0.075), fontsize=8.4,
                 color=_TRAF, fontweight="bold", va="center",
                 arrowprops=dict(arrowstyle="->", color=_TRAF, lw=1.2))

    low = [v for v in s["mclk_states"] if v < s["mclk_top"] * 0.9]
    if low:
        inlow = np.isin(mclk, low)
        tip = (float(np.median(pwr[inlow])), float(np.median(mclk[inlow]))) \
            if inlow.any() else (xmax * 0.15, max(low))
        ax2.annotate("lower memory P-states (%s MHz) are real on this part and\n"
                     "get used when the card is idle. Under load it never\n"
                     "selects one: the granularity exists in the silicon."
                     % ", ".join("%.0f" % v for v in low), xy=tip,
                     xytext=(xmax * 0.045, mmax * 0.30), fontsize=7.6,
                     color=_MEM, va="center", ha="left",
                     arrowprops=dict(arrowstyle="->", color=_MEM, lw=0.9))

    ax2.text(xmax * 0.99, mmax * 0.045,
             "both y axes run 0 to their own maximum, so heights compare as "
             "fraction-of-maximum:\nclock at %.0f%% of its ceiling, traffic at "
             "%.0f%% of its ceiling."
             % (100.0 * s["mclk_top"] / max(s["max_mem"], 1.0), s["mem_med"]),
             fontsize=7.3, color=_GREY, va="bottom", ha="right")

    # ---- right column: the numbers, and the lever ---------------------------
    stat = ("THE OPERATING POINT, %s phase\n"
            "  board power  %5.0f W    median (%.0f-%.0f, 5-95 pct)\n"
            "  SM clock     %5.0f MHz  median (%.0f-%.0f)\n"
            "  memory clock %5.0f MHz  on %.1f%% of samples\n"
            "  SM busy      %5.0f %%    median\n"
            "  memory busy  %5.0f %%    median (%.0f-%.0f)\n"
            "  cap cutting  %5.0f %%    of the sample period\n"
            "                        (NVML power-violation duty)\n"
            "  samples      %5d      over %.0f s\n"
            "\n"
            "INSIDE THE CAP THE CLOUD IS VERTICAL, NOT\n"
            "SLOPED. r(board power, SM clock) = %+.2f over\n"
            "the %d busy samples in the top memory\n"
            "P-state: watts are not buying clock, the cap\n"
            "is handing clock back. Across ALL busy\n"
            "samples that same correlation reads %+.2f -\n"
            "the opposite conclusion, and an artefact of\n"
            "the light samples where power and clock fall\n"
            "together. The conditioned number is the one\n"
            "that describes this workload."
            % (s["focus_name"], s["pwr_med"], s["pwr_p5"], s["pwr_p95"],
               s["pclk_med"], s["pclk_p5"], s["pclk_p95"], s["mclk_top"],
               s["mclk_top_pct"], s["smu_med"], s["mem_med"], s["mem_p5"],
               s["mem_p95"], s["pviol_mean"], s["n_focus"], s["focus_sec"],
               s["r_top"], s["n_top"], s["r_busy"]))
    axT.text(0.0, 1.0, stat, transform=axT.transAxes, fontsize=7.2,
             color=_INK, va="top", ha="left", family="monospace",
             bbox=dict(boxstyle="round,pad=0.5", fc=_PANEL, ec="#c9ced8",
                       lw=0.9))

    lever = ("UNEXPLOITED FIRMWARE LEVER\n"
             "-- NOT A MEASUREMENT --\n"
             "\n"
             "Every watt is contested: the cap cuts\n"
             "clocks on %.0f%% of the sample period. Yet\n"
             "the memory clock is exempt from that\n"
             "negotiation while its controller idles\n"
             "%.0f%% of the time. A phase-aware policy\n"
             "that traded memory clock for SM clock\n"
             "during speculative verify would spend the\n"
             "same watts on the resource that is\n"
             "actually saturated - SM busy %.0f%% against\n"
             "memory busy %.0f%%.\n"
             "\n"
             "THIS RUN DID NOT TEST THAT. llama.cpp\n"
             "cannot express a clock policy, no clock\n"
             "offset or lock was applied anywhere in\n"
             "this campaign, and NVML on this part\n"
             "reports a single board-power number with\n"
             "no per-rail split - so the watts at stake\n"
             "are UNMEASURED. The figure shows the\n"
             "lever exists and is untouched. It does\n"
             "not show what pulling it would buy."
             % (s["pviol_mean"], 100.0 - s["mem_med"], s["smu_med"],
                s["mem_med"]))
    axL.text(0.0, 1.0, lever, transform=axL.transAxes, fontsize=7.35,
             color=_INK, va="top", ha="left", family="monospace",
             bbox=dict(boxstyle="round,pad=0.5", fc=_LEVERBG, ec=_LEVEREC,
                       lw=1.3))

    fig.suptitle("Power is being spent holding a memory clock this workload "
                 "does not use", fontsize=13.5, fontweight="bold", color=_INK,
                 y=0.982)
    mix = _throttle_mix(throttle)
    extra = (("NVML clock-limit reason over non-idle samples: %s."
              % ", ".join("%s %.1f%%" % (k, v)
                          for k, v in sorted(mix.items(),
                                             key=lambda kv: -kv[1])))
             if mix else
             "NVML clock-limit reasons: not collected for this run.")
    _footer(fig, extra)
    fig.subplots_adjust(left=0.073, right=0.996, top=0.912, bottom=0.113)
    path = os.path.join(outdir, "dvfs-operating-point.png")
    fig.savefig(path, dpi=140, facecolor="white")
    plt.close(fig)

    dt_med = float(np.median(np.diff(dmon["t"]))) if len(dmon["t"]) > 1 else 0.0
    cap = ("The part's effective voltage/frequency operating point under a real "
           "agentic-coding load: %d %s plus %d further busy samples, at a "
           "%.2f s cadence. Upper panel plots SM clock against GPU board power, "
           "colour is SM utilisation, marker is workload phase; the grey points "
           "are samples outside the /slots trace, whose phase is unknown rather "
           "than idle, and the inset magnifies the corner the workload actually "
           "occupies. Board power is pinned at %.0f W median against a %.0f W "
           "limit and the SM clock is the variable that gives - %.0f MHz, "
           "%.0f%%, below the %.0f MHz maximum SM P-state - with NVML reporting "
           "the power cap actively reducing clocks on %.0f%% of the sample "
           "period. Inside that capped regime r(board power, SM clock) is "
           "%+.2f, not positive: watts are not buying clock. Lower panel, same "
           "power axis: the memory clock holds %.0f MHz on %.1f%% of %s samples "
           "while its controller is busy only %.0f%% of the time, and the lower "
           "memory P-states this part uses when idle are never selected under "
           "load. THE PHASE-AWARE CLOCK TRADE THIS SUGGESTS IS AN OPPORTUNITY, "
           "NOT A RESULT: nothing in this run varied the memory clock, and with "
           "no per-rail power on this part the watts at stake are unmeasured. "
           "Part: %s. Workload: %s. %s"
           % (s["n_focus"], s["focus_desc"],
              int(np.count_nonzero(s["busy"] & ~s["focus"])), dt_med,
              s["pwr_med"], s["cap_w"], gap,
              100.0 * gap / max(s["max_sm"], 1.0), s["max_sm"],
              s["pviol_mean"], s["r_top"], s["mclk_top"], s["mclk_top_pct"],
              s["focus_name"], s["mem_med"], _PART, _WORKLOAD, _NOTMEAS))
    return path, cap


# --------------------------------------------------------------------------
def _fig_residency(dmon, s, outdir):
    pclk, mclk, mem, dur = dmon["pclk"], dmon["mclk"], dmon["mem"], s["dur"]
    busy = s["busy"]
    tot = float(dur[busy].sum())

    fig, (axA, axB) = plt.subplots(1, 2, figsize=(12.6, 6.9))

    # ---- SM clock ----------------------------------------------------------
    v, w = pclk[busy], dur[busy]
    ok = np.isfinite(v)
    v, w = v[ok], w[ok]
    step = 15.0                      # this part's SM clock granularity
    hi = max(s["max_sm"], s["obs_sm"]) * 1.075
    axA.hist(v, bins=np.arange(0.0, hi + step, step), weights=w, color=_SM,
             edgecolor="none")
    axA.set_xlim(0, hi)
    top = axA.get_ylim()[1] * 1.16
    axA.set_ylim(0, top)
    axA.axvspan(s["pclk_p5"], s["pclk_p95"], color=_TRAF, alpha=0.11, lw=0)
    axA.axvline(s["max_sm"], color=_GREY, ls="--", lw=1.2)
    axA.axvline(s["pclk_med"], color=_TRAF, ls="-", lw=1.4)
    axA.text(s["max_sm"] + hi * 0.017, top * 0.50, _refline_label(s, "SM"),
             fontsize=7.6, color=_GREY, rotation=90, ha="center", va="center")
    axA.annotate("", xy=(s["max_sm"], top * 0.865),
                 xytext=(s["pclk_med"], top * 0.865),
                 arrowprops=dict(arrowstyle="<->", color=_INK, lw=1.4))
    axA.text((s["max_sm"] + s["pclk_med"]) / 2.0, top * 0.885,
             "%.0f MHz never\nreached under load"
             % (s["max_sm"] - s["pclk_med"]), fontsize=8.4, color=_INK,
             ha="center", va="bottom", fontweight="bold")
    frac = _band_frac(v, w, s["pclk_p5"], s["pclk_p95"])
    axA.text(0.03, 0.985,
             "%.0f%% of busy time inside a %.0f MHz band\n(%.0f-%.0f MHz, "
             "5th-95th pct). The cap, not the\nworkload, is choosing this "
             "clock."
             % (frac, s["pclk_p95"] - s["pclk_p5"], s["pclk_p5"],
                s["pclk_p95"]),
             transform=axA.transAxes, fontsize=8, color=_INK, va="top",
             ha="left",
             bbox=dict(boxstyle="round,pad=0.4", fc=_PANEL, ec="#c9ced8",
                       lw=0.8))
    axA.set_xlabel("SM (graphics) clock (MHz), 15 MHz bins", fontsize=9.5)
    axA.set_ylabel("wall time at this clock (s)", fontsize=9.5)
    axA.grid(alpha=0.3)
    axA.tick_params(labelsize=8.5)
    axA.set_title("SM clock: spread over %d frequencies, none of them the "
                  "part's maximum" % len(np.unique(v)), fontsize=10.5,
                  color=_INK, pad=24)
    sa = axA.secondary_xaxis("top", functions=(
        lambda x, m=s["max_sm"]: 100.0 * x / m,
        lambda p, m=s["max_sm"]: p * m / 100.0))
    sa.set_xlabel("% of the maximum SM clock P-state", fontsize=8, color=_GREY)
    sa.tick_params(labelsize=7.5, colors=_GREY)

    # Placed right of the lowest occupied bin: an inset that covers a bar is
    # hiding a measurement in order to explain one.
    axAz = axA.inset_axes([0.195, 0.125, 0.375, 0.40])
    zlo, zhi = s["pclk_p1"] - 60.0, s["pclk_p99"] + 60.0
    axAz.hist(v, bins=np.arange(0.0, hi + step, step), weights=w, color=_SM,
              edgecolor="none")
    axAz.axvline(s["pclk_med"], color=_TRAF, ls="-", lw=1.2)
    axAz.set_xlim(zlo, zhi)
    axAz.grid(alpha=0.25)
    axAz.tick_params(labelsize=6.8)
    axAz.set_xlabel("SM clock (MHz)", fontsize=6.6, labelpad=1)
    axAz.set_ylabel("time (s)", fontsize=6.6, labelpad=1)
    axAz.set_title("the used band, magnified", fontsize=7.4, color=_INK, pad=3)
    for sp in axAz.spines.values():
        sp.set_color(_INK)

    # ---- memory clock ------------------------------------------------------
    mv, mw = mclk[busy], dur[busy]
    ok = np.isfinite(mv)
    mv, mw = mv[ok], mw[ok]
    u = np.unique(mv)
    secs = np.array([float(mw[mv == x].sum()) for x in u])
    hib = max(s["max_mem"], s["obs_mem"]) * 1.075
    axB.bar(u, secs, width=max(hib / 26.0, 180.0), color=_MEM, edgecolor="none")
    axB.axvline(s["max_mem"], color=_GREY, ls="--", lw=1.2)
    axB.set_xlim(0, hib)
    tb = max(float(secs.max()) * 1.40, 1.0)
    axB.set_ylim(0, tb)
    axB.text(s["max_mem"] + hib * 0.017, tb * 0.50, _refline_label(s, "memory"),
             fontsize=7.6, color=_GREY, rotation=90, ha="center", va="center")
    for x, y in zip(u, secs):
        big = y > secs.max() * 0.5
        axB.annotate("%.0f MHz\n%s s\n%.2f%% of busy time"
                     % (x, ("%.0f" % y) if y >= 1.0 else ("%.1f" % y),
                        100.0 * y / max(tot, 1e-9)),
                     xy=(x, y), xytext=(x - hib * 0.022, y + tb * 0.035),
                     fontsize=7.8, color=_INK if big else _MEM,
                     ha="right" if big else "center", va="bottom",
                     fontweight="bold" if big else "normal")
    axB.set_xlabel("memory clock (MHz), one bar per P-state the part selected",
                   fontsize=9.5)
    axB.set_ylabel("wall time at this clock (s)", fontsize=9.5)
    axB.grid(alpha=0.3)
    axB.tick_params(labelsize=8.5)
    axB.set_title("Memory clock: one frequency for %.1f%% of busy time"
                  % (100.0 * secs.max() / max(tot, 1e-9)), fontsize=10.5,
                  color=_INK, pad=24)
    sb = axB.secondary_xaxis("top", functions=(
        lambda x, m=s["max_mem"]: 100.0 * x / m,
        lambda p, m=s["max_mem"]: p * m / 100.0))
    sb.set_xlabel("% of the maximum memory clock P-state", fontsize=8,
                  color=_GREY)
    sb.tick_params(labelsize=7.5, colors=_GREY)

    # The distribution that ISN'T degenerate, drawn against the one that is.
    # Without this the reader has to take on trust that the traffic varies.
    fm = s["focus"]
    tv, tw = mem[fm], dur[fm]
    ok = np.isfinite(tv)
    tv, tw = tv[ok], tw[ok]
    if tv.size:
        axBz = axB.inset_axes([0.115, 0.365, 0.395, 0.385])
        axBz.hist(tv, bins=np.arange(0, 102, 2), weights=tw, color=_TRAF,
                  edgecolor="none")
        axBz.axvline(s["mem_med"], color=_INK, ls="-", lw=1.2)
        axBz.set_xlim(0, 100)
        axBz.grid(alpha=0.25)
        axBz.tick_params(labelsize=6.8)
        axBz.set_xlabel("memory-controller busy (%)", fontsize=7)
        axBz.set_ylabel("time (s)", fontsize=7)
        axBz.set_title("the traffic that clock is serving, %s samples"
                       % s["focus_name"], fontsize=7.4, color=_INK, pad=3)
        for sp in axBz.spines.values():
            sp.set_color(_TRAF)

    axB.text(0.03, 0.985,
             "The memory clock has no distribution to plot: it is one\n"
             "bar. The traffic it serves does - inset - and it is centred\n"
             "on %.0f%% (5th-95th pct %.0f-%.0f%%). The clock is held at\n"
             "its maximum straight through every lull."
             % (s["mem_med"], s["mem_p5"], s["mem_p95"]),
             transform=axB.transAxes, fontsize=8, color=_INK, va="top",
             ha="left",
             bbox=dict(boxstyle="round,pad=0.4", fc=_LEVERBG, ec=_LEVEREC,
                       lw=1.1))

    fig.suptitle("The two clock domains are run on completely different "
                 "policies under one shared power cap", fontsize=13,
                 fontweight="bold", color=_INK, y=0.985)
    _footer(fig,
            "Residency is wall time over busy samples (SM > %g%%), each sample "
            "weighted by its own interval, %.0f s in total. The memory-for-SM "
            "clock trade this contrast suggests was NOT tested: no clock was "
            "locked, offset or varied anywhere in this campaign."
            % (A.BUSY_SM_PCT, tot))
    fig.subplots_adjust(left=0.062, right=0.985, top=0.838, bottom=0.155,
                        wspace=0.19)
    path = os.path.join(outdir, "dvfs-clock-residency.png")
    fig.savefig(path, dpi=140, facecolor="white")
    plt.close(fig)

    dt_med = float(np.median(np.diff(dmon["t"]))) if len(dmon["t"]) > 1 else 0.0
    cap = ("How long each clock domain actually spent at each frequency, over "
           "%.0f s of busy samples (SM > %g%%), each sample weighted by its own "
           "%.2f s interval rather than counted. Left: the SM clock is spread "
           "over %d distinct frequencies on a 15 MHz grid and never reaches the "
           "%.0f MHz maximum P-state, spending %.0f%% of busy time inside a "
           "%.0f MHz band around %.0f MHz. Right: the memory clock is a single "
           "bar, %.0f MHz for %.1f%% of busy time, while the traffic it serves "
           "over that same interval - inset, same axis of time - is a broad "
           "distribution centred on %.0f%% of the sample period (5th-95th pct "
           "%.0f-%.0f%%). The lower memory P-states at the left of that panel "
           "are real and this part uses them when idle, so the granularity "
           "exists in silicon and is simply never selected under load. NOTHING "
           "HERE MEASURES WHAT A DIFFERENT POLICY WOULD COST OR SAVE: no clock "
           "was locked, offset or varied in this campaign, and NVML on this "
           "part gives one board-power number with no per-rail split. Part: %s. "
           "Workload: %s. %s"
           % (tot, A.BUSY_SM_PCT, dt_med, len(np.unique(v)), s["max_sm"], frac,
              s["pclk_p95"] - s["pclk_p5"], s["pclk_med"], s["mclk_top"],
              100.0 * secs.max() / max(tot, 1e-9), s["mem_med"], s["mem_p5"],
              s["mem_p95"], _PART, _WORKLOAD, _NOTMEAS))
    return path, cap


# --------------------------------------------------------------------------
def make(ctx, outdir):
    """ctx has keys: tag, run, dmon, slots, host, throttle, requests, exercises
    (any may be None if that source is absent - degrade gracefully, never
    crash). Returns a list of (png_path, caption_string)."""
    out = []
    dmon = ctx.get("dmon")
    if dmon is None or not len(dmon.get("t", [])):
        print("  [dvfs] no dmon trace: the operating point is unobservable, "
              "so no figure is drawn")
        return out
    for f in ("pclk", "mclk", "pwr", "sm"):
        col = dmon.get(f)
        if col is None or not len(col) or not np.isfinite(col).any():
            print("  [dvfs] dmon field %r is NULL in every sample on this "
                  "part: there is no honest V/F figure to draw, so none is "
                  "drawn" % f)
            return out
    try:
        os.makedirs(outdir, exist_ok=True)
    except Exception as e:
        print("  [dvfs] cannot create %s: %s" % (outdir, e))
        return out

    s = _stats(dmon, ctx.get("slots"))
    if s["n_focus"] < 30:
        print("  [dvfs] only %d usable samples: too few to make a residency "
              "claim, so no figure is drawn" % s["n_focus"])
        return out

    for fn in (lambda: _fig_operating_point(dmon, s, ctx.get("throttle"),
                                            outdir),
               lambda: _fig_residency(dmon, s, outdir)):
        try:
            r = fn()
        except Exception as e:
            print("  [dvfs] figure failed: %s: %s" % (type(e).__name__, e))
            r = None
        if r:
            out.append(r)
    return out
