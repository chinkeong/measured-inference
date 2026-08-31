#!/usr/bin/env python3
"""Memory capacity, and the two paths that turn out not to be constraints.

THE ARGUMENT THIS MODULE MAKES, in the order the figures make it:

  1. VRAM is a DESIGN-TIME commitment. The resident footprint is set at load
     and then does not move - a few tens of MiB of drift across the whole
     run. A board ceiling is therefore not a budget you manage, it is a gate
     you pass or fail before the first token. That is why this campaign owns
     a nine-file quantisation ladder and not a scheduler.

  2. The interconnect is EMPTY, and it is empty BECAUSE capacity was
     sufficient. Weights that are resident are not streamed. The PCIe panel
     is a deliberate null result: it is plotted at the scale of the link's
     own capability so that the emptiness is visible, and so that nobody
     spends silicon area or power widening a bus this workload does not use.

  3. Host storage is null FOR THE INFERENCE PATH, and this module shows that
     the non-null remainder belongs to somebody else. That separation is the
     honest version of the claim, and it is stronger than the claim.

Every number on every figure carries its condition. Nothing here is inferred
from a specification sheet except the lines LABELLED [SPEC]: the board's
physical ceiling and the link's theoretical rate.
"""
import os
import sys
import textwrap

import matplotlib
matplotlib.use("Agg")            # REQUIRED - never an interactive backend
import matplotlib.pyplot as plt
import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.dirname(_HERE) not in sys.path:
    sys.path.insert(0, os.path.dirname(_HERE))
import archdata as A                                    # noqa: E402

# NumPy 2.0 RENAMED np.trapz to np.trapezoid and DELETED the old spelling.
# requirements.txt asks for `numpy>=1.24` with no upper bound, and on this box
# that resolves to numpy 2.5.2 and to nothing else: no numpy 1.x publishes a
# cp314 wheel, so Python 3.14 cannot install a version that still has np.trapz.
# Measured 2026-08-31, Ubuntu 26.04.1 / python 3.14.4 / numpy 2.5.2 -
# `np.trapz([1.,2.],[0.,1.])` raises AttributeError, `hasattr(np,"trapezoid")`
# is True. The author's own venv predated the rename, so PANEL 3's two
# integrated byte totals were computed there and have been uncomputable on
# every fresh install since.
#
# It failed INVISIBLY, which is the part that matters. make()'s "never take a
# run down" except at the foot of this file caught the AttributeError, so
# build-report.py printed "[ ok ] capacity 1 figure(s)", counted 0 failures,
# and published a report from which capacity-null-interconnect.png was simply
# absent - not even listed under "Figures that could not be built", because
# nothing had raised as far as the driver could see. A reader got a shorter
# report that read exactly like a complete one, which is rule 2 broken by an
# import: no reader may ever measure less than the report promised them.
#
# Bind the name once, here, rather than pinning numpy<2 in requirements.txt.
# That pin is unsatisfiable on cp314 and would convert one missing figure into
# a failed install and a setup.sh that exits non-zero on this machine. The
# getattr order also keeps the Windows reference platform byte-identical: an
# older numpy 1.x venv has no `trapezoid`, falls through to `np.trapz`, and
# calls exactly the function it called before.
_trapz = getattr(np, "trapezoid", None) or np.trapz

TITLE = "Capacity is the constraint; the interconnect is not"

# ---------------------------------------------------------------- constants
# Okabe-Ito, safe under all three common colour-vision deficiencies. No pair
# in this module is distinguished by red-against-green alone.
C_RESIDENT = "#0072B2"     # blue
C_HEAD     = "#BDBDBD"     # grey
C_RX       = "#0072B2"     # blue
C_TX       = "#E69F00"     # orange
C_DISK     = "#0072B2"     # blue
C_PAGE     = "#CC79A7"     # reddish purple
C_SPEC     = "#000000"     # black, for every specification line

# SPECIFICATION, not measurement. Labelled [SPEC] wherever it is drawn.
BOARD_MIB = 24576.0        # RTX 3090 physical VRAM, nvidia-smi memory.total
# PCIe Gen4 x16, one direction: 16 GT/s x 16 lanes x 128b/130b = 31.508 GB/s.
# nvidia-smi reports rxpci/txpci in MB/s, so this is 31,508 MB/s.
LINK_MBS = 31508.0
LINK_NAME = "PCIe Gen4 x16"
WIN_PAGE_B = 4096.0        # Windows page size, for pages/s -> bytes/s

