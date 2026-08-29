"""Negative-register entry 6: build a 1440p target whose answers are objective.

WHAT ENTRY 6 ASKS. `--image-max-tokens 1024` cuts a 1440p screenshot 3.6x. What
that costs in what the model can SEE was never measured, so the recipes omit
the flag rather than recommend it. Separately, the campaign's one perception
observation has no withheld-image control, which makes it a transport check
rather than a perception result.

TWO DESIGN CHOICES THAT MAKE THIS STRONGER THAN THE REGISTER ASKED FOR.

1. OBJECTIVE ANSWERS, NOT JUDGED ONES. The register proposed "a question whose
   answer depends on fine detail, scored blind". A blind judge is the right
   instrument when the answer is prose, but here it is not needed: this image
   is GENERATED, so every answer is known exactly and scoring is string
   equality. That removes the judge, its noise floor, and its cost.

2. A WITHIN-IMAGE CONTROL, not just a withheld-image one. The page carries two
   classes of fact:
     COARSE - the headline number, rendered at 96 px. It survives any plausible
              downsampling. If the model misses these at the low budget, the
              problem is not resolution, it is that the pipeline broke.
     FINE   - table cells at 15 px and a serial at 12 px. At 1024 tokens these
              are roughly a third of their linear size and should not be
              legible.
   COARSE questions therefore act as a positive control INSIDE the same image.
   A result where coarse holds and fine collapses is a resolution finding. A
   result where both collapse is a plumbing finding, and they must not be
   confused.

THE WITHHELD-IMAGE CONTROL still matters and is run separately: a model asked
"what is the serial number" with no image can still emit a plausible string,
and without the control a lucky guess is indistinguishable from perception.
Every answer this target asks for is arbitrary and unguessable by design -
random digits, not round numbers - so the control should score ~0.

Writes: detail-target.png (2560x1440) and detail-target.json (ground truth).
"""

import json
import os
import random

from PIL import Image, ImageDraw, ImageFont

W, H = 2560, 1440
OUT = os.path.dirname(os.path.abspath(__file__))
PNG = os.path.join(OUT, "detail-target.png")
TRUTH = os.path.join(OUT, "detail-target.json")

MONO = r"C:\Windows\Fonts\consola.ttf"
SANS = r"C:\Windows\Fonts\segoeui.ttf"

BG, INK, MUTED, LINE = (18, 20, 24), (238, 240, 244), (150, 156, 166), (52, 57, 66)
GOOD, BAD, WARN = (72, 190, 120), (232, 86, 76), (226, 170, 60)

rng = random.Random(20260825)          # fixed: the target must be reproducible


def f(path, size):
    return ImageFont.truetype(path, size)


