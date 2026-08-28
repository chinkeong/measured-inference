#!/usr/bin/env python3
"""Rebuild a scored result artefact from a bench.py progress log.

    reconstruct-from-log.py --log <path> --dataset GPQA-Diamond --out <path.json>

WHY THIS EXISTS. bench.py checkpoints after every DATASET:

    # persist after every dataset so an interrupted run loses at most
    # the dataset in flight, never the finished ones

That is real protection for a seven-dataset suite and NONE AT ALL for a run of
one dataset, which is the shape every anchor run takes. A 198-question GPQA run
stopped at question 100 would write nothing, and ten hours of measurement would
survive only as console text.

The console text is in fact enough. Every prompt prints its own outcome:

    prompt 31/198: 11277 tok, 55.7 tok/s, accept_len 2.38, CORRECT
    prompt 29/198: 30000 tok, 52.4 tok/s, accept_len 2.38, wrong (truncated)

so the score, the token distribution, the truncation count and the acceptance
rate can all be recovered exactly. What CANNOT be recovered from the log is the
condition block - sampler, context, server flags, effort - so this script takes
those as arguments and records them explicitly rather than inventing them. A
reconstructed artefact is marked as reconstructed, and names the log it came
from, so it is never mistaken for one the harness wrote itself.

TRUNCATION IS REPORTED SEPARATELY AND NOT ABSORBED. bench.py scores a truncated
response 0.0, which is correct - an answer that ran out of context is not a
right answer - but it means a run against a small context window carries a
penalty that is not a quality signal. Both figures are emitted: the score as
scored, and the score over the subset that was not truncated.

A STOPPED RUN IS A PREFIX, AND A PREFIX IS ONLY A SAMPLE IF THE FILE IS SHUFFLED.
Added 2026-08-27, after a run of four consecutive truncations prompted a look at
the file itself rather than at the server.

gpqa_diamond.jsonl is SUBJECT-ORDERED. Classifying its 198 questions by keyword
and counting adjacent same-subject pairs gives 106 against 48.2 expected under
random ordering - a permutation test over 20,000 shuffles puts p below 0.0001.
The blocks are visible by eye: astronomy and astrophysics at the front, particle
physics around 41-60, biology and genetics around 61-80, then roughly forty
consecutive organic chemistry questions from 81, and a quantum block at the end.

So a run stopped at question 100 is NOT a random sample of the benchmark. It
covers the front subjects, most of one chemistry block, and none of the quantum
block at all. A Wilson interval assumes the draws are exchangeable and therefore
describes sampling noise ONLY - it cannot describe the subject imbalance, and it
will be too narrow whenever subject difficulty differs, which on this benchmark
it plainly does.

This script now measures that ordering from the frozen file at reconstruct time
and records what a partial run covered and what it missed, so the omission
travels with the number instead of being left for a reader to discover.

CORRECTION RECORDED HERE BECAUSE IT WAS MINE. An earlier check declared this file
free of order effects on the strength of a chi-square of 4.30 on the ANSWER KEY
between halves, 3 degrees of freedom. That test asks whether the correct letter
A/B/C/D is evenly spread. It cannot see subject ordering, and subject ordering is
the thing that actually breaks a prefix. The answer key is evenly spread AND the
file is strongly subject-ordered; both are true, and only the second one matters
for stopping early.
"""
import argparse, io, json, os, random, re, statistics as st, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))

# The frozen GPQA file carries only `question` and `answer` - no subject label -
# so subject is inferred from vocabulary. This is a HEURISTIC and is reported as
# one. It is good enough for the job it does here for a specific reason: a noisy
# classifier can only DILUTE an ordering signal, never manufacture one, so a
# significant clustering result measured through it is a conservative floor
# rather than an artefact of the labelling.
SUBJECT_SIGNATURES = {
    "astronomy/astrophysics": ("exoplanet", "star", "astronom", "telescope",
                               "galax", "orbit", "luminosit", "redshift",
                               "planet", "spectr"),
    "quantum": ("quantum", "wavefunction", "eigen", "hamiltonian", "spin",
                "operator", "qubit", "uncertainty principle", "oscillator"),
    "particle/relativity": ("decay", "meson", "quark", "lepton", "boson",
                            "annihilat", "lorentz", "relativis",
                            "cross section", "muon"),
    "organic chemistry": ("nmr", "synthes", "reagent", "stereochem", "alkene",
                          "carbon", "product", "reaction", "proton", "ppm",
                          "molecul"),
    "biology/genetics": ("gene", "protein", "cell", "mrna", "dna", "chromosom",
                         "enzym", "mice", "mutat", "transcript", "allele"),
}

