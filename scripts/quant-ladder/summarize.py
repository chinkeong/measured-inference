"""Render the quant-ladder curve, the detector matrix and the knee.

    python summarize.py [--out <report.md>]

Reads the two ledgers the runner writes:
    <outdir>/results.txt    RESULT / RIGGATE / RIGPAIR / PASS2-ENABLE / NOTE
    <outdir>/detectors.txt  DETECT

Everything printed here is derived arithmetic over measured numbers; nothing is
estimated. Two facts govern how the rows may be read:

  * Within ONE model's ladder, raw PPL ranks the rungs (rule 6).
  * ACROSS model families it does not - different tokenizers cut the same text
    into different token counts, so equal-text PPL compares nothing. The
    cross-model row is comparable on BITS-PER-BYTE and on scored benchmarks
    only, and is printed with its PPL parenthesised to keep that visible.

The knee: for each adjacent pair the marginal cost of shrinking is
    slope = (percent PPL increase) / (GiB saved)
The knee is the last rung before the first slope that is >= KNEE_FACTOR x the
median slope of every segment above it - i.e. where buying another GiB of disk
saving starts costing disproportionately more quality.
"""

import argparse
import json
import math
import os
import re
import sys

OUTDIR = (r"E:\AI\measured-inference\results\qwen38-27b-blind"
          r"\data\quant-ladder")
MANIFEST = r"E:\AI\measured-inference\scripts\quant-ladder\ladder-manifest.json"
KNEE_FACTOR = 2.0


def parse_kv(line):
    d = {}
    for part in line.split("|"):
        part = part.strip()
        m = re.match(r"^([A-Za-z0-9_]+)=(.*)$", part)
        if m:
            d[m.group(1)] = m.group(2).strip()
    return d


def load_ledger(path, tag):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            m = re.match(r"^\ufeff?" + tag + r"\s+(\S+)\s*\|(.*)$", line)
            if not m:
                continue
            d = parse_kv(m.group(2))
            d["name"] = m.group(1)
            d["_raw"] = line
            rows.append(d)
    return rows


