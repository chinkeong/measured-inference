"""judge-panel.py — the independent judge for rule 21's judge-gated pair.

Rule 21 leaves ALPACA and MT-Bench "judge-scored when an independent judge
endpoint is configured; otherwise speed + transcripts only (a model judging its
own outputs is not a score)". This is that endpoint: a panel of THREE
independent Claude Opus 5 judge seats, run blind over the kept transcripts.

    python judge-panel.py build   # blinded packets + the sealed key
    python judge-panel.py score   # ratings + key -> per-arm scores

WHY THIS IS NOT SELF-GRADING
    The answers were written by Qwen3.8-27B running locally. The judge is a
    different model from a different vendor than the model under test, so the
    rule-21 scoring gate ("a model must not grade its own answers") is
    satisfied. It is NOT fully independent in the strong sense: the judge and
    the author of the report are both Claude models. That is a correlated
    instrument, it is disclosed with every number this file produces, and it is
    the reason the panel reports inter-rater spread rather than a bare mean.

THE PROTOCOL (pinned — comparability requires every report to agree)
    * Rubric: the canonical MT-Bench single-answer grading rubric, 1-10, on
      helpfulness, relevance, accuracy, depth, creativity, level of detail.
    * Rule 21's normalization: score = (r - 1) / 9 * 100.
    * MT-Bench turn 1 only (rule 21 pins it).
    * Blind: every answer carries an opaque id. Arm identity lives only in the
      key file, which no judge seat ever reads.
    * Three seats rate EVERY answer. Each seat gets its own shuffle seed, so
      ordering effects do not correlate across seats.
    * A judge seat sees several answers to the same question inside one batch
      (shuffled apart). That is a KNOWN CONDITION of this instrument, not a
      clean-room single-answer protocol, and it travels with the numbers.
    * An empty or truncated answer is rated like any other answer. It is never
      dropped: rule 7 forbids filtering to the questions one arm handled well.
"""

import hashlib
import json
import os
import random
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
R21 = os.path.join(ROOT, "results", "qwen38-27b-blind", "data", "rule21")
OUT = os.path.join(ROOT, "results", "qwen38-27b-blind", "data", "judge")
PACKETS = os.path.join(OUT, "packets")
KEYFILE = os.path.join(OUT, "key-SEALED.json")
RATINGS = os.path.join(OUT, "ratings")

ARMS = ["low", "medium", "xhigh"]
DATASETS = ["ALPACA", "MT-Bench"]
SEATS = [1, 2, 3]
SEAT_SEED = {1: 42, 2: 43, 3: 44}
HALVES = {"h1": range(0, 13), "h2": range(13, 25)}
CAP = 16384

RUBRIC = (
    "Act as an impartial judge and evaluate the quality of the response "
    "provided by an AI assistant to the user question shown. Consider "
    "helpfulness, relevance, accuracy, depth, creativity, and level of "
    "detail. Be as objective as possible. Rate the response on a scale of "
    "1 to 10, where 1 is unusable and 10 is excellent."
)


def _transcript(arm):
    for f in sorted(os.listdir(R21)):
        if f.startswith("arm-%s-Qwen" % arm) and f.endswith("_transcripts.json"):
            return os.path.join(R21, f)
    raise SystemExit("no transcript for arm %s" % arm)


def _oid(arm, ds, idx):
    """Opaque id. Salted so it cannot be reversed by guessing arm names."""
    h = hashlib.sha256(("rule21-judge-v1|%s|%s|%d" % (arm, ds, idx)).encode())
    return h.hexdigest()[:10]


