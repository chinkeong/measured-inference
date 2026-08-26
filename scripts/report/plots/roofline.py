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
"""
import os

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

# Qwen3.8-27B-UD-IQ4_XS.gguf, size on disk (14,252,845,984 bytes), in decimal
# GB to match SPEC_BW_GBS, which is also decimal (19.5 Gbps x 384 bit / 8).
MODEL_GB = 14.2528

ACCEPT_LEN = 3.55        # mean accepted length, MTP draft head, this workload
DECODE_ON = 99.16        # tokens/s, draft head on
DECODE_OFF = 45.2        # tokens/s, draft head off, a separate measurement

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

_FIG = dict(figsize=(10, 6.5), dpi=140, facecolor="white")
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

    This is the SAME quantity as DECODE_ON but over a different workload: a
    live agentic benchmark whose prompts, and therefore whose draft acceptance,
    vary from request to request. It is drawn as a spread rather than a point
    because it is one.
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
        if busy.sum() > 10 and np.isfinite(dmon["pwr"][busy]).any():
            out["pwr"] = float(np.nanmean(dmon["pwr"][busy]))
            out["pwr_cv"] = float(np.nanstd(dmon["pwr"][busy])
                                  / np.nanmean(dmon["pwr"][busy]))
            out["mclk"] = float(np.nanmedian(dmon["mclk"][busy]))
            out["pclk"] = float(np.nanmedian(dmon["pclk"][busy]))
            out["gtemp"] = float(np.nanmedian(dmon["gtemp"][busy]))
            out["nbusy"] = int(busy.sum())
    if throttle is not None and len(throttle.get("t", ())) > 10:
        _, lab = A.throttle_series(throttle)
        act = [l for l in lab if l not in ("Idle", "no data")]
        if act:
            out["swpow"] = 100.0 * act.count("SW power cap") / len(act)
            out["swthm"] = 100.0 * act.count("SW thermal") / len(act)
            out["nact"] = len(act)
    return out or None


def _fit_speculation():
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
    m = np.array([[1.0, 1.0], [1.0, ACCEPT_LEN]])
    b = np.array([1.0 / DECODE_OFF, ACCEPT_LEN / DECODE_ON])
    try:
        t0, t1 = np.linalg.solve(m, b)
    except np.linalg.LinAlgError:
        return None
    if not (t0 > 0 and t1 > 0):
        return None
    return {"T0": float(t0), "T1": float(t1), "asym": float(1.0 / t1),
            "bw_at_T0": float(MODEL_GB / t0),
            "f": lambda L: (np.asarray(L, dtype=float)
                            / (t0 + t1 * np.asarray(L, dtype=float)))}


# ---------------------------------------------------------------------------
# Shared furniture
# ---------------------------------------------------------------------------
def _roofs(ax, bw, compute, xlim, compute_in_view=True):
    """The roof itself, plus the bandwidth a real controller actually gave."""
    xs = np.logspace(np.log10(xlim[0]), np.log10(xlim[1]), 400)
    roof = np.minimum(bw * xs, compute)
    ach = DECODE_OFF * MODEL_GB
    lab = ("roof: %.0f GB/s spec bandwidth, then %.0f tok/s compute"
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


def _frame(ax, xlim, ylim):
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
                             functions=(lambda x: np.asarray(x) * MODEL_GB,
                                        lambda v: np.asarray(v) / MODEL_GB))
    sec.set_xlabel("tokens committed per pass over the %.2f GB of weights "
                   "(tokens/pass)" % MODEL_GB, fontsize=9.5)
    sec.tick_params(labelsize=8.5)


def _tag(ax, text, xy, xytext, colour, ha="left", va="top", size=8.3,
         weight="normal"):
    ax.annotate(text, xy=xy, xytext=xytext, fontsize=size, color=colour,
                ha=ha, va=va, linespacing=1.35, fontweight=weight,
                bbox=_BOX, zorder=8,
                arrowprops=dict(arrowstyle="-", color=colour, lw=1.0,
                                shrinkA=1, shrinkB=6))


def _footer(fig, left, right, height):
    """Conditions live BELOW the axes, in two columns, so they never sit on
    top of the data. tight_layout is called here, before any inset is added,
    because an inset axes makes tight_layout refuse to run."""
    fig.tight_layout(rect=(0.0, height, 1.0, 1.0))
    y = height - 0.014
    fig.text(0.010, y, "\n".join(left), ha="left", va="top", fontsize=6.9,
             color="#222222", linespacing=1.6)
    fig.text(0.513, y, "\n".join(right), ha="left", va="top", fontsize=6.9,
             color="#444444", linespacing=1.6)
    fig.patches.append(plt.Rectangle(
        (0.006, 0.004), 0.988, height - 0.022, transform=fig.transFigure,
        fc="#FAFAFA", ec="#DDDDDD", lw=0.8, zorder=-5))


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
def _fig_points(outdir, pp, spread, clk):
    bw = A.SPEC_BW_GBS
    x_off = 1.0 / MODEL_GB
    x_on = ACCEPT_LEN / MODEL_GB
    x_pp = UBATCH / MODEL_GB
    x_pp_hi = NBATCH / MODEL_GB

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
    ylim = (16.0, 11000.0)
    roof_on = bw * x_on
    x_ridge = compute / bw

    fig, ax = plt.subplots(**_FIG)
    _roofs(ax, bw, compute, xlim)
    _frame(ax, xlim, ylim)

    # ---- the power-limited gap, drawn at the intensity where it was measured
    ax.vlines(x_on, DECODE_ON, roof_on, color=CB["cap"], lw=11, alpha=0.16,
              zorder=2)
    ax.annotate("", xy=(x_on, roof_on), xytext=(x_on, DECODE_ON),
                arrowprops=dict(arrowstyle="<->", color=CB["cap"], lw=1.7,
                                shrinkA=0, shrinkB=0), zorder=6)
    ax.annotate("%.1fx of the bandwidth roof is left unused here.\n"
                "The binding limit at this point is the 350 W\n"
                "board-power cap, not memory bandwidth."
                % (roof_on / DECODE_ON),
                xy=(x_on * 1.06, np.sqrt(DECODE_ON * roof_on)),
                xytext=(x_on * 2.1, 260.0), fontsize=9.0, color=CB["cap"],
                ha="left", va="top", linespacing=1.4, fontweight="bold",
                bbox=_BOX, zorder=8,
                arrowprops=dict(arrowstyle="-", color=CB["cap"], lw=1.0,
                                shrinkA=1, shrinkB=2))

    # ---- operating points
    ax.plot([x_off], [DECODE_OFF], marker="s", ms=11, color=CB["off"],
            mec="black", mew=0.9, ls="none", zorder=9,
            label="decode, draft head OFF (measured)")
    _tag(ax, "draft head OFF: 1 token per weight pass.\n"
             "%.1f tok/s = %.0f GB/s = %.0f%% of the roof.\n"
             "For practical purposes this point IS the roof."
             % (DECODE_OFF, DECODE_OFF * MODEL_GB,
                100 * DECODE_OFF / (bw * x_off)),
         (x_off * 0.97, DECODE_OFF * 1.06), (0.0235, 2400.0),
         "#7a5400", ha="left")

    if spread is not None:
        ax.vlines(x_on * 0.80, spread["p10"], spread["p90"],
                  color=CB["spread"], lw=7, alpha=0.65, zorder=5,
                  label="live agentic run, p10 to p90 spread")
        ax.plot([x_on * 0.80], [spread["agg"]], marker="_", ms=16,
                color="#12587f", mew=2.6, ls="none", zorder=6)

    ax.plot([x_on], [DECODE_ON], marker="o", ms=12, color=CB["on"],
            mec="black", mew=0.9, ls="none", zorder=9,
            label="decode, MTP draft head ON (measured)")
    _tag(ax, "draft head ON: %.2f tokens / weight pass\n"
             "%.2f tok/s BEATS the %.1f tok/s one-pass-per-token ceiling,\n"
             "so traffic is only %.0f GB/s = %.0f%% of the roof"
             % (ACCEPT_LEN, DECODE_ON, bw / MODEL_GB,
                DECODE_ON / ACCEPT_LEN * MODEL_GB, 100 * DECODE_ON / roof_on),
         (x_on, DECODE_ON * 0.93), (x_on * 0.90, DECODE_ON * 0.60),
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
             "intensity - this phase is compute-bound, not memory-bound.\n"
             "Bar spans n_ubatch 512 to n_batch 2048: the micro-batch\n"
             "was NOT logged, so only the throughput is measured."
             % (compute, bw * x_pp / compute),
         (x_pp * 0.98, compute * 1.12), (x_pp * 0.46, 8600.0), "#5c2c48",
         ha="right")

    # ---- ridge point
    ax.plot([x_ridge], [compute], marker="*", ms=16, color=CB["compute"],
            mec="black", mew=0.7, ls="none", zorder=9,
            label="ridge point: compute takes over from bandwidth")
    _tag(ax, "ridge point: %.0f tokens per weight pass.\n"
             "Everything left of here is memory-bound.\nMTP delivers %.2f."
             % (x_ridge * MODEL_GB, ACCEPT_LEN),
         (x_ridge, compute * 0.90), (x_ridge * 1.5, compute * 0.62),
         "#00563f", ha="left")

    ax.text(0.022, 0.985, "above the roof: physically unreachable",
            transform=ax.transAxes, fontsize=7.8, color="#9A9A9A",
            style="italic", ha="left", va="top", zorder=3)

    ax.set_title("Speculation moves decode off the bandwidth roof and onto "
                 "the power limit", fontsize=13.5, fontweight="bold", pad=26)
    leg = ax.legend(loc="lower right", fontsize=7.5, framealpha=0.95,
                    borderpad=0.6, labelspacing=0.45, handlelength=1.9,
                    bbox_to_anchor=(0.997, 0.015))
    leg.set_zorder(10)

    left = ["CONDITIONS. " + PART + ", fan pinned at 100%.",
            "Workload: agentic coding benchmark, one slot. "
            "Qwen3.8-27B-UD-IQ4_XS, %.2f GB of weights." % MODEL_GB,
            "Server flags, read from the live process: -c 32768, "
            "--parallel 1, -fa on, -ctk q8_0, -ctv q8_0,",
            "  --spec-type draft-mtp, --spec-draft-n-max %d, "
            "--spec-draft-p-min 0.75." % N_DRAFT_MAX]
    if clk and "pwr" in clk:
        left.append("Board power %.0f W mean over %d busy samples, "
                    "coefficient of variation %.0f%% (the standard"
                    % (clk["pwr"], clk["nbusy"], 100 * clk["pwr_cv"]))
        left.append("  deviation as a percentage of the mean). GPU die "
                    "%.0f C median." % clk["gtemp"])
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

    _footer(fig, left, right, 0.298)
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
        "bandwidth-bound. Workload: Qwen3.8-27B-UD-IQ4_XS (%.2f GB resident) "
        "on an agentic coding benchmark, 32768-token context, one slot, flash "
        "attention on, KV cache q8_0, MTP draft head with n_max=%d. The "
        "finding: plain decode moves the whole %.2f GB of weights per token, "
        "so the bandwidth ceiling is %.1f tok/s; drafter-off measures %.1f "
        "tok/s, %.0f%% of it, which is bandwidth-bound. Drafter-on measures "
        "%.2f tok/s at mean accepted length %.2f, and that EXCEEDS the "
        "one-weight-pass-per-token ceiling, so that model cannot explain it: "
        "real traffic is %.0f GB/s, %.0f%% of the roof. The remaining %.1fx is "
        "taken by the 350 W board-power cap%s. NOT measured: FLOPs (which is "
        "why the axes are in tokens, not FLOP/s), KV-cache and draft-head "
        "memory traffic, the prompt-processing micro-batch size (its intensity "
        "bar spans n_ubatch 512 to n_batch 2048, and only its throughput is "
        "measured), per-request accepted length (the live agentic spread is "
        "placed at the run-mean intensity, so only its vertical extent is "
        "measured), memory junction temperature (NVML exposes none on this "
        "part), and any power other than board power."
        % (PART, bw, compute, MODEL_GB, N_DRAFT_MAX, MODEL_GB, bw / MODEL_GB,
           DECODE_OFF, 100 * DECODE_OFF / (bw * x_off), DECODE_ON, ACCEPT_LEN,
           DECODE_ON / ACCEPT_LEN * MODEL_GB, 100 * DECODE_ON / roof_on,
           roof_on / DECODE_ON, tail))
    return path, cap


# ---------------------------------------------------------------------------
# Figure 2 - what a better draft head would buy
# ---------------------------------------------------------------------------
def _fig_sweep(outdir, pp, clk, fit):
    bw = A.SPEC_BW_GBS
    compute = pp["rate"] if pp is not None else PP_FALLBACK
    Ls = np.linspace(1.0, 6.0, 200)
    xs = Ls / MODEL_GB
    x_off, x_on = 1.0 / MODEL_GB, ACCEPT_LEN / MODEL_GB
    x_max = N_DRAFT_MAX / MODEL_GB

    xlim = (0.0410, 0.820)
    ylim = (25.0, 3000.0)

    fig, ax = plt.subplots(**_FIG)
    _roofs(ax, bw, compute, xlim, compute_in_view=False)
    _frame(ax, xlim, ylim)

    ax.plot(xs, fit["f"](Ls), color=CB["on"], lw=2.4, zorder=6,
            label="modelled locus: throughput = L / (T0 + T1 x L)")
    ax.plot(xs, DECODE_OFF * Ls, color=CB["grey"], lw=1.5, ls=":", zorder=3,
            label="if speculation were free: %.1f tok/s x L" % DECODE_OFF)

    for L in (1, 2, 3, 4, 5, 6):
        x, y = L / MODEL_GB, float(fit["f"](L))
        if L == 1:
            continue
        ax.plot([x], [y], marker="o", ms=8, color="white", mec=CB["on"],
                mew=1.8, ls="none", zorder=8)
        ax.annotate("L=%d\n%.0f tok/s" % (L, y), xy=(x, y),
                    xytext=(x * 1.035, y * 1.05), fontsize=8.0, ha="left",
                    va="bottom", color="#0b3a58", linespacing=1.3, zorder=7)

    ax.plot([x_on], [DECODE_ON], marker="o", ms=12, color=CB["on"],
            mec="black", mew=1.0, ls="none", zorder=9,
            label="MEASURED: L = %.2f gives %.2f tok/s (today)"
                  % (ACCEPT_LEN, DECODE_ON))
    ax.plot([x_off], [DECODE_OFF], marker="s", ms=11, color=CB["off"],
            mec="black", mew=1.0, ls="none", zorder=9,
            label="MEASURED: draft head off gives %.1f tok/s" % DECODE_OFF)
    ax.annotate("L=1, %.1f tok/s\nMEASURED" % DECODE_OFF,
                xy=(x_off, DECODE_OFF),
                xytext=(x_off * 0.93, DECODE_OFF * 0.97), fontsize=8.0,
                ha="right", va="top", color="#7a5400", linespacing=1.3,
                bbox=_BOX, zorder=8)
    ax.annotate("L=%.2f, %.1f tok/s\nMEASURED (today)" % (ACCEPT_LEN,
                                                          DECODE_ON),
                xy=(x_on, DECODE_ON * 0.94),
                xytext=(x_on * 0.90, DECODE_ON * 0.66), fontsize=8.0,
                ha="right", va="top", color="#0b3a58", linespacing=1.3,
                bbox=_BOX, zorder=8,
                arrowprops=dict(arrowstyle="-", color=CB["on"], lw=1.0,
                                shrinkA=1, shrinkB=4))

    ax.axvline(x_max, color=CB["cap"], lw=1.7, ls="-.", alpha=0.9, zorder=4)
    ax.annotate("--spec-draft-n-max = %d, the server's own cap.\n"
                "Nothing to the right of this line is reachable\n"
                "without changing the configuration." % N_DRAFT_MAX,
                xy=(x_max, 44.0), xytext=(x_max * 1.05, 47.0), fontsize=8.2,
                color=CB["cap"], ha="left", va="top", linespacing=1.4,
                fontweight="bold", bbox=_BOX, zorder=8)

    ax.axhline(fit["asym"], color=CB["compute"], lw=1.6, ls="--", alpha=0.9,
               zorder=4)
    ax.text(xlim[0] * 1.04, fit["asym"] * 1.09,
            "asymptote 1 / T1 = %.0f tok/s. A PERFECT draft head, accepting "
            "every token it drafts,\nstill stops here: above L of about 3 the "
            "marginal cost per speculated token,\nnot the weight pass, is what "
            "binds." % fit["asym"],
            color="#00563f", fontsize=8.2, va="bottom", ha="left",
            linespacing=1.4, bbox=_BOX, zorder=8)

    g4 = float(fit["f"](N_DRAFT_MAX)) / DECODE_ON - 1.0
    g6 = float(fit["f"](6.0)) / DECODE_ON - 1.0
    gi = fit["asym"] / DECODE_ON - 1.0
    ax.text(0.986, 0.978,
            "What a better draft head buys, from today's L = %.2f\n"
            "     L to %d   today's configured cap       %+.0f%%\n"
            "     L to 6   needs n-max raised          %+.0f%%\n"
            "     L to infinity   a perfect draft head       %+.0f%%\n"
            "Acceptance already runs at %.0f%% of the configured cap,\n"
            "so the lever is the cap, not the draft head's quality -\n"
            "and even the cap is worth only %+.0f%%."
            % (ACCEPT_LEN, N_DRAFT_MAX, 100 * g4, 100 * g6, 100 * gi,
               100 * ACCEPT_LEN / N_DRAFT_MAX, 100 * g6),
            transform=ax.transAxes, ha="right", va="top", fontsize=8.3,
            color="#222222", linespacing=1.55, fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.5", fc="#FFF7E6", ec=CB["off"],
                      lw=1.1), zorder=10)

    ax.set_title("Speculation saturates: a better draft head is worth "
                 "%+.0f%%, not %+.0f%%"
                 % (100 * g6, 100 * (6.0 / ACCEPT_LEN - 1.0)),
                 fontsize=13.5, fontweight="bold", pad=26)
    leg = ax.legend(loc="upper left", fontsize=7.4, framealpha=0.95,
                    borderpad=0.6, labelspacing=0.45, handlelength=1.9,
                    bbox_to_anchor=(0.010, 0.990))
    leg.set_zorder(10)

    left = ["CONDITIONS. " + PART + ", fan pinned at 100%.",
            "Workload: agentic coding benchmark, one slot. "
            "Qwen3.8-27B-UD-IQ4_XS, %.2f GB, KV cache q8_0, -c 32768."
            % MODEL_GB,
            "MODEL, NOT MEASUREMENT. The locus is a two-parameter fit through "
            "exactly two measured points,",
            "  L = 1 and L = %.2f. T0 = %.1f ms is the pass over the weights, "
            "paid once per verification cycle"
            % (ACCEPT_LEN, 1000 * fit["T0"]),
            "  however many tokens ride on it. T1 = %.2f ms is the marginal "
            "cost of each speculated token:" % (1000 * fit["T1"]),
            "  the draft head's own serial pass, the wider verification GEMM, "
            "the extra sampling.",
            "Two points and two parameters leave zero degrees of freedom, so "
            "there is no residual and no",
            "  open marker carries an error bar."]
    if clk and "swpow" in clk:
        left.append("Every point on this curve is under the same 350 W "
                    "board-power cap, active on %.0f%% of" % clk["swpow"])
        left.append("  non-idle samples. Board power only.")

    right = _not_measured([
        "  - any accepted length but L = 1 and L = %.2f. Every open marker is "
        "interpolation, not data." % ACCEPT_LEN,
        "  - whether raising --spec-draft-n-max would itself change "
        "acceptance. The sweep assumes not.",
        "  - the draft head's own traffic and power. Both are folded into T1 "
        "and cannot be separated.",
        "  - T0 alone implies %.0f GB/s for the weight pass, above the %.0f "
        "GB/s measured at L = 1, because" % (fit["bw_at_T0"],
                                             DECODE_OFF * MODEL_GB),
        "    that point also pays T1. The split between them is a model "
        "choice, not an observation."])

    _footer(fig, left, right, 0.278)

    path = os.path.join(outdir, "roofline-accepted-length-sweep.png")
    fig.savefig(path, facecolor="white")
    plt.close(fig)

    cap = (
        "The same roofline swept over hypothetical mean accepted lengths L = 1 "
        "to 6 on %s, so an architect can read off what a better draft head "
        "buys before it stops helping. Filled markers are the two MEASURED "
        "points: L = 1 at %.1f tok/s and L = %.2f at %.2f tok/s, on "
        "Qwen3.8-27B-UD-IQ4_XS (%.2f GB resident), 32768-token context, KV "
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
        % (PART, DECODE_OFF, ACCEPT_LEN, DECODE_ON, MODEL_GB,
           1000 * fit["T0"], 1000 * fit["T1"], ACCEPT_LEN,
           100 * DECODE_ON / fit["asym"], fit["asym"], N_DRAFT_MAX,
           100 * g4, 100 * g6, 100 * gi, 100 * ACCEPT_LEN / N_DRAFT_MAX,
           100 * g6, ACCEPT_LEN))
    return path, cap


# ---------------------------------------------------------------------------
def make(ctx, outdir):
    """ctx has keys: tag, run, dmon, slots, host, throttle, requests, exercises
    (any may be None if that source is absent - degrade gracefully, never
    crash). Returns a list of (png_path, caption_string)."""
    ctx = ctx or {}
    try:
        os.makedirs(outdir, exist_ok=True)
    except OSError:
        pass

    slots = ctx.get("slots")
    pp = _pp_throughput(slots)
    spread = _decode_spread(slots)
    clk = _clock_state(ctx.get("dmon"), ctx.get("throttle"))
    fit = _fit_speculation()

    out = []
    try:
        out.append(_fig_points(outdir, pp, spread, clk))
    except Exception as exc:                            # pragma: no cover
        print("roofline: operating-point figure not built: %r" % (exc,))
    if fit is None:                                     # pragma: no cover
        print("roofline: accepted-length sweep not built - the two measured "
              "points do not yield a positive-cost model, and drawing a locus "
              "would mean inventing a parameter.")
    else:
        try:
            out.append(_fig_sweep(outdir, pp, clk, fit))
        except Exception as exc:                        # pragma: no cover
            print("roofline: accepted-length sweep not built: %r" % (exc,))
    return out
