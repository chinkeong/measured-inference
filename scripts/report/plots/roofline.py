#!/usr/bin/env python3
"""Roofline for a single-stream decoder on the reference part.

WHAT THIS MODULE ASSERTS, AND WHY THE AXES ARE WHAT THEY ARE.

A classic roofline puts FLOP/s against FLOP/byte. That needs a FLOP count per
token, and this campaign has not measured one: the parameter count would be
inferred from a file size, and llama.cpp's IQ4_XS kernels do not do a clean
2*N multiply-accumulates per token. Inventing that number would put a
fabricated quantity on the campaign's headline chart.

So the axes are stated in the units that WERE measured:

    y = achieved throughput, in useful tokens per second
    x = arithmetic intensity, in useful tokens per gigabyte of WEIGHT traffic

which is dimensionally a roofline and nothing else:

    tokens/s  =  (GB/s)  x  (tokens/GB)

The memory-bandwidth roof is therefore the straight line y = BW * x, and the
compute roof is a horizontal line. The x axis has a plain physical reading,
carried on the top spine: tokens committed per pass over the weights. Plain
autoregressive decode commits exactly one, which is the whole problem.

WHAT IS MEASURED AND WHAT IS NOT, stated once here so the figures can be terse:
  measured      decode throughput with and without the draft head; mean
                accepted length; prompt-processing throughput; board power;
                core and memory clocks; throttle reasons; the model file size;
                the server's own command line, read from the live process.
  NOT measured  FLOPs; KV-cache read traffic (the x axis counts weight bytes
                only); the draft head's own weight traffic; per-request
                accepted length; any power figure other than board power.

LAYOUT RULE, because a figure that carries its own conditions carries a lot of
text and every word of it has to be readable: the conditions block is a
FIGURE-level footer whose HEIGHT IS COMPUTED FROM ITS CONTENT, never a hand-
tuned fraction, and every line in it is re-flowed to the column width before it
is drawn. A longer condition therefore makes the block taller and the axes
shorter; it can never run off the page or print on top of the other column.
"""
import os
import textwrap

import matplotlib
matplotlib.use("Agg")            # REQUIRED - never an interactive backend
import matplotlib.pyplot as plt
import numpy as np

try:
    import archdata as A
except ImportError:                                  # pragma: no cover
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    import archdata as A

TITLE = "Speculation moves decode off the bandwidth roof"

# ---------------------------------------------------------------------------
# Measured constants. Every one travels with its condition; none is a round
# number chosen for convenience.
# ---------------------------------------------------------------------------
PART = "RTX 3090 (GA102, 24 GB GDDR6X, 350 W board-power cap)"

# The following three values were measured on the UD-IQ4_XS arm specifically.
# They are used as the plotted "MEASURED" points ONLY when the current run IS
# that arm.  When the run is a different arm, the figure either uses the run's
# own accept_len (from meta) or labels these as belonging to UD-IQ4_XS.
_IQ4XS_DECODE_OFF = 45.2        # tok/s, draft head off, UD-IQ4_XS arm
_IQ4XS_DECODE_ON  = 99.16       # tok/s, draft head on,  UD-IQ4_XS arm
_IQ4XS_ACCEPT_LEN = 3.55        # mean accepted length,  UD-IQ4_XS arm

# Read from the live server process, not assumed:
#   -c 32768 --parallel 1 -fa on -ctk q8_0 -ctv q8_0
#   --spec-type draft-mtp --spec-draft-n-max 4 --spec-draft-p-min 0.75
# and no -b / -ub, so the llama.cpp defaults below stand.
N_DRAFT_MAX = 4
UBATCH = 512             # llama.cpp default n_ubatch: one weight pass
NBATCH = 2048            # llama.cpp default n_batch: the logical batch

MCLK_MAX = 9751.0        # MHz, nvidia-smi clocks.max.memory
PCLK_MAX = 2130.0        # MHz, nvidia-smi clocks.max.sm

# Used only when a telemetry source is absent; labelled as a fallback on the
# figure whenever it is used, so it can never be mistaken for a measurement.
PP_FALLBACK = 2050.0     # prompt tokens/s, sustained

# Okabe-Ito. Every series is also distinguished by marker shape or line style,
# so no reading depends on telling two hues apart.
CB = {"off": "#E69F00", "on": "#0072B2", "spread": "#56B4E9",
      "pp": "#CC79A7", "compute": "#009E73", "cap": "#D55E00",
      "roof": "#000000", "grey": "#8C8C8C"}

# Wide and tall on purpose. These figures carry their conditions, a legend and
# six or seven callouts; on a 10 x 6.5 canvas those blocks are each a third of
# the axes wide and they collide. Giving the canvas more room shrinks every
# text block as a fraction of the axes without shrinking a single word of it.
_FIG = dict(figsize=(13.6, 8.8), dpi=140, facecolor="white")
_BOX = dict(boxstyle="round,pad=0.28", fc="white", ec="none", alpha=0.86)


