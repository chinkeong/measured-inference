#!/usr/bin/env python3
"""Power-performance efficiency: where should the board power limit sit?

Two figures.

(1) The measured operating cloud of the agentic workload, on a
    throughput-against-board-power plane with iso-efficiency contours
    (lines of constant joules per decoded token) underneath. A contour is a
    ray through the origin, because J/token = W / (tokens per second), so
    "up and to the left" is unambiguously the better direction.

(2) The previously published power-cap sweep as an arm-level curve on the
    SAME plane, with the agentic operating point overlaid, so the reader
    can see that the two live in different power regimes. The sweep's
    synthetic decode never reaches its own 350 W limit; the agentic
    workload sits on the limit almost continuously. That caveat is printed
    on the figure rather than left to a footnote.

This module only ever writes the PNGs it is handed an output directory for.
"""
import io
import json
import os
import sys
import textwrap

import matplotlib
matplotlib.use("Agg")            # REQUIRED - never an interactive backend
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import archdata as A

TITLE = "Power-performance Pareto and the power-cap decision"

# Okabe-Ito, colourblind-safe. No two series are separated by red-against-
# green alone; every series also differs in marker, hatch or line style.
_C_CLOUD = "#0072B2"     # blue      - measured agentic operating points
_C_MED = "#D55E00"       # vermilion - the median operating point
_C_SWEEP = "#CC79A7"     # purple    - the published cap sweep
_C_SWEEP_TXT = "#6B2D55"
_C_TPS = "#0072B2"       # blue      - throughput bars
_C_PWR = "#E69F00"       # orange    - board power bars
_C_JPT = "#009E73"       # green     - energy-per-token bars
_C_LINE = "#3A3A3A"      # contour lines, arrows, secondary text

_DPI = 140
_GRID_A = 0.3
_BOX = dict(boxstyle="round,pad=0.5", facecolor="#F4F4F4",
            edgecolor="#BBBBBB", alpha=0.95)

# A poll-to-poll gap longer than this is a stall, not a decode rate.
_MAX_GAP_S = 4.0
# Nearest-sample join tolerance between the slots trace and the dmon trace.
_JOIN_TOL_S = 1.0
# Any JSON larger than this under results/ is a transcript dump, not a sweep.
_MAX_JSON_BYTES = 2_000_000

_NOT_MEASURED = (
    "Not measured: wall or system power - this is the GPU board rail read "
    "in-band by NVML, so power supply loss, CPU, RAM, drives and fans are all "
    "excluded; per-process power attribution (NVML pmon reports \"-\" for "
    "every process under Windows WDDM); memory-junction temperature (NULL on "
    "this part, so memory thermal headroom is unknown).")


# ----------------------------------------------------------------- helpers

def _nearest(src_t, vals, q_t, tol):
    """Value of `vals` at the source sample nearest each query time.

    Returns (values, ok); ok marks queries whose nearest sample lies within
    `tol` seconds. Both arrays have the length of q_t.
    """
    src_t = np.asarray(src_t, dtype=float)
    q_t = np.asarray(q_t, dtype=float)
    if len(src_t) == 0 or len(q_t) == 0:
        return np.full(len(q_t), np.nan), np.zeros(len(q_t), dtype=bool)
    j = np.clip(np.searchsorted(src_t, q_t), 1, len(src_t) - 1)
    left = np.abs(q_t - src_t[j - 1])
    right = np.abs(src_t[j] - q_t)
    pick = np.where(right < left, j, j - 1)
    gap = np.abs(src_t[pick] - q_t)
    return np.asarray(vals, dtype=float)[pick], gap <= tol


