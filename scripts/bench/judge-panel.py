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

R21 = r"E:\AI\measured-inference\results\qwen38-27b-blind\data\rule21"
OUT = r"E:\AI\measured-inference\results\qwen38-27b-blind\data\judge"
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


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    {"build": build, "score": score}[cmd]()