# ---------------------------------------------------------------------------
# Live-data reductions. Each returns None rather than guessing.
# ---------------------------------------------------------------------------
def _pp_throughput(slots):
    """Sustained prompt-processing throughput, tokens/s, plus its conditions.

    Only windows in which the prompt counter advanced and n_decoded did NOT are
    used: a mixed window blends two regimes and would land the point between
    them. Runs of two or more consecutive such windows are preferred, because a
    single poll can catch a counter mid-update and invent a spike.

    The ~1 s poll cannot resolve anything faster than itself, so the answer is
    a LOWER BOUND on the compute-side ceiling, never an estimate of it.
    """
    if slots is None or len(slots.get("t", ())) < 3:
        return None
    runs, ct, cp, n = [], 0.0, 0.0, 0
    for i in range(1, len(slots["t"])):
        same = slots["id_task"][i] == slots["id_task"][i - 1]
        dt = slots["t"][i] - slots["t"][i - 1]
        dp = (slots["n_prompt_tokens_processed"][i]
              - slots["n_prompt_tokens_processed"][i - 1]) if same else 0.0
        dn = (slots["n_decoded"][i]
              - slots["n_decoded"][i - 1]) if same else 0.0
        if same and dt > 0 and dp > 0 and dn <= 0:
            ct += dt
            cp += dp
            n += 1
            continue
        if n >= 2:
            runs.append(cp / ct)
        ct = cp = 0.0
        n = 0
    if n >= 2:
        runs.append(cp / ct)
    if not runs:
        return None
    runs = np.asarray(runs, dtype=float)
    if not np.isfinite(runs).any() or runs.max() <= 0:
        return None
    return {"rate": float(runs.max()), "median": float(np.median(runs)),
            "n": int(runs.size)}


def _decode_spread(slots):
    """The agentic run's own decode-rate distribution, tokens/s.

    This is the SAME quantity as _IQ4XS_DECODE_ON but over a different
    workload: a live agentic benchmark whose prompts, and therefore whose draft
    acceptance, vary from request to request. It is drawn as a spread rather
    than a point because it is one.
    """
    if slots is None or len(slots.get("t", ())) < 3:
        return None
    _, r = A.decode_rate(slots, 1)
    if r.size < 20:
        return None
    tot_n = tot_t = 0.0
    for i in range(1, len(slots["t"])):
        if slots["id_task"][i] != slots["id_task"][i - 1]:
            continue
        dt = slots["t"][i] - slots["t"][i - 1]
        dn = slots["n_decoded"][i] - slots["n_decoded"][i - 1]
        if dt > 0 and dn > 0:
            tot_n += dn
            tot_t += dt
    p10, p50, p90 = np.percentile(r, [10, 50, 90])
    return {"p10": float(p10), "p50": float(p50), "p90": float(p90),
            "agg": float(tot_n / tot_t) if tot_t > 0 else float(p50),
            "n": int(r.size), "tokens": float(tot_n)}


def _clock_state(dmon, throttle):
    """What the power cap actually took, in clocks, on busy samples only."""
    out = {}
    if dmon is not None and len(dmon.get("t", ())) > 10:
        busy = dmon["sm"] > A.BUSY_SM_PCT
        if busy.sum() > 10:
            out["nbusy"] = int(busy.sum())
            # Each field is guarded on its own. A column that is NULL on this
            # part must not suppress a neighbouring column that is live: the
            # figure states what was measured, field by field.
            if np.isfinite(dmon["pwr"][busy]).any():
                out["pwr"] = float(np.nanmean(dmon["pwr"][busy]))
                out["pwr_cv"] = float(np.nanstd(dmon["pwr"][busy])
                                      / np.nanmean(dmon["pwr"][busy]))
            if np.isfinite(dmon["gtemp"][busy]).any():
                out["gtemp"] = float(np.nanmedian(dmon["gtemp"][busy]))
            if (np.isfinite(dmon["mclk"][busy]).any()
                    and np.isfinite(dmon["pclk"][busy]).any()):
                out["mclk"] = float(np.nanmedian(dmon["mclk"][busy]))
                out["pclk"] = float(np.nanmedian(dmon["pclk"][busy]))
    if throttle is not None and len(throttle.get("t", ())) > 10:
        _, lab = A.throttle_series(throttle)
        act = [l for l in lab if l not in ("Idle", "no data")]
        if act:
            out["swpow"] = 100.0 * act.count("SW power cap") / len(act)
            out["swthm"] = 100.0 * act.count("SW thermal") / len(act)
            out["nact"] = len(act)
    return out or None


def _fit_speculation(accept_len, decode_off, decode_on, model_gb):
    """Two-parameter cost model for speculative decode, fitted through the two
    measured points and nothing else.

        seconds per accepted token  =  T0 / L  +  T1
        throughput(L)               =  L / (T0 + T1 * L)

    T0 is the cost of one pass over the weights, paid once per verification
    cycle no matter how many tokens ride on it. T1 is the marginal cost of each
    speculated token: the draft head's own serial forward pass, the wider
    verification GEMM, the extra sampling.

    Two points, two parameters, zero degrees of freedom. There is no residual
    and therefore no error bar. This is an interpolation with a physical shape,
    not a measurement, and both the figure and its caption say so.
    """
    m = np.array([[1.0, 1.0], [1.0, accept_len]])
    b = np.array([1.0 / decode_off, accept_len / decode_on])
    try:
        t0, t1 = np.linalg.solve(m, b)
    except np.linalg.LinAlgError:
        return None
    if not (t0 > 0 and t1 > 0):
        return None
    return {"T0": float(t0), "T1": float(t1), "asym": float(1.0 / t1),
            "bw_at_T0": float(model_gb / t0),
            "f": lambda L: (np.asarray(L, dtype=float)
                            / (t0 + t1 * np.asarray(L, dtype=float)))}