def _operating_points(slots, dmon):
    """Per-moment (board watts, tokens per second) points during decode.

    Only intervals whose BOTH endpoints are decode samples of the SAME task
    are used. The first interval of every decode run is dropped on purpose:
    it begins inside prompt processing, so its token count is spread over a
    window that was not all generation, and keeping it drags a long false
    tail of slow points across the plot.
    """
    if slots is None or dmon is None:
        return None
    if len(slots.get("t", ())) < 3 or len(dmon.get("t", ())) < 2:
        return None
    ph = A.phase_of(slots)
    t, tps, dts, dns, depth = [], [], [], [], []
    for i in range(1, len(slots["t"])):
        if ph[i] != 2 or ph[i - 1] != 2:
            continue
        if slots["id_task"][i] != slots["id_task"][i - 1]:
            continue
        dt = slots["t"][i] - slots["t"][i - 1]
        dn = slots["n_decoded"][i] - slots["n_decoded"][i - 1]
        if dt <= 0 or dt > _MAX_GAP_S or dn <= 0:
            continue
        t.append(slots["t"][i])
        tps.append(dn / dt)
        dts.append(dt)
        dns.append(dn)
        depth.append(slots["n_prompt_tokens_processed"][i]
                     + slots["n_prompt_tokens_cache"][i])
    if len(t) < 10:
        return None
    t = np.asarray(t, dtype=float)
    w, ok = _nearest(dmon["t"], dmon["pwr"], t, _JOIN_TOL_S)
    ok = ok & np.isfinite(w)
    if int(ok.sum()) < 10:
        return None
    return {"t": t[ok], "tps": np.asarray(tps)[ok], "w": w[ok],
            "dt": np.asarray(dts)[ok], "dn": np.asarray(dns)[ok],
            "depth": np.asarray(depth)[ok], "n_unjoined": int((~ok).sum())}


def _cap_bit_fraction(dmon, throttle):
    """(power-cap %, thermal %, n) over busy samples, or None.

    Reads the raw NVML bits, so a sample that is both power-capped and
    thermally capped counts in both. That is the right statistic for "does
    this workload sit on its power limit", unlike the one-label-per-sample
    severity view a stacked plot needs, which would hide a power cap behind
    a thermal cap.
    """
    if throttle is None or dmon is None:
        return None
    tt = throttle.get("t")
    mask = throttle.get("mask")
    if tt is None or mask is None or len(tt) == 0:
        return None
    mask = np.asarray(mask, dtype=np.int64)
    sm, ok = _nearest(dmon["t"], dmon["sm"], tt, _JOIN_TOL_S * 4)
    busy = ok & np.isfinite(sm) & (sm > A.BUSY_SM_PCT) & (mask >= 0)
    if int(busy.sum()) < 20:
        return None
    bits = {name: bit for bit, name in A.THROTTLE_BITS}
    f_pwr = 100.0 * ((mask[busy] & bits["SW power cap"]) > 0).mean()
    f_thm = 100.0 * ((mask[busy] & bits["SW thermal"]) > 0).mean()
    return f_pwr, f_thm, int(busy.sum())


def _iso_efficiency(ax, xlim, ylim, lab_fx=0.13, lab_lo=0.05, lab_hi=0.72):
    """Shade and label lines of constant joules per decoded token.

    J/token = board watts / (tokens per second), so an iso-efficiency line
    is a ray through the origin. Darker shading is more joules per token,
    which is worse.

    The labels are placed by hand in a single column at `lab_fx` across the
    axes, because matplotlib's automatic placement drops them into the data
    - and a contour label sitting on the median marker is worse than an
    unlabelled contour.
    """
    levels = [2.5, 3, 3.5, 4, 4.5, 5, 6, 7, 8, 10, 13]
    gx = np.linspace(xlim[0], xlim[1], 420)
    gy = np.linspace(max(ylim[0], 1e-3), ylim[1], 420)
    gx_m, gy_m = np.meshgrid(gx, gy)
    jpt = gx_m / gy_m
    ax.contourf(gx_m, gy_m, jpt, levels=levels, cmap="Blues", alpha=0.28,
                extend="both", zorder=0)
    cs = ax.contour(gx_m, gy_m, jpt, levels=levels, colors=_C_LINE,
                    linewidths=0.7, alpha=0.5, zorder=1)
    dx, dy = xlim[1] - xlim[0], ylim[1] - ylim[0]
    x_lab = xlim[0] + lab_fx * dx
    y_lo, y_hi = ylim[0] + lab_lo * dy, ylim[0] + lab_hi * dy
    keep, pos = [], []
    for lv in levels:
        y = x_lab / lv
        if y_lo < y < y_hi:
            keep.append(lv)
            pos.append((x_lab, y))
    try:
        if keep:
            ax.clabel(cs, levels=keep, inline=True, fontsize=7.5,
                      fmt="%g J/tok", manual=pos)
        else:
            ax.clabel(cs, inline=True, fontsize=7.5, fmt="%g J/tok")
    except Exception:
        ax.clabel(cs, inline=True, fontsize=7.5, fmt="%g J/tok")


