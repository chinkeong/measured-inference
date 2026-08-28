"""Overnight queue: four measurements, each isolated, artifacts written as they land.

    python overnight.py            run everything still outstanding
    python overnight.py --only vram|ngram|depth|empties

WHY A RUNNER. These run unattended while nobody is at the keyboard, so three
things matter more than usual: every task writes its artifact BEFORE anything
interprets it (this campaign lost two completed GPU runs on 2026-08-25 to a
crash in the paragraph that explains the numbers); a task that fails must not
take the rest of the night with it; and every probe records the machine state
it ran under, because host load is the largest error source on this rig and is
invisible to any clock or temperature log (rule 27).

THE FOUR, in priority order - each answers something a reader is currently
being told without evidence.

1. VRAM  - the published 12 GB block says UD-Q2_K_XL needs 11,396 MiB at
   -c 32768 with the drafter off, leaving 892 MiB, and concludes that if the
   card also draws your desktop then no window works. A sweep on 2026-08-26
   measured the allocation at 10,497 MiB, 899 MiB lower. One of those is wrong
   and a reader is being turned away from a configuration that may fit. This
   re-measures at the published flags exactly, from a verified-clean card.

2. NGRAM - UD-Q2_K_XL is the only one of the three 2-bit-class files that
   contains MTP draft layers; QAT-Q2_0 and UD-IQ2_S refuse `--spec-type
   draft-mtp` outright ("model doesn't contain MTP layers"). The QAT card
   recommends `--spec-type ngram-mod` instead, which this campaign has never
   measured. Negative-register entry 14 asks exactly this: name every drafting
   mechanism a model ships and mark each measured or unmeasured. An unmeasured
   alternative silently omitted reads as nonexistent.

3. DEPTH - the sharpest external criticism this page has received: the only
   reason to choose a 2-bit file is the big window, but its quality verdict
   comes from 75 SHORT-context items. The existing needle probe finds 5 of 5
   distinctive sentences out to 241,655 tokens, which is the easy version.
   This plants MANY SIMILAR numeric records and asks for one of them, across
   f16 / q8_0 / q4_0 KV - because KV quantisation error accumulates over cached
   tokens and is currently priced only in prose perplexity (+0.309% / +0.693%),
   which tests nothing about retrieval.

4. EMPTIES - the recommendation floor rests on 0 of 75 empty answers at
   2.912 bpw against 2 of 75 at 2.481, which is Fisher p = 0.50. Bounding an
   unseen rate below 1% needs ~300 generations per rung. Greedy decoding cannot
   supply them: repeats are identical, so re-running buys nothing. Sampling
   can, and sampling is what a reader actually uses - so this replays the code
   prompts (where every empty on the ladder lives except two) under the model
   card's recommended sampler with a fresh seed each time.
"""

import argparse
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts", "bench"))
import refarm

UNS = os.environ.get("MODEL_DIR", r"C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF")
QAT = r"C:\Users\chink\.lmstudio\models\sdkyuan\qwen3.8-27B-qat-q2_0-gguf\qwen38-27b-qat-q2_0.gguf"
FILES = {
    "UD-Q2_K_XL": os.path.join(UNS, "Qwen3.8-27B-UD-Q2_K_XL.gguf"),
    "QAT-Q2_0": QAT,
    "UD-IQ2_S": os.path.join(UNS, "Qwen3.8-27B-UD-IQ2_S.gguf"),
    "UD-IQ2_XXS": os.path.join(UNS, "Qwen3.8-27B-UD-IQ2_XXS.gguf"),
    "UD-IQ1_M": os.path.join(UNS, "Qwen3.8-27B-UD-IQ1_M.gguf"),
    "UD-IQ1_S": os.path.join(UNS, "Qwen3.8-27B-UD-IQ1_S.gguf"),
}
# which files task_empties walks; overridable so the lower rungs can be run
# separately. The first pass covered only the three 2-bit-class files, which
# left the finding half-made: if the low rungs' empties ALSO vanish under
# sampling then the whole column is a greedy artifact, and if they persist the
# column is real at the bottom and greedy-specific only near the boundary.
EMPTIES_FILES = ["UD-Q2_K_XL", "QAT-Q2_0", "UD-IQ2_S"]
OUT = os.path.join(ROOT, "results", "qwen38-27b-blind", "data", "overnight")
PORT = 1260
BASE = "http://127.0.0.1:%d" % PORT
SHIPPED = {"temperature": 1.0, "top_p": 0.95, "top_k": 20, "min_p": 0.0}
GREEDY = {"temperature": 0, "top_k": 1}


def log(m):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), m)
    print(line, flush=True)
    try:
        os.makedirs(OUT, exist_ok=True)
        io.open(os.path.join(OUT, "overnight.log"), "a",
                encoding="utf-8").write(line + "\n")
    except Exception:
        pass