def main():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # ---- COARSE layer: large enough to survive heavy downsampling -----------
    d.text((64, 52), "CLUSTER TELEMETRY", font=f(SANS, 46), fill=INK)
    d.text((64, 112), "region eu-west-2  ·  window 15 min", font=f(SANS, 28), fill=MUTED)

    headline = rng.randrange(100, 999)          # 3 digits, rendered at 96 px
    d.text((64, 196), str(headline), font=f(MONO, 96), fill=INK)
    d.text((64, 310), "ACTIVE SHARDS", font=f(SANS, 26), fill=MUTED)

    banner = rng.choice(["DEGRADED", "NOMINAL", "CRITICAL"])
    bcol = {"DEGRADED": WARN, "NOMINAL": GOOD, "CRITICAL": BAD}[banner]
    d.rectangle([420, 196, 900, 286], outline=bcol, width=4)
    d.text((444, 214), banner, font=f(SANS, 54), fill=bcol)

    # ---- FINE layer: 15 px table rows, 12 px serial ------------------------
    x0, y0, rowh = 64, 400, 34
    cols = [0, 200, 420, 620, 800]
    hdr = f(MONO, 19)
    d.text((x0, y0), "SHARD", font=hdr, fill=MUTED)
    d.text((x0 + cols[1], y0), "LATENCY", font=hdr, fill=MUTED)
    d.text((x0 + cols[2], y0), "RETRIES", font=hdr, fill=MUTED)
    d.text((x0 + cols[3], y0), "QUEUE", font=hdr, fill=MUTED)
    d.text((x0 + cols[4], y0), "STATUS", font=hdr, fill=MUTED)
    d.line([x0, y0 + 26, x0 + 960, y0 + 26], fill=LINE, width=2)

    cell = f(MONO, 15)                            # the fine detail
    rows, fails = [], 0
    for i in range(1, 15):
        y = y0 + 40 + (i - 1) * rowh
        name = "SHARD-%02d" % i
        lat = rng.randrange(103, 987)             # never round: unguessable
        ret = rng.randrange(0, 29)
        que = rng.randrange(1000, 9999)
        st = "FAIL" if rng.random() < 0.25 else "OK"
        if st == "FAIL":
            fails += 1
        d.text((x0, y), name, font=cell, fill=INK)
        d.text((x0 + cols[1], y), "%d ms" % lat, font=cell, fill=INK)
        d.text((x0 + cols[2], y), str(ret), font=cell, fill=INK)
        d.text((x0 + cols[3], y), str(que), font=cell, fill=INK)
        d.text((x0 + cols[4], y), st, font=cell, fill=(BAD if st == "FAIL" else GOOD))
        rows.append({"shard": name, "latency_ms": lat, "retries": ret,
                     "queue": que, "status": st})

    serial = "%s-%d-%s" % ("".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(3)),
                           rng.randrange(10000, 99999),
                           "".join(rng.choice("0123456789ABCDEF") for _ in range(4)))
    tiny = f(MONO, 12)
    d.text((W - 420, H - 44), "unit serial %s" % serial, font=tiny, fill=MUTED)

    # a second fine item, far from the first, so one lucky read is not enough
    note = rng.randrange(1000, 9999)
    d.text((1200, 404), "calibration offset: %d" % note, font=f(MONO, 14), fill=MUTED)

    img.save(PNG, "PNG")

    target = rows[6]                              # SHARD-07
    truth = {
        "image": PNG, "size": [W, H],
        "questions": [
            {"id": "coarse_headline", "class": "coarse",
             "q": "In the screenshot, what number is printed in large type under the "
                  "heading ACTIVE SHARDS? Reply with the number only.",
             "a": str(headline)},
            {"id": "coarse_banner", "class": "coarse",
             "q": "In the screenshot, what single word appears inside the outlined "
                  "box near the top? Reply with that word only.",
             "a": banner},
            {"id": "fine_latency", "class": "fine",
             "q": "In the screenshot's table, what is the LATENCY value for the row "
                  "labelled SHARD-07? Reply with the number of milliseconds only.",
             "a": str(target["latency_ms"])},
            {"id": "fine_queue", "class": "fine",
             "q": "In the screenshot's table, what is the QUEUE value for the row "
                  "labelled SHARD-07? Reply with the number only.",
             "a": str(target["queue"])},
            {"id": "fine_fails", "class": "fine",
             "q": "In the screenshot's table, how many rows have STATUS equal to "
                  "FAIL? Reply with the count only.",
             "a": str(fails)},
            {"id": "fine_serial", "class": "fine",
             "q": "In the screenshot, what unit serial is printed in small type at "
                  "the bottom right? Reply with the serial only.",
             "a": serial},
            {"id": "fine_offset", "class": "fine",
             "q": "In the screenshot, what is the calibration offset value? Reply "
                  "with the number only.",
             "a": str(note)},
        ],
        "rows": rows,
    }
    json.dump(truth, open(TRUTH, "w", encoding="utf-8"), indent=1)

    print("wrote %s  (%dx%d, %.0f KB)" % (PNG, W, H, os.path.getsize(PNG) / 1024))
    print("wrote %s" % TRUTH)
    print("\nground truth")
    print("  headline %s   banner %s   FAIL rows %d" % (headline, banner, fails))
    print("  SHARD-07 latency %s ms  queue %s" % (target["latency_ms"], target["queue"]))
    print("  serial %s   calibration offset %s" % (serial, note))
    print("\n  %d questions: %d coarse (positive control), %d fine"
          % (len(truth["questions"]),
             sum(1 for q in truth["questions"] if q["class"] == "coarse"),
             sum(1 for q in truth["questions"] if q["class"] == "fine")))


if __name__ == "__main__":
    main()