def fnum(d, k, default=None):
    v = d.get(k)
    if v is None:
        return default
    try:
        return float(v)
    except ValueError:
        return default


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default=OUTDIR)
    ap.add_argument("--manifest", default=MANIFEST)
    ap.add_argument("--json", action="store_true", help="dump machine-readable json too")
    args = ap.parse_args()

    # utf-8-sig: PowerShell 5.1's Set-Content -Encoding utf8 stamps a BOM, which
    # ConvertFrom-Json tolerates and Python's json.load does not.
    man = json.load(open(args.manifest, encoding="utf-8-sig"))
    order = {r["name"]: r["order"] for r in man["rungs"]}
    roles = {r["name"]: r["role"] for r in man["rungs"]}

    res = load_ledger(os.path.join(args.outdir, "results.txt"), "RESULT")
    det = {d["name"]: d for d in load_ledger(os.path.join(args.outdir, "detectors.txt"), "DETECT")}
    if not res:
        print("no RESULT lines yet")
        return

    # A QUARANTINE / WITHDRAWN line makes a rung's perplexity-derived numbers
    # unpublishable. Enforced HERE, in the renderer, so no later edit or lapse of
    # memory can leak a withdrawn number into a table: the row still appears (the
    # reader must know the measurement was attempted) but PPL and bits-per-byte
    # are replaced by the reason they were pulled.
    quarantined = {}
    for tag in ("QUARANTINE", "WITHDRAWN"):
        for q in load_ledger(os.path.join(args.outdir, "results.txt"), tag):
            body = q["_raw"].split("|", 1)[1].strip() if "|" in q["_raw"] else ""
            quarantined[q["name"]] = (tag, body)
    # keep only the newest RESULT per rung (a re-run supersedes its predecessor)
    newest = {}
    for r in res:
        newest[r["name"]] = r
    res = list(newest.values())

    for r in res:
        r["order"] = order.get(r["name"], 99)
        r["role"] = r.get("role", roles.get(r["name"], "?"))
    res.sort(key=lambda r: r["order"])

    # the qwen ladder: everything measured with the qwen tokenizer, PPL-rankable.
    # A quarantined rung is pulled out of BOTH tables - it cannot rank anything.
    ladder = [r for r in res
              if r.get("ppl_comparable", "yes") == "yes" and r["name"] not in quarantined]
    cross = [r for r in res
             if r.get("ppl_comparable", "yes") != "yes" and r["name"] not in quarantined]
    anchor = next((r for r in ladder if r["name"] == "UD-IQ4_XS"), None)

    print("## The ladder\n")
    hdr = ("| rung | role | GiB | bits/weight | PPL +/- err | vs IQ4_XS | "
           "bits/byte | GiB saved | %PPL/GiB | detectors |")
    print(hdr)
    print("|" + "---|" * 10)
    prev = None
    seg = []
    for r in ladder:
        gib = fnum(r, "GiB")
        ppl = fnum(r, "PPL")
        err = fnum(r, "err")
        bpw = fnum(r, "bpw")
        bpb = fnum(r, "bpb")
        vs = ""
        if anchor and fnum(anchor, "PPL"):
            vs = "%+.2f%%" % (100.0 * (ppl - fnum(anchor, "PPL")) / fnum(anchor, "PPL"))
        saved = slope = ""
        if prev is not None:
            dg = fnum(prev, "GiB") - gib
            dp = 100.0 * (ppl - fnum(prev, "PPL")) / fnum(prev, "PPL")
            if dg > 0:
                saved = "%.2f" % dg
                slope = "%.2f" % (dp / dg)
                seg.append((prev["name"], r["name"], dp / dg, dp, dg))
        dv = det.get(r["name"], {})
        dtxt = dv.get("verdict", "-")
        if dtxt not in ("-", "PASS"):
            dtxt = "%s (rep=%s json=%s fence=%s)" % (dtxt, dv.get("rep", "?"),
                                                    dv.get("json", "?"), dv.get("fence", "?"))
        print("| %s | %s | %.3f | %.3f | %.4f +/- %.5f | %s | %.4f | %s | %s | %s |"
              % (r["name"], r["role"], gib, bpw, ppl, err, vs, bpb, saved, slope, dtxt))
        prev = r

    if cross:
        print("\n## Cross-model row (rule 6: PPL is NOT comparable here)\n")
        print("| model | GiB | bits/weight | (PPL, own tokenizer) | tokens | bits/byte | detectors |")
        print("|" + "---|" * 7)
        for r in cross:
            dv = det.get(r["name"], {})
            print("| %s | %.3f | %.3f | (%.4f +/- %.5f) | %s | %.4f | %s |"
                  % (r["name"], fnum(r, "GiB"), fnum(r, "bpw"), fnum(r, "PPL"),
                     fnum(r, "err"), r.get("tokens", "?"), fnum(r, "bpb"),
                     dv.get("verdict", "-")))
        if anchor:
            print("\nbits/byte is the tokenizer-independent quantity: lower is better, "
                  "and it is the ONLY perplexity-derived number that may be compared "
                  "across the two families.")

    if seg:
        print("\n## Marginal cost of shrinking\n")
        print("| segment | GiB saved | %PPL added | %PPL per GiB | vs median above |")
        print("|" + "---|" * 5)
        knee = None
        for i, (a, b, sl, dp, dg) in enumerate(seg):
            above = [s[2] for s in seg[:i]]
            med = sorted(above)[len(above) // 2] if above else None
            ratio = ("%.1fx" % (sl / med)) if med and med > 0 else "-"
            if knee is None and med and med > 0 and sl >= KNEE_FACTOR * med:
                knee = (a, b, sl, med)
            print("| %s -> %s | %.2f | %+.2f | %.2f | %s |" % (a, b, dg, dp, sl, ratio))
        print("")
        if knee:
            print("**KNEE: %s.** The %s -> %s segment costs %.2f %%PPL per GiB, "
                  "%.1fx the median %.2f of every segment above it. %s is the last "
                  "rung before the curve turns up."
                  % (knee[0], knee[0], knee[1], knee[2], knee[2] / knee[3], knee[3], knee[0]))
        else:
            print("**No knee yet**: no segment has reached %.1fx the median slope "
                  "of the segments above it." % KNEE_FACTOR)

    if det:
        print("\n## Detector matrix\n")
        print("| rung | verdict | D1 immediate-loop | D2 line-loop | D3 tail-ngram | "
              "D4 global-repeat | JSON echo | fenced block | probe-A tokens | t/s |")
        print("|" + "---|" * 10)
        for r in res:
            d = det.get(r["name"])
            if not d:
                continue
            print("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |"
                  % (r["name"], d.get("verdict", "?"),
                     d.get("D1_immediate", "?"), d.get("D2_line", "?"),
                     d.get("D3_tailngram", "?"), d.get("D4_globalrep", "?"),
                     d.get("json", "?"), d.get("fence", "?"),
                     d.get("tokA", "?"), d.get("tpsA", "?")))

    # the equal-budget candidate: smallest detector-PASSING qwen rung
    passing = [r for r in ladder
               if det.get(r["name"], {}).get("verdict") in ("PASS", "REVIEW")]
    if passing:
        smallest = min(passing, key=lambda r: fnum(r, "GiB"))
        print("\nSmallest detector-passing 27B rung: **%s** at %.3f GiB "
              "(PPL %.4f, %+.2f%% vs IQ4_XS)"
              % (smallest["name"], fnum(smallest, "GiB"), fnum(smallest, "PPL"),
                 100.0 * (fnum(smallest, "PPL") - fnum(anchor, "PPL")) / fnum(anchor, "PPL")
                 if anchor else 0.0))

    if quarantined:
        print("\n## Withdrawn rows (measured, NOT publishable)\n")
        for name, (tag, why) in quarantined.items():
            r = next((x for x in res if x["name"] == name), None)
            gib = ("%.3f GiB" % fnum(r, "GiB")) if r else "?"
            dv = det.get(name, {}).get("verdict", "-")
            print("| %s | %s | PPL: **%s** | bits/byte: **%s** | detectors: %s |"
                  % (name, gib, tag, tag, dv))
            print("\n> %s\n" % why)

    gates = load_ledger(os.path.join(args.outdir, "results.txt"), "RIGGATE")
    pairs = load_ledger(os.path.join(args.outdir, "results.txt"), "RIGPAIR")
    if gates or pairs:
        print("\n## Rig gates\n")
        for g in gates + pairs:
            print("- `%s`" % g["_raw"])

    if args.json:
        print("\n<!--JSON\n" + json.dumps({"ladder": ladder, "cross": cross,
                                          "detectors": det}, indent=1) + "\nJSON-->")


main()
