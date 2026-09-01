#!/usr/bin/env python3
"""Is the roofline shift caused by CODEBOOKS, or purely by BITS-PER-WEIGHT?

THE CONFOUND THIS REMOVES. Every comparison this campaign has made so far varies
format and bit-width TOGETHER: Q4_K is both a K-quant and 4-bit; IQ2_S is both a
codebook format and 2-bit. The 27B ladder hinted the answer (Q2_K_XL, a
codebook-free format, lands on the IQ curve to within 0.003 in k) but that is a
cross-campaign comparison rule 30 forbids quoting as a measurement.

THE PAIR. Two third-party conversions of the SAME base weights, both dropping the
same MTP layer so the parameter count matches, at effectively identical size:
    Q2_K                 3.83 GB   3.422 bpw   K-quant, NO codebook
    AD-IQ3_XXS-IQ2_S     3.84 GB   3.431 bpw   IQ, codebook/LUT
0.26% apart in bits. Whatever differs between them is FORMAT, not size.

PREDICTION, written before the run (rule 5 keeps a dead claim as a case study):
if bits-per-weight is the whole story, the two land at the same rule-10 constant
and the same SM/DRAM balance. If codebooks add a real penalty, the IQ file sits
further toward compute-bound at equal bits.

Three measurements per file, all inside ONE sweep so rule 30 is satisfied:
  llama-bench tg128 -> decode t/s -> the rule-10 constant
  ncu SpeedOfLight  -> SM % and DRAM % of peak on the hot kernels
  llama-perplexity --kl-divergence vs the BF16 base -> fidelity at equal bits
"""
import json, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "scripts", "lib"))
sys.path.insert(0, os.path.join(REPO, "scripts", "bench"))
import paths, gpu_lock                                        # noqa: E402

DATA = os.path.join(REPO, "results", "ornith-1.5-9b-mtp", "data")
WORK = os.path.join(REPO, "results", "ornith-1.5-9b-mtp", "work")
OUT = os.path.join(DATA, "format-vs-bpw.json")
MODELS = os.path.join(REPO, "models")
BENCH = paths.llama_bin("llama-bench")
PPL = paths.llama_bin("llama-perplexity")
CORPUS = os.path.join(REPO, "corpora", "wikitext-2-raw-test.raw")
BASE_DAT = os.path.join(MODELS, "kld-base-fmt.dat")
PARAMS = 8953803264          # both files drop the MTP layer
PEAK_GBS = 936.0

ARMS = [
    ("Q2_K", "Ornith-1.5-9B.Q2_K.gguf", "K-quant (no codebook)",
     "https://huggingface.co/mradermacher/Ornith-1.5-9B-GGUF/resolve/main/Ornith-1.5-9B.Q2_K.gguf"),
    ("AD-IQ3_XXS-IQ2_S", "Ornith-1.5-9B-AD-IQ3_XXS-IQ2_S.gguf", "IQ (codebook/LUT)",
     "https://huggingface.co/AtomicChat/Ornith-1.5-9B-GGUF/resolve/main/Ornith-1.5-9B-AD-IQ3_XXS-IQ2_S.gguf"),
]
METRICS = ("sm__throughput.avg.pct_of_peak_sustained_elapsed,"
           "gpu__dram_throughput.avg.pct_of_peak_sustained_elapsed,"
           "dram__bytes.sum.per_second")


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def _remote_size(url):
    """Content-Length from a HEAD, following redirects. None if unavailable."""
    try:
        r = subprocess.run(["curl", "-sIL", url], capture_output=True,
                           text=True, timeout=120)
        n = None
        for line in r.stdout.splitlines():
            if line.lower().startswith("content-length:"):
                n = int(line.split(":", 1)[1].strip())
        return n
    except Exception:
        return None


