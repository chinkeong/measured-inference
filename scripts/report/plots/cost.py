#!/usr/bin/env python3
"""Energy cost per unit of useful work, and what actually drives its variance.

TWO FIGURES:
  1. Energy per completion token against the prompt-to-completion token ratio,
     per exercise, coloured by source language, with the fit and correlation.
  2. The caveat, shown rather than asserted: the board sits pinned at its power
     cap, so joules per token is very nearly throughput restated in other units.

THE ATTRIBUTION RULE, which is the whole reason this module is delicate.
aider records two things per exercise, and they do NOT bracket the same
interval. "duration" covers only the model calls. "t_end" is the mtime of the
results file, stamped AFTER the unit tests and the build cleanup have run. So
the window [t_end - duration, t_end] has the right LENGTH in the WRONG PLACE:
it slides backwards over test-and-build time and bills that to the model. An
earlier published version of this figure did exactly that and reported a 30x
spread in joules per token. The true spread is about 3x.

Exercises run strictly one at a time. Therefore each exercise owns the interval
since the PREVIOUS exercise finished, and the correct window is
    A.energy(dmon, prev["t_end"], this["t_end"], busy_only=True)
The first exercise in the trace has no predecessor and is DROPPED rather than
guessed at. Any exercise whose window is not fully inside the telemetry trace is
dropped too, and both counts are stated on the figure.
"""
import os
import subprocess

import matplotlib
matplotlib.use("Agg")            # REQUIRED - never an interactive backend
import matplotlib.pyplot as plt
import numpy as np

import archdata as A

TITLE = "Energy per token, and what drives it"

# Okabe-Ito, minus the yellow that will not hold on white. Colourblind-safe,
# and every series also carries its own marker so colour is never the only
# thing telling two languages apart.
_PALETTE = ("#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9", "#D55E00")
_MARKERS = ("o", "s", "^", "D", "v", "P")

_INK = "#1b1b1b"
_GREY = "#5a5a5a"

# Conditions that are true of every figure this module emits. Written once so a
# number can never travel without them.
_PART = "NVIDIA RTX 3090 (GA102, 24 GB GDDR6X)"
_WORKLOAD = ("aider polyglot exercises, Qwen3-Coder-30B IQ4_XS on llama.cpp, "
             "MTP speculative decoding on")
_NOTMEAS = ("NOT measured: system or wall power (this is GPU board power from "
            "NVML only, so no PSU loss, CPU, RAM or fans); per-process GPU "
            "power (nvidia-smi pmon reports \"-\" for every process under "
            "Windows WDDM, so board draw cannot be split between the server "
            "and anything else on the card); memory junction temperature "
            "(not exposed by NVML on this part).")

# The same conditions, pre-broken into lines that fit a figure footer without
# relying on matplotlib's wrapper, so the reserved height is predictable.
_FOOTER = (
    "Part: NVIDIA RTX 3090 (GA102, 24 GB GDDR6X), stock 350 W board power "
    "limit, fan pinned at 100%.",
    "Workload: aider polyglot exercises, Qwen3-Coder-30B IQ4_XS on llama.cpp, "
    "MTP speculative decoding on.",
    "Attribution: each exercise owns the interval since the PREVIOUS exercise "
    "finished, integrated over GPU-busy samples only. aider's own \"duration\" "
    "is not",
    "used as the window: the results-file timestamp is written after the unit "
    "tests, so that window has the right length in the wrong place.",
    "NOT measured: system or wall power - this is GPU board power from NVML "
    "only, with no PSU loss, CPU, RAM or fans. Per-process GPU power is "
    "unavailable",
    "under Windows WDDM, so board draw is not split between the server and "
    "anything else on the card. Memory junction temperature is not exposed by "
    "NVML.")

_FOOT_IN = 1.12          # inches of figure height reserved for that footer


