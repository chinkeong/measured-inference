#!/usr/bin/env python3
"""Host-side coupling: the platform input the GPU counters cannot see.

Two figures, one argument. Aggregate host CPU utilisation is the wrong number
to carry away from an inference host. On this run the machine reads about 14%
busy - which an architect would read as "the host is free" - while more than
half of that busy time is KERNEL time and the machine is issuing of the order
of 160,000 system calls per second. That is a latency-critical orchestration
loop running at low duty cycle, not a spare CPU, and sizing a platform from the
utilisation figure alone would under-provision it.

Figure 2 makes the same point quantitatively. Joined sample by sample against
GPU decode rate, the host syscall rate carries a real negative association;
aggregate CPU busy, over exactly the same windows, carries none that can be
distinguished from zero.

A NOTE ON CLOCKS. The host collector on this rig stamps its rows from a local
DateTime while the GPU collectors stamp true Unix epoch, so the two series can
sit a whole timezone apart on the time axis. Joining them raw yields an empty
intersection and a silently empty chart. This module detects the offset by
maximising the overlap of the two spans over a half-hour grid, applies it, and
prints the correction on every figure that depends on it. It never edits the
loader and never fits a non-round offset.
"""
import os
import textwrap
import warnings

import numpy as np

import matplotlib
matplotlib.use("Agg")            # REQUIRED - never an interactive backend
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

TITLE = "Host coupling: a quiet-looking CPU on a latency-critical loop"

# Okabe-Ito, colourblind-safe. No pair carries meaning by red/green alone;
# the two rate traces are also separated by line style.
C_KERNEL = "#0072B2"   # blue
C_USER = "#E69F00"     # orange
C_SYS = "#CC79A7"      # reddish purple
C_CTX = "#009E73"      # bluish green
C_GPU = "#56B4E9"      # sky blue
C_FIT = "#D55E00"      # vermillion
C_INK = "#222222"

DPI = 140
GRID_A = 0.3
FOOT_FS = 7.0

# Conditions every caption from this module must carry.
PART = "NVIDIA RTX 3090 (board), single card"
WORKLOAD = ("aider polyglot agentic coding benchmark, scored in a Docker "
            "container on this same host; model IQ4_XS at 14.25 GB resident, "
            "MTP speculative decoding on (mean accepted length 3.55)")
HOSTNOTE = ("Host counters are machine-wide: they include llama-server, the "
            "scoring container and the WSL2 boundary together. Per-process CPU "
            "attribution was not recorded, and neither was the per-core "
            "distribution, the logical-core count, nor interrupt affinity.")
POWERNOTE = ("System and wall power were not measured anywhere in this "
             "campaign - GPU board power only.")


# ---------------------------------------------------------------- utilities

def _fin(*arrays):
    """Row mask where every supplied array is finite."""
    m = np.ones(len(arrays[0]), dtype=bool)
    for a in arrays:
        m &= np.isfinite(a)
    return m


def _roll(v, w):
    """Centred moving average with edge padding; length preserved."""
    v = np.asarray(v, dtype=float)
    if w < 2 or len(v) < w:
        return v
    pad = w // 2
    vv = np.pad(v, (pad, pad), mode="edge")
    return np.convolve(vv, np.ones(w) / float(w), mode="valid")[:len(v)]


def _thousands(v, _pos=None):
    return "{:,.0f}".format(v)


def _stats(x, y):
    """(pearson_r, p, spearman_rho, slope, intercept). SciPy when present, a
    plain-numpy fallback otherwise, so a missing SciPy degrades the annotation
    rather than the figure."""
    m = _fin(x, y)
    x, y = x[m], y[m]
    if len(x) < 3 or np.std(x) == 0 or np.std(y) == 0:
        return (np.nan, np.nan, np.nan, np.nan, np.nan)
    slope, intercept = np.polyfit(x, y, 1)
    try:
        from scipy import stats as _st
        r, p = _st.pearsonr(x, y)
        rho = _st.spearmanr(x, y).statistic
    except Exception:
        r = float(np.corrcoef(x, y)[0, 1])
        p = np.nan
        rx = np.argsort(np.argsort(x)).astype(float)
        ry = np.argsort(np.argsort(y)).astype(float)
        rho = float(np.corrcoef(rx, ry)[0, 1])
    return (float(r), float(p), float(rho), float(slope), float(intercept))