def fetch(url, dest):
    """Download, and only call it done when the size MATCHES the remote.

    `os.path.getsize(dest) > 1e9` accepted any file over a gigabyte as a
    finished download. Both arms here are ~3.83 GB, so a kill or reboot after
    the first gigabyte left a partial file this gate called complete: `curl -C -`
    was then never invoked again on it, and lines below computed `size_bytes`
    and `bpw` from the stub. The whole experiment is "two files 0.22% apart in
    bits, so what differs is FORMAT, not size" -- a 2.0 GB stub yields bpw 1.79
    and would have been written into format-vs-bpw.json as a measurement (rule
    1). It is also silent: llama-bench fails to load the truncated GGUF, tg128
    comes back None, and the arm re-fails identically on every re-run with
    nothing pointing at the download.

    Content-Length is the check that actually answers the question. When the
    remote will not give one, the size is recorded as UNVERIFIED rather than
    assumed good -- an unverifiable download is not a verified one.
    """
    want = _remote_size(url)
    have = os.path.getsize(dest) if os.path.exists(dest) else 0
    if have and want and have == want:
        return True
    if have and want and have != want:
        log("  %s is %d bytes, remote says %d -- resuming the partial download"
            % (os.path.basename(dest), have, want))
    elif have and not want:
        log("  %s exists (%d bytes) and the remote gave no Content-Length: "
            "size UNVERIFIED, re-checking with curl -C -" % (os.path.basename(dest), have))
    log("downloading %s" % os.path.basename(dest))
    r = subprocess.run(["curl", "-sL", "-C", "-", "-o", dest, url], timeout=7200)
    got = os.path.getsize(dest) if os.path.exists(dest) else 0
    if r.returncode != 0:
        log("  curl failed rc=%d for %s" % (r.returncode, os.path.basename(dest)))
        return False
    if want and got != want:
        log("  INCOMPLETE: %s is %d bytes, remote says %d -- refusing to use it"
            % (os.path.basename(dest), got, want))
        return False
    if not want and got <= 1e9:
        log("  %s is only %d bytes and the size could not be verified"
            % (os.path.basename(dest), got))
        return False
    return True


def run(cmd, logp, timeout=7200):
    with open(logp, "w") as fh:
        p = gpu_lock.serve(cmd, tag="fmt", stdout=fh, stderr=subprocess.STDOUT)
        try:
            rc = p.wait(timeout=timeout)
        except Exception:
            p.kill(); rc = -9
    return rc, open(logp, errors="replace").read()


