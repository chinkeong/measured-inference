#!/usr/bin/env python3
"""Stage 1 STRUCTURE for ornith-1.5-9b-mtp: KV cross-check, -ngl proof, floors.

WHY THIS FILE EXISTS AND scripts/probe-config.sh DOES NOT DO IT.
stage-1.md names scripts/probe-config.sh as the POSIX seed for the floor probe.
That script launches llama-server with a bare `&` and stops it with
`pkill -f "llama-server.*--port <port>"`. It never touches scripts/bench/gpu_lock.py.
AGENTS.md rule 20 is explicit and says "enforced": every server goes through
gpu_lock.serve() / Start-GuardedServer, never a bare Popen -- because four
concurrent llama-servers exhausted host commit and hung the reference machine on
2026-08-29. A pkill by port pattern is worse than unguarded: it would also kill a
server another job legitimately holds under the lock.

The stage table says to adapt into results/<slug>/work/ and not to edit the
references, so this is the adaptation. It takes the lock ONCE for the whole
stage (deliberately sticky -- a probe that starts a second server after stopping
the first is still one GPU job) and launches every server through
gpu_lock.serve(), which also commit-caps the child and guarantees it cannot
outlive this process.

WHAT IT PRODUCES, in data/stage1-structure.json:
  * llama-bench tg128 + pp512 per file            -- gate input 1 (rule 10)
  * file size on disk                             -- gate input 2
  * the server's OWN KV figure at a known -c      -- the rule-4 cross-check
    against the header's 32,768 B/token, which is the budget-table backbone
  * a temp-0 floor probe per file, server timings preferred over wall clock
  * the loaded-idle power sample, first time a server is up and idle
"""
import json, os, re, subprocess, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "scripts", "lib"))
sys.path.insert(0, os.path.join(REPO, "scripts", "bench"))
import paths                      # noqa: E402
import gpu_lock                   # noqa: E402

CAMP = paths.load_campaign()
SLUG = CAMP["slug"]
OUT_DIR = os.path.join(REPO, "results", SLUG, "data")
WORK = os.path.join(REPO, "results", SLUG, "work")
PORT = CAMP.get("port", 1234)
SERVER = paths.llama_bin("llama-server")
BENCH = paths.llama_bin("llama-bench")

# The floor probe's conditions. They travel with every number below (rule 3).
CTX = 32768            # cheap, and the depth the KV cross-check is taken at
NGL = 99               # rule 15: the output projection counts as layer n+1
TEMP = 0.0
PROBE = ("Write a Python function that merges two sorted integer lists into one "
         "sorted list without using sort(). Explain the invariant it maintains.")
N_PREDICT = 300

# Header-derived, from results/<slug>/model-*.json. The server must agree.
KV_BYTES_PER_TOKEN_F16 = 32768

ARMS = [("Q8_0", "Ornith-1.5-9B-MTP-Q8_0.gguf"),
        ("Q4_K_M", "Ornith-1.5-9B-MTP-Q4_K_M.gguf"),
        ("IQ2_M", "Ornith-1.5-9B-MTP-IQ2_M.gguf")]


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def gpu_sample():
    """One nvidia-smi row: power, clocks, memory. The loaded-idle reading."""
    q = ("power.draw,clocks.sm,clocks.mem,utilization.gpu,memory.used,"
         "temperature.gpu,pstate,clocks_event_reasons.active")
    out = subprocess.run(["nvidia-smi", "--query-gpu=" + q,
                          "--format=csv,nounits,nounits"],
                         capture_output=True, text=True, timeout=30).stdout
    rows = [r for r in out.strip().splitlines()[1:] if r.strip()]
    if not rows:
        return None
    v = [x.strip() for x in rows[0].split(",")]
    keys = q.split(",")
    return dict(zip(keys, v))


def run_bench(gguf):
    """llama-bench tg128 + pp512. The gate's preferred speed input."""
    if not BENCH or not os.path.exists(BENCH):
        return {"how": "UNKNOWN", "why": "this build ships no llama-bench"}
    cmd = [BENCH, "-m", gguf, "-ngl", str(NGL), "-p", "512", "-n", "128",
           "-r", "3", "-o", "json"]
    log("llama-bench: %s" % os.path.basename(gguf))
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if p.returncode != 0:
        return {"how": "FAILED", "rc": p.returncode,
                "stderr_tail": (p.stderr or "")[-1500:]}
    try:
        rows = json.loads(p.stdout)
    except Exception:
        return {"how": "FAILED", "why": "llama-bench did not emit JSON",
                "stdout_tail": (p.stdout or "")[-1500:]}
    got = {"how": "MEASURED", "rows": []}
    for r in rows:
        got["rows"].append({"n_prompt": r.get("n_prompt"), "n_gen": r.get("n_gen"),
                            "avg_ts": r.get("avg_ts"), "stddev_ts": r.get("stddev_ts"),
                            "backend": r.get("backend"), "model_size": r.get("model_size")})
    return got


KV_RE = re.compile(r"KV (?:self )?size\s*=\s*([\d.]+)\s*MiB|"
                   r"kv_cache.*?size\s*=\s*([\d.]+)\s*MiB|"
                   r"KV buffer size\s*=\s*([\d.]+)\s*MiB", re.I)
OFFLOAD_RE = re.compile(r"offloaded\s+(\d+)/(\d+)\s+layers", re.I)


