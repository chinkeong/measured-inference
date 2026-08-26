#!/usr/bin/env python3
"""How far is our quantised ANCHOR from full precision? Bounded, not measured.

    anchor-crosscheck.py

THE PROBLEM THIS ADDRESSES. Every divergence number in this campaign is
measured against UD-IQ4_XS, because 55 GB of BF16 does not fit a 24 GB card.
That anchor is itself a lossy 4-bit file, so the ladder can say how much each
rung loses RELATIVE TO IT and cannot say how much was already lost before the
ladder starts. Anyone comparing our table against a BF16-anchored table is
comparing two different questions.

WHAT CAN BE DONE WITHOUT THE HARDWARE TO MEASURE IT. Quesma's August 2026 study
(quesma.com/blog/qwen38-27b-quantizations-benchmarked) ran the same Unsloth
files against a real BF16 reference on an H200. One file appears in both
studies with the same metric - UD-IQ1_S, top-1 token agreement - so their
expensive measurement can bound ours for free.

THE METRIC IS THE SAME ONE, which had to be checked before comparing. Our
column is llama-perplexity's "Same top p" output line, whose name collides with
nucleus sampling and has nothing to do with it: it reports how often the
quantised model's most likely next token matches the reference model's. That is
top-1 agreement, which is what Quesma plots as "same top-1 token as BF16".

WHAT THE BOUND IS, AND WHAT IT IS NOT. The triangle inequality on token
disagreement gives a LOWER bound on the anchor's distance from BF16. It does
NOT give an upper bound, so it cannot prove the anchor is close to full
precision, and this script does not claim that it does. A lower bound is still
worth having: it converts "unknown" into "at least this much", and it is the
strongest statement available on 24 GB.

Their value is read off a published chart and stated there as approximate, so
the bound inherits that imprecision. It is reported to one decimal place and
should not be read to more.
"""
import io, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
LADDER = os.path.join(HERE, "..", "..", "results", "qwen38-27b-blind",
                      "data", "quant-ladder", "kld-ladder.json")

# External reference points: file -> (top-1 agreement with BF16, %, source).
# Only files measured by BOTH studies with the SAME metric belong here.
EXTERNAL_BF16 = {
    "UD-IQ1_S": (72.0, "Quesma 2026-08, chart read, stated as approximate"),
}


def main():
    if not os.path.exists(LADDER):
        sys.exit("no ladder at %s" % LADDER)
    d = json.load(io.open(LADDER, encoding="utf-8"))
    rows = [r for r in d["rows"] if not r["file"].startswith("QAT")]
    rows.sort(key=lambda r: -r["bpw"])

    print("ladder anchored on %s over %d chunks" % (d["base"], d["chunks"]))
    print("anchor caveat: %s" % d["base_caveat"])
    print()
    print("  %-12s %6s %9s %9s %14s" %
          ("file", "bpw", "top1_agr", "mean_KLD", "KLD per bpw"))
    # The anchor is 4.223 bpw and agrees with itself perfectly by construction.
    prev_b, prev_k = 4.223, 0.0
    slopes = []
    for r in rows:
        db = prev_b - r["bpw"]
        dk = r["mean_kld"] - prev_k
        s = dk / db if db else float("nan")
        slopes.append((r["file"], r["bpw"], s))
        print("  %-12s %6.3f %8.2f%% %9.4f %14.4f"
              % (r["file"], r["bpw"], r["same_top_p_pct"], r["mean_kld"], s))
        prev_b, prev_k = r["bpw"], r["mean_kld"]

    print()
    print("SHAPE OF THE CURVE")
    top, bot = slopes[0][2], slopes[-1][2]
    print("  cost per bit removed rises from %.4f KLD/bpw at the top of the"
          % top)
    print("  ladder to %.4f at the bottom - a factor of %.1f. The curve is"
          % (bot, bot / top))
    print("  CONVEX, so the flattest region is the one just above the anchor.")
    print("  That is consistent with the anchor sitting near the converged end")
    print("  of the curve, but it is an extrapolation past the last measured")
    print("  point and is NOT evidence of the anchor's absolute quality.")

    print()
    print("EXTERNAL CROSS-CHECK")
    found = False
    for r in rows:
        if r["file"] not in EXTERNAL_BF16:
            continue
        found = True
        theirs, src = EXTERNAL_BF16[r["file"]]
        ours = r["same_top_p_pct"]
        dis_ours, dis_theirs = 100.0 - ours, 100.0 - theirs
        lower = dis_theirs - dis_ours
        print("  file: %s" % r["file"])
        print("    agreement with OUR anchor (%s): %6.2f%%" % (d["base"], ours))
        print("    agreement with BF16:            %6.1f%%   [%s]" % (theirs, src))
        print()
        print("    disagree(file,BF16) <= disagree(file,anchor) + disagree(anchor,BF16)")
        print("    %5.2f               <= %5.2f + disagree(anchor,BF16)"
              % (dis_theirs, dis_ours))
        print("    => the anchor differs from BF16 on AT LEAST %.1f%% of tokens"
              % lower)
        print()
        print("    This is a LOWER bound. It does not prove the anchor is close")
        print("    to full precision, and no measurement on 24 GB can: BF16 is")
        print("    55 GB against 24 GB of VRAM and 31.8 GB of system RAM.")
    if not found:
        print("  no file in the ladder has a published BF16 counterpart")

    print()
    print("WHAT WOULD ACTUALLY SETTLE IT, and why it is not being run")
    print("  Q8_0 (29 GB) is near-lossless against BF16 and would be a sound")
    print("  anchor. It does not fit 24 GB either: it would run with roughly")
    print("  7 GB of weights resident in system RAM and computed on the CPU,")
    print("  and this machine has 31.8 GB of RAM total. A full 200-chunk KL")
    print("  pass under that split is hours of a loaded, noisy machine - which")
    print("  this campaign's own quiet-machine rule forbids while any other")
    print("  measurement is in flight. Recorded as out of scope for this")
    print("  hardware rather than attempted and reported badly.")


if __name__ == "__main__":
    main()