FROZEN = {"GPQA-Diamond": os.path.join(HERE, "datasets-frozen",
                                       "gpqa_diamond.jsonl")}


def classify(question):
    q = question.lower()
    best, score = "unclassified", 0
    for name, words in SUBJECT_SIGNATURES.items():
        hits = sum(q.count(w) for w in words)
        if hits > score:
            best, score = name, hits
    return best if score else "unclassified"


def subject_profile(dataset, completed_n, shuffles=20000, seed=0, offset=0):
    """Measure whether the frozen file is subject-ordered, and if a run stopped
    short, say which subjects it covered and which it never reached.

    Returns None when the frozen file is unavailable - and the CALLER records
    that it could not be checked, because a missing check must never read as a
    passing one."""
    path = FROZEN.get(dataset)
    if not path or not os.path.exists(path):
        return None
    # OFFSET, added 2026-08-28. A run no longer has to start at row 0: bench.py
    # gained --offset so the complement of a stopped prefix could be run. This
    # function assumed the covered rows were [0, completed_n), which for an
    # offset run reports the PREFIX's subjects as the tail's - biology 16 of 16
    # and quantum 3, on a run that answered neither. A coverage figure that
    # describes the wrong rows is worse than none: it reads as measured.
    rows = [json.loads(l) for l in io.open(path, encoding="utf-8") if l.strip()]
    labels = [classify(r.get("question", "")) for r in rows]

    def adjacent_pairs(seq):
        return sum(1 for i in range(1, len(seq)) if seq[i] == seq[i - 1])

    observed = adjacent_pairs(labels)
    rng = random.Random(seed)
    shuffled = labels[:]
    null = []
    for _ in range(shuffles):
        rng.shuffle(shuffled)
        null.append(adjacent_pairs(shuffled))
    at_least = sum(1 for v in null if v >= observed)
    # An exact-zero count is reported as an upper bound rather than as 0, since
    # a permutation test cannot resolve below 1/shuffles.
    p_value = at_least / float(shuffles)

    seen, missed = {}, {}
    lo, hi = offset, offset + completed_n
    for i, lab in enumerate(labels):
        d = seen if lo <= i < hi else missed
        d[lab] = d.get(lab, 0) + 1
    never = sorted(k for k in missed if k not in seen)

    # Per-subject coverage: what share of each subject's questions the prefix
    # reached. A subject can be present in the prefix and still be almost
    # entirely unmeasured, which an absence test cannot see.
    subjects = sorted(set(labels))
    coverage = {}
    for lab in subjects:
        total = labels.count(lab)
        got = seen.get(lab, 0)
        coverage[lab] = {"covered": got, "total": total,
                         "pct": round(100.0 * got / total, 1)}
    # The threshold is the run's own overall completion rate. A subject covered
    # at less than half the rate the run achieved overall is under-represented
    # by the ordering rather than by chance.
    overall = 100.0 * completed_n / len(labels)
    under = sorted([lab for lab, c in coverage.items()
                    if c["pct"] < overall * 0.5],
                   key=lambda l: coverage[l]["pct"])
    return {
        "labelling": "keyword heuristic - the frozen file carries no subject "
                     "field. A noisy classifier can only dilute an ordering "
                     "signal, so this result is a floor.",
        "adjacent_same_subject_pairs": observed,
        "expected_under_random_order": round(sum(null) / float(len(null)), 1),
        "permutation_p": ("< %.5f" % (1.0 / shuffles)) if at_least == 0
                         else round(p_value, 5),
        "shuffles": shuffles,
        "is_subject_ordered": p_value < 0.01,
        "subjects_covered": dict(sorted(seen.items(), key=lambda kv: -kv[1])),
        "subjects_remaining": dict(sorted(missed.items(), key=lambda kv: -kv[1])),
        "subjects_never_reached": never,
        "overall_completion_pct": round(overall, 1),
        "per_subject_coverage": dict(sorted(coverage.items(),
                                            key=lambda kv: kv[1]["pct"])),
        "under_represented": under,
    }

