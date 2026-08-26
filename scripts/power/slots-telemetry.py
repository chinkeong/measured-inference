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
    """Aggregate per-request statistics from a /slots trace.

    THE FIELD THAT LOOKS LIKE THE PROMPT IS NOT THE PROMPT. /slots reports
    n_prompt_tokens as the slot's CURRENT CONTEXT-ARRAY length, so it grows as
    tokens are generated. Publishing max() of it as "prompt depth" inflates the
    figure by the whole decoded count, and worse: because the array is carried
    over and only truncated when a new task takes the slot, a task's first
    sample can still show the PREVIOUS occupant's longer context, which max()
    then latches permanently. The prompt is n_prompt_tokens_processed +
    n_prompt_tokens_cache - two disjoint, monotone counters that sum to it -
    and those are what this reports.

    WHAT A 1 Hz POLL CANNOT SEE, stated rather than smoothed over. n_decoded is
    read between polls and llama-server clears it when the slot goes idle, so
    the last reading before a request ends is always short of the true total:
    every decoded count here is a FLOOR, understated by up to one poll interval
    of generation. Requests shorter than the interval may not be sampled at
    all. Both are reported as counts so the reader can judge the bias instead
    of inheriting it silently.
    """
    path = os.path.join(OUT, "%s-slots.csv" % tag)
    if not os.path.exists(path):
        sys.exit("no slots telemetry at %s" % path)
    rows = []
    for i, ln in enumerate(io.open(path, encoding="utf-8", errors="replace")):
        if i == 0:
            continue
        p_ = ln.strip().split(",")
        if len(p_) != len(COLS):
            continue
        try:
            rows.append((float(p_[0]), int(p_[1]), int(p_[2]), int(p_[3]),
                         int(p_[4]), int(p_[5]), int(p_[6])))
        except ValueError:
            continue
    if not rows:
        sys.exit("no parsable rows")

    tasks, order = {}, []
    for t, tid, proc, npt, nptp, nptc, ndec in rows:
        if tid < 0:
            continue
        if tid not in tasks:
            tasks[tid] = {"t0": t, "t1": t, "n": 0, "nptp": nptp,
                          "nptc": nptc, "ndec": ndec}
            order.append(tid)
        d = tasks[tid]
        d["t1"] = t
        d["n"] += 1
        # Monotone counters: max is right. n_prompt_tokens is deliberately NOT
        # tracked - it is the context array, not the prompt.
        d["ndec"] = max(d["ndec"], ndec)
        d["nptp"] = max(d["nptp"], nptp)
        d["nptc"] = max(d["nptc"], nptc)
    for d in tasks.values():
        d["depth"] = d["nptp"] + d["nptc"]

    span = rows[-1][0] - rows[0][0]
    # Slot occupancy, not wall-clock duty cycle: with several slots these
    # differ, so it is named for what it measures.
    busy_samples = sum(1 for r in rows if r[2])
    nslots = max(1, len(set(r[1] for r in rows if r[2])) and
                 int(round(len(rows) / max(1, len(set(
                     round(r[0], 0) for r in rows))))))
    done = [tasks[i] for i in order if tasks[i]["ndec"] > 0]

    # Requests observed only once cannot have a reliable final count, and
    # requests live at either edge of the window are partly outside it.
    single = [d for d in done if d["n"] == 1]
    edge = [d for d in done
            if d["t0"] <= rows[0][0] + 1e-9 or d["t1"] >= rows[-1][0] - 1e-9]

    tot_dec = sum(d["ndec"] for d in done)
    tot_pro = sum(d["nptp"] for d in done)
    tot_cache = sum(d["nptc"] for d in done)
    tot_depth = sum(d["depth"] for d in done)

    def med(v):
        v = sorted(v)
        n = len(v)
        if not n:
            return 0
        return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0

    print("window            %.1f min  (%d polls at ~%.2f Hz)"
          % (span / 60.0, len(rows), len(rows) / max(span, 1e-9)))
    print("slot occupancy    %.1f%% of samples had a request in flight"
          % (100.0 * busy_samples / len(rows)))
    print("requests seen     %d  (%d produced tokens)" % (len(order), len(done)))
    if single or edge:
        print("  caveats         %d observed in a single poll, %d live at a "
              "window edge" % (len(single), len(edge)))
    print()
    print("tokens decoded    %d   (FLOOR - see docstring; 1 Hz truncation)" % tot_dec)
    print("prompt recomputed %d" % tot_pro)
    print("prompt from cache %d" % tot_cache)
    print("prompt depth      %d   (= recomputed + cache, NOT n_prompt_tokens)"
          % tot_depth)
    if tot_depth:
        print("  cache supplied  %.1f%% of all prompt tokens"
              % (100.0 * tot_cache / tot_depth))
    if done:
        print()
        print("per request       median %.0f decoded, median %.0f prompt depth"
              % (med([d["ndec"] for d in done]), med([d["depth"] for d in done])))
        print("                  max    %d decoded, max    %d prompt depth"
              % (max(d["ndec"] for d in done), max(d["depth"] for d in done)))
    if tot_dec and tot_pro:
        print()
        print("prefill:decode    %.2f prompt TOKENS recomputed per decoded token"
              % (float(tot_pro) / tot_dec))
        print("                  (a token ratio, NOT a time split - prefill runs")
        print("                   batched and far faster per token than decode)")
    return {"span_s": span, "requests": len(order), "decoded": tot_dec,
            "prompt_processed": tot_pro, "prompt_cached": tot_cache,
            "prompt_depth": tot_depth, "n_single_poll": len(single),
            "n_edge": len(edge)}


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