def _better_arrow(ax, xlim, ylim, fx=0.42, fy=0.20, ux=-0.15, uy=0.19):
    """An arrow pointing the way efficiency improves, so the contour field
    reads without the caption. Placed by hand per figure, because the only
    honest place for it is whatever corner the data left empty."""
    dx, dy = xlim[1] - xlim[0], ylim[1] - ylim[0]
    x0, y0 = xlim[0] + fx * dx, ylim[0] + fy * dy
    ax.annotate("", xy=(x0 + ux * dx, y0 + uy * dy), xytext=(x0, y0),
                arrowprops=dict(arrowstyle="-|>", color=_C_LINE, lw=1.7,
                                alpha=0.85), zorder=5)
    ax.text(x0, y0 - 0.028 * dy, "better\n(fewer joules per token)",
            ha="center", va="top", fontsize=8.5, color=_C_LINE,
            style="italic", zorder=5)


def _opaque_legend(ax, **kw):
    """Legend whose markers are readable even though the plotted points are
    nearly transparent. Shaded-region handles keep a light alpha, so the
    swatch still looks like the band it stands for rather than a solid
    block of colour that appears nowhere on the figure."""
    leg = ax.legend(framealpha=0.95, facecolor="white", **kw)
    leg.set_zorder(9)
    for h in getattr(leg, "legend_handles", []):
        try:
            h.set_alpha(0.35 if isinstance(h, matplotlib.patches.Patch)
                        else 1.0)
        except Exception:
            pass
    return leg


# ------------------------------------------------------- cap-sweep lookup

_ARM_TPS = ("mean_tps", "tps", "decode_tps", "mean_decode_tps")
_ARM_W = ("mean_w", "w", "mean_watts", "mean_power_w")
_ARM_J = ("j_per_tok", "jpt", "joules_per_token", "j_per_token")
_ARM_CAP = ("cap", "cap_w", "power_limit_w", "limit_w")


def _num(d, keys):
    for k in keys:
        v = d.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            v = float(v)
            if np.isfinite(v):
                return v
    return None


def _arms_from(obj):
    """Normalise a JSON blob into a sorted list of cap arms, or []."""
    cand = None
    if isinstance(obj, dict):
        for key in ("arms", "caps", "rows", "results"):
            if isinstance(obj.get(key), list):
                cand = obj[key]
                break
    elif isinstance(obj, list):
        cand = obj
    if not cand:
        return []
    arms = []
    for it in cand:
        if not isinstance(it, dict):
            continue
        cap = _num(it, _ARM_CAP)
        if cap is None:
            continue
        tps, w = _num(it, _ARM_TPS), _num(it, _ARM_W)
        j = _num(it, _ARM_J)
        if j is None and tps and w:
            j = w / tps
        if tps is None or w is None or j is None or tps <= 0:
            continue
        probes = it.get("probes") if isinstance(it.get("probes"), list) else []
        p0 = probes[0] if probes and isinstance(probes[0], dict) else {}
        arms.append({"cap": cap, "tps": tps, "w": w, "j": j,
                     "peak": _num(it, ("peak_w", "max_w")),
                     "prompt_n": _num(p0, ("prompt_n",)),
                     "npredict": _num(p0, ("predicted_n", "npredict")),
                     "n_probes": len(probes)})
    arms.sort(key=lambda a: a["cap"])
    return arms if len(arms) >= 2 else []


def _find_sweep(root):
    """Search results/ for a JSON holding per-cap arms.

    Returns (path, meta, arms) or (None, {}, []). Bounded: skips anything
    above 2 MB, which is every transcript dump in this tree.
    """
    res = os.path.abspath(os.path.join(root, "results"))
    if not os.path.isdir(res):
        return None, {}, []
    hits = []
    for dirpath, _dirs, files in os.walk(res):
        for fn in files:
            if not fn.lower().endswith(".json"):
                continue
            path = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(path) > _MAX_JSON_BYTES:
                    continue
                with io.open(path, encoding="utf-8", errors="replace") as fh:
                    obj = json.load(fh)
            except Exception:
                continue
            try:
                arms = _arms_from(obj)
            except Exception:
                arms = []
            if arms:
                meta = obj if isinstance(obj, dict) else {}
                # Prefer the widest sweep; break ties toward a file that
                # names itself a cap sweep.
                score = (len(arms), 1 if "cap" in fn.lower() else 0)
                hits.append((score, path, meta, arms))
    if not hits:
        return None, {}, []
    hits.sort(key=lambda h: h[0], reverse=True)
    _score, path, meta, arms = hits[0]
    return path, meta, arms


