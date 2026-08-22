"""Local dataset benchmark for GGUF models on llama.cpp: accuracy (--score),
per-request mean acceptance length (speculative decoding), or throughput over
GSM8K, MATH-500, HumanEval, MBPP, ALPACA, MeetingBank and MT-Bench, rendered as
a dark table PNG.

The runner launches llama-server itself for each model, waits for /health,
sends the prompts, and reads llama.cpp's `timings` from every response —
no external server or management app required.

--rule21 runs METHODOLOGY's standard benchmark protocol (rule 21): the
seven-dataset suite at n=25, greedy, seed 42, max_tokens 16384, with the
composite Mean over the benchmarks that actually carry a scorer.

Speculative decoding is configured server-side; pass the flags through:
    --server-args "--spec-type draft-mtp --spec-draft-n-max 10 --spec-draft-p-min 0.5"
With lossless rejection sampling every verification pass emits accepted+1
tokens, so:

    mean acceptance length = predicted_n / (predicted_n - draft_n_accepted)

Examples:
    python bench.py --model path\\to\\model.gguf --samples 10
    python bench.py --model a.gguf,b.gguf --datasets GSM8K,MATH-500 --greedy --score
    python bench.py --model a.gguf --rule21
    python bench.py --model a.gguf --rule21 --judge-url http://otherbox:1300/v1 --judge-model gpt-oss-120b
    python bench.py --model a.gguf --server-args "--spec-type draft-mtp --spec-draft-n-max 10"
"""

import argparse
import datetime
import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse

import requests

from datasets_io import (DATASET_NAMES, DEFAULT_MAX_PROMPT_TOKENS, JUDGED_SETS,
                         Judge, ScoreOptions, composite_index, est_tokens,
                         grade, is_binary_scorer, is_scored, load_items,
                         load_prompts, load_qa, resolve_name, score_response,
                         scorer_name, unscored_reason)
import render_table

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(HERE, "results")

# progress must be visible live even when stdout is piped/redirected
# (a multi-hour run with fully buffered output looks hung)
try:
    sys.stdout.reconfigure(line_buffering=True)
except AttributeError:
    pass

# Default sampling settings
SAMPLING = dict(temperature=1.0, top_p=0.95, top_k=20, presence_penalty=1.5)

# Flags whose default depends on --rule21. They parse as None so an explicit
# value on the command line always wins over the preset.
DEFAULTS = dict(samples=10, max_tokens=1024, seed=42, ctx=8192,
                datasets=",".join(DATASET_NAMES))
# METHODOLOGY rule 21 — the standard benchmark protocol
RULE21 = dict(samples=25, max_tokens=16384, seed=42, ctx=None,
              datasets="GSM8K,MATH-500,HumanEval,MBPP,ALPACA,MeetingBank,MT-Bench")

# a judge on one of these hosts at the serving port IS the model under test
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0", "",
               platform.node().lower(), socket.gethostname().lower()}

# subprocess text-mode kwargs: on Windows, bare text=True decodes child output
# as the ANSI codepage (cp1252) and a UTF-8 byte in a child's output kills the
# reader thread mid-communicate(), wedging the run forever
_TEXT = dict(text=True, encoding="utf-8", errors="replace")


def find_server(explicit=None):
    """Locate llama-server: --server-bin, $LLAMA_SERVER, PATH, repo bin/ (setup.*)."""
    repo_bin = os.path.join(os.path.dirname(os.path.dirname(HERE)),
                            "bin", "llama.cpp")
    candidates = [explicit, os.environ.get("LLAMA_SERVER"),
                  shutil.which("llama-server"),
                  os.path.join(repo_bin, "llama-server.exe"),
                  os.path.join(repo_bin, "llama-server")]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    sys.exit("llama-server not found: pass --server-bin, set LLAMA_SERVER, "
             "or put llama-server on PATH")


