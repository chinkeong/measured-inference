#!/usr/bin/env python3
"""Measure KV bytes/token empirically, by the SLOPE of VRAM against -c.

stage-1.md wants the header's KV arithmetic cross-checked against "the server's
reported KV size at a known -c" (rule 4). b10717 prints no such line, so this
is the third reading: load the same file at several context sizes, read settled
VRAM, and take the slope. Everything that does NOT scale with context -- weights,
compute buffers, the 24 recurrent layers' fixed state -- cancels in the
difference, which is exactly what makes a slope trustworthy where an absolute
reading is not.

Why it matters: results/<slug>/plan.json, check-request.py's fit table and every
rule-13 ceiling in this campaign are priced at the HEADER's 32,768 B/token. At
c=32,768 that predicts 1,024 MiB of cache, but Stage 2 measured Q8_0's ENTIRE
overhead above its weights at 215 MiB. One of the two is wrong.

A second pass issues a real request at each rung, because a cache that is
allocated lazily would hide from a load-only reading.
"""
import json, os, statistics, subprocess, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "scripts", "lib"))
sys.path.insert(0, os.path.join(REPO, "scripts", "bench"))
import paths, gpu_lock                                    # noqa: E402

CAMP = paths.load_campaign(); SLUG = CAMP["slug"]
OUT = os.path.join(REPO, "results", SLUG, "data", "stage2-kv-slope.json")
WORK = os.path.join(REPO, "results", SLUG, "work")
PORT = CAMP.get("port", 1234); SERVER = paths.llama_bin("llama-server")
GGUF = paths.model_path(CAMP["models"]["Q4_K_M"])
RUNGS = [8192, 32768, 65536, 131072]
HEADER_KV_BPT = 32768


def vram(n=9):
    v = []
    for _ in range(n):
        o = subprocess.run(["nvidia-smi", "--query-gpu=memory.used",
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=30).stdout
        v.append(float(o.strip().split("\n")[0])); time.sleep(0.4)
    return statistics.median(v)


def one(c):
    logp = os.path.join(WORK, "stage2-kv-c%d.log" % c)
    args = [SERVER, "-m", GGUF, "--alias", "kv%d" % c, "-c", str(c), "-ngl", "99",
            "--parallel", "1", "--jinja", "--host", "127.0.0.1", "--port", str(PORT)]
    fh = open(logp, "w")
    p = gpu_lock.serve(args, tag="kv-%d" % c, stdout=fh, stderr=subprocess.STDOUT)
    rec = {"ctx": c}
    try:
        for _ in range(600):
            time.sleep(2)
            if p.poll() is not None:
                rec["error"] = "exited rc=%s" % p.returncode; return rec
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/health" % PORT, timeout=5)
                break
            except Exception:
                pass
        time.sleep(15)
        rec["at_load_mib"] = vram()
        body = json.dumps({"messages": [{"role": "user", "content":
                "Count from one to forty in words, one per line."}],
                "temperature": 0, "n_predict": 200, "stream": False}).encode()
        r = urllib.request.Request("http://127.0.0.1:%d/v1/chat/completions" % PORT,
                                   data=body, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(r, timeout=600).read()
        time.sleep(8)
        rec["after_request_mib"] = vram()
    finally:
        try: p.terminate(); p.wait(timeout=45)
        except Exception:
            try: p.kill()
            except Exception: pass
        fh.close()
    return rec


def main():
    gpu_lock.acquire("stage2-kv-slope")
    out = {"_schema": "stage2-kv-slope v1", "slug": SLUG,
           "model": os.path.basename(GGUF), "rungs": RUNGS,
           "header_kv_bytes_per_token": HEADER_KV_BPT,
           "method": ("slope of settled VRAM against -c; everything that does not "
                      "scale with context cancels in the difference"),
           "points": []}
    for c in RUNGS:
        rec = one(c)
        out["points"].append(rec)
        print("c=%-7d load %.0f MiB   after-request %.0f MiB"
              % (c, rec.get("at_load_mib") or -1, rec.get("after_request_mib") or -1), flush=True)
        json.dump(out, open(OUT, "w"), indent=1)
    pts = [p for p in out["points"] if p.get("at_load_mib")]
    if len(pts) >= 2:
        lo, hi = pts[0], pts[-1]
        for key in ("at_load_mib", "after_request_mib"):
            if lo.get(key) and hi.get(key):
                bpt = (hi[key] - lo[key]) * 1048576.0 / (hi["ctx"] - lo["ctx"])
                out.setdefault("measured_kv_bytes_per_token", {})[key] = {
                    "value": round(bpt, 1),
                    "from": "c=%d -> c=%d" % (lo["ctx"], hi["ctx"]),
                    "header_says": HEADER_KV_BPT,
                    "ratio_measured_over_header": round(bpt / HEADER_KV_BPT, 3)}
    json.dump(out, open(OUT, "w"), indent=1)
    print(json.dumps(out.get("measured_kv_bytes_per_token"), indent=1))


if __name__ == "__main__":
    main()
