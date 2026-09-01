#!/usr/bin/env python3
"""Where does quality fall off a cliff, and what is the smallest file still worth
running? Answers both, or says plainly that this roster cannot.

    python scripts/report/fidelity-knee.py --slug <slug>
    python scripts/report/fidelity-knee.py --slug <slug> --vram-gb 12,16,24
    python scripts/report/fidelity-knee.py --ladder <kld-ladder.json>   # any campaign

THE QUESTION THIS ANSWERS, in the reader's words: "I have 12 GB. What is the
smallest file that still behaves like the model the vendor published?" That is
the most common reason anyone reads a quant table, and it is the one a ranked
list does not answer -- a ranking says which is best, not where the cliff is.

WHY THIS IS NOT scripts/quant-ladder/summarize.py's KNEE. That one is good and
this does not replace it. Two differences earned by measurement:

  1. IT KNEES ON FIDELITY, NOT PERPLEXITY. summarize.py's slope is
     %PPL-added per GiB-saved. Measured 2026-09-01 on Ornith-1.5-9B, perplexity
     ranked three quants in EXACTLY REVERSE fidelity order -- Q4_K_M scored 1.08
     PPL BETTER than the unquantised weights it was made from while diverging
     13x further in KLD. A knee computed on PPL can therefore point at the wrong
     rung, or at no rung. KLD against the unquantised model is the honest axis;
     same-top-1 agreement is the interpretable one (proposed rule 33).

  2. IT REFUSES TO CONFUSE "NO KNEE" WITH "CANNOT SEE THE KNEE". summarize.py
     prints "No knee yet" when no segment crosses the factor. That reading is
     ambiguous: a flat curve and a roster too sparse to resolve one look
     identical. This tool separates them and, when the rungs are too far apart,
     says WHERE the knee must lie and WHICH files would close the gap. Rule 2 --
     no reader may measure less than the report promised them -- applies to the
     absence of a finding as much as to a finding.

WHAT "USABLE" MEANS HERE. Nothing is invented: no fidelity threshold is asserted.
The knee is derived from the data (the segment whose marginal fidelity cost per
bit first exceeds KNEE_FACTOR x the median of the segments above it), and the
"smallest still worth running" is the smallest rung ABOVE that knee. Where a
reader wants a harder line, same-top-1 is printed for every rung so they can draw
their own and see what it costs.
"""
import argparse, glob, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "scripts", "lib"))

KNEE_FACTOR = 2.0
# A segment wider than this cannot localise a knee inside itself: the curve may
# turn anywhere in the gap. Chosen as the median rung spacing of the reference
# 27B ladder (8 rungs over 1.835-3.895 bpw ~ 0.29 bpw apart); anything much
# wider is a bracket, not a measurement.
RESOLVE_BPW = 0.60


def load_campaign(slug):
    """Rungs from a campaign: bpw and file size from model-*.json, fidelity from
    whichever of the KLD artefacts this campaign wrote."""
    base = os.path.join(ROOT, "results", slug)
    rungs = {}
    for f in sorted(glob.glob(os.path.join(base, "model-*.json"))):
        d = json.load(open(f))
        label = os.path.basename(f)[len("model-"):-len(".json")]
        params = d.get("params_total")
        size = d.get("size_bytes")
        if not size:
            mp = os.path.join(ROOT, "models", d.get("file") or "")
            size = os.path.getsize(mp) if os.path.exists(mp) else None
        if params and size:
            rungs[label] = {"label": label, "bpw": size * 8.0 / params,
                            "gb": size / 1e9, "file": d.get("file")}
    for name in ("kld-full-294912.json", "kld-vs-bf16.json"):
        p = os.path.join(base, "data", name)
        if not os.path.exists(p):
            continue
        arms = json.load(open(p)).get("arms", {})
        for label, rec in arms.items():
            if label in rungs and rec.get("mean_kld") is not None:
                rungs[label].setdefault("mean_kld", rec["mean_kld"])
                rungs[label].setdefault("same_top", rec.get("same_top_pct"))
    for name in ("ppl-rule6-ladder.json",):
        p = os.path.join(base, "data", name)
        if os.path.exists(p):
            for label, rec in json.load(open(p)).get("arms", {}).items():
                if label in rungs:
                    rungs[label].setdefault("ppl", rec.get("ppl"))
    return [r for r in rungs.values() if r.get("mean_kld") is not None]