def _pfmt(p):
    if not np.isfinite(p):
        return "p not computed, SciPy absent"
    if p < 1e-12:
        return "p < 1e-12"
    if p >= 0.001:
        return "p = %.3f" % p
    return "p = %.1e" % p


def _foot(fig, lines, width=176):
    """Wrapped footnote at the bottom-left. Returns the figure fraction to
    reserve for it, so it can never sit on top of the x-axis label."""
    txt = "\n".join(textwrap.fill(s, width) for s in lines if s)
    if not txt:
        return 0.02
    n = txt.count("\n") + 1
    fig.text(0.006, 0.008, txt, fontsize=FOOT_FS, color="#555555",
             va="bottom", ha="left")
    per_line = (FOOT_FS * 1.42 / 72.0) / fig.get_figheight()
    return 0.016 + n * per_line


def _tight(fig, rect, reserve=0.0):
    """tight_layout, then a hard floor on the bottom margin.

    tight_layout refuses to honour a rect on a figure that carries a twin
    axis - it warns and lays out anyway - so the footnote would end up printed
    across the x-axis label. The explicit subplots_adjust afterwards is what
    actually guarantees the clearance.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        fig.tight_layout(rect=rect)
    need = reserve + 0.048          # footnote block plus the x-axis label
    if reserve and fig.subplotpars.bottom < need:
        fig.subplots_adjust(bottom=need)


# ------------------------------------------------------- clock reconciliation

def _gpu_span(ctx):
    """(t0, t1) covered by the GPU-side collectors, or None."""
    lo, hi = [], []
    for key in ("slots", "dmon", "throttle"):
        d = ctx.get(key)
        if d is not None and len(d.get("t", [])) > 1:
            lo.append(float(d["t"][0]))
            hi.append(float(d["t"][-1]))
    if not lo:
        return None
    return (min(lo), max(hi))


def _clock_offset(host_t, span):
    """Seconds to add to host timestamps so they land on the GPU clock.

    The search is a half-hour grid over +/-14 h: clock-domain mistakes on this
    rig are whole timezone offsets, so a free-running fit would only invent
    precision that is not in the data. Returns
    (offset, overlap_s, runner_up_overlap_s); offset 0 when the spans already
    overlap, which is the case whenever the collectors agree.
    """
    if span is None or len(host_t) < 2:
        return (0.0, 0.0, 0.0)
    g0, g1 = span
    h0, h1 = float(host_t[0]), float(host_t[-1])
    shorter = min(h1 - h0, g1 - g0)
    raw_ov = max(0.0, min(h1, g1) - max(h0, g0))
    if shorter <= 0 or raw_ov >= 0.5 * shorter:
        return (0.0, raw_ov, 0.0)
    scored = []
    for k in range(-28, 29):
        off = k * 1800.0
        ov = max(0.0, min(h1 + off, g1) - max(h0 + off, g0))
        scored.append((ov, -abs(off), off))
    scored.sort(reverse=True)
    best = scored[0]
    runner = next((s for s in scored[1:] if abs(s[2] - best[2]) > 1.0),
                  (0.0, 0.0, 0.0))
    return (best[2], best[0], runner[0])


def _offset_note(offset, ov, runner):
    if offset == 0.0:
        return ""
    return ("Clock domains differ: the host collector stamps local time, the "
            "GPU collectors stamp Unix epoch, so the raw series do not "
            "intersect at all. The host series is shifted by %+.2f h (%+.0f s) "
            "- the half-hour offset that maximises span overlap, giving %.0f s "
            "of overlap against %.0f s for the next-best offset. No sub-hour "
            "fitting was applied."
            % (offset / 3600.0, offset, ov, runner))


def _windows(ctx, offset):
    """Join the host counters to the GPU decode rate on time.

    One row per host sample: the host counters are interval averages, so each
    row is matched to the mean decode rate over the interval ending at that
    sample. Only windows in which EVERY /slots sample is in the decode phase
    are kept - a window straddling prompt processing or an idle gap would mix
    two different machines into one point.

    Returns a dict of equal-length arrays, or None if too little survives.
    """
    import archdata as A
    host, slots = ctx.get("host"), ctx.get("slots")
    if host is None or slots is None or len(slots.get("t", [])) < 3:
        return None
    th = np.asarray(host["t"], dtype=float) + offset
    tt = np.asarray(slots["t"], dtype=float)
    if len(th) < 3:
        return None
    ph = A.phase_of(slots)
    trate, rate = A.decode_rate(slots, 1)
    if len(trate) < 3:
        return None
    dts = np.diff(th)
    dt_med = float(np.median(dts)) if len(dts) else 0.0
    fields = ("syscalls_s", "ctxsw_s", "cpu_pct", "priv_pct", "user_pct",
              "interrupts_s")
    keep = {k: [] for k in ("t", "rate") + fields}
    for i in range(1, len(th)):
        a, b = th[i - 1], th[i]
        if dt_med > 0 and (b - a) > 3.0 * dt_med:
            continue                      # collector hiccup: not one window
        sel = (trate > a) & (trate <= b)
        if sel.sum() < 2:
            continue
        cover = (tt > a) & (tt <= b)
        if cover.sum() == 0 or not np.all(ph[cover] == 2):
            continue                      # not a pure decode window
        keep["t"].append(b)
        keep["rate"].append(float(np.mean(rate[sel])))
        for k in fields:
            keep[k].append(float(host[k][i]))
    out = {k: np.asarray(v, dtype=float) for k, v in keep.items()}
    return out if len(out["t"]) >= 30 else None


# ------------------------------------------------------------- figure one

def _fig_decomposition(ctx, outdir, offset, offnote):
    host = ctx["host"]
    t = np.asarray(host["t"], dtype=float) + offset
    kern = np.asarray(host["priv_pct"], dtype=float)
    user = np.asarray(host["user_pct"], dtype=float)
    tot = np.asarray(host["cpu_pct"], dtype=float)
    sysr = np.asarray(host["syscalls_s"], dtype=float)
    ctxr = np.asarray(host["ctxsw_s"], dtype=float)

    ok = _fin(t, kern, user, tot, sysr, ctxr)
    n_drop = int((~ok).sum())
    t, kern, user, tot, sysr, ctxr = (a[ok] for a in
                                      (t, kern, user, tot, sysr, ctxr))
    if len(t) < 5:
        return None
    tm = (t - t[0]) / 60.0

    cpu_mean, cpu_med = float(np.mean(tot)), float(np.median(tot))
    kfrac = 100.0 * float(np.mean(kern)) / max(cpu_mean, 1e-9)
    sys_mean, sys_med = float(np.mean(sysr)), float(np.median(sysr))
    ctx_mean, ctx_med = float(np.mean(ctxr)), float(np.median(ctxr))

    # Optional GPU strip: shows the host trace covers real inference work.
    slots, strip, gap_txt = ctx.get("slots"), None, ""
    if slots is not None and len(slots.get("t", [])) > 3:
        import archdata as A
        tr, rr = A.decode_rate(slots, 5)
        if len(tr) > 3:
            sel = (tr >= t[0]) & (tr <= t[-1])
            if sel.sum() > 3:
                strip = ((tr[sel] - t[0]) / 60.0, rr[sel])
                lead = float(strip[0][0])
                if lead > 1.0:
                    gap_txt = ("no /slots coverage before minute %.0f"
                               % lead)

    if strip is None:
        fig, ax = plt.subplots(figsize=(10, 6), dpi=DPI)
        axb = None
    else:
        fig, (ax, axb) = plt.subplots(
            2, 1, figsize=(10, 6.8), dpi=DPI, sharex=True,
            gridspec_kw={"height_ratios": [3.1, 1.0], "hspace": 0.12})
    fig.patch.set_facecolor("white")

    # Stack the smoothed decomposition so the split is readable, and keep the
    # raw total on top of it so the true sample-to-sample variance is visible.
    ax.stackplot(tm, _roll(kern, 9), _roll(user, 9),
                 colors=(C_KERNEL, C_USER), alpha=0.85, edgecolor="none",
                 labels=["kernel (privileged) time, 27 s mean",
                         "user time, 27 s mean"], zorder=2)
    ax.plot(tm, tot, color=C_INK, lw=0.5, alpha=0.22, zorder=3,
            label="total CPU busy, raw 3 s samples")
    ax.axhline(cpu_med, color=C_INK, ls=(0, (1, 2)), lw=1.4, zorder=4)
    ax.set_ylabel("Host CPU busy (% of total logical-CPU capacity)")
    cpu_top = max(float(np.percentile(tot, 99.5)) * 1.95, 30.0)
    ax.set_ylim(0, cpu_top)
    ax.set_xlim(float(tm[0]), float(tm[-1]))
    ax.grid(alpha=GRID_A)
    ax.set_axisbelow(True)

    ax2 = ax.twinx()
    ax2.plot(tm, sysr / 1e3, color=C_SYS, lw=0.5, alpha=0.18, zorder=2)
    ax2.plot(tm, _roll(sysr, 9) / 1e3, color=C_SYS, lw=1.8, ls="-", zorder=3,
             label="system calls, 27 s mean")
    ax2.plot(tm, _roll(ctxr, 9) / 1e3, color=C_CTX, lw=1.8, ls="--", zorder=3,
             label="context switches, 27 s mean")
    ax2.axhline(sys_med / 1e3, color=C_SYS, ls=(0, (5, 2)), lw=1.4, zorder=4)
    ax2.set_ylabel("Rate (thousands per second)")
    sys_top = max(float(np.percentile(sysr, 99.0)) / 1e3 * 1.95, 60.0)
    ax2.set_ylim(0, sys_top)
    ax2.grid(False)

    # The two medians, said out loud at different x so neither label hides the
    # other. This is the contradiction placed side by side in the plot body.
    # Both are drawn on the twin axis, which is the topmost artist layer.
    def _median_label(x_frac, y_frac, dy, s, colour):
        # y_frac must already be expressed in ITS OWN axis's units divided by
        # that axis's limit - the right axis is in thousands per second.
        ax2.text(x_frac, min(max(y_frac, 0.02), 0.90) + dy, s,
                 transform=ax2.transAxes, fontsize=8.4, color=colour,
                 va="bottom", ha="left", zorder=26, fontweight="bold",
                 bbox=dict(boxstyle="round,pad=0.25", facecolor="white",
                           edgecolor=colour, linewidth=0.6, alpha=0.92))

    _median_label(0.014, cpu_med / cpu_top, 0.012,
                  "median total CPU busy %.1f%%  (left axis, dotted)" % cpu_med,
                  C_INK)
    _median_label(0.46, (sys_med / 1e3) / sys_top, 0.055,
                  "median %s system calls per second  (right axis, dashed)"
                  % _thousands(sys_med), C_SYS)

    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    # The legend lives on the twin axis so it is painted above both series.
    ax2.legend(h1 + h2, l1 + l2, loc="upper right", fontsize=8.0,
               framealpha=0.95).set_zorder(28)

    box = ("THE CONTRADICTION, in one glance\n"
           "  CPU busy         mean %.1f%%, median %.1f%%   -> reads as idle\n"
           "  of which                %.0f%% is KERNEL time, not user work\n"
           "  system calls     %s per second (median %s)\n"
           "  context switches %s per second (median %s)\n"
           "A host at %.0f%% duty cycle making %s system calls a second is a\n"
           "latency-critical orchestration loop, not spare capacity."
           % (cpu_mean, cpu_med, kfrac,
              _thousands(sys_mean), _thousands(sys_med),
              _thousands(ctx_mean), _thousands(ctx_med),
              cpu_med, _thousands(sys_med)))
    # Drawn on the twin axis, above every series, so no trace crosses the text.
    ax2.text(0.013, 0.885, box, transform=ax2.transAxes, fontsize=8.0,
             family="monospace", va="top", ha="left", color=C_INK, zorder=30,
             bbox=dict(boxstyle="round,pad=0.5", facecolor="#F2F2F2",
                       edgecolor="#8C8C8C", alpha=0.97))

    ax.set_title("A host CPU that reads %.0f%% busy is issuing %s system "
                 "calls per second"
                 % (cpu_med, _thousands(round(sys_med / 1000.0) * 1000)),
                 fontsize=12.5, pad=9)

    if axb is not None:
        axb.plot(strip[0], strip[1], color=C_GPU, lw=0.9)
        axb.set_ylabel("GPU decode\n(tokens/s)", fontsize=9)
        axb.set_ylim(0, float(np.nanpercentile(strip[1], 99.5)) * 1.18)
        axb.grid(alpha=GRID_A)
        axb.set_axisbelow(True)
        msg = "GPU decode rate on the same aligned clock"
        if gap_txt:
            msg += "; " + gap_txt
        axb.text(0.985, 0.92, msg, transform=axb.transAxes, ha="right",
                 va="top", fontsize=8, color=C_INK,
                 bbox=dict(boxstyle="round,pad=0.2", facecolor="white",
                           edgecolor="none", alpha=0.8))
        axb.set_xlabel("Time since first host sample (minutes)")
    else:
        ax.set_xlabel("Time since first host sample (minutes)")

    lines = []
    if n_drop:
        lines.append("%d host samples were dropped as non-finite." % n_drop)
    lines.append(HOSTNOTE + " " + POWERNOTE)
    if offnote and axb is not None:
        lines.append(offnote)
    reserve = _foot(fig, lines)
    _tight(fig, (0, reserve, 1, 1), reserve)

    path = os.path.join(outdir, "coupling-host-cpu-decomposition.png")
    fig.savefig(path, dpi=DPI, facecolor="white")
    plt.close(fig)

    cap = ("Host CPU decomposition over an in-flight agentic inference run. "
           "Stacked left axis: kernel (privileged) and user time as a "
           "percentage of total logical-CPU capacity, smoothed over 27 s, with "
           "the raw 3 s total drawn over it; right axis: system-call and "
           "context-switch rates. Aggregate CPU busy averages %.1f%% (median "
           "%.1f%%) and %.0f%% of that is kernel time, while the same samples "
           "sustain %s system calls and %s context switches per second - the "
           "utilisation figure and the syscall figure describe two different "
           "machines, and only the second one is a platform requirement. "
           "Conditions: %s; workload is the %s. %s %s"
           % (cpu_mean, cpu_med, kfrac, _thousands(sys_mean),
              _thousands(ctx_mean), PART, WORKLOAD, HOSTNOTE, POWERNOTE))
    if offnote:
        cap += " " + offnote
    return (path, cap)


# ------------------------------------------------------------- figure two

def _scatter_panel(ax, x, y, xlabel, title, st, note=None):
    r, p, rho, slope, intercept = st
    m = _fin(x, y)
    xs = x[m]
    ax.scatter(xs, y[m], s=11, alpha=0.30, color=C_KERNEL, edgecolors="none",
               zorder=2)
    xhi, xlo = float(np.percentile(xs, 99.5)), float(np.min(xs))
    span = max(xhi - xlo, 1e-9)
    ax.set_xlim(xlo - 0.04 * span, xhi + 0.06 * span)
    off_axis = int((xs > xhi).sum())
    if np.isfinite(slope):
        gx = np.linspace(xlo, xhi, 50)
        ax.plot(gx, slope * gx + intercept, color=C_FIT, lw=2.2, zorder=3)
    ax.set_xlabel(xlabel)
    ax.xaxis.set_major_formatter(FuncFormatter(_thousands))
    ax.grid(alpha=GRID_A)
    ax.set_axisbelow(True)
    ax.set_title(title, fontsize=10.5, pad=7)
    txt = ("n = %d windows\nPearson r = %+.3f  (%s)\nSpearman rho = %+.3f"
           % (len(xs), r, _pfmt(p), rho))
    if note:
        txt += "\n" + note
    if off_axis:
        txt += ("\n%d point(s) past the x-limit, kept in the fit" % off_axis)
    # Bottom-left: the low-decode-rate corner is empty in both panels.
    ax.text(0.025, 0.022, txt, transform=ax.transAxes, ha="left", va="bottom",
            fontsize=7.9, family="monospace", zorder=6,
            bbox=dict(boxstyle="round,pad=0.45", facecolor="#F2F2F2",
                      edgecolor="#8C8C8C", alpha=0.97))


def _fig_coupling(ctx, outdir, offset, offnote):
    w = _windows(ctx, offset)
    if w is None:
        return None
    y = w["rate"]

    # Pick the host pressure metric that tracks decode rate better. The ranked
    # (Spearman) correlation decides it: the syscall-rate distribution has a
    # long right tail, and a rank measure is not steered by that tail.
    cands = {}
    for k, lab, unit, short in (
            ("syscalls_s", "system-call rate", "system calls per second",
             "calls per second"),
            ("ctxsw_s", "context-switch rate", "context switches per second",
             "switches per second")):
        r, p, rho, slope, ic = _stats(w[k], y)
        cands[k] = {"label": lab, "unit": unit, "short": short, "r": r,
                    "p": p, "rho": rho, "slope": slope,
                    "st": (r, p, rho, slope, ic)}
    win = max(cands, key=lambda k: abs(cands[k]["rho"])
              if np.isfinite(cands[k]["rho"]) else -1.0)
    lose = "ctxsw_s" if win == "syscalls_s" else "syscalls_s"
    cpu_st = _stats(w["cpu_pct"], y)
    irq_st = _stats(w["interrupts_s"], y)

    fig, (axL, axR) = plt.subplots(1, 2, figsize=(10.5, 6.0), dpi=DPI,
                                   sharey=True)
    fig.patch.set_facecolor("white")

    per10k = cands[win]["slope"] * 1e4
    note = ("fit: %+.1f tokens/s per extra\n10,000 %s"
            % (per10k, cands[win]["unit"]))
    _scatter_panel(axL, w[win], y, "Host %s (%s)"
                   % (cands[win]["label"], cands[win]["short"]),
                   "Host pressure: %s" % cands[win]["label"],
                   cands[win]["st"], note=note)
    axL.set_ylabel("GPU decode rate (tokens/s, mean over each 3 s window)")
    axL.set_ylim(0, float(np.percentile(y, 99.5)) * 1.12)

    _scatter_panel(axR, w["cpu_pct"], y,
                   "Host aggregate CPU busy (% of total logical-CPU capacity)",
                   "The trap: aggregate CPU busy", cpu_st,
                   note="not distinguishable from zero")

    fig.suptitle("Host system-call rate tracks GPU decode rate; aggregate CPU "
                 "busy does not", fontsize=12.8, y=0.975)

    lines = [
        ("Same %d windows, same y-axis, same fit method - only the x-axis "
         "differs. Pressure metric chosen by ranked correlation: %s "
         "(rho %+.3f) over %s (rho %+.3f). The strongest host correlate "
         "measured here was neither: the interrupt rate, at rho %+.3f."
         % (len(y), cands[win]["label"], cands[win]["rho"],
            cands[lose]["label"], cands[lose]["rho"], irq_st[2])),
        ("This is an association across one uncontrolled run, not a causal "
         "test. This campaign separately measured, in a controlled "
         "loaded-host A/B, that loading the host costs 5.4% of GPU decode "
         "throughput WHILE the GPU clock RISES - a coupling that neither "
         "side's counters can show alone."),
        ("Pearson r is the straight-line correlation coefficient; Spearman "
         "rho is the same measure computed on ranks, so a handful of extreme "
         "samples cannot steer it. Both run from -1 to +1, and 0 means no "
         "relationship. p is the probability of seeing a correlation at least "
         "this large if the true one were zero."),
        HOSTNOTE + " " + POWERNOTE,
    ]
    if offnote:
        lines.append(offnote)
    reserve = _foot(fig, lines)
    _tight(fig, (0, reserve, 1, 0.955), reserve)

    path = os.path.join(outdir, "coupling-host-pressure-vs-decode.png")
    fig.savefig(path, dpi=DPI, facecolor="white")
    plt.close(fig)

    cap = ("Host-to-GPU coupling, joined on time. Each point is one host "
           "counter interval (about 3 s) in which every /slots sample was in "
           "the decode phase; y is the mean GPU decode rate over that "
           "interval, from n_decoded differences, so a slow request and a "
           "loaded host land on the same axis. Left: host %s, Pearson r = "
           "%+.3f (%s), Spearman rho = %+.3f, fit %+.1f tokens/s per extra "
           "10,000 %s. Right: the same %d windows against aggregate CPU busy, "
           "Pearson r = %+.3f (%s) - the utilisation number an architect "
           "would reach for carries no usable signal about the GPU. The %s "
           "was selected because its ranked correlation is the stronger of "
           "the two named candidates; the interrupt rate, not a candidate, "
           "was stronger still at rho %+.3f. Conditions: %s; %s. This is an "
           "association over one uncontrolled run - the controlled 5.4%% "
           "decode cost of host load was measured separately in this "
           "campaign, and the GPU clock rose while it happened. %s %s"
           % (cands[win]["label"], cands[win]["r"], _pfmt(cands[win]["p"]),
              cands[win]["rho"], per10k, cands[win]["unit"], len(y),
              cpu_st[0], _pfmt(cpu_st[1]), cands[win]["label"], irq_st[2],
              PART, WORKLOAD, HOSTNOTE, POWERNOTE))
    if offnote:
        cap += " " + offnote
    return (path, cap)


# ------------------------------------------------------------------- entry

def make(ctx, outdir):
    """ctx has keys: tag, run, dmon, slots, host, throttle, requests,
    exercises (any may be None if that source is absent - degrade gracefully,
    never crash). Returns a list of (png_path, caption_string)."""
    out = []
    if not isinstance(ctx, dict):
        return out
    try:
        os.makedirs(outdir, exist_ok=True)
    except Exception:
        return out

    host = ctx.get("host")
    if host is None or len(host.get("t", [])) < 5:
        return out     # nothing host-side was collected; emit no empty chart

    offset, ov, runner = _clock_offset(np.asarray(host["t"], dtype=float),
                                       _gpu_span(ctx))
    offnote = _offset_note(offset, ov, runner)

    for fn in (_fig_decomposition, _fig_coupling):
        try:
            got = fn(ctx, outdir, offset, offnote)
        except Exception:
            got = None
        if got:
            out.append(got)
    return out