def machine_info(server_bin):
    """Fingerprint of this machine/backend, stored in every result file."""
    info = {
        "host": platform.node(),
        "os": platform.platform(),
        "cpu": platform.processor(),
    }
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version",
                            "--format=csv,noheader"], capture_output=True,
                           **_TEXT, timeout=15)
        if r.returncode == 0 and r.stdout.strip():
            info["gpu"] = r.stdout.strip().splitlines()[0]
    except OSError:
        pass
    try:
        r = subprocess.run([server_bin, "--version"], capture_output=True,
                           **_TEXT, timeout=15)
        out = (r.stdout or "") + (r.stderr or "")
        for line in out.splitlines():
            if line.strip().startswith("version"):
                info["llama_cpp"] = line.strip()
                break
    except OSError:
        pass
    return info


def _suite_hash(prompts_by_ds):
    h = hashlib.sha256()
    for ds in sorted(prompts_by_ds):
        for p in prompts_by_ds[ds]:
            h.update(ds.encode())
            h.update(p.encode("utf-8"))
    return h.hexdigest()[:16]


def freeze_suite(path, datasets, samples, seed, max_tokens,
                 max_prompt_tokens=DEFAULT_MAX_PROMPT_TOKENS):
    """Snapshot the exact prompts + settings into a portable suite file."""
    items_by_ds = {ds: load_items(ds, samples, max_prompt_tokens) for ds in datasets}
    prompts_by_ds = {ds: [it["prompt"] for it in items]
                     for ds, items in items_by_ds.items()}
    suite = {
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "settings": {**SAMPLING, "samples": samples, "max_tokens": max_tokens,
                     "seed": seed, "max_prompt_tokens": max_prompt_tokens},
        "prompts": prompts_by_ds,
        "answers": {ds: [it["ref"] for it in items]
                    for ds, items in items_by_ds.items()},
        "notes": {ds: [it["note"] for it in items]
                  for ds, items in items_by_ds.items()},
        "hash": _suite_hash(prompts_by_ds),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(suite, f, indent=2, ensure_ascii=False)
    print(f"froze suite -> {path} (hash {suite['hash']}, "
          f"{sum(len(v) for v in prompts_by_ds.values())} prompts). "
          f"Copy this file to other machines and run with --suite.")


def load_suite(path):
    with open(path, encoding="utf-8") as f:
        suite = json.load(f)
    actual = _suite_hash(suite["prompts"])
    if actual != suite.get("hash"):
        sys.exit(f"suite file {path} is corrupted: hash {actual} != {suite.get('hash')}")
    return suite


class Server:
    """One llama-server process hosting one model."""

    def __init__(self, server_bin, model_path, port, ctx, server_args):
        self.base_url = f"http://127.0.0.1:{port}"
        cmd = [server_bin, "-m", model_path, "-c", str(ctx), "-ngl", "99",
               "--parallel", "1", "--jinja",
               "--host", "127.0.0.1", "--port", str(port)] + server_args
        print(f"starting llama-server for {os.path.basename(model_path)} ...")
        self.log = open(os.path.join(RESULTS_DIR, "llama-server.log"), "w",
                        encoding="utf-8", errors="replace")
        self.proc = subprocess.Popen(cmd, stdout=self.log, stderr=self.log)

    def wait_ready(self, timeout_s=600):
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            if self.proc.poll() is not None:
                raise RuntimeError(
                    f"llama-server exited with code {self.proc.returncode} "
                    f"(see results/llama-server.log)")
            try:
                r = requests.get(f"{self.base_url}/health", timeout=3)
                if r.ok and r.json().get("status") == "ok":
                    return
            except requests.RequestException:
                pass
            time.sleep(2)
        raise RuntimeError("llama-server did not become healthy in time")

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.log.close()


def run_one(base_url, prompt, max_tokens, seed=None, sampling=None,
            timeout=1800):
    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "stream": False,
        **(sampling or SAMPLING),
    }
    if seed is not None:
        payload["seed"] = seed
    r = requests.post(f"{base_url}/v1/chat/completions", json=payload,
                      timeout=timeout)
    r.raise_for_status()
    body = r.json()
    t = body.get("timings", {}) or {}
    try:
        msg = body["choices"][0]["message"]
        # with --jinja llama-server splits thinking into reasoning_content;
        # the final answer (####, \boxed{}) lives in content
        content = msg.get("content") or ""
    except (KeyError, IndexError):
        content = ""
    completion = int(t.get("predicted_n") or 0)
    rec = {
        "tokens": completion,
        "tok_s": t.get("predicted_per_second", 0.0) or 0.0,
        "ttft": (t.get("prompt_ms", 0.0) or 0.0) / 1000.0,
        "text": content,
    }
    accepted = t.get("draft_n_accepted")
    total_draft = t.get("draft_n")
    if accepted is not None and completion and completion > accepted:
        rec["accept_len"] = completion / (completion - accepted)
        if total_draft:
            rec["accept_rate"] = accepted / total_draft
    return rec