def save(name, obj):
    """Artifact first, interpretation second. Always."""
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, name)
    json.dump(obj, io.open(p, "w", encoding="utf-8"), indent=1, default=str)
    log("-> %s" % p)


def smi():
    return float(subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        capture_output=True, text=True).stdout.strip().splitlines()[0])


def wait_clean(limit=2200, tries=40):
    for _ in range(tries):
        v = smi()
        if v < limit:
            return v
        time.sleep(3)
    return smi()


def post(payload, timeout=2400):
    req = urllib.request.Request(BASE + "/v1/chat/completions",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def serve(path, ctx, extra, tag):
    args = [refarm.SERVER, "-m", path, "--alias", "m", "-ngl", "99",
            "-c", str(ctx), "--parallel", "1", "-fa", "on",
            "--jinja", "--reasoning", "off",
            "--host", "127.0.0.1", "--port", str(PORT)] + extra
    os.makedirs(os.path.join(OUT, "logs"), exist_ok=True)
    lf = io.open(os.path.join(OUT, "logs", "%s.log" % tag), "a",
                 encoding="utf-8", errors="replace")
    p = subprocess.Popen(args, stdout=lf, stderr=subprocess.STDOUT)
    t0 = time.time()
    while time.time() - t0 < 900:
        if p.poll() is not None:
            lf.close()
            return None, None
        try:
            with urllib.request.urlopen(BASE + "/health", timeout=2) as r:
                if json.loads(r.read().decode()).get("status") == "ok":
                    return p, lf
        except Exception:
            pass
        time.sleep(2)
    return None, None


def kill(p, lf):
    if p and p.poll() is None:
        p.terminate()
        try:
            p.wait(timeout=30)
        except subprocess.TimeoutExpired:
            p.kill()
    try:
        if lf:
            lf.close()
    except Exception:
        pass
    wait_clean()


# ---------------------------------------------------------------- 1. VRAM
def task_vram():
    """Re-measure the published 12 GB configuration from a verified-clean card."""
    log("TASK vram: reconciling the 899 MiB gap against the published 11,396 MiB")
    base = wait_clean()
    log("verified-clean baseline: %.0f MiB" % base)
    rows = []
    # the published block's flags, verbatim, and then one variant at a time
    variants = [
        ("published flags", ["--load-mode", "none", "-ctk", "q8_0", "-ctv",
                             "q8_0", "--spec-type", "none"]),
        ("without --load-mode none", ["-ctk", "q8_0", "-ctv", "q8_0",
                                      "--spec-type", "none"]),
        ("f16 KV instead of q8_0", ["--load-mode", "none", "--spec-type", "none"]),
    ]
    for label, extra in variants:
        p, lf = serve(FILES["UD-Q2_K_XL"], 32768, extra, "vram-%s" % label.split()[0])
        if not p:
            log("  %-26s FAILED TO LOAD" % label)
            rows.append({"variant": label, "loaded": False})
            continue
        peak = smi()
        try:
            post({"model": "m", "max_tokens": 200, "cache_prompt": True,
                  "messages": [{"role": "user", "content": "Say OK."}], **GREEDY})
            peak = max(peak, smi())
        except Exception as e:
            log("  probe failed: %s" % e)
        kill(p, lf)
        rows.append({"variant": label, "loaded": True, "peak_mib": peak,
                     "baseline_mib": base, "alloc_mib": round(peak - base)})
        log("  %-26s total %6.0f MiB   allocation %6.0f MiB"
            % (label, peak, peak - base))
    save("vram-reconcile.json",
         {"date": time.strftime("%Y-%m-%d %H:%M"), "published_total_mib": 11396,
          "baseline_mib": base, "rows": rows})
    log("TASK vram: done")


# ---------------------------------------------------------------- 2. NGRAM
def task_ngram():
    """Every drafting mechanism these files can actually use (register entry 14)."""
    log("TASK ngram: drafters on files that have no MTP layers")
    prompt = ("Write a single self-contained Python module implementing an LRU "
              "cache with a capacity limit, get/put in O(1), and a docstring on "
              "every method. Include three example calls. Code only.")
    drafters = [
        ("none", ["--spec-type", "none"]),
        ("ngram-mod (card's own)", ["--spec-type", "ngram-mod",
                                    "--spec-ngram-mod-n-match", "24",
                                    "--spec-ngram-mod-n-min", "48",
                                    "--spec-ngram-mod-n-max", "64"]),
        ("ngram-simple", ["--spec-type", "ngram-simple"]),
        ("ngram-cache", ["--spec-type", "ngram-cache"]),
        ("draft-mtp", ["--spec-type", "draft-mtp", "--spec-draft-n-max", "4",
                       "--spec-draft-p-min", "0.75"]),
    ]
    rows = []
    for fname, path in FILES.items():
        for dlabel, extra in drafters:
            q = refarm.quiet_report()
            p, lf = serve(path, 32768, ["-ctk", "q8_0", "-ctv", "q8_0"] + extra,
                          "ngram-%s-%s" % (fname, dlabel.split()[0]))
            if not p:
                log("  %-12s %-24s NOT SUPPORTED (server refused)" % (fname, dlabel))
                rows.append({"file": fname, "drafter": dlabel, "loaded": False})
                continue
            tps, acc = [], []
            try:
                post({"model": "m", "max_tokens": 500, "cache_prompt": True,
                      "messages": [{"role": "user", "content": prompt}], **GREEDY})
                for _ in range(3):
                    r = post({"model": "m", "max_tokens": 500, "cache_prompt": True,
                              "messages": [{"role": "user", "content": prompt}],
                              **GREEDY})
                    t = r.get("timings", {})
                    tps.append(t.get("predicted_per_second", 0))
                    dn, da = t.get("draft_n"), t.get("draft_n_accepted")
                    if dn:
                        acc.append(da / dn)
            except Exception as e:
                log("  probe failed: %s" % e)
            peak = smi()
            kill(p, lf)
            m = sum(tps) / len(tps) if tps else 0
            rows.append({"file": fname, "drafter": dlabel, "loaded": True,
                         "tps": round(m, 2), "peak_mib": peak,
                         "acceptance": round(sum(acc) / len(acc), 3) if acc else None,
                         "host": q["status"], "probes": [round(x, 2) for x in tps]})
            log("  %-12s %-24s %6.2f t/s   %5.0f MiB   acc %s"
                % (fname, dlabel, m, peak,
                   round(sum(acc) / len(acc), 3) if acc else "-"))
        save("ngram-drafters.json", {"date": time.strftime("%Y-%m-%d %H:%M"),
                                     "rows": rows})
    log("TASK ngram: done")


# ---------------------------------------------------------------- 3. DEPTH
def _records(n):
    """Many SIMILAR numeric records - the hard version of a needle test."""
    out = []
    for i in range(1, n + 1):
        out.append("Record %04d | shard %02d | region %s | latency %d ms | "
                   "retries %d | checksum %05X"
                   % (i, i % 64, "abcdefgh"[i % 8], 100 + (i * 37) % 900,
                      i % 7, (i * 48271) % 1048573))
    return out


def task_depth():
    """Retrieval among distractors, at depth, across KV precision."""
    log("TASK depth: distractor retrieval x KV precision")
    kvs = [("f16", []), ("q8_0", ["-ctk", "q8_0", "-ctv", "q8_0"]),
           ("q4_0", ["-ctk", "q4_0", "-ctv", "q4_0"])]
    # CALIBRATION, corrected twice. The first attempt read 17.7 tokens per
    # record from a cached prompt_n and was wrong: `cache_prompt` makes
    # prompt_n report NEWLY PROCESSED tokens, and the three depths shared a
    # prefix, so the later figures were increments and not depths. Measured
    # uncached, one record is 33.2 tokens. The second attempt then overshot
    # and asked for ~123k against a 98,304 server, which is the HTTP 400 in
    # that log. Each depth now gets its OWN server load, so prompt_n is always
    # the true depth, and the largest fits the window with room to answer in.
    depths = [(1860, 61727), (2700, 89000), (3600, 118000)]
    rows = []
    for fname in ("UD-Q2_K_XL", "QAT-Q2_0"):
        for kvlabel, kvflags in kvs:
          for nrec, target_tok in depths:
            ctx = 131072
            p, lf = serve(FILES[fname], ctx, kvflags + ["--spec-type", "none"],
                          "depth-%s-%s-%d" % (fname, kvlabel, nrec))
            if not p:
                log("  %-12s KV %-5s %5d rec FAILED TO LOAD" % (fname, kvlabel, nrec))
                rows.append({"file": fname, "kv": kvlabel, "records": nrec,
                             "loaded": False})
                continue
            try:
                for _once in (1,):
                    recs = _records(nrec)
                    body = "\n".join(recs)
                    hits = 0
                    asked = []
                    for frac in (0.1, 0.3, 0.5, 0.7, 0.9):
                        idx = max(1, int(nrec * frac))
                        want = re.search(r"latency (\d+) ms", recs[idx - 1]).group(1)
                        q = ("%s\n\nUsing only the table above, what is the latency "
                             "in ms for Record %04d? Reply with the number only."
                             % (body, idx))
                        r = post({"model": "m", "max_tokens": 24,
                                  "cache_prompt": True,
                                  "messages": [{"role": "user", "content": q}],
                                  **GREEDY})
                        a = (r["choices"][0]["message"]["content"] or "").strip()
                        got = re.search(r"\d+", a)
                        ok = bool(got and got.group(0) == want)
                        hits += 1 if ok else 0
                        asked.append({"record": idx, "want": want, "got": a[:40],
                                      "ok": ok,
                                      "prompt_n": r.get("timings", {}).get("prompt_n")})
                    rows.append({"file": fname, "kv": kvlabel, "loaded": True,
                                 "records": nrec, "target_tokens": target_tok,
                                 "hits": hits, "of": 5, "detail": asked})
                    log("  %-12s KV %-5s %4d records (~%s tok)  %d/5 correct"
                        % (fname, kvlabel, nrec,
                           asked[0].get("prompt_n"), hits))
                    save("depth-retrieval.json",
                         {"date": time.strftime("%Y-%m-%d %H:%M"), "rows": rows})
            except Exception as e:
                log("  depth probe failed: %s" % e)
            kill(p, lf)
    save("depth-retrieval.json", {"date": time.strftime("%Y-%m-%d %H:%M"),
                                  "rows": rows})
    log("TASK depth: done")


# ---------------------------------------------------------------- 4. EMPTIES
def _code_prompts():
    """The exact HumanEval/MBPP prompts already used on the ladder."""
    import glob
    g = glob.glob(os.path.join(ROOT, "results", "qwen38-27b-blind", "data",
                               "quant-ladder", "bench",
                               "arm-qwen-iq2s-Qwen*transcripts.json"))
    d = json.load(io.open(g[0], encoding="utf-8"))
    out = []
    for suite in ("HumanEval", "MBPP"):
        for it in d["generations"].get(suite, []):
            out.append((suite, it["index"], it["prompt"]))
    return out


def task_empties(seeds=6):
    """Power for the empty-answer rate, where the empties actually live."""
    log("TASK empties: code prompts x %d seeds, shipped sampler" % seeds)
    prompts = _code_prompts()
    log("  %d code prompts recovered from the frozen suite" % len(prompts))
    rows = []
    for fname in EMPTIES_FILES:
        p, lf = serve(FILES[fname], 32768,
                      ["-ctk", "q8_0", "-ctv", "q8_0", "--spec-type", "none"],
                      "empties-%s" % fname)
        if not p:
            log("  %-12s FAILED TO LOAD" % fname)
            continue
        empt, total, cases = 0, 0, []
        try:
            for seed in range(42, 42 + seeds):
                for suite, idx, text in prompts:
                    r = post({"model": "m", "max_tokens": 16384,
                              "cache_prompt": True, "seed": seed,
                              "messages": [{"role": "user", "content": text}],
                              **SHIPPED})
                    a = (r["choices"][0]["message"]["content"] or "")
                    tk = r.get("timings", {}).get("predicted_n")
                    total += 1
                    if not a.strip():
                        empt += 1
                        cases.append({"suite": suite, "index": idx, "seed": seed,
                                      "tokens": tk, "at_cap": bool(tk and tk >= 16300)})
                log("  %-12s seed %d done: %d empty of %d so far"
                    % (fname, seed, empt, total))
                save("empties-power.json",
                     {"date": time.strftime("%Y-%m-%d %H:%M"), "rows": rows,
                      "in_progress": {"file": fname, "empty": empt,
                                      "total": total, "cases": cases}})
        except Exception as e:
            log("  empties probe failed: %s" % e)
        kill(p, lf)
        rate = empt / total * 100 if total else 0
        rows.append({"file": fname, "generations": total, "empty": empt,
                     "rate_pct": round(rate, 2),
                     "rule_of_three_upper_pct": round(3 / total * 100, 2) if total else None,
                     "cases": cases})
        log("  %-12s FINAL %d empty of %d generations (%.2f%%)"
            % (fname, empt, total, rate))
        save("empties-power.json", {"date": time.strftime("%Y-%m-%d %H:%M"),
                                    "rows": rows})
    log("TASK empties: done")


TASKS = [("vram", task_vram), ("ngram", task_ngram), ("depth", task_depth),
         ("empties", task_empties)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=[n for n, _ in TASKS])
    ap.add_argument("--files", help="comma-separated file keys for --only empties")
    a = ap.parse_args()
    if a.files:
        global EMPTIES_FILES
        EMPTIES_FILES = [x.strip() for x in a.files.split(",")]
    log("=" * 62)
    log("OVERNIGHT QUEUE START   host: %s" % refarm.quiet_report()["status"])
    for name, fn in TASKS:
        if a.only and a.only != name:
            continue
        try:
            fn()
        except Exception as e:
            log("TASK %s FAILED: %r - continuing with the rest" % (name, e))
    log("OVERNIGHT QUEUE COMPLETE")


main()