# ---------------------------------------------------------------------------
# Shared furniture
# ---------------------------------------------------------------------------
def _roofs(ax, bw, compute, xlim, model_gb, decode_off,
           compute_in_view=True):
    """The roof itself, plus the bandwidth a real controller actually gave."""
    xs = np.logspace(np.log10(xlim[0]), np.log10(xlim[1]), 400)
    roof = np.minimum(bw * xs, compute)
    ach = decode_off * model_gb
    lab = ("roof: %.0f GB/s bandwidth, then %.0f tok/s compute"
           % (bw, compute)) if compute_in_view else (
          "roof: %.0f GB/s spec bandwidth (the %.0f tok/s compute\n"
          "roof is far above and right of this view)" % (bw, compute))
    ax.plot(xs, roof, color=CB["roof"], lw=2.4, zorder=4, label=lab)
    ax.plot(xs, np.minimum(ach * xs, compute), color=CB["grey"], lw=1.5,
            ls="--", zorder=3,
            label="bandwidth achieved: %.0f GB/s, %.0f%% of spec"
                  % (ach, 100 * ach / bw))
    ax.fill_between(xs, np.minimum(ach * xs, compute), roof,
                    color=CB["grey"], alpha=0.10, lw=0, zorder=1)
    return ach


def _frame(ax, xlim, ylim, model_gb):
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.grid(True, which="major", alpha=0.3)
    ax.grid(True, which="minor", alpha=0.12)
    ax.set_xlabel("arithmetic intensity  (useful tokens per GB of weight "
                  "traffic, tokens/GB)", fontsize=10)
    ax.set_ylabel("achieved throughput\n(useful tokens per second, tok/s)",
                  fontsize=10)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    sec = ax.secondary_xaxis("top",
                             functions=(lambda x: np.asarray(x) * model_gb,
                                        lambda v: np.asarray(v) / model_gb))
    sec.set_xlabel("tokens committed per pass over the %.2f GB of weights "
                   "(tokens/pass)" % model_gb, fontsize=9.5)
    sec.tick_params(labelsize=8.5)


def _tag(ax, text, xy, xytext, colour, ha="left", va="top", size=8.3,
         weight="normal"):
    ax.annotate(text, xy=xy, xytext=xytext, fontsize=size, color=colour,
                ha=ha, va=va, linespacing=1.35, fontweight=weight,
                bbox=_BOX, zorder=8,
                arrowprops=dict(arrowstyle="-", color=colour, lw=1.0,
                                shrinkA=1, shrinkB=6))


def _cols(width_in, pt, k=0.545):
    """Roughly how many characters of a given point size fit across a column of
    the given width in inches. Deliberately pessimistic: over-estimating the
    column is what clips text at the figure edge, which is the one failure this
    helper exists to prevent."""
    return max(int(width_in * 72.0 / (pt * k)), 30)


def _reflow(items, ncols):
    """Re-flow the conditions lines to the column width. Lines that already fit
    come back untouched, so the hand-set line breaks are respected; a line that
    would have overrun the column is wrapped instead of being clipped, with a
    hanging indent if it is a bullet."""
    out = []
    for it in items:
        body = it.lstrip(" ")
        lead = len(it) - len(body)
        sub = " " * (lead + 2) if body.startswith("- ") else " " * lead
        out.extend(textwrap.wrap(it, width=ncols, subsequent_indent=sub,
                                 break_long_words=False,
                                 break_on_hyphens=False) or [""])
    return out


def _footer(fig, left, right, pt=6.9, lead=1.6):
    """Conditions live BELOW the axes, in two columns, so they never sit on
    top of the data.

    The block's height is COMPUTED from how many lines it actually holds, so
    the text can neither be cut off at the bottom of the page nor leave a band
    of empty grey behind it, whichever way the conditions grow. The axes get
    whatever is left. Returns that height as a figure fraction.

    tight_layout is called here, before any inset is added, because an inset
    axes makes tight_layout refuse to run.
    """
    hpt = fig.get_figheight() * 72.0
    x0, xm, gap = 0.010, 0.513, 0.014
    col = _cols((xm - x0 - 0.012) * fig.get_figwidth(), pt)
    L, R = _reflow(left, col), _reflow(right, col)
    rows = max(len(L), len(R))
    height = (rows * pt * lead + 18.0) / hpt
    fig.tight_layout(rect=(0.0, height + gap, 1.0, 1.0))
    dy = pt * lead / hpt
    y = height - 9.0 / hpt
    for i, ln in enumerate(L):
        fig.text(x0, y - i * dy, ln, ha="left", va="top", fontsize=pt,
                 color="#222222")
    for i, ln in enumerate(R):
        fig.text(xm, y - i * dy, ln, ha="left", va="top", fontsize=pt,
                 color="#444444")
    fig.patches.append(plt.Rectangle(
        (0.006, 0.005), 0.988, height - 0.005, transform=fig.transFigure,
        fc="#FAFAFA", ec="#DDDDDD", lw=0.8, zorder=-5))
    return height


def _not_measured(extra):
    base = ["NOT MEASURED, and so implied nowhere above:",
            "  - FLOPs. Neither axis is in FLOP/s because a FLOP count per "
            "token would have to be invented.",
            "  - KV-cache reads, and the draft head's own weights. x counts "
            "WEIGHT bytes only, so true intensity",
            "    is a little lower, and true bandwidth use a little higher, "
            "than plotted.",
            "  - system power and wall power. Board power only, throughout."]
    return base + extra + [
        "  - memory junction temperature: NVML exposes none on this part "
        "(mtemp is NULL on every sample)."]