def build():
    os.makedirs(PACKETS, exist_ok=True)
    os.makedirs(RATINGS, exist_ok=True)
    key = {}
    pool = {ds: [] for ds in DATASETS}

    for arm in ARMS:
        gen = json.load(open(_transcript(arm), encoding="utf-8"))["generations"]
        for ds in DATASETS:
            for it in gen[ds]:
                idx = int(it["index"])
                oid = _oid(arm, ds, idx)
                toks = int(it.get("tokens", 0))
                body = str(it.get("response", ""))
                key[oid] = {"arm": arm, "dataset": ds, "index": idx,
                            "tokens": toks, "chars": len(body),
                            "at_cap": toks >= CAP,
                            "empty": not body.strip()}
                pool[ds].append({"id": oid, "index": idx,
                                 "question": str(it["prompt"]),
                                 "answer": body})

    json.dump(key, open(KEYFILE, "w", encoding="utf-8"), indent=1)
    n = 0
    for ds in DATASETS:
        for half, rng in HALVES.items():
            items = [x for x in pool[ds] if x["index"] in rng]
            for seat in SEATS:
                shuffled = list(items)
                random.Random(SEAT_SEED[seat] + hash(ds + half) % 1000).shuffle(shuffled)
                # index is a tell (it groups the same question); strip it
                clean = [{"id": x["id"], "question": x["question"],
                          "answer": x["answer"]} for x in shuffled]
                p = os.path.join(PACKETS, "%s-%s-seat%d.json"
                                 % (ds.lower().replace("-", ""), half, seat))
                json.dump({"rubric": RUBRIC, "dataset": ds, "seat": seat,
                           "n": len(clean), "answers": clean},
                          open(p, "w", encoding="utf-8"), indent=1)
                n += 1
    print("built %d packets, %d blinded answers, key sealed at %s"
          % (n, len(key), KEYFILE))
    trunc = [k for k, v in key.items() if v["at_cap"]]
    for t in trunc:
        print("  AT-CAP (rule 7): %s %s[%d] tokens=%d empty=%s"
              % (key[t]["arm"], key[t]["dataset"], key[t]["index"],
                 key[t]["tokens"], key[t]["empty"]))


def score():
    key = json.load(open(KEYFILE, encoding="utf-8"))
    # ratings/<anything>.json : {"seat": N, "ratings": [{"id":..,"rating":..}]}
    by_id = {}
    seats_seen = set()
    for f in sorted(os.listdir(RATINGS)):
        if not f.endswith(".json"):
            continue
        d = json.load(open(os.path.join(RATINGS, f), encoding="utf-8"))
        seat = d.get("seat")
        seats_seen.add(seat)
        for r in d["ratings"]:
            oid = r["id"]
            if oid not in key:
                print("  WARN unknown id %s in %s" % (oid, f))
                continue
            rating = int(r["rating"])
            if not 1 <= rating <= 10:
                print("  WARN out-of-range %s in %s" % (rating, f))
                continue
            by_id.setdefault(oid, {})[seat] = rating

    missing = [k for k in key if k not in by_id]
    partial = [k for k, v in by_id.items() if len(v) < len(SEATS)]
    out = {"protocol": "rule21-judge-panel-v1", "rubric": RUBRIC,
           "judge": "Claude Opus 5 (claude-opus-5), 3 blind seats",
           "normalization": "(r-1)/9*100",
           "seats": sorted(s for s in seats_seen if s is not None),
           "answers_rated": len(by_id), "answers_total": len(key),
           "missing": missing, "partial": partial, "arms": {}}

    for arm in ARMS:
        out["arms"][arm] = {}
        for ds in DATASETS:
            ids = [k for k, v in key.items()
                   if v["arm"] == arm and v["dataset"] == ds and k in by_id]
            if not ids:
                continue
            per_item = []
            spreads = []
            for oid in ids:
                rs = list(by_id[oid].values())
                per_item.append(statistics.mean(rs))
                if len(rs) > 1:
                    spreads.append(max(rs) - min(rs))
            mean_r = statistics.mean(per_item)
            norm = (mean_r - 1.0) / 9.0 * 100.0
            flagged = [key[o]["index"] for o in ids if key[o]["at_cap"]]
            out["arms"][arm][ds] = {
                "n": len(ids),
                "mean_rating_1_10": round(mean_r, 3),
                "score_0_100": round(norm, 1),
                "sd_across_items": round(statistics.pstdev(per_item), 3),
                "mean_seat_spread": round(statistics.mean(spreads), 3) if spreads else None,
                "max_seat_spread": max(spreads) if spreads else None,
                "at_cap_items": flagged,
                "provisional": bool(flagged),
            }
    p = os.path.join(OUT, "judge-scores.json")
    json.dump(out, open(p, "w", encoding="utf-8"), indent=1)
    print(json.dumps(out["arms"], indent=1))
    print("rated %d/%d  missing=%d partial=%d -> %s"
          % (len(by_id), len(key), len(missing), len(partial), p))