def load_ladder(path):
    """Rungs from a quant-ladder kld json (the reference campaign's shape)."""
    d = json.load(open(path))
    out = []
    for r in d.get("rows", []):
        if r.get("bpw") and r.get("mean_kld") is not None:
            out.append({"label": os.path.basename(str(r.get("file") or "?")),
                        "bpw": r["bpw"], "mean_kld": r["mean_kld"],
                        "same_top": r.get("same_top_p_pct"), "gb": None})
    return out


def flag_outliers(rungs):
    """A rung whose fidelity is WORSE than a smaller rung is not on this ladder.

    Fidelity must improve with bits within one quantisation family. A rung that
    breaks that is a different KIND of file -- a quantisation-aware-trained one,
    a vendor variant, a different base checkpoint -- and it cannot be compared on
    a bits axis with the rest. Measured 2026-09-01 on the reference 27B ladder:
    QAT-Q2_0 at 2.595 bpw carries KLD 0.297 while the SMALLER UD-IQ2_S at 2.481
    carries 0.141. Left in, it produced a nonsense -14.8x segment AND set the
    knee, because the 6.9x spike that triggered it was measured against the
    outlier rather than against the curve. An outlier that sets the answer is
    worse than one that is merely visible.
    """
    out = []
    for i, r in enumerate(sorted(rungs, key=lambda x: -x["bpw"])):
        smaller = [q for q in rungs if q["bpw"] < r["bpw"]]
        if smaller and min(q["mean_kld"] for q in smaller) < r["mean_kld"]:
            better = min(smaller, key=lambda q: q["mean_kld"])
            out.append((r, better))
    return out


