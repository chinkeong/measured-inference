"""Does every quoted figure still carry the condition it was measured under?

    python condition-check.py <file.html> [more files...]
    python condition-check.py --git <rev> <path> --repo <dir>   check history

WHY THIS EXISTS. Four defects in one session, 2026-08-25/26, all the same
shape: a CORRECT number quoted where its condition no longer held.

  11,396 MiB   lost "board VRAM, contains this machine's desktop" three
               sections downstream and became a card verdict telling every
               12 GB owner "No, use a smaller model" about a configuration
               that needs 10,497.
  2 of 75      lost "at temperature 0" and became a recommendation floor no
               reader running the shipped sampler could ever meet.
  prompt_n     lost "newly processed tokens, not depth" under cache_prompt.
  a recipe     lost "at 196,608 tokens" and was pasted into a -c 229376 block.

These survive review. The 12 GB row passed four gates and a 137-agent audit,
because every number in it was correct. Reading for correctness cannot find
them; only re-deriving a figure from its raw measurement can.

WHAT DOES NOT WORK, recorded so nobody rebuilds it. Two designs were tried and
thrown away before this one:

  (1) "Does this paragraph state its flags?" The 12 GB row states `-c 32768`
      and "drafter off" and passes. Flags were never what it dropped.
  (2) "Does every occurrence of a figure carry every qualifier any occurrence
      carries?" This demands a glossary definition repeat a table's conditions,
      produces pages of meaningless output, and buried the one defect it was
      built to find.

WHAT WORKS is tying qualifiers to the figure's UNIT and grouping them by the
reading they select between. "Board VRAM" and "allocation" are two readings of
one MiB figure and differ by the size of a desktop; "greedy" and "temperature
1.0" are two readings of one t/s figure and differ by 7x in spread. When one
occurrence picks a reading and another picks none, the second is unfalsifiable.

CHECK A is that comparison, and it is mechanical. CHECK B is a prompt rather
than a proof: a global omission - every occurrence silent, as with temperature
0 - has nothing to drift against, so it can only be caught by insisting the
words appear at all near a MEASURED chip.

Exit status is always 0. This reports for a human before publishing; a gate
that blocks a release on a heuristic gets switched off within a week.
"""

import argparse
import io
import os
import re
import subprocess
import sys
from collections import defaultdict

# (group name, which figures it applies to, [(pattern, reading it selects)])
GROUPS = [
    ("memory scope", r"MiB|GiB|\bGB\b",
     [(r"board\s+VRAM", "board VRAM"),
      (r"\ballocation\b|server's own", "allocation"),
      (r"\bdesktop\b|\breserve\b", "desktop-aware")]),
    ("sampler", r"\bt/s\b|tokens?\s*/\s*s|per second",
     [(r"\bgreedy\b", "greedy"),
      (r"temperature|\btemp\b", "temperature"),
      (r"top[-_ ]?p|top[-_ ]?k|\bsampler\b", "sampler named")]),
    ("failure kind", r"\bempt|blank answer|truncat",
     [(r"\bsilent\b", "silent"),
      (r"\bat cap\b|truncat", "at-cap"),
      (r"\bgreedy\b|temperature|\btemp\b", "sampler named")]),
]

MEASURED_CHIP = re.compile(r'class="(?:pv m|chip m)"[^>]*>\s*measured\s*<', re.I)
BLOCK = re.compile(r"<(p|td|li|dd)\b[^>]*>(.*?)</\1>", re.S | re.I)
TAGS = re.compile(r"<[^>]+>")
ENT = [("&nbsp;", " "), ("&mdash;", "-"), ("&ndash;", "-"), ("&amp;", "&"),
       ("&lt;", "<"), ("&gt;", ">"), ("&sect;", "S"), ("&plusmn;", "+/-"),
       ("&ldquo;", '"'), ("&rdquo;", '"'), ("&rsquo;", "'")]
SAMPLER_WORDS = re.compile(
    r"\bgreedy\b|temperature|\btemp\b|top[-_ ]?p|top[-_ ]?k|\bsampler\b", re.I)
SPEED_OR_RATE = re.compile(
    r"\bt/s\b|tokens?\s*/\s*s|empty answers?|blank answers?", re.I)
# a distinctive figure: comma-grouped thousands, or 3+ decimal places
FIGURE = re.compile(r"\b\d{1,3},\d{3}\b|\b\d+\.\d{3,}\b")


def plain(html):
    t = TAGS.sub(" ", html)
    for a, b in ENT:
        t = t.replace(a, b)
    return " ".join(t.split())


def blocks(src):
    out = []
    for m in BLOCK.finditer(src):
        inner = m.group(2)
        if BLOCK.search(inner):          # skip wrappers containing other blocks
            continue
        out.append((m.start(), plain(inner), inner))
    return out


def check_a(bs):
    """Origin picks a reading; a destination quoting the same figure picks none."""
    where = defaultdict(list)
    for pos, text, _ in bs:
        for f in set(FIGURE.findall(text)):
            where[f].append((pos, text))
    out = []
    for fig, occ in sorted(where.items()):
        if len(occ) < 2:
            continue
        for gname, unit_pat, members in GROUPS:
            rel = [(p, t) for p, t in occ if re.search(unit_pat, t, re.I)]
            if len(rel) < 2:
                continue
            hits = [(p, t, {n for pat, n in members if re.search(pat, t, re.I)})
                    for p, t in rel]
            stated = [h for h in hits if h[2]]
            silent = [h for h in hits if not h[2]]
            if stated and silent:
                out.append({
                    "figure": fig, "group": gname,
                    "origin_says": sorted(set().union(*[h[2] for h in stated])),
                    "silent": [h[1] for h in silent]})
    return out


