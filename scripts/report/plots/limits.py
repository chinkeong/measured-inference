#!/usr/bin/env python3
"""What limited the part, over time and in total.

Two figures, both built from the NVML clock-event mask (the "throttle"
collector) and cross-checked against the dmon violation counters:

  1. limits-timeline.png -- a step timeline of which single limit was active
     at each sampled moment, with board power overlaid on a secondary axis so
     the reader can watch the cap engage.
  2. limits-share.png    -- time in each limit as a share of BUSY samples.
     Idle is excluded: idle is a state, not a limit, and counting it would
     dilute every bar.

The severity collapse is A.throttle_series()'s, so exactly one label is active
per sample and the timeline stack sums to 100% at every instant. Because that
collapse hides co-occurring reasons, figure 2 also plots the raw "this bit was
set at all" share beside each exclusive bar.

BOARD POWER ONLY. Everything here is the NVML board-power domain reported by
nvidia-smi. No PSU, CPU, VRM-loss or wall measurement exists in this campaign,
and nothing on these figures may be read as system power.
"""
import os
import subprocess

import numpy as np

import matplotlib
matplotlib.use("Agg")            # REQUIRED - never an interactive backend
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

TITLE = "What limited the part"

# Okabe-Ito, colourblind-safe, and separated in lightness as well as hue so the
# figures survive greyscale printing. No red/green pairing carries meaning.
LIMIT_COLOUR = {
    "Idle":            "#BDBDBD",
    "Unconstrained":   "#56B4E9",
    "SW power cap":    "#E69F00",
    "SW thermal":      "#CC79A7",
    "HW slowdown":     "#0072B2",
    "HW thermal":      "#D55E00",
    "HW power brake":  "#000000",
    "no data":         "#FFFFFF",
}

# Severity order, most severe first. Mirrors archdata.throttle_series().
SEVERITY = ["HW thermal", "HW power brake", "HW slowdown", "SW thermal",
            "SW power cap", "Unconstrained"]

# NVML bit per reason, used ONLY for the "bit set at all" overlay in figure 2.
# The exclusive bars always come from A.throttle_series().
REASON_BIT = {"SW power cap": 0x0004, "HW slowdown": 0x0008,
              "SW thermal": 0x0020, "HW thermal": 0x0040,
              "HW power brake": 0x0080}

PART = "NVIDIA GeForce RTX 3090 (single board, GPU 0)"
WORKLOAD = ("aider polyglot agentic coding benchmark against a local "
            "llama-server, IQ4_XS weights 14.25 GB resident, MTP speculative "
            "decoding on")
NOT_MEASURED = ("board power is the NVML GPU board domain only, so PSU, CPU "
                "and wall power were not measured, and per-process power "
                "attribution is unavailable under Windows WDDM")
DPI = 140
GRID_A = 0.3
BUSY_SM = 5.0                    # matches archdata.BUSY_SM_PCT


# ---------------------------------------------------------------- helpers

def _get(ctx, key):
    """ctx may be a dict or an object, and any source may be absent."""
    if ctx is None:
        return None
    if isinstance(ctx, dict):
        return ctx.get(key)
    return getattr(ctx, key, None)


def _spot_gpu_read():
    """Read-only nvidia-smi spot query for the few facts the sampled telemetry
    does not carry: fan speed is not a dmon column, and the enforced power
    limit is a setting rather than a sample.

    Returns a dict of strings. A missing key means the query failed, and the
    caller must then say "not read" instead of inventing a number.
    """
    out = {}
    try:
        q = "fan.speed,enforced.power.limit,power.limit,temperature.gpu,name"
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=" + q,
             "--format=csv,noheader,nounits", "-i", "0"],
            capture_output=True, text=True, timeout=10)
        if r.returncode != 0 or not r.stdout.strip():
            return out
        f = [x.strip() for x in r.stdout.strip().splitlines()[0].split(",")]
        for k, v in zip(["fan_pct", "enf_limit_w", "limit_w", "gtemp_c",
                         "name"], f):
            if v and v not in ("[N/A]", "N/A", "-", ""):
                out[k] = v
    except Exception:
        pass
    return out


def _fnum(d, key):
    try:
        return float(d[key])
    except (KeyError, TypeError, ValueError):
        return float("nan")