def _lay_out(fig, axes, top=1.0):
    """Common finish: grid, despine, reserve the footer band, stamp it."""
    for a in axes:
        a.grid(alpha=0.3, linewidth=0.6)
        a.set_axisbelow(True)
        for sp in ("top", "right"):
            a.spines[sp].set_visible(False)
    frac = _FOOT_IN / float(fig.get_size_inches()[1])
    fig.tight_layout(rect=(0, frac, 1, top))
    fig.text(0.008, frac - 0.015, chr(10).join(_FOOTER), fontsize=7.6,
             color=_GREY, ha="left", va="top", linespacing=1.5)


_LANG_MEMO = {}


def _langs_by_mtime(run):
    """Best-effort map {rounded results-file mtime -> language}.

    A.load_exercises now resolves lang correctly itself (it once landed one
    directory short and returned the literal "exercises" for every row, which
    drew a six-language figure in one colour). This local map is kept because
    it is keyed on the same mtime the loader uses for t_end, so the join to a
    record is exact rather than by case name, which repeats across languages.
    ONE read-only `find`. If WSL is not there, the caller falls back to a
    single series and says so ON the figure.
    """
    if run in _LANG_MEMO:
        return _LANG_MEMO[run]
    out = {}
    try:
        cmd = ("find ~/bench/aider/tmp.benchmarks/" + run +
               " -name .aider.results.json -printf '%T@ %p\\n' 2>/dev/null")
        o = subprocess.run(["wsl", "-e", "bash", "-lc", cmd],
                           capture_output=True, text=True, timeout=90).stdout
        for ln in o.strip().splitlines():
            if " " not in ln:
                continue
            mt, path = ln.split(" ", 1)
            parts = path.strip().replace("\\", "/").split("/")
            if len(parts) < 5:
                continue
            try:
                out[round(float(mt), 3)] = parts[-5]
            except ValueError:
                continue
    except Exception:
        out = {}
    _LANG_MEMO[run] = out
    return out


def _attribute(dmon, exercises, run):
    """Per-exercise energy records under the previous-exercise-finished rule.

    Returns (records, dropped_no_predecessor, dropped_outside_trace,
    dropped_no_busy_energy, telemetry_late_minutes). The last two used to be
    folded into the outside-trace count, which reported an exercise whose
    window held no busy sample as though the trace did not cover it.
    """
    ex = sorted((e for e in exercises if e.get("completion")),
                key=lambda e: e["t_end"])
    if len(ex) < 2:
        return [], len(ex), 0, 0, 0.0
    lang = _langs_by_mtime(run)
    t_lo, t_hi = float(dmon["t"][0]), float(dmon["t"][-1])
    # How much of the run had already happened before the GPU collector
    # started. Every exercise in that stretch is unattributable, and the
    # count of them is meaningless without the reason.
    late_min = max(0.0, (t_lo - ex[0]["t_end"]) / 60.0)
    recs, outside, empty = [], 0, 0
    for i in range(1, len(ex)):
        prev, cur = ex[i - 1], ex[i]
        # The window must be COVERED by the telemetry trace at both ends.
        # A half-covered window would understate joules and look cheap.
        if prev["t_end"] < t_lo or cur["t_end"] > t_hi:
            outside += 1
            continue
        j, busy_s = A.energy(dmon, prev["t_end"], cur["t_end"], busy_only=True)
        comp = float(cur["completion"])
        if j <= 0 or busy_s <= 0 or comp <= 0:
            empty += 1
            continue
        recs.append({
            "case": cur.get("case", "?"),
            "lang": lang.get(round(cur["t_end"], 3), ""),
            "j": j, "busy_s": busy_s, "wall_s": cur["t_end"] - prev["t_end"],
            "comp": comp, "prompt": float(cur.get("prompt", 0) or 0),
            "passed": bool(cur.get("passed")),
        })
    return recs, 1, outside, empty, late_min


def _pearson(x, y):
    if len(x) < 3:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def _spearman(x, y):
    if len(x) < 3:
        return float("nan")
    rx = np.argsort(np.argsort(x)).astype(float)
    ry = np.argsort(np.argsort(y)).astype(float)
    return _pearson(rx, ry)


