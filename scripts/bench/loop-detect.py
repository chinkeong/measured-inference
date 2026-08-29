"""D5 — a detector for the degeneration shapes D1-D4 cannot see.

    python loop-detect.py validate     # prove it on known cases first
    python loop-detect.py scan         # then run it over every transcript

WHY THIS EXISTS. This campaign ships four repetition detectors and they are all
EXACT-MATCH: immediate block repeats, identical line repeats, tail n-grams,
global repeat ratio. Three separate pieces of evidence say that is not enough.

  1. The blind judge panel (2026-08-24) found a story prompt that became an
     endless spelled-out number count - "one hundred and one, one hundred and
     two..." - at 1,682 tokens, nowhere near any cap. No block repeats, so D1-D4
     saw nothing. Three seats rated it 1.
  2. The same panel found a counter-incrementing shape - visitedMap21,
     visitedMap22 - where every line DIFFERS by a digit, which exact matching is
     blind to by construction.
  3. An independent tester (2026-08-25) reports that LOOPING is the failure mode
     that actually kills these files in agentic use: IQ1_M, Q2_K_XL and Q3_K_XL
     all failed by locking into loops rather than by being wrong.

The empty-answer audit added yesterday catches the SYMPTOM of the worst cases
(the model returns nothing) but not the SHAPE (it is looping). This names the
shape.

THE SIGNALS, deliberately orthogonal so no single quirk trips all of them:
  N1 digit-normalised immediate repeat - collapse every run of digits to '#'
     before looking for back-to-back block repeats. Catches counters.
  N2 line-skeleton repeat - strip digits, quoted strings and identifiers to a
     structural skeleton, then count the most common skeleton's share.
  N3 compression ratio - looping text compresses far better than prose. Cheap,
     global, and independent of the other two.
  N4 worst sliding-window type-token ratio - catches a collapse that happens in
     one region of an otherwise healthy answer, which a whole-text ratio hides.

THE CONTROL THAT MAKES IT USABLE. Two prompts in this suite (GSM8K[16] and
HumanEval[19]) produce low-diversity output at EVERY rung including the 4-bit
reference - they are legitimately repetitive tasks. A detector that flags those
is measuring the prompt, not the model. So the verdict is always reported
BESIDE the reference file's value for the same item, and `validate` proves the
separation before anything is believed.
"""

import glob
import json
import os
import re
import sys
import zlib
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
R21 = os.path.join(ROOT, "results", "qwen38-27b-blind", "data", "rule21")
LADDER = os.path.join(ROOT, "results", "qwen38-27b-blind",
                      "data", "quant-ladder", "bench")

_DIGITS = re.compile(r"\d+")
# The first validation run caught a real miss: N1 normalised DIGITS only, and
# the campaign's worst known loop counts in WORDS ("one hundred and one, one
# hundred and two..."), so it slipped straight through the one signal built to
# catch counters. Number-words are normalised too.
_NUMWORD = re.compile(
    r"\b(zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
    r"thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|"
    r"first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\b",
    re.I)
_STR = re.compile(r"(['\"]).*?\1")
_IDENT = re.compile(r"\b[A-Za-z_][A-Za-z_0-9]*\b")
_WORD = re.compile(r"[A-Za-z']+")
_FENCE = re.compile(r"```.*?```", re.S)


def _prose(text):
    """Text with fenced code removed.

    The second validation run flagged four answers on the 4-BIT REFERENCE file
    that are not loops at all: a dict literal mapping number words to digits, a
    doctest block, and two worked-example lists. Enumerated structure is what
    correct code and worked examples LOOK like, and the number-word
    normalisation added for N1 turns "'one': 1, 'two': 2" into "'#': #, '#': #"
    - manufacturing the very pattern it was built to catch. So the two
    STRUCTURAL signals run on prose only; the two GLOBAL ones (N3, N4) see the
    whole answer, because a genuine runaway drags those down wherever it lives.
    """
    return _FENCE.sub(" ", text)


def n1_digit_normalised_repeat(text, min_k=3, max_k=40, min_reps=3):
    """Back-to-back repeats after collapsing digit runs. Catches counters."""
    ws = _NUMWORD.sub("#", _DIGITS.sub("#", _prose(text))).split()
    n, best = len(ws), 0
    for k in range(min_k, max_k + 1):
        i = 0
        while i + 2 * k <= n:
            if ws[i:i + k] == ws[i + k:i + 2 * k]:
                reps, j = 2, i + 2 * k
                while j + k <= n and ws[j:j + k] == ws[i:i + k]:
                    reps += 1
                    j += k
                if reps >= min_reps:
                    best = max(best, reps * k)   # words covered by the loop
                i = j
            else:
                i += 1
    return best / n if n else 0.0                 # fraction of the answer looping