def serve_and_probe(label, gguf, first):
    """One server, through gpu_lock.serve(). Returns the floor + the KV reading."""
    logp = os.path.join(WORK, "stage1-%s-server.log" % label)
    args = [SERVER, "-m", gguf, "--alias", label, "-c", str(CTX), "-ngl", str(NGL),
            "--parallel", "1", "--jinja", "--host", "127.0.0.1", "--port", str(PORT)]
    rec = {"label": label, "file": os.path.basename(gguf),
           "size_bytes": os.path.getsize(gguf), "ctx": CTX, "ngl": NGL,
           "cache_type": "f16 (server default) -- matches the header's f16 figure",
           "server_log": os.path.relpath(logp, REPO), "argv": args}
    fh = open(logp, "w")
    proc = gpu_lock.serve(args, tag="stage1-%s" % label, stdout=fh,
                          stderr=subprocess.STDOUT)
    try:
        healthy = False
        for _ in range(600):
            time.sleep(2)
            if proc.poll() is not None:
                rec["error"] = "server exited early, rc=%s" % proc.returncode
                break
            try:
                with urllib.request.urlopen(
                        "http://127.0.0.1:%d/health" % PORT, timeout=5) as r:
                    if r.status == 200:
                        healthy = True
                        break
            except Exception:
                pass
        if not healthy:
            fh.flush()
            rec.setdefault("error", "server never became healthy")
            rec["server_log_tail"] = open(logp).read()[-2500:]
            return rec

        # --- the loaded-idle power baseline, once, while nothing is decoding
        if first:
            time.sleep(5)
            samples = []
            for _ in range(15):
                s = gpu_sample()
                if s:
                    samples.append(s)
                time.sleep(0.5)
            w = [float(s["power.draw"]) for s in samples if s.get("power.draw")]
            rec["loaded_idle"] = {
                "how": "MEASURED", "n": len(w),
                "mean_w": round(sum(w) / len(w), 2) if w else None,
                "min_w": min(w) if w else None, "max_w": max(w) if w else None,
                "memory_used_mib": samples[-1].get("memory.used") if samples else None,
                "tier": "in-band GPU board power (NVML); PSU losses and PUE excluded",
                "note": "server up, model resident, nothing decoding"}

        # --- the floor probe: temp 0, short code task, server timings
        body = json.dumps({
            "messages": [{"role": "user", "content": PROBE}],
            "temperature": TEMP, "n_predict": N_PREDICT, "stream": False,
            "cache_prompt": False}).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:%d/v1/chat/completions" % PORT, data=body,
            headers={"Content-Type": "application/json"})
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=900) as r:
            resp = json.load(r)
        wall = time.time() - t0
        tim = resp.get("timings") or {}
        rec["floor"] = {
            "how": "MEASURED",
            "predicted_per_second": tim.get("predicted_per_second"),
            "prompt_per_second": tim.get("prompt_per_second"),
            "predicted_n": tim.get("predicted_n"), "prompt_n": tim.get("prompt_n"),
            "wall_s": round(wall, 3),
            "source": ("server timings.predicted_per_second -- NOT tokens/wall, "
                       "which includes prefill and lies at depth (stage-1.md)"),
            "conditions": {"temp": TEMP, "ctx": CTX, "ngl": NGL,
                           "speculation": "none", "content": "short code task",
                           "desktop": "live GNOME + Steam + browser (rule 27)"}}
        rec["sample_head"] = (resp.get("choices") or [{}])[0].get(
            "message", {}).get("content", "")[:400]
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=30)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        fh.close()

    # --- what the server itself said about KV and offload (the rule-4 cross-check)
    text = open(logp, errors="replace").read()
    kv_hits = [m for m in re.findall(
        r"^.*(?:KV|kv_cache|kv self).*MiB.*$", text, re.M | re.I)][:12]
    off = OFFLOAD_RE.search(text)
    rec["server_says"] = {
        "kv_lines": kv_hits,
        "offloaded": off.group(0) if off else None,
        "predicted_kv_mib_from_header": round(KV_BYTES_PER_TOKEN_F16 * CTX / 1048576, 1),
        "how": ("rule 4: two independent cheap readings agreeing beat one. The "
                "header derives 32,768 B/token; at c=%d that is %.1f MiB." %
                (CTX, KV_BYTES_PER_TOKEN_F16 * CTX / 1048576))}
    return rec


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(WORK, exist_ok=True)
    gpu_lock.acquire("stage1-structure")          # once, for the whole stage
    out = {"_schema": "stage1-structure v1", "slug": SLUG,
           "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "conditions": {"ctx": CTX, "ngl": NGL, "temp": TEMP,
                          "desktop": "live GNOME + Steam + browser, recorded as-is",
                          "backend": "cuda b10717 (bin/llama.cpp/INSTALL.json)"},
           "arms": []}
    for i, (label, fname) in enumerate(ARMS):
        gguf = paths.model_path(fname)
        log("=== %s ===" % label)
        rec = serve_and_probe(label, gguf, first=(i == 0))
        rec["bench"] = run_bench(gguf)
        out["arms"].append(rec)
        with open(os.path.join(OUT_DIR, "stage1-structure.json"), "w") as f:
            json.dump(out, f, indent=1)          # rule 28: write as it happens
        log("%s: floor %s t/s" % (label, (rec.get("floor") or {}).get(
            "predicted_per_second")))
    out["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(os.path.join(OUT_DIR, "stage1-structure.json"), "w") as f:
        json.dump(out, f, indent=1)
    log("wrote %s" % os.path.join(OUT_DIR, "stage1-structure.json"))


if __name__ == "__main__":
    main()
