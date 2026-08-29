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

RUNGS COME FROM THE PLAN WHEN THE LADDER IS NOT A FIXED EXPERIMENT. A context
ceiling is a property of <this file + this card>, so a ladder of -c values
written into an arm file is a ladder for somebody else's machine. An arm may
therefore carry a "rungs" object in place of a literal -c, and is then a
TEMPLATE: the runner expands it into one arm per rung out of
results/<slug>/plan.json, which scripts/plan-campaign.py derives from the GGUF
header, machine.json and the KV arithmetic.

    {"id": "q4km-c{rung.c}", "sweep": "q4km-ceiling",
     "rungs": {"from": "plan", "file": "Q4_K_M"},
     "server": {"model": "Q4_K_M",
                "flags": ["-c", "{rung.c}", "-ngl", "99", "--jinja"]},
     "probes": [{"id": "rbtree", "prompt": "...", "n_predict": 400}]}

"file" is the plan's label for the weight file - the <label> in
results/<slug>/model-<label>.json - and defaults to the arm's own server.model,
because both are the same quant label by construction. "{rung.KEY}" is
substituted wherever a string appears in the arm: the id, a flag, a probe
prompt, an n_predict. KEY is any field of the plan's rung record - c, zone,
deep_fill_tokens, above_predicted_ceiling - plus index, of and file. A string
that is EXACTLY one placeholder takes the VALUE'S TYPE, so
"n_predict": "{rung.deep_fill_tokens}" is an integer cap and not a string; a
placeholder inside a longer string is interpolated as text, which is what an id
template wants. The expanded arms come out in ascending -c, so a ladder walk
under "order": "fixed" runs bottom-up as its stop rule expects.

THERE IS NO FALLBACK, and that is the entire point. An arm file that names a
rung source and finds no plan.json ABORTS, naming the command that writes one.
Falling back to a hardcoded value is exactly how a ladder sized for one 27B on
one 24 GB card gets run against a 1.7B whose whole 40,960-token window sits
below the ladder's bottom rung - and the ledger would record those readings as
if the ladder had been derived for that model.

WHAT THE LEDGER RECORDS ABOUT IT (rules 3 and 28). Every probe line carries
ctx_size - the -c actually in the argv, parsed back out of it - and ctx_source,
one of "plan", "literal" or "none". A plan-driven line also carries the whole
rung record and the plan it came from, and the sweep_start line carries the
plan's path, slug, generation time and step rule. A window is a condition, and
a condition that exists only inside a flags array is one grep away from being
lost.

WHEN A LITERAL -c IS RIGHT, AND WHAT HAPPENS THEN. A depth series at
1.5k/28k/91k, an effort sweep at rule 21's frozen cap, a speculative-decoding
grid held at one window - those -c values are part of a fixed experiment, and a
runner that rewrote them would be running a different one. So it does not touch
them. It does CHECK them: when a plan is present, a literal -c above the
model's own trained context_length, or above the plan's predicted ceiling for
that file, is warned about in the listing, in the plan, on the sweep_start line
and in the console. Loud, recorded, and never silently changed.

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