def n2_line_skeleton_share(text):
    """Share of non-trivial lines collapsing to one structural skeleton."""
    lines = [l.strip() for l in _prose(text).splitlines() if len(l.strip()) > 12]
    if len(lines) < 6:
        return 0.0
    skel = []
    for l in lines:
        s = _STR.sub("S", l)
        s = _DIGITS.sub("#", s)
        s = _IDENT.sub("I", s)
        skel.append(re.sub(r"\s+", " ", s))
    top = Counter(skel).most_common(1)[0][1]
    return top / len(lines)


def n3_compression_ratio(text):
    """Compressed size over raw. Looping text compresses hard."""
    b = text.encode("utf-8", "ignore")
    if len(b) < 400:
        return 1.0
    return len(zlib.compress(b, 6)) / len(b)


def n4_worst_window_ttr(text, win=120, step=40):
    """Lowest type-token ratio over any sliding window of `win` words."""
    w = [x.lower() for x in _WORD.findall(text)]
    if len(w) < win * 2:
        return 1.0
    worst = 1.0
    for i in range(0, len(w) - win, step):
        seg = w[i:i + win]
        worst = min(worst, len(set(seg)) / len(seg))
    return worst


def signals(text):
    return {
        "n1_loop_frac": round(n1_digit_normalised_repeat(text), 4),
        "n2_skeleton": round(n2_line_skeleton_share(text), 4),
        "n3_compress": round(n3_compression_ratio(text), 4),
        "n4_worst_ttr": round(n4_worst_window_ttr(text), 4),
    }


# Thresholds are set in validate() against known cases and the reference
# control, NOT chosen a priori. Changing them requires re-running validate.
# Two thresholds per signal, both set FROM the validation run rather than a
# priori. WARN is where the reference file's worst answer sits plus margin;
# STRONG is set so that each known degeneration clears it on its own.
# Observed on the 4-bit reference (75 answers): n2 max 0.2222, n3 min 0.3698,
# n4 min 1.0000 on the control items. Observed on the known loops: n2 0.5217
# and 0.7645, n3 0.2021 and 0.2416, n4 0.1167.
WARN   = {"n1_loop_frac": 0.10, "n2_skeleton": 0.32, "n3_compress": 0.30,
          "n4_worst_ttr": 0.45}
STRONG = {"n1_loop_frac": 0.20, "n2_skeleton": 0.45, "n3_compress": 0.26,
          "n4_worst_ttr": 0.30}


def _fires(s, key, table):
    lo = key in ("n3_compress", "n4_worst_ttr")   # these fire when LOW
    return s[key] <= table[key] if lo else s[key] >= table[key]


def verdict(s):
    """One signal far past threshold is a verdict; two mild ones also are.

    The first validation run showed every known degeneration firing exactly ONE
    signal, but firing it hard - the counting story at n4=0.1167 against a
    reference minimum of 1.0000, the 100-set answer at n2=0.7645 against a
    reference maximum of 0.2222. A rule demanding two agreeing signals scored
    all three as mere hints. Requiring corroboration is right when signals are
    weak and wrong when one is unambiguous, so both routes are allowed.
    """
    names = {"n1_loop_frac": "N1-counter-loop", "n2_skeleton": "N2-line-skeleton",
             "n3_compress": "N3-compresses", "n4_worst_ttr": "N4-vocab-collapse"}
    # N1 and N2 are structural and, on code, noisy - they need corroboration.
    # N3 and N4 are global and separated cleanly on the control, so either may
    # stand alone when it is strong.
    SOLO = ("n3_compress", "n4_worst_ttr")
    strong = [names[k] for k in names if _fires(s, k, STRONG)]
    solo_strong = [names[k] for k in SOLO if _fires(s, k, STRONG)]
    warn = [names[k] for k in names if _fires(s, k, WARN)]
    if solo_strong or len(strong) >= 2:
        return "LOOP", [x + "!" for x in strong] + [w for w in warn if w not in strong]
    if len(warn) >= 2:
        return "LOOP", warn
    if strong:
        return "hint", [x + "!" for x in strong]
    return ("hint" if warn else "clean"), warn


def _load(path, ds=None):
    j = json.load(open(path, encoding="utf-8"))
    out = {}
    for name, items in j.get("generations", {}).items():
        if ds and name != ds:
            continue
        for it in items:
            out[(name, int(it["index"]))] = str(it.get("response", ""))
    return out


