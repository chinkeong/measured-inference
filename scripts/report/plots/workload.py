#!/usr/bin/env python3
"""WORKLOAD - the shape of the demand the silicon must serve.

Two figures, both per-request, both reconstructed from the 1 Hz /slots poll:

  1. How much prompt arrives and how much text is generated, side by side, with
     the peak KV footprint (prompt + generated) measured against the context
     window the server was actually started with.
  2. How much of each prompt the KV cache supplied instead of the GPU
     recomputing it, against prompt depth.

CORRECTNESS. Prompt depth is n_prompt_tokens_processed + n_prompt_tokens_cache,
which is what A.requests() returns as "depth". It is NOT the field called
n_prompt_tokens: that one is the slot's current context array, it grows as
tokens are generated, and on a task's first sample it can still hold the
previous occupant's context. This module never touches the raw field.

FLOOR. n_decoded is polled at 1 Hz and the server clears it when the slot goes
idle, so the last reading before a request ends is short by up to one poll
interval of generation. Every generated-token number here is a lower bound, and
the figures say so.

LAYOUT. These figures place every explanatory block OUTSIDE the axes, and set
their margins explicitly. tight_layout() cannot lay out a twinx pair and
silently ignores its rect, which is how a footer ends up printed across the
data.
"""
import os
import textwrap

import numpy as np

import matplotlib
matplotlib.use("Agg")            # REQUIRED - never an interactive backend
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

TITLE = "Workload shape: prompt depth, generated length, KV reuse"

# Okabe-Ito: safe under deuteranopia, protanopia and tritanopia. Nothing in
# this module is distinguished by red against green alone - the two request
# populations differ by marker shape as well as by colour.
_BLUE = "#0072B2"
_ORANGE = "#E69F00"
_GREEN = "#009E73"
_VERM = "#D55E00"
_SKY = "#56B4E9"
_GREY = "#555555"

# The context window the campaign's server was started with (llama-server
# -c 32768 --parallel 1 -fa on -ctk q8_0 -ctv q8_0). Written down rather than
# inferred, so the ceiling drawn on the figure is a stated condition and not a
# magic number; ctx["ctx_tokens"] overrides it for a differently-served run.
_SERVER_CTX_TOKENS = 32768

# Measured decode rate for this part and this build. Used only to turn the 1 Hz
# poll interval into a token count when explaining how short the floor falls.
_DECODE_TOK_S = 99.16

_GRID = dict(alpha=0.3, linewidth=0.7)
_BOX = dict(boxstyle="round,pad=0.4", facecolor="#F7F7F7",
            edgecolor="#CCCCCC", alpha=1.0)


def _ck(ctx, key, default=None):
    """ctx may be a dict or an object; either way this must not raise."""
    if ctx is None:
        return default
    if isinstance(ctx, dict):
        return ctx.get(key, default)
    return getattr(ctx, key, default)


def _reqs(ctx):
    """Per-request records, preferring what the caller already built.

    Falls back to A.requests(slots) so the module works standalone, and returns
    [] rather than raising when neither source is present.
    """
    rs = _ck(ctx, "requests")
    if rs:
        return list(rs)
    slots = _ck(ctx, "slots")
    if slots is None:
        return []
    try:
        import archdata as A
    except ImportError:
        # Standalone use: the caller has not put scripts/report on the path.
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        try:
            import archdata as A
        except ImportError:
            return []
    try:
        return list(A.requests(slots))
    except Exception:
        return []


