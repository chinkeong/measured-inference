#!/usr/bin/env python3
"""Did a published page's prose actually go through the prose writer?

WHY THIS IS A GATE AND NOT A NOTE. AGENTS.md routes prose work to
methodology/WRITING.md, and that file's first section says published prose
should be written by Claude Opus 4.6 because the campaign model "drifts toward
the changelog tone this page has already been corrected for three times."

On 2026-09-02 the orchestrating model grepped WRITING.md's section list, saw
that heading printed in its own terminal, and then decided to write the page
itself anyway -- justifying it by citing section 6 ("the writer may not decide
what is true"), which constrains the WRITER's role and says nothing about who
should draft. The routing table worked. A heading and a preference did not
survive contact with a model that had already decided.

So the preference is now checkable. A page that names no writer run is not
refused -- WRITING.md section 1 is explicit that an unavailable model is never
a reason to leave a measurement unpublished -- but it must SAY SO, in the page
and in the campaign log, which is exactly the disclosure the fallback clause
already requires and which nobody remembers to write.

    python scripts/verify/writer-provenance.py [--slug SLUG]
"""
import argparse
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))


def check(slug):
    """(ok, [lines]) for one campaign."""
    root = os.path.join(REPO, "results", slug)
    page = os.path.join(root, "index.html")
    out = []
    if not os.path.exists(page):
        return None, ["%s: no index.html yet -- nothing to check" % slug]

    # Evidence a writer ran: a brief, a captured writer output, or an explicit
    # in-page disclosure that it did not.
    briefs = glob.glob(os.path.join(root, "work", "*brief*.md"))
    runs = glob.glob(os.path.join(root, "work", "writer*", "*")) + \
        glob.glob(os.path.join(root, "work", "*writer*.out")) + \
        glob.glob(os.path.join(root, "work", "*writer*.log"))
    html = open(page, encoding="utf-8", errors="replace").read()
    # The fallback disclosure WRITING.md section 1 already requires.
    disclosed = re.search(
        r"(opus\s*4\.?6[^<]{0,80}(unavailable|not available|could not))"
        r"|((unavailable|not available)[^<]{0,80}opus\s*4\.?6)",
        html, re.I)

    if briefs or runs:
        out.append("  writer provenance: %d brief(s), %d captured run(s)"
                   % (len(briefs), len(runs)))
        return True, out
    if disclosed:
        out.append("  writer provenance: no brief on disk, but the page "
                   "DISCLOSES that the writer was unavailable -- allowed by "
                   "WRITING.md section 1")
        return True, out
    out.append("  index.html exists (%d bytes) and there is NO evidence the "
               "prose writer was used:" % len(html))
    out.append("    - no results/%s/work/*brief*.md" % slug)
    out.append("    - no captured writer output under results/%s/work/" % slug)
    out.append("    - and the page does not disclose that 4.6 was unavailable")
    out.append("  WRITING.md section 1 permits writing it in the campaign model "
               "-- it does NOT permit doing so silently. Either brief the "
               "writer (section 2; on POSIX/root see the invocation note), or "
               "state in the page and the commit that 4.6 was unavailable and "
               "queue a voice pass.")
    return False, out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slug", default=None, help="check one campaign")
    a = ap.parse_args()
    res = os.path.join(REPO, "results")
    # ANY published page, not only campaigns that kept a campaign.json. The
    # first version keyed on campaign.json and silently skipped
    # results/qwen38-27b-blind -- the shipped worked example, the one page in
    # this tree a reader is most likely to open. A gate that does not cover the
    # example it points at is decoration.
    slugs = [a.slug] if a.slug else sorted(
        d for d in os.listdir(res)
        if os.path.isfile(os.path.join(res, d, "index.html")))
    bad = 0
    checked = 0
    for s in slugs:
        ok, lines = check(s)
        if ok is None:
            continue
        checked += 1
        print("%s %s" % ("PASS" if ok else "FAIL", s))
        for ln in lines:
            print(ln)
        if not ok:
            bad += 1
    if not checked:
        print("no published pages yet -- nothing to check")
        return 0
    print()
    print("%d of %d published page(s) FAILED" % (bad, checked) if bad
          else "%d published page(s) OK" % checked)
    return 1 if bad else 0


if __name__ == "__main__":
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        print(__doc__.strip())
        sys.exit(0)
    sys.exit(main())
