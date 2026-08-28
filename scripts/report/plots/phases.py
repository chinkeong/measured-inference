#!/usr/bin/env python3
"""What the machine spends its time and its joules on.

Two figures, built only from the slots trace and the dmon board-power trace:

  1. phases-timeline.png -- decode / prompt-processing / idle over the whole
     run, with board power on the same time axis, plus a representative zoom
     so the duty cycle is legible at its true period.
  2. phases-time-energy-tokens.png -- the split of wall-clock seconds, board
     joules and tokens between the phases, side by side, because on this run
     the time ratio and the token ratio point in opposite directions and a
     reader given only one of them will draw the wrong conclusion.

METHOD, stated so it can be argued with:
  * Phase labels come from A.phase_of(slots). Sample i labels the interval
    (t[i-1], t[i]]; time is interval-weighted, never sample-counted, so an
    uneven poll cadence cannot bias the split.
  * Energy per phase is A.energy() integrated over each CONTIGUOUS phase run
    and summed by phase, with busy_only=False. Trapezoidal, interpolated at
    both edges. busy_only is off on purpose: the idle phase is exactly the
    thing whose energy we want reported rather than filtered away.
  * Any poll interval longer than the gap cap is a collector stall. It is
    dropped from BOTH the time and the energy sum, so the two stay consistent.
  * Board power only. NVML reports the board; the rest of the system is not
    instrumented here and no figure in this module implies wall power.
"""
import os
import sys

import matplotlib
matplotlib.use("Agg")            # REQUIRED - never an interactive backend
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.lines import Line2D
import numpy as np

try:
    import archdata as A
except ImportError:                                    # imported from elsewhere
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import archdata as A

TITLE = "Where the seconds and the joules go"

# Okabe-Ito. Distinguishable by hue AND by lightness, so the figure survives
# both colour blindness and a greyscale printer. No red/green pairing.
_COL = {2: "#0072B2", 1: "#E69F00", 0: "#9A9A9A"}
_NAME = {2: "decode", 1: "prompt-processing", 0: "idle"}
_PWR = "#101010"
_RAW = "#BFBFBF"
_DPI = 140
_GA = 0.3
_ZOOM_S = 150.0        # width of the representative window, seconds
_PWR_TOP = 380.0       # W, fixed so the two power panels are comparable
_NOTE = ("NOT MEASURED - memory junction temp: not exposed by NVML on this "
         "part;  per-process power: not attributable under Windows WDDM;  "
         "system / wall power: not instrumented, board power only")


def _runs(t, ph, gapcap):
    """Contiguous (phase, t_start, t_end) runs, collector stalls excised.

    Sample i labels the interval (t[i-1], t[i]]. An interval longer than
    gapcap means the poller stalled: we know neither the phase nor the power
    across it, so it is charged to no phase and reported separately.
    """
    out, gap = [], 0.0
    cp = ca = cb = None
    for i in range(1, len(t)):
        span = t[i] - t[i - 1]
        if span <= 0:
            continue
        if span > gapcap:
            if cp is not None:
                out.append((cp, ca, cb))
                cp = None
            gap += span
            continue
        p = int(ph[i])
        if cp is None or p != cp:
            if cp is not None:
                out.append((cp, ca, cb))
            cp, ca, cb = p, t[i - 1], t[i]
        else:
            cb = t[i]
    if cp is not None:
        out.append((cp, ca, cb))
    return out, gap


def _seconds(runs):
    s = {0: 0.0, 1: 0.0, 2: 0.0}
    for p, a, b in runs:
        s[p] += b - a
    return s


def _joules(dmon, runs):
    """Board joules per phase, and the seconds of each phase the power trace
    actually covered. (None, None) when there is no usable power trace."""
    if dmon is None or len(dmon.get("t", ())) < 2:
        return None, None
    j = {0: 0.0, 1: 0.0, 2: 0.0}
    cov = {0: 0.0, 1: 0.0, 2: 0.0}
    for p, a, b in runs:
        e, sec = A.energy(dmon, a, b, busy_only=False)
        j[p] += e
        cov[p] += sec
    return j, cov


def _tok(n):
    if n >= 1e6:
        return "%.2f M" % (n / 1e6)
    if n >= 1e3:
        return "%.0f k" % (n / 1e3)
    return "%.0f" % n


def _shares(d, keys):
    tot = float(sum(d[k] for k in keys))
    return {k: (100.0 * d[k] / tot if tot > 0 else 0.0) for k in keys}, tot