def analyse(rungs):
    rungs = sorted(rungs, key=lambda r: -r["bpw"])
    seg = []
    for a, b in zip(rungs, rungs[1:]):
        dbpw = a["bpw"] - b["bpw"]
        dkld = b["mean_kld"] - a["mean_kld"]
        if dbpw > 0:
            seg.append({"from": a, "to": b, "dbpw": dbpw, "dkld": dkld,
                        "slope": dkld / dbpw})
    knee = None
    for i, s in enumerate(seg):
        above = sorted(x["slope"] for x in seg[:i])
        med = above[len(above) // 2] if above else None
        s["median_above"] = med
        s["ratio"] = (s["slope"] / med) if med and med > 0 else None
        if knee is None and med and med > 0 and s["slope"] >= KNEE_FACTOR * med:
            knee = s
    return rungs, seg, knee


def verdict(rungs, seg, knee):
    """RESOLVED / BRACKETED / NOT-REACHED -- and never silence."""
    if not seg:
        return ("NOT-MEASURABLE",
                "only %d rung(s) with fidelity data; a knee needs at least two "
                "segments, i.e. three rungs." % len(rungs))
    if knee is None:
        widest = max(seg, key=lambda s: s["dbpw"])
        if widest["dbpw"] > RESOLVE_BPW:
            return ("BRACKETED",
                    "no segment crossed %.1fx the median slope, but the rungs are "
                    "too far apart to conclude the curve is flat: the widest gap "
                    "is %.2f bpw (%s -> %s). If a knee exists it is inside a gap "
                    "this roster did not sample."
                    % (KNEE_FACTOR, widest["dbpw"], widest["from"]["label"],
                       widest["to"]["label"]))
        return ("NOT-REACHED",
                "no segment crossed %.1fx the median slope and the rungs are "
                "closely spaced (widest gap %.2f bpw), so the curve really is "
                "still flat at the smallest rung measured (%.3f bpw)."
                % (KNEE_FACTOR, widest["dbpw"], rungs[-1]["bpw"]))
    if knee["dbpw"] > RESOLVE_BPW:
        return ("BRACKETED",
                "the cliff is inside the %s -> %s segment, but that segment spans "
                "%.2f bpw -- too wide to say where in it the curve turns. The "
                "knee is SOMEWHERE BETWEEN %.3f and %.3f bpw."
                % (knee["from"]["label"], knee["to"]["label"], knee["dbpw"],
                   knee["to"]["bpw"], knee["from"]["bpw"]))
    return ("RESOLVED",
            "the curve turns at %s (%.3f bpw): the next segment costs %.4f KLD "
            "per bit, %.1fx the median of every segment above it."
            % (knee["from"]["label"], knee["from"]["bpw"], knee["slope"],
               knee["ratio"]))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slug")
    ap.add_argument("--ladder")
    ap.add_argument("--vram-gb", default="8,12,16,24")
    ap.add_argument("--kv-gb", type=float, default=1.0,
                    help="KV + projector + buffers to reserve per fit (GB)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--keep-outliers", action="store_true",
                    help="keep rungs whose fidelity is worse than a smaller "
                         "rung. Off by default: such a rung is a different kind "
                         "of file and will set a false knee.")
    a = ap.parse_args()
    if not a.slug and not a.ladder:
        ap.error("give --slug or --ladder")
    rungs = load_ladder(a.ladder) if a.ladder else load_campaign(a.slug)
    outliers = flag_outliers(rungs)
    if outliers and not a.keep_outliers:
        rungs = [r for r in rungs if r not in [o[0] for o in outliers]]
    if len(rungs) < 2:
        print("Not enough rungs carrying fidelity data (%d). A knee needs three."
              % len(rungs))
        return 2
    rungs, seg, knee = analyse(rungs)
    state, why = verdict(rungs, seg, knee)

    print("# Fidelity knee — where quality falls off, and the smallest file worth running\n")
    for bad, better in outliers:
        print("**OFF-LADDER: %s** (%.3f bpw, KLD %.6f) is worse than the SMALLER "
              "%s (%.3f bpw, KLD %.6f). Fidelity must improve with bits inside one "
              "quantisation family, so this is a different kind of file — QAT, a "
              "vendor variant, or another base checkpoint — and it cannot sit on a "
              "bits axis with the rest. %s from the knee analysis (--keep-outliers "
              "to override).\n"
              % (bad["label"], bad["bpw"], bad["mean_kld"], better["label"],
                 better["bpw"], better["mean_kld"],
                 "Kept" if a.keep_outliers else "EXCLUDED"))
    print("| rung | bpw | file GB | mean KLD | same top-1 |")
    print("|---|---|---|---|---|")
    for r in rungs:
        print("| %s | %.3f | %s | %.6f | %s |"
              % (r["label"], r["bpw"],
                 ("%.2f" % r["gb"]) if r.get("gb") else "—",
                 r["mean_kld"],
                 ("%.1f%%" % r["same_top"]) if r.get("same_top") else "—"))
    print("\n| segment | bpw dropped | KLD added | KLD per bit | vs median above |")
    print("|---|---|---|---|---|")
    for s in seg:
        print("| %s → %s | %.3f | %+.6f | %.6f | %s |"
              % (s["from"]["label"], s["to"]["label"], s["dbpw"], s["dkld"],
                 s["slope"], ("%.1fx" % s["ratio"]) if s.get("ratio") else "—"))

    print("\n## VERDICT: %s\n" % state)
    print(why + "\n")
    if state == "BRACKETED":
        lo = knee["to"]["bpw"] if knee else min(
            s["to"]["bpw"] for s in seg if s["dbpw"] == max(x["dbpw"] for x in seg))
        hi = knee["from"]["bpw"] if knee else max(
            s["from"]["bpw"] for s in seg if s["dbpw"] == max(x["dbpw"] for x in seg))
        print("**The report must say the knee is BETWEEN %.2f and %.2f bpw and "
              "that this campaign did not resolve it.** A roster spaced to show "
              "THAT quantisation hurts is not spaced to show WHERE it starts "
              "hurting, and a reader sizing a file to their VRAM needs the "
              "second. Closing it means laddering a quant inside that range.\n"
              % (lo, hi))

    print("## Smallest file worth running, by VRAM budget\n")
    print("Reserving %.1f GB for KV, projector and compute buffers. "
          "'Above knee' is the data's own verdict, not a threshold this tool "
          "invented.\n" % a.kv_gb)
    print("| VRAM | largest that fits | bpw | mean KLD | same top-1 | above knee? |")
    print("|---|---|---|---|---|---|")
    kneebpw = knee["from"]["bpw"] if knee else None
    for v in [float(x) for x in a.vram_gb.split(",")]:
        fit = [r for r in rungs if r.get("gb") and r["gb"] + a.kv_gb <= v]
        if not fit:
            print("| %.0f GB | nothing on this roster fits | — | — | — | — |" % v)
            continue
        best = max(fit, key=lambda r: r["bpw"])
        ok = ("yes" if kneebpw and best["bpw"] >= kneebpw
              else ("BELOW" if kneebpw else "unknown — knee unresolved"))
        print("| %.0f GB | %s | %.3f | %.6f | %s | %s |"
              % (v, best["label"], best["bpw"], best["mean_kld"],
                 ("%.1f%%" % best["same_top"]) if best.get("same_top") else "—", ok))
    if a.json:
        print("\n" + json.dumps({"state": state, "why": why,
                                 "rungs": rungs, "segments": seg}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
