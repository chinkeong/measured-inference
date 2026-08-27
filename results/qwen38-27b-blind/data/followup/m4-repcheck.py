# Degenerate-repetition detector for long greedy transcripts.
# Two independent tests, both purely lexical, no GPU:
#   1) IMMEDIATE LOOP: the same k-word block repeated back-to-back >= 3 times.
#      This is the classic greedy-decoding death spiral.
#   2) TAIL LOOP: an n-gram from the last 15% of the file that occurs >= 4
#      times overall AND whose occurrences are clustered in the tail.
#   3) LINE LOOP: identical non-trivial lines repeated back-to-back.
# Also reports the raw tail so a human can eyeball the ending.
import sys, os, re, json
from collections import Counter, defaultdict

def words(t):
    return re.findall(r"\S+", t)

def immediate_loops(ws, min_k=3, max_k=60, min_reps=3):
    """Find maximal back-to-back repeats of a k-word block."""
    hits = []
    n = len(ws)
    i = 0
    seen_spans = []
    for k in range(min_k, max_k + 1):
        i = 0
        while i + 2 * k <= n:
            if ws[i:i + k] == ws[i + k:i + 2 * k]:
                reps = 2
                j = i + 2 * k
                while j + k <= n and ws[j:j + k] == ws[i:i + k]:
                    reps += 1
                    j += k
                if reps >= min_reps:
                    span = (i, j)
                    # skip if already covered by a shorter-k hit at same place
                    if not any(a <= i and j <= b for a, b in seen_spans):
                        hits.append({
                            "word_index": i, "block_words": k, "reps": reps,
                            "span_words": j - i,
                            "block": " ".join(ws[i:i + k])[:220],
                        })
                        seen_spans.append(span)
                i = j
            else:
                i += 1
    return hits

def tail_ngrams(ws, n_gram=16, tail_frac=0.20, min_count=4):
    n = len(ws)
    if n < n_gram * 4:
        return []
    tail_start = int(n * (1 - tail_frac))
    pos = defaultdict(list)
    for i in range(n - n_gram + 1):
        pos[tuple(ws[i:i + n_gram])].append(i)
    out = []
    for g, ps in pos.items():
        if len(ps) < min_count:
            continue
        in_tail = [p for p in ps if p >= tail_start]
        if len(in_tail) >= min_count - 1 and len(in_tail) >= 3:
            out.append({"count": len(ps), "in_tail": len(in_tail),
                        "first": ps[0], "last": ps[-1],
                        "ngram": " ".join(g)[:200]})
    out.sort(key=lambda d: -d["in_tail"])
    return out[:12]

def global_repeats(ws, n_gram=16, min_count=3):
    """Any 16-word block appearing >=3 times anywhere. In 8k words of code or
    prose this is unusual unless the model is repeating itself."""
    n = len(ws)
    if n < n_gram * 3:
        return []
    pos = defaultdict(list)
    for i in range(n - n_gram + 1):
        pos[tuple(ws[i:i + n_gram])].append(i)
    out = []
    for g, ps in pos.items():
        if len(ps) >= min_count:
            out.append({"count": len(ps), "positions": ps[:8],
                        "ngram": " ".join(g)[:200]})
    out.sort(key=lambda d: -d["count"])
    return out[:8]

def line_loops(text, min_reps=3, min_len=12):
    lines = text.splitlines()
    hits = []
    i = 0
    while i < len(lines):
        cur = lines[i].strip()
        if len(cur) >= min_len:
            j = i + 1
            while j < len(lines) and lines[j].strip() == cur:
                j += 1
            if j - i >= min_reps:
                hits.append({"line_index": i, "reps": j - i, "line": cur[:200]})
            i = j
        else:
            i += 1
    return hits

def analyse(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        t = f.read()
    ws = words(t)
    r = {
        "file": path,
        "bytes": os.path.getsize(path),
        "words": len(ws),
        "immediate_loops": immediate_loops(ws),
        "tail_ngrams": tail_ngrams(ws),
        "global_repeats": global_repeats(ws),
        "line_loops": line_loops(t),
        "tail_600": t[-600:],
        "unique_word_ratio": round(len(set(ws)) / max(1, len(ws)), 4),
    }
    return r

if __name__ == "__main__":
    files = sys.argv[1:]
    results = [analyse(p) for p in files]
    for r in results:
        verdict = "LOOPING" if (r["immediate_loops"] or r["line_loops"] or r["tail_ngrams"] or r["global_repeats"]) else "CLEAN"
        print("=" * 78)
        print("%s  [%s]" % (os.path.basename(r["file"]), verdict))
        print("  bytes=%d words=%d unique_word_ratio=%.4f" % (r["bytes"], r["words"], r["unique_word_ratio"]))
        for h in r["immediate_loops"][:6]:
            print("  IMMEDIATE-LOOP at word %d: %d-word block x%d (%d words) | %s"
                  % (h["word_index"], h["block_words"], h["reps"], h["span_words"], h["block"]))
        for h in r["line_loops"][:6]:
            print("  LINE-LOOP at line %d x%d | %s" % (h["line_index"], h["reps"], h["line"]))
        for h in r["tail_ngrams"][:6]:
            print("  TAIL-NGRAM-16 count=%d in_tail=%d first_word=%d last_word=%d | %s"
                  % (h["count"], h["in_tail"], h["first"], h["last"], h["ngram"]))
        for h in r["global_repeats"][:6]:
            print("  GLOBAL-REPEAT-16 count=%d at=%s | %s"
                  % (h["count"], h["positions"], h["ngram"]))
        print("  --- last 600 chars ---")
        print("  " + r["tail_600"].replace("\n", "\n  "))