# ---------------------------------------------------------------------------
# Figure 1 - the operating points
# ---------------------------------------------------------------------------
def _fig_points(outdir, pp, spread, clk, model_gb, decode_off, decode_on,
                accept_len, is_iq4xs, meta):
    bw = A.SPEC_BW_GBS
    x_off = 1.0 / model_gb
    x_on = accept_len / model_gb
    x_pp = UBATCH / model_gb
    x_pp_hi = NBATCH / model_gb

    model_name = A.model_phrase(meta)
    window_str = A.window_phrase(meta)
    drafter_str = A.drafter_phrase(meta)

    # Where the decode measurements came from
    if is_iq4xs:
        meas_src = "measured on this arm (UD-IQ4_XS)"
    else:
        meas_src = "measured on UD-IQ4_XS, not this run"

    if pp is not None:
        compute = pp["rate"]
        pp_src = ["  - the compute roof as a spec number. It is measured over "
                  "%d sustained prompt-processing" % pp["n"],
                  "    windows, and the ~1 s poll resolves nothing faster, so "
                  "it is a FLOOR on the true ceiling."]
        pp_why = ("measured over %d sustained prompt-processing windows, and "
                  "the ~1 s poll resolves nothing faster, so it is a floor on "
                  "the true ceiling" % pp["n"])
    else:
        compute = PP_FALLBACK
        pp_src = ["  - the compute roof at all. It is a FALLBACK CONSTANT: "
                  "the /slots trace was absent, so",
                  "    prompt processing was NOT measured this run."]
        pp_why = ("a fallback constant - the /slots trace was absent, so "
                  "prompt processing was not measured this run")

    xlim = (0.020, 260.0)
    ylim = (16.0, 14000.0)
    roof_on = bw * x_on
    x_ridge = compute / bw

    fig, ax = plt.subplots(**_FIG)
    _roofs(ax, bw, compute, xlim, model_gb, decode_off)
    _frame(ax, xlim, ylim, model_gb)

    # ---- the power-limited gap, drawn at the intensity where it was measured
    ax.vlines(x_on, decode_on, roof_on, color=CB["cap"], lw=11, alpha=0.16,
              zorder=2)
    ax.annotate("", xy=(x_on, roof_on), xytext=(x_on, decode_on),
                arrowprops=dict(arrowstyle="<->", color=CB["cap"], lw=1.7,
                                shrinkA=0, shrinkB=0), zorder=6)
    ax.annotate("%.1fx of the bandwidth roof is unused here.\n"
                "What binds at this point is the 350 W\n"
                "board-power cap, not bandwidth."
                % (roof_on / decode_on),
                xy=(x_on * 1.06, np.sqrt(decode_on * roof_on)),
                xytext=(x_on * 1.58, 250.0), fontsize=8.5, color=CB["cap"],
                ha="left", va="top", linespacing=1.4, fontweight="bold",
                bbox=_BOX, zorder=8,
                arrowprops=dict(arrowstyle="-", color=CB["cap"], lw=1.0,
                                shrinkA=1, shrinkB=2))

    # ---- operating points
    meas_label_off = ("decode, draft head OFF (%s)" % meas_src)
    ax.plot([x_off], [decode_off], marker="s", ms=11, color=CB["off"],
            mec="black", mew=0.9, ls="none", zorder=9,
            label=meas_label_off)
    _tag(ax, "draft head OFF: 1 token per weight pass.\n"
             "%.1f tok/s = %.0f GB/s = %.0f%% of the roof.\n"
             "For practical purposes this point IS the roof."
             % (decode_off, decode_off * model_gb,
                100 * decode_off / (bw * x_off)),
         (x_off * 0.97, decode_off * 1.06), (0.0235, 2400.0),
         "#7a5400", ha="left")

    if spread is not None:
        ax.vlines(x_on * 0.80, spread["p10"], spread["p90"],
                  color=CB["spread"], lw=7, alpha=0.65, zorder=5,
                  label="live agentic run, p10 to p90 spread")
        ax.plot([x_on * 0.80], [spread["agg"]], marker="_", ms=16,
                color="#12587f", mew=2.6, ls="none", zorder=6)

    meas_label_on = ("decode, MTP draft head ON (%s)" % meas_src)
    ax.plot([x_on], [decode_on], marker="o", ms=12, color=CB["on"],
            mec="black", mew=0.9, ls="none", zorder=9,
            label=meas_label_on)
    _tag(ax, "draft head ON: %.2f tokens / weight pass\n"
             "%.2f tok/s BEATS the %.1f tok/s one-pass-per-token ceiling,\n"
             "so traffic is only %.0f GB/s = %.0f%% of the roof"
             % (accept_len, decode_on, bw / model_gb,
                decode_on / accept_len * model_gb, 100 * decode_on / roof_on),
         (x_on, decode_on * 0.93), (x_on * 0.90, decode_on * 0.60),
         "#0b3a58", ha="left")

    # ---- prompt processing: y measured, x inferred and said to be inferred
    ax.plot([x_pp], [compute], marker="D", ms=10, color=CB["pp"],
            mec="black", mew=0.9, ls="none", zorder=9,
            label="prompt processing (throughput measured)")
    ax.hlines(compute, x_pp, x_pp_hi, color=CB["pp"], lw=2.6, alpha=0.85,
              zorder=7)
    for xe in (x_pp, x_pp_hi):
        ax.plot([xe], [compute], marker="|", ms=11, color=CB["pp"], mew=2.2,
                ls="none", zorder=7)
    _tag(ax, "prompt processing: a whole micro-batch per weight pass.\n"
             "%.0f tok/s, about %.0fx BELOW the bandwidth roof at its own\n"
             "intensity - compute-bound, not memory-bound. Bar spans\n"
             "n_ubatch 512 to 2048: NOT logged, so only y is measured."
             % (compute, bw * x_pp / compute),
         (x_pp * 0.98, compute * 1.12), (x_pp * 0.70, 12200.0), "#5c2c48",
         ha="right")

    # ---- ridge point
    ax.plot([x_ridge], [compute], marker="*", ms=16, color=CB["compute"],
            mec="black", mew=0.7, ls="none", zorder=9,
            label="ridge point: compute takes over from bandwidth")
    _tag(ax, "ridge point: %.0f tokens per weight pass.\n"
             "Everything left of here is memory-bound.\nMTP delivers %.2f."
             % (x_ridge * model_gb, accept_len),
         (x_ridge, compute * 0.90), (x_ridge * 1.5, compute * 0.62),
         "#00563f", ha="left")

    ax.text(0.022, 0.985, "above the roof: physically unreachable",
            transform=ax.transAxes, fontsize=7.8, color="#9A9A9A",
            style="italic", ha="left", va="top", zorder=3)

    ax.set_title("Speculation moves decode off the bandwidth roof and onto "
                 "the power limit", fontsize=13.5, fontweight="bold", pad=26)
    leg = ax.legend(loc="lower right", fontsize=7.2, framealpha=0.95,
                    borderpad=0.55, labelspacing=0.42, handlelength=1.8,
                    bbox_to_anchor=(0.997, 0.015))
    leg.set_zorder(10)

    left = ["CONDITIONS. " + PART + ", fan pinned at 100%.",
            "Workload: agentic coding benchmark, one slot. "
            "%s, %.2f GB of weights." % (model_name, model_gb),
            "Server flags: %s, %s." % (window_str, drafter_str)]
    if not is_iq4xs:
        left.append("Decode measurements (%.1f and %.2f tok/s at L = %.2f) "
                    "are from UD-IQ4_XS, not this arm."
                    % (decode_off, decode_on, accept_len))
    if clk and "pwr" in clk:
        left.append("Board power %.0f W mean over %d busy samples, "
                    "coefficient of variation %.0f%% (the standard"
                    % (clk["pwr"], clk["nbusy"], 100 * clk["pwr_cv"]))
        left.append("  deviation as a percentage of the mean). GPU die "
                    "%s." % ("%.0f C median" % clk["gtemp"]
                             if "gtemp" in clk else "temperature NOT measured"))
    if clk and "swpow" in clk:
        left.append("SW power cap active on %.0f%% of %d non-idle samples; "
                    "SW thermal on %.0f%%." % (clk["swpow"], clk["nact"],
                                               clk["swthm"]))
    if clk and "pclk" in clk:
        left.append("The cap takes CORE clock, not memory clock: core %.0f of "
                    "%.0f MHz (%.0f%%), memory %.0f of"
                    % (clk["pclk"], PCLK_MAX, 100 * clk["pclk"] / PCLK_MAX,
                       clk["mclk"]))
        left.append("  %.0f MHz (%.0f%%). So the bandwidth roof stays put and "
                    "the compute roof comes down."
                    % (MCLK_MAX, 100 * clk["mclk"] / MCLK_MAX))
    if not clk:
        left.append("GPU telemetry absent for this run: board power, clocks "
                    "and throttle reasons were NOT measured.")

    right = _not_measured([
        "  - the prompt-processing micro-batch. Its bar spans n_ubatch 512 to "
        "n_batch 2048; only",
        "    its throughput is measured.",
        "  - per-request accepted length. The live spread sits at the RUN-MEAN "
        "intensity, so only",
        "    its vertical extent is measured, not where it sits on x."]
        + pp_src)

    _footer(fig, left, right)
    path = os.path.join(outdir, "roofline-operating-points.png")
    fig.savefig(path, facecolor="white")
    plt.close(fig)

    if clk and "swpow" in clk and "pclk" in clk:
        tail = (", which is active on %.0f%% of non-idle samples and pulls the "
                "core clock to %.0f of %.0f MHz while the memory clock holds "
                "at %.0f of %.0f MHz - the cap lowers the compute roof and "
                "leaves the bandwidth roof exactly where it was"
                % (clk["swpow"], clk["pclk"], PCLK_MAX, clk["mclk"], MCLK_MAX))
    else:
        tail = " (throttle and clock telemetry absent for this run)"

    cap = (
        "Roofline for single-stream decode on %s. Axes: achieved useful tokens "
        "per second against useful tokens per GB of weight traffic, both log; "
        "the roof is y = min(%.0f GB/s x intensity, the measured compute "
        "ceiling of %.0f tok/s), so a point lying ON the sloped roof is "
        "bandwidth-bound. Workload: %s (%.2f GB resident) "
        "on an agentic coding benchmark, %s, flash "
        "attention on, KV cache q8_0, %s. The "
        "finding: plain decode moves the whole %.2f GB of weights per token, "
        "so the bandwidth ceiling is %.1f tok/s; drafter-off measures %.1f "
        "tok/s, %.0f%% of it, which is bandwidth-bound. Drafter-on measures "
        "%.2f tok/s at mean accepted length %.2f, and that EXCEEDS the "
        "one-weight-pass-per-token ceiling, so that model cannot explain it: "
        "real traffic is %.0f GB/s, %.0f%% of the roof. The remaining %.1fx is "
        "taken by the 350 W board-power cap%s. Decode measurements %s. "
        "NOT measured: FLOPs (which is "
        "why the axes are in tokens, not FLOP/s), KV-cache and draft-head "
        "memory traffic, the prompt-processing micro-batch size (its intensity "
        "bar spans n_ubatch 512 to n_batch 2048, and only its throughput is "
        "measured), per-request accepted length (the live agentic spread is "
        "placed at the run-mean intensity, so only its vertical extent is "
        "measured), memory junction temperature (NVML exposes none on this "
        "part), and any power other than board power."
        % (PART, bw, compute, model_name, model_gb,
           window_str, drafter_str,
           model_gb, bw / model_gb,
           decode_off, 100 * decode_off / (bw * x_off), decode_on, accept_len,
           decode_on / accept_len * model_gb, 100 * decode_on / roof_on,
           roof_on / decode_on, tail, meas_src))
    return path, cap


