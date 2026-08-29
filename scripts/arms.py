#!/usr/bin/env python3
"""One JSON file describes a sweep; one command runs it to completion.

    python scripts/arms.py --arms scripts/arms/spec-sweep.json --list
    python scripts/arms.py --arms scripts/arms/spec-sweep.json --dry-run
    python scripts/arms.py --arms scripts/arms/spec-sweep.json --slug qwen38-27b
    python scripts/arms.py --arms scripts/arms/spec-sweep.json --resume

WHY THIS FILE EXISTS. Thirteen PowerShell sweeps under scripts/reference-3090/
carried the reference campaign, and every one of them is the same program:

    stop any server -> launch llama-server with a flag set -> poll /health
    -> issue one or more probes -> record timings and acceptance -> next arm

They differ only in the flag sets, the prompts, and how many tokens they ask
for. That is data, not code. So here it is data - an ARM FILE, under
scripts/arms/ - and the runner is this one Python file, which runs on Linux,
macOS and Windows. The PowerShell originals do not: that directory's own README
calls them historical artifacts that must never be edited, which left a Linux
clone with no implementation of Stages 2, 3, 6a and 6b at all.

WHAT AN ARM FILE LOOKS LIKE

    {
      "name":   "spec-sweep",
      "models": ["Q4_K_M", "mmproj"],
      "defaults": {"repeat": 1, "discard_first": false,
                   "sampling": {"temperature": 0, "top_k": 1},
                   "probe": {"n_predict": 700}},
      "arms": [
        {"id": "spec-none", "sweep": "spec-sweep",
         "server": {"model": "Q4_K_M",
                    "flags": ["--mmproj", "mmproj", "-c", "122880",
                              "-ngl", "99", "--jinja", "--spec-type", "none"]},
         "probes": [{"id": "rbtree", "prompt": "Write a red-black tree in JS."}]}
      ]
    }

`defaults` fills in anything an arm or a probe leaves out: arm keys (repeat,
discard_first, port, ...) at the arm level, `defaults.probe` at the probe
level, and `defaults.sampling` merged under each arm's own sampling block - so
a file holds its shared settings once.

FLAG LISTS ARE COMPLETE AND SELF-CONTAINED. Whatever an arm lists is what
llama-server receives, in that order. Only --host and --port are added, and
only when absent, because the runner owns the transport (bench.py's Server does
the same). Nothing else is injected: these flag lists were reconstructed from
the .ps1 originals flag for flag, and a runner that "helpfully" adds --jinja or
-ngl would silently be measuring a different server than the one the published
numbers came from. Missing -ngl or -c is WARNED about, loudly, and left alone.

A LOGICAL MODEL NAME may appear inside the flag list - "--mmproj", "mmproj" -
and any flag value that matches an entry in the file's "models" list, or that
follows a model-carrying flag, is resolved through paths.model_path(). No
absolute path ever appears in an arm file, which is what makes one file run on
Windows today and Ubuntu tomorrow.

A probe names its prompt in exactly one of three ways:

    "prompt":       the literal string
    "prompt_file":  a path, read UTF-8 (relative to the arm file, then the repo)
    "filler_notes": N, the deterministic synthetic filler - N notes joined
                    with "\\n" - or {"n": N, "prefix": P, "suffix": S}, which
                    is '\\n'.join([P] + notes + [S])

Any of the three may also be wrapped in probe-level "prefix" / "suffix", and
those concatenate with NO separator of the runner's own - you supply the
newlines, so the prompt is exactly what you wrote. Both spellings reproduce
the PowerShell [string]::Join("`n", header + notes + task); which one a file
uses is checked, not assumed, by the frozen hash below.

A probe may also carry "prompt_chars" / "prompt_sha256". Those are FROZEN
INPUTS (rule 23): every probe that declares them is rendered and hashed before
a single server starts, and a mismatch aborts the run. A prompt that does not
reproduce is not the prompt the published number was measured at, and finding
that out after the sweep is finding it out too late.

THE REQUEST BODY IS EXACTLY WHAT THE ARM FILE DECLARES. No sampler default is
injected, ever. An arm with "sampling": {"temperature": 0, "top_k": 1} is
greedy; an arm with no sampling block inherits the server's own sampler
(--temp 1.0 --top-p 0.95 ...), and that IS the measurement in the effort
sweeps. Injecting a house default would quietly convert one into the other.
"n_predict": -1 means uncapped - llama.cpp generates until the window ends -
and is sent by omitting max_tokens, which is what the .ps1 originals did.

THE FIVE THINGS A HAND-WRITTEN SWEEP FORGETS, and this one cannot:

  LEDGER (rule 28). One JSON line per probe, appended and fsynced the moment
  the probe returns, to results/<slug>/data/arms/<armfile-stem>.jsonl. Never
  buffered to the end of a sweep. The GPQA run that lost ten hours of
  measurement because its results existed only in scrollback is the reason this
  is not optional.

  RESUME. --resume reads that ledger and skips arm/repeat units already
  complete, so a reboot costs at most the arm in flight. It refuses to skip a
  unit whose arm SPEC has changed since it ran (each line carries a spec hash),
  because skipping a changed arm would publish numbers from a configuration
  that no longer exists.

  HEARTBEAT (rule 20). results/<slug>/work/heartbeat.json is rewritten every
  probe. An agent resuming after a session loss reads eleven fields instead of
  three thousand log lines.

  DISCARD (rule 12). The first probe after a server load reads up to 45% low -
  the clocks are still ramping. With "discard_first" it is dropped from the
  summary and STILL written to the ledger, flagged discarded, because a
  discarded probe is a measurement of the ramp and must not vanish.

  ORDER (rule 30). Throughput on the reference rig has two levels ~13% apart
  and nothing recorded predicts which one you get. Arms are therefore compared
  inside ONE sweep - the "sweep" field on each arm names the group, and arms
  from different groups are never summarised together - and with
  "order": "alternate" (the default) the order within a group reverses on every
  second pass, so a position in the sweep cannot masquerade as an effect. The
  order actually used is recorded on every line.

THE FILLER. deep-decode-probe.ps1 and nuance-suite.ps1 both carry the same
deterministic note generator, and the depth numbers this campaign published
were measured at the prompt lengths it produces. filler_notes() below is that
generator, transcribed arithmetic for arithmetic; all seven frozen sha256
values in scripts/arms/depth-series.json reproduce from it. Changing any
constant in it silently relabels every published depth number.

WHAT THIS DOES NOT DO. It does not score answers (that is bench.py, which the
"bench_arms" in an arm file are for), it does not walk a data-dependent stop
rule, and it does not decide anything: it runs the arms it is given, records
the order it ran them in, and writes down what happened. The parse check after
the first probe is the one exception - it stops a sweep whose server does not
report the timings the ledger needs, before the expensive part (rule 25: cheap
probes buy the map).

ON REUSING bench.py's Server CLASS. Its health poll and its gpu_lock.serve()
launch are COPIED here rather than imported. bench.Server builds a FIXED argv
(-c / -ngl / --parallel / --jinja) and writes to a fixed log path under
scripts/bench/results/, and an arm runner's whole job is an arbitrary per-arm
flag list and a per-arm log; importing it would also drag in datasets_io and
render_table, and therefore Pillow, for a class with three methods. The launch
still goes through gpu_lock.serve(), so rule 20 holds identically.
"""