def bench_model(label, base_url, prompts_by_ds, max_tokens, seed, sampling,
                answers_by_ds=None, checkpoint_cb=None, opts=None,
                notes_by_ds=None, transcripts=None, record_all=False):
    opts = opts or ScoreOptions(exec_enabled=False)
    results = {}
    speculative = False
    for ds, prompts in prompts_by_ds.items():
        answers = (answers_by_ds or {}).get(ds) or [None] * len(prompts)
        notes = (notes_by_ds or {}).get(ds) or [None] * len(prompts)
        scoring = answers_by_ds is not None
        scored_ds = scoring and is_scored(ds, opts)
        binary = is_binary_scorer(ds)
        # a scored run keeps the generations its scorers couldn't grade (rule 21:
        # ALPACA without a judge is speed + transcripts) and always keeps the
        # judged ones, so a dead judge -- or a better one later -- can re-score
        # them without re-running the model; a plain throughput run writes no
        # transcripts unless asked
        keep_text = transcripts is not None and (
            record_all or (scoring and (not scored_ds or ds in JUDGED_SETS)))
        judge_errors0 = opts.judge.errors if opts.judge else 0
        recs = []
        how = scorer_name(ds, opts) if scored_ds else (unscored_reason(ds, opts) if scoring else "not scored")
        print(f"[{label}] {ds}: {len(prompts)} prompts ({how})")
        for i, p in enumerate(prompts):
            try:
                rec = run_one(base_url, p, max_tokens, seed, sampling)
            except (requests.RequestException, RuntimeError) as e:
                print(f"    prompt {i+1}/{len(prompts)} FAILED: {e}")
                continue
            truncated = rec["tokens"] >= max_tokens
            text = rec.pop("text")
            # a truncated response never reached its final answer: score it zero
            # without the last-number fallback, which can luckily match a
            # mid-thinking number and score a spurious CORRECT
            sc = None
            if scored_ds:
                sc = (0.0 if truncated
                      else score_response(ds, text, answers[i], prompt=p, opts=opts))
            if sc is not None:
                rec["score"] = sc
                rec["truncated"] = truncated
                if binary:
                    rec["correct"] = sc >= 1.0
            if notes[i]:
                rec["note"] = notes[i]
            if keep_text:
                transcripts.setdefault(ds, []).append(
                    {"index": i, "prompt": p, "response": text,
                     "tokens": rec["tokens"],
                     **({"score": round(sc * 100, 1)} if sc is not None else {})})
            recs.append(rec)
            al = f", accept_len {rec['accept_len']:.2f}" if "accept_len" in rec else ""
            trunc = " (truncated)" if truncated else ""
            sc_txt = ("" if sc is None else
                      ", CORRECT" if binary and sc >= 1.0 else
                      f", wrong{trunc}" if binary else
                      f", score {sc*100:.1f}{trunc}")
            print(f"    prompt {i+1}/{len(prompts)}: {rec['tokens']} tok, "
                  f"{rec['tok_s']:.1f} tok/s{al}{sc_txt}")
        if not recs:
            print(f"    {ds}: all prompts failed, skipping dataset")
            continue
        agg = {
            "n": len(recs),
            "tokens": _mean(recs, "tokens"),
            "tok_s": _mean(recs, "tok_s"),
            "ttft": _mean(recs, "ttft"),
        }
        graded = [r for r in recs if "score" in r]
        if graded:
            # `accuracy` stays the 0-1 fraction for every scorer (exact match,
            # pass@1, ROUGE-L F1, normalized judge rating); `score` is the same
            # number on rule 21's 0-100 scale
            agg["accuracy"] = sum(r["score"] for r in graded) / len(graded)
            agg["score"] = round(agg["accuracy"] * 100, 1)
            agg["scorer"] = scorer_name(ds, opts)
            agg["graded_n"] = len(graded)
            agg["truncated_n"] = sum(r.get("truncated", False) for r in graded)
        elif scoring:
            # a scorer that produced nothing (every judge call failed, say) must
            # say so — never let a benchmark drop out of the Mean silently
            agg["unscored_reason"] = (
                unscored_reason(ds, opts)
                or "unscored: the scorer returned no score for any sample")
        if opts.judge and opts.judge.errors > judge_errors0:
            agg["judge_errors"] = opts.judge.errors - judge_errors0
        prompt_truncated = sum(1 for n in notes if n)
        if prompt_truncated:
            agg["prompt_truncated_n"] = prompt_truncated
        with_spec = [r for r in recs if "accept_len" in r]
        if with_spec:
            speculative = True
            agg["accept_len"] = _mean(with_spec, "accept_len")
            agg["accept_rate"] = _mean([r for r in with_spec if "accept_rate" in r],
                                       "accept_rate") if any("accept_rate" in r for r in with_spec) else 0.0
        results[ds] = agg
        if "score" in agg:
            print(f"    {ds}: {agg['score']:.1f}/100 ({agg['scorer']}, "
                  f"n={agg['graded_n']}, {agg['truncated_n']} truncated)")
        # persist after every dataset so an interrupted run loses at most
        # the dataset in flight, never the finished ones
        if checkpoint_cb:
            checkpoint_cb(dict(results), speculative)
    return results, speculative


