#!/usr/bin/env python3
"""Stage 2 MEMORY MAP for ornith-1.5-9b-mtp — the two-constant model, measured.

stage-2.md's products: the budget table, the drafter VRAM on/off PAIR, the
projector PAIR, the desktop slack, and a deep-fill probe near the top of any
window this campaign intends to label (rule 13b — "no window is labeled without
a deep-fill probe near its top").

WHAT MAKES THIS CAMPAIGN'S STAGE 2 UNUSUAL. plan.json flagged it: the whole
262,144-token window fits every arm, so there is no CEILING to find and the
ceiling sweep collapses to one rung per file. What is still worth measuring is
the CONSTANTS -- what the projector costs, what the drafter costs, and whether
the fit arithmetic that said "5,666 MiB spare at full context" survives contact
with llama.cpp's compute buffers, which check-request.py explicitly does not
count and warns are worth hundreds of MiB.

Rule 13's scope is <file + drafter + projector + desktop>, and every number here
carries all four.

VRAM IS READ SETTLED, NOT AT LOAD. Stage 1 measured a board reading 133.14 W and
1821 MHz five seconds after a load and 31.12 W settled; memory.used is steadier
than power but the same discipline applies -- these readings are taken after the
server is healthy AND after a settle wait, and each is the median of n samples.
"""
import json, os, statistics, subprocess, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "scripts", "lib"))
sys.path.insert(0, os.path.join(REPO, "scripts", "bench"))
import paths            # noqa: E402
import gpu_lock         # noqa: E402

CAMP = paths.load_campaign()
SLUG = CAMP["slug"]
OUT = os.path.join(REPO, "results", SLUG, "data", "stage2-memory-map.json")
WORK = os.path.join(REPO, "results", SLUG, "work")
PORT = CAMP.get("port", 1234)
SERVER = paths.llama_bin("llama-server")
MACHINE = json.load(open(os.path.join(REPO, "results", SLUG, "machine.json")))
BOARD = MACHINE["board_total_mib"]
DESKTOP = MACHINE["desktop_reserve_mib"]["max"]

CTX = 32768            # the pair table's constant context; the deep fill is separate
NGL = 99
SETTLE_S = 20
N_SAMPLES = 9

