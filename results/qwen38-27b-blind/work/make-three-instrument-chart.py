"""Emit the three-instrument overlay as inline SVG.

The point of the figure, and the only reason it earns its place beside the
tables: THREE INSTRUMENTS BREAK AT THREE DIFFERENT POINTS on the same ladder.
Perplexity climbs from the very first step down. The empty-answer rate is
exactly flat at zero until 2.481 bits per weight and only then moves. Task
accuracy is flat-with-noise until it falls off a cliff at 2.153. A reader
absorbs that in two seconds from the picture and cannot get it from any one
table.

Every value plotted is normalised against the reference file UD-IQ4_XS so the
three can share one axis: perplexity as % ADDED, accuracy as % LOST, empty
answers as % of the 75 graded items. All three therefore read "worse is
higher", and the y-axis is labelled as degradation, not as a score.

REPORT-SPEC: a figure never carries a number alone. Every point here also
appears in the tables beside it; this only draws them.
"""

DATA = [
    # bpw,    file,          perplexity, accuracy Mean, empty count (of 75)
    (4.223, "UD-IQ4_XS",   6.5956, 97.30,  0),
    (3.895, "UD-Q3_K_XL",  6.7691, 96.00,  0),
    (3.240, "UD-IQ3_XXS",  6.9187, 93.30,  0),
    (2.912, "UD-Q2_K_XL",  6.9957, 96.00,  0),
    (2.481, "UD-IQ2_S",    7.5481, 90.70,  2),
    (2.153, "UD-IQ2_XXS",  8.0079, 78.70,  3),
    (1.994, "UD-IQ1_M",    8.1418, 85.30,  5),
    (1.835, "UD-IQ1_S",    8.9265, 34.70, 28),
]
REF_PPL, REF_ACC, N = 6.5956, 97.30, 75

W, H = 780, 400
L, R, T, B = 78, 742, 46, 300
XMIN, XMAX = 4.45, 1.72          # descending: bigger files on the left
YMAX = 70.0                       # degradation %


def px(bpw):
    return L + (XMIN - bpw) / (XMIN - XMAX) * (R - L)


def py(pct):
    return T + min(pct, YMAX) / YMAX * (B - T)


def series():
    ppl = [(px(b), py((p - REF_PPL) / REF_PPL * 100)) for b, _, p, _, _ in DATA]
    acc = [(px(b), py((REF_ACC - a) / REF_ACC * 100)) for b, _, _, a, _ in DATA]
    emp = [(px(b), py(e / N * 100)) for b, _, _, _, e in DATA]
    return ppl, acc, emp


def path(pts):
    return "M " + " L ".join("%.1f %.1f" % p for p in pts)


def dots(pts, cls):
    return "".join('<circle cx="%.1f" cy="%.1f" r="3.4" class="%s"/>' % (x, y, cls)
                   for x, y in pts)


def main():
    ppl, acc, emp = series()
    out = []
    A = out.append
    A('<figure class="chart3">')
    A('<svg viewBox="0 0 %d %d" role="img" width="100%%" '
      'aria-labelledby="c3t c3d">' % (W, H))
    A('<title id="c3t">Three instruments break at three different points</title>')
    A('<desc id="c3d">Degradation against the UD-IQ4_XS reference file, plotted '
      'against bits per weight falling from 4.223 to 1.835. Perplexity rises '
      'from the first step down, reaching plus 35 percent at the smallest file. '
      'The empty-answer rate is exactly zero for every file down to and '
      'including 2.912 bits, then rises to 2.7, 4.0, 6.7 and 37.3 percent of 75 '
      'graded answers. Task accuracy is flat within noise until 2.153 bits, then '
      'falls, ending 64 percent below the reference. Every value is also printed '
      'in the tables beside this figure.</desc>')
    # grid
    for pct in (0, 10, 20, 30, 40, 50, 60, 70):
        y = py(pct)
        A('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" class="g"/>' % (L, y, R, y))
        A('<text x="%d" y="%.1f" class="ax ar">%d%%</text>' % (L - 9, y + 4, pct))
    for b, name, _, _, _ in DATA:
        x = px(b)
        A('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" class="g gv"/>' % (x, T, x, B))
        A('<text x="%.1f" y="%d" class="ax am">%.2f</text>' % (x, B + 18, b))
        A('<text x="%.1f" y="%d" class="ax am fn" transform="rotate(-38 %.1f %d)">'
          '%s</text>' % (x, B + 34, x, B + 34, name.replace("UD-", "")))
    A('<text x="%.1f" y="%d" class="ax am lbl">bits per weight &#8594; smaller '
      'file</text>' % ((L + R) / 2, B + 62))
    A('<text x="18" y="%d" class="ax lbl" transform="rotate(-90 18 %d)">worse '
      '&#8594; degradation vs the reference file</text>' % ((T + B) / 2, (T + B) / 2))
    # the knee and the accuracy cliff, called out where they happen
    A('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" class="mark"/>' % (px(2.912), T, px(2.912), B))
    A('<text x="%.1f" y="%d" class="ax note">perplexity knee 2.91</text>'
      % (px(2.912) + 5, T + 12))
    A('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" class="mark"/>' % (px(2.153), T, px(2.153), B))
    A('<text x="%.1f" y="%d" class="ax note" text-anchor="end">accuracy cliff '
      '2.15</text>' % (px(2.153) - 5, T + 12))
    # series
    A('<path d="%s" class="s ppl"/>%s' % (path(ppl), dots(ppl, "d ppl")))
    A('<path d="%s" class="s emp"/>%s' % (path(emp), dots(emp, "d emp")))
    A('<path d="%s" class="s acc"/>%s' % (path(acc), dots(acc, "d acc")))
    # legend
    lx, ly = L + 12, T + 8
    for i, (cls, txt) in enumerate((
            ("ppl", "perplexity added &#8212; moves from the first step"),
            ("emp", "empty answers &#8212; flat at zero until 2.48"),
            ("acc", "accuracy lost &#8212; flat until the cliff at 2.15"))):
        y = ly + i * 17
        A('<line x1="%d" y1="%d" x2="%d" y2="%d" class="s %s"/>' % (lx, y, lx + 26, y, cls))
        A('<circle cx="%d" cy="%d" r="3.4" class="d %s"/>' % (lx + 13, y, cls))
        A('<text x="%d" y="%d" class="ax lg">%s</text>' % (lx + 33, y + 4, txt))
    A('</svg>')
    A('<figcaption><b>Three instruments, three different breaking points.</b> '
      'Perplexity starts moving at the very first step down and never stops, '
      'which makes it the most sensitive of the three &mdash; and the one that '
      'says least about whether the model still works. The empty-answer rate is '
      'exactly zero for every file down to the 2.912-bpw knee, then climbs; it '
      'catches damage a full rung above where the accuracy test can resolve '
      'anything, and costs no GPU time because it is read from transcripts '
      'already on disk. Task accuracy is flat within noise until 2.153 bpw and '
      'then falls away. <b>None of these curves is the truth on its own.</b> '
      'Every value plotted is printed in the tables above; this figure only '
      'draws them.</figcaption>')
    A('</figure>')
    return "\n".join(out)


print(main())
