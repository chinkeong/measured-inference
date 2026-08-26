#!/usr/bin/env python3
"""Loaders for the telemetry a hardware architect reads, and the derived
quantities that turn samples into design inputs.

ONE CONTRACT, DEFINED ONCE. Every plot in this directory reads through here so
that a column index is written down in exactly one place. The dmon header is
the reason: nvidia-smi writes a "#" before "gpu", so the header row and the
data rows are offset by one field, and a plot that indexes the raw CSV itself
will silently draw the wrong column. That mistake does not raise - it produces
a chart.

WHAT IS LIVE ON THE REFERENCE PART (RTX 3090, verified 2026-08-27):
    pwr gtemp sm mem mclk pclk pviol tviol fb bar1 rxpci txpci
WHAT IS NULL, so no plot should imply it was measured:
    mtemp (memory junction temperature), ccpm, sbecc/dbecc (no ECC on this
    part), and per-process attribution (nvidia-smi pmon reports "-" for every
    process under Windows WDDM).
"""
import io, json, os, subprocess

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")
TEL = os.path.join(ROOT, "results", "qwen38-27b-blind", "data", "telemetry")

# dmon data-row layout AFTER the timestamp we prepend. Index 0 is the gpu
# index; the header row carries an extra leading "#" and is NOT aligned with
# these positions.
DMON = {"gpu": 0, "pwr": 1, "gtemp": 2, "mtemp": 3, "sm": 4, "mem": 5,
        "enc": 6, "dec": 7, "jpg": 8, "ofa": 9, "mclk": 10, "pclk": 11,
        "pviol": 12, "tviol": 13, "fb": 14, "bar1": 15, "ccpm": 16,
        "sbecc": 17, "dbecc": 18, "pci": 19, "rxpci": 20, "txpci": 21}

SLOTS_COLS = ("t", "id_task", "is_processing", "n_prompt_tokens",
              "n_prompt_tokens_processed", "n_prompt_tokens_cache", "n_decoded")

HOST_COLS = ("t", "cpu_pct", "priv_pct", "user_pct", "ctxsw_s", "syscalls_s",
             "runq", "avail_mb", "pagefaults_s", "pagesin_s",
             "committed_bytes", "disk_bytes_s", "disk_qlen", "interrupts_s")

# NVML clock-event bits. Idle is a state, not a limit, and is kept separate
# from every reason so it can never dilute a percentage.
THROTTLE_BITS = ((0x0001, "Idle"), (0x0004, "SW power cap"),
                 (0x0008, "HW slowdown"), (0x0020, "SW thermal"),
                 (0x0040, "HW thermal"), (0x0080, "HW power brake"))

# Reference-part constants, used only for the roofline. Stated here so a plot
# never carries an unlabelled magic number.
SPEC_BW_GBS = 936.0        # RTX 3090 quoted memory bandwidth
BUSY_SM_PCT = 5.0          # a sample counts as work above this SM utilisation


def _p(tag, kind):
    return os.path.join(TEL, "%s-%s.csv" % (tag, kind))


def have(tag, kind):
    return os.path.exists(_p(tag, kind))


def load_dmon(tag, gpu=0):
    """Per-sample GPU telemetry as a dict of float arrays. NULL fields ("-")
    become NaN rather than zero: a plot must be able to tell "not measured"
    from "measured as nothing"."""
    t, cols = [], {k: [] for k in DMON}
    for ln in io.open(_p(tag, "dmon"), encoding="utf-8", errors="replace"):
        p = ln.strip().split(",")
        if len(p) < 3 or not p[1].isdigit():
            continue
        d = p[1:]
        if int(d[DMON["gpu"]]) != gpu:
            continue
        try:
            ts = float(p[0])
        except ValueError:
            continue
        t.append(ts)
        for k, i in DMON.items():
            v = d[i] if i < len(d) else "-"
            try:
                cols[k].append(float(v))
            except ValueError:
                cols[k].append(np.nan)
    out = {k: np.asarray(v, dtype=float) for k, v in cols.items()}
    out["t"] = np.asarray(t, dtype=float)
    order = np.argsort(out["t"])
    return {k: v[order] for k, v in out.items()}


def load_throttle(tag):
    t, mask = [], []
    for ln in io.open(_p(tag, "throttle"), encoding="utf-8", errors="replace"):
        p = ln.strip().split(",")
        if len(p) < 2 or not p[1].startswith("0x"):
            continue
        try:
            t.append(float(p[0]))
            mask.append(int(p[1], 16))
        except ValueError:
            continue
    t, mask = np.asarray(t), np.asarray(mask)
    o = np.argsort(t)
    return {"t": t[o], "mask": mask[o]}