def check_b(bs):
    """A MEASURED speed or failure-rate claim that names no sampler at all."""
    out = []
    for pos, text, inner in bs:
        if not MEASURED_CHIP.search(inner):
            continue
        if not SPEED_OR_RATE.search(text):
            continue
        if SAMPLER_WORDS.search(text):
            continue
        out.append(text)
    return out


# Blocks that RE-SUBTRACT a reserve from a figure whose own table already
# includes it. This is narrow on purpose. Check A tests VOCABULARY and cannot
# see this defect: the 12 GB row said "keep the reserve", so it picked a
# reading and passed. It did not omit the condition - it applied it TWICE. The
# defect is arithmetic, so the detector has to be arithmetic too.
BOARD_FIG = re.compile(r"\b(1[0-9],\d{3}|[89],\d{3})\b")
SUBTRACTS = re.compile(
    r"keep the reserve|minus the reserve|after .{0,20}reserve|"
    r"is what you have|leaves? (?:about )?\d", re.I)
NEEDS = re.compile(r"\bneeds?\b|\brequires?\b|\bover\b|\bshort\b", re.I)


def board_inclusive_figures(bs):
    """Figures whose own neighbourhood declares them board or total VRAM."""
    out = set()
    for _, text, _ in bs:
        if re.search(r"board\s+VRAM|contains? .{0,30}desktop|"
                     r"includes? .{0,30}desktop", text, re.I):
            out.update(BOARD_FIG.findall(text))
    return out


def check_c(bs):
    """WITHDRAWN 2026-08-26. Kept as a dated negative result, not deleted.

    The idea: flag a board-inclusive figure used where a reserve is subtracted
    again. Validated against the two published versions and it is BACKWARDS -
    it reports nothing on the buggy version and fires on the corrected one.

    Why it cannot work as written. A figure's board-inclusiveness is declared
    in the TABLE CAPTION ("Memory is board VRAM, so it contains this machine's
    desktop as well as the server"), and that caption never repeats the figure.
    So 11,396 is never marked board-inclusive by any text rule, while the
    CORRECTION - which says in plain words "11,396 is a board figure" - is.
    A detector that fires on the fix and stays silent on the fault is worse
    than none.

    Making it work needs table-structure parsing: attach a caption's scope to
    every cell beneath it, then follow each cell's figures wherever they are
    quoted. That is real work with an uncertain payoff, and it still would not
    have caught this one, because the misuse was three sections away from the
    table entirely.

    THE HONEST FINDING, which is the point of leaving this here: this defect
    class is NOT lintable. Three designs were tried - flags-present,
    qualifier-union, double-subtraction - and none catches it. What caught it
    was re-deriving the number from a fresh measurement. Checks A and B below
    remain useful for what they do see; nothing in this file substitutes for
    measuring the thing again.
    """
    return []


def report(path, src):
    bs = blocks(src)
    print("=" * 74)
    print(path)
    print("  %d readable blocks, %d 'measured' chips"
          % (len(bs), len(MEASURED_CHIP.findall(src))))

    a = check_a(bs)
    print("\n  CHECK A - figure quoted with NO reading, where the same figure")
    print("            picks one elsewhere")
    if not a:
        print("    nothing")
    seen = set()
    for f in a:
        key = (f["figure"], f["group"])
        if key in seen:
            continue
        seen.add(key)
        print("    %-9s [%s] elsewhere says %s; %d place(s) say none"
              % (f["figure"], f["group"], "/".join(f["origin_says"]),
                 len(f["silent"])))
        for t in f["silent"][:2]:
            print("        ...%s" % t[:150])

    b = check_b(bs)
    print("\n  CHECK B - MEASURED speed/rate claim naming no sampler (%d)" % len(b))
    for t in b[:6]:
        print("        ...%s" % t[:150])
    if len(b) > 6:
        print("        (%d more)" % (len(b) - 6))

    c = check_c(bs)
    print("\n  CHECK C - DOUBLE SUBTRACTION: a board-inclusive figure used in a")
    print("            block that also subtracts a desktop reserve")
    if not c:
        print("    nothing")
    for f in c:
        print("    *** %s" % ", ".join(f["figures"]))
        print("        %s" % f["text"][:280])
    return a, b, c


def main():
    # Windows consoles default to cp1252 and this page contains arrows, en
    # dashes and section signs. Printing one of them raises UnicodeEncodeError
    # mid-report and loses everything after it - the same defect that made
    # llama-tokenize return None silently earlier in this campaign.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--git", nargs=2, metavar=("REV", "PATH"))
    ap.add_argument("--repo", default=".")
    a = ap.parse_args()
    if a.git:
        rev, path = a.git
        src = subprocess.run(["git", "-C", a.repo, "show", "%s:%s" % (rev, path)],
                             capture_output=True, text=True,
                             encoding="utf-8", errors="replace").stdout
        if not src:
            sys.exit("could not read %s:%s" % (rev, path))
        report("%s @ %s" % (path, rev), src)
        return
    for p in a.paths:
        if not os.path.exists(p):
            print("missing: %s" % p)
            continue
        report(p, io.open(p, encoding="utf-8", errors="replace").read())


main()