# Measured EARLIER in this campaign, on this same rig and these same files.
# Carried here so the capacity argument is stated in measurements rather than
# in arithmetic; each is labelled with its provenance on the figure.
FULLWIN_IQ4XS_MIB = 23821.0    # UD-IQ4_XS @ -c 262144, drafter OFF, at depth
FULLWIN_Q2KXL_MIB = 22859.0    # UD-Q2_K_XL @ -c 262144, drafter ON, at depth
FULLWIN_Q2KXL_BPW = 2.912      # UD-Q2_K_XL
DESKTOP_FENCE_MIB = 1796.0     # 1,669 MiB desktop worst case, measured
                               # with NO server loaded, + 127 MiB of
                               # load-to-load variation. CORRECTED
                               # 2026-08-27 from 1308.0, which rested on
                               # a 1,181 MiB desktop maximum an audit
                               # showed was read off a board ALREADY
                               # SPILLING - a desktop being evicted, not
                               # one at rest.
LADDER_TOP_BPW = 4.223         # UD-IQ4_XS, the top of the ladder
LADDER_BOT_BPW = 1.835         # UD-IQ1_S, the rung that stops terminating
LADDER_FLOOR_BPW = 2.481       # UD-IQ2_S, smallest rung whose code EXECUTES

GRID = dict(alpha=0.3, linewidth=0.6)
BOX = dict(boxstyle="round,pad=0.5", facecolor="white", edgecolor="#888888",
           linewidth=0.8, alpha=0.96)


# ---------------------------------------------------------------- utilities
def _fin(a):
    """Finite values only, as a float array. Empty array if there are none."""
    if a is None:
        return np.zeros(0)
    a = np.asarray(a, dtype=float)
    return a[np.isfinite(a)]


def _n(x):
    """Thousands-separated integer, or 'n/a' for a missing value."""
    try:
        if x is None or not np.isfinite(x):
            return "n/a"
    except TypeError:
        return "n/a"
    return "{:,.0f}".format(x)


def _origin(dmon, slots, host):
    """One time origin for every panel, so the x axes are comparable."""
    for src in (dmon, slots, host):
        if src is not None and len(src.get("t", [])):
            return float(src["t"][0])
    return 0.0


def _host_offset(host, dmon, slots):
    """The host collector on this rig writes LOCAL-time epoch while the GPU
    and server collectors write UTC epoch, so the two series sit a whole
    number of hours apart. All three are still writing, so the offset is
    recoverable from their last samples.

    Returns (offset_seconds, note); the offset is applied as t_host - offset.
    A residual larger than five minutes means the assumption did not hold,
    and the caller is TOLD so rather than handed a silently wrong axis - the
    same failure mode the dmon column offset causes, one file over.
    """
    ref = dmon if (dmon is not None and len(dmon.get("t", []))) else slots
    if (host is None or ref is None or not len(host.get("t", []))
            or not len(ref.get("t", []))):
        return 0.0, None
    raw = float(host["t"][-1]) - float(ref["t"][-1])
    snapped = round(raw / 3600.0) * 3600.0
    resid = raw - snapped
    if abs(snapped) < 1800.0:
        return 0.0, None
    if abs(resid) > 300.0:
        return 0.0, ("INSTRUMENT WARNING: the host clock offset of %+.0f s did "
                     "not snap to a whole hour (residual %+.0f s), so the host "
                     "panel is drawn on its OWN elapsed axis and is NOT "
                     "sample-aligned with the GPU panel above it."
                     % (raw, resid))
    return snapped, ("Instrument note: the host collector logs local-time "
                     "epoch while the GPU collector logs UTC; the host panel "
                     "is aligned to GPU telemetry by %+.1f h (residual "
                     "%+.0f s)." % (-snapped / 3600.0, resid))


def _footer(fig, text, width=170, size=7.2):
    """The conditions line every figure in this campaign carries, wrapped so
    that it cannot run off the canvas. Returns the bottom rect fraction to
    reserve for it."""
    body = textwrap.fill(text, width=width)
    lines = body.count("\n") + 1
    h = fig.get_size_inches()[1]
    reserve = (lines * (size + 3.2) / 72.0) / h + 0.008
    fig.text(0.5, 0.004, body, ha="center", va="bottom", fontsize=size,
             color="#333333", linespacing=1.3)
    return reserve


def _decorate(ax):
    ax.grid(True, **GRID)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)


def _save(fig, outdir, name):
    os.makedirs(outdir, exist_ok=True)
    p = os.path.join(outdir, name)
    fig.savefig(p, dpi=140, facecolor="white")
    plt.close(fig)
    return p


