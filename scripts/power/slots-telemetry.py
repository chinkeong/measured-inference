#!/usr/bin/env python3
"""Per-request server telemetry, polled from llama-server's /slots endpoint.

    slots-telemetry.py --tag <name> [--port 1283] [--interval 1.0]
    slots-telemetry.py --analyse --tag <name>

WHY THIS EXISTS, and it is a lesson rather than a feature. The first full
agentic run of this campaign was launched with no `--metrics` flag and with the
server's stdout going to a file that stayed 0 bytes for two hours. The GPU
power trace was complete, the pass rates were complete, and the two could not
be divided into each other: joules were known, tokens were not, so the run
could produce no joules-per-token at all.

The recovery was that /slots is served unconditionally - no flag, no restart -
and carries MORE than the log lines would have:

    n_prompt_tokens            full prompt depth for the request
    n_prompt_tokens_processed  what was actually recomputed. NOT the same
                               number: under cache_prompt this campaign has
                               already been misled once, having read the
                               processed count as depth and under-reported
                               retrieval depth by half
    n_prompt_tokens_cache      what the cache supplied, which is the whole
                               difference between those two
    n_decoded                  tokens generated so far, so decode rate falls
                               out of consecutive samples
    is_processing / id_task    phase and request boundaries, which is what
                               splits prefill from decode without a log

The rule earned: an expensive run is the scarce thing, not the sampling. Poll
every source the server offers while the work is in front of you, because a
missing field cannot be recovered afterwards at any price.
"""
import argparse, io, json, os, sys, time, urllib.request

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "..", "results", "qwen38-27b-blind", "data", "telemetry")

COLS = ("t", "id_task", "is_processing", "n_prompt_tokens",
        "n_prompt_tokens_processed", "n_prompt_tokens_cache", "n_decoded")


def poll(port, timeout=5):
    with urllib.request.urlopen("http://127.0.0.1:%d/slots" % port,
                                timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def collect(tag, port, interval):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "%s-slots.csv" % tag)
    f = io.open(path, "w", encoding="utf-8")
    f.write(",".join(COLS) + "\n")
    f.flush()
    print("collecting -> %s" % path, flush=True)
    misses = 0
    while True:
        try:
            for s in poll(port):
                nt = s.get("next_token") or [{}]
                nt = nt[0] if isinstance(nt, list) else nt
                row = (round(time.time(), 3), s.get("id_task", -1),
                       1 if s.get("is_processing") else 0,
                       s.get("n_prompt_tokens", 0),
                       s.get("n_prompt_tokens_processed", 0),
                       s.get("n_prompt_tokens_cache", 0),
                       nt.get("n_decoded", 0))
                f.write(",".join(str(x) for x in row) + "\n")
            f.flush()
            misses = 0
        except Exception:
            # The server going away is the normal end of a run, not an error.
            # Keep trying for a while so a brief stall does not end collection,
            # but do not spin forever against a dead port.
            misses += 1
            if misses > 600:
                print("server unreachable for %d polls, stopping" % misses,
                      flush=True)
                break
        time.sleep(interval)
    f.close()


def analyse(tag):
    path = os.path.join(OUT, "%s-slots.csv" % tag)
    if not os.path.exists(path):
        sys.exit("no slots telemetry at %s" % path)
    rows = []
    for i, ln in enumerate(io.open(path, encoding="utf-8", errors="replace")):
        if i == 0:
            continue
        p = ln.strip().split(",")
        if len(p) != len(COLS):
            continue
        try:
            rows.append((float(p[0]), int(p[1]), int(p[2]), int(p[3]),
                         int(p[4]), int(p[5]), int(p[6])))
        except ValueError:
            continue
    if not rows:
        sys.exit("no parsable rows")

    # Group by request. A task id repeats across polls; its last sample holds
    # the final decoded count and its first holds the prompt shape.
    tasks, order = {}, []
    for t, tid, proc, npt, nptp, nptc, ndec in rows:
        if tid < 0:
            continue
        if tid not in tasks:
            tasks[tid] = {"t0": t, "t1": t, "npt": npt, "nptp": nptp,
                          "nptc": nptc, "ndec": ndec}
            order.append(tid)
        else:
            d = tasks[tid]
            d["t1"] = t
            d["ndec"] = max(d["ndec"], ndec)
            d["npt"] = max(d["npt"], npt)
            d["nptp"] = max(d["nptp"], nptp)
            d["nptc"] = max(d["nptc"], nptc)

    span = rows[-1][0] - rows[0][0]
    busy = sum(1 for r in rows if r[2])
    done = [tasks[i] for i in order if tasks[i]["ndec"] > 0]
    tot_dec = sum(d["ndec"] for d in done)
    tot_pro = sum(d["nptp"] for d in done)
    tot_cache = sum(d["nptc"] for d in done)
    tot_depth = sum(d["npt"] for d in done)

    print("window            %.1f min  (%d polls, %.1f%% with a request in flight)"
          % (span / 60.0, len(rows), 100.0 * busy / len(rows)))
    print("requests seen     %d  (%d produced tokens)" % (len(order), len(done)))
    print()
    print("tokens decoded    %d" % tot_dec)
    print("prompt recomputed %d" % tot_pro)
    print("prompt from cache %d" % tot_cache)
    print("prompt depth      %d" % tot_depth)
    if tot_depth:
        print("  cache supplied  %.1f%% of all prompt tokens"
              % (100.0 * tot_cache / tot_depth))
    if done:
        dec = sorted(d["ndec"] for d in done)
        dep = sorted(d["npt"] for d in done)
        print()
        print("per request       median %d decoded, median %d prompt depth"
              % (dec[len(dec) // 2], dep[len(dep) // 2]))
        print("                  max    %d decoded, max    %d prompt depth"
              % (dec[-1], dep[-1]))
    if tot_dec and tot_pro:
        print()
        print("prefill:decode    %.2f prompt tokens recomputed per decoded token"
              % (float(tot_pro) / tot_dec))
    return {"span_s": span, "requests": len(order), "decoded": tot_dec,
            "prompt_processed": tot_pro, "prompt_cached": tot_cache,
            "prompt_depth": tot_depth}


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
