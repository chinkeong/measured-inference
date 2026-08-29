"""The quantisation ladder as one figure. Supersedes make-three-instrument-chart.py.

WHY IT CHANGED. The earlier version plotted three instruments and its headline
was "three instruments break at three different points". A6 — running the code
instead of reading it — added a fourth, and the fourth does NOT add a fourth
breaking point. It lands exactly where the accuracy cliff lands. That is a
better finding than the one the old chart carried:

  perplexity     moves at the very first step down and never stops. It is the
                 most sensitive instrument here and the one that says least
                 about whether the model still works.
  empty answers  exactly zero down to 2.912 bpw, first flinch at 2.481. It is
                 the EARLY WARNING, and it costs no GPU time.
  accuracy       ties the reference all the way to 2.481, breaks at 2.153.
  execution      last file whose code runs is 2.481; 2.153 and below do not run.

So the two instruments that ask "does the text look right" disagree with each
other, and the two that ask "does it WORK" — task accuracy and a JavaScript
parser, which share no machinery whatsoever — agree exactly. The functional
boundary is between 2.481 and 2.153 bpw, and it has two independent witnesses.

Emitted to match the host guide's existing chart idiom: 640-wide viewBox,
var(--line)/var(--ink)/var(--muted)/var(--accent)/var(--bad) tokens so it
follows the page's light and dark palettes, class="axis-t" for tick text, and
every series separated by DASH as well as by colour so the figure survives
greyscale, print, and colour-blind reading.

REPORT-SPEC: a figure never carries a number alone. Every value plotted is also
printed in the tables beside it; this only draws them.
"""

import sys

# bpw,   file,          PPL,    accuracy, empty/75, executes
DATA = [
    (4.223, "IQ4_XS",   6.5956, 97.30,  0, True),
    (3.895, "Q3_K_XL",  6.7691, 96.00,  0, True),
    (3.240, "IQ3_XXS",  6.9187, 93.30,  0, True),
    (2.912, "Q2_K_XL",  6.9957, 96.00,  0, True),
    (2.481, "IQ2_S",    7.5481, 90.70,  2, True),
    (2.153, "IQ2_XXS",  8.0079, 78.70,  3, False),
    (1.994, "IQ1_M",    8.1418, 85.30,  5, False),
    (1.835, "IQ1_S",    8.9265, 34.70, 28, False),
]
# OFF-LADDER, measured 2026-08-26. NOT part of DATA above, and that is
# deliberate: DATA is drawn as three POLYLINES, so anything placed in it is
# joined to its neighbours and reads as a point on the same curve. This file is
# a different PRODUCTION METHOD - quantisation-aware training rather than
# post-training quantisation - so a line through it would assert exactly the
# thing the ladder cannot show, that bits per weight explains where it lands.
#
#   bpw     file         PPL      acc/75   empty/75  executes
OFF_LADDER = [
    (2.595, "QAT-Q2_0", 7.4996, 90.70, 1, True),
]
# Before this is plotted it needs a DISTINCT marker (not a line vertex) and the
# figure's aria description rewritten - that text enumerates every value drawn,
# and it currently describes an eight-file ladder.
#
# What it measured, for whoever draws it:
#   - PPL 7.4996 against 7.4020 interpolated on the PTQ curve at 2.595 bpw:
#     1.32% WORSE, on an identical tokenizer (297,193 tokens both, so rule 6
#     is satisfied by measurement, not assumption).
#   - accuracy 90.70 = 68/75, an EXACT tie with UD-IQ2_S at 2.481 bpw, which is
#     0.114 bpw smaller. Paired McNemar: discordant 2:2, p = 1.0000.
#   - against UD-Q2_K_XL (2.912 bpw, 96.00): discordant 0:4, p = 0.1250.
#     Directional - it never wins an item Q2_K_XL loses - but n=75 cannot
#     resolve it, and saying otherwise would repeat the error this ladder was
#     just criticised for.
#   - 1 empty answer, HumanEval[6] - the SAME prompt that empties on UD-IQ2_S
#     and UD-IQ1_S. Three files, two production methods, one prompt.
#   - the code RUNS.
# No instrument here shows QAT buying anything at its bit rate.

REF_PPL, REF_ACC, N = 6.5956, 97.30, 75

W, H = 640, 300
L, R, T, B = 48, 620, 30, 196
XMIN, XMAX = 4.35, 1.75      # descending: bigger files on the left
YMAX = 70.0
STRIP = 232                  # y of the runs/does-not-run strip
BOUNDARY = 2.317             # midway between the last runner and the first failure


def px(bpw):
    return L + (XMIN - bpw) / (XMIN - XMAX) * (R - L)


def py(pct):
    # Larger percentage -> larger y, and in SVG a larger y is FURTHER
    # DOWN the page. So a worse file is drawn LOWER. The axis note used
    # to read "worse is higher", which contradicted this mapping and
    # shipped that way on the live page; the standalone PNG had been
    # corrected but this generator had not, and it would have
    # reintroduced the wrong label on its next run.
    return T + min(pct, YMAX) / YMAX * (B - T)