# ------------------------------------------------------------------ FIGURE 1
def _vram(ctx, outdir, t0, meta=None):
    """VRAM in use against the physical ceiling, with headroom shaded."""
    dmon = ctx.get("dmon")
    if dmon is None or len(_fin(dmon.get("fb"))) < 2:
        return None

    t = np.asarray(dmon["t"], dtype=float)
    fb = np.asarray(dmon["fb"], dtype=float)
    good = np.isfinite(fb)
    tm = (t[good] - t0) / 60.0
    mib = fb[good]
    gib = mib / 1024.0
    ceil_gib = BOARD_MIB / 1024.0

    med = float(np.median(mib))
    lo, hi = float(mib.min()), float(mib.max())
    head = BOARD_MIB - med
    drift_pct = 100.0 * (hi - lo) / med
    mins = float(tm[-1] - tm[0])

    fig, ax = plt.subplots(figsize=(11.5, 7.4))

    # Headroom first, so the resident block sits on top of it.
    ax.fill_between(tm, gib, ceil_gib, color=C_HEAD, alpha=0.40, linewidth=0,
                    label="headroom at this window: %s MiB (%.1f GiB, %.0f%% "
                          "of the board)"
                          % (_n(head), head / 1024.0,
                             100.0 * head / BOARD_MIB))
    ax.fill_between(tm, 0, gib, color=C_RESIDENT, alpha=0.80, linewidth=0,
                    label="resident, dmon fb: median %s MiB (%.2f GiB)"
                          % (_n(med), med / 1024.0))
    ax.plot(tm, gib, color=C_RESIDENT, linewidth=1.0)

    ax.axhline(ceil_gib, color=C_SPEC, linestyle="--", linewidth=1.5,
               label="board physical ceiling %s MiB (%.2f GiB) [SPEC]"
                     % (_n(BOARD_MIB), ceil_gib))
    practical = (BOARD_MIB - DESKTOP_FENCE_MIB) / 1024.0
    ax.axhline(practical, color=C_SPEC, linestyle=":", linewidth=1.3,
               label="practical ceiling with a desktop attached, %s MiB - "
                     "rule-14 reserve measured earlier this campaign"
                     % _n(BOARD_MIB - DESKTOP_FENCE_MIB))

    ax.set_xlim(tm[0], tm[-1])
    ax.set_ylim(0, ceil_gib * 1.10)
    ax.set_xlabel("elapsed time (minutes since GPU telemetry start)")
    ax.set_ylabel("board VRAM in use (GiB)")
    # The drift percentage is stated WITH its denominator. A bare "0.17%" on
    # a figure that also shows a 24,576 MiB ceiling reads as a share of the
    # board, which is a different and much smaller number.
    ax.set_title("24 GiB is a gate, not a budget: the footprint is committed "
                 "at load\nand then moves %.0f MiB across %.0f minutes of "
                 "work - %.2f%% of the %s MiB it holds"
                 % (hi - lo, mins, drift_pct, _n(med)),
                 fontsize=13, fontweight="bold", pad=10)
    _decorate(ax)

    sec = ax.secondary_yaxis(
        "right", functions=(lambda g: g * 1024.0, lambda m: m / 1024.0))
    sec.set_ylabel("board VRAM in use (MiB)")

    # Where the benchmark workload begins, if the server trace says so.
    slots = ctx.get("slots")
    if slots is not None and len(slots.get("t", [])):
        ws = (float(slots["t"][0]) - t0) / 60.0
        if tm[0] < ws < tm[-1]:
            ax.axvline(ws, color="#444444", linewidth=1.1, linestyle="-.")
            ax.annotate("benchmark workload starts here.\nThe weights are "
                        "ALREADY resident:\nthere is no step, and that is\n"
                        "the whole point.",
                        xy=(ws, 18.6), xytext=(ws + 2.0, 18.4),
                        fontsize=7.6, color="#222222", va="top",
                        bbox=dict(boxstyle="round,pad=0.35",
                                  facecolor="white", edgecolor="#AAAAAA",
                                  alpha=0.92))

    # The trace is flat, so prove the instrument is live rather than stuck.
    iax = ax.inset_axes([0.578, 0.745, 0.407, 0.170], zorder=6)
    iax.set_facecolor("white")
    iax.patch.set_alpha(1.0)
    iax.plot(tm, mib, color=C_RESIDENT, linewidth=0.8)
    pad = max(2.0, (hi - lo) * 0.15)
    iax.set_ylim(lo - pad, hi + pad)
    iax.set_xlim(tm[0], tm[-1])
    iax.tick_params(labelsize=6.2, length=2)
    iax.set_ylabel("MiB", fontsize=6.5)
    iax.set_xlabel("minutes", fontsize=6.5, labelpad=1)
    iax.grid(True, alpha=0.3, linewidth=0.5)
    iax.set_title("zoomed to the %.0f MiB of real variation:\nthe instrument "
                  "is live, not stuck" % (hi - lo), fontsize=6.6, pad=3)
    for s in ("top", "right"):
        iax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        iax.spines[s].set_color("#666666")

    # Orient the ladder argument around whichever rung THIS run is.
    _label = meta.get("model_label") if meta else None
    _bpw = meta.get("bpw") if meta else None
    if _label == "UD-Q2_K_XL":
        _this_fullwin = FULLWIN_Q2KXL_MIB
        _this_drafter_note = "WITH speculation"
        _other_label = "UD-IQ4_XS"
        _other_fullwin = FULLWIN_IQ4XS_MIB
        _other_drafter_note = "drafter OFF"
    else:
        # Default / UD-IQ4_XS — the original orientation
        _this_fullwin = FULLWIN_IQ4XS_MIB
        _this_drafter_note = "speculation OFF because nothing else fits"
        _other_label = "UD-Q2_K_XL"
        _other_fullwin = FULLWIN_Q2KXL_MIB
        _other_drafter_note = "WITH speculation"
    # An unrecorded model degrades to a NAMED ABSENCE, never to a name.
    # Defaulting an unknown run to UD-IQ4_XS is exactly the defect this
    # module is being repaired for: it is how the 2-bit report came to
    # describe a 4-bit file under every one of its figures.
    _this_label = _label if _label else "the file this run loaded (NOT RECORDED)"
    _this_bpw = _bpw if _bpw else None

    ax.text(0.015, 0.545,
            "WHY THIS BOARD HAS A QUANTISATION LADDER\n"
            "This file is %s, %s, run at %s: "
            "%.1f GiB resident, %.1f GiB spare.\n"
            "The SAME file at the full native 262,144-token window was "
            "MEASURED at %s MiB - only %s MiB clear of\n"
            "the ceiling, INSIDE the %s MiB desktop reserve, and with "
            "%s.\n"
            "%s at %.3f bits per weight holds that same window at %s "
            "MiB %s. The ladder runs\n"
            "%.3f down to %.3f bits per weight, and every rung down costs "
            "measured accuracy; the smallest rung\n"
            "whose generated code actually EXECUTES is %.3f. Capacity, not "
            "bandwidth, is what decides which\nmodel runs at all."
            % (_this_label,
               ("%.3f bits per weight" % _this_bpw) if _this_bpw
               else "bits per weight NOT RECORDED for this run",
               A.window_phrase(meta) if meta else
               "a context window NOT RECORDED for this run",
               med / 1024.0, head / 1024.0,
               _n(_this_fullwin), _n(BOARD_MIB - _this_fullwin),
               _n(DESKTOP_FENCE_MIB), _this_drafter_note,
               _other_label, A.LADDER_BPW.get(_other_label, 0.0),
               _n(_other_fullwin), _other_drafter_note,
               LADDER_TOP_BPW, LADDER_BOT_BPW, LADDER_FLOOR_BPW),
            transform=ax.transAxes, ha="left", va="top", fontsize=7.6,
            bbox=BOX, linespacing=1.4)

    _model_gb = ("%.2f GB" % meta["model_gb"]) if (meta and meta.get("model_gb")) else "the model file"
    ax.text(0.015, 0.045,
            "The %s is not the whole cost. The KV cache "
            "(%s, q8_0 for K and V), the CUDA\n"
            "context, the compute buffers and the MTP drafter are all inside "
            "this %.1f GiB as well.\n"
            "NOT MEASURED: which allocation owns which byte. nvidia-smi pmon "
            "reports \"-\" for every process under\n"
            "Windows WDDM, so this rig has no per-process VRAM attribution "
            "and this figure claims none."
            % (_model_gb,
               ("{:,} tokens".format(meta["ctx_tokens"])
                if (meta and meta.get("ctx_tokens"))
                else "window size NOT RECORDED for this run"),
               med / 1024.0),
            transform=ax.transAxes, ha="left", va="bottom", fontsize=7.6,
            bbox=BOX, linespacing=1.4)

    leg = ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.105),
                    ncol=2, fontsize=8, framealpha=0.95)
    leg.get_frame().set_edgecolor("#AAAAAA")

    _mp = A.model_phrase(meta) if meta else "model not recorded"
    _wp = A.window_phrase(meta) if meta else "a context window NOT RECORDED for this run"
    _dp = A.drafter_phrase(meta) if meta else "drafter status not recorded"
    res = _footer(fig,
                  "RTX 3090, 24,576 MiB. Board memory only - never system RAM, "
                  "and no system or wall power is implied anywhere in this "
                  "module. Workload: aider polyglot agentic benchmark, "
                  "%s, -ngl 99, %s, "
                  "-fa on, KV q8_0 for K and V, %s, "
                  "deepest request %s prompt tokens. "
                  "%s dmon samples over %.0f minutes."
                  % (_mp, _wp, _dp, _n(_deepest(ctx)),
                     _n(good.sum()), mins))
    fig.tight_layout(rect=(0, res + 0.062, 1, 1))

    p = _save(fig, outdir, "capacity-vram-ceiling.png")
    _cap_model = A.model_phrase(meta) if meta else "model not recorded"
    cap = (
        "VRAM in use across the whole telemetry window against the RTX 3090's "
        "24,576 MiB physical ceiling, with headroom shaded. CONDITIONS: RTX "
        "3090, board memory only (dmon 'fb'); %s, -ngl 99, %s, "
        "--parallel 1, -fa on, KV q8_0 "
        "for both K and V; workload is the aider "
        "polyglot agentic benchmark. FINDING: the footprint is %s MiB median "
        "(%.2f GiB) and varies by only %.0f MiB across %.0f minutes, which is "
        "%.2f%% of that median footprint. "
        "Capacity is committed once at load and is never managed at run time, "
        "which is what makes a board ceiling a gate rather than a budget, and "
        "it is why a memory limit here is answered with a quantisation ladder "
        "rather than with a scheduler. %.1f GiB of headroom is left at this "
        "window. The ladder argument is measured, not arithmetic: "
        "UD-IQ4_XS at the full native 262,144-token window reached %s MiB - "
        "%s MiB from the ceiling, inside the %s MiB desktop reserve, with "
        "speculation off - while UD-Q2_K_XL at 2.912 bits per weight held the "
        "same window at %s MiB with speculation on. NOT MEASURED: per-process "
        "VRAM attribution, because nvidia-smi pmon reports '-' for every "
        "process under Windows WDDM; the split between weights, KV cache, "
        "CUDA context, compute buffers and the drafter cannot be read off this "
        "trace, and the figure says so on its face. The 24,576 MiB ceiling is "
        "specification; every other number on the figure is measured on this "
        "rig."
        % (_cap_model, _wp, _n(med), med / 1024.0, hi - lo, mins, drift_pct,
           head / 1024.0, _n(FULLWIN_IQ4XS_MIB),
           _n(BOARD_MIB - FULLWIN_IQ4XS_MIB), _n(DESKTOP_FENCE_MIB),
           _n(FULLWIN_Q2KXL_MIB)))
    return p, cap