RJ = os.path.join(OUT, "rejudge-alpaca")
CAP32K = os.path.join(R21, "arm-xhigh-alpaca-cap32k-"
                           "Qwen3_8-27B-UD-IQ4_XS_20260824_154740_transcripts.json")


def rebuild():
    """Re-judge ALL of ALPACA with xhigh's answers taken from the rule-7 re-run.

    Rule 7's raise ran and REPRODUCED the truncation, so the published 72.9
    still rested on the 16,384-cap generations. Arguing that the score cannot
    move because the answers are byte-identical is reasoning where a
    measurement is available; this measures it.

    All THREE arms are re-judged, not just xhigh. The original pass showed each
    seat a shuffled batch containing all three arms, so judging xhigh alone
    would change the conditions (no cross-arm anchoring) and the result would
    not be comparable to the number it replaces. Same protocol, same shape,
    one input changed.

    It doubles as the only reproducibility check this campaign has on the judge
    itself: 74 of the 75 answers are byte-identical to ones already rated by
    three seats, so the spread between the two passes on those 74 is the
    judge's own repeatability.
    """
    os.makedirs(RJ, exist_ok=True)
    os.makedirs(os.path.join(RJ, "packets"), exist_ok=True)
    os.makedirs(os.path.join(RJ, "ratings"), exist_ok=True)

    new_xhigh = {int(it["index"]): it for it in
                 json.load(open(CAP32K, encoding="utf-8"))["generations"]["ALPACA"]}
    key, pool = {}, []
    for arm in ARMS:
        gen = json.load(open(_transcript(arm), encoding="utf-8"))["generations"]
        for it in gen["ALPACA"]:
            idx = int(it["index"])
            src = "16384"
            if arm == "xhigh":
                it = new_xhigh[idx]          # the raised-cap answer
                src = "32768"
            body = str(it.get("response", ""))
            toks = int(it.get("tokens", 0))
            # v2 salt: ids cannot be matched to pass-1 ids by any seat
            oid = hashlib.sha256(("rule21-judge-v2|%s|ALPACA|%d" % (arm, idx))
                                 .encode()).hexdigest()[:10]
            key[oid] = {"arm": arm, "dataset": "ALPACA", "index": idx,
                        "tokens": toks, "chars": len(body), "cap": src,
                        "at_cap": (toks >= 32768 if src == "32768" else toks >= CAP),
                        "empty": not body.strip()}
            pool.append({"id": oid, "index": idx,
                         "question": str(it["prompt"]), "answer": body})

    json.dump(key, open(os.path.join(RJ, "key-SEALED.json"), "w",
                        encoding="utf-8"), indent=1)
    n = 0
    for half, rng in HALVES.items():
        items = [x for x in pool if x["index"] in rng]
        for seat in SEATS:
            sh = list(items)
            random.Random(SEAT_SEED[seat] + 7000 + hash(half) % 1000).shuffle(sh)
            clean = [{"id": x["id"], "question": x["question"],
                      "answer": x["answer"]} for x in sh]
            json.dump({"rubric": RUBRIC, "dataset": "ALPACA", "seat": seat,
                       "n": len(clean), "answers": clean},
                      open(os.path.join(RJ, "packets",
                                        "alpaca-%s-seat%d.json" % (half, seat)),
                           "w", encoding="utf-8"), indent=1)
            n += 1
    print("rebuilt %d packets, %d answers (xhigh from the 32,768-cap re-run)"
          % (n, len(key)))
    for k, v in key.items():
        if v["at_cap"]:
            print("  AT-CAP: %s ALPACA[%d] cap=%s tokens=%d empty=%s"
                  % (v["arm"], v["index"], v["cap"], v["tokens"], v["empty"]))