def pts(vals):
    return " ".join("%.0f,%.0f" % v for v in vals)


def main():
    ppl = [(px(b), py((p - REF_PPL) / REF_PPL * 100)) for b, _, p, _, _, _ in DATA]
    acc = [(px(b), py((REF_ACC - a) / REF_ACC * 100)) for b, _, _, a, _, _ in DATA]
    emp = [(px(b), py(e / N * 100)) for b, _, _, _, e, _ in DATA]
    o = []
    A = o.append

    aria = (
        "Line chart of the eight-file quantisation ladder, plotting degradation "
        "against the UD-IQ4_XS reference file as bits per weight falls from "
        "4.223 on the left to 1.835 on the right. Perplexity added rises from "
        "zero at the first step to 35 percent at the smallest file, moving at "
        "every single step. Empty answers are exactly zero for every file down "
        "to 2.912 bits, then rise to 2.7, 4.0, 6.7 and 37.3 percent of 75 "
        "graded answers. Accuracy lost is flat within noise to 2.481 bits and "
        "then falls away, ending 64 percent below the reference. A strip along "
        "the bottom marks whether each file's emitted JavaScript actually ran: "
        "the five files from 4.223 down to 2.481 bits all run, and the three "
        "below — 2.153, 1.994 and 1.835 bits — do not. The accuracy cliff and "
        "the execution failure begin at the same rung, 2.153 bits per weight. "
        "Every value plotted is also printed in the tables beside this figure.")

    A('<figure>')
    A('<svg viewBox="0 0 %d %d" role="img" aria-label="%s">' % (W, H, aria))

    # the region where nothing executes
    xb = px(BOUNDARY)
    A('<rect x="%.0f" y="%d" width="%.0f" height="%d" fill="var(--bad)" '
      'opacity="0.055"/>' % (xb, T, R - xb, B - T))
    A('<line x1="%.0f" y1="%d" x2="%.0f" y2="%d" stroke="var(--bad)" '
      'stroke-width="1" stroke-dasharray="3 3" opacity="0.6"/>' % (xb, T, xb, STRIP + 10))

    # horizontal grid
    A('<g stroke="var(--line)" stroke-width="1">')
    for pct in (0, 10, 20, 30, 40, 50, 60, 70):
        A('<line x1="%d" y1="%.0f" x2="%d" y2="%.0f"/>' % (L, py(pct), R, py(pct)))
    A('</g>')
    for pct in (0, 20, 40, 60):
        A('<text class="axis-t" x="%d" y="%.0f" text-anchor="end">%d%%</text>'
          % (L - 8, py(pct) + 4, pct))

    # series - colour AND dash, so the figure survives greyscale
    A('<polyline points="%s" fill="none" stroke="var(--muted)" stroke-width="2" '
      'stroke-dasharray="2 3" stroke-linejoin="round"/>' % pts(ppl))
    A('<polyline points="%s" fill="none" stroke="var(--bad)" stroke-width="2" '
      'stroke-dasharray="7 4" stroke-linejoin="round"/>' % pts(emp))
    A('<polyline points="%s" fill="none" stroke="var(--accent)" stroke-width="2.5" '
      'stroke-linejoin="round"/>' % pts(acc))
    for cls, series, r in (("var(--muted)", ppl, 2.6), ("var(--bad)", emp, 2.6),
                           ("var(--accent)", acc, 3.5)):
        A('<g fill="%s" stroke="var(--ground)" stroke-width="1.5">%s</g>'
          % (cls, "".join('<circle cx="%.0f" cy="%.0f" r="%s"/>' % (x, y, r)
                          for x, y in series)))

    # x ticks: bits per weight, and the file each one is
    for b, name, _, _, _, _ in DATA:
        x = px(b)
        A('<text class="axis-t" x="%.0f" y="%d" text-anchor="middle">%.2f</text>'
          % (x, B + 16, b))
        A('<text class="axis-t" x="%.0f" y="%d" text-anchor="middle" '
          'style="font-size:9px" opacity="0.85">%s</text>' % (x, B + 28, name))

    # the fourth instrument: did the code actually run
    A('<text class="axis-t" x="%d" y="%d" text-anchor="end" '
      'style="font-size:9.5px">code</text>' % (L - 8, STRIP - 2))
    A('<text class="axis-t" x="%d" y="%d" text-anchor="end" '
      'style="font-size:9.5px">runs?</text>' % (L - 8, STRIP + 9))
    for b, _, _, _, _, ok in DATA:
        x = px(b)
        if ok:
            A('<circle cx="%.0f" cy="%d" r="5" fill="var(--accent)" '
              'stroke="var(--ground)" stroke-width="1.5"/>' % (x, STRIP))
        else:
            A('<g stroke="var(--bad)" stroke-width="2.2" stroke-linecap="round">'
              '<line x1="%.0f" y1="%d" x2="%.0f" y2="%d"/>'
              '<line x1="%.0f" y1="%d" x2="%.0f" y2="%d"/></g>'
              % (x - 4.5, STRIP - 4.5, x + 4.5, STRIP + 4.5,
                 x + 4.5, STRIP - 4.5, x - 4.5, STRIP + 4.5))
    A('<text class="axis-t" x="%.0f" y="%d" style="font-size:9.5px" '
      'fill="var(--bad)">&#8592; nothing below here runs</text>' % (xb + 6, STRIP + 26))
    A('<text class="axis-t" x="%d" y="%d" text-anchor="end">bits per weight '
      '&#8594; smaller file &#183; worse is LOWER</text>' % (R, T - 12))

    # legend
    ly = 262
    for i, (col, dash, txt) in enumerate((
            ("var(--muted)", '2 3', "perplexity added &#183; moves at every step"),
            ("var(--bad)", '7 4', "empty answers &#183; first flinch at 2.481"),
            ("var(--accent)", '0', "accuracy lost &#183; ties the reference to 2.481"))):
        y = ly + i * 13
        A('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="2.2" '
          '%s/>' % (L, y, L + 24, y, col,
                    ('stroke-dasharray="%s"' % dash) if dash != '0' else ''))
        A('<text class="axis-t" x="%d" y="%d" style="font-size:10px">%s</text>'
          % (L + 30, y + 4, txt))
    A('</svg>')

    A('<figcaption><b>Four instruments, and only two of them agree.</b> '
      '<span class="chip d">der</span> Every plotted point is a ratio against '
      'the <code>UD-IQ4_XS</code> reference, so that instruments in different '
      'units can share one axis: <b>perplexity added</b> = (PPL &minus; 6.5956) '
      '&divide; 6.5956, <b>accuracy lost</b> = (97.30 &minus; Mean) &divide; '
      '97.30, <b>empty rate</b> = empties &divide; 75. The measured values '
      'behind all three are printed in the tables above. The run / does-not-run '
      'strip along the bottom is <span class="chip m">meas</span> directly. '
      'Perplexity moves at the very first step '
      'down and never stops &mdash; the most sensitive line here, and the one '
      'that says least about whether the model still works. The empty-answer '
      'rate is <b>exactly zero</b> down to 2.912 bits per weight and first '
      'flinches at 2.481: it is the early warning, and it costs no GPU time '
      'because it is counted from answers already on disk. Then the two '
      'instruments that ask whether the model actually <em>works</em> &mdash; '
      'the paired accuracy test and a JavaScript parser, which share no '
      'machinery at all &mdash; <b>break at the same rung</b>. Everything down '
      'to <code>UD-IQ2_S</code> at 2.481 runs; nothing below it does. '
      '<b>The functional boundary is between 2.481 and 2.153 bits per weight, '
      'and it has two independent witnesses.</b> Execution is '
      '<span class="chip u">n=1</span> per file.</figcaption>')
    A('</figure>')
    return "\n".join(o)


