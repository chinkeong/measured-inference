#!/usr/bin/env python3
"""Stage 6a — GPQA Diamond, all 198, against the vendor's published 86.4.

THE MEASUREMENT IS OF THE HARNESS, NOT THE MODEL. methodology/NEXT-MODELS.md has
recorded since this repo began that GPQA Diamond is "the cheapest harness
validation available, and it is universal", and that the gap -- never once having
checked this harness against a published number -- has been open the whole time.
scripts/bench/run-gpqa-anchor.ps1 says it plainly and it is worth repeating
before any number lands: "It detects a BROKEN harness. It does not validate one."

CONDITIONS, ALL FROM THE DATED RECIPE LOCK, none guessed:
  model      R1, Q8_0 -- the fidelity pick (KLD 0.016 from BF16, argmax 97.6%)
  thinking   ON. The published 86.4 is the vendor's headline figure and this
             model reasons by default; the template's open <think> is the
             default branch.
  cap        5,407. Rule 7 wants the cap above the appetite distribution's UPPER
             TAIL: Stage 4 measured max 3,605 across six reasoning prompts with
             ZERO truncations at 16,384, so 3,605 is a true maximum and not a
             lower bound, and 1.5x it is the locked cap. A tight cap does not
             degrade -- it truncates, and bench.py scores a truncated answer 0.0,
             which a report would publish as model quality (rule 16).
  sampler    greedy (temp 0, top_k 1). NOT the vendor's sampling profile, which
             is unpublished -- ornith-ai/Ornith-1.5-9B ships no
             generation_config.json (404, checked 2026-09-01). Greedy is this
             campaign's own condition and is stated as one; it is a difference
             from whatever produced 86.4 and the comparison must say so.

WHAT THIS RUN CANNOT CLAIM, recorded before it starts so it is not claimed after:
  - the published 86.4 is vendor self-reported, with no independent third-party
    score for this model on this benchmark;
  - the option order is the frozen mirror's, not the order that produced 86.4;
  - the sampler differs (above);
  - the rig serves 32,768 tokens of a 262,144-token model.
A large gap here means the harness, the conditions, or the claim is wrong. A
small one means none of those is obviously wrong. Neither is a validation.

Resumable: answers are written after every question, and a re-run skips what is
already recorded. 198 questions with a 5,407 cap is hours; a crash must not cost
them.
"""
import json, os, re, subprocess, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "scripts", "lib"))
sys.path.insert(0, os.path.join(REPO, "scripts", "bench"))
import paths, gpu_lock                                          # noqa: E402

