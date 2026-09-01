#!/usr/bin/env python3
"""Decompose a multiple-choice score into KNOWLEDGE and FORMAT, from saved text.

WHY THIS EXISTS. `_grade_choice` scores an unreadable answer WRONG, on purpose
(its docstring says why, and OpenAI's simple-evals does the same). The cost of
that correct choice is that one published number, "68.5% on GPQA-Diamond",
silently mixes two unrelated failures: the model did not know, and the model
knew but never emitted a letter the extractor could find. A reader deciding
whether to deploy needs those apart -- the first is the model, the second is a
prompt or chat-template defect the reader can fix in an afternoon.

That docstring already promised the diagnostic: "run with transcripts kept, and
the unparsed rate can be recovered by re-running this extractor over them."
Nothing computed it. This does, at zero GPU cost, from text that is already on
disk (rule 28: the run is the scarce thing, re-reading it is free).

WHAT IT REPORTS, and which of rule 1's three categories each number is in:

  MEASURED (counted from the saved text)
    truncated_n        hit the token cap; never reached a final answer
    empty_body_n       visible reply empty after the think block was stripped
    unparsed_n         non-truncated, non-empty, and the STRICT extractor found
                       no letter at all -- the format-failure count
    compliant_n        the entire visible reply is one bare capital letter,
                       which is the definition the model cards use when they
                       quote a "format compliance" percentage
  LABELLED-DERIVED (arithmetic on the above, and labelled as such in the output)
    strict_accuracy    what the harness publishes; truncated and unparsed = 0
    lenient_accuracy   the same generations re-scored with the permissive
                       extractor below -- an UPPER BOUND, see the warning
    format_tax_pp      lenient - strict, in percentage points

THE WARNING THAT TRAVELS WITH lenient_accuracy. On four options a permissive
extractor that will accept a letter out of running prose scores about 25% of
genuinely-lost answers correct by luck, so the lenient figure is a CEILING on
capability, never a capability measurement. It is published only as the other
end of a bracket: the truth about what the model knows lies between strict and
lenient, and the width of that bracket IS the format tax. Every recovery is
attributed to the tier that made it, so a reader can see how much of the
bracket rests on the weakest tier and discount accordingly.

THINKING IS STRIPPED FIRST, in both extractors. Chain-of-thought routinely
contains "so the answer would be B" on the way to rejecting B; a lenient pass
over raw text would grade the scratch work. This is the one place leniency is
not extended, and it is not negotiable.

NO DRIFT. The strict pass imports datasets_io's own regexes rather than
restating them, and every item is cross-checked against `_grade_choice` itself.
A reimplementation that quietly diverged from the real grader would make this
whole report a fiction, so a single disagreement is a hard failure, not a
warning.

    python scripts/bench/rescore-choices.py <transcripts.json | run.json.partial.jsonl>
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datasets_io import (_CHOICE_BARE, _CHOICE_TAGGED, _grade_choice,  # noqa: E402
                         load_items, strip_think)

# Leniency, in descending order of how much the model committed to the choice.
# Tier 1 is the strict grader unchanged. Tiers 2-4 are what it refuses.
_LENIENT_TIERS = [
    ("prose_answer", re.compile(
        r"(?:answer|option|choice|correct(?:\s+one)?)\s*(?:is|:|=|would\s+be|"
        r"should\s+be|must\s+be)?\s*[\(\[]?\*{0,2}([ABCD])\b", re.I)),
    ("bare_line", re.compile(r"(?:^|\n)\s*[\(\[]?\*{0,2}([ABCD])[\.\)\]\*\s]*(?:$|\n)")),
    ("last_letter", re.compile(r"(?<![A-Za-z0-9])([ABCD])(?![A-Za-z0-9])")),
]
_BARE_ONLY = re.compile(r"^[\s\*\(\[]*([ABCD])[\s\*\)\]\.\,]*$")


def strict_letter(body):
    """The letter `_grade_choice` would extract, or None. Same regexes, same
    order, last match wins -- imported, not restated."""
    m = list(_CHOICE_TAGGED.finditer(body))
    if m:
        return m[-1].group(1).upper()
    m = list(_CHOICE_BARE.finditer(body.rstrip()))
    if m:
        return m[-1].group(1).upper()
    return None


def lenient_letter(body):
    """(letter, tier) under progressively weaker evidence, or (None, None)."""
    s = strict_letter(body)
    if s:
        return s, "strict"
    for tier, rx in _LENIENT_TIERS:
        m = list(rx.finditer(body))
        if m:
            return m[-1].group(1).upper(), tier
    return None, None


def load_records(path):
    """Either artefact the bench writes: the end-of-run transcripts JSON, or
    the per-question crash-protection .partial.jsonl (which carries the text
    only for runs made after the rule-28 fix -- older files have none, and this
    says so rather than reporting an empty run as a clean one)."""
    if path.endswith(".jsonl"):
        rows, ds = [], None
        for line in open(path, encoding="utf-8", errors="replace"):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            ds = ds or r.get("dataset")
            rows.append({"index": r.get("i"), "response": r.get("response"),
                         "tokens": r.get("tokens"),
                         "truncated": r.get("truncated"),
                         "score": (r.get("score") or 0) * 100})
        if rows and not any(r["response"] for r in rows):
            sys.exit("%s carries no generations: written before the rule-28 fix "
                     "that appends response text per question. The text for that "
                     "run cannot be recovered." % path)
        return ds, rows, None
    d = json.load(open(path, encoding="utf-8"))
    gens = d.get("generations") or {}
    ds = next((k for k in gens if k in ("GPQA-Diamond",)), None) or next(iter(gens), None)
    return ds, gens.get(ds) or [], d.get("suite_hash")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", help="*_transcripts.json or *.json.partial.jsonl")
    ap.add_argument("--dataset", default=None, help="override the dataset name")
    ap.add_argument("--samples", type=int, default=198,
                    help="the run's --samples, so references line up by index")
    ap.add_argument("--max-prompt-tokens", type=int, default=0)
    ap.add_argument("--json", metavar="OUT", help="also write the record here")
    a = ap.parse_args()

    ds, recs, suite_hash = load_records(a.path)
    ds = a.dataset or ds
    if not recs:
        sys.exit("no records in %s" % a.path)
    items = load_items(ds, a.samples, a.max_prompt_tokens)
    refs = [it["ref"] for it in items]

    rows, tiers, disagreements = [], {}, 0
    for r in recs:
        i = r.get("index")
        if i is None or i >= len(refs):
            continue
        ref, resp = refs[i], r.get("response") or ""
        body = strip_think(resp)
        trunc = bool(r.get("truncated"))
        sl = strict_letter(body)
        ll, tier = lenient_letter(body)
        # NO DRIFT: the reimplemented strict pass must agree with the real
        # grader on every non-truncated item, or this report is fiction.
        if not trunc and _grade_choice(resp, ref) != (sl == str(ref).strip().upper()):
            disagreements += 1
        if tier and tier != "strict":
            tiers[tier] = tiers.get(tier, 0) + 1
        rows.append({
            "index": i, "ref": ref, "tokens": r.get("tokens"),
            "truncated": trunc,
            "empty_body": not body.strip(),
            "strict_letter": sl, "lenient_letter": ll, "lenient_tier": tier,
            "strict_correct": (not trunc) and sl == str(ref).strip().upper(),
            "lenient_correct": (not trunc) and ll == str(ref).strip().upper(),
            "compliant": bool(_BARE_ONLY.match(body.strip())),
        })
    if disagreements:
        sys.exit("FATAL: this extractor disagreed with _grade_choice on %d items. "
                 "The regexes have drifted; fix before quoting any number."
                 % disagreements)

    n = len(rows)
    live = [r for r in rows if not r["truncated"]]
    trunc_n = n - len(live)
    empty_n = sum(r["empty_body"] for r in live)
    unparsed = [r for r in live if not r["empty_body"] and r["strict_letter"] is None]
    strict_n = sum(r["strict_correct"] for r in rows)
    lenient_n = sum(r["lenient_correct"] for r in rows)
    comp_n = sum(r["compliant"] for r in live)
    tok_correct = (sum(r["tokens"] or 0 for r in rows) / strict_n) if strict_n else None

    out = {
        "_schema": "rescore-choices v1",
        "source": os.path.relpath(a.path), "dataset": ds, "suite_hash": suite_hash,
        "measured": {
            "n": n, "truncated_n": trunc_n, "empty_body_n": empty_n,
            "unparsed_n": len(unparsed), "compliant_n": comp_n,
            "strict_correct_n": strict_n, "lenient_correct_n": lenient_n,
            "recovered_by_tier": tiers,
        },
        "derived": {
            "_label": "labelled-derived: arithmetic on the measured counts above",
            "strict_accuracy_pct": round(100.0 * strict_n / n, 1),
            "lenient_accuracy_pct": round(100.0 * lenient_n / n, 1),
            "format_tax_pp": round(100.0 * (lenient_n - strict_n) / n, 1),
            "compliance_rate_pct": round(100.0 * comp_n / len(live), 1) if live else None,
            "unparsed_rate_pct": round(100.0 * len(unparsed) / len(live), 1) if live else None,
            "truncation_rate_pct": round(100.0 * trunc_n / n, 1),
            "tokens_per_correct": round(tok_correct, 1) if tok_correct else None,
        },
        "caveat": (
            "lenient_accuracy_pct is a CEILING, not a measurement: on four "
            "options a prose-tolerant extractor scores ~25%% of genuinely-lost "
            "answers correct by luck. Publish the pair as a bracket -- what the "
            "model knows is between strict and lenient -- and quote "
            "recovered_by_tier so a reader can see how much of the bracket "
            "rests on the weakest tier."),
        "rows": rows,
    }

    d = out["derived"]; m = out["measured"]
    print("%s  n=%d   (%s)" % (ds, n, os.path.basename(a.path)))
    print("  MEASURED")
    print("    truncated            %4d   %5.1f%%   never reached an answer" % (trunc_n, d["truncation_rate_pct"]))
    print("    empty visible reply  %4d            all output stayed in reasoning_content" % empty_n)
    print("    unparsed (format)    %4d   %5.1f%%   of the %d that finished" % (len(unparsed), d["unparsed_rate_pct"] or 0, len(live)))
    print("    bare-letter replies  %4d   %5.1f%%   'compliance', as the cards define it" % (comp_n, d["compliance_rate_pct"] or 0))
    print("  DERIVED")
    print("    strict accuracy           %5.1f%%   what the harness publishes" % d["strict_accuracy_pct"])
    print("    lenient accuracy          %5.1f%%   CEILING -- luck-inflated, see caveat" % d["lenient_accuracy_pct"])
    print("    format tax                %5.1f pp  knowledge the format threw away" % d["format_tax_pp"])
    if m["recovered_by_tier"]:
        print("      recovered by: %s" % ", ".join("%s=%d" % kv for kv in sorted(tiers.items())))
    if d["tokens_per_correct"]:
        print("    tokens per correct answer %7.1f" % d["tokens_per_correct"])
    if a.json:
        json.dump(out, open(a.json, "w"), indent=1)
        print("wrote %s" % a.json)


if __name__ == "__main__":
    main()
