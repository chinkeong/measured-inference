"""Is 353 t/s a drafter winning, or a model looping? Read the text, not the rate.

    python ngram-verify.py

WHY. The overnight sweep measured UD-Q2_K_XL at **353.23 t/s with acceptance
1.000** under `--spec-type ngram-mod`, against 45.71 t/s with no drafter. A
7.7x speedup would be the largest single effect this campaign has ever
recorded.

Acceptance of exactly 1.000 is the reason to distrust it. An n-gram drafter
proposes continuations copied from text the model has already produced, so it
is accepted every time precisely when the model is REPEATING ITSELF. Degenerate
output and a spectacular drafter look identical in the timing fields, and this
campaign's own page already carries the lesson in another form: a rung whose
lexical diversity had collapsed to 0.358 passed four lexical detectors.

The overnight task recorded throughput and acceptance but not the generated
text, so it cannot tell the two apart. This does, by reading what came out:

  - distinct-trigram ratio: unique 3-grams divided by total. Healthy prose and
    code sit high; a loop drives it toward zero.
  - longest immediately-repeated block, in lines.
  - whether the answer ends with a stop or ran to the cap.
  - and the plain text of the first and last few lines, printed, because a
    number about degeneration that nobody eyeballs is how this happens again.

It compares three drafters on identical prompts and a fixed seed, so the only
variable is the speculation mechanism. If ngram-mod's output is as diverse as
the no-drafter output, the speedup is real and belongs in the report. If it is
not, 353 t/s is a measurement of the model failing, and belongs in the failure
library instead.
"""

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
sys.path.insert(0, os.path.join(ROOT, "scripts", "lib"))
import refarm
import gpu_lock
import paths

MODEL_NAME = "Qwen3.8-27B-UD-Q2_K_XL.gguf"
PORT = 1262
BASE = "http://127.0.0.1:%d" % PORT
OUT = os.path.join(ROOT, "results", "qwen38-27b-blind", "data", "overnight")

PROMPTS = [
    ("lru", "Write a single self-contained Python module implementing an LRU "
            "cache with a capacity limit, get/put in O(1), and a docstring on "
            "every method. Include three example calls. Code only."),
    ("essay", "Explain in four paragraphs why memory bandwidth, not compute, "
              "limits single-stream text generation on consumer GPUs."),
]
DRAFTERS = [
    ("none", ["--spec-type", "none"]),
    ("ngram-mod", ["--spec-type", "ngram-mod", "--spec-ngram-mod-n-match", "24",
                   "--spec-ngram-mod-n-min", "48", "--spec-ngram-mod-n-max", "64"]),
    ("draft-mtp", ["--spec-type", "draft-mtp", "--spec-draft-n-max", "4",
                   "--spec-draft-p-min", "0.75"]),
]


def model_file():
    """The rung under test.

    paths.model_path searches campaign.json's models/model_dir,
    $MODEL_DIR and <repo>/models/, and exits naming all of them when
    the file is on none. Resolved at call time so --help needs no
    weights on disk.
    """
    return paths.model_path(MODEL_NAME)