import argparse
import datetime
import hashlib
import json
import os
import socket
import subprocess
import sys
import threading
import time

import requests

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(_HERE, "bench"), _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from lib import paths
except ImportError as _e:
    sys.exit("scripts/lib/paths.py could not be imported (%s).\n"
             "Every path in this repo resolves through it, and there is no "
             "fallback on purpose: a guessed model path measures the wrong "
             "file and says nothing about it." % _e)
import gpu_lock

# progress must stay visible when stdout is redirected: a multi-hour sweep with
# fully buffered output is indistinguishable from a hung one
try:
    sys.stdout.reconfigure(line_buffering=True)
except AttributeError:
    pass

DEFAULT_PORT = 1234
DEFAULT_HEALTH_TIMEOUT_S = 600      # bench.py Server.wait_ready
DEFAULT_REQUEST_TIMEOUT_S = 3600    # a 27k-depth probe is minutes, not seconds
DEFAULT_STOP_GRACE_S = 3            # every reference sweep waits 3 s after a kill
DEFAULT_SETTLE_S = 0                # q2-vs-q4-headtohead.py waits 5 s after a discard
VRAM_SAMPLE_S = 2.0                 # nvidia-smi cadence while a probe runs

# Keys `defaults` may set at the ARM level, and at the PROBE level. They are
# disjoint on purpose: "repeat" is a property of an arm, "temperature" is a
# property of a request, and a file that says {"repeat": 1, "temperature": 0}
# means both, at their own levels.
ARM_KEYS = ("repeat", "discard_first", "port", "host", "health_timeout_s",
            "request_timeout_s", "stop_grace_s", "settle_s", "slug", "sweep")
SAMPLER_KEYS = ("temperature", "top_k", "top_p", "min_p", "typical_p",
                "presence_penalty", "frequency_penalty", "repeat_penalty",
                "repeat_last_n", "dynatemp_range", "dynatemp_exponent", "seed")
PROBE_KEYS = ("n_predict", "prefix", "suffix") + SAMPLER_KEYS

# Probe keys that are commentary, not configuration: a change to one of these
# must not read as "the arm changed" and force a completed unit to rerun.
PROSE_KEYS = ("note", "notes", "derived_from", "comment")

# Flags whose value is a weight file, so it resolves like server.model even
# when the arm file names it logically ("--mmproj", "mmproj").
MODEL_FLAGS = ("--mmproj", "-md", "--model-draft", "--mmproj-file")

# The timings fields the ledger is built on. Without them the sweep is
# recording nothing usable and should stop before it costs hours (rule 25).
REQUIRED_TIMINGS = ("prompt_n", "predicted_n", "prompt_ms", "predicted_ms",
                    "predicted_per_second")