def _busy_power(dmon):
    """(mean W, coefficient of variation, n) over samples the GPU was busy on."""
    sm, pw = dmon["sm"], dmon["pwr"]
    m = np.isfinite(sm) & np.isfinite(pw) & (sm > A.BUSY_SM_PCT)
    if not m.any():
        return float("nan"), float("nan"), 0
    v = pw[m]
    return float(v.mean()), float(v.std() / v.mean()), int(m.sum())


def _throttle_mix(throttle):
    """{label: percent} over non-idle samples. Idle is a state, not a limit."""
    if throttle is None or not len(throttle.get("t", [])):
        return {}
    _, lab = A.throttle_series(throttle)
    live = [l for l in lab if l not in ("Idle", "no data")]
    if not live:
        return {}
    return {k: 100.0 * live.count(k) / len(live) for k in set(live)}


# --------------------------------------------------------------------------
# Figure 1: cost against the shape of the request
# --------------------------------------------------------------------------
def _fig_cost_vs_ratio(recs, ctx, n_nopred, n_outside, n_empty, late_min,
                       outdir):
    jpt = np.array([r["j"] / r["comp"] for r in recs])
    ratio = np.array([r["prompt"] / r["comp"] for r in recs])
    ok = np.isfinite(jpt) & np.isfinite(ratio) & (ratio > 0)
    jpt, ratio = jpt[ok], ratio[ok]
    keep = [r for r, k in zip(recs, ok) if k]
    if len(jpt) < 3:
        return None

    overall = sum(r["j"] for r in keep) / sum(r["comp"] for r in keep)
    spread = float(jpt.max() / jpt.min())
    r_raw = _pearson(ratio, jpt)
    r_log = _pearson(np.log10(ratio), jpt)
    rho = _spearman(ratio, jpt)

    fig, ax = plt.subplots(figsize=(10.6, 7.0), facecolor="white")
    ax.set_facecolor("white")

    langs = sorted({r["lang"] for r in keep if r["lang"]})
    have_lang = bool(langs)
    if have_lang:
        for i, L in enumerate(langs):
            m = np.array([r["lang"] == L for r in keep])
            if not m.any():
                continue
            ax.scatter(ratio[m], jpt[m], s=48, alpha=0.9,
                       color=_PALETTE[i % len(_PALETTE)],
                       marker=_MARKERS[i % len(_MARKERS)],
                       edgecolors="white", linewidths=0.5, zorder=3,
                       label="%s (n=%d)" % (L, int(m.sum())))
    else:
        ax.scatter(ratio, jpt, s=48, alpha=0.9, color=_PALETTE[0],
                   marker="o", edgecolors="white", linewidths=0.5, zorder=3,
                   label="all exercises (n=%d)" % len(jpt))

    # Least-squares fit in log10(ratio); the ratio spans two decades.
    lx = np.log10(ratio)
    slope, icept = np.polyfit(lx, jpt, 1)
    xs = np.linspace(lx.min(), lx.max(), 100)
    ax.plot(10 ** xs, slope * xs + icept, "--", color=_INK, linewidth=1.7,
            zorder=4,
            label="fit: %.2f x log10(ratio) + %.2f" % (slope, icept))

    # Room on both sides so the extreme labels are never clipped.
    ax.set_xscale("log")
    ax.set_xlim(float(ratio.min()) / 1.8, float(ratio.max()) * 2.6)
    ax.set_ylim(0, float(jpt.max()) * 1.20)

    ax.axhline(overall, color=_GREY, linestyle=":", linewidth=1.5, zorder=2)
    ax.text(ax.get_xlim()[0] * 1.06, overall,
            "run mean %.2f J/token" % overall, va="bottom", ha="left",
            fontsize=8.5, color=_GREY)

    lo_i, hi_i = int(np.argmin(jpt)), int(np.argmax(jpt))
    for i, dy, va in ((lo_i, 15, "bottom"), (hi_i, 0, "center")):
        ax.annotate("%s\n%.2f J/token" % (keep[i]["case"], jpt[i]),
                    (ratio[i], jpt[i]), textcoords="offset points",
                    xytext=(10, dy), fontsize=8, color=_INK, ha="left",
                    va=va,
                    bbox=dict(boxstyle="round,pad=0.28", fc="white",
                              ec=_GREY, lw=0.6, alpha=0.92))

    ax.set_xlabel("Prompt tokens per completion token "
                  "(dimensionless ratio, log scale)", fontsize=10.5)
    ax.set_ylabel("Energy per completion token  (joules per token,\n"
                  "GPU board power only)", fontsize=10.5)
    ax.set_title("Prompt-heavy calls cost %.1fx more board energy "
                 "per completion token" % spread,
                 fontsize=12.5, fontweight="bold", color=_INK, pad=10)

    note = ("Window: the interval since the previous exercise finished,\n"
            "GPU-busy samples only (SM > %.0f%%).\n"
            "n = %d attributed. Dropped: %d with no predecessor, %d whose\n"
            "window falls outside the telemetry trace (the GPU collector\n"
            "started %.0f min after the first exercise finished), %d whose\n"
            "window held no GPU-busy sample.\n"
            "Pearson r = %.2f on the raw ratio, %.2f in log10;\n"
            "Spearman rho = %.2f.\n"
            "%s"
            % (A.BUSY_SM_PCT, len(jpt), n_nopred, n_outside, late_min,
               n_empty, r_raw, r_log, rho,
               "Language read from the exercise path."
               if have_lang else
               "Language: NOT resolvable here, all points drawn alike."))
    ax.text(0.015, 0.975, note, transform=ax.transAxes, fontsize=7.9,
            va="top", ha="left", color=_INK, linespacing=1.45,
            bbox=dict(boxstyle="round,pad=0.5", fc="#f4f4f4", ec="#cccccc",
                      lw=0.8))

    ax.legend(loc="lower right", fontsize=8.3, framealpha=0.94,
              edgecolor="#cccccc")

    _lay_out(fig, [ax])

    path = os.path.join(outdir, "cost-energy-per-token-vs-prompt-ratio.png")
    fig.savefig(path, dpi=140, facecolor="white")
    plt.close(fig)

    cap = ("Energy per completion token against the prompt-to-completion token "
           "ratio, one point per aider polyglot exercise, coloured by source "
           "language. Part: %s. Workload: %s. Attribution: each exercise owns "
           "the interval since the previous exercise finished, integrated over "
           "GPU-busy samples (SM > %.0f%%); aider's \"duration\" is deliberately "
           "not used as the window because the results-file timestamp is "
           "written after the unit tests, which would bill test-time idle to "
           "the model. %d exercises attributed, %d dropped for having no "
           "predecessor, %d for falling outside the telemetry trace (the GPU "
           "collector started %.0f minutes after the first exercise finished) "
           "and %d for holding no GPU-busy sample. Run "
           "mean %.2f J per completion token (%.2f kWh per million completion "
           "tokens); range %.2f (%s) to %.2f (%s), a spread of %.1fx, "
           "correlating with the prompt:completion ratio at Pearson r = %.2f "
           "(Spearman rho = %.2f, n = %d). %s"
           % (_PART, _WORKLOAD, A.BUSY_SM_PCT, len(jpt), n_nopred, n_outside,
              late_min, n_empty,
              overall, overall * 1e6 / 3.6e6, float(jpt.min()),
              keep[lo_i]["case"], float(jpt.max()), keep[hi_i]["case"],
              spread, r_raw, rho, len(jpt), _NOTMEAS))
    return path, cap