# ---------------------------------------------------------------- fig (1)

def _fig_cloud(ctx, op, capfrac, outdir):
    w, tps = op["w"], op["tps"]
    med_w, med_tps = float(np.median(w)), float(np.median(tps))
    # The aggregate is total joules over total tokens. It is NOT the median
    # of the per-interval ratios, and the two differ here.
    joules = float((w * op["dt"]).sum())
    tok = float(op["dn"].sum())
    secs = float(op["dt"].sum())
    agg_j, agg_tps, agg_w = joules / tok, tok / secs, joules / secs
    cv_w = 100.0 * float(w.std()) / float(w.mean())
    cv_t = 100.0 * float(tps.std()) / float(tps.mean())
    med_depth = float(np.median(op["depth"]))

    xlo = max(0.0, float(np.percentile(w, 0.5)) - 12)
    xhi = float(np.percentile(w, 99.5)) + 10
    ylo, yhi = 0.0, float(np.percentile(tps, 99.8)) * 1.10

    fig, ax = plt.subplots(figsize=(10, 6))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    _iso_efficiency(ax, (xlo, xhi), (ylo, yhi))
    ax.grid(alpha=_GRID_A, zorder=1.5)

    ax.scatter(w, tps, s=9, c=_C_CLOUD, alpha=0.20, linewidths=0, zorder=3,
               label="one ~1 s decode interval (n=%d)" % len(w))
    # An interquartile cross, so the reader sees the shape and not only a dot.
    ax.plot([np.percentile(w, 25), np.percentile(w, 75)], [med_tps, med_tps],
            color=_C_MED, lw=2.4, solid_capstyle="butt", zorder=5)
    ax.plot([med_w, med_w], [np.percentile(tps, 25), np.percentile(tps, 75)],
            color=_C_MED, lw=2.4, solid_capstyle="butt", zorder=5)
    ax.plot([med_w], [med_tps], marker="D", ms=10, color=_C_MED, ls="none",
            markeredgecolor="white", markeredgewidth=1.4, zorder=6,
            label="median %.0f W, %.1f tok/s (bars = interquartile range)"
                  % (med_w, med_tps))
    ax.plot([agg_w], [agg_tps], marker="*", ms=17, color="#000000", ls="none",
            markeredgecolor="white", markeredgewidth=1.0, zorder=6,
            label="run aggregate, DECODE intervals only:\n"
                  "%.0f W, %.1f tok/s = %.2f J per decoded token"
                  % (agg_w, agg_tps, agg_j))
    _better_arrow(ax, (xlo, xhi), (ylo, yhi))

    ax.set_xlim(xlo, xhi)
    ax.set_ylim(ylo, yhi)
    # The caveat rides on the axis label, not in the stats box: without it
    # a reader takes the star for the run's energy per completion token,
    # and it is not - prompt processing and the idle gaps between requests
    # are outside every interval plotted here, so this number is lower. In
    # the box it either pushed the box down over the topmost iso-efficiency
    # label or widened it over the top of the point cloud.
    ax.set_xlabel("GPU board power (W, NVML in-band board rail)\n"
                  "one point is one DECODE interval; prompt processing "
                  "and the idle between requests\nare off this axis, so "
                  "this is not the run's energy per completion token",
                  fontsize=9.5, linespacing=1.45)
    ax.set_ylabel("decode throughput (tokens per second)")
    ax.set_title("The board is pinned at its power limit and only throughput "
                 "moves,\nso energy per token is set by the decoder, not by "
                 "the power knob",
                 fontsize=12.5, fontweight="bold")

    iqr_w = float(np.percentile(w, 75) - np.percentile(w, 25))
    iqr_t = float(np.percentile(tps, 75) - np.percentile(tps, 25))
    lines = [
        "board power: median %.0f W, middle half spans %.0f W"
        % (med_w, iqr_w),
        "   (coefficient of variation, the standard deviation as a",
        "   percentage of the mean: %.1f%%)" % cv_w,
        "throughput: median %.0f tok/s, middle half spans %.0f tok/s"
        % (med_tps, iqr_t),
        "   (coefficient of variation %.1f%% - %.0f times as scattered)"
        % (cv_t, cv_t / max(cv_w, 1e-9))]
    if capfrac:
        lines.append("software power cap set on %.1f%% of busy samples,"
                     % capfrac[0])
        lines.append("   software thermal cap on %.1f%% (n=%d busy samples;"
                     % (capfrac[1], capfrac[2]))
        lines.append("   a sample can carry both bits)")
    else:
        lines.append("throttle-reason trace: not available for this tag")
    ax.text(0.022, 0.975, "\n".join(lines), transform=ax.transAxes, va="top",
            ha="left", fontsize=8.4, bbox=_BOX, zorder=7)

    _opaque_legend(ax, loc="lower right", fontsize=8.5)
    fig.tight_layout()
    png = os.path.join(outdir, "pareto-operating-cloud.png")
    fig.savefig(png, dpi=_DPI, facecolor="white")
    plt.close(fig)

    caption = (
        "Part: RTX 3090, 350 W stock board limit, fan pinned at 100%%. Model: "
        "Qwen3.8-27B UD-IQ4_XS, 14.25 GB resident, MTP speculative decoding "
        "on. Workload: the live agentic coding benchmark, tag %s, run %s - "
        "real multi-turn edit-and-test traffic on one slot, median context "
        "depth %s tokens. Each point is one poll-to-poll decode interval of "
        "about 1 s whose BOTH endpoints are decode samples of the same task "
        "(n=%d; the first interval of every decode run is discarded because "
        "it starts inside prompt processing, and gaps over %.0f s are "
        "discarded as stalls). Board power is the NVML sample nearest in "
        "time, within %.1f s. The shaded field and its labelled rays are "
        "lines of constant energy per decoded token. FINDING: board power "
        "holds a coefficient of variation of %.1f%% while throughput holds "
        "%.1f%%, so the measured cloud is a near-vertical stripe standing on "
        "the power limit. At this operating point there is no power-side "
        "lever to pull - energy per token is decided almost entirely by "
        "decode speed, which is to say by speculative-decoding acceptance. "
        "Run aggregate: %.2f J per decoded token, %s tokens over %.0f s of "
        "decode, %.0f W mean. %s"
        % (ctx.get("tag"), ctx.get("run"), "{:,}".format(int(med_depth)),
           len(w), _MAX_GAP_S, _JOIN_TOL_S, cv_w, cv_t, agg_j,
           "{:,}".format(int(tok)), secs, agg_w, _NOT_MEASURED))

    stats = {"agg_j": agg_j, "agg_tps": agg_tps, "agg_w": agg_w,
             "med_w": med_w, "med_tps": med_tps, "cv_w": cv_w, "cv_t": cv_t,
             "n": len(w), "tok": tok, "secs": secs,
             "p5_w": float(np.percentile(w, 5)),
             "p95_w": float(np.percentile(w, 95))}
    return png, caption, stats


