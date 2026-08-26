#!/usr/bin/env python3
"""Server-side counters from llama-server's Prometheus endpoint.

    metrics-telemetry.py --tag <name> [--port 1283] [--interval 1.0]
    metrics-telemetry.py --analyse --tag <name>

REQUIRES the server to have been started with `--metrics`. It refuses to run
otherwise rather than writing an empty file, because a collector that exits 0
having recorded nothing is the failure mode this campaign keeps finding.

WHY, GIVEN /slots ALREADY EXISTS. /slots is polled state: it says what a slot
holds at the instant it is asked, so phase and rate have to be inferred from
differences between samples, and anything shorter than the poll interval is
invisible. /metrics is CUMULATIVE, and it carries the two quantities polling
cannot reconstruct:

    prompt_seconds_total            time the server spent processing prompts
    tokens_predicted_seconds_total  time it spent generating

Those give the prefill-against-decode split in TIME, exactly, instead of the
approximation this campaign has been making by counting one-second samples in
which a counter advanced. The distinction matters because the same run splits
73/24 by wall-clock seconds and inverts to roughly 4.6 prompt tokens per
generated token - two true statements in different units that are easy to
misquote for one another.

It also carries kv_cache_usage_ratio, which is the only direct measure of how
close the context is to full, and requests_deferred, which says whether the
server ever had to queue - a scheduling fact invisible from the GPU side.
"""
import argparse, io, os, sys, time, urllib.request

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "..", "results", "qwen38-27b-blind", "data", "telemetry")

# Counter names are prefixed "llamacpp:" in the exposition format. Kept as a
# tuple so the CSV column order is fixed and a later reader can trust it.
WANT = ("prompt_tokens_total", "tokens_predicted_total",
        "prompt_seconds_total", "tokens_predicted_seconds_total",
        "n_decode_total", "n_busy_slots_per_decode",
        "kv_cache_usage_ratio", "kv_cache_tokens",
        "requests_processing", "requests_deferred")


def scrape(port, timeout=5):
    with urllib.request.urlopen("http://127.0.0.1:%d/metrics" % port,
                                timeout=timeout) as r:
        body = r.read().decode("utf-8", "replace")
    out = {}
    for ln in body.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        parts = ln.split()
        if len(parts) < 2:
            continue
        name = parts[0].split("{")[0]
        if name.startswith("llamacpp:"):
            name = name[len("llamacpp:"):]
        if name in WANT:
            try:
                out[name] = float(parts[1])
            except ValueError:
                pass
    return out


def collect(tag, port, interval):
    try:
        first = scrape(port)
    except Exception as e:
        sys.exit("cannot read /metrics on port %d (%s).\n"
                 "The server must be started with --metrics; refusing to "
                 "write an empty file." % (port, e))
    if not first:
        sys.exit("/metrics answered but exposed none of the expected "
                 "counters; refusing to write a file that would look like a "
                 "measurement.")
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "%s-metrics.csv" % tag)
    f = io.open(path, "w", encoding="utf-8")
    f.write("t," + ",".join(WANT) + "\n")
    f.flush()
    print("collecting -> %s (%d counters)" % (path, len(first)), flush=True)
    misses = 0
    while True:
        try:
            m = scrape(port)
            f.write("%.3f,%s\n" % (time.time(),
                                   ",".join(str(m.get(k, "")) for k in WANT)))
            f.flush()
            misses = 0
        except Exception:
            misses += 1
            if misses > 600:
                print("server unreachable for %d polls, stopping" % misses,
                      flush=True)
                break
        time.sleep(interval)
    f.close()


def analyse(tag):
    path = os.path.join(OUT, "%s-metrics.csv" % tag)
    if not os.path.exists(path):
        sys.exit("no metrics telemetry at %s" % path)
    rows, hdr = [], None
    for i, ln in enumerate(io.open(path, encoding="utf-8", errors="replace")):
        p = ln.strip().split(",")
        if i == 0:
            hdr = p
            continue
        try:
            rows.append([float(x) if x else float("nan") for x in p])
        except ValueError:
            continue
    if len(rows) < 2:
        sys.exit("not enough samples")
    idx = {k: hdr.index(k) for k in hdr}
    a, b = rows[0], rows[-1]

    def d(k):
        return b[idx[k]] - a[idx[k]]

    span = b[0] - a[0]
    pt, tp = d("prompt_tokens_total"), d("tokens_predicted_total")
    ps, ts = d("prompt_seconds_total"), d("tokens_predicted_seconds_total")
    print("window            %.1f min (%d samples)" % (span / 60.0, len(rows)))
    print()
    print("prompt tokens     %d in %.1f s  = %.0f tok/s" %
          (pt, ps, pt / ps if ps else 0))
    print("predicted tokens  %d in %.1f s  = %.1f tok/s" %
          (tp, ts, tp / ts if ts else 0))
    if ps + ts > 0:
        print()
        print("TIME split        prefill %.1f%%, decode %.1f%%"
              % (100.0 * ps / (ps + ts), 100.0 * ts / (ps + ts)))
        print("                  (exact, from cumulative server counters -")
        print("                   NOT inferred from poll samples)")
    if pt and tp:
        print("TOKEN ratio       %.2f prompt tokens per generated token"
              % (float(pt) / tp))
        print("                  (the same run, the opposite direction: the")
        print("                   two ratios differ in unit, not in fact)")
    kv = [r[idx["kv_cache_usage_ratio"]] for r in rows
          if not (r[idx["kv_cache_usage_ratio"]] != r[idx["kv_cache_usage_ratio"]])]
    if kv:
        kv_s = sorted(kv)
        print()
        print("KV cache usage    median %.1f%%, p95 %.1f%%, max %.1f%%"
              % (100 * kv_s[len(kv_s) // 2], 100 * kv_s[int(len(kv_s) * .95)],
                 100 * kv_s[-1]))
    defer = d("requests_deferred")
    print()
    print("requests deferred %d  (%s)" % (defer,
          "the server never had to queue" if defer == 0 else "the server QUEUED"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--port", type=int, default=1283)
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--analyse", action="store_true")
    a = ap.parse_args()
    if a.analyse:
        analyse(a.tag)
    else:
        collect(a.tag, a.port, a.interval)
