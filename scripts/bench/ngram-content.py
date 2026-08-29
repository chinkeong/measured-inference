"""How much does ngram-mod's speedup depend on what you are writing?

    python ngram-content.py

WHY. The register now publishes "3.9x on code, 1.5x on prose" for
`--spec-type ngram-mod`, and that claim rests on TWO prompts. It is hedged as a
range with a named workload, which is honest, but a published figure standing
on n=2 is thin by this campaign's own standard - and this drafter's speedup is
content-dependent by construction, so two samples cannot describe its range.

An n-gram drafter proposes continuations copied from text already in the
context. It therefore wins exactly where text REPEATS, and the question is not
"how fast is it" but "how much repetition does your work contain". Six content
types, chosen to span that axis rather than to be representative of anything:

  boilerplate   getters/setters over many fields - maximum self-similarity
  code          a novel algorithm, little internal repetition
  refactor      the input restated with one systematic change, so the output
                is largely a copy of the prompt - the drafter's best case, and
                the one real agentic work most resembles
  json          structured records, repetitive punctuation and keys
  prose         an explanation, low repetition
  translation   the same content re-expressed - repetition of MEANING but not
                of tokens, which is where an n-gram drafter should fail

Each runs against no drafter, ngram-mod, and draft-mtp, greedy, one server
load per drafter so the comparison within a load is exact. Speculative decoding
is lossless under greedy, so identical output is the CHECK - any content where
the three disagree means something is wrong with the run, not with the drafter.

WHAT IT SHOULD PRODUCE. Not a headline number. A range with the shape of the
work named, so a reader can locate their own workload on it instead of
expecting 3.9x and getting 1.2x.
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
sys.path.insert(0, HERE)
import refarm
import gpu_lock

MODEL = os.path.join(os.environ.get("MODEL_DIR", r"C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF"),
                     "Qwen3.8-27B-UD-Q2_K_XL.gguf")
PORT = 1270
BASE = "http://127.0.0.1:%d" % PORT
OUT = os.path.join(ROOT, "results", "qwen38-27b-blind", "data", "register")
NPREDICT = 700

FIELDS = ", ".join("field_%02d" % i for i in range(1, 25))
SAMPLE = "\n".join(
    "  { \"id\": %d, \"shard\": %d, \"latency_ms\": %d, \"ok\": %s }," %
    (i, i % 8, 100 + (i * 37) % 900, "true" if i % 3 else "false")
    for i in range(1, 13))

PROMPTS = [
    ("boilerplate",
     "Write a Python class Config with exactly these 24 attributes: %s. "
     "For EACH one write a property getter and a setter that validates the "
     "value is not None. Code only, no explanation." % FIELDS),
    ("code",
     "Write a single self-contained Python module implementing a "
     "self-balancing AVL tree with insert, delete and in-order traversal. "
     "Docstring on every method. Code only."),
    ("refactor",
     "Here is a JSON array:\n%s\n\nRewrite it exactly, changing only "
     "`latency_ms` to `latency_seconds` with the value divided by 1000 and "
     "written to three decimal places. Output the full array, nothing else."
     % SAMPLE),
    ("json",
     "Emit a JSON array of 20 objects. Each has keys id, region, latency_ms, "
     "retries, ok - id counting from 1, region cycling through north, south, "
     "east, west, latency_ms = 100 + 37*id modulo 900, retries = id modulo 5, "
     "ok true unless id is divisible by 3. JSON only."),
    ("prose",
     "Explain in five paragraphs why memory bandwidth rather than compute "
     "limits single-stream text generation on consumer GPUs, and what changes "
     "when speculative decoding is used."),
    ("translation",
     "Translate the following into formal French, preserving paragraph "
     "breaks:\n\nMemory bandwidth is the number that decides how fast a "
     "language model writes. The card must read every weight it uses for each "
     "token it produces. A smaller file is read faster. Speculation changes "
     "the arithmetic by verifying several tokens in one pass."),
]

DRAFTERS = [
    ("none", ["--spec-type", "none"]),
    ("ngram-mod", ["--spec-type", "ngram-mod", "--spec-ngram-mod-n-match", "24",
                   "--spec-ngram-mod-n-min", "48", "--spec-ngram-mod-n-max", "64"]),
    ("draft-mtp", ["--spec-type", "draft-mtp", "--spec-draft-n-max", "4",
                   "--spec-draft-p-min", "0.75"]),
]


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def post(payload, timeout=1800):
    req = urllib.request.Request(BASE + "/v1/chat/completions",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def serve(extra, tag):
    args = [refarm.server_bin(), "-m", MODEL, "--alias", "m", "-ngl", "99",
            "-c", "32768", "--parallel", "1", "-fa", "on",
            "-ctk", "q8_0", "-ctv", "q8_0", "--jinja", "--reasoning", "off",
            "--host", "127.0.0.1", "--port", str(PORT)] + extra
    os.makedirs(os.path.join(OUT, "ngram-logs"), exist_ok=True)
    lf = io.open(os.path.join(OUT, "ngram-logs", "%s.log" % tag), "a",
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
            if float(refarm.smi("memory.used")) < 2400:
                return
        except Exception:
            pass


def repetition(text):
    toks = re.findall(r"\S+", text)
    tri = [tuple(toks[i:i + 3]) for i in range(max(0, len(toks) - 2))]
    return round(1.0 - (len(set(tri)) / len(tri)), 4) if tri else 0.0


USAGE = """\
How much does the ngram-mod speedup depend on what you are writing? Six
content types against three drafters, greedy, one server load per drafter.

    python scripts/bench/ngram-content.py