THE SIX THINGS A HAND-WRITTEN SWEEP FORGETS, and this one cannot:

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

  RESPONSES (rule 28, and METHODOLOGY's artifact read-back). Every generated
  body is written verbatim to <ledger-stem>-responses/, named by arm, pass and
  probe so it joins back to its ledger line, and the line carries the path.
  ON by default; --no-save-responses turns it off. A ledger that records
  response_chars and throws the text away can say how MUCH was generated and
  nothing about WHAT: no reasoning-appetite count, no blind judging, nothing
  for the repetition detector to read, no "max coherent output" column - and
  no way to notice a probe that spent its whole budget thinking and copied
  nothing, which is the correction that cost this campaign the most.

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
import re
import socket
import subprocess
import sys
import textwrap
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

# The DERIVED ladder, written by scripts/plan-campaign.py from the GGUF header
# and machine.json. "from": "plan" is spelled out in the arm file rather than
# assumed, so a second source one day is a new VALUE and not a new shape.
PLAN_FILE = "plan.json"
PLAN_WRITER = "scripts/plan-campaign.py"
MODEL_WRITER = "scripts/inspect-model.py"
RUNG_SOURCES = ("plan",)
RUNG_RE = re.compile(r"\{rung\.([A-Za-z_][A-Za-z0-9_]*)\}")
CTX_FLAGS = ("-c", "--ctx-size")

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


def _wrap(text, width=72, indent=""):
    return [indent + ln for ln in textwrap.wrap(str(text or ""), width)] or []


def raw_ctx(flags):
    """The token the flag list puts after -c, or None if it names no window."""
    for i in range(len(flags) - 1):
        if flags[i] in CTX_FLAGS:
            return str(flags[i + 1])
    return None


def ctx_size(flags):
    """The -c actually in this flag list, or None if it names no window.

    Read back OUT of the flag list rather than remembered from wherever the
    value came from, so the ledger records the window the server was actually
    given (rule 3) whether it was a literal, a plan rung, or absent.
    """
    tok = raw_ctx(flags)
    try:
        return int(tok)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Rungs from the campaign plan
#
# A -c ladder is a property of <this weight file + this card>, not of the
# experiment, so scripts/plan-campaign.py derives one per model file and this
# is where an arm file spends it. Everything below either produces a concrete
# ladder or refuses in a way that names the command that would fix it: there is
# no path through this section that ends in a guessed window.
# ---------------------------------------------------------------------------

def _rel(path):
    """Repo-relative when it can be, absolute when it cannot.

    os.path.relpath RAISES on Windows across drives, and --plan pointing at a
    file on another volume is an ordinary thing to do. A path that cannot be
    made relative is still a perfectly good path.
    """
    try:
        return os.path.relpath(path, paths.repo_root()).replace(os.sep, "/")
    except ValueError:
        return os.path.abspath(path).replace(os.sep, "/")


def default_plan_path(slug):
    return os.path.join(paths.repo_root(), "results", str(slug), PLAN_FILE)


def load_plan(slug, explicit=None):
    """(plan, path, why_not). Never raises - the caller decides how loud.

    Absence is fatal for an arm file that NAMES a rung source and merely
    informative for one that does not, and only the caller knows which, so
    this reports rather than exits. Every rejection carries the reason in the
    words a fix would be written in.
    """
    path = explicit or default_plan_path(slug)
    if not os.path.isfile(path):
        return None, path, "there is no such file"
    try:
        with open(path, encoding="utf-8-sig") as fh:
            plan = json.load(fh)
    except (OSError, ValueError) as e:
        return None, path, "%s: %s" % (type(e).__name__, e)
    if not isinstance(plan, dict):
        return None, path, "it is not a JSON object"
    got = plan.get("slug")
    if got and slug and str(got) != str(slug):
        # The guard that makes --plan safe. A ladder derived for one model on
        # one card is not a ladder for another, and a plan pointed at the
        # wrong campaign is precisely the 27B-ladder-on-a-1.7B accident with
        # an extra step.
        return None, path, ("it is the plan for campaign %r and this sweep is "
                            "campaign %r - a ladder derived for one model on "
                            "one card is not a ladder for another"
                            % (str(got), str(slug)))
    per_file = (plan.get("rungs") or {}).get("per_file")
    if not isinstance(per_file, list):
        return None, path, ("it carries no rungs.per_file list, so %s never "
                            "got as far as deriving a ladder (its own "
                            "verdict: %s)"
                            % (PLAN_WRITER, plan.get("verdict") or "not recorded"))
    return plan, path, None


def plan_record(plan, label):
    """The plan's rung record for one model label, or None."""
    if not plan:
        return None
    for rec in (plan.get("rungs") or {}).get("per_file") or []:
        if isinstance(rec, dict) and str(rec.get("file")) == str(label):
            return rec
    return None


def plan_labels(plan):
    return [str(r.get("file"))
            for r in (plan.get("rungs") or {}).get("per_file") or []
            if isinstance(r, dict)]


def no_plan_message(arm_id, arm_file, slug, path, why):
    """Why the sweep stopped, and the exact command that unblocks it."""
    return (
        "arm %r in %s takes its -c values from the campaign plan, and no "
        "usable plan was found.\n"
        "  looked at  : %s\n"
        "  because    : %s\n"
        "Write one - it needs the model's own GGUF header and this machine:\n"
        "  python %s --slug %s --repo <org>/<repo>-GGUF --quant <LABEL>   "
        "# only if results/%s/model-<LABEL>.json is missing\n"
        "  python %s --slug %s\n"
        "There is deliberately NO fallback to a hardcoded ladder. A -c ladder "
        "belongs to one weight file on one card; run another model's ladder "
        "and the sweep measures windows this model has never had, while the "
        "ledger records the readings as though the ladder had been derived "
        "for it (rule 1: measured, cited or labeled-derived - a borrowed "
        "ladder is none of the three)."
        % (arm_id, arm_file, path, why,
           MODEL_WRITER, slug, slug, PLAN_WRITER, slug))


def _rung_value(key, values, where):
    if key not in values:
        _fail("%s: {rung.%s} is not a field of the plan's rung record. "
              "This plan offers: %s"
              % (where, key, ", ".join(sorted(values))))
    return values[key]


def _subst(obj, values, where):
    """{rung.KEY} -> the plan's value, wherever a string appears in the arm.

    A string that is EXACTLY one placeholder takes the value's TYPE, so
    ["-c", "{rung.c}"] becomes ["-c", 122880] (merge_arm stringifies flags
    anyway) and "n_predict": "{rung.deep_fill_tokens}" is an integer cap that
    passes merge_arm's integer check. A placeholder inside a longer string is
    interpolated as text, which is what "q4km-c{rung.c}" wants.

    Exact-token matching, not str.format(): a flag list here legitimately
    contains {"reasoning_effort":"low"}, and format() would explode on it.
    """
    if isinstance(obj, str):
        m = RUNG_RE.fullmatch(obj)
        if m:
            return _rung_value(m.group(1), values, where)
        return RUNG_RE.sub(
            lambda mo: str(_rung_value(mo.group(1), values, where)), obj)
    if isinstance(obj, list):
        return [_subst(v, values, where) for v in obj]
    if isinstance(obj, dict):
        return dict((k, _subst(v, values, where)) for k, v in obj.items())
    return obj


def expand_rungs(raw_arms, plan, plan_path, arm_file):
    """Template arms -> one concrete arm per plan rung. (arms, ladders).

    Arms that name no rung source pass through untouched, so a file may mix a
    derived ladder with fixed arms. `ladders` is what --list, --dry-run and
    the sweep_start line print and record: the resolved rungs, the plan's own
    reason for them, and the reference ladder they replaced.
    """
    out, ladders = [], []
    rel = _rel(plan_path)
    for arm in raw_arms:
        src = arm.get("rungs") if isinstance(arm, dict) else None
        if not src:
            out.append(arm)
            continue
        arm_id = arm.get("id")
        where = "arm %r in %s" % (arm_id, arm_file)
        if not isinstance(src, dict):
            _fail("%s: \"rungs\" must be an object, e.g. "
                  "{\"from\": \"plan\", \"file\": \"Q4_K_M\"}" % where)
        frm = str(src.get("from") or "plan")
        if frm not in RUNG_SOURCES:
            _fail("%s: \"rungs\".from is %r; the only source is %s"
                  % (where, frm, " or ".join(repr(s) for s in RUNG_SOURCES)))
        label = src.get("file") or (arm.get("server") or {}).get("model")
        if not label:
            _fail("%s: \"rungs\" names no \"file\" and the arm has no "
                  "server.model to take the plan label from" % where)
        rec = plan_record(plan, label)
        if rec is None:
            _fail("%s: wants rungs for plan file %r, and %s has none. It "
                  "holds: %s.\nEither this campaign inspected a different "
                  "quant, or \"rungs\".file names the wrong label. Re-run "
                  "%s for %r, then %s."
                  % (where, str(label), rel, ", ".join(plan_labels(plan))
                     or "(nothing)", MODEL_WRITER, str(label), PLAN_WRITER))
        rungs = [r for r in (rec.get("rungs") or []) if isinstance(r, dict)]
        if not rungs:
            _fail("%s: %s derives NO rungs for %r, and gives this reason:\n"
                  "  %s\nThat is an answer about this machine, not a bug - "
                  "but there is nothing for this sweep to run, so it stops "
                  "here rather than inventing a window."
                  % (where, rel, str(label), rec.get("why") or "none recorded"))
        if len(rungs) > 1 and "{rung." not in str(arm_id or ""):
            _fail("%s: expands to %d arms and its id carries no {rung.*} "
                  "placeholder, so every one of them would be called %r. Arm "
                  "ids key the ledger and the resume index - put {rung.c} in "
                  "the id." % (where, len(rungs), arm_id))
        for i, r in enumerate(rungs):
            values = dict(r)
            values.update({"file": str(label), "index": i + 1,
                           "of": len(rungs)})
            body = dict((k, v) for k, v in arm.items() if k != "rungs")
            concrete = _subst(body, values, where)
            # Provenance rides on the arm itself so the ledger can copy it
            # onto every line the arm produces (rules 3 and 28). It is NOT in
            # spec_hash(): the -c is already in the flag list, and rehashing
            # the plan's metadata would force a completed sweep to rerun every
            # time plan-campaign.py is re-run with the same numbers.
            concrete["_rung"] = {
                "source": "plan", "plan": rel, "plan_file": str(label),
                "template": arm_id, "index": i + 1, "of": len(rungs),
                "c": r.get("c"), "zone": r.get("zone"),
                "deep_fill_tokens": r.get("deep_fill_tokens"),
                "above_predicted_ceiling": r.get("above_predicted_ceiling"),
                "predicted_ceiling": rec.get("predicted_ceiling"),
                "predicted_ceiling_drafter_off":
                    rec.get("predicted_ceiling_drafter_off"),
                "model_context_length": rec.get("model_context_length"),
                "cache_type": rec.get("cache_type"),
                "quantum": rec.get("quantum"),
            }
            out.append(concrete)
        ladders.append({
            "template": arm_id, "plan": rel, "plan_file": str(label),
            "c": [r.get("c") for r in rungs],
            "zones": [r.get("zone") for r in rungs],
            "deep_fill_tokens": [r.get("deep_fill_tokens") for r in rungs],
            "predicted_ceiling": rec.get("predicted_ceiling"),
            "model_context_length": rec.get("model_context_length"),
            "cache_type": rec.get("cache_type"),
            "collapse_point_reachable": rec.get("collapse_point_reachable"),
            "why": rec.get("why"),
            # Documentation, carried as DATA so it can be compared instead of
            # believed: the literal ladder this template replaced.
            "reference_rungs": src.get("reference_rungs"),
        })
    return out, ladders


# ---------------------------------------------------------------------------
# Arm file -> plan
# ---------------------------------------------------------------------------

def read_arm_file(path):
    """The arm file as written: (spec, raw arms). Nothing merged, nothing
    expanded - rung templates are still templates here, because resolving one
    needs the campaign slug and the slug is resolved from this same spec."""
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
    if not isinstance(spec.get("defaults") or {}, dict):
        _fail("\"defaults\" must be an object in %s" % path)
    return spec, arms


def merge_arms(spec, arms, path):
    """defaults + each (already expanded) arm -> the fully resolved list."""
    defaults = spec.get("defaults") or {}
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
    return merged


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
    # Set by expand_rungs(); carried through so every ledger line this arm
    # produces can say which rung of which plan it is (rules 3 and 28).
    if arm.get("_rung"):
        out["_rung"] = arm["_rung"]
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


def arm_warnings(arm, plan=None):
    """Conditions worth shouting about, without touching the flag list.

    The flag lists in scripts/arms/*.json were reconstructed from the .ps1
    originals flag for flag; silently adding to one would measure a different
    server than the published number came from. So these are warnings, printed
    in the plan and recorded in the ledger, and nothing more.

    With a plan in hand the same restraint applies to a LITERAL -c. A depth
    series or a frozen effort suite names its window on purpose, and rewriting
    it would run a different experiment - but a window above the model's own
    trained context_length, or above what the card can hold, is a fact the
    operator has to be told before the hours are spent, not after.
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
    if plan is not None and not arm.get("_rung"):
        c = ctx_size(flags)
        rec = plan_record(plan, arm["server"]["model"])
        window = (rec or {}).get("model_context_length")
        ceiling = (rec or {}).get("predicted_ceiling")
        if c and window and c > window:
            w.append("-c %d is ABOVE this model's own trained window (%d, "
                     "from the GGUF header via %s). llama.cpp does not refuse "
                     "that, it rope-scales, so the arm would measure "
                     "extrapolation rather than the model - and the window is "
                     "a condition every number here travels with (rule 3). "
                     "The value is left exactly as the arm file wrote it: it "
                     "is part of a fixed experiment and only a deliberate "
                     "re-freeze may change it." % (c, window, PLAN_FILE))
        elif c and ceiling and c > ceiling:
            w.append("-c %d is above the plan's predicted ceiling for %s (%s "
                     "tokens at %s KV, %s). The arithmetic says this window "
                     "does not fit on this card, so expect this arm to fail "
                     "to load or to spill - which is a RESULT the ledger "
                     "records, not a reason to change the flag"
                     % (c, arm["server"]["model"], ceiling,
                        (rec or {}).get("cache_type"), PLAN_FILE))
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


RESPONSES_SUFFIX = "-responses"


def response_name(arm_id, rep, probe_index, probe_id, ext=".txt"):
    """arm / pass / probe in the filename, so a file joins back to its line.

    The ledger's own key for a probe is (arm, rep, probe_index, probe) and this
    is that tuple, in that order, filesystem-safe. Sorting the directory sorts
    the sweep.
    """
    return "%s__rep%d__%02d-%s%s" % (_safe(arm_id), rep, probe_index,
                                     _safe(probe_id), ext)


def save_response(dir_path, name, text):
    """Write one generated body VERBATIM. Returns (relative path, error|None).

    Verbatim, and not "prettified": the repetition detector, the blind judge
    and any max-coherent-output measurement read this file and are entitled to
    the model's characters rather than the runner's. An EMPTY body still gets
    its file - a zero-byte file next to a line saying finish_reason=stop is
    the empty-answer shape METHODOLOGY names, and it is only nameable because
    something was written.

    A failure here never kills the sweep: the probe already happened and its
    numbers are real. It is reported on the record instead, so a missing file
    is a fact in the ledger rather than a silence.
    """
    path = os.path.join(dir_path, name)
    try:
        os.makedirs(dir_path, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
    except OSError as e:
        return None, "%s: %s" % (type(e).__name__, e)
    return "%s/%s" % (os.path.basename(dir_path), name), None


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


def ctx_source(arm):
    """"plan", "literal" or "none" - where this arm's window came from."""
    if arm.get("_rung"):
        return "plan"
    return "literal" if ctx_size(arm["server"]["flags"]) is not None else "none"


def _ctx_line(arm):
    """The window and its origin, in the one line rule 3 wants beside it."""
    flags = arm["server"]["flags"]
    c, src, tok = ctx_size(flags), ctx_source(arm), raw_ctx(flags)
    if src == "none" and tok is not None:
        # Only reachable in --list / --dry-run: the plan could not be read, so
        # the template was never expanded and this is still the placeholder.
        return "%s   (UNEXPANDED - see the UNRESOLVED rungs above)" % tok
    if src == "none":
        return ("NONE in the flag list - llama.cpp's own default applies and a "
                "deep probe truncates silently")
    if src == "literal":
        return "%s   (literal, written in the arm file)" % c
    r = arm["_rung"]
    return ("%s   (plan rung %s of %s, zone %s, from rungs.per_file[%s]; "
            "predicted ceiling %s, model window %s, %s KV)"
            % (c, r["index"], r["of"], r["zone"], r["plan_file"],
               r["predicted_ceiling"], r["model_context_length"],
               r["cache_type"]))


def print_ladders(ladders, plan, plan_path):
    """The resolved -c ladder, before any hours are committed.

    An agent about to spend a Stage-2 evening on a ceiling hunt should be able
    to read the whole ladder, the arithmetic that produced it, and the plan
    file it came from, off one screen - and see immediately when this machine's
    ladder is not the one the arm file was reconstructed from.
    """
    if not ladders:
        return
    rel = _rel(plan_path)
    print("plan       : %s" % rel)
    print("             generated %s by %s; %s KV; budget %s MiB"
          % (plan.get("generated_utc"), plan.get("generated_by"),
             plan.get("cache_type"),
             (plan.get("machine") or {}).get("budget_mib")))
    for lad in ladders:
        print("\n  ladder %s  <- rungs.per_file[%s]"
              % (lad["template"], lad["plan_file"]))
        print("    %d rung(s), %s KV: %s"
              % (len(lad["c"]), lad["cache_type"],
                 ", ".join("%s (%s)" % (c, z)
                           for c, z in zip(lad["c"], lad["zones"]))))
        print("    predicted ceiling %s   model window %s   collapse point "
              "reachable: %s"
              % (lad["predicted_ceiling"], lad["model_context_length"],
                 lad["collapse_point_reachable"]))
        for line in _wrap(lad["why"], 74, "    "):
            print(line)
        ref = lad.get("reference_rungs")
        if ref:
            # Compared as text: reference_rungs is hand-written in an arm
            # file, and a comparison that can raise on somebody's typo would
            # take down a --dry-run whose whole job is to be safe.
            same = [str(x) for x in ref] == [str(c) for c in lad["c"]]
            print("    reference ladder: %s"
                  % ("REPRODUCED exactly - this machine derives the ladder "
                     "the reference campaign ran"
                     if same else
                     "DIFFERENT. The reference campaign ran %d rungs (%s ... "
                     "%s); this machine derives %d. Numbers from the two are "
                     "not arm-for-arm comparable (rule 30)."
                     % (len(ref), ref[0], ref[-1], len(lad["c"]))))


def print_unresolved(spec, raw_arms, order_mode, problem):
    """What --list and --dry-run print when the ladder cannot be resolved.

    The templates are NOT run through merge_arm here. An unexpanded template
    still has "{rung.c}" where its window goes, and validating that as if it
    were an arm produces a complaint about a placeholder instead of the one
    fact that matters: there is no plan. So the file is described as it was
    written, and the actionable message is the last thing on screen.
    """
    print("sweep file : %s" % (spec.get("name") or "(unnamed)"))
    print("order      : %s" % order_mode)
    print("arms       : %d as written, of which %d take their -c from the plan"
          % (len(raw_arms),
             sum(1 for a in raw_arms if isinstance(a, dict) and a.get("rungs"))))
    for a in raw_arms:
        if not isinstance(a, dict):
            continue
        src = a.get("rungs")
        if src:
            print("\n  %-30s TEMPLATE, one arm per rung of "
                  "rungs.per_file[%s]"
                  % (a.get("id"), (src.get("file")
                                   or (a.get("server") or {}).get("model"))))
            ref = src.get("reference_rungs")
            if ref:
                print("    the literal ladder it replaced: %d rungs, %s ... %s"
                      % (len(ref), ref[0], ref[-1]))
        else:
            print("\n  %-30s literal, -c %s"
                  % (a.get("id"), raw_ctx((a.get("server") or {}).get("flags")
                                          or []) or "(none)"))
    print("\nrungs      : UNRESOLVED - nothing in this file can run yet")
    for line in str(problem).splitlines():
        print("  %s" % line)


def print_listing(spec, arms, order_mode, ladders=(), plan=None,
                  plan_path=None):
    print("sweep file : %s" % (spec.get("name") or "(unnamed)"))
    print("order      : %s%s"
          % (order_mode,
             "  (order within a sweep group reverses on every second pass, "
             "rule 30)" if order_mode == "alternate" else
             "  (file order, kept - correct for a ladder whose walk depends "
             "on it; rule 30 wants alternate wherever arms are COMPARED)"))
    print_ladders(ladders, plan, plan_path)
    print("arms       : %d%s"
          % (len(arms),
             "   (%d expanded from %d plan-driven template(s))"
             % (sum(1 for a in arms if a.get("_rung")), len(ladders))
             if ladders else ""))
    total = 0
    for a in arms:
        total += len(a["probes"]) * a["repeat"]
        print("\n  %-30s sweep %-22s repeat %d  discard_first %s"
              % (a["id"], a["sweep"] or "(ungrouped)", a["repeat"],
                 str(a["discard_first"]).lower()))
        print("    model  : %s" % a["server"]["model"])
        print("    -c     : %s" % _ctx_line(a))
        print("    flags  : %s" % (" ".join(a["server"]["flags"]) or "(none)"))
        for p in a["probes"]:
            print("    probe  : %-20s %-26s n_predict %s"
                  % (p["id"], _probe_source(p), _cap(p)))
        for w in arm_warnings(a, plan):
            print("    WARNING: %s" % w)
    print("\ntotal probes: %d" % total)


def print_plan(units, resolved, ledger_path, hb_path, slug, arm_dir, checked,
               responses_dir=None, ladders=(), plan=None, plan_path=None):
    print("slug       : %s" % slug)
    print_ladders(ladders, plan, plan_path)
    print("ledger     : %s" % ledger_path)
    print("responses  : %s" % (responses_dir or
                               "NOT SAVED (--no-save-responses): the generated "
                               "text will not exist after this run (rule 28)"))
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
        print("    -c       : %s" % _ctx_line(arm))
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
        for w in arm_warnings(arm, plan):
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
    ap.add_argument("--plan", metavar="FILE", default=None,
                    help="the campaign plan an arm file's \"rungs\" are taken "
                         "from; default results/<slug>/" + PLAN_FILE +
                         ", written by " + PLAN_WRITER + ". Its own \"slug\" "
                         "must match this campaign - one model's ladder on "
                         "another model is refused, not warned about")
    ap.add_argument("--resume", action="store_true",
                    help="skip arm/repeat units the ledger already records as "
                         "complete, and print which ones were skipped")
    ap.add_argument("--only", metavar="ID", default=None,
                    help="run just this arm id - what a raised-cap rerun and a "
                         "data-dependent ladder walk both need")
    # DEFAULT: ON, and rule 28 decides that, not taste. "A field not written
    # down during the run cannot be recovered at any price" is exactly what a
    # response body is: once the server has stopped, rerunning the probe is a
    # NEW sample under new clocks - and under any sampler but greedy it is not
    # even the same text - so the thing that was generated is simply gone.
    # Four downstream jobs read it and none can be served by response_chars:
    # Stage 4 counts reasoning appetite from the text, Stage 6b blind-judges
    # it, rule 20's repetition check has to spot-read it before a long greedy
    # run's tokens or timings may be trusted, and a "max coherent output"
    # column cannot be filled without it. METHODOLOGY is blunter still: a
    # probe whose claim carries a content label must have its text SAVED and
    # READ, because discarded output cannot support a claim about what was
    # generated.
    #
    # Against that, the disk. A body is capped at n_predict tokens at roughly
    # 4 chars a token, so this campaign's largest cap - 16,384 tokens - is
    # about 64 KiB, and a 400-probe sweep at that cap is about 26 MiB. The
    # weight file it was measuring is 9 GiB. Paying three thousandths of one
    # model file to keep the only unrecoverable artifact of the run is not a
    # trade worth deliberating, so saving is ON and the flag that matters is
    # the one that turns it OFF.
    ap.add_argument("--save-responses", dest="save_responses",
                    action="store_true", default=True,
                    help="write every generated body to "
                         "<ledger-stem>-responses/ beside the ledger, named "
                         "arm__repN__NN-probe.txt (this is the DEFAULT; the "
                         "flag is accepted so a command can say so out loud)")
    ap.add_argument("--no-save-responses", dest="save_responses",
                    action="store_false",
                    help="do NOT keep the generated text. Only for a sweep "
                         "measuring pure throughput at a huge cap where no "
                         "claim will ever be made about the CONTENT - the "
                         "text cannot be recovered afterwards (rule 28)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the full plan - every arm, its resolved model "
                         "path, its full argv, every probe - and touch nothing")
    ap.add_argument("--list", action="store_true",
                    help="list the arms and probes in the file and exit; "
                         "resolves no paths, so it runs anywhere")
    args = ap.parse_args()

    spec, raw_arms = read_arm_file(args.arms)
    order_mode = (spec.get("order")
                  or (spec.get("defaults") or {}).get("order") or "alternate")
    # --list and --dry-run REPORT a broken plan and exit 2; a real run refuses
    # outright. Neither ever falls back to a hardcoded window.
    soft = bool(args.list or args.dry_run)
    needs_plan = any(isinstance(a, dict) and a.get("rungs") for a in raw_arms)

    # A dry run must never take the GPU. gpu_lock refuses outright under this
    # variable, which turns "the plan accidentally launched something" from a
    # wasted hour into a stack trace.
    if args.dry_run:
        os.environ.setdefault(gpu_lock.DRY_RUN_ENV, "1")
    elif not args.list and os.environ.get(gpu_lock.DRY_RUN_ENV):
        _fail("%s is set in the environment but --dry-run was not passed. "
              "Every launch would raise DryRunViolation partway through the "
              "sweep. Pass --dry-run, or unset the variable deliberately."
              % gpu_lock.DRY_RUN_ENV)

    # The slug has to be resolved BEFORE the arms are merged now, because a
    # rung template is resolved out of results/<slug>/plan.json. --list on a
    # file of literal arms still resolves nothing and still runs anywhere.
    slug, plan, plan_path, problem = None, None, None, None
    if needs_plan or args.plan or not args.list:
        try:
            slug = resolve_slug(args.slug, spec, raw_arms)
        except SystemExit as e:
            if not soft:
                raise
            slug = None
            # Only a stopper for a file whose rungs live under results/<slug>/.
            # A --list of literal arms has never needed a campaign and still
            # does not.
            problem = str(e) if needs_plan else None
    if slug is not None:
        plan, plan_path, why = load_plan(slug, args.plan)
        if plan is None and needs_plan:
            tmpl = next(a for a in raw_arms
                        if isinstance(a, dict) and a.get("rungs"))
            msg = no_plan_message(tmpl.get("id"), args.arms, slug,
                                  plan_path, why)
            if soft:
                problem = msg
            else:
                _fail(msg)
        elif plan is None and args.plan:
            _fail("--plan %s cannot be used: %s" % (plan_path, why))

    if problem and needs_plan:
        # soft only - a real run already exited inside the block above.
        print_unresolved(spec, raw_arms, order_mode, problem)
        return 2

    ladders = []
    if plan is not None and needs_plan:
        raw_arms, ladders = expand_rungs(raw_arms, plan, plan_path, args.arms)
    arms = merge_arms(spec, raw_arms, args.arms)

    if args.only:
        arms = [a for a in arms if a["id"] == args.only]
        if not arms:
            _fail("--only %r matches no arm in %s%s"
                  % (args.only, args.arms,
                     " (a plan-driven arm's id is the EXPANDED one, with this "
                     "machine's rung substituted into the template - run "
                     "--list to see them)" if needs_plan else ""))

    if args.list:
        print_listing(spec, arms, order_mode, ladders, plan, plan_path)
        return 0

    stem = os.path.splitext(os.path.basename(args.arms))[0]
    root = paths.repo_root()
    arm_dir = os.path.dirname(os.path.abspath(args.arms))
    data_dir = os.path.join(root, "results", slug, "data", "arms")
    work_dir = os.path.join(root, "results", slug, "work", "arms", _safe(stem))
    ledger_path = os.path.join(data_dir, stem + ".jsonl")
    # Beside the ledger, not under work/: the text IS data, it is what a later
    # stage judges, and a directory that ships with the .jsonl keeps the two
    # together when the campaign is archived or handed on.
    responses_dir = (os.path.join(data_dir, stem + RESPONSES_SUFFIX)
                     if args.save_responses else None)
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
        print_plan(units, resolved, ledger_path, hb_path, slug, arm_dir,
                   checked, responses_dir, ladders, plan, plan_path)
        print("\nDRY RUN: nothing was launched and nothing was written.")
        if unresolved:
            print("%d arm(s) could not be resolved - see UNRESOLVED above."
                  % unresolved)
            return 2
        return 0

    for d in (data_dir, work_dir, os.path.dirname(hb_path)):
        os.makedirs(d, exist_ok=True)
    if responses_dir:
        os.makedirs(responses_dir, exist_ok=True)

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
                  "ctx_size": ctx_size(a["server"]["flags"]),
                  "ctx_source": ctx_source(a), "rung": a.get("_rung"),
                  "warnings": arm_warnings(a, plan)} for a in arms],
        "frozen_prompts_verified": checked,
        # rule 3, and the reason this runner reads a plan at all: the ladder is
        # DERIVED, so the derivation travels with the sweep it produced. A
        # plan-driven ladder that cannot be traced back to the arithmetic and
        # the machine that made it is a hardcoded ladder with extra steps.
        # NOT "plan": that key is already this line's per-pass ARM ORDER.
        "campaign_plan": ({"path": _rel(plan_path),
                  "slug": plan.get("slug"),
                  "generated_utc": plan.get("generated_utc"),
                  "generated_by": plan.get("generated_by"),
                  "cache_type": plan.get("cache_type"),
                  "c_min": plan.get("c_min"),
                  "exit_code": plan.get("exit_code"),
                  "verdict": plan.get("verdict"),
                  "machine": plan.get("machine"),
                  "step_rule": (plan.get("rungs") or {}).get("step_rule")}
                 if plan is not None else None),
        "ladders": ladders,
        # Whether the text survives this run is a CONDITION of every content
        # claim made from it later (rule 3), so it is on the sweep's own line.
        "save_responses": bool(args.save_responses),
        "responses_dir": responses_dir,
        "resume": bool(args.resume), "only": args.only,
        "pid": os.getpid(), "argv": sys.argv,
        # rule 3: the conditions travel with the numbers, in the same file
        "machine": machine,
    })

    print("sweep file %s: %d arms, %d loads, %d probes -> %s"
          % (file_name, len(arms), len(units), total_probes, ledger_path))
    print("%d frozen prompt(s) verified against the arm file (rule 23)"
          % checked)
    if ladders:
        print_ladders(ladders, plan, plan_path)
    for a in arms:
        for w in arm_warnings(a, plan):
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
                # The window, and where it came from, on every line this arm
                # writes. A number without its conditions is unfalsifiable
                # (rule 3), and "which -c was this?" answered by re-parsing a
                # flags array in a later stage is one refactor from being
                # answered wrongly. ctx_source distinguishes a DERIVED rung
                # from a literal, which is itself a condition of the ceiling.
                "ctx_size": ctx_size(arm["server"]["flags"]),
                "ctx_source": ctx_source(arm),
                "rung": arm.get("_rung"),
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
                    t_start_iso = _iso()
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
                    message = choice.get("message") or {}
                    content = message.get("content") or ""
                    # A server run with --reasoning keeps the thinking out of
                    # content. It is generated text too, it is what a probe
                    # that "spent the whole budget thinking and copied nothing"
                    # actually produced, and this request is already being
                    # issued - rule 28: widening it costs nothing.
                    reasoning = (message.get("reasoning_content")
                                 or message.get("reasoning") or "")
                    finish = choice.get("finish_reason")

                    resp_file = reas_file = save_err = None
                    if responses_dir:
                        resp_file, save_err = save_response(
                            responses_dir,
                            response_name(arm["id"], rep, j, p["id"]), content)
                        if reasoning:
                            reas_file, r_err = save_response(
                                responses_dir,
                                response_name(arm["id"], rep, j, p["id"],
                                              ".reasoning.txt"), reasoning)
                            save_err = save_err or r_err
                        if save_err:
                            print("       WARNING: the generated text could "
                                  "not be saved (%s) - this probe's numbers "
                                  "are real but its content is gone (rule 28)"
                                  % save_err)

                    rec = dict(
                        common, kind="probe", ts=_iso(), probe=p["id"],
                        # The energy join needs the request's START, and rule 28
                        # says a field not written during the run cannot be
                        # recovered at any price. With t_start_iso and label
                        # present, scripts/power/attribute-power.py consumes this
                        # ledger directly (--events), so every arm sweep is an
                        # energy arm for free and Stage 6e needs no PowerShell.
                        t_start_iso=t_start_iso,
                        label="%s/%s" % (arm["id"], p["id"]),
                        probe_index=j, discarded=discarded,
                        n_predict=p["n_predict"], prompt_source=src,
                        prompt_chars=len(text),
                        prompt_sha256=p.get("prompt_sha256"),
                        request=request, timings=t, drafting=drafting(t),
                        usage=resp.get("usage"), vram=vram.result(),
                        finish_reason=finish, response_chars=len(content),
                        # response_chars says how much; response_file is the
                        # only thing that can ever say WHAT. The path is
                        # relative to this ledger's own directory, so the pair
                        # survives the campaign being moved or archived.
                        response_file=resp_file,
                        response_saved=bool(resp_file),
                        response_save_error=save_err,
                        reasoning_chars=len(reasoning),
                        reasoning_file=reas_file,
                        # METHODOLOGY: an empty completion has two shapes and
                        # only one trips a cap. finish_reason=stop with zero
                        # characters is invisible to every truncation count,
                        # so it is counted here, separately, by name.
                        empty_answer=(len(content) == 0),
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
                    if rec["empty_answer"] and not rec["truncated"]:
                        print("       NOTE: EMPTY ANSWER - finish_reason=%s "
                              "with 0 characters after %d reasoning chars. No "
                              "truncation counter can see this; it is its own "
                              "metric." % (finish, len(reasoning)))
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
    if responses_dir:
        print("generated text -> %s" % responses_dir)
    else:
        print("generated text: NOT SAVED (--no-save-responses). Nothing in "
              "this run can support a claim about what was generated.")
    if failed_arms:
        print("FAILED arms: %s" % ", ".join(failed_arms))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