def _busy_dmon(dmon):
    """Per-sample busy mask for dmon, by SM utilisation."""
    if dmon is None:
        return np.zeros(0, dtype=bool)
    sm = dmon.get("sm")
    if sm is None or not len(sm):
        return np.zeros(0, dtype=bool)
    return np.nan_to_num(np.asarray(sm, dtype=float), nan=0.0) > BUSY_SM


def _thermal_note(dmon, spot):
    """One plain sentence about heat, so that nobody reads these figures and
    concludes there is thermal headroom sitting unused."""
    bits = []
    if spot.get("fan_pct"):
        bits.append("fan pinned at %s%% (spot read, not sampled over time)"
                    % spot["fan_pct"])
    else:
        bits.append("fan speed: not sampled by this collector and the spot "
                    "read was unavailable")
    got = False
    if dmon is not None and len(dmon.get("gtemp", [])):
        b = _busy_dmon(dmon)
        g = np.asarray(dmon["gtemp"], dtype=float)
        gb = g[b] if b.any() else g
        gb = gb[~np.isnan(gb)]
        if len(gb):
            bits.append("GPU core %.0f C median and %.0f C maximum while busy"
                        % (np.median(gb), np.max(gb)))
            got = True
    if not got:
        bits.append("GPU core temperature: dmon telemetry absent")
    bits.append("memory junction temperature: not exposed by NVML on this "
                "part")
    return " | ".join(bits)


def _steps(t, y):
    """Extend a sampled series by one median interval so the final sample is
    actually drawn by a step='post' fill instead of vanishing."""
    if len(t) < 2:
        return t, y
    dt = float(np.median(np.diff(t)))
    return np.append(t, t[-1] + dt), np.append(y, y[-1])


def _wrap(s, n):
    lines, cur = [], ""
    for w in s.split():
        if cur and len(cur) + 1 + len(w) > n:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return lines or [""]


def _chars(fig, pt, frac=0.96):
    """Roughly how many characters of a given point size fit across the
    figure. Used so a title or a conditions line is wrapped instead of being
    silently clipped at the figure edge."""
    px = fig.get_figwidth() * DPI * frac
    return max(int(px / (pt * DPI / 72.0 * 0.58)), 24)


def _header(fig, title, cond, title_pt=12.5, sub_pt=8.3):
    """Title and conditions in FIGURE coordinates, so they can use the whole
    width and never collide with the axes. Returns the top of the region
    tight_layout should leave for the axes."""
    hpt = fig.get_figheight() * 72.0
    y = 1.0 - 9.0 / hpt
    for ln in _wrap(title, _chars(fig, title_pt)):
        fig.text(0.012, y, ln, fontsize=title_pt, fontweight="bold",
                 color="#111111", ha="left", va="top")
        y -= title_pt * 1.32 / hpt
    y -= 5.0 / hpt
    for ln in _wrap(cond, _chars(fig, sub_pt)):
        fig.text(0.012, y, ln, fontsize=sub_pt, color="#444444", ha="left",
                 va="top")
        y -= sub_pt * 1.5 / hpt
    return max(y - 7.0 / hpt, 0.5)


def _footer(fig, notes, pt=8.0):
    """Notes below the axes. Returns the bottom of the region tight_layout
    should leave for the axes."""
    hpt = fig.get_figheight() * 72.0
    lines = []
    for n in notes:
        lines.extend(_wrap(n, _chars(fig, pt)))
    y = 8.0 / hpt
    for ln in reversed(lines):
        fig.text(0.012, y, ln, fontsize=pt, color="#333333", ha="left",
                 va="bottom")
        y += pt * 1.5 / hpt
    return min(y + 4.0 / hpt, 0.5)


def _dur(sec):
    if not np.isfinite(sec):
        return "duration unknown"
    return "%.0f s" % sec if sec < 90.0 else "%.0f min" % (sec / 60.0)


def _labels(thr):
    """(t, labels) or (None, None). archdata is imported lazily so this module
    can be read without the loader already on sys.path."""
    if thr is None:
        return None, None
    t = np.asarray(thr.get("t", []), dtype=float)
    if len(t) < 2:
        return None, None
    import archdata as A
    tt, lab = A.throttle_series(thr)
    return np.asarray(tt, dtype=float), np.asarray(lab, dtype=object)