# ---------------------------------------------------------------------------
# Figure 2 - what a better draft head would buy
# ---------------------------------------------------------------------------
def _fig_sweep(outdir, pp, clk, fit, model_gb, decode_off, decode_on,
               accept_len, is_iq4xs, meta):
    bw = A.SPEC_BW_GBS
    compute = pp["rate"] if pp is not None else PP_FALLBACK
    Ls = np.linspace(1.0, 6.0, 200)
    xs = Ls / model_gb
    x_off, x_on = 1.0 / model_gb, accept_len / model_gb
    x_max = N_DRAFT_MAX / model_gb

    model_name = A.model_phrase(meta)
    window_str = A.window_phrase(meta)
    drafter_str = A.drafter_phrase(meta)

    if is_iq4xs:
        meas_src = "measured on this arm (UD-IQ4_XS)"
    else:
        meas_src = "measured on UD-IQ4_XS, not this run"

    xlim = (0.0410, 0.820)
    ylim = (25.0, 12000.0)

    fig, ax = plt.subplots(**_FIG)
    _roofs(ax, bw, compute, xlim, model_gb, decode_off,
           compute_in_view=False)
    _frame(ax, xlim, ylim, model_gb)

    ax.plot(xs, fit["f"](Ls), color=CB["on"], lw=2.4, zorder=6,
            label="modelled locus: throughput = L / (T0 + T1 x L)")
    ax.plot(xs, decode_off * Ls, color=CB["grey"], lw=1.5, ls=":", zorder=3,
            label="if speculation were free: %.1f tok/s x L" % decode_off)

    for L in (1, 2, 3, 4, 5, 6):
        x, y = L / model_gb, float(fit["f"](L))
        if L == 1:
            continue
        ax.plot([x], [y], marker="o", ms=8, color="white", mec=CB["on"],
                mew=1.8, ls="none", zorder=8)
        # Label every other L only: consecutive markers are closer together
        # than a two-line label is wide, and the summary box carries the rest.
        if L % 2 == 0:
            ax.annotate("L=%d\n%.0f tok/s" % (L, y), xy=(x, y),
                        xytext=(x * 1.03, y * 0.93), fontsize=8.0,
                        ha="left", va="top", color="#0b3a58",
                        linespacing=1.3, zorder=7)

    ax.plot([x_on], [decode_on], marker="o", ms=12, color=CB["on"],
            mec="black", mew=1.0, ls="none", zorder=9,
            label="MEASURED: L = %.2f gives %.2f tok/s (%s)"
                  % (accept_len, decode_on, meas_src))
    ax.plot([x_off], [decode_off], marker="s", ms=11, color=CB["off"],
            mec="black", mew=1.0, ls="none", zorder=9,
            label="MEASURED: draft head off gives %.1f tok/s (%s)"
                  % (decode_off, meas_src))
    # Both measured labels hang BELOW-LEFT and ABOVE-LEFT of their markers.
    # Anywhere above-right and they would print over the roof (L=1) or over the
    # L=5 and L=6 markers (L=3.55), and hiding the roof on a roofline is the
    # one thing this figure cannot afford.
    ax.annotate("L=1, %.1f tok/s" % decode_off,
                xy=(x_off, decode_off),
                xytext=(x_off * 0.98, decode_off * 0.90), fontsize=8.0,
                ha="right", va="top", color="#7a5400", linespacing=1.3,
                bbox=_BOX, zorder=8)
    ax.annotate("L=%.2f, %.1f tok/s (%s)" % (accept_len,
                                              decode_on, meas_src),
                xy=(x_on, decode_on * 1.05),
                xytext=(x_on * 0.97, decode_on * 1.10), fontsize=8.0,
                ha="right", va="bottom", color="#0b3a58", linespacing=1.3,
                bbox=_BOX, zorder=8,
                arrowprops=dict(arrowstyle="-", color=CB["on"], lw=1.0,
                                shrinkA=1, shrinkB=4))

    ax.axvline(x_max, color=CB["cap"], lw=1.7, ls="-.", alpha=0.9, zorder=4)
    ax.annotate("--spec-draft-n-max = %d, the server's own cap.\n"
                "Nothing to the right of this line is reachable\n"
                "without changing the configuration." % N_DRAFT_MAX,
                xy=(x_max, 780.0), xytext=(0.655, 0.720),
                textcoords=ax.transAxes, fontsize=8.2,
                color=CB["cap"], ha="left", va="top", linespacing=1.4,
                fontweight="bold", bbox=_BOX, zorder=8)

    ax.axhline(fit["asym"], color=CB["compute"], lw=1.6, ls="--", alpha=0.9,
               zorder=4)
    # Placed in AXES FRACTIONS, not data coordinates, so this block, the
    # legend, the cap note and the summary box can be checked against one
    # another without doing log arithmetic. It sits in the wedge above the
    # roof, which is unreachable by construction and therefore always empty.
    ax.text(0.012, 0.338,
            "asymptote 1 / T1 = %.0f tok/s. A PERFECT draft head, accepting "
            "every token it drafts,\nstill stops here: above L of about 3 the "
            "marginal cost per speculated token,\nnot the weight pass, is what "
            "binds." % fit["asym"],
            transform=ax.transAxes, color="#00563f", fontsize=8.2,
            va="bottom", ha="left", linespacing=1.4, bbox=_BOX, zorder=8)

    g4 = float(fit["f"](N_DRAFT_MAX)) / decode_on - 1.0
    g6 = float(fit["f"](6.0)) / decode_on - 1.0
    gi = fit["asym"] / decode_on - 1.0
    ax.text(0.988, 0.988,
            "What a better draft head buys, from today's L = %.2f\n"
            "     L to %d   today's configured cap       %+.0f%%\n"
            "     L to 6   needs n-max raised          %+.0f%%\n"
            "     L to infinity   a perfect draft head       %+.0f%%\n"
            "Acceptance already runs at %.0f%% of the configured cap,\n"
            "so the lever is the cap, not the draft head's quality -\n"
            "and even the cap is worth only %+.0f%%."
            % (accept_len, N_DRAFT_MAX, 100 * g4, 100 * g6, 100 * gi,
               100 * accept_len / N_DRAFT_MAX, 100 * g6),
            transform=ax.transAxes, ha="right", va="top", fontsize=8.0,
            color="#222222", linespacing=1.5, fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.5", fc="#FFF7E6", ec=CB["off"],
                      lw=1.1), zorder=10)

    ax.set_title("Speculation saturates: a better draft head is worth "
                 "%+.0f%%, not %+.0f%%"
                 % (100 * g6, 100 * (6.0 / accept_len - 1.0)),
                 fontsize=13.5, fontweight="bold", pad=26)
    leg = ax.legend(loc="upper left", fontsize=7.4, framealpha=0.95,
                    borderpad=0.6, labelspacing=0.45, handlelength=1.9,
                    bbox_to_anchor=(0.010, 0.990))
    leg.set_zorder(10)

    left = ["CONDITIONS. " + PART + ", fan pinned at 100%.",
            "Workload: agentic coding benchmark, one slot."
            " %s, %.2f GB, %s."
            % (model_name, model_gb, window_str),
            "MODEL, NOT MEASUREMENT. The locus is a two-parameter fit through "
            "exactly two measured points,",
            "  L = 1 and L = %.2f. T0 = %.1f ms is the pass over the weights, "
            "paid once per verification cycle"
            % (accept_len, 1000 * fit["T0"]),
            "  however many tokens ride on it. T1 = %.2f ms is the marginal "
            "cost of each speculated token:" % (1000 * fit["T1"]),
            "  the draft head's own serial pass, the wider verification GEMM, "
            "the extra sampling.",
            "Two points and two parameters leave zero degrees of freedom, so "
            "there is no residual and no",
            "  open marker carries an error bar."]
    if not is_iq4xs:
        left.append("The two measured points (%.1f and %.2f tok/s) are from "
                    "UD-IQ4_XS, not this arm."
                    % (decode_off, decode_on))
    if clk and "swpow" in clk:
        left.append("Every point on this curve is under the same 350 W "
                    "board-power cap, active on %.0f%% of" % clk["swpow"])
        left.append("  non-idle samples. Board power only.")

    right = _not_measured([
        "  - any accepted length but L = 1 and L = %.2f. Every open marker is "
        "interpolation, not data." % accept_len,
        "  - whether raising --spec-draft-n-max would itself change "
        "acceptance. The sweep assumes not.",
        "  - the draft head's own traffic and power. Both are folded into T1 "
        "and cannot be separated.",
        "  - T0 alone implies %.0f GB/s for the weight pass, above the %.0f "
        "GB/s measured at L = 1, because" % (fit["bw_at_T0"],
                                             decode_off * model_gb),
        "    that point also pays T1. The split between them is a model "
        "choice, not an observation."])

    _footer(fig, left, right)

    path = os.path.join(outdir, "roofline-accepted-length-sweep.png")
    fig.savefig(path, facecolor="white")
    plt.close(fig)

    cap = (
        "The same roofline swept over hypothetical mean accepted lengths L = 1 "
        "to 6 on %s, so an architect can read off what a better draft head "
        "buys before it stops helping. Filled markers are the two MEASURED "
        "points (%s): L = 1 at %.1f tok/s and L = %.2f at %.2f tok/s, on "
        "%s (%.2f GB resident), %s, KV "
        "cache q8_0, agentic coding workload, 350 W board-power cap. Open "
        "markers are a two-parameter cost model, throughput = L / (T0 + T1 x "
        "L), fitted through those two points and nothing else: T0 = %.1f ms is "
        "the pass over the weights, paid once per verification cycle however "
        "many tokens ride on it, and T1 = %.2f ms is the marginal cost of each "
        "speculated token (the draft head's own serial pass, the wider "
        "verification GEMM, the extra sampling). Two points and two parameters "
        "leave zero degrees of freedom, so there is no residual and no error "
        "bar: the open markers are an interpolation with a physical shape, not "
        "measurements. Reading: today's L = %.2f already returns %.0f%% of the "
        "1/T1 = %.0f tok/s asymptote, so lifting acceptance to the server's "
        "configured --spec-draft-n-max = %d is worth %+.0f%%, reaching L = 6 "
        "is worth %+.0f%%, and a perfect draft head that accepted every token "
        "it drafted would be worth %+.0f%%. Measured acceptance is already "
        "%.0f%% of the configured cap, so the cap is the lever, not the draft "
        "head's quality - and the cap itself is worth only %+.0f%%. NOT "
        "measured: any accepted length other than 1 and %.2f; whether raising "
        "n-max would itself change acceptance; the draft head's own weight "
        "traffic, power and FLOPs; KV-cache traffic. Board power only - system "
        "and wall power were NOT measured."
        % (PART, meas_src,
           decode_off, accept_len, decode_on, model_name, model_gb,
           window_str,
           1000 * fit["T0"], 1000 * fit["T1"], accept_len,
           100 * decode_on / fit["asym"], fit["asym"], N_DRAFT_MAX,
           100 * g4, 100 * g6, 100 * gi, 100 * accept_len / N_DRAFT_MAX,
           100 * g6, accept_len))
    return path, cap