LINE = re.compile(
    r"prompt (\d+)/(\d+):\s*(\d+) tok,\s*([0-9.]+) tok/s"
    r"(?:,\s*accept_len ([0-9.]+))?,\s*(CORRECT|wrong)(\s*\(truncated\))?",
    re.IGNORECASE)


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0, 0.0)
    p = k / float(n)
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4.0 * n * n)) ** 0.5) / d
    return (100 * p, 100 * max(0.0, c - h), 100 * min(1.0, c + h))


def parse(path):
    rows = []
    for ln in io.open(path, encoding="utf-8", errors="replace"):
        m = LINE.search(ln)
        if not m:
            continue
        rows.append({
            "index": int(m.group(1)),
            "planned_n": int(m.group(2)),
            "tokens": int(m.group(3)),
            "tok_s": float(m.group(4)),
            "accept_len": float(m.group(5)) if m.group(5) else None,
            "correct": m.group(6).upper() == "CORRECT",
            "truncated": bool(m.group(7)),
        })
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True)
    ap.add_argument("--dataset", default="GPQA-Diamond")
    ap.add_argument("--offset", type=int, default=0,
                    help="row the run STARTED at, matching bench.py --offset. "
                         "Subject coverage is computed over rows "
                         "[offset, offset+completed_n); leaving it at 0 for an "
                         "offset run reports the wrong rows as covered.")
    ap.add_argument("--out", required=True)
    ap.add_argument("--model-label", default="Qwen3.8-27B-UD-IQ4_XS")
    ap.add_argument("--published", type=float, default=None,
                    help="a published figure to compare against, e.g. 89.2")
    ap.add_argument("--conditions", default=None,
                    help="JSON object of the run's conditions; recorded verbatim")
    a = ap.parse_args()

    rows = parse(a.log)
    if not rows:
        sys.exit("no prompt lines matched in %s - nothing to reconstruct" % a.log)

    n = len(rows)
    k = sum(1 for r in rows if r["correct"])
    trunc = [r for r in rows if r["truncated"]]
    kept = [r for r in rows if not r["truncated"]]
    k_kept = sum(1 for r in kept if r["correct"])
    tok = [r["tokens"] for r in rows]
    acc = [r["accept_len"] for r in rows if r["accept_len"]]

    p, lo, hi = wilson(k, n)
    pk, lok, hik = wilson(k_kept, len(kept))

    out = {
        "reconstructed": True,
        "reconstructed_from": os.path.abspath(a.log),
        "reconstructed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "why": "bench.py checkpoints once per DATASET; a single-dataset run "
               "writes nothing until the last question, so an interrupted run "
               "survives only in its log",
        "model_label": a.model_label,
        "dataset": a.dataset,
        "planned_n": rows[0]["planned_n"],
        "completed_n": n,
        "partial": n < rows[0]["planned_n"],
        "score": {
            "correct": k, "n": n, "pct": round(p, 2),
            "wilson95": [round(lo, 2), round(hi, 2)],
        },
        # The same score with truncated questions removed. Truncation is a
        # context-window artefact, not a quality signal, so both are published
        # and neither is presented alone.
        "score_excluding_truncated": {
            "correct": k_kept, "n": len(kept), "pct": round(pk, 2),
            "wilson95": [round(lok, 2), round(hik, 2)],
        },
        "truncated_n": len(trunc),
        "truncated_pct": round(100.0 * len(trunc) / n, 2),
        "truncated_indices": [r["index"] for r in trunc],
        "tokens": {
            "mean": round(st.mean(tok), 1),
            "median": st.median(tok),
            "min": min(tok), "max": max(tok),
        },
        "accept_len_mean": round(st.mean(acc), 3) if acc else None,
        # Per-block scores. A subject-ordered file makes the block index a
        # proxy for subject, so this is where a coverage problem becomes
        # visible as a number rather than as a caveat.
        "score_by_block_of_20": [
            {"first": b[0]["index"], "last": b[-1]["index"],
             "n": len(b),
             "correct": sum(1 for r in b if r["correct"]),
             "truncated": sum(1 for r in b if r["truncated"]),
             "mean_tokens": round(st.mean([r["tokens"] for r in b]), 0)}
            for b in [rows[i:i + 20] for i in range(0, len(rows), 20)]
        ],
        "tok_s_mean": round(st.mean([r["tok_s"] for r in rows]), 2),
        "rows": rows,
    }
    prof = subject_profile(a.dataset, n, offset=a.offset)
    if prof is None:
        # NOT silence. A check that could not run is recorded as not having run.
        out["subject_coverage"] = {
            "checked": False,
            "why": "the frozen dataset file for %s was not found, so subject "
                   "ordering could not be measured. Do not read this as "
                   "'no ordering'." % a.dataset,
        }
    else:
        prof["checked"] = True
        if out["partial"] and prof["is_subject_ordered"]:
            bits = []
            for lab in prof["under_represented"]:
                c = prof["per_subject_coverage"][lab]
                bits.append("%s %d of %d (%.0f%%)"
                            % (lab, c["covered"], c["total"], c["pct"]))
            prof["warning"] = (
                "THIS RUN IS A PREFIX OF A SUBJECT-ORDERED FILE, NOT A RANDOM "
                "SAMPLE. %d of %d questions were answered, which is %.0f%% "
                "overall, but the subjects are not covered at that rate: %s. "
                "The Wilson intervals above describe sampling noise only. They "
                "cannot describe this imbalance, and they are too narrow to "
                "the extent that subject difficulty differs on this benchmark "
                "- which it does."
                % (n, out["planned_n"], prof["overall_completion_pct"],
                   "; ".join(bits) or "no subject falls below half the overall "
                                      "rate"))
        out["subject_coverage"] = prof

    if a.conditions:
        out["conditions"] = json.loads(a.conditions)
    if a.published is not None:
        out["published_reference"] = {
            "value": a.published,
            "inside_wilson95": lo <= a.published <= hi,
            "note": "a published figure this run can be compared against. It "
                    "detects a BROKEN harness; it does not validate one - the "
                    "option order is the mirror's, the published value is "
                    "vendor self-reported, and this rig serves a fraction of "
                    "the model's native context.",
        }

    io.open(a.out, "w", encoding="utf-8").write(
        json.dumps(out, indent=1, ensure_ascii=False))

    print("reconstructed %d of %d questions from %s"
          % (n, out["planned_n"], os.path.basename(a.log)))
    print("  score              %d/%d = %.1f%%   95%% CI %.1f - %.1f"
          % (k, n, p, lo, hi))
    print("  excluding truncated %d/%d = %.1f%%   95%% CI %.1f - %.1f"
          % (k_kept, len(kept), pk, lok, hik))
    print("  truncated          %d (%.1f%%) at indices %s"
          % (len(trunc), out["truncated_pct"], out["truncated_indices"][:12]))
    print("  tokens             mean %.0f, median %.0f, max %d"
          % (out["tokens"]["mean"], out["tokens"]["median"], out["tokens"]["max"]))
    sc = out.get("subject_coverage") or {}
    if not sc.get("checked"):
        print("  subject order     NOT CHECKED - %s" % sc.get("why", ""))
    else:
        print("  subject order     %d adjacent same-subject pairs against %.1f "
              "expected, p %s"
              % (sc["adjacent_same_subject_pairs"],
                 sc["expected_under_random_order"], sc["permutation_p"]))
        if sc.get("warning"):
            print("  COVERAGE          run is %.0f%% complete overall, but by "
                  "subject:" % sc["overall_completion_pct"])
            for lab, c in sc["per_subject_coverage"].items():
                flag = "  <- under-represented" if lab in sc["under_represented"] else ""
                print("                      %-24s %3d/%3d = %5.1f%%%s"
                      % (lab, c["covered"], c["total"], c["pct"], flag))
            print("                    a prefix of a subject-ordered file is "
                  "not a random sample; the intervals above are too narrow")
    if a.published is not None:
        verdict = ("INSIDE" if out["published_reference"]["inside_wilson95"]
                   else "OUTSIDE")
        print("  published %.1f is %s the 95%% interval" % (a.published, verdict))
    print("wrote %s" % a.out)