def _deepest(ctx):
    """Deepest prompt actually reached, for the conditions line."""
    rq = ctx.get("requests")
    if rq:
        try:
            return max(float(r.get("depth", 0.0)) for r in rq)
        except (TypeError, ValueError):
            pass
    return float("nan")


# ------------------------------------------------------------------ FIGURE 2
def _null_paths(ctx, outdir, t0, meta=None):
    """PCIe traffic, and host storage, each plotted at the scale of what that
    path could carry. Two deliberate null results."""
    dmon = ctx.get("dmon")
    host = ctx.get("host")
    have_pcie = (dmon is not None
                 and len(_fin(dmon.get("rxpci"))) > 1
                 and len(_fin(dmon.get("txpci"))) > 1)
    have_disk = (host is not None and len(_fin(host.get("disk_bytes_s"))) > 1)
    if not have_pcie and not have_disk:
        return None

    nrows = int(have_pcie) + int(have_disk)
    # Panel 2 is given the taller share: its whole point is that the trace
    # lies on the floor of an axis scaled to the link, and that needs room.
    fig, axes = plt.subplots(
        nrows, 1, figsize=(11.5, 6.0 + 5.2 * (nrows - 1)),
        gridspec_kw=({"height_ratios": [1.16, 1.0]} if nrows == 2 else None))
    axes = np.atleast_1d(axes)
    k = 0
    notes = []
    cap_bits = []
    med_c = None          # PCIe median, reused by the storage panel's text
    xspan = None          # shared so the two panels line up in time

    # ---- PANEL 2: PCIe ---------------------------------------------------
    if have_pcie:
        ax = axes[k]
        k += 1
        t = np.asarray(dmon["t"], dtype=float)
        rx = np.asarray(dmon["rxpci"], dtype=float)
        tx = np.asarray(dmon["txpci"], dtype=float)
        good = np.isfinite(rx) & np.isfinite(tx)
        tm = (t[good] - t0) / 60.0
        rx, tx = rx[good], tx[good]
        comb = rx + tx
        xspan = (float(tm[0]), float(tm[-1]))

        below1 = 100.0 * float(np.mean((rx + tx) < 1000.0))
        ax.axhspan(0, 1000.0, color="#56B4E9", alpha=0.28, linewidth=0,
                   zorder=0,
                   label="0 to 1,000 MB/s: where %.1f%% of samples live "
                         "(3.2%% of the link)" % below1)
        ax.plot(tm, rx, color=C_RX, linewidth=0.8,
                label="host to board, rxpci (MB/s)")
        ax.plot(tm, tx, color=C_TX, linewidth=0.8, alpha=0.9,
                label="board to host, txpci (MB/s)")
        ax.axhline(LINK_MBS, color=C_SPEC, linestyle="--", linewidth=1.5,
                   label="%s theoretical, one direction: %s MB/s [SPEC]"
                         % (LINK_NAME, _n(LINK_MBS)))
        ax.set_ylim(0, LINK_MBS * 1.045)
        ax.set_xlim(*xspan)
        ax.set_xlabel("elapsed time (minutes since GPU telemetry start)")
        ax.set_ylabel("PCIe traffic (MB/s, per direction)")

        med_c = float(np.median(comb))
        p95_c = float(np.percentile(comb, 95))
        p99_c = float(np.percentile(comb, 99))
        max_c = float(comb.max())

        ax.set_title("PANEL 2, A DELIBERATE NULL RESULT - the link carries "
                     "%.1f%% of what it could:\ndo not spend silicon area or "
                     "power widening this bus"
                     % (100.0 * med_c / LINK_MBS),
                     fontsize=12.5, fontweight="bold", pad=10)
        _decorate(ax)
        ax.legend(loc="upper left", bbox_to_anchor=(0.008, 0.925),
                  fontsize=8, framealpha=0.95)

        ax.text(0.992, 0.925,
                "THIS AXIS IS SCALED TO THE LINK, NOT TO THE DATA.\n"
                "The trace lies on the floor because that IS the finding.\n"
                "\n"
                "rx + tx combined, over the window plotted:\n"
                "  median    %9s MB/s   %5.2f%% of the link\n"
                "  95th pct  %9s MB/s   %5.2f%% of the link\n"
                "  99th pct  %9s MB/s   %5.2f%% of the link\n"
                "  maximum   %9s MB/s   %5.2f%% of the link\n"
                "  %.1f%% of samples stay below 1,000 MB/s.\n"
                "\n"
                "The bus is empty BECAUSE capacity was sufficient:\n"
                "weights that are resident are never streamed.\n"
                "This is figure 1's finding, seen from the other side."
                % (_n(med_c), 100.0 * med_c / LINK_MBS,
                   _n(p95_c), 100.0 * p95_c / LINK_MBS,
                   _n(p99_c), 100.0 * p99_c / LINK_MBS,
                   _n(max_c), 100.0 * max_c / LINK_MBS, below1),
                transform=ax.transAxes, ha="right", va="top", fontsize=7.5,
                family="monospace", bbox=BOX, linespacing=1.3)

        ax.text(0.008, 0.728,
                "THE TAIL IS NAMED, NOT HIDDEN. %.1f%% of samples burst above "
                "1,000 MB/s, peaking at %.0f%% of the\n"
                "link. Those bursts are brief and never sustained, and this "
                "campaign did NOT establish what causes\n"
                "them: per-process PCIe attribution is unavailable "
                "(nvidia-smi pmon reports \"-\" for every process\n"
                "under Windows WDDM) and a scoring container was co-resident "
                "throughout. BAR1 read flat at\n"
                "32,739 MiB on all %s samples; NVML does not distinguish "
                "aperture from occupancy here, so this\n"
                "module reads nothing into that number. rxpci was exactly "
                "zero on %.1f%% of samples and txpci on\n"
                "%.1f%% - measured as zero, not missing."
                % (100.0 - below1, 100.0 * max_c / LINK_MBS, _n(good.sum()),
                   100.0 * float(np.mean(rx == 0.0)),
                   100.0 * float(np.mean(tx == 0.0))),
                transform=ax.transAxes, ha="left", va="top", fontsize=7.5,
                bbox=BOX, linespacing=1.4)

        cap_bits.append(
            "PANEL 2, PCIe: rxpci and txpci from nvidia-smi dmon, plotted "
            "against the theoretical one-direction rate of %s (%s MB/s, "
            "SPECIFICATION) so that the emptiness is legible rather than "
            "autoscaled away. Over the plotted window, combined traffic is %s "
            "MB/s median - %.2f%% of the link - and %s MB/s at the 95th "
            "percentile, with %.1f%% of samples below 1,000 MB/s. DECISION: "
            "do not spend silicon area or power widening this interconnect "
            "for local inference; it is empty precisely because the weights "
            "fit in VRAM, which is figure 1's finding seen from the other "
            "side. THE TAIL IS DISCLOSED RATHER THAN SMOOTHED: %.1f%% of "
            "samples burst above 1,000 MB/s, peaking at %s MB/s (%.0f%% of "
            "the link); the bursts are brief and never sustained, and their "
            "cause was NOT MEASURED, because per-process PCIe attribution "
            "does not exist under Windows WDDM and a scoring container shared "
            "the machine. BAR1 was flat at 32,739 MiB on every sample and is "
            "deliberately not interpreted, since NVML does not separate "
            "aperture from occupancy on this part."
            % (LINK_NAME, _n(LINK_MBS), _n(med_c), 100.0 * med_c / LINK_MBS,
               _n(p95_c), below1, 100.0 - below1, _n(max_c),
               100.0 * max_c / LINK_MBS))

    # ---- PANEL 3: host storage ------------------------------------------
    if have_disk:
        ax = axes[k]
        k += 1
        off, onote = _host_offset(host, dmon, ctx.get("slots"))
        if onote:
            notes.append(onote)
        ht = np.asarray(host["t"], dtype=float) - off
        aligned = (off != 0.0) or (dmon is None)
        base = t0 if aligned else float(ht[0])

        disk = np.asarray(host["disk_bytes_s"], dtype=float)
        pin_raw = host.get("pagesin_s")
        pin = (np.asarray(pin_raw, dtype=float) * WIN_PAGE_B
               if pin_raw is not None and len(pin_raw) == len(disk)
               else np.full_like(disk, np.nan))
        good = np.isfinite(disk)
        tm = (ht[good] - base) / 60.0
        disk = disk[good]
        pin_g = pin[good]

        FLOOR = 1e3          # 1 kB/s, so a log axis can still show a zero
        ax.plot(tm, np.maximum(disk, FLOOR), color=C_DISK, linewidth=0.8,
                label="host disk transfer, all volumes (bytes/s)")
        have_pin = bool(np.isfinite(pin_g).any())
        if have_pin:
            # Gaps where paging is exactly zero, so the reader can see the
            # difference between "no paging" and "a little paging".
            shown = np.where(pin_g > 0.0, pin_g, np.nan)
            ax.plot(tm, np.maximum(shown, FLOOR), color=C_PAGE, linewidth=0.8,
                    linestyle="-", alpha=0.75,
                    label="host pages-in x 4 KiB page (bytes/s); gaps are "
                          "samples with zero pages-in")
        ax.set_yscale("log")
        ax.set_ylim(FLOOR * 0.8, max(4e9, float(np.nanmax(disk)) * 5.0))
        if aligned and xspan is not None:
            ax.set_xlim(*xspan)
        else:
            ax.set_xlim(float(tm[0]), float(tm[-1]))
        ax.set_xlabel("elapsed time (minutes since GPU telemetry start)"
                      if aligned else
                      "elapsed time (minutes since HOST telemetry start; "
                      "NOT aligned to the panel above)")
        ax.set_ylabel("host storage traffic (bytes/s, log scale)")

        med_d = float(np.median(disk))
        quiet = 100.0 * float(np.mean(disk < 1e6))
        zero_d = 100.0 * float(np.mean(disk == 0.0))
        zero_p = (100.0 * float(np.mean(pin_g == 0.0)) if have_pin
                  else float("nan"))
        ok = np.isfinite(disk) & np.isfinite(pin_g)
        r = float("nan")
        if ok.sum() > 2 and disk[ok].std() > 0 and pin_g[ok].std() > 0:
            r = float(np.corrcoef(disk[ok], pin_g[ok])[0, 1])
        secs = tm * 60.0
        tot_d = float(_trapz(disk, secs)) if len(secs) > 1 else float("nan")
        tot_p = (float(_trapz(pin_g[ok], secs[ok]))
                 if ok.sum() > 2 else float("nan"))
        share = (100.0 * tot_p / tot_d
                 if np.isfinite(tot_d) and tot_d > 0 else float("nan"))
        avail = _fin(host.get("avail_mb"))
        avail_min = float(avail.min()) if len(avail) else float("nan")

        ax.axhline(med_d, color=C_DISK, linestyle=":", linewidth=1.2)
        gap = (aligned and xspan is not None and tm[0] - xspan[0] > 1.0)
        if gap:
            ax.axvspan(xspan[0], tm[0], color="#EEEEEE", zorder=0)
            ax.text((xspan[0] + tm[0]) / 2.0, FLOOR * 2.2,
                    "host collector\nstarted %.0f min\nlate: no data,\n"
                    "not zero" % (tm[0] - xspan[0]),
                    ha="center", va="bottom", fontsize=7.0, color="#555555")
        ax.text((tm[0] - 0.6) if gap else (tm[0] + 0.4), med_d * 1.6,
                "median %s kB/s" % _n(med_d / 1e3),
                ha="right" if gap else "left", va="bottom", fontsize=7.4,
                color=C_DISK)

        ax.set_title("PANEL 3 - the inference path is storage-null, and the "
                     "traffic that IS here belongs to somebody else\n"
                     "(host paging tracks disk bytes at r = %s)"
                     % ("%.3f" % r if np.isfinite(r) else "not computable"),
                     fontsize=12.5, fontweight="bold", pad=10)
        _decorate(ax)
        ax.legend(loc="upper left", fontsize=8, framealpha=0.95)

        drift = float("nan")
        if dmon is not None and len(_fin(dmon.get("fb"))):
            fbf = _fin(dmon["fb"])
            drift = float(fbf.max() - fbf.min())

        ax.text(0.992, 0.035,
                "THE NULL, AND ITS LIMIT - two different claims, kept apart.\n"
                "\n"
                "NULL, and measured directly: the weights never come back "
                "from disk. Board VRAM held to %s MiB\n"
                "of drift over the run (figure 1), so nothing was evicted and "
                "re-read, and PCIe stayed at %s of\n"
                "the link (panel 2). Median host disk is %s kB/s, %.1f%% of "
                "samples sit below 1 MB/s, and %.1f%%\n"
                "read exactly zero.\n"
                "\n"
                "NOT NULL, and NOT the inference path: %s GB crossed the disk "
                "in this window, of which %s is host\n"
                "paging. Available host RAM fell to %s MiB. These are "
                "MACHINE-WIDE Windows counters and a scoring\n"
                "container ran on this machine throughout.\n"
                "\n"
                "NOT MEASURED: per-process disk attribution. The tail is "
                "therefore reported as host memory pressure\n"
                "from a co-tenant and is NOT charged to inference. Storage "
                "bandwidth is not a local-inference design\n"
                "input once the weights are resident - but host RAM sizing is."
                % (_n(drift),
                   ("%.1f%%" % (100.0 * med_c / LINK_MBS))
                   if med_c is not None else "its measured floor",
                   _n(med_d / 1e3), quiet, zero_d, _n(tot_d / 1e9),
                   ("%.0f%%" % share) if np.isfinite(share)
                   else "an unmeasured share",
                   _n(avail_min)),
                transform=ax.transAxes, ha="right", va="bottom", fontsize=7.2,
                # Fully opaque, not the shared 0.96 alpha: this box sits over
                # live traces, and a 4% bleed puts faint strokes through the
                # sentences.
                bbox=dict(BOX, alpha=1.0), linespacing=1.38, zorder=8)

        if not have_pin:
            ax.text(0.008, 0.90,
                    "pages-in: not present in this host trace, so the disk "
                    "tail cannot be attributed here",
                    transform=ax.transAxes, ha="left", va="top", fontsize=7.5,
                    bbox=BOX)

        cap_bits.append(
            "PANEL 3, host storage: disk bytes/s and pages-in converted to "
            "bytes/s using the 4 KiB Windows page, on a log axis; these are "
            "machine-wide Windows performance counters, not per-process ones. "
            "THE NULL HOLDS FOR THE INFERENCE PATH, and it is measured "
            "directly rather than assumed: board VRAM drifted by only %s MiB "
            "across the run and PCIe stayed near the floor, so no weight was "
            "evicted and re-read. Median host disk is %s kB/s, %.1f%% of "
            "samples sit below 1 MB/s, and %.1f%% read exactly zero. THE NULL "
            "DOES NOT HOLD MACHINE-WIDE, and that is a correction to the "
            "expected result rather than a footnote: %s GB crossed the disk in "
            "this window, of which %s is host paging - pages-in x 4 KiB tracks "
            "disk bytes at r = %s - while available host RAM fell to %s MiB. "
            "NOT MEASURED: per-process disk attribution, so that traffic is "
            "reported as host memory pressure from the co-resident scoring "
            "container and is explicitly NOT charged to inference. DECISION: "
            "storage bandwidth is not a local-inference design input once the "
            "weights are resident, but host RAM sizing is - the co-tenant that "
            "scores the run can page the machine into the ground while the "
            "board itself is untouched."
            % (_n(drift), _n(med_d / 1e3), quiet, zero_d, _n(tot_d / 1e9),
               ("%.0f%%" % share) if np.isfinite(share)
               else "an unmeasured share",
               ("%.3f" % r) if np.isfinite(r) else "not computable",
               _n(avail_min)))

    _np_model = A.model_phrase(meta) if meta else "model not recorded"
    _np_window = A.window_phrase(meta) if meta else "a context window NOT RECORDED for this run"
    _np_drafter = A.drafter_phrase(meta) if meta else "drafter status not recorded"
    cond = ("RTX 3090; PCIe link negotiated at Gen4 x16 (nvidia-smi, "
            "read-only query). Board telemetry only - no system or wall power "
            "is implied. Workload: aider polyglot agentic benchmark, "
            "%s, -ngl 99, %s, %s. The link rate is "
            "SPECIFICATION; all traffic is measured."
            % (_np_model, _np_window, _np_drafter))
    if notes:
        cond += "  " + "  ".join(notes)
    res = _footer(fig, cond)
    fig.tight_layout(rect=(0, res, 1, 1))

    p = _save(fig, outdir, "capacity-null-interconnect.png")
    cap = ("Two deliberate null results, each plotted at the scale of what "
           "that path could carry so that the emptiness is the message and "
           "not an omission. " + "  ".join(cap_bits))
    if notes:
        cap += "  INSTRUMENT NOTE: " + "  ".join(notes)
    return p, cap


# -------------------------------------------------------------------- entry
def make(ctx, outdir):
    """ctx has keys: tag, run, dmon, slots, host, throttle, requests,
    exercises (any may be None if that source is absent - degrade gracefully,
    never crash). Returns a list of (png_path, caption_string)."""
    ctx = dict(ctx or {})
    meta = ctx.get("meta")
    out = []
    t0 = _origin(ctx.get("dmon"), ctx.get("slots"), ctx.get("host"))

    for fn in (_vram, _null_paths):
        try:
            r = fn(ctx, outdir, t0, meta=meta)
        except Exception as e:                       # never take a run down
            print("capacity: %s could not be built: %s: %s"
                  % (fn.__name__, type(e).__name__, e))
            r = None
        if r:
            out.append(r)
    return out