def _footer(fig, ctx, extra=""):
    """The condition line every figure in this campaign carries, hard-wrapped
    to the figure width so it can never run off the canvas."""
    tag = _ck(ctx, "tag", "?")
    run = _ck(ctx, "run", "?")
    cols = max(60, int(fig.get_figwidth() * 16))
    parts = [
        ("Conditions: RTX 3090, board telemetry only - no system or wall power "
         "is implied. Qwen3.8-27B UD-IQ4_XS on llama-server -c %d --parallel 1 "
         "(single slot, no concurrency), -fa on, KV quantised q8_0, MTP "
         "speculative decoding on." % _SERVER_CTX_TOKENS),
        ("Workload: aider polyglot coding benchmark, agentic edit loop. "
         "Requests reconstructed from a 1 Hz /slots poll. Tag %s, run %s."
         % (tag, run)),
    ]
    if extra:
        parts.append(extra)
    txt = "\n".join(textwrap.fill(p, cols) for p in parts)
    fig.text(0.006, 0.012, txt, fontsize=7.4, va="bottom", ha="left",
             color="#333333", linespacing=1.35)


def _note(fig, ax, y, text, size=7.8):
    """A monospace explanation block, left-aligned under its panel and outside
    the axes, so it can never sit on top of a data point."""
    fig.text(ax.get_position().x0, y, text, va="top", ha="left",
             fontsize=size, family="monospace", linespacing=1.35,
             color="#222222", bbox=_BOX)


def _logbins(v, n=28):
    """Log-spaced bin edges over the positive values of v."""
    lo = max(float(np.min(v)), 1.0)
    hi = float(np.max(v))
    if hi <= lo:
        hi = lo * 2.0
    return np.logspace(np.log10(lo), np.log10(hi), n + 1)


def _ecdf(v):
    xs = np.sort(np.asarray(v, dtype=float))
    ys = np.arange(1, len(xs) + 1) / float(len(xs)) * 100.0
    return xs, ys


def _mark(ax, x, colour, label, y=0.97, ls="-"):
    if not np.isfinite(x) or x <= 0:
        return
    ax.axvline(x, color=colour, linestyle=ls, linewidth=1.8, zorder=5)
    ax.annotate(label, xy=(x, y), xycoords=("data", "axes fraction"),
                xytext=(5, -2), textcoords="offset points",
                ha="left", va="top", fontsize=8.5, color=colour,
                fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.2", facecolor="white",
                          edgecolor="none", alpha=0.85))


# ---------------------------------------------------------------- figure 1

