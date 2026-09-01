#!/usr/bin/env python3
"""Sequenced campaign runner — the tasks that do NOT need the RECIPE LOCK.

Rule 25 is a sequencing law: cheap probes buy the map, the map locks the
recipes, and only locked recipes earn expensive hours. Everything scheduled here
is either free, cheap, or independent of the lock. The expensive quality block
(GPQA, the rule-21 suite, vision) is deliberately NOT here: it runs after a dated
RECIPE LOCK exists, and that lock has a judgement in it this runner must not make
— whether this campaign ranks quants by perplexity or by KL-divergence, given
that the two came out in opposite orders.

Detached, resumable, checkpoint-committed, per the standing rules: every task
records into data/, appends to campaign.md, commits, and is skipped on a re-run
if its output already exists. A crash costs the task in flight and nothing else.
Rule 20 holds throughout: one GPU job at a time, every server through
gpu_lock.serve().

    nohup .venv/bin/python results/<slug>/work/runner.py > work/runner.log 2>&1 &
"""
import hashlib, json, os, re, subprocess, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "scripts", "lib"))
sys.path.insert(0, os.path.join(REPO, "scripts", "bench"))
import paths, gpu_lock                                          # noqa: E402
import importlib.util as _il
_spec = _il.spec_from_file_location("loopdet",
        os.path.join(REPO, "scripts", "bench", "loop-detect.py"))
loopdet = _il.module_from_spec(_spec); _spec.loader.exec_module(loopdet)

CAMP = paths.load_campaign(); SLUG = CAMP["slug"]
DATA = os.path.join(REPO, "results", SLUG, "data")
WORK = os.path.join(REPO, "results", SLUG, "work")
LOG = os.path.join(REPO, "results", SLUG, "campaign.md")
STATE = os.path.join(DATA, "runner-state.json")
PORT = CAMP.get("port", 1234)
SERVER = paths.llama_bin("llama-server")
DRAFT = paths.model_path("drafter")
NGL, CTX = 99, 32768

PROSE = ("Explain, for a technically literate reader, how a marine aquarium's "
         "nitrogen cycle works: what each bacterial population consumes and "
         "produces, why a new tank is dangerous for weeks, and what a keeper "
         "measures to know it has finished.")
CODE = ("Write a single self-contained JavaScript file implementing a red-black "
        "tree class with insert, delete, search and an in-order iterator. Code "
        "only, no explanation.")