# --------------------------------------------------------------------------
# Figure 2: the caveat, demonstrated
# --------------------------------------------------------------------------
def _fig_cost_is_throughput(recs, ctx, outdir):
    jpt = np.array([r["j"] / r["comp"] for r in recs])
    spt = np.array([r["busy_s"] / r["comp"] for r in recs])
    ok = np.isfinite(jpt) & np.isfinite(spt) & (spt > 0)
    jpt, spt = jpt[ok], spt[ok]
    if len(jpt) < 3:
        return None

    dmon = ctx.get("dmon")
    pw_mean, pw_cv, pw_n = _busy_power(dmon)
    win_pw = jpt / spt                       # per-window mean board power, W
    win_cv = float(win_pw.std() / win_pw.mean())
    p_bar = float(win_pw.mean())
    # Goodness of fit of the ONE-parameter model actually drawn, J/tok =
    # P_bar * s/tok, which passes through the origin. Not Pearson r squared:
    # that would score a two-parameter line nobody plotted.
    ss_res = float(((jpt - p_bar * spt) ** 2).sum())
    ss_tot = float(((jpt - jpt.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    mix = _throttle_mix(ctx.get("throttle"))

    fig, (axL, axR) = plt.subplots(
        1, 2, figsize=(11.6, 6.4), facecolor="white",
        gridspec_kw={"width_ratios": [1.35, 1.0]})
    for a in (axL, axR):
        a.set_facecolor("white")

    axL.scatter(spt, jpt, s=44, alpha=0.85, color=_PALETTE[0], marker="o",
                edgecolors="white", linewidths=0.5, zorder=3,
                label="one exercise (n=%d)" % len(jpt))
    xs = np.linspace(0, float(spt.max()) * 1.05, 50)
    axL.plot(xs, p_bar * xs, "-", color=_PALETTE[5], linewidth=1.9, zorder=4,
             label="constant %.0f W board draw" % p_bar)
    axL.set_xlim(0, float(spt.max()) * 1.08)
    axL.set_ylim(0, float(jpt.max()) * 1.12)
    axL.set_xlabel("GPU-busy seconds per completion token  (s/token)",
                   fontsize=10.5)
    axL.set_ylabel("Energy per completion token  (joules per token,\n"
                   "GPU board power only)", fontsize=10.5)
    axL.set_title("Cost per token is time per token times a constant",
                  fontsize=11, color=_INK, pad=8)
    axL.text(0.035, 0.955,
             "The one-parameter model J/token = %.0f W x s/token\n"
             "explains r$^2$ = %.3f of the variance, with no intercept.\n"
             "Mean board power per exercise varies by only %.1f%%\n"
             "(coefficient of variation), so the energy axis carries\n"
             "almost no information that throughput does not."
             % (p_bar, r2, 100 * win_cv),
             transform=axL.transAxes, fontsize=8.3, va="top", ha="left",
             color=_INK, linespacing=1.45,
             bbox=dict(boxstyle="round,pad=0.45", fc="#f4f4f4",
                       ec="#cccccc", lw=0.8))
    axL.legend(loc="lower right", fontsize=8.3, framealpha=0.94,
               edgecolor="#cccccc")

    if pw_n:
        busy_w = dmon["pwr"][np.isfinite(dmon["pwr"]) &
                             (dmon["sm"] > A.BUSY_SM_PCT)]
        # A ~1% tail of ramp-in samples sits near idle draw. Left in the axis
        # it flattens the whole distribution against the right spine, so the
        # axis is windowed and the excluded count is stated rather than hidden.
        lo_w = 260.0
        below = int((busy_w < lo_w).sum())
        axR.hist(busy_w[busy_w >= lo_w], bins=36, color=_PALETTE[4],
                 edgecolor="white", linewidth=0.4)
        axR.set_xlim(lo_w, float(busy_w.max()) + 6)
        axR.axvline(pw_mean, color=_INK, linestyle="--", linewidth=1.6)
        axR.text(pw_mean, axR.get_ylim()[1] * 0.97,
                 " mean %.0f W " % pw_mean, rotation=90, va="top",
                 ha="right", fontsize=8.5, color=_INK)
        axR.set_xlabel("GPU board power on busy samples  (watts)",
                       fontsize=10.5)
        axR.set_ylabel("Telemetry samples  (count, ~1 Hz)", fontsize=10.5)
        axR.set_title("The board lives at its cap", fontsize=11,
                      color=_INK, pad=8)
        mix_txt = "\n".join(
            "    %-16s %4.1f%%" % (k, v)
            for k, v in sorted(mix.items(), key=lambda kv: -kv[1])) \
            or "    not collected"
        axR.text(0.035, 0.955,
                 "n = %d busy samples (SM > %.0f%%), mean %.0f W,\n"
                 "coefficient of variation %.1f%%.\n"
                 "%d further busy samples (%.1f%%) fall below %.0f W\n"
                 "during ramp-in and are off this axis, not dropped.\n"
                 "NVML clock-limit reason, non-idle samples:\n%s"
                 % (pw_n, A.BUSY_SM_PCT, pw_mean, 100 * pw_cv, below,
                    100.0 * below / pw_n, lo_w, mix_txt),
                 transform=axR.transAxes, fontsize=7.9, va="top", ha="left",
                 color=_INK, linespacing=1.45,
                 bbox=dict(boxstyle="round,pad=0.45", fc="#f4f4f4",
                           ec="#cccccc", lw=0.8))
    else:
        axR.text(0.5, 0.5, "GPU board power: not present in this trace",
                 ha="center", va="center", fontsize=11, color=_GREY,
                 transform=axR.transAxes)
        axR.set_xticks([])
        axR.set_yticks([])

    fig.suptitle("Read joules per token as throughput in other units: the part "
                 "is power-capped, not power-varying",
                 fontsize=12.5, fontweight="bold", color=_INK, y=0.982)

    _lay_out(fig, (axL, axR), top=0.955)

    path = os.path.join(outdir, "cost-energy-is-throughput-restated.png")
    fig.savefig(path, dpi=140, facecolor="white")
    plt.close(fig)

    cap = ("Why the joules-per-token number on the companion figure is not an "
           "independent measurement. Left: energy per completion token against "
           "GPU-busy seconds per completion token, one point per exercise; the "
           "line is a constant %.0f W board draw and fits at r2 = %.3f. Mean "
           "board power per exercise varies by only %.1f%% (coefficient of "
           "variation), so energy per token is essentially time per token "
           "multiplied by a fixed number. Right: distribution of board power "
           "over %d GPU-busy telemetry samples (SM > %.0f%%), mean %.0f W at "
           "%.1f%% coefficient of variation, with the NVML clock-limit reason "
           "over non-idle samples (%s). An architect should therefore treat "
           "energy-per-token differences on this part as throughput "
           "differences, and expect the two to decouple only on a part that is "
           "not pinned to its power limit. Part: %s. Workload: %s. %s"
           % (p_bar, r2, 100 * win_cv, pw_n, A.BUSY_SM_PCT, pw_mean,
              100 * pw_cv,
              ", ".join("%s %.1f%%" % (k, v)
                        for k, v in sorted(mix.items(), key=lambda kv: -kv[1]))
              or "not collected",
              _PART, _WORKLOAD, _NOTMEAS))
    return path, cap


# --------------------------------------------------------------------------
def make(ctx, outdir):
    """ctx has keys: tag, run, dmon, slots, host, throttle, requests, exercises
    (any may be None if that source is absent - degrade gracefully, never
    crash). Returns a list of (png_path, caption_string)."""
    out = []
    dmon = ctx.get("dmon")
    exercises = ctx.get("exercises")
    run = ctx.get("run") or ""

    # Both figures need per-exercise energy, which needs both sources. With
    # either one missing there is no honest figure to draw, so draw none.
    if dmon is None or not len(dmon.get("t", [])):
        return out
    if not exercises:
        return out

    try:
        os.makedirs(outdir, exist_ok=True)
    except Exception:
        return out

    recs, n_nopred, n_outside, n_empty, late_min = _attribute(
        dmon, exercises, run)
    if len(recs) < 3:
        return out

    for fn in (lambda: _fig_cost_vs_ratio(recs, ctx, n_nopred, n_outside,
                                          n_empty, late_min, outdir),
               lambda: _fig_cost_is_throughput(recs, ctx, outdir)):
        try:
            r = fn()
        except Exception:
            r = None
        if r:
            out.append(r)
    return out