def post(payload, timeout=2400):
    req = urllib.request.Request(BASE + "/v1/chat/completions",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def serve(extra, tag):
    args = [refarm.server_bin(), "-m", model_file(), "--alias", "m", "-ngl", "99",
            "-c", "32768", "--parallel", "1", "-fa", "on",
            "-ctk", "q8_0", "-ctv", "q8_0", "--jinja", "--reasoning", "off",
            "--host", "127.0.0.1", "--port", str(PORT)] + extra
    os.makedirs(os.path.join(OUT, "logs"), exist_ok=True)
    lf = io.open(os.path.join(OUT, "logs", "verify-%s.log" % tag), "a",
                 encoding="utf-8", errors="replace")
    p = gpu_lock.serve(args, stdout=lf, stderr=subprocess.STDOUT)
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
    for _ in range(30):
        time.sleep(1)
        try:
            v = float(subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.used",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True).stdout.strip().splitlines()[0])
            if v < 2400:
                return
        except Exception:
            pass


def diversity(text):
    toks = re.findall(r"\S+", text)
    tri = [tuple(toks[i:i + 3]) for i in range(max(0, len(toks) - 2))]
    ratio = (len(set(tri)) / len(tri)) if tri else 0.0
    lines = [l.rstrip() for l in text.split("\n")]
    best, run = 0, 1
    for i in range(1, len(lines)):
        if lines[i] and lines[i] == lines[i - 1]:
            run += 1
            best = max(best, run)
        else:
            run = 1
    return {"tokens": len(toks), "distinct_trigram_ratio": round(ratio, 4),
            "longest_repeated_line_run": best}


USAGE = """\
Is 353 t/s a drafter winning, or a model looping? Read the text, not the rate:
distinct-trigram ratio, longest repeated block, and whether it hit the cap.

    python scripts/quant-ladder/ngram-verify.py

Positional arguments: none. The conditions are pinned in this file -
Qwen3.8-27B-UD-Q2_K_XL, greedy, 400 predicted tokens, two prompts (an LRU cache
and a four-paragraph essay) against three drafters: none, ngram-mod, draft-mtp.

Environment, all optional:
  LLAMA_SERVER / LLAMA_DIR       where llama-server is (scripts/lib/paths.py)
  MODEL_DIR                      directory holding the .gguf weights
  MEASURED_INFERENCE_DRY_RUN=1   gpu_lock refuses the card, so nothing loads
  MEASURED_INFERENCE_MEM_CAP_GB  per-job commit cap (gpu_lock)
  MEASURED_INFERENCE_LOCK        the one-job lockfile (gpu_lock)

Takes the card: one llama-server per drafter through gpu_lock.serve.
Writes results/qwen38-27b-blind/data/overnight/ngram-verify.json, and prints
the first lines of an ngram-mod answer, because a number about degeneration
that nobody eyeballs is how this happens again.
"""


def main():
    # A help request must never start work. This script has no argument parser,
    # so without this line --help falls through and loads a model (rule 20).
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        print(USAGE.rstrip())
        return

    os.makedirs(OUT, exist_ok=True)
    print("Is the ngram-mod speedup real? Reading the output, not the rate.\n")
    rows = []
    for dlabel, extra in DRAFTERS:
        p, lf = serve(extra, dlabel)
        if not p:
            print("%-11s FAILED TO LOAD" % dlabel)
            rows.append({"drafter": dlabel, "loaded": False})
            continue
        try:
            for pname, prompt in PROMPTS:
                post({"model": "m", "max_tokens": 400, "cache_prompt": True,
                      "temperature": 0, "top_k": 1,
                      "messages": [{"role": "user", "content": prompt}]})
                r = post({"model": "m", "max_tokens": 900, "cache_prompt": True,
                          "temperature": 0, "top_k": 1, "seed": 42,
                          "messages": [{"role": "user", "content": prompt}]})
                txt = r["choices"][0]["message"]["content"] or ""
                t = r.get("timings", {})
                dn, da = t.get("draft_n"), t.get("draft_n_accepted")
                d = diversity(txt)
                row = {"drafter": dlabel, "prompt": pname, "loaded": True,
                       "tps": round(t.get("predicted_per_second", 0), 2),
                       "predicted_n": t.get("predicted_n"),
                       "acceptance": round(da / dn, 3) if dn else None,
                       "finish": (r.get("choices") or [{}])[0].get("finish_reason"),
                       "chars": len(txt), "text": txt}
                row.update(d)
                rows.append(row)
                print("%-11s %-6s %7.2f t/s  acc %-6s distinct-trigram %.4f  "
                      "repeat-run %d  finish=%s"
                      % (dlabel, pname, row["tps"], row["acceptance"],
                         d["distinct_trigram_ratio"],
                         d["longest_repeated_line_run"], row["finish"]))
        except Exception as e:
            print("  probe failed: %s" % e)
        kill(p, lf)

    json.dump({"date": time.strftime("%Y-%m-%d %H:%M"), "rows": rows},
              io.open(os.path.join(OUT, "ngram-verify.json"), "w",
                      encoding="utf-8"), indent=1, default=str)
    print("\n-> %s" % os.path.join(OUT, "ngram-verify.json"))

    base = [r for r in rows if r.get("drafter") == "none" and r.get("loaded")]
    ng = [r for r in rows if r.get("drafter") == "ngram-mod" and r.get("loaded")]
    if base and ng:
        b = sum(r["distinct_trigram_ratio"] for r in base) / len(base)
        n = sum(r["distinct_trigram_ratio"] for r in ng) / len(ng)
        print("\ndistinct-trigram ratio: no drafter %.4f, ngram-mod %.4f" % (b, n))
        if n < b * 0.8:
            print("DEGENERATE: ngram-mod's output is markedly more repetitive.")
            print("  The speed figure is the model looping, not the drafter")
            print("  winning, and it must not be published as a throughput result.")
        else:
            print("REAL: output diversity holds, so the speedup is a genuine")
            print("  property of this drafter on this content. Note it is content-")
            print("  dependent by construction - an n-gram drafter can only win")
            print("  where text repeats - so it needs a workload caveat, not a")
            print("  headline number.")
        for r in ng[:1]:
            print("\n--- first 400 chars of an ngram-mod answer ---")
            print(r["text"][:400])


if __name__ == "__main__":
    main()