# ---------------------------------------------------------------- figure 1

def _fig_timeline(thr, dmon, spot, outdir):
    t, lab = _labels(thr)
    if t is None:
        return None

    t0 = float(t[0])
    if dmon is not None and len(dmon.get("t", [])):
        t0 = min(t0, float(dmon["t"][0]))
    x = (t - t0) / 60.0
    per = float(np.median(np.diff(t)))

    fig, ax = plt.subplots(figsize=(12.6, 6.9), dpi=DPI)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    # The stack. Exactly one label holds each sample, so every band runs 0->100
    # and the stack sums to 100% at every instant by construction.
    present = [L for L in (["Idle"] + SEVERITY + ["no data"])
               if (lab == L).any()]
    for L in present:
        xs, ys = _steps(x, np.where(lab == L, 100.0, 0.0))
        ax.fill_between(xs, 0.0, ys, step="post",
                        color=LIMIT_COLOUR.get(L, "#888888"), alpha=0.62,
                        linewidth=0, zorder=1,
                        hatch="///" if L == "no data" else None)

    # Rare limits last one or two samples, and at this aspect ratio one sample
    # is about one pixel wide. The band above keeps the true widths; this rug
    # keeps single samples visible, drawn at a fixed width.
    rug = [L for L in present if L not in ("SW power cap", "Idle")]
    for L in rug:
        sel = (lab == L)
        if sel.any():
            ax.vlines(x[sel], 102.0, 108.0,
                      color=LIMIT_COLOUR.get(L, "#888888"), linewidth=2.0,
                      zorder=4)
    if rug:
        ax.text(0.003, 112.5,
                "marks above the band: one per sample of a limit other than "
                "the power cap, drawn at a fixed width so a single %.1f s "
                "sample stays visible" % per,
                transform=ax.get_yaxis_transform(), zorder=5, fontsize=7.8,
                color="#555555", va="center", ha="left")

    ax.set_ylim(0, 118)
    # The band is CATEGORICAL: exactly one label holds each sample, so each
    # band is either full height or absent and never takes an intermediate
    # value. Numbered ticks would invite a reader to read a share off an
    # axis that has none, so the axis carries no ticks and says what it is.
    ax.set_yticks([])
    ax.set_ylabel("which limit was active\n"
                  "(one per sample, chosen by severity;\n"
                  "the band is full height by construction)")
    ax.set_xlabel("time since telemetry start (minutes)")
    span = float(x[-1]) - float(x[0])
    ax.set_xlim(float(x[0]), float(x[-1]) + max(span * 0.004, 0.05))
    ax.grid(True, axis="x", alpha=GRID_A)
    ax.set_axisbelow(True)

    handles = [Patch(facecolor=LIMIT_COLOUR.get(L, "#888888"), alpha=0.62,
                     edgecolor="#999999", label=L) for L in present]

    # ---- board power on the secondary axis
    cap_w = _fnum(spot, "enf_limit_w")
    ax2 = ax.twinx()
    pmean = float("nan")
    if dmon is not None and len(dmon.get("t", [])):
        dx = (np.asarray(dmon["t"], dtype=float) - t0) / 60.0
        pw = np.asarray(dmon["pwr"], dtype=float)
        ok = ~np.isnan(pw)
        if ok.any():
            ax2.plot(dx[ok], pw[ok], color="#111111", linewidth=0.75,
                     alpha=0.9, zorder=3)
            handles.append(Line2D([0], [0], color="#111111", lw=1.3,
                                  label="board power (W, right axis)"))
            b = _busy_dmon(dmon) & ok
            if b.any():
                pmean = float(np.mean(pw[b]))
        else:
            ax2.text(0.5, 0.55, "board power: every dmon sample is NULL",
                     transform=ax2.transAxes, ha="center", va="center",
                     fontsize=11, color="#7B2D00",
                     bbox=dict(boxstyle="round", fc="white", ec="#7B2D00"))
        if np.isfinite(cap_w):
            ln = ax2.axhline(cap_w, color="#111111", linewidth=1.5,
                             linestyle=(0, (6, 3)), zorder=5)
            ln.set_path_effects([pe.withStroke(linewidth=3.6,
                                               foreground="white")])
            handles.append(Line2D([0], [0], color="#111111", lw=1.5,
                                  ls=(0, (6, 3)),
                                  label="enforced board-power limit, %.0f W"
                                        % cap_w))
    else:
        ax2.text(0.5, 0.55, "board power NOT drawn: dmon telemetry absent",
                 transform=ax2.transAxes, ha="center", va="center",
                 fontsize=11, color="#7B2D00",
                 bbox=dict(boxstyle="round", fc="white", ec="#7B2D00"))

    # 100% on the left band maps to 400 W on the right, so the cap line and the
    # trace both sit inside the band and the idle troughs stay visible.
    ax2.set_ylim(0, 400.0 * 118.0 / 100.0)
    ax2.set_yticks([0, 100, 200, 300, 400])
    ax2.set_ylabel("board power (W)\nGPU board domain only, not system power")

    title = ("Board power sits at the %s for the whole run, and thermal "
             "limiting appears only as isolated samples"
             % ("%.0f W cap" % cap_w if np.isfinite(cap_w)
                else "board-power cap"))
    cond = "%s | workload: %s" % (PART, WORKLOAD)
    if np.isfinite(pmean):
        cond += " | board power %.0f W mean over busy samples" % pmean
    cond += " | %s | %s" % (_thermal_note(dmon, spot), NOT_MEASURED)
    top = _header(fig, title, cond)

    fig.tight_layout(rect=(0, 0.095, 1, top))
    fig.legend(handles=handles, loc="lower center",
               ncol=min(6, max(len(handles), 1)), frameon=False, fontsize=9,
               bbox_to_anchor=(0.5, 0.004))

    p = os.path.join(outdir, "limits-timeline.png")
    fig.savefig(p, dpi=DPI, facecolor="white")
    plt.close(fig)
    return p


