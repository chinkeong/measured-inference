"""Measure the QAT Q2_0 file as a new rung of the quant ladder.

    python qat-rung.py --step all
    python qat-rung.py --step verify|smoke|ppl|tokens|accuracy|execute

WHAT THIS IS. `sdkyuan/qwen3.8-27B-qat-q2_0-gguf` is the first
QUANTISATION-AWARE-TRAINED file this campaign has looked at. Every rung on the
existing ladder is post-training quantisation from one publisher (Unsloth), so
the ladder currently measures one production method and calls it "bits per
weight". If QAT lands where its bpw says it should, the ladder's x-axis is
about bits. If it lands higher, the axis is about bits AND method, and every
recommendation keyed to a bpw number needs that caveat.

WHAT IT ACTUALLY IS, read from the GGUF header before downloading anything
(`gguf-inspect.py --hf`, 11 MiB fetched of 8.16 GiB):

    file            8,759,266,208 bytes = 8.16 GiB
    ggml type 42 = Q2_0, 18 bytes per 64 weights = 2.25 bpw exactly,
                   carrying 89.8% of all weights (all FFN, most attention)
    embedding       Q4_K  4.50 bpw
    output          Q6_K  6.56 bpw
    norms           F32
    architecture    qwen35   (the same arch the campaign already runs)
    general.file_type 41 = Q2_0, and `llama-quantize --help` in the pinned
                   build lists "41 or Q2_0 : 2.25 bpw quantization (group 64)",
                   so this build supports it - confirmed before scheduling.

    ON THE LADDER'S OWN CONVENTION (params = 27,000,000,000, fixed for every
    rung, per ladder-manifest.json): **2.595 bpw**.

That places it between UD-IQ2_S (2.481) and UD-Q2_K_XL (2.912) - and directly
on top of the campaign's measured floor, which is the most interesting bpw on
the whole chart. UD-IQ2_S is where empty answers first appear (2 of 75) and
UD-IQ2_XXS at 2.153 is where generated code stops executing.

THE PUBLISHER'S CLAIM, which this rung can check rather than repeat: their card
reports QAT beating UD-Q2_K_XL on reasoning (94.7 vs 94.4 top-1) and code
(93.3 vs 93.1) while LOSING on tool calling (78.7 vs 82.5) and wikitext
(78.3 vs 87.5). Those are top-1-agreement and KL numbers against an FP16
teacher, which is a different instrument from anything here - this campaign
measures scored accuracy, perplexity and whether the code runs. A directional
prediction falls out of their claim: the QAT file should do WELL on
GSM8K/HumanEval/MBPP and BADLY on wikitext perplexity relative to its bpw.
That is a real prediction and this rung tests it.

CONDITIONS - taken from ladder-manifest.json so the numbers join the existing
eight rather than starting a second ladder:
    ppl        llama-perplexity -ngl 99 -c 8192 -fa on --load-mode mmap,
               f16 KV (default), corpus wikitext-2-raw-test.raw pinned at
               md5 7c0137fc034ddbc56a296bce31b4f7fb
    tokens     llama-tokenize --show-count, the model's OWN count (rule 6,
               needed for bits-per-byte since PPL is not comparable across
               tokenizers)
    accuracy   the frozen suite via decisive-arm.ps1: GSM8K/HumanEval/MBPP,
               n=25 each (the /75), greedy, seed 42, cap 16,384, -c 32768,
               -ctk q8_0 -ctv q8_0, reasoning_effort=low, NO drafter
    execute    execute-probe.py - runs the generated JavaScript under node,
               the instrument that registers degradation a full rung above
               where the paired accuracy test can resolve anything

NOT a speed measurement, so rule 27's quiet-machine requirement is not binding
on the numbers here - but it IS reported per step, because a busy host makes
everything take longer and the deadline logic cares.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts", "bench"))
import gpu_lock

MODEL_DIR = r"C:\Users\chink\.lmstudio\models\sdkyuan\qwen3.8-27B-qat-q2_0-gguf"
MODEL = os.path.join(MODEL_DIR, "qwen38-27b-qat-q2_0.gguf")
EXPECT_BYTES = 8759266208

LLAMA = r"E:\AI\llama.cpp"
PPL_EXE = os.path.join(LLAMA, "llama-perplexity.exe")
TOK_EXE = os.path.join(LLAMA, "llama-tokenize.exe")
SRV_EXE = os.path.join(LLAMA, "llama-server.exe")
CORPUS = os.path.join(ROOT, "corpora", "wikitext-2-raw-test.raw")
CORPUS_MD5 = "7c0137fc034ddbc56a296bce31b4f7fb"

OUT = os.path.join(ROOT, "results", "qwen38-27b-blind", "data", "quant-ladder",
                   "qat-q2_0")
TAG = "qwen-qat-q2_0"
LADDER_PARAMS = 27000000000            # the ladder's fixed convention

# what the chart needs, and where each column comes from
COLUMNS = ["bpw", "PPL", "accuracy/75", "empty/75", "executes"]


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def host():
    try:
        import refarm
        q = refarm.quiet_report()
        return "%s (%sx idle)" % (q["status"], q.get("ratio", "?"))
    except Exception as e:
        return "unknown (%s)" % e


def save(name, obj):
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, name)
    json.dump(obj, open(p, "w", encoding="utf-8"), indent=1, default=str)
    log("-> %s" % p)


def step_verify():
    if not os.path.exists(MODEL):
        sys.exit("model not present: %s\n  download it first" % MODEL)
    n = os.path.getsize(MODEL)
    ok = (n == EXPECT_BYTES)
    log("file %d bytes (%.2f GiB) expected %d  %s"
        % (n, n / 1024 ** 3, EXPECT_BYTES, "OK" if ok else "*** MISMATCH ***"))
    if not ok:
        sys.exit("size mismatch - the download is incomplete or the file changed")
    if not os.path.exists(CORPUS):
        sys.exit("corpus missing: %s" % CORPUS)
    md5 = hashlib.md5(open(CORPUS, "rb").read()).hexdigest()
    log("corpus md5 %s  %s" % (md5, "OK" if md5 == CORPUS_MD5 else "*** MISMATCH ***"))
    if md5 != CORPUS_MD5:
        sys.exit("corpus does not match the manifest - PPL would not be comparable")
    r = subprocess.run([sys.executable, os.path.join(HERE, "gguf-inspect.py"), MODEL],
                       capture_output=True, text=True)
    print(r.stdout)
    bpw_chart = n * 8.0 / LADDER_PARAMS
    log("bpw on the ladder convention (params=%d): %.3f" % (LADDER_PARAMS, bpw_chart))
    save("verify.json", {"bytes": n, "gib": round(n / 1024 ** 3, 3),
                         "bpw_ladder_convention": round(bpw_chart, 4),
                         "corpus_md5": md5, "inspect": r.stdout})
    return bpw_chart


def step_smoke():
    """The gate: does this build actually load Q2_0 + qwen35? Nothing else runs
    until it does, because every later step would fail the same way."""
    import urllib.request
    port = 1253
    logp = os.path.join(OUT, "smoke.log")
    os.makedirs(OUT, exist_ok=True)
    lf = open(logp, "w", encoding="utf-8", errors="replace")
    args = [SRV_EXE, "-m", MODEL, "--alias", "qat", "-ngl", "99", "-c", "8192",
            "--parallel", "1", "-fa", "on", "--jinja", "--reasoning", "off",
            "--host", "127.0.0.1", "--port", str(port)]
    log("smoke-loading: %s" % " ".join(args[1:8]))
    p = gpu_lock.serve(args, stdout=lf, stderr=subprocess.STDOUT)
    ok, t0 = False, time.time()
    while time.time() - t0 < 600:
        if p.poll() is not None:
            break
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/health" % port, timeout=2) as r:
                if json.loads(r.read().decode()).get("status") == "ok":
                    ok = True
                    break
        except Exception:
            pass
        time.sleep(2)
    vram = None
    answer = None
    if ok:
        try:
            vram = float(subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.used",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True).stdout.strip().splitlines()[0])
        except Exception:
            pass
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:%d/v1/chat/completions" % port,
                data=json.dumps({"model": "qat", "temperature": 0, "top_k": 1,
                                 "max_tokens": 64,
                                 "messages": [{"role": "user",
                                               "content": "Reply with exactly: OK"}]}).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as r:
                answer = json.loads(r.read().decode())["choices"][0]["message"]["content"]
        except Exception as e:
            answer = "ERROR: %s" % e
    if p.poll() is None:
        p.terminate()
        try:
            p.wait(timeout=30)
        except subprocess.TimeoutExpired:
            p.kill()
    lf.close()
    tail = open(logp, encoding="utf-8", errors="replace").read()[-1500:]
    log("loaded: %s   vram %s MiB   first answer: %r" % (ok, vram, answer))
    save("smoke.json", {"loaded": ok, "vram_mib": vram, "answer": answer,
                        "log_tail": tail})
    if not ok:
        print("\n--- server log tail ---\n%s" % tail)
        sys.exit("SMOKE TEST FAILED - this build cannot load the file. "
                 "Nothing further is scheduled.")
    return True


def step_ppl():
    os.makedirs(OUT, exist_ok=True)
    args = [PPL_EXE, "-m", MODEL, "-f", CORPUS, "-ngl", "99", "-c", "8192",
            "-fa", "on", "--load-mode", "mmap"]
    log("perplexity (manifest conditions): %s" % " ".join(args[3:]))
    t0 = time.time()
    # encoding= is not optional on Windows: text=True decodes as cp1252, and
    # llama-tokenize dumps 297k tokens containing bytes cp1252 cannot map. The
    # reader thread then throws, stdout comes back EMPTY, and returncode is
    # still 0 - a silent None rather than an error.
    r = subprocess.run(args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    txt = (r.stdout or "") + (r.stderr or "")
    open(os.path.join(OUT, "ppl.log"), "w", encoding="utf-8",
         errors="replace").write(txt)
    ppl = None
    import re
    m = re.findall(r"Final estimate: PPL = ([0-9.]+)", txt)
    if m:
        ppl = float(m[-1])
    log("PPL = %s   (%.1f min)" % (ppl, (time.time() - t0) / 60))
    save("ppl.json", {"ppl": ppl, "minutes": round((time.time() - t0) / 60, 1),
                      "flags": args[3:], "corpus_md5": CORPUS_MD5})
    return ppl


def step_tokens():
    args = [TOK_EXE, "-m", MODEL, "-f", CORPUS, "--show-count"]
    log("tokenizing the corpus with this model's OWN tokenizer (rule 6)")
    # encoding= is not optional on Windows: text=True decodes as cp1252, and
    # llama-tokenize dumps 297k tokens containing bytes cp1252 cannot map. The
    # reader thread then throws, stdout comes back EMPTY, and returncode is
    # still 0 - a silent None rather than an error.
    r = subprocess.run(args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    txt = (r.stdout or "") + (r.stderr or "")
    import re
    # match the LABEL, not "the last number in the output": stderr warnings are
    # concatenated after stdout, so a trailing-number regex picks up whatever
    # llama.cpp last complained about. It silently returned None the first time.
    m = re.search(r"Total number of tokens:\s*(\d+)", txt)
    n = int(m.group(1)) if m else None
    corpus_bytes = os.path.getsize(CORPUS)
    log("token count: %s   corpus %d bytes   %.4f bytes/token"
        % (n, corpus_bytes, (corpus_bytes / n) if n else 0))
    save("tokens.json", {"tokens": n, "corpus_bytes": corpus_bytes,
                         "bytes_per_token": round(corpus_bytes / n, 4) if n else None,
                         "raw_tail": txt[-400:]})
    return n


def step_accuracy():
    ps = os.path.join(HERE, "decisive-arm.ps1")
    arm = "%s|%s|qwen" % (TAG, MODEL)
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps,
           "-Arms", arm, "-DeadlineMinutes", "120"]
    log("accuracy, frozen suite, via decisive-arm.ps1")
    log("  arm: %s" % arm)
    r = subprocess.run(cmd, text=True)
    log("decisive-arm exit %s" % r.returncode)
    return r.returncode


def step_execute():
    """Generate this rung's probe-A output, THEN execute it.

    execute-probe.py scores files that already exist - it reads
    det-<name>-probeA.txt out of the ladder data directory and runs them under
    node. It does not generate. Handing it a new model without generating
    first would silently re-score the existing eight rungs and skip this one,
    which would look exactly like success.

    So this generates under the detector conditions from ladder-manifest.json,
    unchanged, because the point of the number is comparison with the other
    rungs: -ngl 99 -c 8192 -fa on --parallel 1 --jinja --reasoning off, alias
    'ladder', port 1235, greedy (temperature 0, top_k 1), max_tokens 2048.
    """
    import re
    import urllib.request
    D = os.path.join(ROOT, "results", "qwen38-27b-blind", "data", "quant-ladder")
    det = os.path.join(HERE, "detectors.ps1")
    src = open(det, encoding="utf-8", errors="replace").read()
    m = re.search(r"\$PROBE_A\s*=\s*@['\"](.*?)['\"]@", src, re.S)
    if not m:
        sys.exit("could not recover the probe-A prompt from detectors.ps1")
    prompt = m.group(1)
    log("probe-A prompt recovered: %d chars" % len(prompt))

    port = 1235
    os.makedirs(OUT, exist_ok=True)
    lf = open(os.path.join(OUT, "detector.log"), "w", encoding="utf-8",
              errors="replace")
    args = [SRV_EXE, "-m", MODEL, "--alias", "ladder", "-ngl", "99",
            "-c", "8192", "-fa", "on", "--parallel", "1", "--jinja",
            "--reasoning", "off", "--host", "127.0.0.1", "--port", str(port)]
    log("serving under the manifest's detector flags")
    p = gpu_lock.serve(args, stdout=lf, stderr=subprocess.STDOUT)
    ok, t0 = False, time.time()
    while time.time() - t0 < 600:
        if p.poll() is not None:
            break
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/health" % port,
                                        timeout=2) as r:
                if json.loads(r.read().decode()).get("status") == "ok":
                    ok = True
                    break
        except Exception:
            pass
        time.sleep(2)
    text = None
    try:
        if not ok:
            sys.exit("detector server failed to start")
        req = urllib.request.Request(
            "http://127.0.0.1:%d/v1/chat/completions" % port,
            data=json.dumps({"model": "ladder", "temperature": 0, "top_k": 1,
                             "max_tokens": 2048,
                             "messages": [{"role": "user", "content": prompt}]}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=1800) as r:
            body = json.loads(r.read().decode())
        text = body["choices"][0]["message"]["content"]
        log("probe-A generated: %d chars, finish=%s"
            % (len(text), body["choices"][0].get("finish_reason")))
    finally:
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=30)
            except subprocess.TimeoutExpired:
                p.kill()
        lf.close()

    dest = os.path.join(D, "det-QAT-Q2_0-probeA.txt")
    open(dest, "w", encoding="utf-8").write(text)
    log("-> %s" % dest)

    ep = os.path.join(ROOT, "scripts", "bench", "execute-probe.py")
    log("executing every rung under node, this one included")
    r = subprocess.run([sys.executable, "-u", ep], text=True)
    log("execute-probe exit %s" % r.returncode)
    return r.returncode


STEPS = [("verify", step_verify), ("smoke", step_smoke), ("ppl", step_ppl),
         ("tokens", step_tokens), ("accuracy", step_accuracy),
         ("execute", step_execute)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", default="all",
                    choices=["all"] + [n for n, _ in STEPS])
    a = ap.parse_args()
    log("host: %s" % host())
    log("chart columns this rung must fill: %s" % ", ".join(COLUMNS))
    for name, fn in STEPS:
        if a.step in ("all", name):
            print("\n" + "=" * 70)
            print("STEP: %s" % name.upper())
            print("=" * 70)
            fn()
    print("\nDone. Chart point goes in scripts/quant-ladder/make-ladder-chart.py")
    print("DATA as:  (2.595, \"QAT-Q2_0\", <ppl>, <accuracy>, <empty>, <executes>)")
    print("and it is the FIRST non-Unsloth, non-PTQ rung - label it as such, or")
    print("the chart will imply the x-axis explains it.")


main()