def _fig_request_shape(ctx, rs, outdir):
    depth = np.array([r["depth"] for r in rs], dtype=float)
    dec = np.array([r["ndec"] for r in rs], dtype=float)
    peak = depth + dec
    n = len(rs)

    # A log axis cannot show a zero. A slot polled once at the instant a task
    # was assigned reports nothing; drop it from the axis and say how many.
    dpos, decpos = depth[depth > 0], dec[dec > 0]
    n_dzero, n_deczero = int((depth <= 0).sum()), int((dec <= 0).sum())
    if len(dpos) < 3 or len(decpos) < 3:
        return None

    ratio = depth.sum() / dec.sum() if dec.sum() > 0 else float("nan")
    ceil = float(_ck(ctx, "ctx_tokens", _SERVER_CTX_TOKENS) or
                 _SERVER_CTX_TOKENS)
    p99_peak = float(np.percentile(peak, 99))

    fig = plt.figure(figsize=(12.6, 7.9), dpi=140, facecolor="white")
    gs = GridSpec(1, 2, figure=fig, left=0.055, right=0.945,
                  top=0.885, bottom=0.405, wspace=0.30)
    axL = fig.add_subplot(gs[0, 0])
    axR = fig.add_subplot(gs[0, 1])

    # ---- left: prompt depth, with the peak KV footprint beside it ----
    axL.hist(dpos, bins=_logbins(dpos), color=_BLUE, alpha=0.50,
             edgecolor="white", linewidth=0.5, zorder=2)
    axL.set_xscale("log")
    axL.set_xlabel("prompt depth per request (tokens, log scale)")
    axL.set_ylabel("requests (count)")
    axL.grid(True, which="major", **_GRID)
    axL.set_axisbelow(True)

    eL = axL.twinx()
    xs, ys = _ecdf(dpos)
    eL.step(xs, ys, where="post", color=_BLUE, linewidth=2.2, zorder=6,
            label="prompt depth (histogram + this curve)")
    if int((peak > 0).sum()) >= 3:
        xp, yp = _ecdf(peak[peak > 0])
        eL.step(xp, yp, where="post", color=_ORANGE, linewidth=2.2,
                linestyle="--", zorder=6,
                label="peak KV footprint = prompt + generated")
    eL.set_ylim(0, 103)
    eL.set_ylabel("requests at or below x (%)")

    med_d, p95_d = float(np.median(depth)), float(np.percentile(depth, 95))
    _mark(axL, med_d, _BLUE, "median %.0f tok" % med_d, y=0.985)
    _mark(axL, p95_d, _GREY, "p95 %.0f tok" % p95_d, y=0.885, ls=":")

    # The ceiling is only worth drawing when the workload is anywhere near it.
    if peak.max() > 0.4 * ceil:
        axL.axvline(ceil, color=_VERM, linestyle="-.", linewidth=2.0, zorder=7)
        axL.annotate("server context\nwindow: -c %d" % ceil,
                     xy=(ceil, 0.62), xycoords=("data", "axes fraction"),
                     xytext=(-7, 0), textcoords="offset points",
                     ha="right", va="center", fontsize=8.4, color=_VERM,
                     fontweight="bold",
                     bbox=dict(boxstyle="round,pad=0.25", facecolor="white",
                               edgecolor=_VERM, alpha=0.95))
        axL.set_xlim(right=ceil * 1.55)

    # Legend below the axes: the panel interior belongs to the data.
    eL.legend(loc="upper left", bbox_to_anchor=(0.0, -0.147), ncol=2,
              frameon=False, fontsize=8.3, borderaxespad=0.0,
              handlelength=2.4, columnspacing=1.6)

    axL.set_title("Depth median %.0f tok, p95 %.0f tok - a %.1fx spread"
                  % (med_d, p95_d, p95_d / max(med_d, 1.0)),
                  fontsize=10.8, loc="left", pad=8)

    txtL = ("n = %d requests.  depth = processed + cache-supplied tokens,\n"
            "never the slot's n_prompt_tokens field (that one grows during\n"
            "generation and can hold a previous occupant's context).\n"
            "Peak KV footprint p99 = %.0f tok = %.0f%% of the %d-token window.\n"
            "Deeper than  8192 tok: %d requests (%.1f%%).\n"
            "Deeper than 16384 tok: %d requests (%.1f%%)."
            % (n, p99_peak, 100.0 * p99_peak / ceil, ceil,
               int((depth > 8192).sum()), 100.0 * float((depth > 8192).mean()),
               int((depth > 16384).sum()),
               100.0 * float((depth > 16384).mean())))
    if n_dzero:
        txtL += ("\n%d request(s) reported depth 0 (slot polled once at task\n"
                 "assignment); not shown, a log axis has no zero." % n_dzero)

    # ---- right: generated tokens ----
    axR.hist(decpos, bins=_logbins(decpos), color=_GREEN, alpha=0.50,
             edgecolor="white", linewidth=0.5, zorder=2)
    axR.set_xscale("log")
    axR.set_xlabel("tokens generated per request (log scale)  -  A FLOOR")
    axR.set_ylabel("requests (count)")
    axR.grid(True, which="major", **_GRID)
    axR.set_axisbelow(True)

    eR = axR.twinx()
    xs, ys = _ecdf(decpos)
    eR.step(xs, ys, where="post", color=_GREEN, linewidth=2.2, zorder=6)
    eR.set_ylim(0, 103)
    eR.set_ylabel("requests at or below x (%)")

    med_g, p95_g = float(np.median(dec)), float(np.percentile(dec, 95))
    _mark(axR, med_g, _GREEN, "median >= %.0f tok" % med_g, y=0.985)
    _mark(axR, p95_g, _GREY, "p95 >= %.0f tok" % p95_g, y=0.885, ls=":")

    axR.set_title("Generated median >= %.0f tok, p95 >= %.0f tok"
                  % (med_g, p95_g), fontsize=10.8, loc="left", pad=8)

    txtR = ("A FLOOR, not an exact count. n_decoded is polled at 1 Hz and the\n"
            "server clears it when the slot goes idle, so every request loses\n"
            "its last partial second of generation - up to ~%d tokens at the\n"
            "measured %.2f tok/s. Read each value here as \"at least\".\n"
            "Generated over 1024 tok: %d requests (%.1f%%).\n"
            "Generated over 2048 tok: %d requests (%.1f%%)."
            % (int(round(_DECODE_TOK_S)), _DECODE_TOK_S,
               int((dec > 1024).sum()), 100.0 * float((dec > 1024).mean()),
               int((dec > 2048).sum()), 100.0 * float((dec > 2048).mean())))
    if n_deczero:
        txtR += ("\n%d request(s) showed 0 generated tokens in every poll;\n"
                 "not shown, a log axis has no zero." % n_deczero)

    _note(fig, axL, 0.292, txtL)
    _note(fig, axR, 0.292, txtR)

    # The denominator of this ratio is a FLOOR (n_decoded is polled at 1 Hz
    # and cleared when a slot idles), so the ratio itself is a ceiling. Said
    # on the title rather than only in the right-hand panel note.
    fig.suptitle("Prefill dominates this agentic workload: at most %.1f "
                 "prompt tokens arrive for every token generated"
                 % ratio,
                 fontsize=13.5, fontweight="bold", y=0.968)

    _footer(fig, ctx,
            "Not measured: KV bytes per token - this harness does not read the "
            "model's layer and head geometry, so a token count is not "
            "converted to megabytes here (K and V are q8_0). A request shorter "
            "than one poll interval cannot appear at all, so the request count "
            "is itself a floor.")

    path = os.path.join(outdir, "workload-request-shape.png")
    fig.savefig(path, dpi=140, facecolor="white")
    plt.close(fig)

    cap = ("Per-request demand over %d requests of the aider polyglot agentic "
           "coding loop, on one RTX 3090 running Qwen3.8-27B UD-IQ4_XS. "
           "Left: prompt depth (processed + cache-supplied tokens), median %.0f "
           "and p95 %.0f tokens, with the peak KV footprint (prompt + "
           "generated) as the dashed curve; the p99 footprint of %.0f tokens is "
           "%.0f%% of the %d-token window the server was started with, so this "
           "workload runs close to the configured wall. Right: generated "
           "tokens, median at least %.0f and p95 at least %.0f. Prompt tokens "
           "outnumber generated tokens %.1f to 1. Generated counts are a floor "
           "- the 1 Hz /slots poll loses the last partial second of every "
           "request. Single slot (--parallel 1), so no concurrency appears in "
           "this distribution. Board telemetry only; no system or wall power is "
           "implied. KV bytes per token were not computed: layer and head "
           "geometry is not measured by this harness."
           % (n, med_d, p95_d, p99_peak, 100.0 * p99_peak / ceil, ceil,
              med_g, p95_g, ratio))
    return path, cap