def rescore():
    """Score the re-judge, and measure the judge against itself on the 74
    answers that did not change."""
    key2 = json.load(open(os.path.join(RJ, "key-SEALED.json"), encoding="utf-8"))
    by2 = {}
    import glob
    for p in glob.glob(os.path.join(RJ, "ratings", "*.json")):
        d = json.load(open(p, encoding="utf-8"))
        for r in d["ratings"]:
            by2.setdefault(r["id"], {})[d["seat"]] = int(r["rating"])
    missing = [k for k in key2 if k not in by2]
    partial = [k for k, v in by2.items() if len(v) < len(SEATS)]
    if missing or partial:
        print("REFUSING: %d unrated, %d partial" % (len(missing), len(partial)))
        return 1

    # pass-1 ratings, for the repeatability comparison
    key1 = json.load(open(KEYFILE, encoding="utf-8"))
    by1 = {}
    for p in glob.glob(os.path.join(RATINGS, "*.json")):
        d = json.load(open(p, encoding="utf-8"))
        for r in d["ratings"]:
            by1.setdefault(r["id"], {})[d["seat"]] = int(r["rating"])
    p1 = {(v["arm"], v["index"]): statistics.mean(by1[k].values())
          for k, v in key1.items() if v["dataset"] == "ALPACA" and k in by1}

    out = {"protocol": "rule21-judge-panel-v1 (re-judge)",
           "input_change": "xhigh ALPACA answers taken from the rule-7 "
                           "raised-cap re-run (cap 32,768, 2026-08-24 16:08); "
                           "low and medium unchanged",
           "arms": {}, "repeatability": {}}
    same, diffs = [], []
    for arm in ARMS:
        ids = [k for k, v in key2.items() if v["arm"] == arm]
        per = [statistics.mean(by2[k].values()) for k in ids]
        mean_r = statistics.mean(per)
        out["arms"][arm] = {
            "n": len(ids),
            "mean_rating_1_10": round(mean_r, 3),
            "score_0_100": round((mean_r - 1.0) / 9.0 * 100.0, 1),
            "pass1_score_0_100": round(
                (statistics.mean([p1[(arm, key2[k]["index"])] for k in ids]) - 1.0)
                / 9.0 * 100.0, 1),
        }
        for k in ids:
            a = p1[(arm, key2[k]["index"])]
            b = statistics.mean(by2[k].values())
            # 74 of 75 answers are byte-identical between passes
            if not (arm == "xhigh" and key2[k]["index"] == 21):
                same.append(abs(b - a))
            diffs.append((arm, key2[k]["index"], round(a, 2), round(b, 2)))
    out["repeatability"] = {
        "n_identical_answers": len(same),
        "mean_abs_rating_change": round(statistics.mean(same), 3),
        "max_abs_rating_change": round(max(same), 3),
        "unchanged_exactly": sum(1 for x in same if x == 0),
        "note": "the same answers, rated by three fresh blind seats in a second "
                "pass; this is the judge's repeatability, not the model's",
    }
    json.dump(out, open(os.path.join(OUT, "judge-rejudge.json"), "w",
                        encoding="utf-8"), indent=1)
    print(json.dumps(out, indent=1))
    return 0


def _ratings(dirpath):
    import glob
    by = {}
    for p in glob.glob(os.path.join(dirpath, "*.json")):
        d = json.load(open(p, encoding="utf-8"))
        for r in d["ratings"]:
            by.setdefault(r["id"], {})[d["seat"]] = int(r["rating"])
    return by


def _merged_by_arm_index():
    """Per-(arm, dataset, index) seat ratings, with ALPACA taken from the
    re-judge when one exists.

    ALPACA's published numbers must come from the rule-7 REMEDIED generations,
    so once the raised-cap arm exists, pass 1's ALPACA is superseded whole.
    All three arms move together: they were rated in one batch, and mixing a
    pass-1 arm with a pass-2 arm inside one dataset would compare two
    different judging sessions rather than two effort levels.
    """
    key1 = json.load(open(KEYFILE, encoding="utf-8"))
    by1 = _ratings(RATINGS)
    out, src = {}, {}
    for oid, v in key1.items():
        if oid in by1:
            out[(v["arm"], v["dataset"], v["index"])] = by1[oid]
            src[v["dataset"]] = "pass-1 (16,384-cap generations)"
    k2p = os.path.join(RJ, "key-SEALED.json")
    if os.path.exists(k2p):
        key2 = json.load(open(k2p, encoding="utf-8"))
        by2 = _ratings(os.path.join(RJ, "ratings"))
        if all(o in by2 for o in key2):
            for oid, v in key2.items():
                out[(v["arm"], v["dataset"], v["index"])] = by2[oid]
            src["ALPACA"] = ("pass-2 (xhigh from the 32,768-cap rule-7 re-run; "
                             "low and medium answers unchanged, re-rated in the "
                             "same batch so all three arms share one session)")
    return out, src