USAGE = """\
The quantisation ladder as one inline SVG figure: perplexity added, accuracy
lost and the empty-answer rate against the UD-IQ4_XS reference, over a strip
saying whether each file's emitted JavaScript actually ran.

    python scripts/quant-ladder/make-ladder-chart.py > <destination>.html

Positional arguments: none. Every value is pinned in the DATA table in this
file - eight Unsloth rungs from 4.223 down to 1.835 bpw, measured elsewhere
and printed in the tables beside this figure. No environment variables. No
server, no model, no GPU: nothing is measured here, the numbers are only
drawn.

Example:
  python scripts/quant-ladder/make-ladder-chart.py \\
      > results/qwen38-27b-blind/work/ladder-chart.svg.html

OUTPUT. The <figure> block goes to STDOUT and nowhere else - this script
opens no file for writing. The published copy is
results/qwen38-27b-blind/work/ladder-chart.svg.html, which is that stdout
redirected there by the caller.

IT DOES NOT WRITE THE PNG. results/qwen38-27b-blind/figures/quant-ladder.png
is a different artifact rendered by a different file,
scripts/quant-ladder/make-ladder-png.py, which loads its sources and draws
them inside main() behind an argument parser: importing that file reads no
file and writes none, and the figure moves only when somebody types the
command. Until 2026-08-30 its whole body was module level, so merely
importing it rewrote the published figure - which is how the cheap pre-check
in scripts/verify/probe-smoke-test.py rewrote a 280,937-byte published
artefact on 2026-08-29. Two artifacts, two files; this is the one the guide
page carries inline.
"""


if __name__ == "__main__":
    # A help request must never start work. This script has no argument
    # parser, so without this line --help falls through and prints the whole
    # figure instead of answering - and a caller redirecting stdout gets a
    # chart where the usage should have been.
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        print(USAGE.rstrip())
        raise SystemExit(0)
    print(main())