def _mean(recs, key):
    vals = [r[key] for r in recs]
    return sum(vals) / len(vals) if vals else 0.0


def _round_up_ctx(need):
    """Smallest power-of-two context that clears `need` (min 8192)."""
    ctx = 8192
    while ctx < need:
        ctx *= 2
    return ctx


def context_report(prompts_by_ds, ctx, max_tokens, spawning):
    """Rule 21: the server's -c must exceed the longest prompt + max_tokens.
    Prints the arithmetic and warns when the configured window can't hold it."""
    longest, where = 0, None
    for ds, prompts in prompts_by_ds.items():
        for p in prompts:
            t = est_tokens(p)
            if t > longest:
                longest, where = t, ds
    need = longest + max_tokens
    print(f"context check: longest prompt ~{longest} tok ({where}) + max_tokens "
          f"{max_tokens} = ~{need} tok needed")
    if ctx < need:
        who = "-c" if spawning else "the already-running server's -c"
        print(f"  WARNING: {who} is {ctx}; the longest prompt cannot finish. "
              f"Use -c {_round_up_ctx(need)} or lower --max-prompt-tokens "
              f"(METHODOLOGY rule 21).")
    return need


def _is_self_judge(judge_url, port):
    """Does this judge URL point at the model under test?"""
    raw = judge_url if "://" in judge_url else "http://" + judge_url
    u = urllib.parse.urlsplit(raw)
    host = (u.hostname or "").lower()
    try:
        judge_port = u.port or (443 if u.scheme == "https" else 80)
    except ValueError:
        return False
    return host in LOCAL_HOSTS and judge_port == port


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", help="path to a GGUF file, or comma-separated paths")
    ap.add_argument("--server-bin", help="path to llama-server (default: "
                    "$LLAMA_SERVER, PATH, or known local installs)")
    ap.add_argument("--server-args", default="",
                    help="extra llama-server flags, e.g. "
                         "\"--spec-type draft-mtp --spec-draft-n-max 10\" "
                         "(whitespace-split; avoid paths with spaces)")
    ap.add_argument("--port", type=int, default=1236,
                    help="port for the spawned llama-server (default 1236)")
    ap.add_argument("--ctx", type=int, default=None,
                    help="context size -c for the spawned server (default 8192; "
                         "with --rule21, sized from the longest prompt + --max-tokens)")
    ap.add_argument("--datasets", default=None,
                    help="comma-separated subset of: " + ", ".join(DATASET_NAMES))
    ap.add_argument("--samples", type=int, default=None,
                    help="prompts per dataset (default 10; --rule21: 25)")
    ap.add_argument("--max-tokens", type=int, default=None,
                    help="max completion tokens (default 1024; --rule21: 16384)")
    ap.add_argument("--seed", type=int, default=None,
                    help="sampler seed sent with every request (default 42)")
    ap.add_argument("--greedy", action="store_true",
                    help="temperature 0 / top-k 1: deterministic decoding for "
                         "quality comparisons (overrides default sampling)")
    ap.add_argument("--score", action="store_true",
                    help="grade answers on the scorable datasets (exact match, "
                         "execution pass@1, ROUGE-L, judge) and report the "
                         "composite Mean; combine with --greedy for reproducibility")
    ap.add_argument("--rule21", action="store_true",
                    help="METHODOLOGY rule 21, the standard benchmark protocol: "
                         "--score --greedy --seed 42 --samples 25 --max-tokens 16384 "
                         "over GSM8K,MATH-500,HumanEval,MBPP,ALPACA,MeetingBank,MT-Bench")
    ap.add_argument("--max-prompt-tokens", type=int, default=DEFAULT_MAX_PROMPT_TOKENS,
                    help="cap on prompt length (~4 chars/token); MeetingBank "
                         "transcripts longer than this are head-truncated and the "
                         "run records a note (default %d, 0 disables)"
                         % DEFAULT_MAX_PROMPT_TOKENS)
    ap.add_argument("--no-exec", action="store_true",
                    help="don't run model-generated code: HumanEval and MBPP fall "
                         "back to unscored transcript runs")
    ap.add_argument("--judge-url", default=None,
                    help="OpenAI-compatible endpoint that scores ALPACA and "
                         "MT-Bench on a 1-10 rubric (e.g. http://otherbox:1300/v1); "
                         "without it both datasets stay unscored")
    ap.add_argument("--judge-model", default=None,
                    help="model name to ask the judge endpoint for")
    ap.add_argument("--judge-key", default=None,
                    help="bearer token for the judge endpoint (default: "
                         "$JUDGE_API_KEY, then $OPENAI_API_KEY)")
    ap.add_argument("--allow-self-judge", action="store_true",
                    help="permit a judge URL that points at the model under test "
                         "(a model judging its own outputs is not a score — the "
                         "result JSON records that it happened)")
    ap.add_argument("--transcripts", action="store_true",
                    help="save generations for every dataset, not just the "
                         "unscored ones")
    ap.add_argument("--freeze-suite", metavar="FILE",
                    help="write the exact prompts+settings to FILE and exit; "
                         "copy it to other machines for identical runs")
    ap.add_argument("--suite", metavar="FILE",
                    help="run the prompts/settings frozen in FILE instead of "
                         "sampling datasets locally")
    ap.add_argument("--no-spawn", action="store_true",
                    help="don't launch llama-server; use whatever is already "
                         "listening on --port")
    args = ap.parse_args()

    # --rule21 only fills in the flags the operator left alone
    preset = RULE21 if args.rule21 else DEFAULTS
    for key, value in preset.items():
        if getattr(args, key) is None:
            setattr(args, key, value)
    if args.rule21:
        args.score = True
        args.greedy = True
        print("METHODOLOGY rule 21: the standard benchmark protocol "
              f"(n={args.samples}, greedy, seed {args.seed}, "
              f"max_tokens {args.max_tokens})")

    datasets, bad = [], []
    for d in args.datasets.split(","):
        if not d.strip():
            continue
        canonical = resolve_name(d)
        if canonical is None:
            bad.append(d.strip())
        elif canonical not in datasets:
            datasets.append(canonical)
    if bad:
        ap.error(f"unknown dataset(s): {bad}; choose from {DATASET_NAMES}")

    if args.freeze_suite:
        freeze_suite(args.freeze_suite, datasets, args.samples, args.seed,
                     args.max_tokens, args.max_prompt_tokens)
        return

    if not args.model:
        ap.error("--model is required (or use --freeze-suite)")

    models = [m.strip() for m in args.model.split(",") if m.strip()]
    missing = [m for m in models if not os.path.exists(m)]
    if missing and not args.no_spawn:
        ap.error(f"model file(s) not found: {missing}")

    judge = None
    if args.judge_url:
        if not args.judge_model:
            ap.error("--judge-url needs --judge-model")
        self_judge = _is_self_judge(args.judge_url, args.port)
        if self_judge and not args.allow_self_judge:
            ap.error(f"--judge-url points at the model under test (port {args.port}): "
                     "a model judging its own outputs is not a score "
                     "(METHODOLOGY rule 21). Point it at an independent endpoint, "
                     "or pass --allow-self-judge to record it anyway.")
        judge = Judge(args.judge_url, args.judge_model,
                      args.judge_key or os.environ.get("JUDGE_API_KEY")
                      or os.environ.get("OPENAI_API_KEY"),
                      self_judge=self_judge)
        note = " [SELF-JUDGE: not an independent score]" if self_judge else ""
        print(f"judge: {judge.model} at {judge.url}{note}")
        if urllib.parse.urlsplit(judge.url).hostname in LOCAL_HOSTS:
            print("  note: the judge runs on this machine and competes for the GPU; "
                  "tok/s comes from llama.cpp's own counters, but wall clock inflates")
    elif args.judge_model:
        ap.error("--judge-model needs --judge-url")

    opts = ScoreOptions(exec_enabled=not args.no_exec, judge=judge,
                        max_prompt_tokens=args.max_prompt_tokens)

    server_bin = find_server(args.server_bin)
    server_args = args.server_args.split()

    answers_by_ds = notes_by_ds = None
    if args.suite:
        suite = load_suite(args.suite)
        prompts_by_ds = suite["prompts"]
        s = suite["settings"]
        args.samples, args.max_tokens = s["samples"], s["max_tokens"]
        args.seed = s.get("seed", args.seed)
        args.max_prompt_tokens = s.get("max_prompt_tokens", args.max_prompt_tokens)
        opts.max_prompt_tokens = args.max_prompt_tokens
        sampling = {k: s[k] for k in SAMPLING}
        suite_hash = suite["hash"]
        notes_by_ds = suite.get("notes")
        if args.score:
            answers_by_ds = suite.get("answers")
            if not answers_by_ds:
                sys.exit("--score with a suite needs answers in the suite file; "
                         "re-freeze it with the current bench.py")
        print(f"using suite {args.suite} (hash {suite_hash})")
    else:
        items_by_ds = {ds: load_items(ds, args.samples, args.max_prompt_tokens)
                       for ds in datasets}
        prompts_by_ds = {ds: [it["prompt"] for it in items]
                         for ds, items in items_by_ds.items()}
        notes_by_ds = {ds: [it["note"] for it in items]
                       for ds, items in items_by_ds.items()}
        if args.score:
            answers_by_ds = {ds: [it["ref"] for it in items]
                             for ds, items in items_by_ds.items()}
        sampling = dict(SAMPLING)
        suite_hash = _suite_hash(prompts_by_ds)

    if args.greedy:
        sampling.update(temperature=0.0, top_k=1, top_p=1.0, presence_penalty=0.0)

    if args.ctx is None:  # --rule21 sizes the window from the suite itself
        longest = max((est_tokens(p) for ps in prompts_by_ds.values() for p in ps),
                      default=0)
        args.ctx = _round_up_ctx(longest + args.max_tokens)
        print(f"context: -c {args.ctx} (sized for the longest prompt + --max-tokens)")
    context_report(prompts_by_ds, args.ctx, args.max_tokens, not args.no_spawn)

    if args.score:
        skipped = {ds: unscored_reason(ds, opts) for ds in prompts_by_ds
                   if not is_scored(ds, opts)}
        for ds, why in skipped.items():
            print(f"  {ds}: {why}")

    machine = machine_info(server_bin)
    print(f"machine: {machine.get('host')} | {machine.get('gpu', machine.get('cpu'))} "
          f"| {machine.get('llama_cpp', 'llama.cpp version unknown')}")

    os.makedirs(RESULTS_DIR, exist_ok=True)
    run_files = []
    for model in models:
        label = os.path.splitext(os.path.basename(model))[0]
        server = None
        base_url = f"http://127.0.0.1:{args.port}"
        try:
            if not args.no_spawn:
                server = Server(server_bin, model, args.port, args.ctx, server_args)
                server.wait_ready()
        except RuntimeError as e:
            print(f"skipping {label}: {e}")
            if server:
                server.stop()
            continue
        t0 = time.time()
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(RESULTS_DIR, f"{render_table._slug(label)}_{stamp}.json")
        transcripts = {}

        def save(results, speculative, model=model, label=label, t0=t0, path=path,
                 transcripts=transcripts):
            run = {
                "model_label": label,
                "model_key": model,
                "speculative": speculative,
                "scored": bool(args.score),
                "protocol": "METHODOLOGY rule 21" if args.rule21 else None,
                "backend": {"engine": "llama.cpp (llama-server)",
                            "server_bin": server_bin,
                            "version": machine.get("llama_cpp"),
                            "server_args": args.server_args,
                            "ctx": args.ctx},
                "machine": machine,
                "suite_hash": suite_hash,
                "datasets": [d for d in prompts_by_ds if d in results],
                "results": results,
                "scorers": {d: m["scorer"] for d, m in results.items() if "scorer" in m},
                "unscored": {d: m["unscored_reason"] for d, m in results.items()
                             if "unscored_reason" in m},
                "composite": composite_index(
                    {d: m["score"] for d, m in results.items() if "score" in m},
                    order=[d for d in prompts_by_ds if d in results],
                    excluded={d: m["unscored_reason"] for d, m in results.items()
                              if "unscored_reason" in m}),
                "judge": judge.info() if judge else None,
                "exec_scoring": bool(opts.exec_enabled),
                "settings": {**sampling, "samples": args.samples,
                             "max_tokens": args.max_tokens, "seed": args.seed,
                             "max_prompt_tokens": args.max_prompt_tokens},
                "elapsed_s": round(time.time() - t0, 1),
                "date": datetime.datetime.now().isoformat(timespec="seconds"),
            }
            if transcripts:
                tpath = path.replace(".json", "_transcripts.json")
                run["transcripts"] = os.path.basename(tpath)
                tmp = tpath + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump({"model_label": label, "suite_hash": suite_hash,
                               "generations": transcripts}, f, indent=2,
                              ensure_ascii=False)
                os.replace(tmp, tpath)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(run, f, indent=2)
            os.replace(tmp, path)

        try:
            results, speculative = bench_model(label, base_url, prompts_by_ds,
                                               args.max_tokens, args.seed,
                                               sampling, answers_by_ds,
                                               checkpoint_cb=save, opts=opts,
                                               notes_by_ds=notes_by_ds,
                                               transcripts=transcripts,
                                               record_all=args.transcripts)
        finally:
            if server:
                server.stop()
        if not results:
            print(f"no results for {label}, skipping")
            continue
        comp = composite_index(
            {d: m["score"] for d, m in results.items() if "score" in m},
            order=[d for d in prompts_by_ds if d in results])
        if comp:
            print(f"[{label}] Mean {comp['mean']:.1f}/100 - {comp['label']}")
        print(f"saved {path}")
        run_files.append(path)

    if not run_files:
        sys.exit("nothing benchmarked")

    runs = render_table.load_runs(run_files)
    for rf, run in zip(run_files, runs):
        render_table.render_runs([run], out_path=rf.replace(".json", ".png"))
    if len(runs) > 1:
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        render_table.render_runs(runs, out_path=os.path.join(RESULTS_DIR,
                                                             f"comparison_{stamp}.png"))


if __name__ == "__main__":
    main()