# ---------------------------------------------------------------- fig (2)

def _fig_sweep(ctx, arms, meta, sweep_path, op, stats, capfrac, outdir):
    caps = np.array([a["cap"] for a in arms], dtype=float)
    aw = np.array([a["w"] for a in arms], dtype=float)
    at = np.array([a["tps"] for a in arms], dtype=float)
    aj = np.array([a["j"] for a in arms], dtype=float)
    base = int(np.argmax(caps))               # the stock, highest-cap arm

    fig = plt.figure(figsize=(13.0, 8.0))
    fig.patch.set_facecolor("white")
    gs = fig.add_gridspec(1, 2, width_ratios=[1.30, 1.0])
    ax = fig.add_subplot(gs[0, 0])
    bx = fig.add_subplot(gs[0, 1])
    ax.set_facecolor("white")
    bx.set_facecolor("white")
    # Explicit, not tight_layout: a figure-level caveat box has to be given
    # its room up front, and tight_layout cannot see it.
    fig.subplots_adjust(left=0.062, right=0.988, top=0.845, bottom=0.335,
                        wspace=0.20)

    # ---- left: both workloads on one plane
    xs = [float(aw.min()), float(aw.max()), float(caps.max())]
    ys = [float(at.min()), float(at.max())]
    if op is not None:
        xs += [float(np.percentile(op["w"], 0.5)),
               float(np.percentile(op["w"], 99.5))]
        ys += [float(np.percentile(op["tps"], 99.8))]
    xlo, xhi = max(0.0, min(xs) - 24), max(xs) + 14
    ylo, yhi = 0.0, max(ys) * 1.14
    _iso_efficiency(ax, (xlo, xhi), (ylo, yhi), lab_fx=0.055, lab_lo=0.06,
                    lab_hi=0.80)
    ax.grid(alpha=_GRID_A, zorder=1.5)

    if op is not None:
        ax.axvspan(stats["p5_w"], stats["p95_w"], color=_C_CLOUD, alpha=0.10,
                   zorder=1.6,
                   label="shaded band = agentic 5th to 95th percentile power "
                         "(%.0f-%.0f W)" % (stats["p5_w"], stats["p95_w"]))
        ax.scatter(op["w"], op["tps"], s=7, c=_C_CLOUD, alpha=0.13,
                   linewidths=0, zorder=2,
                   label="agentic workload, per-interval (this run)")
        ax.plot([stats["agg_w"]], [stats["agg_tps"]], marker="*", ms=17,
                color="#000000", ls="none", markeredgecolor="white",
                markeredgewidth=1.0, zorder=6,
                label="agentic aggregate, DECODE intervals only:\n"
                      "%.0f W, %.1f tok/s = %.2f J per decoded token"
                      % (stats["agg_w"], stats["agg_tps"],
                         stats["agg_j"]))

    for a in arms:
        ax.plot([a["cap"], a["cap"]], [ylo, yhi], color=_C_SWEEP, lw=0.9,
                ls=":", alpha=0.6, zorder=1.7)
    ax.plot(aw, at, color=_C_SWEEP, lw=2.0, marker="o", ms=8, zorder=5,
            markeredgecolor="white", markeredgewidth=1.2,
            label="published cap sweep, synthetic decode (%s)"
                  % meta.get("date", "date not recorded"))
    ax.plot([], [], color=_C_SWEEP, lw=0.9, ls=":",
            label="dotted line = the limit each arm was set to")
    for a in arms:
        ax.annotate("%.0f W limit\ndrew %.0f W" % (a["cap"], a["w"]),
                    xy=(a["w"], a["tps"]), xytext=(0, -34),
                    textcoords="offset points", fontsize=8.5, ha="center",
                    color=_C_SWEEP_TXT, zorder=6)
    # The headroom the stock arm never used, drawn where the cloud is not.
    hy = yhi * 0.085
    ax.annotate("", xy=(arms[base]["cap"], hy), xytext=(arms[base]["w"], hy),
                arrowprops=dict(arrowstyle="<|-|>", color=_C_SWEEP_TXT,
                                lw=1.3), zorder=6)
    ax.text((arms[base]["w"] + arms[base]["cap"]) / 2.0, hy * 1.22,
            "%.0f W of headroom the\n%.0f W arm never used"
            % (arms[base]["cap"] - arms[base]["w"], arms[base]["cap"]),
            ha="center", va="bottom", fontsize=8.0, color=_C_SWEEP_TXT,
            zorder=6)

    _better_arrow(ax, (xlo, xhi), (ylo, yhi), fx=0.40, fy=0.18,
                  ux=-0.16, uy=0.15)
    ax.set_xlim(xlo, xhi)
    ax.set_ylim(ylo, yhi)
    ax.set_xlabel("GPU board power (W, NVML in-band board rail)")
    ax.set_ylabel("decode throughput (tokens per second)")
    ax.set_title("The sweep's arms never enter the power band this run "
                 "occupies", fontsize=11.5, fontweight="bold")
    _opaque_legend(ax, loc="upper left", fontsize=7.6)

    # ---- right: what each cap step cost and bought, against the stock arm
    # Ordered as the decision is taken: step down from the stock limit.
    others = sorted((i for i in range(len(arms)) if i != base),
                    key=lambda i: -caps[i])
    d_tps = [100.0 * (at[i] - at[base]) / at[base] for i in others]
    d_pwr = [100.0 * (aw[i] - aw[base]) / aw[base] for i in others]
    d_jpt = [100.0 * (aj[i] - aj[base]) / aj[base] for i in others]
    idx = np.arange(len(others), dtype=float)
    bw = 0.26
    series = (("throughput lost (down is worse)", d_tps, _C_TPS, ""),
              ("board power saved (down is better)", d_pwr, _C_PWR, "//"),
              ("energy per token (down is better)", d_jpt, _C_JPT, "xx"))
    for k, (lab, vals, col, hatch) in enumerate(series):
        pos = idx + (k - 1) * bw
        bx.bar(pos, vals, width=bw, color=col, edgecolor="white", lw=0.8,
               hatch=hatch, label=lab, zorder=3)
        for x, v in zip(pos, vals):
            bx.annotate("%+.1f%%" % v, (x, v), textcoords="offset points",
                        xytext=(0, -13 if v < 0 else 5), ha="center",
                        fontsize=8.5, zorder=4)
    bx.axhline(0, color="#000000", lw=1.0, zorder=3.5)
    bx.set_xticks(idx)
    bx.set_xticklabels(["%.0f W limit" % caps[i] for i in others])
    bx.set_ylabel("change from the %.0f W stock limit (%%)" % caps[base])
    span = max(abs(min(d_tps + d_pwr + d_jpt)), 1.0)
    bx.set_ylim(-span * 1.42, span * 0.16)
    bx.set_xlim(-0.55, len(others) - 0.45)
    bx.grid(alpha=_GRID_A, axis="y", zorder=1)
    bx.set_title("Capping bought more efficiency than it cost throughput\n"
                 "- on the workload it was measured on",
                 fontsize=11.5, fontweight="bold")
    bx.text(0.5, 0.035,
            "synthetic decode probe, %d runs per arm, %d-token generation.\n"
            "Every bar is a change against the %.0f W arm, not an absolute."
            % (int(arms[base].get("n_probes") or 0),
               int(arms[base].get("npredict")
                   or _num(meta, ("npredict",)) or 0), caps[base]),
            transform=bx.transAxes, ha="center", va="bottom", fontsize=8.0,
            color=_C_LINE, zorder=5, bbox=_BOX)
    bx.legend(loc="lower left", fontsize=8.0, framealpha=0.95,
              facecolor="white", bbox_to_anchor=(0.0, 0.16))

    # ---- the caveat, printed on the figure
    frac = 100.0 * arms[base]["w"] / arms[base]["cap"]
    cap_pct = ("%.1f%%" % capfrac[0]) if capfrac else "the great majority"
    npred = arms[base].get("npredict") or _num(meta, ("npredict",)) or 700
    pn = arms[base].get("prompt_n")
    prompt_txt = ("a %d-token prompt" % int(pn)) if pn else "a very short prompt"
    peak_txt = (("peak %.0f W" % arms[base]["peak"]) if arms[base]["peak"]
                else "peak not recorded")
    caveat = (
        "READ THIS BEFORE USING THE CURVE. The cap sweep on the left was "
        "measured on SYNTHETIC decode - a %d-token generation from %s - whose "
        "mean draw at the stock %.0f W limit is only %.0f W, that is %.0f%% "
        "of the limit (%s). That workload never reaches its own cap, so "
        "lowering the cap first takes away headroom the workload was not "
        "using. The agentic workload plotted here sits ON the limit: the "
        "software power-cap bit is set on %s of busy samples and steady "
        "decode averages %.0f W. The two clouds barely overlap in power. The "
        "published curve therefore describes a regime this workload is not "
        "in, and its numbers must NOT be assumed to transfer: the %.0f W step "
        "that costs this synthetic probe only %.1f%% of its throughput is "
        "removing headroom the probe was not using, whereas the same step "
        "would cut into power the agentic workload is actively spending, and "
        "could cost it a great deal more. Choosing a power limit for agentic "
        "serving needs this sweep re-run ON agentic traffic."
        % (int(npred), prompt_txt, arms[base]["cap"], arms[base]["w"], frac,
           peak_txt, cap_pct,
           stats["agg_w"] if stats else float("nan"),
           caps[others[0]], -d_tps[0]))

    fig.text(0.5, 0.268, textwrap.fill(caveat, 150), ha="center", va="top",
             fontsize=8.6, linespacing=1.45,
             bbox=dict(boxstyle="round,pad=0.7", facecolor="#FFF4E0",
                       edgecolor="#E69F00", lw=1.3))
    fig.suptitle("The stock %.0f W limit sits past the efficiency knee - but "
                 "the sweep that says so\nnever ran in the regime this "
                 "workload occupies" % caps[base],
                 fontsize=13, fontweight="bold", y=0.988)

    png = os.path.join(outdir, "pareto-power-cap-sweep.png")
    fig.savefig(png, dpi=_DPI, facecolor="white")
    plt.close(fig)

    steps = "; ".join(
        "the %.0f W limit costs %.1f%% throughput for %.1f%% less board power "
        "and %.1f%% less energy per token"
        % (caps[i], -d_tps[k], -d_pwr[k], -d_jpt[k])
        for k, i in enumerate(others))
    caption = (
        "Part: RTX 3090, %.0f W stock board limit. LEFT: the published "
        "power-cap sweep as an arm-level curve, drawn on the same "
        "throughput-against-board-power plane as the operating cloud, with "
        "each arm placed at the power it ACTUALLY drew rather than at the "
        "limit it was set to (dotted verticals mark the limits). Source %s, "
        "measured %s on %s, %d probes per arm, %d-token context. RIGHT: what "
        "each cap step changed against the %.0f W stock arm - %s. Capping "
        "improved energy per token at both steps, which puts the stock "
        "%.0f W limit past the efficiency knee FOR THAT WORKLOAD. CAVEAT, "
        "carried on the figure: the sweep ran on synthetic decode drawing "
        "%.0f W against a %.0f W limit, so it never reaches its cap, while "
        "the agentic workload in this run sits on the cap (%s of busy samples "
        "carry the software power-cap bit) and averages %.0f W in steady "
        "decode. The two power distributions barely overlap, so the published "
        "curve describes a regime the agentic workload is not in and must not "
        "be assumed to transfer. %s"
        % (caps[base],
           os.path.relpath(sweep_path, A.ROOT).replace("\\", "/"),
           meta.get("date", "date not recorded"),
           meta.get("card", "the reference part"),
           int(arms[base].get("n_probes") or 0),
           int(_num(meta, ("ctx",)) or 0), caps[base], steps, caps[base],
           arms[base]["w"], arms[base]["cap"], cap_pct,
           stats["agg_w"] if stats else float("nan"), _NOT_MEASURED))
    return png, caption