# <file + drafter + projector + desktop> -- rule 13's scope, one arm per corner.
PAIRS = [
    ("Q8_0-bare",          "Q8_0",   False, False),
    ("Q8_0-proj",          "Q8_0",   True,  False),
    ("Q8_0-draft",         "Q8_0",   False, True),
    ("Q8_0-proj-draft",    "Q8_0",   True,  True),
    ("Q4_K_M-bare",        "Q4_K_M", False, False),
    ("Q4_K_M-proj-draft",  "Q4_K_M", True,  True),
    ("IQ2_M-bare",         "IQ2_M",  False, False),
    ("IQ2_M-proj-draft",   "IQ2_M",  True,  True),
]


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def vram_samples(n=N_SAMPLES):
    used, pw = [], []
    for _ in range(n):
        o = subprocess.run(["nvidia-smi",
                            "--query-gpu=memory.used,power.draw,clocks.sm",
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=30).stdout
        parts = o.strip().split(",")
        used.append(float(parts[0]))
        pw.append(float(parts[1]))
        time.sleep(0.5)
    return {"median_mib": statistics.median(used), "min_mib": min(used),
            "max_mib": max(used), "n": n,
            "power_median_w": round(statistics.median(pw), 2)}


def load():
    if os.path.exists(OUT):
        try:
            return json.load(open(OUT))
        except Exception:
            pass
    return {"_schema": "stage2-memory-map v1", "slug": SLUG,
            "board_total_mib": BOARD, "desktop_reserve_mib": DESKTOP,
            "budget_mib": BOARD - DESKTOP, "ctx": CTX, "ngl": NGL,
            "settle_s": SETTLE_S,
            "scope": "rule 13: <file + drafter + projector + desktop>",
            "note": ("memory.used includes the desktop. Subtract "
                     "desktop_reserve_mib for the server's own footprint."),
            "pairs": {}}


def measure(tag, model_alias, want_proj, want_draft, out):
    if tag in out["pairs"] and out["pairs"][tag].get("settled"):
        log("%s already measured -- skipping" % tag)
        return
    gguf = paths.model_path(CAMP["models"][model_alias])
    flags = [SERVER, "-m", gguf, "--alias", tag, "-c", str(CTX), "-ngl", str(NGL),
             "--parallel", "1", "--jinja", "--host", "127.0.0.1", "--port", str(PORT)]
    if want_proj:
        flags += ["--mmproj", paths.model_path(CAMP["models"]["mmproj"])]
    if want_draft:
        flags += ["--spec-type", "draft-mtp", "-md",
                  paths.model_path(CAMP["models"]["drafter"]),
                  "--spec-draft-ngl", "99", "--spec-draft-n-max", "10",
                  "--spec-draft-p-min", "0.5"]
    logp = os.path.join(WORK, "stage2-%s.log" % tag)
    rec = {"model": model_alias, "projector": want_proj, "drafter": want_draft,
           "ctx": CTX, "server_log": os.path.relpath(logp, REPO)}
    log("%s: loading" % tag)
    fh = open(logp, "w")
    proc = gpu_lock.serve(flags, tag="stage2-" + tag, stdout=fh,
                          stderr=subprocess.STDOUT)
    try:
        ok = False
        for _ in range(600):
            time.sleep(2)
            if proc.poll() is not None:
                break
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/health" % PORT,
                                            timeout=5) as r:
                    if r.status == 200:
                        ok = True
                        break
            except Exception:
                pass
        if not ok:
            fh.flush()
            rec["error"] = "never healthy (rc=%s)" % proc.poll()
            rec["log_tail"] = open(logp, errors="replace").read()[-2000:]
            out["pairs"][tag] = rec
            return
        time.sleep(SETTLE_S)
        s = vram_samples()
        rec["settled"] = s
        rec["server_mib"] = round(s["median_mib"] - DESKTOP, 1)
        log("%s: %.0f MiB total, %.0f MiB server-only, %.1f W"
            % (tag, s["median_mib"], rec["server_mib"], s["power_median_w"]))
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=45)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        fh.close()
    out["pairs"][tag] = rec


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    out = load()
    gpu_lock.acquire("stage2-memory-map")
    for tag, alias, proj, draft in PAIRS:
        measure(tag, alias, proj, draft, out)
        json.dump(out, open(OUT, "w"), indent=1)      # rule 28
    # --- the two constants, derived from the pairs that differ by one thing ---
    p = out["pairs"]

    def delta(a, b):
        if a in p and b in p and p[a].get("server_mib") and p[b].get("server_mib"):
            return round(p[a]["server_mib"] - p[b]["server_mib"], 1)
        return None
    out["constants"] = {
        "projector_mib": {
            "value": delta("Q8_0-proj", "Q8_0-bare"),
            "how": "MEASURED: Q8_0-proj minus Q8_0-bare, one flag apart",
            "header_says": 879},
        "drafter_mib": {
            "value": delta("Q8_0-draft", "Q8_0-bare"),
            "how": "MEASURED: Q8_0-draft minus Q8_0-bare, one flag apart",
            "file_bytes": 2430895232,
            "note": "rule 13: drafter VRAM is an on/off pair, not a slider"},
        "both_vs_sum": {
            "value": delta("Q8_0-proj-draft", "Q8_0-bare"),
            "how": ("MEASURED: both minus bare. Compare against projector+drafter "
                    "summed -- if they differ, the two are not independent and the "
                    "budget table cannot add them.")}}
    out["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    json.dump(out, open(OUT, "w"), indent=1)
    log("wrote %s" % OUT)


if __name__ == "__main__":
    main()