def load_host(tag):
    cols = {k: [] for k in HOST_COLS}
    for i, ln in enumerate(io.open(_p(tag, "host"), encoding="utf-8",
                                   errors="replace")):
        if i == 0:
            continue
        p = ln.strip().split(",")
        if len(p) != len(HOST_COLS):
            continue
        try:
            vals = [float(x) for x in p]
        except ValueError:
            continue
        for k, v in zip(HOST_COLS, vals):
            cols[k].append(v)
    out = {k: np.asarray(v, dtype=float) for k, v in cols.items()}
    o = np.argsort(out["t"])
    return {k: v[o] for k, v in out.items()}


def load_slots(tag):
    cols = {k: [] for k in SLOTS_COLS}
    for i, ln in enumerate(io.open(_p(tag, "slots"), encoding="utf-8",
                                   errors="replace")):
        if i == 0:
            continue
        p = ln.strip().split(",")
        if len(p) != len(SLOTS_COLS):
            continue
        try:
            vals = [float(p[0])] + [int(x) for x in p[1:]]
        except ValueError:
            continue
        for k, v in zip(SLOTS_COLS, vals):
            cols[k].append(v)
    out = {k: np.asarray(v, dtype=float) for k, v in cols.items()}
    o = np.argsort(out["t"])
    return {k: v[o] for k, v in out.items()}


def requests(slots):
    """Per-request records from a /slots trace.

    The prompt is n_prompt_tokens_processed + n_prompt_tokens_cache. It is NOT
    n_prompt_tokens: that field is the slot's current context array, it grows
    as tokens are generated, and it can still hold a previous occupant's longer
    context on a task's first sample.

    n_decoded is a FLOOR. The counter is read between polls and the server
    clears it when the slot goes idle, so the last reading before a request
    ends is always short by up to one poll interval of generation.
    """
    out, order = {}, []
    for i in range(len(slots["t"])):
        tid = int(slots["id_task"][i])
        if tid < 0:
            continue
        if tid not in out:
            out[tid] = {"id": tid, "t0": slots["t"][i], "t1": slots["t"][i],
                        "n": 0, "nptp": 0.0, "nptc": 0.0, "ndec": 0.0}
            order.append(tid)
        r = out[tid]
        r["t1"] = slots["t"][i]
        r["n"] += 1
        r["nptp"] = max(r["nptp"], slots["n_prompt_tokens_processed"][i])
        r["nptc"] = max(r["nptc"], slots["n_prompt_tokens_cache"][i])
        r["ndec"] = max(r["ndec"], slots["n_decoded"][i])
    rs = [out[i] for i in order]
    for r in rs:
        r["depth"] = r["nptp"] + r["nptc"]
        r["cache_frac"] = r["nptc"] / r["depth"] if r["depth"] else 0.0
        r["wall"] = max(r["t1"] - r["t0"], 0.0)
    return rs


def decode_rate(slots, smooth=1):
    """(t, tokens/s) from consecutive n_decoded readings within one task.

    Only same-task, increasing pairs are used: a task change resets the
    counter, and differencing across that boundary would invent a negative
    rate or a spurious spike.
    """
    t, r = [], []
    for i in range(1, len(slots["t"])):
        if slots["id_task"][i] != slots["id_task"][i - 1]:
            continue
        dt = slots["t"][i] - slots["t"][i - 1]
        dn = slots["n_decoded"][i] - slots["n_decoded"][i - 1]
        if dt <= 0 or dn <= 0:
            continue
        t.append(slots["t"][i])
        r.append(dn / dt)
    t, r = np.asarray(t), np.asarray(r)
    if smooth > 1 and len(r) >= smooth:
        k = np.ones(smooth) / smooth
        r = np.convolve(r, k, mode="same")
    return t, r


def phase_of(slots):
    """Per-sample phase label: 2 decode, 1 prompt-processing, 0 idle.

    Decode is identified by n_decoded ADVANCING, not by is_processing, which
    is equally true during prompt processing.
    """
    n = len(slots["t"])
    ph = np.zeros(n, dtype=int)
    for i in range(1, n):
        if not slots["is_processing"][i]:
            continue
        same = slots["id_task"][i] == slots["id_task"][i - 1]
        if same and slots["n_decoded"][i] > slots["n_decoded"][i - 1]:
            ph[i] = 2
        else:
            ph[i] = 1
    return ph