# -------------------------------------------------------------------- api

def make(ctx, outdir):
    """ctx has keys: tag, run, dmon, slots, host, throttle, requests,
    exercises (any may be None if that source is absent - degrade
    gracefully, never crash). Returns a list of (png_path, caption).

    A figure that could NOT be built is returned as a (None, reason) entry
    rather than dropped, and never as an empty chart. A caller that wants
    only images should filter on `png is not None`; the reasons exist so a
    reader of the report can tell a figure that is missing from a figure
    that was measured as nothing.
    """
    notes, figs = [], []
    ctx = ctx or {}
    try:
        os.makedirs(outdir, exist_ok=True)
    except Exception as exc:
        return [(None, "pareto: could not create %s (%s)" % (outdir, exc))]

    try:
        op = _operating_points(ctx.get("slots"), ctx.get("dmon"))
    except Exception as exc:
        op, _ = None, notes.append(
            "pareto: the decode operating points could not be derived (%s: "
            "%s)." % (type(exc).__name__, exc))
    try:
        capfrac = _cap_bit_fraction(ctx.get("dmon"), ctx.get("throttle"))
    except Exception:
        capfrac = None

    stats = None
    if op is None:
        notes.append(
            "pareto: figure 1 not built. It needs a /slots trace and a dmon "
            "trace that overlap in time and contain at least ten decode "
            "intervals with both endpoints in the same task; this run did "
            "not provide them. Absent, not zero.")
    else:
        try:
            png, cap, stats = _fig_cloud(ctx, op, capfrac, outdir)
            figs.append((png, cap))
        except Exception as exc:
            notes.append("pareto: the operating cloud failed to draw (%s: %s)."
                         % (type(exc).__name__, exc))

    try:
        sweep_path, meta, arms = _find_sweep(A.ROOT)
    except Exception:
        sweep_path, meta, arms = None, {}, []

    if not arms:
        notes.append(
            "pareto: figure 2 not built. No power-cap sweep was found under "
            "results/ - the search reads every JSON below 2 MB and keeps any "
            "holding at least two arms with a cap plus throughput and board "
            "power. The arm-level cap curve is therefore absent from this "
            "report, not measured as zero.")
    elif stats is None:
        notes.append(
            "pareto: figure 2 not built. The cap sweep at %s was found, but "
            "without the live operating cloud there is nothing to compare it "
            "against, and this campaign does not publish that curve on its "
            "own: it was measured on synthetic decode that never reaches its "
            "own cap, so it must not travel without the workload it is being "
            "contrasted with." % sweep_path)
    else:
        try:
            png, cap = _fig_sweep(ctx, arms, meta, sweep_path, op, stats,
                                  capfrac, outdir)
            figs.append((png, cap))
        except Exception as exc:
            notes.append("pareto: the cap-sweep figure failed to draw (%s: %s)."
                         % (type(exc).__name__, exc))

    if not figs and not notes:
        notes.append("pareto: no figure could be built.")
    return figs + [(None, n) for n in notes]