# ---------------------------------------------------------------- figure 2

def _fig_share(thr, dmon, spot, outdir):
    t, lab = _labels(thr)
    if t is None:
        return None
    mask = np.asarray(thr["mask"], dtype=np.int64)

    busy = (lab != "Idle") & (lab != "no data")
    n_busy = int(busy.sum())
    if n_busy == 0:
        return None
    n_all, n_idle = len(lab), int((lab == "Idle").sum())
    n_nodata = int((lab == "no data").sum())

    dt = np.diff(t)
    per = float(np.median(dt)) if len(dt) else float("nan")
    spread = (float(dt.max() - dt.min()) / per * 100.0) \
        if len(dt) and np.isfinite(per) and per > 0 else float("nan")

    excl, anyset = {}, {}
    for L in SEVERITY:
        excl[L] = float((lab[busy] == L).sum())
        if L == "Unconstrained":
            anyset[L] = float((mask[busy] == 0).sum())
        else:
            anyset[L] = float(((mask[busy] & REASON_BIT[L]) != 0).sum())

    order = sorted(SEVERITY, key=lambda L: (excl[L] > 0, excl[L], anyset[L]),
                   reverse=True)
    y = np.arange(len(order))[::-1]

    fig, ax = plt.subplots(figsize=(11.8, 6.6), dpi=DPI)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    for yi, L in zip(y, order):
        pct = 100.0 * excl[L] / n_busy
        apct = 100.0 * anyset[L] / n_busy
        ax.barh(yi, pct, height=0.5, color=LIMIT_COLOUR.get(L, "#888888"),
                alpha=0.92, edgecolor="#555555", linewidth=0.6, zorder=2)
        if abs(apct - pct) > 1e-9:
            ax.plot([pct, apct], [yi, yi], color="#555555", lw=0.9, ls=":",
                    zorder=3)
            ax.plot([apct], [yi], marker="D", ms=7.0, mfc="white",
                    mec=LIMIT_COLOUR.get(L, "#888888"), mew=1.8, zorder=4)
        if excl[L] == 0 and anyset[L] == 0:
            ax.text(0.8, yi, "0 samples -- measured, and never observed in "
                             "this run", va="center", ha="left", fontsize=8.6,
                    color="#666666", style="italic", zorder=5)
            continue
        txt = "%.1f%%   %d of %d busy samples   %s" \
              % (pct, int(excl[L]), n_busy, _dur(excl[L] * per))
        if abs(apct - pct) > 1e-9:
            txt += "   [reason bit set at all: %.1f%%]" % apct
        if pct > 55:
            ax.text(1.8, yi, txt, va="center", ha="left", fontsize=9,
                    color="white", fontweight="bold", zorder=5)
        else:
            ax.text(max(pct, apct) + 1.8, yi, txt, va="center", ha="left",
                    fontsize=9, color="#222222", zorder=5)

    ax.set_yticks(y)
    ax.set_yticklabels(order, fontsize=10.5)
    ax.set_ylim(-0.65, len(order) - 0.35)
    ax.set_xlim(0, 100)
    ax.set_xlabel("share of BUSY samples (%) -- idle excluded")
    ax.grid(True, axis="x", alpha=GRID_A)
    ax.set_axisbelow(True)

    # The conclusion, said once, in the empty half of the chart.
    ax.text(0.42, 0.30,
            "What to decide from this:\n"
            "more compute would be clipped by the power cap, not realised.\n"
            "Cooling is not the throughput constraint, even with the fan\n"
            "held at 100%.",
            transform=ax.transAxes, ha="left", va="center", fontsize=9.5,
            color="#222222", linespacing=1.5,
            bbox=dict(boxstyle="round,pad=0.55", fc="#F4F4F4", ec="#BBBBBB"))

    pcap = 100.0 * excl["SW power cap"] / n_busy
    tsw = 100.0 * excl["SW thermal"] / n_busy
    unc = 100.0 * excl["Unconstrained"] / n_busy
    title = ("Power is the limit on %.0f%% of busy samples, temperature on "
             "%.0f%%, and the part is unconstrained on %.1f%%"
             % (pcap, tsw, unc))
    cond = ("%s | workload: %s | %d idle samples (%.1f%% of all %d) excluded: "
            "idle is a state, not a limit, and counting it would dilute every "
            "bar" % (PART, WORKLOAD, n_idle, 100.0 * n_idle / n_all, n_all))
    if n_nodata:
        cond += "; %d samples carried no mask and are excluded too" % n_nodata
    top = _header(fig, title, cond)

    # Conditions and the independent corroboration. dmon samples about five
    # times as often as the clock-event mask, from a different NVML field.
    notes = []
    if np.isfinite(per):
        notes.append("Clock-event mask sampled every %.2f s and the interval "
                     "varies by only %.1f%% of the median, so the share of "
                     "samples is also the share of busy time. Filled bars are "
                     "the severity-collapsed label, one per sample; open "
                     "diamonds are how often that reason bit was set at all, "
                     "because reasons co-occur."
                     % (per, spread))
    tviol_zero = False
    if dmon is not None and len(dmon.get("t", [])):
        b = _busy_dmon(dmon)
        sub = []
        pv = dmon.get("pviol")
        if pv is not None and b.any() and not np.all(np.isnan(pv[b])):
            sub.append("the power-violation counter reads %.0f%% of busy time "
                       "on average" % np.nanmean(pv[b]))
        tv = dmon.get("tviol")
        if tv is not None and b.any() and not np.all(np.isnan(tv[b])):
            m = float(np.nanmean(tv[b]))
            tviol_zero = (m == 0.0)
            sub.append("the thermal-violation counter reads %.2f" % m)
        if sub:
            notes.append("Independent check from dmon, sampled about five "
                         "times as often: " + " and ".join(sub) + ".")
        pw = np.asarray(dmon.get("pwr", []), dtype=float)
        if b.any() and len(pw) == len(b) and not np.all(np.isnan(pw[b])):
            q = pw[b][~np.isnan(pw[b])]
            cap_w = _fnum(spot, "enf_limit_w")
            s = ("Board power over busy samples: %.0f W mean, %.0f W maximum"
                 % (np.mean(q), np.max(q)))
            if np.isfinite(cap_w):
                s += ", against a %.0f W enforced limit" % cap_w
            notes.append(s + ". " + NOT_MEASURED[0].upper() + NOT_MEASURED[1:]
                         + ".")
    else:
        notes.append("dmon telemetry absent: no power or temperature "
                     "corroboration is available for this tag. " +
                     NOT_MEASURED[0].upper() + NOT_MEASURED[1:] + ".")
    if tviol_zero and excl["SW thermal"] > 0:
        notes.append("The two thermal readings disagree because they measure "
                     "different things: the clock-event mask reports the soft "
                     "temperature-target clock step, while the dmon "
                     "thermal-violation counter reports a hardware thermal "
                     "violation, which never occurred.")
    tn = _thermal_note(dmon, spot)
    notes.append(tn[0].upper() + tn[1:] + ".")
    bottom = _footer(fig, notes)

    fig.tight_layout(rect=(0, bottom, 1, top))
    p = os.path.join(outdir, "limits-share.png")
    fig.savefig(p, dpi=DPI, facecolor="white")
    plt.close(fig)
    return p