def validate():
    """Prove the detector on cases whose truth is already established."""
    arm = {}
    for tag in ("low", "medium", "xhigh"):
        f = [x for x in sorted(glob.glob(os.path.join(R21, "arm-%s-Qwen*_transcripts.json" % tag)))]
        if f:
            arm[tag] = _load(f[-1])
    ref = None
    f = sorted(glob.glob(os.path.join(LADDER, "arm-qwen-iq4xs-anchor-*_transcripts.json")))
    if f:
        ref = _load(f[-1])

    print("KNOWN DEGENERATIONS - the judge panel rated every one of these 1-4.")
    print("%-34s %-9s %-9s %-9s %-9s  %s" % ("case", "N1 loop", "N2 skel",
                                             "N3 comp", "N4 ttr", "verdict"))
    known = [
        ("low MT-Bench[2] counting story", arm.get("low", {}).get(("MT-Bench", 2))),
        ("xhigh ALPACA[16] 100 sets", arm.get("xhigh", {}).get(("ALPACA", 16))),
        ("low ALPACA[23] ripple/crash", arm.get("low", {}).get(("ALPACA", 23))),
    ]
    for label, t in known:
        if not t:
            print("%-34s (transcript not found)" % label)
            continue
        s = signals(t)
        v, h = verdict(s)
        print("%-34s %-9.4f %-9.4f %-9.4f %-9.4f  %s %s"
              % (label, s["n1_loop_frac"], s["n2_skeleton"], s["n3_compress"],
                 s["n4_worst_ttr"], v, ",".join(h)))

    print("\nTHE CONTROL - items that look repetitive at EVERY rung, reference file.")
    print("If the detector fires on these it is measuring the PROMPT, not the model.")
    for key in (("GSM8K", 16), ("HumanEval", 19), ("MBPP", 0), ("GSM8K", 0)):
        t = (ref or {}).get(key)
        if not t:
            continue
        s = signals(t)
        v, h = verdict(s)
        print("%-34s %-9.4f %-9.4f %-9.4f %-9.4f  %s %s"
              % ("reference %s[%d]" % key, s["n1_loop_frac"], s["n2_skeleton"],
                 s["n3_compress"], s["n4_worst_ttr"], v, ",".join(h)))

    print("\nBASELINE - every reference-file answer, to size the false-positive rate.")
    if ref:
        vs = [verdict(signals(t))[0] for t in ref.values() if t.strip()]
        c = Counter(vs)
        print("  reference file, %d non-empty answers: %s" % (len(vs), dict(c)))
        print("  FALSE POSITIVES (LOOP on the 4-bit reference): %d" % c.get("LOOP", 0))


def scan():
    files = sorted(glob.glob(os.path.join(LADDER, "arm-qwen-*_transcripts.json")))
    files = [f for f in files if "cap32k" not in f]
    print("%-13s %5s %6s %6s  %s" % ("file", "n", "LOOP", "hint", "flagged items"))
    for f in files:
        j = json.load(open(f, encoding="utf-8"))
        lab = j.get("model_label", os.path.basename(f)).replace("Qwen3.8-27B-", "")
        loops, hints, flagged, n = 0, 0, [], 0
        for ds, items in j.get("generations", {}).items():
            for it in items:
                t = str(it.get("response", ""))
                if not t.strip():
                    continue
                n += 1
                v, h = verdict(signals(t))
                if v == "LOOP":
                    loops += 1
                    flagged.append("%s[%d]:%s" % (ds, it["index"], "+".join(x[:2] for x in h)))
                elif v == "hint":
                    hints += 1
        print("%-13s %5d %6d %6d  %s" % (lab, n, loops, hints,
                                         " ".join(flagged[:6]) or "-"))


USAGE = """\
D5, the detector for the degeneration shapes exact matching cannot see: a
digit-normalised immediate repeat, a line-skeleton share, a compression ratio
and a worst-window type-token ratio.

    python scripts/bench/loop-detect.py <subcommand>

Subcommands (default: validate):
  validate   prove the detector on the known cases first
  scan       run it over every quant-ladder transcript

Positional arguments: the subcommand, and nothing else. No environment
variables. No server, no model, no GPU - this reads transcripts and prints.

Example:
  python scripts/bench/loop-detect.py validate

Reads results/qwen38-27b-blind/data/rule21/ and .../data/quant-ladder/bench/
transcript JSON. Writes no file; the verdict goes to stdout, always beside the
reference file's value for the same item.
"""


if __name__ == "__main__":
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        print(USAGE.rstrip())
        raise SystemExit(0)
    {"validate": validate, "scan": scan}[sys.argv[1] if len(sys.argv) > 1 else "validate"]()