# subprocess text kwargs: on Windows bare text=True decodes the child as cp1252,
# and one UTF-8 byte in the child's output kills the reader (bench.py:77)
_TEXT = dict(text=True, encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# The deterministic filler
# ---------------------------------------------------------------------------

def filler_notes(n):
    """The synthetic note block from deep-decode-probe.ps1 / nuance-suite.ps1.

    Transcribed from:

        $frag = [Convert]::ToString((($i * 48271) % 1048573), 16)
        'Note ' + $i + ': subsystem alpha-' + (($i * 7) % 97) + ...

    [Convert]::ToString(x, 16) renders lowercase hex with no prefix and no zero
    padding, which is exactly format(x, "x"); every operand here is
    non-negative, so PowerShell's % and Python's % agree on every value. Lines
    are joined with a bare LF - the PowerShell source joins on "`n", not CRLF.
    i is 1-BASED.

    DO NOT "improve" any constant. Published depth numbers are indexed by the
    prompt lengths this produces, so a changed constant relabels them silently.
    All seven prompt_sha256 values frozen in scripts/arms/depth-series.json -
    themselves taken by running the PowerShell original - reproduce from this
    function.
    """
    if n < 0:
        raise ValueError("filler_notes: n must be >= 0, got %r" % (n,))
    out = []
    for i in range(1, n + 1):
        frag = format((i * 48271) % 1048573, "x")
        out.append(
            "Note %d: subsystem alpha-%d reported latency %d ms on shard %d, "
            "retry budget %d, digest fragment %s, remark: threshold crossed "
            "only when the moving median over window %d exceeded baseline by "
            "%d percent."
            % (i, (i * 7) % 97, (17 * i) % 993, i % 13, (3 * i) % 29, frag,
               (5 * i) % 47, (11 * i) % 83))
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def _safe(name):
    """A filename component that survives every filesystem we target."""
    return "".join(c if (c.isalnum() or c in "-_.") else "-" for c in str(name))


def _fail(msg):
    raise SystemExit("arms.py: " + msg)


def _flag_present(flags, *names):
    return any(f in names for f in flags)


# ---------------------------------------------------------------------------
# Arm file -> plan
# ---------------------------------------------------------------------------

def load_arm_file(path):
    """Read and validate an arm file. Returns (spec, merged_arms)."""
    if not os.path.exists(path):
        _fail("arm file not found: %s" % path)
    try:
        with open(path, encoding="utf-8-sig") as fh:
            spec = json.load(fh)
    except ValueError as e:
        _fail("arm file %s is not valid JSON: %s" % (path, e))
    if not isinstance(spec, dict):
        _fail("arm file %s must be a JSON object with an \"arms\" list" % path)
    arms = spec.get("arms")
    if not isinstance(arms, list) or not arms:
        _fail("arm file %s has no \"arms\" list" % path)
    defaults = spec.get("defaults") or {}
    if not isinstance(defaults, dict):
        _fail("\"defaults\" must be an object in %s" % path)

    merged, seen = [], set()
    for i, arm in enumerate(arms):
        if not isinstance(arm, dict):
            _fail("arms[%d] in %s is not an object" % (i, path))
        m = merge_arm(defaults, arm, i, path)
        if m["id"] in seen:
            _fail("duplicate arm id %r in %s - ids key the ledger and the "
                  "resume index, so they have to be unique" % (m["id"], path))
        seen.add(m["id"])
        merged.append(m)
    return spec, merged


def merge_arm(defaults, arm, index, path):
    """defaults + one arm -> one fully resolved arm dict."""
    out = {}
    for key in ARM_KEYS:
        if key in arm:
            out[key] = arm[key]
        elif key in defaults:
            out[key] = defaults[key]

    out["id"] = str(arm.get("id") or "").strip()
    if not out["id"]:
        _fail("arms[%d] in %s has no \"id\"" % (index, path))

    d_server = defaults.get("server") or {}
    a_server = arm.get("server") or {}
    if not isinstance(d_server, dict) or not isinstance(a_server, dict):
        _fail("\"server\" must be an object (arm %r)" % out["id"])
    model = a_server.get("model") or d_server.get("model")
    if not model:
        _fail("arm %r has no server.model, and defaults.server.model is unset"
              % out["id"])
    # defaults first, arm last. Reference arm files carry COMPLETE flag lists
    # and inherit nothing, which is the safe shape; this only matters for a
    # file that chooses to factor its shared flags into defaults.
    flags = list(d_server.get("flags") or []) + list(a_server.get("flags") or [])
    for f in flags:
        if not isinstance(f, (str, int, float)):
            _fail("arm %r has a non-scalar flag %r; flags are a flat list, "
                  "exactly as llama-server would receive them" % (out["id"], f))
    out["server"] = {"model": model, "flags": [str(f) for f in flags]}

    probes = arm.get("probes") or defaults.get("probes")
    if not isinstance(probes, list) or not probes:
        _fail("arm %r has no probes (and defaults.probes is unset)" % out["id"])
    # `defaults.probe` is the current shape; flat probe keys in `defaults` are
    # tolerated because earlier arm files wrote them that way.
    probe_defaults = {k: defaults[k] for k in PROBE_KEYS if k in defaults}
    probe_defaults.update(defaults.get("probe") or {})
    resolved, pseen = [], set()
    for j, p in enumerate(probes):
        if not isinstance(p, dict):
            _fail("arm %r probes[%d] is not an object" % (out["id"], j))
        q = dict(probe_defaults)
        q.update(p)
        q["id"] = str(q.get("id") or "p%d" % j)
        if q["id"] in pseen:
            _fail("arm %r has two probes with id %r" % (out["id"], q["id"]))
        pseen.add(q["id"])
        srcs = [k for k in ("prompt", "prompt_file", "filler_notes") if k in q]
        if len(srcs) != 1:
            _fail("arm %r probe %r needs exactly one of prompt / prompt_file / "
                  "filler_notes (found %s)"
                  % (out["id"], q["id"], ", ".join(srcs) or "none"))
        if "filler_notes" in q and filler_n(q) is None:
            _fail("arm %r probe %r: filler_notes must be a note count - an "
                  "integer >= 0, or an object with an integer \"n\""
                  % (out["id"], q["id"]))
        n = q.get("n_predict")
        # -1 is the .ps1 originals' uncapped request: llama.cpp generates until
        # the window ends. 0 is not a request, it is a typo.
        if not isinstance(n, int) or isinstance(n, bool) or n == 0 or n < -1:
            _fail("arm %r probe %r needs an integer n_predict: a positive cap, "
                  "or -1 for uncapped. The cap is a condition every number "
                  "travels with (rule 3)." % (out["id"], q["id"]))
        resolved.append(q)
    out["probes"] = resolved

    out.setdefault("repeat", 1)
    if not isinstance(out["repeat"], int) or out["repeat"] < 1:
        _fail("arm %r: repeat must be an integer >= 1" % out["id"])
    out.setdefault("discard_first", False)
    out.setdefault("port", DEFAULT_PORT)
    out.setdefault("host", "127.0.0.1")
    out.setdefault("health_timeout_s", DEFAULT_HEALTH_TIMEOUT_S)
    out.setdefault("request_timeout_s", DEFAULT_REQUEST_TIMEOUT_S)
    out.setdefault("stop_grace_s", DEFAULT_STOP_GRACE_S)
    out.setdefault("settle_s", DEFAULT_SETTLE_S)
    out.setdefault("sweep", "")
    # sampling MERGES rather than replaces, so a file can put the shared
    # greedy pair in defaults and let one arm add to it. An absent or empty
    # sampling block means the request carries no sampler at all and the
    # server's own flags apply - which is the measurement in the effort arms.
    sampling = dict(defaults.get("sampling") or {})
    sampling.update(arm.get("sampling") or {})
    out["sampling"] = sampling
    return out


def filler_n(probe):
    """The note count a probe asks for, or None if it is not a valid one.

    Accepts "filler_notes": 60 (the current shape) and the earlier
    {"n": 60, "prefix": ..., "suffix": ...} object, so an arm file written
    against either revision still runs.
    """
    fn = probe.get("filler_notes")
    if isinstance(fn, bool):
        return None
    if isinstance(fn, int):
        return fn if fn >= 0 else None
    if isinstance(fn, dict) and isinstance(fn.get("n"), int) \
            and not isinstance(fn.get("n"), bool) and fn["n"] >= 0:
        return fn["n"]
    return None


def arm_warnings(arm):
    """Conditions worth shouting about, without touching the flag list.

    The flag lists in scripts/arms/*.json were reconstructed from the .ps1
    originals flag for flag; silently adding to one would measure a different
    server than the published number came from. So these are warnings, printed
    in the plan and recorded in the ledger, and nothing more.
    """
    flags, w = arm["server"]["flags"], []
    if not _flag_present(flags, "-ngl", "--n-gpu-layers", "--gpu-layers"):
        w.append("no -ngl in the flag list: llama.cpp counts the output "
                 "projection as layer n+1, so anything short of -ngl 99 leaves "
                 "it on the CPU without saying so (rule 15)")
    if not _flag_present(flags, "-c", "--ctx-size"):
        w.append("no -c in the flag list: the window falls back to llama.cpp's "
                 "own default, and a deep probe then truncates silently")
    if arm["discard_first"] and len(arm["probes"]) == 1:
        w.append("discard_first with a single probe: every probe this arm "
                 "takes is the ramp probe, so the arm contributes NO kept "
                 "reading. Add a second probe, or set discard_first false and "
                 "say in the writeup that the reading is a cold one (rule 12)")
    return w


def spec_hash(arm):
    """Fingerprint of everything about an arm that could move a number.

    Resume compares this against the ledger. If the arm file was edited after a
    unit ran, the recorded numbers describe a configuration that no longer
    exists, and skipping the unit would republish them as if they described
    this one.
    """
    payload = {"id": arm["id"], "server": arm["server"],
               "sampling": arm["sampling"],
               "probes": [{k: v for k, v in p.items() if k not in PROSE_KEYS}
                          for p in arm["probes"]]}
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def build_plan(arms, order_mode):
    """[{rep, arm, group, order, pos}] - the sweep, pass by pass.

    Rule 30: arms are compared INSIDE one sweep, so the outer loop is the
    repeat and the inner loop is the arms - never the other way round - and the
    arms of one "sweep" group stay together. With "alternate", every second
    pass runs a group backwards, so an arm's POSITION cannot be mistaken for a
    property of the arm.
    """
    if order_mode not in ("alternate", "fixed"):
        _fail("order must be \"alternate\" or \"fixed\", got %r" % (order_mode,))
    groups, seen = [], {}
    for a in arms:
        g = a.get("sweep") or "(ungrouped)"
        if g not in seen:
            seen[g] = len(groups)
            groups.append((g, []))
        groups[seen[g]][1].append(a)

    units = []
    for rep in range(1, max(a["repeat"] for a in arms) + 1):
        for gname, members in groups:
            run = [a for a in members if a["repeat"] >= rep]
            if not run:
                continue
            if order_mode == "alternate" and rep % 2 == 0:
                run = list(reversed(run))
            ids = [a["id"] for a in run]
            for pos, arm in enumerate(run):
                units.append({"rep": rep, "arm": arm, "group": gname,
                              "order": ids, "pos": pos})
    return units


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

def render_prompt(probe, arm_file_dir):
    """(prompt_text, source_label) for one probe spec.

    Both reproduce the PowerShell [string]::Join("`n", header + notes + task),
    and each is self-consistent about where the newlines live:

      "filler_notes": {"n": N, "prefix": P, "suffix": S}
          '\\n'.join([P] + notes + [S]), absent parts omitted from the join.
          P and S carry no newlines of their own; the join supplies them.

      probe-level "prefix" / "suffix"
          concatenated with NO separator of the runner's own, so P ends in a
          newline and S starts with one. You supply them, and the prompt is
          exactly what you wrote.

    Anything else would be a guess about somebody's intent. The prompt_sha256
    on the depth probes is what proves the rule applied was the right one.
    """
    if "prompt" in probe:
        body, src = str(probe["prompt"]), "prompt"
    elif "filler_notes" in probe:
        n = filler_n(probe)
        body, src = filler_notes(n), "filler_notes:%d" % n
        fn = probe["filler_notes"]
        if isinstance(fn, dict):
            parts = ([str(fn["prefix"])] if fn.get("prefix") else [])
            parts.append(body)
            if fn.get("suffix"):
                parts.append(str(fn["suffix"]))
            body = "\n".join(parts)
    else:
        rel = str(probe["prompt_file"])
        cands = ([rel] if os.path.isabs(rel) else
                 [os.path.join(arm_file_dir, rel),
                  os.path.join(paths.repo_root(), rel)])
        for c in cands:
            if os.path.isfile(c):
                with open(c, encoding="utf-8") as fh:
                    body = fh.read()
                src = "prompt_file:%s" % os.path.abspath(c)
                break
        else:
            _fail("probe %r: prompt_file %r not found (looked in %s)"
                  % (probe["id"], rel, " and ".join(cands)))
    return (str(probe.get("prefix") or "") + body
            + str(probe.get("suffix") or "")), src


def frozen_problems(probe, text):
    """Rule 23: does the rendered prompt still match what was frozen?"""
    out = []
    want_n = probe.get("prompt_chars")
    if isinstance(want_n, int) and len(text) != want_n:
        out.append("prompt_chars %d, rendered %d" % (want_n, len(text)))
    want_sha = probe.get("prompt_sha256")
    if want_sha:
        got = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if got != want_sha:
            out.append("prompt_sha256 %s, rendered %s" % (want_sha, got))
    return out


def check_frozen_prompts(arms, arm_file_dir):
    """Render every probe once, before anything is launched, and verify it.

    Cheap (a few hundred milliseconds for the whole depth ladder) and it buys
    the whole map: a prompt that no longer reproduces is not the prompt the
    published number was measured at, and a sweep is the wrong place to find
    that out.
    """
    bad, checked = [], 0
    for a in arms:
        for p in a["probes"]:
            text, _ = render_prompt(p, arm_file_dir)
            if "prompt_sha256" in p or "prompt_chars" in p:
                checked += 1
                for prob in frozen_problems(p, text):
                    bad.append("%s / %s: %s" % (a["id"], p["id"], prob))
    if bad:
        _fail("FROZEN PROMPT MISMATCH (rule 23) - these prompts are not the "
              "ones the arm file froze:\n  " + "\n  ".join(bad) +
              "\nA prompt that does not reproduce is a different experiment. "
              "Fix the generator or re-freeze the file deliberately; do not "
              "run the sweep.")
    return checked


# ---------------------------------------------------------------------------
# The server: launch, health, stop. Copied from bench.py's Server - see the
# module docstring for why it is copied rather than imported.
# ---------------------------------------------------------------------------

def resolve_flags(flags, model_names, slug):
    """Flag list with logical model names resolved to real paths.

    "--mmproj", "mmproj" is how an arm file names a projector without writing
    an absolute path into a file that has to run on two operating systems.
    """
    out, subs, prev = [], [], None
    for tok in flags:
        is_model = (prev in MODEL_FLAGS or
                    (tok in model_names and prev is not None
                     and prev.startswith("-")))
        if is_model:
            real = paths.model_path(tok, slug)
            out.append(real)
            subs.append((tok, real))
        else:
            out.append(tok)
        prev = tok
    return out, subs


def build_argv(server_bin, model_path_, flags, arm):
    """The exact command line. Only the transport is ours.

    --host / --port are added when absent because the runner owns the port it
    polls; the arm files drop them for exactly that reason. Nothing else is
    added - see arm_warnings() for what is said instead.
    """
    injected = []
    if not _flag_present(flags, "--host"):
        injected += ["--host", str(arm["host"])]
    if not _flag_present(flags, "--port"):
        injected += ["--port", str(arm["port"])]
    return [server_bin, "-m", model_path_] + list(flags) + injected, injected


def port_occupied(host, port, timeout_s=1.0):
    """Is something already listening there?

    Found by this file's own selftest, and it is the worst class of bug this
    runner can have. A server left behind by a crashed sweep - or any other
    tool holding the port - answers /health instantly, so wait_ready() returns
    "healthy in 0 s", every probe goes to THAT server, and the ledger records
    the readings under THIS arm's flags. The numbers look perfect and describe
    a configuration that was never loaded.

    gpu_lock.acquire() already refuses when a foreign process NAMED
    llama-server is alive, which catches the common case. This catches the rest
    - an orphan under a different name, a tunnel, an LM Studio - by asking the
    only question that actually matters: can anything accept a connection on
    the port we are about to serve on?
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout_s)
    try:
        return s.connect_ex((host, int(port))) == 0
    except OSError:
        return False
    finally:
        s.close()


def wait_ready(proc, base_url, timeout_s):
    """Poll /health until it says ok. Raises RuntimeError if it never does."""
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if proc.poll() is not None:
            raise RuntimeError("llama-server exited with code %s after %.0f s"
                               % (proc.returncode, time.time() - t0))
        try:
            r = requests.get(base_url + "/health", timeout=3)
            if r.ok and r.json().get("status") == "ok":
                return time.time() - t0
        except (requests.RequestException, ValueError):
            pass
        time.sleep(2)
    raise RuntimeError("llama-server did not become healthy in %d s" % timeout_s)


def stop_server(proc, grace_s, host=None, port=None, release_timeout_s=60):
    """Stop the server and wait until the port it held is actually free.

    Waiting on the PORT rather than sleeping a fixed number of seconds is the
    difference between a sweep that continues and one that aborts: the next
    arm refuses to launch into an occupied port (see port_occupied), so a
    server that takes a few seconds longer than usual to let go would otherwise
    kill the whole run. The grace sleep still happens on top, because VRAM is
    not free the instant the process is gone and the next arm loads into
    whatever is left.
    """
    if proc is not None:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    pass
    if host is not None and port is not None:
        deadline = time.time() + release_timeout_s
        while time.time() < deadline and port_occupied(host, port, 0.25):
            time.sleep(0.5)
    time.sleep(grace_s)


def log_tail(path, n=30):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return [ln.rstrip("\n") for ln in fh.readlines()[-n:]]
    except OSError:
        return []


# ---------------------------------------------------------------------------
# VRAM, sampled WHILE the probe runs
# ---------------------------------------------------------------------------

def gpu_used_mib():
    """Dedicated VRAM in use, or None on a box without nvidia-smi."""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=memory.used",
                            "--format=csv,noheader,nounits"],
                           capture_output=True, timeout=15, **_TEXT)
        if r.returncode == 0 and r.stdout.strip():
            return int(r.stdout.strip().splitlines()[0].strip())
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return None


class VramSampler(object):
    """Samples VRAM for the life of one probe. Rule 28: during, not after.

    ctx-limit-sweep.ps1 read nvidia-smi beside every rung, and the ceiling work
    in rule 13 is built on those readings. Peak matters more than the resting
    value, because the KV cache grows through prefill - so this samples while
    the request is in flight and reports the peak alongside the count of
    samples that produced it. Entirely best effort: on a machine with no
    nvidia-smi it records nothing and says so by being null.
    """

    def __init__(self, period_s=VRAM_SAMPLE_S):
        self.period_s = period_s
        self.samples = []
        self._stop = threading.Event()
        self._thread = None

    def __enter__(self):
        first = gpu_used_mib()
        if first is None:
            return self          # no nvidia-smi: stay silent, cost nothing
        self.samples.append(first)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def _loop(self):
        while not self._stop.wait(self.period_s):
            v = gpu_used_mib()
            if v is not None:
                self.samples.append(v)

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=20)
        return False

    def result(self):
        if not self.samples:
            return None
        return {"peak_mib": max(self.samples), "first_mib": self.samples[0],
                "last_mib": self.samples[-1], "n": len(self.samples),
                "sampled": "during the probe, every %.0f s" % self.period_s}


# ---------------------------------------------------------------------------
# One probe
# ---------------------------------------------------------------------------

def probe_body(probe, prompt, arm_sampling):
    """The request body, carrying exactly what the arm file declared.

    No sampler default is added, ever. A probe whose arm names no sampler
    inherits the server's own (--temp 1.0 --top-p 0.95 ... in the effort arms),
    and THAT is the measurement; injecting a house default would silently
    convert it into a greedy one. n_predict -1 is sent by OMITTING max_tokens,
    which is what the .ps1 originals did and what llama.cpp reads as "until the
    window ends".

    Precedence, least to most specific: the arm's sampling block, then any
    sampler key written directly on the probe, then the probe's own sampling
    block.
    """
    body = {"messages": [{"role": "user", "content": prompt}], "stream": False}
    if probe["n_predict"] > 0:
        body["max_tokens"] = probe["n_predict"]
    body.update(arm_sampling or {})
    for k in SAMPLER_KEYS:
        if k in probe:
            body[k] = probe[k]
    body.update(probe.get("sampling") or {})
    return body


def run_probe(base_url, body, timeout_s):
    r = requests.post(base_url + "/v1/chat/completions", json=body,
                      timeout=timeout_s)
    r.raise_for_status()
    return r.json()


def drafting(timings):
    """Rule 11's drafting PAIR, with the counter formula rule 11 names.

    Each verify pass emits one non-drafted token, so

        passes            = predicted_n - draft_n_accepted
        accepted_per_pass = draft_n_accepted / passes   <- mean draft length
        drafted_per_pass  = draft_n / passes

    Acceptance alone is the wrong quantity: two rows reading 100% and 99%
    acceptance ran 3.96 vs 10.54 accepted per target pass. Both go in the
    ledger, always, and so does the formula that produced them.
    """
    dn = timings.get("draft_n")
    da = timings.get("draft_n_accepted")
    pn = timings.get("predicted_n")
    if not dn or da is None or pn is None:
        return {}
    passes = pn - da
    out = {"draft_n": dn, "draft_n_accepted": da,
           "acceptance": round(da / dn, 4),
           "verify_passes": passes,
           "formula": "accepted_per_pass = draft_n_accepted / "
                      "(predicted_n - draft_n_accepted)"}
    if passes > 0:
        out["accepted_per_pass"] = round(da / passes, 3)
        out["drafted_per_pass"] = round(dn / passes, 3)
    return out


def parse_check(body):
    """Does this response carry what the ledger is built on? (rule 25)"""
    t = body.get("timings")
    if not isinstance(t, dict):
        return ["the response has no \"timings\" object at all"]
    return ["timings.%s missing" % k
            for k in REQUIRED_TIMINGS if t.get(k) is None]


# ---------------------------------------------------------------------------
# Ledger, heartbeat
# ---------------------------------------------------------------------------

def append_ledger(path, rec):
    """One line, written and FSYNCED before anything else happens (rule 28).

    Buffering is what loses runs. A field not written down during the run
    cannot be recovered at any price, and being certain costs one short append
    against a probe that took seconds to minutes.
    """
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def write_heartbeat(path, rec):
    """Rewritten every probe, atomically. Rule 20's 'where is it now'."""
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(rec, fh, indent=2, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except OSError as e:
        # never take the run down with the status file
        sys.stderr.write("arms.py: heartbeat write failed: %s\n" % e)


def read_ledger(path):
    """{(arm, rep): {probes: set, spec: sha, failed: bool}} from the ledger."""
    done = {}
    if not os.path.exists(path):
        return done
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                # a torn last line is what a crash mid-append looks like; the
                # unit it belonged to simply reruns
                continue
            kind = rec.get("kind")
            if kind not in ("probe", "arm_failed"):
                continue
            key = (rec.get("arm"), rec.get("rep"))
            slot = done.setdefault(key, {"probes": set(), "spec": None,
                                         "failed": False})
            slot["spec"] = rec.get("spec_sha") or slot["spec"]
            if kind == "arm_failed":
                slot["failed"] = True
            else:
                # The ledger is append-ordered, so a probe recorded AFTER a
                # failure means the arm was retried and produced data. Without
                # this, `failed` is sticky: an arm that failed once and
                # succeeded on the rerun stays marked failed forever and
                # --resume refuses to count it. Observed 2026-08-29 on the
                # first Linux run, where every arm failed under RLIMIT_AS and
                # then succeeded once that was gated off.
                slot["failed"] = False
                slot["probes"].add(rec.get("probe_index"))
    return done


# ---------------------------------------------------------------------------
# Printing
# ---------------------------------------------------------------------------

def _probe_source(p):
    if "prompt" in p:
        return "prompt"
    if "filler_notes" in p:
        return "filler_notes n=%d" % filler_n(p)
    return "prompt_file=%s" % p["prompt_file"]


def _cap(p):
    return "uncapped" if p["n_predict"] < 0 else str(p["n_predict"])


def print_listing(spec, arms, order_mode):
    print("sweep file : %s" % (spec.get("name") or "(unnamed)"))
    print("order      : %s%s"
          % (order_mode,
             "  (order within a sweep group reverses on every second pass, "
             "rule 30)" if order_mode == "alternate" else
             "  (file order, kept - correct for a ladder whose walk depends "
             "on it; rule 30 wants alternate wherever arms are COMPARED)"))
    print("arms       : %d" % len(arms))
    total = 0
    for a in arms:
        total += len(a["probes"]) * a["repeat"]
        print("\n  %-30s sweep %-22s repeat %d  discard_first %s"
              % (a["id"], a["sweep"] or "(ungrouped)", a["repeat"],
                 str(a["discard_first"]).lower()))
        print("    model  : %s" % a["server"]["model"])
        print("    flags  : %s" % (" ".join(a["server"]["flags"]) or "(none)"))
        for p in a["probes"]:
            print("    probe  : %-20s %-26s n_predict %s"
                  % (p["id"], _probe_source(p), _cap(p)))
        for w in arm_warnings(a):
            print("    WARNING: %s" % w)
    print("\ntotal probes: %d" % total)


def print_plan(units, resolved, ledger_path, hb_path, slug, arm_dir, checked):
    print("slug       : %s" % slug)
    print("ledger     : %s" % ledger_path)
    print("heartbeat  : %s" % hb_path)
    print("frozen     : %d probe(s) carry prompt_sha256/prompt_chars, all "
          "reproduced" % checked)
    print("units      : %d arm loads, %d probes\n"
          % (len(units), sum(len(u["arm"]["probes"]) for u in units)))
    for k, u in enumerate(units):
        arm = u["arm"]
        r = resolved[arm["id"]]
        print("--- [%d/%d] sweep %s, pass %d, position %d of %s"
              % (k + 1, len(units), u["group"], u["rep"], u["pos"] + 1,
                 " -> ".join(u["order"])))
        print("    arm      : %s   (spec %s)" % (arm["id"], spec_hash(arm)))
        if r.get("error"):
            print("    UNRESOLVED: %s" % r["error"])
        else:
            print("    model    : %s" % r["model_path"])
            for logical, real in r["model_subs"]:
                print("    flag arg : %s -> %s" % (logical, real))
            print("    argv     : %s" % " ".join(r["argv"]))
            if r["injected"]:
                print("    injected : %s   (the runner owns the transport)"
                      % " ".join(r["injected"]))
        for j, p in enumerate(arm["probes"]):
            text, src = render_prompt(p, arm_dir)
            mark = (" DISCARDED (rule 12)"
                    if (j == 0 and arm["discard_first"]) else "")
            print("    probe %d  : %-20s %-24s %d chars, n_predict %s%s"
                  % (j + 1, p["id"], src, len(text), _cap(p), mark))
            body = probe_body(p, "", arm["sampling"])
            body.pop("messages", None)
            print("               request %s" % json.dumps(body, sort_keys=True))
        for w in arm_warnings(arm):
            print("    WARNING  : %s" % w)


def print_summary(rows):
    """Grouped by sweep, because rule 30 forbids comparing across them."""
    if not rows:
        return
    print("\n--- summary (kept probes only; rule 30: compare INSIDE a sweep, "
          "never across) ---")
    # dict.fromkeys, not set(): the printing order is the order the arms ran
    for group in dict.fromkeys(r["group"] for r in rows):
        here = [r for r in rows if r["group"] == group]
        print("\nsweep %s" % group)
        for arm in dict.fromkeys(r["arm"] for r in here):
            mine = [r for r in here if r["arm"] == arm]
            for probe in dict.fromkeys(r["probe"] for r in mine):
                same = [r for r in mine if r["probe"] == probe]
                kept = [r for r in same if not r["discarded"] and r["tps"]]
                drop = sum(1 for r in same if r["discarded"])
                if not kept:
                    print("  %-30s %-20s no kept reading%s"
                          % (arm, probe, " (%d discarded)" % drop if drop else ""))
                    continue
                tps = [r["tps"] for r in kept]
                depth = kept[0]["depth"]
                print("  %-30s %-20s %6.2f t/s  n=%d  depth %s%s"
                      % (arm, probe, sum(tps) / len(tps), len(tps), depth,
                         "  (%d discarded)" % drop if drop else ""))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def resolve_slug(explicit, spec, arms):
    if explicit:
        return str(explicit)
    for src in [spec, spec.get("defaults") or {}] + arms:
        if src.get("slug"):
            return str(src["slug"])
    slug = (paths.load_campaign() or {}).get("slug")
    if slug:
        return str(slug)
    # campaign.json need not carry its own slug, but the directory it lives in
    # IS the slug; if exactly one campaign is present, that is not a guess.
    res = os.path.join(paths.repo_root(), "results")
    found = []
    if os.path.isdir(res):
        found = [d for d in sorted(os.listdir(res))
                 if os.path.isfile(os.path.join(res, d, "campaign.json"))
                 or os.path.isfile(os.path.join(res, d, "campaign.md"))]
    if len(found) == 1:
        return found[0]
    _fail("no campaign slug: pass --slug, or put \"slug\" in the arm file, or "
          "add it to results/<slug>/campaign.json%s"
          % (" (candidates: %s)" % ", ".join(found) if found else ""))


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arms", required=True, metavar="FILE",
                    help="the arm file: an object with \"arms\", and "
                         "optionally \"name\", \"models\", \"order\" and "
                         "\"defaults\"")
    ap.add_argument("--slug", default=None,
                    help="campaign slug; default: the arm file's slug, then "
                         "campaign.json, then the one campaign under results/")
    ap.add_argument("--resume", action="store_true",
                    help="skip arm/repeat units the ledger already records as "
                         "complete, and print which ones were skipped")
    ap.add_argument("--only", metavar="ID", default=None,
                    help="run just this arm id - what a raised-cap rerun and a "
                         "data-dependent ladder walk both need")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the full plan - every arm, its resolved model "
                         "path, its full argv, every probe - and touch nothing")
    ap.add_argument("--list", action="store_true",
                    help="list the arms and probes in the file and exit; "
                         "resolves no paths, so it runs anywhere")
    args = ap.parse_args()

    spec, arms = load_arm_file(args.arms)
    order_mode = (spec.get("order")
                  or (spec.get("defaults") or {}).get("order") or "alternate")

    if args.only:
        arms = [a for a in arms if a["id"] == args.only]
        if not arms:
            _fail("--only %r matches no arm in %s" % (args.only, args.arms))

    if args.list:
        print_listing(spec, arms, order_mode)
        return 0

    # A dry run must never take the GPU. gpu_lock refuses outright under this
    # variable, which turns "the plan accidentally launched something" from a
    # wasted hour into a stack trace.
    if args.dry_run:
        os.environ.setdefault(gpu_lock.DRY_RUN_ENV, "1")
    elif os.environ.get(gpu_lock.DRY_RUN_ENV):
        _fail("%s is set in the environment but --dry-run was not passed. "
              "Every launch would raise DryRunViolation partway through the "
              "sweep. Pass --dry-run, or unset the variable deliberately."
              % gpu_lock.DRY_RUN_ENV)

    slug = resolve_slug(args.slug, spec, arms)
    stem = os.path.splitext(os.path.basename(args.arms))[0]
    root = paths.repo_root()
    arm_dir = os.path.dirname(os.path.abspath(args.arms))
    data_dir = os.path.join(root, "results", slug, "data", "arms")
    work_dir = os.path.join(root, "results", slug, "work", "arms", _safe(stem))
    ledger_path = os.path.join(data_dir, stem + ".jsonl")
    hb_path = os.path.join(root, "results", slug, "work", "heartbeat.json")

    units = build_plan(arms, order_mode)
    # rule 23, before anything expensive: every frozen prompt still reproduces
    checked = check_frozen_prompts(arms, arm_dir)

    model_names = set(spec.get("models") or [])

    # Resolve every binary and model BEFORE the first launch: an arm file with
    # a typo in arm nine should fail in the first second, not eight arms in.
    resolved, unresolved = {}, 0
    for a in arms:
        rec = {}
        try:
            server_bin = paths.llama_bin("llama-server")
            model_path_ = paths.model_path(a["server"]["model"], slug)
            flags, subs = resolve_flags(a["server"]["flags"], model_names, slug)
            rec["server_bin"] = server_bin
            rec["model_path"] = model_path_
            rec["model_subs"] = subs
            rec["flags_resolved"] = flags
            rec["argv"], rec["injected"] = build_argv(server_bin, model_path_,
                                                      flags, a)
        except SystemExit as e:
            # In a dry run this is information, not a stop: print the whole
            # plan, mark what could not be resolved, exit non-zero at the end.
            if not args.dry_run:
                raise
            rec["error"] = str(e)
            unresolved += 1
        resolved[a["id"]] = rec

    if args.dry_run:
        print_plan(units, resolved, ledger_path, hb_path, slug, arm_dir, checked)
        print("\nDRY RUN: nothing was launched and nothing was written.")
        if unresolved:
            print("%d arm(s) could not be resolved - see UNRESOLVED above."
                  % unresolved)
            return 2
        return 0

    for d in (data_dir, work_dir, os.path.dirname(hb_path)):
        os.makedirs(d, exist_ok=True)

    already = read_ledger(ledger_path) if args.resume else {}
    total_probes = sum(len(u["arm"]["probes"]) for u in units)
    started = _iso()
    done_probes = 0        # progress: counts skipped and failed units too, so
                           # the heartbeat fraction still reaches its total
    probes_written = 0     # probe records actually appended to the ledger
    failed_arms, summary_rows = [], []
    parse_checked = False
    file_name = spec.get("name") or stem

    try:
        machine = paths.load_machine(slug)
    except SystemExit as e:
        machine = {"error": str(e)}

    # Take the lock BEFORE writing a sweep_start line, so a sweep that never
    # started leaves no record claiming it did. acquire() is idempotent, so the
    # guard below simply adopts this one and still releases it at the end.
    # Caught rather than raised: an operator who collides with another job
    # needs the holder's name and one command, not a stack trace.
    try:
        gpu_lock.acquire("arms:%s" % stem)
    except gpu_lock.GpuBusy as e:
        print("cannot start: %s" % e)
        print("\nNothing was launched and the ledger was not touched. When the "
              "other job is done, re-run this exact command with --resume.")
        return 2

    append_ledger(ledger_path, {
        "kind": "sweep_start", "ts": started, "slug": slug,
        "armfile": stem, "armfile_name": file_name,
        "armfile_path": os.path.abspath(args.arms), "order_mode": order_mode,
        "plan": [{"rep": u["rep"], "sweep": u["group"], "order": u["order"]}
                 for u in units if u["pos"] == 0],
        "arms": [{"id": a["id"], "sweep": a["sweep"], "spec_sha": spec_hash(a),
                  "model": a["server"]["model"], "flags": a["server"]["flags"],
                  "repeat": a["repeat"], "discard_first": a["discard_first"],
                  "warnings": arm_warnings(a)} for a in arms],
        "frozen_prompts_verified": checked,
        "resume": bool(args.resume), "only": args.only,
        "pid": os.getpid(), "argv": sys.argv,
        # rule 3: the conditions travel with the numbers, in the same file
        "machine": machine,
    })

    print("sweep file %s: %d arms, %d loads, %d probes -> %s"
          % (file_name, len(arms), len(units), total_probes, ledger_path))
    print("%d frozen prompt(s) verified against the arm file (rule 23)"
          % checked)
    for a in arms:
        for w in arm_warnings(a):
            print("WARNING [%s]: %s" % (a["id"], w))

    with gpu_lock.guard("arms:%s" % stem):
        for k, unit in enumerate(units):
            arm, rep = unit["arm"], unit["rep"]
            r = resolved[arm["id"]]
            sha = spec_hash(arm)
            prior = already.get((arm["id"], rep))
            if prior is not None:
                if prior["spec"] and prior["spec"] != sha:
                    print("[%d/%d] %s pass %d: in the ledger, but the arm SPEC "
                          "CHANGED (%s -> %s) - rerunning"
                          % (k + 1, len(units), arm["id"], rep, prior["spec"],
                             sha))
                elif prior["failed"]:
                    print("[%d/%d] %s pass %d: SKIPPED, the ledger records it "
                          "FAILED (delete that line to retry it)"
                          % (k + 1, len(units), arm["id"], rep))
                    failed_arms.append("%s/pass%d (previously)"
                                       % (arm["id"], rep))
                    done_probes += len(arm["probes"])
                    continue
                elif len(prior["probes"]) >= len(arm["probes"]):
                    print("[%d/%d] %s pass %d: SKIPPED, already complete "
                          "(%d probes in the ledger)"
                          % (k + 1, len(units), arm["id"], rep,
                             len(prior["probes"])))
                    done_probes += len(arm["probes"])
                    continue

            base_url = "http://%s:%s" % (arm["host"], arm["port"])
            log_path = os.path.join(work_dir, "%s-rep%d.log"
                                    % (_safe(arm["id"]), rep))
            common = {
                "slug": slug, "sweep": unit["group"], "armfile": stem,
                "arm": arm["id"], "spec_sha": sha, "rep": rep,
                "order": unit["order"], "pos": unit["pos"],
                "order_mode": order_mode, "model": arm["server"]["model"],
                "model_path": r["model_path"], "server_bin": r["server_bin"],
                "flags": arm["server"]["flags"],
                "flags_resolved": r["flags_resolved"], "argv": r["argv"],
                "injected_flags": r["injected"], "port": arm["port"],
                "server_log": log_path,
            }

            print("\n[%d/%d] arm %s, sweep %s, pass %d (position %d of %d: %s)"
                  % (k + 1, len(units), arm["id"], unit["group"], rep,
                     unit["pos"] + 1, len(unit["order"]),
                     " -> ".join(unit["order"])))
            print("       %s" % " ".join(r["argv"]))

            # Nothing may already be listening there. See port_occupied():
            # probing a leftover server records perfect-looking numbers under
            # the wrong flags, and no later check can tell that it happened.
            if port_occupied(arm["host"], arm["port"]):
                append_ledger(ledger_path, dict(
                    common, kind="sweep_aborted", ts=_iso(),
                    error="port %s:%s was already serving before this arm "
                          "launched" % (arm["host"], arm["port"])))
                print("\nPORT %s:%s IS ALREADY IN USE, before this arm "
                      "launched anything." % (arm["host"], arm["port"]))
                print("Whatever is listening would answer every probe, and the "
                      "ledger would record ITS numbers under %s's flags. That "
                      "is unrecoverable after the fact, so the sweep stops "
                      "here." % arm["id"])
                print("  python scripts/bench/gpu_lock.py status    "
                      "# see who holds the card")
                print("  python scripts/bench/gpu_lock.py kill      "
                      "# stop a leftover server, then re-run with --resume")
                return 2

            proc, logfh = None, None
            try:
                logfh = open(log_path, "w", encoding="utf-8", errors="replace")
                proc = gpu_lock.serve(r["argv"],
                                      tag="arms:%s:%s" % (stem, arm["id"]),
                                      stdout=logfh, stderr=subprocess.STDOUT)
                load_s = wait_ready(proc, base_url, arm["health_timeout_s"])
                print("       healthy in %.0f s" % load_s)
            except (RuntimeError, gpu_lock.GpuBusy, OSError) as e:
                # An arm that will not load is a RESULT, not a reason to stop
                # and wait for a human. Record it, with the server's own last
                # words, and move to the next arm. (ctx-ceiling.json's stop
                # rule reads exactly this: a rung that never loads is over the
                # limit.)
                stop_server(proc, arm["stop_grace_s"], arm["host"], arm["port"])
                if logfh:
                    logfh.close()
                tail = log_tail(log_path)
                append_ledger(ledger_path, dict(
                    common, kind="arm_failed", ts=_iso(), error=str(e),
                    server_log_tail=tail))
                print("       ARM FAILED: %s" % e)
                for ln in tail[-8:]:
                    print("         | %s" % ln)
                failed_arms.append("%s/pass%d" % (arm["id"], rep))
                done_probes += len(arm["probes"])
                write_heartbeat(hb_path, {
                    "pid": os.getpid(), "arm": arm["id"], "probe": None,
                    "started_utc": started, "updated_utc": _iso(),
                    "done": done_probes, "total": total_probes, "rep": rep,
                    "sweep": unit["group"], "ledger": ledger_path,
                    "state": "arm_failed"})
                continue

            try:
                for j, p in enumerate(arm["probes"]):
                    text, src = render_prompt(p, arm_dir)
                    discarded = (j == 0 and arm["discard_first"])
                    body = probe_body(p, text, arm["sampling"])
                    request = {kk: vv for kk, vv in body.items()
                               if kk != "messages"}
                    write_heartbeat(hb_path, {
                        "pid": os.getpid(), "arm": arm["id"], "probe": p["id"],
                        "started_utc": started, "updated_utc": _iso(),
                        "done": done_probes, "total": total_probes, "rep": rep,
                        "sweep": unit["group"], "ledger": ledger_path,
                        "state": "running"})
                    t0 = time.time()
                    try:
                        with VramSampler() as vram:
                            resp = run_probe(base_url, body,
                                             arm["request_timeout_s"])
                    except (requests.RequestException, ValueError) as e:
                        elapsed = round(time.time() - t0, 2)
                        append_ledger(ledger_path, dict(
                            common, kind="probe_failed", ts=_iso(),
                            probe=p["id"], probe_index=j, discarded=discarded,
                            n_predict=p["n_predict"], prompt_source=src,
                            prompt_chars=len(text), request=request,
                            elapsed_s=elapsed, error=str(e)))
                        print("       probe %s FAILED after %.1f s: %s"
                              % (p["id"], elapsed, e))
                        if proc.poll() is not None:
                            raise RuntimeError(
                                "llama-server died during probe %s (exit %s)"
                                % (p["id"], proc.returncode))
                        continue
                    elapsed = round(time.time() - t0, 2)

                    if not parse_checked:
                        # rule 25: the map is bought here, once, for the price
                        # of one probe - before the other loads happen.
                        problems = parse_check(resp)
                        parse_checked = True
                        if problems:
                            append_ledger(ledger_path, dict(
                                common, kind="parse_check_failed", ts=_iso(),
                                probe=p["id"], probe_index=j,
                                problems=problems,
                                response_keys=sorted(resp.keys()),
                                timings=resp.get("timings")))
                            stop_server(proc, arm["stop_grace_s"], arm["host"], arm["port"])
                            logfh.close()
                            print("\nPARSE CHECK FAILED on the first probe:")
                            for pr in problems:
                                print("  - %s" % pr)
                            print("The ledger is built on those fields. "
                                  "Recording %d more probes without them "
                                  "produces a file that looks like measurement "
                                  "and is not, so this stops here (rule 25)."
                                  % (total_probes - 1))
                            return 2
                        print("       parse check OK: timings carries %s"
                              % ", ".join(REQUIRED_TIMINGS))

                    t = resp.get("timings") or {}
                    choice = (resp.get("choices") or [{}])[0]
                    content = (choice.get("message") or {}).get("content") or ""
                    finish = choice.get("finish_reason")
                    rec = dict(
                        common, kind="probe", ts=_iso(), probe=p["id"],
                        probe_index=j, discarded=discarded,
                        n_predict=p["n_predict"], prompt_source=src,
                        prompt_chars=len(text),
                        prompt_sha256=p.get("prompt_sha256"),
                        request=request, timings=t, drafting=drafting(t),
                        usage=resp.get("usage"), vram=vram.result(),
                        finish_reason=finish, response_chars=len(content),
                        elapsed_s=elapsed,
                        # rule 7: a truncation is a condition, not a footnote
                        truncated=(finish == "length"))
                    append_ledger(ledger_path, rec)
                    done_probes += 1
                    probes_written += 1
                    summary_rows.append({
                        "group": unit["group"], "arm": arm["id"],
                        "probe": p["id"], "discarded": discarded,
                        "tps": t.get("predicted_per_second"),
                        "depth": t.get("prompt_n")})
                    write_heartbeat(hb_path, {
                        "pid": os.getpid(), "arm": arm["id"], "probe": p["id"],
                        "started_utc": started, "updated_utc": _iso(),
                        "done": done_probes, "total": total_probes, "rep": rep,
                        "sweep": unit["group"], "ledger": ledger_path,
                        "state": "ok"})
                    d = rec["drafting"]
                    acc = ("  accept %.3f  acc/pass %s"
                           % (d["acceptance"], d.get("accepted_per_pass"))
                           if d else "")
                    v = rec["vram"]
                    print("       probe %-20s depth %-7s %6.2f t/s  "
                          "prefill %s t/s%s%s%s"
                          % (p["id"], t.get("prompt_n"),
                             t.get("predicted_per_second") or 0.0,
                             round(t.get("prompt_per_second") or 0.0, 1), acc,
                             "  vram %d MiB" % v["peak_mib"] if v else "",
                             "  [DISCARDED, rule 12]" if discarded else ""))
                    if rec["truncated"]:
                        print("       NOTE: finish_reason=length - this probe "
                              "TRUNCATED at its cap (rule 7: raise the cap and "
                              "rerun this arm, never filter it out)")
                    if discarded and arm["settle_s"]:
                        time.sleep(arm["settle_s"])
            except RuntimeError as e:
                append_ledger(ledger_path, dict(
                    common, kind="arm_failed", ts=_iso(), error=str(e),
                    server_log_tail=log_tail(log_path)))
                print("       ARM FAILED mid-probe: %s" % e)
                failed_arms.append("%s/pass%d" % (arm["id"], rep))
            finally:
                stop_server(proc, arm["stop_grace_s"], arm["host"], arm["port"])
                if logfh:
                    logfh.close()

    write_heartbeat(hb_path, {
        "pid": os.getpid(), "arm": None, "probe": None,
        "started_utc": started, "updated_utc": _iso(),
        "done": done_probes, "total": total_probes, "rep": None,
        "sweep": None, "ledger": ledger_path, "state": "finished"})
    append_ledger(ledger_path, {
        "kind": "sweep_end", "ts": _iso(), "slug": slug, "armfile": stem,
        "probes_recorded": probes_written, "probes_planned": total_probes,
        "failed": failed_arms})

    print_summary(summary_rows)
    print("\n%d probe record(s) written of %d planned -> %s"
          % (probes_written, total_probes, ledger_path))
    if failed_arms:
        print("FAILED arms: %s" % ", ".join(failed_arms))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