def throttle_series(thr):
    """(t, label) per sample, choosing ONE label by severity so a stacked plot
    sums to 100%. Hardware protection outranks a software clock step, which
    outranks the power cap, which outranks unconstrained."""
    lab = []
    for m in thr["mask"]:
        m = int(m)
        if m < 0:
            lab.append("no data")
        elif m & 0x0001:
            lab.append("Idle")
        elif m & 0x0040:
            lab.append("HW thermal")
        elif m & 0x0080:
            lab.append("HW power brake")
        elif m & 0x0008:
            lab.append("HW slowdown")
        elif m & 0x0020:
            lab.append("SW thermal")
        elif m & 0x0004:
            lab.append("SW power cap")
        else:
            lab.append("Unconstrained")
    return thr["t"], lab


def load_exercises(run, cache=True):
    """aider per-exercise results, via WSL. Cached, because the run holds
    hundreds of files and a plot pass should not shell out hundreds of times."""
    # The listing is one cheap call; catting hundreds of files is the expensive
    # part, so the cache is validated against the CURRENT file count rather
    # than trusted. A run in flight gains exercises continuously, and a cache
    # that never invalidates would quietly build every later report from the
    # first snapshot it happened to take - a report that is stale and complete-
    # looking at the same time.
    cf = os.path.join(TEL, "exercises-%s.json" % run)
    cmd = ("find ~/bench/aider/tmp.benchmarks/" + run +
           " -name .aider.results.json -printf '%T@ %p\\n' 2>/dev/null")
    o = subprocess.run(["wsl", "-e", "bash", "-lc", cmd],
                       capture_output=True, text=True, timeout=300).stdout
    items = sorted((float(l.split(" ", 1)[0]), l.split(" ", 1)[1].strip())
                   for l in o.strip().splitlines() if l.strip())
    if cache and os.path.exists(cf):
        try:
            blob = json.load(io.open(cf, encoding="utf-8"))
            # The cache records how many files existed when it was built. If
            # the listing has grown, it is stale by definition.
            if isinstance(blob, dict) and blob.get("n_listed") == len(items):
                return blob["items"]
        except Exception:
            pass
    out = []
    for mt, path in items:
        cat = subprocess.run(["wsl", "-e", "bash", "-lc",
                              "cat " + json.dumps(path)],
                             capture_output=True, text=True, timeout=60).stdout
        try:
            r = json.loads(cat)
        except Exception:
            continue
        if isinstance(r, list):
            r = r[-1] if r else {}
        if not r.get("completion_tokens"):
            continue
        out.append({"t_end": mt, "dur": r.get("duration", 0.0),
                    "prompt": r.get("prompt_tokens", 0),
                    "completion": r.get("completion_tokens", 0),
                    "case": r.get("testcase", "?"),
                    # <run>/<lang>/exercises/practice/<case>/.aider.results.json
                    # - FOUR levels up, not three. Three lands on the literal
                    # directory "exercises", which is the same for every row,
                    # so a figure colouring by language would draw one colour
                    # and look fine doing it.
                    "lang": os.path.basename(os.path.dirname(os.path.dirname(
                        os.path.dirname(os.path.dirname(path))))),
                    # The polyglot benchmark allows two attempts; the LAST
                    # outcome is the one the pass rate counts.
                    "passed": bool((r.get("tests_outcomes") or [False])[-1])})
    if cache:
        try:
            json.dump({"n_listed": len(items), "items": out},
                      io.open(cf, "w", encoding="utf-8"))
        except Exception:
            pass
    return out


def energy(dmon, t0, t1, busy_only=True):
    """Trapezoidal joules over a window, interpolating at both edges.

    Truncating to samples strictly inside loses up to one sampling period at
    each end, which on a short window is a real fraction of the answer.
    """
    t, w, sm = dmon["t"], dmon["pwr"], dmon["sm"]
    j = bs = 0.0
    for i in range(1, len(t)):
        if t[i] <= t0 or t[i - 1] >= t1:
            continue
        span = t[i] - t[i - 1]
        if span <= 0:
            continue
        ca, cb = max(t[i - 1], t0), min(t[i], t1)
        pa = w[i - 1] + (w[i] - w[i - 1]) * ((ca - t[i - 1]) / span)
        pb = w[i - 1] + (w[i] - w[i - 1]) * ((cb - t[i - 1]) / span)
        if busy_only and max(sm[i - 1], sm[i]) <= BUSY_SM_PCT:
            continue
        j += (pa + pb) / 2.0 * (cb - ca)
        bs += cb - ca
    return j, bs