# ---------------------------------------------------------------------------
def make(ctx, outdir):
    """ctx has keys: tag, run, dmon, slots, host, throttle, requests, exercises,
    meta (any may be None if that source is absent - degrade gracefully, never
    crash). Returns a list of (png_path, caption_string)."""
    ctx = ctx or {}
    try:
        os.makedirs(outdir, exist_ok=True)
    except OSError:
        pass

    meta = ctx.get("meta")

    # ---- Resolve model_gb from this run's own metadata ------------------
    model_gb = meta.get("model_gb") if meta else None
    if model_gb is None:
        print("roofline: model_gb is not recorded for this run. The "
              "roofline's x axis depends on weight traffic (file size), "
              "so neither figure can be placed. Skipping.")
        # Build a degraded placeholder figure that says so
        fig, ax = plt.subplots(**_FIG)
        ax.text(0.5, 0.5,
                "Roofline not drawn: the model file size is not recorded "
                "for this run,\nso the weight-traffic axis cannot be placed.",
                transform=ax.transAxes, ha="center", va="center",
                fontsize=14, color="#AA0000", linespacing=1.6)
        ax.set_xticks([])
        ax.set_yticks([])
        for s in ax.spines.values():
            s.set_visible(False)
        ax.set_title("Roofline: file size not recorded", fontsize=13.5,
                     fontweight="bold")
        path = os.path.join(outdir, "roofline-operating-points.png")
        fig.savefig(path, facecolor="white")
        plt.close(fig)
        cap = ("Roofline not drawn because the model file size is not "
               "recorded for this run. The roofline's x axis is useful "
               "tokens per GB of weight traffic, and without the file "
               "size that axis cannot be placed.")
        return [(path, cap)]

    # ---- Determine which arm this run belongs to -----------------------
    model_label = meta.get("model_label") if meta else None
    is_iq4xs = (model_label == "UD-IQ4_XS")

    # ---- Resolve decode measurements -----------------------------------
    # The three decode constants (decode_off, decode_on, accept_len) were
    # measured on UD-IQ4_XS specifically.  When the current run IS that arm,
    # they are used directly.  When it is not, the run's own accept_len from
    # meta is used if available; decode_off and decode_on remain the IQ4_XS
    # values but the figure and caption say so.
    decode_off = _IQ4XS_DECODE_OFF
    decode_on = _IQ4XS_DECODE_ON
    if is_iq4xs:
        accept_len = _IQ4XS_ACCEPT_LEN
    else:
        # The plotted point must stay a PAIR that was measured TOGETHER.
        # Substituting this run's own accepted length while keeping the other
        # arm's throughput invents a coordinate no run ever produced - the
        # q2kxl report plotted "L = 3.84 at 99.16 tok/s" and labelled it
        # MEASURED, pairing this run's 3.84 with the IQ4_XS arm's 99.16.
        # The borrowed pair travels intact; the run's own accepted length is
        # reported beside it as its own quantity, never spliced into it.
        accept_len = _IQ4XS_ACCEPT_LEN

    slots = ctx.get("slots")
    pp = _pp_throughput(slots)
    spread = _decode_spread(slots)
    clk = _clock_state(ctx.get("dmon"), ctx.get("throttle"))

    # The fitted speculation model is only valid when its two input points
    # (decode_off, decode_on at accept_len) are measurements from THIS arm.
    # When they are borrowed from another arm, the fit is still drawn but
    # the caption says so.
    fit = _fit_speculation(accept_len, decode_off, decode_on, model_gb)

    out = []
    try:
        out.append(_fig_points(outdir, pp, spread, clk, model_gb,
                               decode_off, decode_on, accept_len,
                               is_iq4xs, meta))
    except Exception as exc:                            # pragma: no cover
        print("roofline: operating-point figure not built: %r" % (exc,))
    if fit is None:                                     # pragma: no cover
        print("roofline: accepted-length sweep not built - the two measured "
              "points do not yield a positive-cost model, and drawing a locus "
              "would mean inventing a parameter.")
    else:
        try:
            out.append(_fig_sweep(outdir, pp, clk, fit, model_gb,
                                  decode_off, decode_on, accept_len,
                                  is_iq4xs, meta))
        except Exception as exc:                        # pragma: no cover
            print("roofline: accepted-length sweep not built: %r" % (exc,))
    return out
