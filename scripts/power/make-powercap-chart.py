"""The power-cap result as one figure.

THE POINT OF THE CHART, and the only reason it earns space beside the table:
capping the board makes POWER fall faster than THROUGHPUT does, and the vertical
gap between those two lines IS the efficiency win. A table states that; a picture
shows it in one glance, and shows that the gap widens as the cap bites harder.

The SM clock line is drawn because it explains the shape. A cap works by
lowering the clock, and throughput falls LESS than the clock does - decode is
partly memory-bandwidth-bound and the memory clock is untouched. Without that
line a reader sees an effect with no mechanism.

Everything is plotted as PER CENT OF STOCK so three quantities in three
different units share one axis, and the axis reads "how much of the stock value
you keep" - where higher is better for all three, so there is no mixed-direction
trap.

J/token is deliberately NOT a line. It is the ratio of two lines already drawn,
so plotting it would double-count the same fact; it is printed as a value under
each cap instead.

REPORT-SPEC: every number here is printed in the table beside it; this only
draws them.
"""

# cap W, decode t/s, mean W, SM MHz, J/token
DATA = [
    (350, 75.61, 305.4, 1618, 4.033),
    (300, 71.82, 271.2, 1524, 3.771),
    (250, 65.90, 229.6, 1261, 3.479),
]
BASE = DATA[0]

W, H = 640, 300
L, R, T, B = 52, 616, 34, 210


def px(i):
    return L + i * (R - L) / (len(DATA) - 1)


def py(pct):
    lo, hi = 68.0, 104.0
    return T + (hi - pct) / (hi - lo) * (B - T)


def pts(vals):
    return " ".join("%.0f,%.0f" % (px(i), py(v)) for i, v in enumerate(vals))


def main():
    tput = [d[1] / BASE[1] * 100 for d in DATA]
    powr = [d[2] / BASE[2] * 100 for d in DATA]
    clk = [d[3] / BASE[3] * 100 for d in DATA]

    o = []
    A = o.append
    aria = (
        "Line chart of what a GPU power cap costs, plotted as per cent of the stock "
        "350 watt setting, across caps of 350, 300 and 250 watts. Board power falls "
        "fastest, to 88.8 and then 75.2 per cent. The SM clock falls to 94.2 and then "
        "77.9 per cent. Decode throughput falls least, to 95.0 and then 87.2 per cent. "
        "Because throughput is retained better than power is spent, energy per token "
        "improves from 4.033 joules to 3.771 and then 3.479. Every value is printed in "
        "the table beside this figure.")
    A('<figure>')
    A('<svg viewBox="0 0 %d %d" role="img" aria-label="%s">' % (W, H, aria))

    A('<g stroke="var(--line)" stroke-width="1">')
    for p in (70, 80, 90, 100):
        A('<line x1="%d" y1="%.0f" x2="%d" y2="%.0f"/>' % (L, py(p), R, py(p)))
    A('</g>')
    for p in (70, 80, 90, 100):
        A('<text class="axis-t" x="%d" y="%.0f" text-anchor="end">%d%%</text>'
          % (L - 8, py(p) + 4, p))

    for i, d in enumerate(DATA):
        A('<text class="axis-t" x="%.0f" y="%d" text-anchor="middle">%d W</text>'
          % (px(i), B + 18, d[0]))
        A('<text class="axis-t" x="%.0f" y="%d" text-anchor="middle" '
          'style="font-size:10px" opacity=".85">%.3f J/tok</text>'
          % (px(i), B + 34, d[4]))

    # the gap between power and throughput is the finding - shade it
    A('<path d="M %s L %s Z" fill="var(--accent)" opacity=".10"/>'
      % (pts(tput), " L ".join(reversed(pts(powr).split(" ")))))

    A('<polyline points="%s" fill="none" stroke="var(--bad)" stroke-width="2.4" '
      'stroke-linejoin="round"/>' % pts(powr))
    A('<polyline points="%s" fill="none" stroke="var(--muted)" stroke-width="2" '
      'stroke-dasharray="2 3" stroke-linejoin="round"/>' % pts(clk))
    A('<polyline points="%s" fill="none" stroke="var(--accent)" stroke-width="2.6" '
      'stroke-linejoin="round"/>' % pts(tput))
    for series, col, r in ((powr, "var(--bad)", 3.2), (clk, "var(--muted)", 2.6),
                           (tput, "var(--accent)", 3.6)):
        A('<g fill="%s" stroke="var(--ground)" stroke-width="1.5">%s</g>'
          % (col, "".join('<circle cx="%.0f" cy="%.0f" r="%s"/>' % (px(i), py(v), r)
                          for i, v in enumerate(series))))

    A('<text class="axis-t" x="%.0f" y="%.0f" style="font-size:10.5px" '
      'fill="var(--accent)">this gap is the win</text>'
      % (px(1) + 8, (py(tput[1]) + py(powr[1])) / 2 + 4))
    A('<text class="axis-t" x="%d" y="%d" text-anchor="end">power cap &#8594; '
      'lower &#183; higher is better</text>' % (R, T - 12))

    ly = 254
    for i, (col, dash, txt) in enumerate((
            ("var(--accent)", "0", "decode throughput kept &#8212; falls least"),
            ("var(--bad)", "0", "board power &#8212; falls fastest"),
            ("var(--muted)", "2 3", "SM clock &#8212; why the others move"))):
        y = ly + i * 13
        A('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="2.4" %s/>'
          % (L, y, L + 24, y, col,
             ('stroke-dasharray="%s"' % dash) if dash != "0" else ""))
        A('<text class="axis-t" x="%d" y="%d" style="font-size:10px">%s</text>'
          % (L + 30, y + 4, txt))
    A('</svg>')
    A('<figcaption><b>Capping the board spends power faster than it costs speed.</b> '
      '<span class="chip m">meas</span> Each line is that quantity as a percentage of '
      'the stock 350&nbsp;W setting, so higher is better throughout. <b>Power falls '
      'fastest and throughput falls least</b>, and the shaded gap between them is the '
      'efficiency win &mdash; it widens as the cap bites, which is why 250&nbsp;W is a '
      'better trade than 300 rather than a worse one. <b>The dashed clock line explains '
      'the shape:</b> a cap works by lowering the SM clock, and throughput does not '
      'follow it down one-for-one because decode is partly memory-bandwidth-bound and '
      'the memory clock is untouched. Note also that <b>the stock arm never reaches its '
      'own cap</b> &mdash; 305.4&nbsp;W against a 350&nbsp;W limit &mdash; so the first '
      '50&nbsp;W removes headroom the workload was not using. Decode only; prefill is '
      'compute-bound and would plausibly lose more. <span class="chip u">n=3</span> per '
      'arm.</figcaption>')
    A('</figure>')
    return "\n".join(o)


if __name__ == "__main__":
    print(main())