Positional arguments: none. The content types (boilerplate, code, refactor,
json, prose, translation), the drafters (none, ngram-mod, draft-mtp) and the
700 predicted tokens are pinned in this file.

MODEL_DIR is REQUIRED off the machine this was written on: the model path
defaults to a Windows LM Studio directory, and the file wanted inside it is
Qwen3.8-27B-UD-Q2_K_XL.gguf.

Environment, all optional:
  LLAMA_SERVER / LLAMA_DIR       where llama-server is (scripts/lib/paths.py)
  MODEL_DIR                      directory holding the .gguf weights
  MEASURED_INFERENCE_DRY_RUN=1   gpu_lock refuses the card, so nothing loads
  MEASURED_INFERENCE_MEM_CAP_GB  per-job commit cap (gpu_lock)
  MEASURED_INFERENCE_LOCK        the one-job lockfile (gpu_lock)

Takes the card: one llama-server per drafter through gpu_lock.serve.
Writes results/qwen38-27b-blind/data/register/ngram-content.json.

Greedy speculative decoding is lossless, so identical output across the three
drafters is the check that the run is sound.
"""


def main():
    # A help request must never start work. This script has no argument parser,
    # so without this line --help falls through and loads a model (rule 20).
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        print(USAGE.rstrip())
        return

    os.makedirs(OUT, exist_ok=True)
    log("host: %s" % refarm.quiet_report()["status"])
    log("six content types x three drafters, greedy, UD-Q2_K_XL")
    results = {}
    texts = {}
    for dname, extra in DRAFTERS:
        p, lf = serve(extra, dname)
        if not p:
            log("  %-10s FAILED TO LOAD" % dname)
            continue
        try:
            for pname, prompt in PROMPTS:
                post({"model": "m", "temperature": 0, "top_k": 1,
                      "max_tokens": 200, "cache_prompt": True,
                      "messages": [{"role": "user", "content": prompt}]})
                r = post({"model": "m", "temperature": 0, "top_k": 1,
                          "max_tokens": NPREDICT, "cache_prompt": True,
                          "messages": [{"role": "user", "content": prompt}]})
                t = r.get("timings", {})
                txt = r["choices"][0]["message"]["content"] or ""
                dn, da = t.get("draft_n"), t.get("draft_n_accepted")
                results.setdefault(pname, {})[dname] = {
                    "tps": round(t.get("predicted_per_second", 0), 2),
                    "predicted_n": t.get("predicted_n"),
                    "acceptance": round(da / dn, 3) if dn else None,
                    "repetition": repetition(txt),
                }
                texts.setdefault(pname, {})[dname] = txt
                log("  %-10s %-12s %7.2f t/s  acc %-6s repetition %.3f"
                    % (dname, pname, results[pname][dname]["tps"],
                       results[pname][dname]["acceptance"],
                       results[pname][dname]["repetition"]))
        except Exception as e:
            log("  probe failed: %s" % e)
        kill(p, lf)

    log("")
    log("%-12s %10s %12s %10s %8s %10s"
        % ("content", "no drafter", "ngram-mod", "draft-mtp", "ngram x", "repetition"))
    rows = []
    for pname, _ in PROMPTS:
        d = results.get(pname, {})
        if "none" not in d:
            continue
        base = d["none"]["tps"] or 1
        ng = d.get("ngram-mod", {}).get("tps")
        mt = d.get("draft-mtp", {}).get("tps")
        # lossless check: greedy speculation must reproduce the same text
        same = len({texts[pname].get(k, "") for k in texts.get(pname, {})}) == 1
        rows.append({"content": pname, "none": base, "ngram_mod": ng,
                     "draft_mtp": mt,
                     "ngram_speedup": round(ng / base, 2) if ng else None,
                     "mtp_speedup": round(mt / base, 2) if mt else None,
                     "repetition": d["none"]["repetition"],
                     "identical_output_across_drafters": same})
        log("%-12s %10.2f %12s %10s %8s %10.3f%s"
            % (pname, base, ng, mt,
               ("%.2fx" % (ng / base)) if ng else "-",
               d["none"]["repetition"], "" if same else "   *** OUTPUT DIFFERS"))

    ok = [r for r in rows if r["ngram_speedup"]]
    if ok:
        lo = min(r["ngram_speedup"] for r in ok)
        hi = max(r["ngram_speedup"] for r in ok)
        log("")
        log("ngram-mod ranges %.2fx to %.2fx across these six content types."
            % (lo, hi))
        log("The register currently publishes 3.9x on code and 1.5x on prose")
        log("from two prompts. Replace that with this range and the shape of")
        log("the work, not with a single number.")
    json.dump({"date": time.strftime("%Y-%m-%d %H:%M"),
               "model": os.path.basename(MODEL), "npredict": NPREDICT,
               "note": "greedy; speculative decoding is lossless under greedy so "
                       "identical output across drafters is the correctness check",
               "rows": rows, "raw": results},
              io.open(os.path.join(OUT, "ngram-content.json"), "w",
                      encoding="utf-8"), indent=1)
    log("-> %s" % os.path.join(OUT, "ngram-content.json"))


if __name__ == "__main__":
    main()