def _pick_window(runs, t0, t1, width, step=30.0):
    """A REPRESENTATIVE zoom window: of every candidate window of this width,
    take the one whose phase-change count is the median. Not the busiest, not
    the calmest, and not chosen by eye - a window picked for appearance would
    make the duty cycle look like whatever the author wanted."""
    last = max(t1 - width, t0)
    starts = np.arange(t0, last + 1e-9, step)
    if len(starts) == 0:
        starts = np.asarray([t0])
    cnt = np.asarray([sum(1 for _, a, b in runs if b > s and a < s + width)
                      for s in starts])
    k = int(np.argsort(cnt, kind="stable")[len(cnt) // 2])
    w0 = float(starts[k])
    return w0, min(w0 + width, t1), int(cnt[k])


# --------------------------------------------------------------------------
def _fig_timeline(ctx, outdir, runs, secs, jou, gap, nreq, meta=None):
    t = ctx["slots"]["t"]
    dmon = ctx.get("dmon")
    t0, t1 = float(t[0]), float(t[-1])
    span = t1 - t0
    tot_s = sum(secs.values())

    fig = plt.figure(figsize=(10, 7.0), facecolor="white")
    gs = fig.add_gridspec(3, 1, height_ratios=[0.5, 1.9, 1.7],
                          hspace=0.58, left=0.085, right=0.985,
                          top=0.862, bottom=0.115)
    ax0 = fig.add_subplot(gs[0])
    ax1 = fig.add_subplot(gs[1], sharex=ax0)
    ax2 = fig.add_subplot(gs[2])
    for ax in (ax0, ax1, ax2):
        ax.set_facecolor("white")

    mw = ({p: jou[p] / secs[p] for p in (0, 1, 2)}
          if jou is not None and all(secs[p] > 0 for p in (0, 1, 2)) else None)

    # --- phase strip ------------------------------------------------------
    for p in (2, 1, 0):
        segs = [((a - t0) / 60.0, (b - a) / 60.0) for q, a, b in runs if q == p]
        if segs:
            ax0.broken_barh(segs, (0.0, 1.0), facecolors=_COL[p], linewidth=0)
    ax0.set_ylim(0, 1)
    ax0.set_yticks([])
    ax0.set_xlim(0, span / 60.0)
    ax0.set_ylabel("phase", fontsize=8.5)
    ax0.tick_params(labelbottom=False)
    lab = {p: "%s\n%.1f%% of wall-clock s" % (_NAME[p],
                                              100.0 * secs[p] / tot_s)
           for p in (2, 1, 0)}
    if mw is not None:
        for p in (2, 1, 0):
            lab[p] += "  |  %.0f W mean" % mw[p]
    ax0.legend(handles=[Patch(facecolor=_COL[p], label=lab[p])
                        for p in (2, 1, 0)],
               ncol=3, fontsize=7.6, loc="lower center",
               bbox_to_anchor=(0.5, 1.06), frameon=False,
               handlelength=1.6, columnspacing=1.6)

    # --- board power on the same time axis --------------------------------
    have_pwr = False
    if dmon is not None and len(dmon.get("t", ())) > 2:
        m = (dmon["t"] >= t0) & (dmon["t"] <= t1) & np.isfinite(dmon["pwr"])
        if int(m.sum()) > 2:
            have_pwr = True
            x = (dmon["t"][m] - t0) / 60.0
            y = dmon["pwr"][m]
            dt = float(np.median(np.diff(dmon["t"][m])))
            ax1.plot(x, y, lw=0.6, color=_RAW, zorder=2,
                     label="board power, per sample (%.2f s)" % dt)
            k = max(3, int(round(30.0 / max(dt, 1e-6))))
            if len(y) > k:
                mv = np.convolve(y, np.ones(k) / k, mode="valid")
                ax1.plot(x[k - 1:], mv, lw=1.5, color=_PWR, zorder=3,
                         label="30 s moving mean")
            ax1.legend(fontsize=8, loc="lower right", framealpha=0.92)
    if not have_pwr:
        ax1.text(0.5, 0.5, "board power: no dmon trace for this run\n"
                           "(the phases above are still measured)",
                 ha="center", va="center", fontsize=11, transform=ax1.transAxes)
    ax1.set_ylim(0, _PWR_TOP)
    ax1.set_xlim(0, span / 60.0)
    ax1.set_ylabel("board power (W)", fontsize=9.5)
    ax1.set_xlabel("elapsed time from the start of the /slots trace (minutes)",
                   fontsize=9.5)
    ax1.grid(alpha=_GA, linewidth=0.6)
    ax1.set_axisbelow(True)
    if mw is not None:
        ax1.set_title("Board power hardly marks the phase: decode %.0f W "
                      "against prompt-processing %.0f W - only %.0f W apart"
                      % (mw[2], mw[1], abs(mw[2] - mw[1])),
                      fontsize=9.2, pad=5)

    # --- representative zoom ---------------------------------------------
    w0, w1, nchg = _pick_window(runs, t0, t1, _ZOOM_S)
    for p, a, b in runs:
        if b <= w0 or a >= w1:
            continue
        ax2.axvspan(max(a, w0) - w0, min(b, w1) - w0, facecolor=_COL[p],
                    alpha=0.30, linewidth=0, zorder=1)
    if have_pwr:
        mz = (dmon["t"] >= w0) & (dmon["t"] <= w1) & np.isfinite(dmon["pwr"])
        if int(mz.sum()) > 1:
            ax2.plot(dmon["t"][mz] - w0, dmon["pwr"][mz], lw=1.3, color=_PWR,
                     marker="o", ms=2.6, zorder=4)
    ax2.set_ylim(0, _PWR_TOP)
    ax2.set_xlim(0, max(w1 - w0, 1.0))
    ax2.set_xlabel("elapsed time within the zoom window (s), starting %.1f min "
                   "into the trace" % ((w0 - t0) / 60.0), fontsize=9.5)
    ax2.set_ylabel("board power (W)", fontsize=9.5)
    ax2.grid(alpha=_GA, linewidth=0.6)
    ax2.set_axisbelow(True)
    ax2.set_title("The duty cycle at its true period: %.0f s with %d phase "
                  "changes - the MEDIAN such window, not one picked for looks"
                  % (w1 - w0, max(nchg - 1, 0)), fontsize=9.2, pad=5)
    handles = [Patch(facecolor=_COL[p], alpha=0.30, label=_NAME[p])
               for p in (2, 1, 0)]
    if have_pwr:
        handles.append(Line2D([], [], color=_PWR, marker="o", ms=3, lw=1.3,
                              label="board power (W)"))
    ax2.legend(handles=handles, ncol=4, fontsize=8, loc="lower center",
               framealpha=0.92)

    rl = [b - a for _, a, b in runs]
    fig.suptitle("Decode owns the clock: %.0f%% of wall-clock seconds, taken "
                 "in %d short bursts across %d requests"
                 % (100.0 * secs[2] / tot_s,
                    sum(1 for p, _, _ in runs if p == 2), nreq),
                 fontsize=13, y=0.985)
    model_sub = A.model_phrase(meta) if meta else "model identity not recorded"
    fig.text(0.5, 0.945,
             "%s  -  RTX 3090, %s  -  median "
             "phase run %.1f s, longest %.0f s%s"
             % (ctx.get("tag", "?"), model_sub, float(np.median(rl)), max(rl),
                ("" if gap <= 0 else
                 "  -  %.0f s of collector gap excluded" % gap)),
             ha="center", va="top", fontsize=8.7, color="#444444")
    fig.text(0.5, 0.022, _NOTE, ha="center", va="center", fontsize=7.3,
             color="#666666")

    p = os.path.join(outdir, "phases-timeline.png")
    fig.savefig(p, dpi=_DPI, facecolor="white")
    plt.close(fig)
    return p


# --------------------------------------------------------------------------
def _fig_split(ctx, outdir, secs, jou, tokens, cache_tok, nreq, inst, meta=None):
    ks = (2, 1, 0)
    s_sh, _ = _shares(secs, ks)
    t_sh, _ = _shares(tokens, ks)
    j_sh = _shares(jou, ks)[0] if jou is not None else None

    groups = ["wall-clock time\n(seconds)"]
    absfmt = [{p: "%.0f s" % secs[p] for p in ks}]
    shares = [s_sh]
    if j_sh is not None:
        groups.append("board energy\n(joules)")
        absfmt.append({p: "%.0f kJ" % (jou[p] / 1000.0) for p in ks})
        shares.append(j_sh)
    groups.append("tokens\n(count)")
    absfmt.append({2: _tok(tokens[2]) + "\n(floor)", 1: _tok(tokens[1]),
                   0: "0\nmeasured,\nnot missing"})
    shares.append(t_sh)

    fig = plt.figure(figsize=(10, 6.8), facecolor="white")
    gs = fig.add_gridspec(2, 2, width_ratios=[1.66, 1.0], hspace=0.66,
                          wspace=0.34, left=0.078, right=0.985,
                          top=0.830, bottom=0.240)
    axA = fig.add_subplot(gs[:, 0])
    axB = fig.add_subplot(gs[0, 1])
    axC = fig.add_subplot(gs[1, 1])
    for ax in (axA, axB, axC):
        ax.set_facecolor("white")

    # --- the inversion ----------------------------------------------------
    xs = np.arange(len(groups), dtype=float)
    w = 0.25
    for n, p in enumerate(ks):
        vals = [sh[p] for sh in shares]
        bars = axA.bar(xs + (n - 1) * w, vals, w, color=_COL[p],
                       label=_NAME[p], edgecolor="white", linewidth=0.6,
                       hatch=("//" if p == 0 else None))
        for gi, b in enumerate(bars):
            axA.text(b.get_x() + b.get_width() / 2.0, b.get_height() + 1.6,
                     "%.1f%%\n%s" % (vals[gi], absfmt[gi][p]),
                     ha="center", va="bottom", fontsize=7.3, linespacing=1.15)
    axA.set_xticks(xs)
    axA.set_xticklabels(groups, fontsize=9.5)
    axA.set_xlim(-0.66, len(groups) - 1 + 0.66)
    axA.set_ylim(0, 118)
    axA.set_ylabel("share of the run's total for that quantity (%)",
                   fontsize=9.5)
    axA.grid(alpha=_GA, axis="y", linewidth=0.6)
    axA.set_axisbelow(True)
    axA.legend(fontsize=8.5, loc="upper center", ncol=3, framealpha=0.92)
    axA.set_title("Read the three groups left to right: the ratio flips",
                  fontsize=10, pad=6)

    # --- why the ratio flips: per-token cost ------------------------------
    ok = tokens[2] > 0 and tokens[1] > 0 and secs[2] > 0 and secs[1] > 0
    if ok and jou is not None:
        jt = {p: jou[p] / tokens[p] for p in (2, 1)}
        bb = axB.bar(["decode", "prompt-\nprocessing"], [jt[2], jt[1]],
                     color=[_COL[2], _COL[1]], width=0.55, edgecolor="white")
        for r, v in zip(bb, (jt[2], jt[1])):
            axB.text(r.get_x() + r.get_width() / 2.0, v, "%.2f" % v,
                     ha="center", va="bottom", fontsize=8.5)
        axB.set_ylim(0, max(jt.values()) * 1.34)
        axB.set_ylabel("board energy per token\n(J / token)", fontsize=9)
        axB.set_title("decode: %.0fx the joules\nper token"
                      % (jt[2] / jt[1]), fontsize=9.5, pad=4)
    else:
        axB.text(0.5, 0.5, "board energy per token:\nNOT MEASURED - no usable "
                           "board-power\ntrace for this run",
                 ha="center", va="center", fontsize=9.5,
                 transform=axB.transAxes, linespacing=1.5)
        axB.set_xticks([])
        axB.set_yticks([])
    axB.grid(alpha=_GA, axis="y", linewidth=0.6)
    axB.set_axisbelow(True)

    if ok:
        mt = {p: 1000.0 * secs[p] / tokens[p] for p in (2, 1)}
        bb = axC.bar(["decode", "prompt-\nprocessing"], [mt[2], mt[1]],
                     color=[_COL[2], _COL[1]], width=0.55, edgecolor="white")
        for r, v, tp in zip(bb, (mt[2], mt[1]), (2, 1)):
            axC.text(r.get_x() + r.get_width() / 2.0, v,
                     "%.2f\n%.0f tok/s" % (v, tokens[tp] / secs[tp]),
                     ha="center", va="bottom", fontsize=8.2, linespacing=1.2)
        axC.set_ylim(0, max(mt.values()) * 1.48)
        axC.set_ylabel("time per token\n(ms / token)", fontsize=9)
        axC.set_title("prompt processing is batched:\n%.0fx cheaper per token"
                      % (mt[2] / mt[1]), fontsize=9.5, pad=4)
    else:
        axC.text(0.5, 0.5, "time per token:\nno token counts in the trace",
                 ha="center", va="center", fontsize=9.5,
                 transform=axC.transAxes, linespacing=1.5)
        axC.set_xticks([])
        axC.set_yticks([])
    axC.grid(alpha=_GA, axis="y", linewidth=0.6)
    axC.set_axisbelow(True)

    fig.suptitle("Same run, opposite ratios: decode is %.0f%% of the SECONDS "
                 "but %.0f%% of the TOKENS" % (s_sh[2], t_sh[2]),
                 fontsize=13, y=0.978)
    how = ("time is interval-weighted; energy is A.energy() integrated over "
           "each\ncontiguous phase run (busy_only=False) and summed by phase"
           if j_sh is not None else
           "time is interval-weighted; board energy is absent from this run "
           "and is\nreported as not measured, not as zero")
    model_sub = A.model_phrase(meta) if meta else "model identity not recorded"
    fig.text(0.5, 0.938,
             "%s, %d requests  -  RTX 3090, %s  -  %s"
             % (ctx.get("tag", "?"), nreq, model_sub, how),
             ha="center", va="top", fontsize=8.5, color="#444444",
             linespacing=1.4)

    ratio = tokens[1] / tokens[2] if tokens[2] > 0 else float("nan")
    para = ("%.2f prompt tokens are recomputed per token generated.   A "
            "further %s prompt tokens were served from KV cache and cost no "
            "prefill compute, so they\nare not counted above.   "
            "Decoded-token totals are a FLOOR: n_decoded is sampled between "
            "polls and the server clears it when a slot is released, so\n"
            "decode's token share is a lower bound and its per-token cost an "
            "upper bound." % (ratio, _tok(cache_tok)))
    if inst is not None:
        para += ("\nThe decode tok/s above is a PHASE AGGREGATE over every "
                 "decode second in the run; the instantaneous rate in the "
                 "same trace is median %.0f, p90 %.0f tok/s."
                 % (inst[0], inst[1]))
    fig.text(0.5, 0.158, para, ha="center", va="top", fontsize=8,
             color="#333333", linespacing=1.5)
    fig.text(0.5, 0.022, _NOTE, ha="center", va="center", fontsize=7.3,
             color="#666666")

    p = os.path.join(outdir, "phases-time-energy-tokens.png")
    fig.savefig(p, dpi=_DPI, facecolor="white")
    plt.close(fig)
    return p


# --------------------------------------------------------------------------
def make(ctx, outdir):
    """ctx has keys: tag, run, dmon, slots, host, throttle, requests,
    exercises (any may be None if that source is absent - degrade gracefully,
    never crash). Returns a list of (png_path, caption_string)."""
    out = []
    slots = ctx.get("slots")
    if slots is None or len(slots.get("t", ())) < 3:
        return out                   # no phase trace: nothing honest to draw
    try:
        os.makedirs(outdir, exist_ok=True)
    except OSError:
        return out

    t = slots["t"]
    ph = A.phase_of(slots)
    dts = np.diff(t)
    dts = dts[dts > 0]
    gapcap = max(5.0, 5.0 * float(np.median(dts))) if len(dts) else 5.0
    runs, gap = _runs(t, ph, gapcap)
    if not runs:
        return out
    secs = _seconds(runs)
    tot_s = sum(secs.values())
    if tot_s <= 0:
        return out

    dmon = ctx.get("dmon")
    jou, cov = _joules(dmon, runs)
    if jou is not None and (sum(cov.values()) < 0.5 * tot_s
                            or not all(np.isfinite(jou[p]) for p in (0, 1, 2))):
        # The power trace barely overlaps the run, or a NULL power sample has
        # poisoned a phase sum. Either way the joules are not measured, and a
        # not-measured energy is dropped and SAID rather than drawn.
        jou = None

    reqs = ctx.get("requests")
    if not reqs:
        try:
            reqs = A.requests(slots)
        except Exception:
            reqs = []
    nreq = len(reqs)
    tokens = {2: float(sum(r["ndec"] for r in reqs)),
              1: float(sum(r["nptp"] for r in reqs)),
              0: 0.0}
    cache_tok = float(sum(r["nptc"] for r in reqs))

    # The phase aggregate below sits under the campaign's steady-state decode
    # figure, and the two get misquoted against each other. Derive the
    # instantaneous distribution from this same trace so both are on the page.
    inst = None
    try:
        _, rate = A.decode_rate(slots, 1)
        if len(rate) >= 20:
            inst = (float(np.median(rate)), float(np.percentile(rate, 90)))
    except Exception:
        inst = None

    run_meta = ctx.get("meta")
    model_cond = A.model_phrase(run_meta) if run_meta else "model identity not recorded"
    drafter_cond = A.drafter_phrase(run_meta) if run_meta else ""
    cond = ("RTX 3090 (board power via NVML; system and wall power not "
            "measured), %s%s, "
            "aider polyglot agentic workload, run %s, tag %s. Phase accounting "
            "is scoped to the %.0f-minute /slots trace; GPU work outside that "
            "window is not counted."
            % (model_cond,
               (", %s" % drafter_cond) if drafter_cond else "",
               ctx.get("run", "?"), ctx.get("tag", "?"), tot_s / 60.0))

    try:
        p1 = _fig_timeline(ctx, outdir, runs, secs, jou, gap, nreq, meta=run_meta)
        mw = ""
        if jou is not None and all(secs[p] > 0 for p in (0, 1, 2)):
            fb = (np.nanmean(dmon["fb"]) / 1024.0
                  if dmon is not None and len(dmon.get("fb", ())) else float("nan"))
            mw = (" Mean board power is %.0f W in decode and %.0f W in prompt "
                  "processing - only %.0f W apart, so the phase cannot be read "
                  "off the power trace; the idle floor is %.0f W with %.1f GiB "
                  "still resident in VRAM."
                  % (jou[2] / secs[2], jou[1] / secs[1],
                     abs(jou[2] / secs[2] - jou[1] / secs[1]),
                     jou[0] / secs[0], fb))
        out.append((p1,
                    "Phase timeline with board power. %s Decode holds %.1f%% of "
                    "wall-clock seconds, prompt processing %.1f%% and idle "
                    "%.1f%%, alternating in %d runs across %d requests (median "
                    "run %.1f s).%s The lower panel is the %.0f s window whose "
                    "phase-change count is the median over every window of "
                    "that width, so it is representative rather than chosen "
                    "for appearance. Memory junction temperature and "
                    "per-process power are not exposed on this part: absent, "
                    "not zero."
                    % (cond, 100.0 * secs[2] / tot_s, 100.0 * secs[1] / tot_s,
                       100.0 * secs[0] / tot_s, len(runs), nreq,
                       float(np.median([b - a for _, a, b in runs])), mw,
                       _ZOOM_S)))
    except Exception as e:                        # a figure must never take the run down
        out.append((None, "phases-timeline.png could not be built: %r" % (e,)))

    try:
        p2 = _fig_split(ctx, outdir, secs, jou, tokens, cache_tok, nreq, inst, meta=run_meta)
        ej = ""
        if jou is not None and sum(jou.values()) > 0:
            tj = sum(jou.values())
            ej = (" Board energy splits %.1f%% decode / %.1f%% prompt "
                  "processing / %.1f%% idle of %.0f kJ, computed by "
                  "integrating A.energy() over each contiguous phase run with "
                  "busy_only=False and summing by phase."
                  % (100.0 * jou[2] / tj, 100.0 * jou[1] / tj,
                     100.0 * jou[0] / tj, tj / 1000.0))
        tt = tokens[2] + tokens[1]
        out.append((p2,
                    "Time, energy and tokens split between phases. %s Decode "
                    "takes %.1f%% of the seconds but only %.1f%% of the "
                    "tokens: %.2f prompt tokens are recomputed per token "
                    "generated, because prompt processing runs batched at "
                    "%.0f tok/s against decode's %.0f tok/s aggregate.%s "
                    "Decoded-token counts are a FLOOR - n_decoded is sampled "
                    "between polls and the server clears it when a slot is "
                    "released - so decode's token share is a lower bound and "
                    "its per-token cost an upper bound. A further %s prompt "
                    "tokens hit KV cache and are excluded, since they cost no "
                    "prefill compute."
                    % (cond, 100.0 * secs[2] / tot_s,
                       (100.0 * tokens[2] / tt) if tt else float("nan"),
                       (tokens[1] / tokens[2]) if tokens[2] else float("nan"),
                       (tokens[1] / secs[1]) if secs[1] else float("nan"),
                       (tokens[2] / secs[2]) if secs[2] else float("nan"),
                       ej, _tok(cache_tok)) +
                    ("" if inst is None else
                     " The %.0f tok/s decode figure is a phase aggregate over "
                     "every decode second in the run, so it sits below "
                     "steady-state decode: instantaneous rate in the same "
                     "trace is median %.0f tok/s, p90 %.0f tok/s."
                     % (tokens[2] / secs[2] if secs[2] else float("nan"),
                        inst[0], inst[1]))))
    except Exception as e:
        out.append((None, "phases-time-energy-tokens.png could not be built: "
                          "%r" % (e,)))

    return [(p, c) for p, c in out if p]