def finalize():
    """The publishable scores: ALPACA from the re-judge, MT-Bench from pass 1."""
    import itertools
    by, src = _merged_by_arm_index()
    key1 = json.load(open(KEYFILE, encoding="utf-8"))
    atcap = {(v["arm"], v["dataset"], v["index"]) for v in key1.values()
             if v["at_cap"]}
    out = {"protocol": "rule21-judge-panel-v1", "sources": src,
           "judge": "Claude Opus 5, 3 blind seats per pass",
           "normalization": "(r-1)/9*100", "arms": {}, "paired": []}
    for arm in ARMS:
        out["arms"][arm] = {}
        for ds in DATASETS:
            ks = [k for k in by if k[0] == arm and k[1] == ds]
            per = [statistics.mean(by[k].values()) for k in ks]
            spr = [max(by[k].values()) - min(by[k].values()) for k in ks]
            mr = statistics.mean(per)
            out["arms"][arm][ds] = {
                "n": len(ks), "mean_rating_1_10": round(mr, 3),
                "score_0_100": round((mr - 1.0) / 9.0 * 100.0, 1),
                "sd_across_items": round(statistics.pstdev(per), 3),
                "mean_seat_spread": round(statistics.mean(spr), 3),
                "max_seat_spread": max(spr),
                "at_cap_items": sorted(k[2] for k in ks if k in atcap),
                "provisional": False,
                "note": ("the at-cap item was re-run at 32,768 and reproduced "
                         "the truncation, so rule 7's remedy is exhausted and "
                         "the score is final with a disclosed non-terminating "
                         "item") if any(k in atcap for k in ks) else None,
            }
    rng = random.Random(42)
    for ds in DATASETS:
        for a, b in itertools.combinations(ARMS, 2):
            A = {k[2]: statistics.mean(by[k].values()) for k in by
                 if k[0] == a and k[1] == ds}
            B = {k[2]: statistics.mean(by[k].values()) for k in by
                 if k[0] == b and k[1] == ds}
            idx = sorted(set(A) & set(B))
            d = [B[i] - A[i] for i in idx]
            boot = sorted(statistics.mean([rng.choice(d) for _ in d])
                          for _ in range(20000))
            lo, hi = boot[500], boot[19500]
            rec = {"dataset": ds, "a": a, "b": b, "n": len(d),
                   "mean_diff_b_minus_a": round(statistics.mean(d), 3),
                   "ci95": [round(lo, 3), round(hi, 3)],
                   "b_better_on": sum(1 for x in d if x > 0),
                   "b_worse_on": sum(1 for x in d if x < 0),
                   "tied_on": sum(1 for x in d if x == 0),
                   "verdict": "DIFFERENT" if (lo > 0 or hi < 0) else "TIE"}
            if rec["verdict"] == "DIFFERENT" and min(abs(lo), abs(hi)) < 0.05:
                rec["verdict"] = "DIFFERENT (marginal)"
            out["paired"].append(rec)
    rj = os.path.join(OUT, "judge-rejudge.json")
    if os.path.exists(rj):
        out["judge_repeatability"] = json.load(open(rj, encoding="utf-8"))["repeatability"]
    p = os.path.join(OUT, "judge-scores-final.json")
    json.dump(out, open(p, "w", encoding="utf-8"), indent=1)
    for arm in ARMS:
        print("%-7s ALPACA %5.1f   MT-Bench %5.1f"
              % (arm, out["arms"][arm]["ALPACA"]["score_0_100"],
                 out["arms"][arm]["MT-Bench"]["score_0_100"]))
    for r in out["paired"]:
        print("  %-9s %-6s vs %-6s  %+.3f  [%+.3f,%+.3f]  %s"
              % (r["dataset"], r["a"], r["b"], r["mean_diff_b_minus_a"],
                 r["ci95"][0], r["ci95"][1], r["verdict"]))
    print("-> %s" % p)