# ---------------------------------------------------------------- contract

def make(ctx, outdir):
    """ctx has keys: tag, run, dmon, slots, host, throttle, requests,
    exercises (any may be None if that source is absent - degrade gracefully,
    never crash). Returns a list of (png_path, caption_string)."""
    tag = _get(ctx, "tag") or "unknown-tag"
    run = _get(ctx, "run") or "unknown-run"
    thr = _get(ctx, "throttle")
    dmon = _get(ctx, "dmon")

    if thr is None or len(np.asarray(thr.get("t", []), dtype=float)) < 2:
        # Nothing to draw. An empty axis would be worse than no figure: a
        # blank chart reads as "nothing limited the part".
        return []
    try:
        os.makedirs(outdir, exist_ok=True)
    except Exception:
        return []

    spot = _spot_gpu_read()
    t, lab = _labels(thr)
    busy = (lab != "Idle") & (lab != "no data")
    n_busy = max(int(busy.sum()), 1)
    pcap = 100.0 * (lab[busy] == "SW power cap").sum() / n_busy
    tsw = 100.0 * (lab[busy] == "SW thermal").sum() / n_busy
    unc = 100.0 * (lab[busy] == "Unconstrained").sum() / n_busy
    span_min = (float(t[-1]) - float(t[0])) / 60.0

    cond = ("%s. Workload: %s; run %s, tag %s. Window: %.0f minutes of "
            "telemetry, %d clock-event samples, %d of them busy. %s."
            % (PART, WORKLOAD, run, tag, span_min, len(t), n_busy,
               NOT_MEASURED[0].upper() + NOT_MEASURED[1:]))

    out = []
    try:
        p1 = _fig_timeline(thr, dmon, spot, outdir)
    except Exception:
        p1 = None
    if p1:
        c = ("Which single limit was active at each sampled moment across the "
             "whole run, with board power on the right axis. The band is the "
             "severity-collapsed NVML clock-event label, so exactly one limit "
             "holds each sample and the stack is 100% at every instant; "
             "limits other than the power cap also get fixed-width tick marks "
             "above the band, because one sample is roughly one pixel wide at "
             "this aspect ratio and would otherwise be invisible. Board power "
             "tracks the enforced limit for essentially the entire run, "
             "dropping only where the server goes idle between requests. "
             + cond)
        if dmon is None:
            c += (" Board power is NOT drawn on this copy: the dmon source "
                  "was absent, and the figure says so on its face.")
        out.append((p1, c))

    try:
        p2 = _fig_share(thr, dmon, spot, outdir)
    except Exception:
        p2 = None
    if p2:
        c = ("Time in each limit as a share of BUSY samples. Idle is excluded "
             "and the figure states how many idle samples were dropped: idle "
             "is a state, not a limit, and including it would dilute every "
             "bar. Filled bars are the exclusive severity-collapsed label; "
             "open diamonds are how often each reason bit was set at all, "
             "since reasons co-occur. Measured in this window: SW power cap "
             "%.1f%% of busy samples, SW thermal %.1f%%, unconstrained "
             "%.1f%%. Limits that never fired are drawn at zero and labelled "
             "as measured rather than omitted, so a reader can tell 'never "
             "happened' from 'never sampled'. %s" % (pcap, tsw, unc, cond))
        out.append((p2, c))

    return out