VERBATIM = ("Reproduce the following text exactly, character for character, with "
            "no commentary:\n\n" + PROSE)


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def state():
    if os.path.exists(STATE):
        try:
            return json.load(open(STATE))
        except Exception:
            pass
    return {"done": [], "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                     time.gmtime())}


def save_state(s):
    json.dump(s, open(STATE, "w"), indent=1)


def heartbeat(task, note):
    json.dump({"_schema": "heartbeat v1", "slug": SLUG, "in_flight": task,
               "note": note, "pid": os.getpid(),
               "written_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "recovery": "read campaign.md end to end, then git log --oneline"},
              open(os.path.join(WORK, "heartbeat.json"), "w"), indent=1)


def append(md):
    with open(LOG, "a") as f:
        f.write(md)


def commit(msg):
    """Checkpoint, then PUBLISH it. A commit that exists only on this disk is
    not protection against losing the machine -- and this box may be borrowed.
    The push is best-effort and never fails a task: work/autopush.sh is the
    safety net that retries, so a transient network error here costs nothing."""
    subprocess.run(["git", "add", "-A", "results/%s" % SLUG], cwd=REPO)
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=REPO)
    try:
        subprocess.run(["git", "push", "origin", "main"], cwd=REPO,
                       capture_output=True, timeout=300)
    except Exception:
        pass


# --------------------------------------------------------------- server helper
def serve(model, extra, tag):
    args = [SERVER, "-m", model, "--alias", tag, "-c", str(CTX), "-ngl", str(NGL),
            "--parallel", "1", "--jinja", "--host", "127.0.0.1",
            "--port", str(PORT)] + extra
    fh = open(os.path.join(WORK, "runner-%s.log" % tag), "w")
    p = gpu_lock.serve(args, tag=tag, stdout=fh, stderr=subprocess.STDOUT)
    for _ in range(600):
        time.sleep(2)
        if p.poll() is not None:
            fh.close()
            return None, fh
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/health" % PORT, timeout=5)
            return p, fh
        except Exception:
            pass
    return None, fh


def stop(p, fh):
    try:
        p.terminate(); p.wait(timeout=45)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass
    try:
        fh.close()
    except Exception:
        pass


def ask(prompt, n_predict, kwargs=None):
    body = {"messages": [{"role": "user", "content": prompt}], "temperature": 0,
            "top_k": 1, "n_predict": n_predict, "stream": False,
            "cache_prompt": False}
    if kwargs:
        body["chat_template_kwargs"] = kwargs
    r = urllib.request.Request("http://127.0.0.1:%d/v1/chat/completions" % PORT,
                               data=json.dumps(body).encode(),
                               headers={"Content-Type": "application/json"})
    resp = json.load(urllib.request.urlopen(r, timeout=3600))
    ch = (resp.get("choices") or [{}])[0]
    msg = ch.get("message", {}) or {}
    # REASONING IS PART OF THE GENERATION. With --jinja, llama.cpp splits a
    # thinking model's output: the chain-of-thought goes to `reasoning_content`
    # and only the visible reply to `content`. Reading `content` alone returned
    # the EMPTY STRING for a probe that had generated 700 tokens, and the loop
    # detector then scored that empty string "clean" -- so task A1 published
    # `chars: 0, verdict: clean` for all three Stage-1 floor arms while the same
    # file scored LOOP on all six spec-sweep transcripts at the very sampler
    # those floors used. All three work/a1-floor-*.txt were written 0 bytes.
    #
    # Rule 20's loop check protects "its tokens or timings", and the timings
    # count EVERY generated token, reasoning included. So a loop that happens
    # inside the thinking block is exactly the loop that corrupts a throughput
    # number, and `full` is what the detector must be given.
    content = msg.get("content") or ""
    reasoning = msg.get("reasoning_content") or ""
    return {"text": content, "reasoning": reasoning,
            "full": (reasoning + "\n\n" + content) if reasoning else content,
            "finish": ch.get("finish_reason"),
            "timings": resp.get("timings") or {}}


SPEC_ON = ["--spec-type", "draft-mtp", "-md", DRAFT, "--spec-draft-ngl", "99",
           "--spec-draft-n-max", "4", "--spec-draft-p-min", "0.75"]
SPEC_OFF = ["--spec-type", "none"]


# ===================================================================== TASK A1
def task_a1():
    """Loop-detect over every transcript this campaign has kept, plus fresh
    full-text floor probes -- Stage 1 saved only 400 chars per floor, so the
    floors could not be loop-checked from what was written down (rule 28, the
    hard way)."""
    out = {"_schema": "loop-scan v1", "slug": SLUG,
           "detector": "scripts/bench/loop-detect.py signals()/verdict(), D5",
           "why": ("the Stage-1 floors and the whole spec sweep used temp 0 / "
                   "top_k 1, the sampler that degenerated on the code prompt. A "
                   "number taken from a looping generation is not a speed "
                   "measurement of anything a reader will do."),
           "existing_transcripts": {}, "fresh_floor_probes": {}}
    d = os.path.join(DATA, "arms", "spec-sweep-ornith-responses")
    if os.path.isdir(d):
        for fn in sorted(os.listdir(d)):
            txt = open(os.path.join(d, fn), errors="replace").read()
            s = loopdet.signals(txt)
            out["existing_transcripts"][fn] = {
                "chars": len(txt), "verdict": loopdet.verdict(s),
                "signals": {k: round(v, 4) for k, v in s.items()}}
    # fresh floors, full text kept this time
    for label in ("Q8_0", "Q4_K_M", "IQ2_M"):
        gguf = paths.model_path(label)
        p, fh = serve(gguf, SPEC_OFF, "a1-%s" % label)
        if not p:
            out["fresh_floor_probes"][label] = {"error": "server never healthy"}
            continue
        try:
            r = ask(CODE, 700)
            s = loopdet.signals(r["full"])
            out["fresh_floor_probes"][label] = {
                "t_s": r["timings"].get("predicted_per_second"),
                "predicted_n": r["timings"].get("predicted_n"),
                "finish": r["finish"], "chars": len(r["full"]),
                "reasoning_chars": len(r["reasoning"]),
                "content_chars": len(r["text"]),
                "verdict": loopdet.verdict(s),
                "signals": {k: round(v, 4) for k, v in s.items()}}
            open(os.path.join(WORK, "a1-floor-%s.txt" % label), "w").write(r["full"])
            log("  %s floor %.2f t/s  %s  %s" % (
                label, r["timings"].get("predicted_per_second") or 0,
                r["finish"], loopdet.verdict(s)))
        finally:
            stop(p, fh)
    json.dump(out, open(os.path.join(DATA, "loop-scan.json"), "w"), indent=1)
    bad = [k for k, v in out["fresh_floor_probes"].items()
           if v.get("verdict") == "LOOP"]
    rows = "\n".join("| %s | %s | %s | %s |" % (
        k, v.get("predicted_n"), v.get("finish"), v.get("verdict"))
        for k, v in out["fresh_floor_probes"].items())
    append("""
### A1 — loop scan over every transcript kept (2026-09-01)

Stage 1 saved only 400 characters per floor probe, so the floors could not be
loop-checked from what was written down — rule 28 the hard way, and the reason
this task re-takes them with the full text kept. Detector:
`scripts/bench/loop-detect.py`'s D5 signals, the repo's own.

| floor | predicted_n | finish | verdict |
|---|---|---|---|
%s

Spec-sweep transcripts: %s

**Floors showing a loop: %s**
""" % (rows,
       ", ".join("%s=%s" % (k, v["verdict"])
                 for k, v in out["existing_transcripts"].items()) or "none kept",
       ", ".join(bad) if bad else "none"))
    commit("A1: loop-scan the floors and the spec transcripts")


# ===================================================================== TASK A2
def task_a2():
    """A speculation baseline on a prompt that does NOT degenerate. The Stage-3
    vs-none column is provisional because spec-none looped on the code prompt;
    prose is the control."""
    out = {"_schema": "spec-rebaseline v1", "slug": SLUG,
           "why": ("Stage 3's baseline degenerated on the code prompt and ran to "
                   "its cap, so 'vs none' compared a loop against a clean "
                   "generation. This re-takes both arms on prose and on code, so "
                   "the speedup is quoted where the baseline is honest."),
           "arms": {}}
    gguf = paths.model_path("Q4_K_M")
    for pname, prompt in (("prose", PROSE), ("code", CODE)):
        for aname, extra in (("spec-none", SPEC_OFF), ("spec-n4-p0.75", SPEC_ON)):
            p, fh = serve(gguf, extra, "a2-%s-%s" % (pname, aname))
            if not p:
                continue
            try:
                r = ask(prompt, 3000)
                s = loopdet.signals(r["text"])
                out["arms"]["%s/%s" % (pname, aname)] = {
                    "t_s": r["timings"].get("predicted_per_second"),
                    "predicted_n": r["timings"].get("predicted_n"),
                    "finish": r["finish"],
                    "sha256": hashlib.sha256(r["text"].encode()).hexdigest()[:16],
                    "verdict": loopdet.verdict(s),
                    "draft_n": r["timings"].get("draft_n"),
                    "draft_n_accepted": r["timings"].get("draft_n_accepted")}
                log("  %s/%s %.2f t/s %s %s" % (
                    pname, aname, r["timings"].get("predicted_per_second") or 0,
                    r["finish"], loopdet.verdict(s)))
            finally:
                stop(p, fh)
    json.dump(out, open(os.path.join(DATA, "spec-rebaseline.json"), "w"), indent=1)
    rows = "\n".join("| %s | %.2f | %s | %s | %s | `%s` |" % (
        k, v.get("t_s") or 0, v.get("predicted_n"), v.get("finish"),
        v.get("verdict"), v.get("sha256")) for k, v in out["arms"].items())
    append("""
### A2 — the speculation speedup on a baseline that does not loop

| arm | t/s | predicted_n | finish | loop verdict | sha |
|---|---|---|---|---|---|
%s
""" % rows)
    commit("A2: re-baseline speculation on a non-degenerate prompt")


# ===================================================================== TASK A3
def task_a3():
    """Rule 11: content decides acceptance, flags only move you along one curve.
    Novel code against near-verbatim reproduction, same server, same flags."""
    out = {"_schema": "acceptance-demo v1", "slug": SLUG, "arms": {}}
    gguf = paths.model_path("Q4_K_M")
    p, fh = serve(gguf, SPEC_ON, "a3-accept")
    if p:
        try:
            for name, prompt in (("novel-code", CODE), ("verbatim-prose", VERBATIM)):
                r = ask(prompt, 1500)
                t = r["timings"]
                dn, da = t.get("draft_n"), t.get("draft_n_accepted")
                out["arms"][name] = {
                    "t_s": t.get("predicted_per_second"),
                    "predicted_n": t.get("predicted_n"), "draft_n": dn,
                    "draft_n_accepted": da,
                    "acceptance": round(da / dn, 4) if dn else None,
                    "finish": r["finish"]}
                log("  %s %.2f t/s accept=%s" % (
                    name, t.get("predicted_per_second") or 0,
                    out["arms"][name]["acceptance"]))
        finally:
            stop(p, fh)
    json.dump(out, open(os.path.join(DATA, "acceptance-demo.json"), "w"), indent=1)
    rows = "\n".join("| %s | %.2f | %s | %s |" % (
        k, v.get("t_s") or 0, v.get("acceptance"), v.get("predicted_n"))
        for k, v in out["arms"].items())
    append("""
### A3 — acceptance is a property of the CONTENT (rule 11)

Same server, same flags (draft-mtp n4/p0.75), two regimes:

| regime | t/s | acceptance | predicted_n |
|---|---|---|---|
%s
""" % rows)
    commit("A3: acceptance demo across two content regimes")


# ===================================================================== TASK B1
def task_b1():
    """Stage 4 APPETITE. The gate on every expensive run: rule 7 says cap above
    the appetite distribution's UPPER TAIL, and rule 16 says a level whose
    appetite exceeds the window truncates rather than degrading. bench.py scores
    a truncated answer 0.0, so a tight cap deflates a benchmark and reports it as
    model quality. This is the probe the reference campaign skipped and lost a
    21-minute, 120 Wh arm to."""
    qs = [
        "A rope over a pulley has a 3 kg mass on one side and a 5 kg mass on the other. Find the acceleration and the tension, showing your reasoning.",
        "Prove that the square root of 2 is irrational, then explain where the proof would fail for the square root of 4.",
        "A 40%% solution is mixed with a 15%% solution to make 10 litres of a 25%% solution. How much of each? Show the algebra.",
        "Explain why the halting problem is undecidable, in terms a strong undergraduate would follow.",
        "Design a schema for a library lending system and justify each table and key choice.",
        "What is the expected number of coin flips to get two heads in a row? Derive it.",
    ]
    out = {"_schema": "appetite v1", "slug": SLUG, "cap": 16384,
           "knob": "enable_thinking (BOOLEAN on this model -- two arms, not four)",
           "arms": {}}
    gguf = paths.model_path("Q4_K_M")
    for think in (True, False):
        arm = "thinking-%s" % ("on" if think else "off")
        p, fh = serve(gguf, SPEC_OFF, "b1-%s" % arm)
        if not p:
            continue
        recs = []
        try:
            for i, q in enumerate(qs):
                r = ask(q, 16384, {"enable_thinking": think})
                t = r["timings"]
                txt = r["text"]
                think_chars = 0
                m = re.search(r"<think>(.*?)</think>", txt, re.S)
                if m:
                    think_chars = len(m.group(1))
                recs.append({"q": i, "predicted_n": t.get("predicted_n"),
                             "finish": r["finish"], "chars": len(txt),
                             "think_chars": think_chars,
                             "t_s": t.get("predicted_per_second")})
                log("  %s q%d n=%s %s think_chars=%d" % (
                    arm, i, t.get("predicted_n"), r["finish"], think_chars))
        finally:
            stop(p, fh)
        ns = sorted(x["predicted_n"] for x in recs if x.get("predicted_n"))
        out["arms"][arm] = {
            "probes": recs, "n": len(ns),
            "min": ns[0] if ns else None, "max": ns[-1] if ns else None,
            "median": ns[len(ns) // 2] if ns else None,
            "truncated": sum(1 for x in recs if x.get("finish") == "length"),
            "recommended_cap": (int(ns[-1] * 1.5) if ns else None),
            "cap_rule": ("rule 7: cap above the UPPER TAIL, not the median. "
                         "1.5x the observed max is the floor of a safe cap, and "
                         "any truncation at all means this number is a lower "
                         "bound on the appetite, not the appetite.")}
    json.dump(out, open(os.path.join(DATA, "stage4-appetite.json"), "w"), indent=1)
    rows = "\n".join("| %s | %s | %s | %s | %s | %s |" % (
        k, v.get("n"), v.get("min"), v.get("median"), v.get("max"),
        v.get("truncated")) for k, v in out["arms"].items())
    caps = {k: v.get("recommended_cap") for k, v in out["arms"].items()}
    append("""
## Stage 4 — APPETITE  ·  2026-09-01

The effort knob on this model is `enable_thinking`, BOOLEAN, so the sweep is two
arms and not four levels. Six reasoning prompts per arm, cap 16,384, temp 0.

| arm | probes | min | median | max | truncated |
|---|---|---|---|---|---|
%s

**Derived caps (rule 7 — above the upper tail, never the median): %s**

This is the gate on Stage 6. A benchmark run at a cap below the upper tail does
not degrade gracefully: it truncates, and a truncated answer scores 0.0, which
the report would publish as model quality.
""" % (rows, json.dumps(caps)))
    commit("Stage 4: thinking appetite, and the cap every expensive run needs")


# ===================================================================== TASK E1
def task_e1():
    """The KLD ladder at rule 6's own position count. The 4-chunk run already
    inverted the perplexity ranking; this puts the evidence at 294,912 positions
    so it stands beside rule 6 on rule 6's terms."""
    base = os.path.join(REPO, "models", "kld-base-bf16-36.dat")
    ppl = paths.llama_bin("llama-perplexity")
    corpus = os.path.join(REPO, CAMP["corpus"])
    out = {"_schema": "kld-full v1", "slug": SLUG, "ctx": 8192, "chunks": 36,
           "token_positions": 294912, "arms": {}}
    if not os.path.exists(base):
        log("  dumping BF16 base logits at 36 chunks (large)")
        with open(os.path.join(WORK, "kld36-base.log"), "w") as fh:
            gpu_lock.serve([ppl, "-m", paths.model_path("vendor-Ornith-1.5-9B-BF16.gguf"),
                            "-f", corpus, "-c", "8192", "--chunks", "36",
                            "-ngl", "99", "--kl-divergence-base", base],
                           tag="kld36-base", stdout=fh,
                           stderr=subprocess.STDOUT).wait()
    for label in ("Q8_0", "Q4_K_M", "IQ2_M"):
        lp = os.path.join(WORK, "kld36-%s.log" % label)
        with open(lp, "w") as fh:
            gpu_lock.serve([ppl, "-m", paths.model_path(label), "-f", corpus,
                            "-c", "8192", "--chunks", "36", "-ngl", "99",
                            "--kl-divergence", "--kl-divergence-base", base],
                           tag="kld36-%s" % label, stdout=fh,
                           stderr=subprocess.STDOUT).wait()
        txt = open(lp, errors="replace").read()
        rec = {}
        for k, pat in (("mean_kld", r"Mean\s+KLD:\s*([0-9.eE+-]+)"),
                       ("median_kld", r"Median\s+KLD:\s*([0-9.eE+-]+)"),
                       ("same_top_pct", r"Same\s+top\s+p:\s*([0-9.]+)")):
            m = re.search(pat, txt)
            if m:
                rec[k] = float(m.group(1))
        out["arms"][label] = rec
        log("  %s %s" % (label, rec))
        json.dump(out, open(os.path.join(DATA, "kld-full-294912.json"), "w"),
                  indent=1)
    try:
        os.remove(base)
    except OSError:
        pass
    rows = "\n".join("| %s | %s | %s | %s%% |" % (
        k, v.get("mean_kld"), v.get("median_kld"), v.get("same_top_pct"))
        for k, v in out["arms"].items())
    append("""
### E1 — the KLD ladder at rule 6's own position count (294,912)

| arm | mean KLD vs BF16 | median KLD | same top-1 |
|---|---|---|---|
%s
""" % rows)
    commit("E1: KLD ladder at 294,912 positions, rule 6's own count")


TASKS = [("A1", task_a1), ("A2", task_a2), ("A3", task_a3),
         ("B1", task_b1), ("E1", task_e1)]


def main():
    s = state()
    gpu_lock.acquire("campaign-runner")
    for name, fn in TASKS:
        if name in s["done"]:
            log("%s already done -- skipping" % name)
            continue
        log("=== %s ===" % name)
        heartbeat(name, "running")
        try:
            fn()
            s["done"].append(name)
        except Exception as exc:                                  # noqa: BLE001
            log("%s FAILED: %s: %s" % (name, type(exc).__name__, exc))
            s.setdefault("failed", []).append(
                {"task": name, "error": "%s: %s" % (type(exc).__name__, exc)})
        save_state(s)
    heartbeat(None, "runner finished")
    log("runner finished: done=%s failed=%s" % (s["done"], s.get("failed")))


if __name__ == "__main__":
    main()
