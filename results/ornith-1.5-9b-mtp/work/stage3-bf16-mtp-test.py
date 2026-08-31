#!/usr/bin/env python3
"""Does MTP still change the output at BF16? Two hypotheses, one run.

Stage 3's sweep produced six different texts at temperature 0 / top_k 1, and the
non-speculative baseline degenerated into a repetition loop and ran to its cap
while every speculative arm terminated normally. The tempting reading is
"speculation changes the output", which would make the 1.238x speedup not free.

That reading is not earned until a cheaper question is answered: does the SAME
configuration, run twice, produce the same text? If it does not, the divergence
is numerical nondeterminism at near-tied logits -- which a degeneration loop is
full of -- and speculation is merely one more thing that perturbs the path.

Two configurations, two repeats each, same server flags, fresh server per repeat.
"""
import hashlib, json, os, subprocess, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "scripts", "lib"))
sys.path.insert(0, os.path.join(REPO, "scripts", "bench"))
import paths, gpu_lock                                       # noqa: E402

CAMP = paths.load_campaign(); SLUG = CAMP["slug"]
OUT = os.path.join(REPO, "results", SLUG, "data", "stage3-bf16-mtp-test.json")
WORK = os.path.join(REPO, "results", SLUG, "work")
PORT = CAMP.get("port", 1234); SERVER = paths.llama_bin("llama-server")
GGUF = paths.model_path("vendor-Ornith-1.5-9B-BF16.gguf"); DRAFT = paths.model_path("drafter")
PROMPT = ("Write a single self-contained JavaScript file implementing a red-black "
          "tree class with insert, delete, search and an in-order iterator. Code "
          "only, no explanation.")
BASE = ["--alias", "det", "-c", "32768", "-ngl", "99", "--parallel", "1", "--jinja",
        "--chat-template-kwargs", '{"enable_thinking":false}']
CONFIGS = {
    "spec-none": BASE + ["--spec-type", "none"],
    "spec-n4-p0.75": BASE + ["--spec-type", "draft-mtp", "-md", DRAFT,
                             "--spec-draft-ngl", "99",
                             "--spec-draft-n-max", "4", "--spec-draft-p-min", "0.75"],
}


def run(tag, flags, rep):
    logp = os.path.join(WORK, "stage3-bf16-%s-r%d.log" % (tag, rep))
    fh = open(logp, "w")
    p = gpu_lock.serve([SERVER, "-m", GGUF] + flags + ["--host", "127.0.0.1",
                       "--port", str(PORT)], tag="det", stdout=fh,
                       stderr=subprocess.STDOUT)
    try:
        for _ in range(600):
            time.sleep(2)
            if p.poll() is not None:
                return {"error": "exited rc=%s" % p.returncode}
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/health" % PORT, timeout=5)
                break
            except Exception:
                pass
        body = json.dumps({"messages": [{"role": "user", "content": PROMPT}],
                           "temperature": 0, "top_k": 1, "n_predict": 4096,
                           "stream": False, "cache_prompt": False}).encode()
        r = urllib.request.Request("http://127.0.0.1:%d/v1/chat/completions" % PORT,
                                   data=body, headers={"Content-Type": "application/json"})
        resp = json.load(urllib.request.urlopen(r, timeout=1800))
        txt = (resp.get("choices") or [{}])[0].get("message", {}).get("content", "")
        t = resp.get("timings") or {}
        return {"sha256": hashlib.sha256(txt.encode()).hexdigest(),
                "chars": len(txt), "predicted_n": t.get("predicted_n"),
                "t_s": t.get("predicted_per_second"),
                "finish": (resp.get("choices") or [{}])[0].get("finish_reason"),
                "tail": txt[-200:]}
    finally:
        try: p.terminate(); p.wait(timeout=45)
        except Exception:
            try: p.kill()
            except Exception: pass
        fh.close()


def main():
    gpu_lock.acquire("stage3-bf16-mtp")
    out = {"_schema": "stage3-determinism v1", "slug": SLUG,
           "question": ("does the SAME config, run twice, produce the same text at "
                        "temperature 0 / top_k 1?"), "configs": {}}
    for tag, flags in CONFIGS.items():
        reps = []
        for rep in (1, 2):
            r = run(tag, flags, rep)
            reps.append(r)
            print("%-14s rep%d  %6s chars  n=%-5s %s  sha %s" % (
                tag, rep, r.get("chars"), r.get("predicted_n"), r.get("finish"),
                (r.get("sha256") or "")[:12]), flush=True)
        same = (len(reps) == 2 and reps[0].get("sha256") == reps[1].get("sha256"))
        out["configs"][tag] = {"reps": reps, "reproducible": same}
        print("  -> %s REPRODUCIBLE: %s" % (tag, same), flush=True)
        json.dump(out, open(OUT, "w"), indent=1)
    a = out["configs"].get("spec-none", {}).get("reps", [{}])[0].get("sha256")
    b = out["configs"].get("spec-n4-p0.75", {}).get("reps", [{}])[0].get("sha256")
    out["spec_changes_output"] = (a != b) if (a and b) else None
    json.dump(out, open(OUT, "w"), indent=1)
    print("spec-none vs spec-n4 identical text:", a == b)


if __name__ == "__main__":
    main()
