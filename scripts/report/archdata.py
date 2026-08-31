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
    """aider per-exercise results, read through a POSIX shell. Cached, because
    the run holds hundreds of files and a plot pass should not shell out
    hundreds of times."""
    # The listing is one cheap call; catting hundreds of files is the expensive
    # part, so the cache is validated against the CURRENT file count rather
    # than trusted. A run in flight gains exercises continuously, and a cache
    # that never invalidates would quietly build every later report from the
    # first snapshot it happened to take - a report that is stale and complete-
    # looking at the same time.
    #
    # THE CACHE IS READ BEFORE THE LISTING, and rule 23's loading order -
    # frozen file, then local cache, then the live source - is why. Until
    # 2026-08-31 the shell-out ran first and took the whole function with it
    # when it failed, so on bare-metal Ubuntu 26.04 (no `wsl` on PATH,
    # FileNotFoundError) the COMMITTED cache for
    # 2026-08-26-14-57-05--iq4xs-full - the run named in build-report.py's own
    # usage line - could not be reached at all, and build-report dropped every
    # agentic figure behind one "[ctx] exercises unavailable" line. The listing
    # is still taken and still invalidates; it is now the thing the cache is
    # checked against rather than the gate standing in front of it.
    cf = os.path.join(TEL, "exercises-%s.json" % run)
    blob = None
    if cache and os.path.exists(cf):
        try:
            b = json.load(io.open(cf, encoding="utf-8"))
            if isinstance(b, dict) and isinstance(b.get("items"), list):
                blob = b
        except Exception:
            blob = None
    cmd = ("find ~/bench/aider/tmp.benchmarks/" + run +
           " -name .aider.results.json -printf '%T@ %p\\n' 2>/dev/null")
    # The command body is ordinary POSIX - aider-bench.sh sets
    # AIDER_DIR=$HOME/bench/aider - and `wsl -e bash -lc` is how a WINDOWS
    # Python reaches the Linux filesystem the benchmark writes into. It is the
    # right and only route there, and a hard dependency that exists nowhere
    # else: measured 2026-08-31 on bare-metal Ubuntu 26.04, this call raised
    # "FileNotFoundError: [Errno 2] No such file or directory: 'wsl'" before it
    # could read anything. On a POSIX host bash runs the same body directly;
    # the Windows route is unchanged.
    argv = (["wsl", "-e", "bash", "-lc", cmd] if os.name == "nt"
            else ["bash", "-lc", cmd])
    try:
        o = subprocess.run(argv, capture_output=True, text=True,
                           timeout=300).stdout
    except OSError:
        # No shell route at all on this box. A committed cache is still a true
        # record of a finished run, so it answers; with no cache there is
        # nothing to say and the caller must see the failure rather than an
        # empty list that reads like a run which produced no exercises.
        if blob is not None:
            return blob["items"]
        raise
    items = sorted((float(l.split(" ", 1)[0]), l.split(" ", 1)[1].strip())
                   for l in o.strip().splitlines() if l.strip())
    # The cache records how many files existed when it was built. If the
    # listing has grown, it is stale by definition - but an EMPTY listing does
    # not invalidate anything. The archived runs here finished in August 2026
    # and their working trees are gone from any box that reads this repo
    # afterwards, so a `find` matching nothing says the files are absent, not
    # that the run had no exercises. Trusting it would return nothing AND
    # overwrite the committed cache below with {"n_listed": 0, "items": []},
    # destroying the only surviving record of a run that cost hours - which
    # rule 28 says cannot be bought back at any price.
    if blob is not None and (not items or blob.get("n_listed") == len(items)):
        return blob["items"]
    out = []
    for mt, path in items:
        # Same POSIX/WSL split as the listing above, for the same reason.
        cat_cmd = "cat " + json.dumps(path)
        cat = subprocess.run((["wsl", "-e", "bash", "-lc", cat_cmd]
                              if os.name == "nt" else ["bash", "-lc", cat_cmd]),
                             capture_output=True, text=True, timeout=60).stdout
        try:
            r = json.loads(cat)
        except Exception:
            continue
        if isinstance(r, list):
            r = r[-1] if r else {}
        # A ZERO-TOKEN EXERCISE IS A REAL ATTEMPT AND A REAL FAILURE, and it is
        # kept. This used to `continue` past them, which silently deleted work
        # the benchmark had done - and the deletion was ASYMMETRIC. The 2-bit
        # arm had two such exercises (go/robot-simulator, javascript/pig-latin);
        # the 4-bit arm had none. Both failed after 353 s and 334 s having
        # produced nothing at all, so dropping them moved that arm's pass rate
        # from the true 96 of 225 (42.7%) to 96 of 223 (43.0%) and its seconds
        # per case from 72.2 down to 69.8 - flattering, in both directions, the
        # one file under scrutiny. aider's own run summary was right and every
        # figure derived here was the biased one.
        #
        # zero_tokens is flagged rather than dropped so a caller that must
        # divide by tokens can exclude them explicitly and say that it did.
        out.append({"t_end": mt, "dur": r.get("duration", 0.0),
                    "zero_tokens": not r.get("completion_tokens"),
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


# ---------------------------------------------------------------------------
# Run-metadata loader and phrase builders.
#
# Every plot module reads its run conditions through here, so a condition
# is written down in exactly one place and a run that lacks a server log
# says so in the same words everywhere.
# ---------------------------------------------------------------------------

LOGS = os.path.join(ROOT, "results", "qwen38-27b-blind", "logs")

# Cited from campaign.md:1436-1443. These are CITED, not measured on any
# individual run — the bits-per-weight values come from the quantisation
# specification, not from a per-run instrument.
LADDER_BPW = {
    "UD-IQ4_XS": 4.223, "UD-Q3_K_XL": 3.895, "UD-IQ3_XXS": 3.240,
    "UD-Q2_K_XL": 2.912, "UD-IQ2_S": 2.481, "UD-IQ2_XXS": 2.153,
    "UD-IQ1_M": 1.994, "UD-IQ1_S": 1.835,
}

# On-disk sizes recorded in campaign.md:1232-1235. Only files whose size
# was explicitly recorded are here; do not invent one.
# Where campaign.md gives an exact byte count, it goes in LADDER_BYTES.
# Where campaign.md gives only a GiB figure, it goes in LADDER_GIB.
LADDER_BYTES = {
    "UD-IQ4_XS": 14_252_845_984,
}
LADDER_GIB = {
    "UD-Q2_K_XL": 9.154,
    "UD-IQ1_M":   6.267,
    "UD-IQ1_S":   5.767,
}

_TAG_TO_LABEL = {
    "iq4xs": "UD-IQ4_XS", "q2kxl": "UD-Q2_K_XL", "q3kxl": "UD-Q3_K_XL",
    "iq3xxs": "UD-IQ3_XXS", "iq2s": "UD-IQ2_S", "iq2xxs": "UD-IQ2_XXS",
    "iq1m": "UD-IQ1_M", "iq1s": "UD-IQ1_S",
}

_FLAG_PATTERNS = [
    ("ngl", "n_gpu_layers", "-ngl"),
    ("flash_attention", "flash", "-fa"),
    ("type_k", "type_k", "q8_0"),
    ("type_v", "type_v", "q8_0"),
    ("spec_draft_n_max", "spec-draft-n-max", "--spec-draft-n-max"),
    ("spec_draft_p_min", "spec-draft-p-min", "--spec-draft-p-min"),
    ("build", "build", "build"),
]

_FLAG_NAMES = [name for name, _, _ in _FLAG_PATTERNS]


def _label_from_filename(basename):
    """Extract e.g. 'UD-Q2_K_XL' from 'Qwen3.8-27B-UD-Q2_K_XL.gguf'."""
    stem = basename.replace(".gguf", "")
    for suffix in LADDER_BPW:
        if stem.endswith(suffix):
            return suffix
    return None


def _model_id_from_filename(basename):
    """Extract e.g. 'Qwen3.8-27B' from 'Qwen3.8-27B-UD-Q2_K_XL.gguf'."""
    stem = basename.replace(".gguf", "")
    for suffix in LADDER_BPW:
        if stem.endswith(suffix):
            prefix = stem[: -len(suffix)].rstrip("-")
            return prefix if prefix else None
    return None


def _label_from_tag(tag):
    """Infer the model label from a run tag string."""
    tag_lower = tag.lower().replace("-", "").replace("_", "")
    for key, label in _TAG_TO_LABEL.items():
        if key.replace("_", "") in tag_lower:
            return label
    return None


def load_runmeta(tag):
    """Parse the server log for a run tag if it exists.

    Every field is either a value READ FROM THE LOG or None. There are no
    defaults. When the log does not exist, the model label is inferred
    from the tag string and inferred_from_tag is set to True.
    """
    import re

    meta = {
        "model_file": None, "model_label": None, "model_id": None,
        "bpw": None, "model_bytes": None, "model_gb": None,
        "model_gib": None, "ctx_tokens": None, "n_slots": None,
        "drafter": None, "accept_len": None, "accept_len_n": None,
        "flags_recorded": {}, "flags_missing": list(_FLAG_NAMES),
        "log": None, "inferred_from_tag": False,
    }

    logpath = os.path.join(LOGS, "%s-server.log.err" % tag)
    if not os.path.exists(logpath):
        label = _label_from_tag(tag)
        if label:
            meta["model_label"] = label
            meta["bpw"] = LADDER_BPW.get(label)
            if label in LADDER_BYTES:
                meta["model_bytes"] = LADDER_BYTES[label]
                meta["model_gb"] = LADDER_BYTES[label] / 1e9
                meta["model_gib"] = LADDER_BYTES[label] / (1024 ** 3)
            elif label in LADDER_GIB:
                meta["model_gib"] = LADDER_GIB[label]
                meta["model_gb"] = LADDER_GIB[label] * 1.073741824
            meta["inferred_from_tag"] = True
        return meta

    meta["log"] = logpath
    text = io.open(logpath, encoding="utf-8", errors="replace").read()
    lines = text.splitlines()

    # model_file: "load_model: loading model '<path>'"
    m = re.search(r"load_model: loading model '([^']+)'", text)
    if m:
        fullpath = m.group(1).replace("\\", "/")
        basename = fullpath.rsplit("/", 1)[-1]
        meta["model_file"] = basename
        meta["model_label"] = _label_from_filename(basename)
        meta["model_id"] = _model_id_from_filename(basename)

    label = meta["model_label"]
    if label:
        meta["bpw"] = LADDER_BPW.get(label)
        if label in LADDER_BYTES:
            meta["model_bytes"] = LADDER_BYTES[label]
            meta["model_gb"] = LADDER_BYTES[label] / 1e9
            meta["model_gib"] = LADDER_BYTES[label] / (1024 ** 3)
        elif label in LADDER_GIB:
            meta["model_gib"] = LADDER_GIB[label]
            meta["model_gb"] = LADDER_GIB[label] * 1.073741824

    # ctx_tokens and n_slots: "n_slots = N, n_ctx_slot = N"
    m = re.search(r"n_slots\s*=\s*(\d+)", text)
    if m:
        meta["n_slots"] = int(m.group(1))
    m = re.search(r"n_ctx_slot\s*=\s*(\d+)", text)
    if m:
        meta["ctx_tokens"] = int(m.group(1))

    # drafter: presence of "common_speculative_init_result"
    meta["drafter"] = "common_speculative_init_result" in text

    # accept_len: mean of all "mean len = X" values
    means = re.findall(r"mean len\s*=\s*([\d.]+)", text)
    if means:
        vals = [float(v) for v in means]
        meta["accept_len"] = float(np.mean(vals))
        meta["accept_len_n"] = len(vals)

    # flags: search for each known flag pattern
    recorded = {}
    missing = []
    for name, *patterns in _FLAG_PATTERNS:
        found = False
        for pat in patterns:
            if pat in text:
                found = True
                break
        if found:
            recorded[name] = True
        else:
            missing.append(name)
    meta["flags_recorded"] = recorded
    meta["flags_missing"] = missing

    if not meta["model_label"]:
        label = _label_from_tag(tag)
        if label:
            meta["model_label"] = label
            meta["bpw"] = LADDER_BPW.get(label)
            meta["inferred_from_tag"] = True

    return meta


# ---------------------------------------------------------------------------
# Phrase builders. Every plot module calls these so that the same condition
# is stated in the same words everywhere, and degrades in the same words
# when a field is absent.
# ---------------------------------------------------------------------------

def model_phrase(meta):
    """Human sentence naming the model, its provenance, and its bpw."""
    if meta is None:
        return "the model file is not recorded for this run"
    label = meta.get("model_label")
    mid = meta.get("model_id")
    bpw = meta.get("bpw")
    if not label:
        return "the model file is not recorded for this run"
    name = ("%s %s" % (mid, label)) if mid else label
    bpw_s = " at %.3f bits per weight (cited, campaign.md)" % bpw if bpw else ""
    if meta.get("inferred_from_tag"):
        return ("%s%s — inferred from the run tag, because no server log "
                "for this run is committed" % (name, bpw_s))
    return ("%s%s, read from this run's own server log" % (name, bpw_s))


def resident_phrase(meta):
    """On-disk size with unit disambiguation, or a statement that it is unknown."""
    if meta is None:
        return "no on-disk size is recorded for this model file"
    b = meta.get("model_bytes")
    gib_only = meta.get("model_gib")
    if b is not None:
        gb = b / 1e9
        gib = b / (1024 ** 3)
        return ("%.4f decimal GB (derived: {:,} bytes × 1e−9) and "
                "%.3f GiB (derived: {:,} bytes ÷ 1024³) on disk "
                "— the recorded figure is the exact byte count {:,}; "
                "both human-readable forms are derived from it, and the gap "
                "between the two units is about 7 percent"
                .format(b, b, b) % (gb, gib))
    if gib_only is not None:
        gb_derived = gib_only * 1.073741824
        return ("%.3f GiB on disk (recorded in campaign.md at that precision)"
                "; %.4f decimal GB (derived: %.3f GiB × 1.073741824) "
                "— the recorded figure is the GiB value; the decimal-GB "
                "form is derived from it, and the gap between the two units "
                "is about 7 percent" % (gib_only, gb_derived, gib_only))
    return "no on-disk size is recorded for this model file"


def window_phrase(meta):
    """Context window and slot count, or a statement that they are unknown."""
    if meta is None:
        return "the context window is not recorded for this run"
    ctx = meta.get("ctx_tokens")
    ns = meta.get("n_slots")
    if ctx is None:
        return "the context window is not recorded for this run"
    slot_s = ("with %d slot%s (--parallel %d)"
              % (ns, "s" if ns != 1 else "", ns)) if ns else ""
    if meta.get("log"):
        return ("-c {:,}".format(ctx) + (" " + slot_s if slot_s else "")
                + ", read from the server log")
    return ("-c {:,}".format(ctx) + (" " + slot_s if slot_s else "")
            + " — source not recorded")


def drafter_phrase(meta):
    """Drafter status including the run's own mean accepted length."""
    if meta is None or meta.get("drafter") is None:
        return ("MTP speculative decoding status is not recorded for this "
                "run — no server log is committed")
    if not meta["drafter"]:
        return "MTP speculative decoding OFF, read from the server log"
    al = meta.get("accept_len")
    aln = meta.get("accept_len_n")
    if al is not None and aln is not None:
        return ("MTP speculative decoding ON, read from the server log; "
                "mean accepted length — which is how many tokens of the "
                "draft head's guess the full model accepted per attempt, "
                "so a value of 1 would mean speculation bought nothing — "
                "is %.2f, the mean over %d draft-acceptance lines in this "
                "run's own log" % (al, aln))
    return ("MTP speculative decoding ON, read from the server log; "
            "mean accepted length is not recorded for this run")


def conditions(meta, extra=""):
    """Full CONDITIONS clause for a figure caption or footer.

    Always ends with a NOT RECORDED clause listing missing flags,
    or a sentence stating that every flag was recorded.
    """
    parts = [model_phrase(meta)]
    if meta:
        parts.append(resident_phrase(meta))
        parts.append(window_phrase(meta))
        parts.append(drafter_phrase(meta))
    if extra:
        parts.append(extra)

    missing = meta.get("flags_missing", []) if meta else _FLAG_NAMES
    if missing:
        if meta and meta.get("log"):
            parts.append(
                "NOT RECORDED FOR THIS RUN: %s — a server log exists "
                "for this run, but the server was started at a verbosity "
                "that never dumped its parameter block"
                % ", ".join(missing))
        else:
            parts.append(
                "NOT RECORDED FOR THIS RUN: %s — nothing about the "
                "server's parameters is recorded, because no server log "
                "for this run is committed at all; that is a wider absence "
                "than a quiet parameter block"
                % ", ".join(missing))
    else:
        parts.append("every server flag checked was recorded in the log")
    return "CONDITIONS: " + "; ".join(parts) + "."