CAMP = paths.load_campaign(); SLUG = CAMP["slug"]
DATA = os.path.join(REPO, "results", SLUG, "data")
WORK = os.path.join(REPO, "results", SLUG, "work")
OUT = os.path.join(DATA, "stage6a-gpqa-anchor.json")
PORT = CAMP.get("port", 1234)
SERVER = paths.llama_bin("llama-server")
FROZEN = os.path.join(REPO, "scripts", "bench", "datasets-frozen", "gpqa_diamond.jsonl")
CAP, CTX, NGL = 5407, 32768, 99
PUBLISHED = 86.4


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def load_rows():
    rows = []
    with open(FROZEN, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


LETTER = re.compile(r"\b([ABCD])\b")


def extract(ans):
    """The chosen letter. Last explicit marker wins, else the last bare letter."""
    for pat in (r"(?:answer|Answer)\s*(?:is)?\s*[:\-]?\s*\(?([ABCD])\)?",
                r"\\boxed\{\s*\(?([ABCD])\)?\s*\}",
                r"\*\*\s*\(?([ABCD])\)?\s*\*\*"):
        m = list(re.finditer(pat, ans))
        if m:
            return m[-1].group(1)
    m = list(LETTER.finditer(ans[-400:]))
    return m[-1].group(1) if m else None


def main():
    rows = load_rows()
    out = {"_schema": "gpqa-anchor v1", "slug": SLUG, "n_total": len(rows),
           "published": PUBLISHED, "published_source": "ornith-ai/Ornith-1.5-9B model card, read 2026-08-31",
           "recipe": "R1 (Q8_0), thinking ON, cap %d, greedy" % CAP,
           "cannot_claim": ["vendor self-reported, no independent third-party score",
                            "option order is the frozen mirror's, not the published run's",
                            "sampler is greedy; the vendor's profile is unpublished (no generation_config.json)",
                            "rig serves 32,768 of a 262,144-token window"],
           "answers": {}}
    if os.path.exists(OUT):
        try:
            out = json.load(open(OUT))
        except Exception:
            pass
    gpu_lock.acquire("stage6a-gpqa")
    logp = os.path.join(WORK, "stage6a-gpqa-server.log")
    fh = open(logp, "w")
    p = gpu_lock.serve([SERVER, "-m", paths.model_path("Q8_0"), "--alias", "gpqa",
                        "-c", str(CTX), "-ngl", str(NGL), "--parallel", "1",
                        "--jinja", "--mmproj", paths.model_path("mmproj"),
                        "--host", "127.0.0.1", "--port", str(PORT)],
                       tag="gpqa", stdout=fh, stderr=subprocess.STDOUT)
    try:
        for _ in range(900):
            time.sleep(2)
            if p.poll() is not None:
                log("server exited rc=%s" % p.returncode); return
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/health" % PORT, timeout=5)
                break
            except Exception:
                pass
        t0 = time.time()
        for i, row in enumerate(rows):
            key = str(i)
            if key in out["answers"]:
                continue
            q = row.get("question") or row.get("Question") or ""
            choices = row.get("choices") or row.get("options") or []
            gold = row.get("answer") or row.get("correct") or row.get("label")
            opts = "\n".join("%s) %s" % (c, t) for c, t in
                             zip("ABCD", choices)) if choices else ""
            prompt = ("%s\n\n%s\n\nAnswer with the single letter A, B, C or D."
                      % (q, opts))
            body = json.dumps({"messages": [{"role": "user", "content": prompt}],
                               "temperature": 0, "top_k": 1, "n_predict": CAP,
                               "stream": False, "cache_prompt": False,
                               "chat_template_kwargs": {"enable_thinking": True}}).encode()
            req = urllib.request.Request(
                "http://127.0.0.1:%d/v1/chat/completions" % PORT, data=body,
                headers={"Content-Type": "application/json"})
            try:
                resp = json.load(urllib.request.urlopen(req, timeout=3600))
            except Exception as exc:
                out["answers"][key] = {"error": str(exc)[:200]}
                json.dump(out, open(OUT, "w"), indent=1)
                continue
            ch = (resp.get("choices") or [{}])[0]
            msg = ch.get("message", {})
            tim = resp.get("timings") or {}
            content = msg.get("content") or ""
            pick = extract(content)
            out["answers"][key] = {
                "gold": gold, "pick": pick,
                "correct": (pick is not None and gold is not None
                            and str(pick).strip().upper() == str(gold).strip().upper()),
                "finish": ch.get("finish_reason"),
                "truncated": ch.get("finish_reason") == "length",
                "predicted_n": tim.get("predicted_n"),
                "reasoning_chars": len(msg.get("reasoning_content") or ""),
                "content_chars": len(content)}
            json.dump(out, open(OUT, "w"), indent=1)     # rule 28, every question
            if (i + 1) % 10 == 0:
                done = [a for a in out["answers"].values() if "correct" in a]
                acc = 100.0 * sum(1 for a in done if a["correct"]) / max(1, len(done))
                tr = sum(1 for a in done if a.get("truncated"))
                log("%d/%d  running acc %.1f%%  truncated %d  %.0f min elapsed"
                    % (i + 1, len(rows), acc, tr, (time.time() - t0) / 60))
    finally:
        try:
            p.terminate(); p.wait(timeout=60)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
        fh.close()
    done = [a for a in out["answers"].values() if "correct" in a]
    out["n_scored"] = len(done)
    out["n_truncated"] = sum(1 for a in done if a.get("truncated"))
    out["accuracy_pct"] = round(100.0 * sum(1 for a in done if a["correct"])
                                / max(1, len(done)), 2)
    out["delta_vs_published"] = round(out["accuracy_pct"] - PUBLISHED, 2)
    json.dump(out, open(OUT, "w"), indent=1)
    log("GPQA %.2f%% (n=%d, %d truncated) vs published %.1f  ->  %+.2f"
        % (out["accuracy_pct"], out["n_scored"], out["n_truncated"], PUBLISHED,
           out["delta_vs_published"]))


if __name__ == "__main__":
    main()