# ---------------------------------------------------------------- figure 2

def _fig_kv_reuse(ctx, rs, outdir):
    depth = np.array([r["depth"] for r in rs], dtype=float)
    nptc = np.array([r["nptc"] for r in rs], dtype=float)
    frac = np.array([r["cache_frac"] for r in rs], dtype=float) * 100.0

    ok = depth > 0
    if int(ok.sum()) < 3:
        return None
    d, f, c = depth[ok], frac[ok], nptc[ok]

    tokw = 100.0 * nptc.sum() / depth.sum() if depth.sum() > 0 else 0.0
    cold = f <= 0.0
    n_cold, n_tot = int(cold.sum()), len(f)

    fig = plt.figure(figsize=(11.6, 7.4), dpi=140, facecolor="white")
    gs = GridSpec(1, 2, figure=fig, left=0.075, right=0.955,
                  top=0.885, bottom=0.410, width_ratios=[4.2, 1.0],
                  wspace=0.05)
    ax = fig.add_subplot(gs[0, 0])
    axm = fig.add_subplot(gs[0, 1], sharey=ax)

    # Cold and warm are split by marker shape as well as by colour, so the
    # distinction survives greyscale printing and any colour vision deficiency.
    ax.scatter(d[cold], f[cold], s=34, marker="x", linewidths=1.3,
               color=_VERM, alpha=0.75, zorder=4,
               label="cold prompt: cache supplied nothing (n=%d)" % n_cold)
    ax.scatter(d[~cold], f[~cold], s=40, marker="o", color=_BLUE, alpha=0.60,
               edgecolors="white", linewidths=0.5, zorder=5,
               label="warm prompt: cache supplied part (n=%d)"
                     % int((~cold).sum()))

    # Token-weighted reuse per depth band. A per-request mean would let a
    # 700-token prompt count as much as a 30k one; the architect sizes for
    # tokens, so the band value is weighted by tokens.
    edges = np.array([0, 1024, 2048, 4096, 8192, 16384, 32768, 1e9])
    bx, by, bn = [], [], []
    for i in range(len(edges) - 1):
        m = (d >= edges[i]) & (d < edges[i + 1])
        if int(m.sum()) < 5:
            continue
        lo = max(float(edges[i]), float(d[m].min()), 1.0)
        hi = max(min(float(edges[i + 1]), float(d[m].max())), lo * 1.01)
        bx.append(float(np.sqrt(lo * hi)))
        by.append(100.0 * c[m].sum() / max(d[m].sum(), 1.0))
        bn.append(int(m.sum()))
    if bx:
        ax.plot(bx, by, color=_GREEN, linewidth=2.6, marker="D",
                markersize=8, markeredgecolor="white", zorder=7,
                label="token-weighted reuse per depth band")
        # Adjacent bands can land at nearly the same height (two bands both
        # near 17% here). Staggering the offset keeps their labels apart
        # whatever the data does.
        for k, (x, y, nb) in enumerate(zip(bx, by, bn)):
            ax.annotate("%.0f%%  n=%d" % (y, nb), xy=(x, y),
                        xytext=(0, 13 if k % 2 == 0 else 28),
                        textcoords="offset points",
                        ha="center", va="bottom", fontsize=7.8,
                        color=_GREEN, fontweight="bold",
                        bbox=dict(boxstyle="round,pad=0.15",
                                  facecolor="white", edgecolor="none",
                                  alpha=0.85))

    ax.axhline(tokw, color=_GREY, linestyle="--", linewidth=1.6, zorder=3)
    ax.annotate("whole run, token-weighted: %.1f%%" % tokw,
                xy=(0.995, tokw), xycoords=("axes fraction", "data"),
                xytext=(0, 6), textcoords="offset points", ha="right",
                fontsize=8.6, color=_GREY, fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.2", facecolor="white",
                          edgecolor="none", alpha=0.85))

    ax.set_xscale("log")
    ax.set_xlim(max(float(d.min()) * 0.72, 1.0), float(d.max()) * 1.5)
    ax.set_ylim(-5, 108)
    ax.set_xlabel("prompt depth per request (tokens, log scale)")
    ax.set_ylabel("share of the prompt supplied by the KV cache (%)")
    ax.grid(True, which="major", **_GRID)
    ax.set_axisbelow(True)
    ax.legend(loc="upper left", bbox_to_anchor=(0.0, -0.152), ncol=3,
              frameon=False, fontsize=8.2, borderaxespad=0.0,
              handlelength=1.8, columnspacing=1.4)

    ax.set_title("Reuse is not a function of depth: deep prompts are not the "
                 "warm ones", fontsize=10.8, loc="left", pad=8)

    # Marginal: half the points sit exactly on zero and would overplot into a
    # meaningless line. This marginal is what makes that spike readable.
    counts, _, _ = axm.hist(f, bins=np.linspace(0, 100, 21),
                            orientation="horizontal", color=_SKY,
                            edgecolor="white", linewidth=0.5, zorder=2)
    axm.set_xlabel("requests (count)", fontsize=9)
    axm.grid(True, axis="x", **_GRID)
    axm.set_axisbelow(True)
    axm.tick_params(labelleft=False)
    axm.set_title("how reuse is\ndistributed", fontsize=9.2, loc="center",
                  pad=8)
    if len(counts):
        axm.annotate("%d requests in the\nbottom bin (0-5%%)" % int(counts[0]),
                     xy=(counts[0], 2.5), xytext=(-6, 24),
                     textcoords="offset points", ha="right", va="bottom",
                     fontsize=7.8, color="#1a6a99", fontweight="bold")

    fig.suptitle("Half the prompts arrive cold, yet the KV cache still spares "
                 "the GPU %.0f%% of all prompt tokens" % tokw,
                 fontsize=13.5, fontweight="bold", y=0.968)

    txt = ("Of %d prompt tokens the cache supplied %d (%.1f%%); the GPU "
           "recomputed the other %d.\n"
           "%d of %d requests (%.1f%%) reused nothing at all, so the median "
           "request reuses %.1f%% while the\n"
           "token-weighted figure for the run is %.1f%%. Size the cache for "
           "the tokens, not for the median request.\n"
           "The band markers show the same quantity within a depth band: it "
           "rises, collapses and rises again,\n"
           "so prompt depth on its own does not predict whether a prompt will "
           "hit in cache."
           % (int(depth.sum()), int(nptc.sum()), tokw,
              int(depth.sum() - nptc.sum()), n_cold, n_tot,
              100.0 * n_cold / n_tot, float(np.median(f)), tokw))
    _note(fig, ax, 0.305, txt)

    _footer(fig, ctx,
            "Reuse is the server's own n_prompt_tokens_cache divided by depth "
            "= processed + cache. Not measured: cache evictions, reuse across "
            "the single slot's task boundaries, and the bytes a cached token "
            "occupies (K and V are q8_0, but this harness does not read layer "
            "and head geometry, so no megabyte figure is offered).")

    path = os.path.join(outdir, "workload-kv-reuse.png")
    fig.savefig(path, dpi=140, facecolor="white")
    plt.close(fig)

    cap = ("KV cache reuse per request, %d requests of the aider polyglot "
           "agentic coding loop on one RTX 3090 running Qwen3.8-27B UD-IQ4_XS "
           "with a single slot (--parallel 1) and q8_0-quantised K and V. Each "
           "point is one request: prompt depth against the share of that prompt "
           "the server reported as cache-supplied. Across the run the cache "
           "supplied %.1f%% of all %d prompt tokens, but %.1f%% of requests "
           "reused nothing at all and the median request reused only %.1f%%, so "
           "a per-request average would badly understate the hardware benefit "
           "- the green markers give token-weighted reuse inside each depth "
           "band. Reuse does not increase with depth: it rises, collapses in "
           "the 4k-8k band and rises again, so depth alone does not predict a "
           "cache hit. Cache evictions and the byte size of a cached token were "
           "not measured. Board telemetry only; no system or wall power is "
           "implied."
           % (n_tot, tokw, int(depth.sum()), 100.0 * n_cold / n_tot,
              float(np.median(f))))
    return path, cap


# ---------------------------------------------------------------- entry

def make(ctx, outdir):
    """ctx has keys: tag, run, dmon, slots, host, throttle, requests, exercises
    (any may be None if that source is absent - degrade gracefully, never
    crash). Returns a list of (png_path, caption_string).

    This module needs only the /slots trace. With no slots and no prebuilt
    request list it returns an empty list rather than an empty chart.
    """
    try:
        os.makedirs(outdir, exist_ok=True)
    except OSError:
        return []

    rs = _reqs(ctx)
    if len(rs) < 3:
        return []

    out = []
    for fn in (_fig_request_shape, _fig_kv_reuse):
        try:
            r = fn(ctx, rs, outdir)
        except Exception:
            r = None
        if r:
            out.append(r)
    return out