def main():
    out = {"_schema": "format-vs-bpw v1",
           "question": "codebooks, or bits-per-weight? matched-bpw pair, one sweep",
           "peak_bandwidth_gbs": PEAK_GBS, "params": PARAMS, "arms": {}}
    if os.path.exists(OUT):
        try: out = json.load(open(OUT))
        except Exception: pass
    for label, fname, family, url in ARMS:
        if not fetch(url, os.path.join(MODELS, fname)):
            out["arms"][label] = {"error": "download failed"}; continue
    gpu_lock.acquire("stage6-format")
    if not os.path.exists(BASE_DAT):
        log("BF16 base logits for the KLD arm")
        # WRITE TO A .part AND RENAME. `if not os.path.exists(BASE_DAT)` was the
        # only completeness test on a file llama-perplexity writes INCREMENTALLY
        # -- 8,135,225,332 bytes for these 4 chunks. A SIGKILL or reboot during
        # the dump left a partial .dat that the next run accepted, and BOTH arms
        # were then compared against a truncated base, which is a silently wrong
        # KLD rather than a missing one. The rename is atomic, so the canonical
        # path only ever names a file that was written to completion.
        part = BASE_DAT + ".part"
        try:
            os.remove(part)
        except OSError:
            pass
        rc, _ = run([PPL, "-m", os.path.join(MODELS, "vendor-Ornith-1.5-9B-BF16.gguf"),
                     "-f", CORPUS, "-c", "8192", "--chunks", "4", "-ngl", "99",
                     "--kl-divergence-base", part], os.path.join(WORK, "fmt-base.log"))
        if rc != 0 or not os.path.exists(part):
            log("  base logits FAILED rc=%s -- leaving no .dat rather than a "
                "partial one every later run would trust" % rc)
            try:
                os.remove(part)
            except OSError:
                pass
            raise SystemExit("KLD base could not be produced; re-run when fixed")
        os.replace(part, BASE_DAT)
        log("  base logits complete: %d bytes" % os.path.getsize(BASE_DAT))
    for label, fname, family, url in ARMS:
        # AN ARM CARRIES THREE INDEPENDENT MEASUREMENTS and the resume key
        # checked one. tg128, the ncu counters and the KLD pair each come from a
        # separate subprocess whose failure run() swallows (it returns an rc
        # nobody reads, and a timeout kills the child and returns -9 down the
        # same silent path). So an arm where llama-bench succeeded and ncu was
        # denied perf-counter permission, or whose KLD leg was killed, was
        # persisted with tg128 set and the rest simply missing -- and every
        # later run printed "already measured" and skipped it forever. The whole
        # point of the resumability is that a re-run repairs what failed.
        done = out["arms"].get(label, {})
        have = [k for k in ("tg128", "ncu", "mean_kld")
                if done.get(k) not in (None, {}, "")]
        if len(have) == 3:
            log("%s already measured (tg128, ncu, KLD all present)" % label)
            continue
        if have:
            log("%s incomplete -- have %s, missing %s: re-measuring"
                % (label, "+".join(have),
                   "+".join(k for k in ("tg128", "ncu", "mean_kld") if k not in have)))
        g = os.path.join(MODELS, fname)
        rec = {"family": family, "file": fname,
               "size_bytes": os.path.getsize(g),
               "bpw": os.path.getsize(g) * 8.0 / PARAMS}
        log("=== %s (%s, %.3f bpw) ===" % (label, family, rec["bpw"]))
        rc, t = run([BENCH, "-m", g, "-ngl", "99", "-p", "0", "-n", "128",
                     "-r", "3", "-o", "json"], os.path.join(WORK, "fmt-bench-%s.log" % label))
        try:
            rows = json.loads(t[t.index("["):t.rindex("]") + 1])
            rec["tg128"] = max(r["avg_ts"] for r in rows if r.get("n_gen"))
        except Exception:
            rec["tg128"] = None
        if rec["tg128"]:
            rec["rule10_k"] = rec["tg128"] * rec["size_bytes"] / 1e9 / PEAK_GBS
        rc, t = run(["ncu", "--target-processes", "all", "--metrics", METRICS,
                     "--launch-skip", "200", "--launch-count", "60", "--csv",
                     BENCH, "-m", g, "-ngl", "99", "-p", "0", "-n", "128",
                     "-r", "1", "-o", "json"], os.path.join(WORK, "fmt-ncu-%s.log" % label))
        agg, hdr = {}, None
        for line in t.splitlines():
            if '","' not in line: continue
            c = [x.strip().strip('"') for x in line.split('","')]
            if hdr is None and "Metric Name" in c: hdr = c; continue
            if hdr and len(c) == len(hdr):
                d = dict(zip(hdr, c))
                try: agg.setdefault(d["Metric Name"], []).append(float(d["Metric Value"].replace(",", "")))
                except Exception: pass
        rec["ncu"] = {k: round(sum(v) / len(v), 3) for k, v in agg.items()}
        rc, t = run([PPL, "-m", g, "-f", CORPUS, "-c", "8192", "--chunks", "4",
                     "-ngl", "99", "--kl-divergence", "--kl-divergence-base", BASE_DAT],
                    os.path.join(WORK, "fmt-kld-%s.log" % label))
        for k, pat in (("mean_kld", r"Mean\s+KLD:\s*([0-9.eE+-]+)"),
                       ("same_top_pct", r"Same\s+top\s+p:\s*([0-9.]+)")):
            m = re.search(pat, t)
            if m: rec[k] = float(m.group(1))
        out["arms"][label] = rec
        log("  %s: %.2f t/s  k=%.3f  KLD=%s  same-top=%s" % (
            label, rec.get("tg128") or 0, rec.get("rule10_k") or 0,
            rec.get("mean_kld"), rec.get("same_top_pct")))
        json.dump(out, open(OUT, "w"), indent=1)
    try: os.remove(BASE_DAT)
    except OSError: pass
    json.dump(out, open(OUT, "w"), indent=1)
    log("wrote %s" % OUT)


if __name__ == "__main__":
    main()