def compare():
    """Paired arm-vs-arm test on the judged pair.

    Rule 8 forbids reading a point difference at small n as a finding, and
    rule 9 calls a lower score at higher effort a tie until proven. So the
    arms are compared PAIRED — the same 25 prompts, each item scored as the
    mean of its three seats — and a difference is only called when a 20,000-
    resample bootstrap CI of the per-item differences excludes zero.

    Six comparisons are run. At 95% that is roughly one false positive every
    three runs, so a CI that barely clears zero is reported as marginal and
    never as a result on its own.
    """
    import itertools
    import glob
    key = json.load(open(KEYFILE, encoding="utf-8"))
    by = {}
    for p in glob.glob(os.path.join(RATINGS, "*.json")):
        d = json.load(open(p, encoding="utf-8"))
        for r in d["ratings"]:
            by.setdefault(r["id"], {})[d["seat"]] = int(r["rating"])

    def items(arm, ds):
        return {key[o]["index"]: statistics.mean(by[o].values())
                for o in key
                if key[o]["arm"] == arm and key[o]["dataset"] == ds and o in by}

    rng = random.Random(42)
    out = {"method": "paired bootstrap, 20000 resamples, seed 42, "
                     "item = mean of 3 seats",
           "multiplicity": "6 comparisons at 95% — a CI that barely clears "
                           "zero is marginal, not a finding",
           "comparisons": []}
    for ds in DATASETS:
        for a, b in itertools.combinations(ARMS, 2):
            A, B = items(a, ds), items(b, ds)
            idx = sorted(set(A) & set(B))
            d = [B[i] - A[i] for i in idx]
            boot = sorted(statistics.mean([rng.choice(d) for _ in d])
                          for _ in range(20000))
            lo, hi = boot[500], boot[19500]
            rec = {"dataset": ds, "a": a, "b": b, "n": len(d),
                   "mean_diff_b_minus_a": round(statistics.mean(d), 3),
                   "ci95": [round(lo, 3), round(hi, 3)],
                   "b_better_on": sum(1 for x in d if x > 0),
                   "b_worse_on": sum(1 for x in d if x < 0),
                   "tied_on": sum(1 for x in d if x == 0),
                   "verdict": "DIFFERENT" if (lo > 0 or hi < 0) else "TIE"}
            if rec["verdict"] == "DIFFERENT" and min(abs(lo), abs(hi)) < 0.05:
                rec["verdict"] = "DIFFERENT (marginal — CI barely clears zero)"
            out["comparisons"].append(rec)
            print("%-9s %-6s vs %-6s  diff %+.3f  CI [%+.3f,%+.3f]  %s"
                  % (ds, a, b, rec["mean_diff_b_minus_a"], lo, hi,
                     rec["verdict"]))
    p = os.path.join(OUT, "judge-paired.json")
    json.dump(out, open(p, "w", encoding="utf-8"), indent=1)
    print("-> %s" % p)


USAGE = """\
The independent judge for rule 21's judge-gated pair: three blind Claude seats
over the kept ALPACA and MT-Bench transcripts, rated 1-10 and normalised to
(r - 1) / 9 * 100.

    python scripts/bench/judge-panel.py <subcommand>

Subcommands, in the order they run (default: build):
  build      blinded packets plus the sealed key
  score      ratings plus the key, to per-arm scores
  compare    paired arm-against-arm bootstrap on the judged pair
  rebuild    re-judge ALL of ALPACA against the rule-7 re-run answers
  rescore    score the re-judge, and the judge against itself on the 74
             answers that did not change
  finalize   the publishable scores: ALPACA from the re-judge, MT-Bench pass 1

Positional arguments: the subcommand, and nothing else. No environment
variables. No server, no model, no GPU - this reads and writes JSON.

Example:
  python scripts/bench/judge-panel.py build

Reads results/qwen38-27b-blind/data/rule21/ transcripts. Writes under
results/qwen38-27b-blind/data/judge/: packets/, key-SEALED.json,
judge-scores.json, judge-rejudge.json, judge-scores-final.json and
judge-paired.json. `build` OVERWRITES the sealed key.
"""


if __name__ == "__main__":
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        print(USAGE.rstrip())
        raise SystemExit(0)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    {"build": build, "score": score, "compare": compare,
     "rebuild": rebuild, "rescore": rescore, "finalize": finalize}[cmd]()
