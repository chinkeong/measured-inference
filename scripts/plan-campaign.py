#!/usr/bin/env python3
"""Turn the measured card and the measured model files into the campaign plan.

    python scripts/plan-campaign.py --slug qwen38-27b-blind
    python scripts/plan-campaign.py --slug lfm2-1.2b --cache-type q8_0 --json

Reads every `results/<slug>/model-*.json` (one per model FILE) plus
`results/<slug>/machine.json`, and writes `results/<slug>/plan.json` with four
things: the fit table, the ceiling-sweep rungs, the stage gate, and an estimate.

WHY THIS FILE EXISTS. Everything describing the MACHINE in this repo is
measured -- `scripts/detect-machine.py` writes `machine.json` and
`scripts/lib/paths.py` would rather stop the campaign than default a board
size. Everything describing the MODEL was still hardcoded from one worked
example, a 27B on a 24 GB card:

  * `scripts/arms/*.json` hardcode 23 distinct `-c` values, 22 of them between
    49,152 and 262,144, and exactly two logical model names (Q4_K_M,
    UD-IQ4_XS). On a 1.2B with a 32,768-token window every one of those rungs
    is above the model's own window; on a 1M-context Granite the top rung is a
    quarter of it.
  * Stage 3 sweeps a drafter whether or not the model HAS one. Stage 6c assumes
    a projector. Stage 4 assumes an effort knob. The stage files say "if the
    model has ..." in PROSE, and prose enforces nothing -- so a campaign on a
    model with no draft head runs the spec sweep, measures nothing, and the
    report reads as though speculation was tried and lost. Rule 2: no reader
    may measure less than the report promised them. A silently skipped axis is
    a measured negative in disguise, and this file is what makes every skip
    explicit and quotable.

WHAT IT REFUSES TO GUESS. Board size and desktop reserve come from
`machine.json` through `scripts/lib/paths.py`, exactly as `check-request.py`
takes them: absent, the fit is UNKNOWN with the command that writes one, and
nothing is called a ceiling. KV bytes/token comes from the model profile;
absent, the rungs are UNKNOWN. Architecture support comes from the profile,
backfilled from `scripts/lib/archs.py` when that module is importable and
reported UNKNOWN when it is not.

WHAT IT REUSES. `check-request.py` already prints a fit table against
`board - desktop_reserve.max`, and its `Report`, `ascii_only`, `comma`, `mib`,
`_stem` and cache-element constants are imported here rather than rewritten --
two fit tables that round differently are two answers to one question.

RULES: stdlib only (urllib, not requests -- Stage 0 runs before `.venv` is
guaranteed). Cross-platform. No GPU work and no downloads: the only network
call is an optional 1-byte ranged GET to learn a projector's or drafter's size
when the profile did not record it, and `--no-network` turns even that off.

exit: 0 the plan is complete   1 the campaign cannot start (unsupported
architecture, or nothing fits)   2 nothing failed but something is UNKNOWN --
an unsized fit is not a plan.
"""
import argparse
import glob
import io
import json
import math
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))
import paths                                                      # noqa: E402


# ---------------------------------------------------------------------------
# reuse, rather than diverge
# ---------------------------------------------------------------------------

def _load_sibling(filename, modname):
    """Import a hyphenated script next to this one as a module."""
    import importlib.util
    path = os.path.join(HERE, filename)
    spec = importlib.util.spec_from_file_location(modname, path)
    if spec is None or spec.loader is None:
        raise SystemExit("cannot import %s -- this plan would have to invent a "
                         "second fit table, and two fit tables that round "
                         "differently are two answers to one question." % path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CR = _load_sibling("check-request.py", "check_request")

# check-request.py is edited by other work (it grew a seventh check while this
# file was being written). Name what is borrowed, and say so plainly if one of
# them ever goes away, rather than dying on an AttributeError halfway through a
# fit table.
_BORROWED = ("Report", "ascii_only", "comma", "mib", "human", "_stem",
             "CACHE_TYPES", "DEFAULT_C_MIN", "RESOLVE", "_open", "find_token",
             "OK", "FAIL", "UNKNOWN", "SKIP")
_gone = [n for n in _BORROWED if not hasattr(CR, n)]
if _gone:
    raise SystemExit(
        "scripts/check-request.py no longer defines %s, and this script "
        "borrows them so the two fit tables cannot drift apart.\nEither "
        "restore the name there or take a local copy here -- but a second, "
        "silently different fit table is the outcome to avoid."
        % ", ".join(_gone))

ascii_only, comma, mib, human = CR.ascii_only, CR.comma, CR.mib, CR.human
Report, _stem = CR.Report, CR._stem
OK, FAIL, UNKNOWN, SKIP = CR.OK, CR.FAIL, CR.UNKNOWN, CR.SKIP
CACHE_TYPES = CR.CACHE_TYPES
RUNS, SKIPPED = "RUNS", "SKIPPED"

# archs.py is written by a concurrent job. Import it if it is there; report
# support as UNKNOWN if it is not. Never fail because it is missing.
try:
    import archs as _archs                                        # noqa: E402
except Exception:                                # ImportError, and anything it
    _archs = None                                # raises while reading a binary

CAPS = ("text", "vision", "drafter", "effort")


# ---------------------------------------------------------------------------
# the model profiles -- workstream A's output
# ---------------------------------------------------------------------------

REQUIRED = ("file", "file_bytes", "arch", "arch_supported", "context_length",
            "kv_bytes_per_token", "capabilities")


def results_dir(slug):
    return os.path.join(paths.repo_root(), "results", slug)


def profile_writer_hint(slug):
    """Name the command that writes a model-*.json.

    The model profiler is the other half of this pair and this script must not
    guess its filename, so the name is FOUND: the schema field `arch_supported`
    appears in no other file in this repo, which makes it an exact fingerprint
    for the writer.
    """
    root = paths.repo_root()
    for pat in ("scripts/*.py", "scripts/*/*.py"):
        for path in sorted(glob.glob(os.path.join(root, pat))):
            if os.path.abspath(path) == os.path.abspath(__file__):
                continue
            try:
                with io.open(path, "r", encoding="utf-8", errors="replace") as fh:
                    body = fh.read()
            except OSError:
                continue
            if "arch_supported" in body and "model-" in body:
                rel = os.path.relpath(path, root).replace(os.sep, "/")
                return "python %s --slug %s <org/repo>" % (rel, slug)
    return ("python scripts/inspect-model.py --slug %s <org/repo>   (the model "
            "profiler -- it is NOT in this checkout yet; it is the other half "
            "of this pair and it writes results/%s/model-<label>.json)"
            % (slug, slug))


def load_profiles(slug):
    """Every results/<slug>/model-*.json, plus what is wrong with each."""
    found, broken = [], []
    for path in sorted(glob.glob(os.path.join(results_dir(slug), "model-*.json"))):
        try:
            with io.open(path, "r", encoding="utf-8-sig") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            broken.append((os.path.basename(path), str(exc)))
            continue
        if not isinstance(data, dict):
            broken.append((os.path.basename(path), "not a JSON object"))
            continue
        data["_path"] = path
        data["_label"] = re.sub(r"^model-|\.json$", "", os.path.basename(path))
        data["_missing"] = [k for k in REQUIRED if data.get(k) is None]
        found.append(data)
    return found, broken


def kv_bytes(prof, cache_type):
    """(bytes_per_token, formula-string) for this cache type, or (None, why)."""
    kv = prof.get("kv_bytes_per_token")
    if not isinstance(kv, dict):
        return None, "the profile records no kv_bytes_per_token"
    val = kv.get(cache_type)
    if not isinstance(val, (int, float)) or isinstance(val, bool) or val <= 0:
        have = ", ".join(sorted(k for k, v in kv.items()
                                if isinstance(v, (int, float))
                                and not isinstance(v, bool)))
        return None, ("kv_bytes_per_token has no %r (has: %s)"
                      % (cache_type, have or "nothing usable"))
    return float(val), kv_formula(prof, cache_type)


def kv_formula(prof, cache_type):
    """The formula string the profiler recorded, wherever it put it."""
    kv = prof.get("kv_bytes_per_token") or {}
    arith = prof.get("kv_arithmetic") or {}
    prov = prof.get("provenance") or {}
    pk = prov.get("kv_bytes_per_token")
    for cand in (arith.get("formula") if isinstance(arith, dict) else None,
                 kv.get("formula"), kv.get("formula_" + cache_type),
                 prof.get("kv_formula"),
                 (pk or {}).get("formula") if isinstance(pk, dict) else None,
                 (pk or {}).get("how") if isinstance(pk, dict) else None,
                 pk if isinstance(pk, str) else None):
        if isinstance(cand, str) and cand.strip():
            return cand.strip()
    # Nothing recorded: rebuild it from the header fields and SAY that is what
    # happened. Rule 1 -- derived arithmetic is publishable only when shown.
    n, kvh, hd = (prof.get("block_count"), prof.get("head_count_kv"),
                  prof.get("head_dim"))
    if all(isinstance(v, int) and v > 0 for v in (n, kvh, hd)):
        eb = CACHE_TYPES.get(cache_type, (None,))[0]
        return ("no formula recorded; rebuilt from the header fields: 2 x %d "
                "layers x %d kv-heads x %d head-dim x %s B -- an UPPER BOUND, "
                "because the profile did not say how many layers are FULL "
                "attention" % (n, kvh, hd, eb))
    return "no formula recorded and the header fields to rebuild one are absent"


def fixed_state(prof):
    """Context-INDEPENDENT resident bytes, and how sure the profiler is.

    A hybrid's linear / gated-delta / mamba layers hold a per-sequence state
    that does not grow with the window: on the reference 27B, 48 recurrent
    layers at ~150 MiB. It is not KV and it is not weights, so it falls through
    both terms of the fit -- and 150 MiB is the difference between a thin fit
    and a spill. `check-request.py` charges the same quantity from config.json;
    this reads the profiler's, which comes from the GGUF header instead.
    """
    arith = prof.get("kv_arithmetic")
    if not isinstance(arith, dict):
        return 0.0, None
    rec = arith.get("recurrent_state")
    if not isinstance(rec, dict):
        return 0.0, None
    for key in ("bytes_per_sequence", "bytes", "mib"):
        v = rec.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            val = float(v) if key == "mib" else mib(float(v))
            how = ("%s MiB of context-independent state on %s recurrent "
                   "layers -- %s. %s"
                   % (comma(val), rec.get("recurrent_layers", "?"),
                      rec.get("formula") or "no formula recorded",
                      "VERIFIED against a server log."
                      if rec.get("verified") else
                      "UNVERIFIED against this build: the profiler derived it "
                      "from llama.cpp's tensor shapes, and a Stage-1 startup "
                      "log settles it."))
            return val, how
    return 0.0, None


def side_bytes(prof, which, token, offline, notes):
    """Bytes of the projector or the drafter, and where the number came from.

    The schema names `vision.mmproj_file` and `drafter.file` but not their
    sizes, and both are resident VRAM the whole time the recipe runs -- rule
    13's scope is <file + drafter + projector + desktop>. So: take a recorded
    size if the profiler wrote one, else ask the Hub for a Content-Length (one
    ranged GET of a single byte, no download), else report it UNKNOWN and say
    the total is optimistic by that much. Never invent it.
    """
    blk = prof.get(which)
    if not isinstance(blk, dict):
        return None, None, None
    name = blk.get("mmproj_file") or blk.get("file")
    for key in ("file_bytes", "bytes", "mmproj_bytes", "size_bytes"):
        v = blk.get(key)
        if isinstance(v, int) and not isinstance(v, bool) and v > 0:
            return name, v, "MEASURED (profile.%s.%s)" % (which, key)
    if offline or not name or not prof.get("repo"):
        notes.append("%s %s: size not recorded%s -- charged as UNKNOWN"
                     % (which, name or "?",
                        " and --no-network forbids asking" if offline else ""))
        return name, None, "UNKNOWN"
    url = CR.RESOLVE % (prof["repo"], name)
    try:
        with CR._open(url, token, {"Range": "bytes=0-0"}) as r:
            cr = r.headers.get("Content-Range") or ""
            total = cr.rsplit("/", 1)[-1]
            if total.isdigit():
                notes.append("%s %s: %s from a 1-byte ranged GET (no download)"
                             % (which, name, human(int(total))))
                return name, int(total), "MEASURED (HTTP Content-Range)"
            n = r.headers.get("Content-Length")
            if n and n.isdigit() and int(n) > 1:
                return name, int(n), "MEASURED (HTTP Content-Length)"
    except Exception as exc:                     # HttpFail, NetworkDown, OSError
        notes.append("%s %s: could not size it (%s)" % (which, name, exc))
    return name, None, "UNKNOWN"


# ---------------------------------------------------------------------------
# the budget -- taken exactly as check-request.py takes it
# ---------------------------------------------------------------------------

def budget(slug, notes):
    """(board_mib, reserve_dict) from machine.json, or (None, None).

    paths.py raises SystemExit when the file is missing, which is right for a
    run about to measure and wrong for a planner whose job is to report what is
    missing. Caught, reported, never defaulted (rule 3, rule 14).
    """
    try:
        board = paths.board_total_mib(slug)
        reserve = paths.desktop_reserve_mib(slug)
    except SystemExit as exc:
        text = str(exc).strip()
        notes.append("machine.json: %s"
                     % (text.splitlines()[0] if text else "unavailable"))
        return None, None
    notes.append("machine.json: board %s MiB, desktop reserve max %s MiB "
                 "(n=%s, measured %s)"
                 % (comma(board), comma(reserve["max"]), reserve["n"],
                    reserve["date"]))
    return board, reserve


NOT_COUNTED = ("NOT counted: llama.cpp's compute/output buffers (hundreds of "
               "MiB, unknown until the server logs it). Every predicted "
               "ceiling below is therefore OPTIMISTIC -- which is exactly why "
               "the ladder puts rungs BELOW it as well as above.")


def fit_one(prof, bpt, avail_mib, proj_mib, draft_mib, c_min, state_mib=0.0):
    """weights + drafter + projector + fixed state + kv(c) against the budget,
    plus the largest c that fits with the drafter aboard and with it off."""
    w = mib(prof["file_bytes"])
    fixed_on = w + proj_mib + draft_mib + state_mib
    fixed_off = w + proj_mib + state_mib
    row = {"file": prof.get("file"), "label": prof["_label"],
           "weights_mib": round(w, 1), "projector_mib": round(proj_mib, 1),
           "drafter_mib": round(draft_mib, 1),
           "fixed_state_mib": round(state_mib, 1),
           "kv_bytes_per_token": bpt, "c_min": c_min,
           "budget_mib": None if avail_mib is None else round(avail_mib, 1)}
    if bpt:
        row["kv_at_c_min_mib"] = round(mib(bpt * c_min), 1)
    if avail_mib is None or not bpt:
        row["verdict"] = UNKNOWN
        row["total_at_c_min_mib"] = None
        row["largest_c"] = None
        row["largest_c_drafter_off"] = None
        row["arithmetic"] = None
        return row
    total = fixed_on + mib(bpt * c_min)
    row["total_at_c_min_mib"] = round(total, 1)
    row["verdict"] = "FITS" if total <= avail_mib else "SPILLS"
    row["spare_mib_at_c_min"] = round(avail_mib - total, 1)
    row["largest_c"] = max(0, int((avail_mib - fixed_on) * 1048576.0 / bpt))
    row["largest_c_drafter_off"] = max(
        0, int((avail_mib - fixed_off) * 1048576.0 / bpt))
    row["arithmetic"] = (
        "%s weights + %s drafter + %s projector + %s fixed state + %s "
        "KV(c=%s) = %s MiB against a %s MiB budget -> %s.  Largest c that fits "
        "= (%s budget - %s resident) MiB x 1,048,576 / %s B per token = %s "
        "tokens (drafter aboard), %s with the drafter off."
        % (comma(w), comma(draft_mib), comma(proj_mib), comma(state_mib),
           comma(mib(bpt * c_min)), comma(c_min), comma(total),
           comma(avail_mib), row["verdict"],
           comma(avail_mib), comma(fixed_on), comma(bpt),
           comma(row["largest_c"]), comma(row["largest_c_drafter_off"])))
    return row


# ---------------------------------------------------------------------------
# THE RUNGS -- the part that makes the harness scale-free
# ---------------------------------------------------------------------------
#
# Stage 2 sweeps `-c` upward looking for three things (rule 13): the fully
# resident ceiling, the shallow-safe ceiling above it, and the collapse point
# above that. Today those rungs are 22 hardcoded numbers measured once, on a
# 27B, over a 24 GB card. They are DERIVED here instead, from four measured
# inputs: the file's weights, its KV bytes/token, the card's budget, and the
# model's OWN context_length out of the GGUF header.
#
# THE STEP RULE, and why each part of it is there.
#
#   ceiling  The largest c whose arithmetic fits, with the drafter aboard when
#            there is one. It is a PREDICTION and it is optimistic: it omits
#            llama.cpp's compute buffers, which is precisely why rungs are
#            placed below it as well as above.
#
#   q        The step. The dense band should hold seven rungs and span about a
#            third of the ceiling, so q is about a sixteenth of it, snapped to
#            a power of two (round windows, and llama.cpp pads n_ctx anyway)
#            and clamped to [1,024, 16,384]. On the reference 27B this returns
#            8,192 -- the step the reference campaign picked by hand.
#
#   lever    Two rungs far below, by halving. They are not ceiling candidates:
#            they are the lever arm for Stage 2's real deliverable, the
#            two-constant fit VRAM(window) = fixed + per-token x window, which
#            needs widely separated points and gets nothing from seven
#            neighbours.
#
#   dense    Every q from ceiling-2q to ceiling+4q. Two below because the
#            prediction is optimistic and the real resident ceiling is under
#            it; four above because rule 13's SECOND ceiling -- shallow-safe --
#            is above the resident one, and a sweep that stops at the
#            prediction finds one ceiling and reports two.
#
#   coarse   Every 4q from ceiling+8q to the top. The collapse point only has
#            to be BRACKETED here: ctx-ceiling.json's own stop_rule
#            binary-refines between the last good and the first bad rung at
#            4,096 resolution, so fine rungs up here buy nothing.
#
#   top      min(model context_length, 2 x ceiling). Bounded by the model's own
#            window because a rung above it measures rope scaling, not memory;
#            bounded at 2x because on the reference rig the measured
#            shallow-safe ceiling landed at ~1.6x the resident one with the
#            collapse just past it.
#
# AND THE CASE THE LADDER IS WRONG FOR. When the ceiling is at or above the
# model's whole window there is no ceiling to find: the window is resident, end
# of story. A ladder there would be a dozen arms proving one fact a dozen
# times. ONE rung, at the model's window, and the plan says why.

Q_MIN, Q_MAX = 1024, 16384
Q_DIVISOR = 16
DENSE_BELOW, DENSE_ABOVE = 2, 4
COARSE_START, COARSE_STEP = 8, 4
OVERSHOOT = 2
LEVER_RUNGS = 2
DEEP_FILL = 0.90        # rule 13b: no window is labeled without a deep-fill

STEP_RULE = (
    "q = clamp(2^round(log2(ceiling/%d)), %s, %s); "
    "lever = %d rungs by halving below the dense band, snapped to q, floored "
    "at max(q, ceiling/8); "
    "dense = every q in [ceiling-%dq, ceiling+%dq]; "
    "coarse = every %dq from ceiling+%dq to top; "
    "top = min(model context_length, %dx ceiling). "
    "Ceiling = the largest c whose arithmetic fits with the drafter aboard; it "
    "is optimistic (compute buffers are not in it), so rungs sit below it as "
    "well as above. The collapse point is BRACKETED, not resolved: "
    "scripts/arms/ctx-ceiling.json's stop_rule binary-refines at 4,096 "
    "resolution between the last good and the first bad rung."
    % (Q_DIVISOR, comma(Q_MIN), comma(Q_MAX), LEVER_RUNGS,
       DENSE_BELOW, DENSE_ABOVE, COARSE_STEP, COARSE_START, OVERSHOOT))


def quantum(ceiling):
    if ceiling <= 0:
        return Q_MIN
    q = 2 ** int(round(math.log(max(ceiling / float(Q_DIVISOR), 1.0), 2)))
    return int(min(max(q, Q_MIN), Q_MAX))


def _snap(x, q):
    return int(max(q, (int(x) // q) * q))


def derive_rungs(label, ceiling, ceiling_off, ctx_len, cache_type, why_no=None):
    """The ladder for one file on one card, or a stated reason there is none."""
    out = {"file": label, "cache_type": cache_type,
           "predicted_ceiling": ceiling,
           "predicted_ceiling_drafter_off": ceiling_off,
           "model_context_length": ctx_len, "quantum": None, "top": None,
           "rungs": [], "step_rule": STEP_RULE, "why": None,
           "collapse_point_reachable": None}

    if why_no:
        out["why"] = why_no
        return out
    if not ceiling or ceiling <= 0:
        out["why"] = ("NOTHING FITS. The weights plus projector plus drafter "
                      "already exceed the budget, so there is no window to "
                      "sweep and no rungs to run.")
        out["collapse_point_reachable"] = False
        return out

    if ctx_len and ceiling >= ctx_len:
        out["top"] = int(ctx_len)
        out["rungs"] = [{"c": int(ctx_len), "zone": "whole-window",
                         "deep_fill_tokens": int(ctx_len * DEEP_FILL),
                         "above_predicted_ceiling": False}]
        out["why"] = (
            "THE WHOLE WINDOW FITS -- there is no ceiling to find. The "
            "arithmetic holds %s tokens and the model was only trained for %s, "
            "so rule 13's fully-resident ceiling and shallow-safe ceiling are "
            "the same number, the model's own window, and this card has no "
            "collapse point for this file. A ceiling ladder here would spend a "
            "dozen arms proving one fact a dozen times. ONE rung, at the "
            "model's window -- still deep-filled to %d%% of it, because rule 13 "
            "labels no window without a deep-fill probe near its top."
            % (comma(ceiling), comma(ctx_len), int(DEEP_FILL * 100)))
        out["collapse_point_reachable"] = False
        return out

    q = quantum(ceiling)
    ceil0 = _snap(ceiling, q)
    top = int(OVERSHOOT * ceil0)
    bounded_by_model = False
    if ctx_len and ctx_len < top:
        top, bounded_by_model = int(ctx_len), True

    dense_lo = max(q, ceil0 - DENSE_BELOW * q)
    dense_hi = min(top, ceil0 + DENSE_ABOVE * q)

    rungs = {}
    x = dense_lo
    while x <= dense_hi:
        rungs[x] = "dense"
        x += q

    x, floor = dense_lo, max(q, ceil0 // 8)
    for _ in range(LEVER_RUNGS):
        x = _snap(x / 2.0, q)
        if x < floor or x in rungs:
            break
        rungs[x] = "lever"

    x = ceil0 + COARSE_START * q
    while x <= top:
        rungs[x] = "coarse"
        x += COARSE_STEP * q
    if top not in rungs and top > dense_hi:
        rungs[top] = "coarse"

    out["quantum"] = q
    out["top"] = top
    out["rungs"] = [{"c": c, "zone": rungs[c],
                     "deep_fill_tokens": int(c * DEEP_FILL),
                     "above_predicted_ceiling": c > ceiling}
                    for c in sorted(rungs)]
    above = [r for r in out["rungs"] if r["above_predicted_ceiling"]]
    out["collapse_point_reachable"] = bool(above)
    if not above:
        out["why"] = (
            "NO RUNG ABOVE THE PREDICTED CEILING. The card holds %s tokens and "
            "the model's window stops at %s, so the sweep runs out of model "
            "before it runs out of card. Rule 13's collapse point is NOT "
            "reachable inside the trained window on this machine: the report "
            "must publish the top rung as 'the largest window this model "
            "offers', never as a measured ceiling."
            % (comma(ceiling), comma(ctx_len)))
    elif bounded_by_model:
        out["why"] = (
            "%d rungs, step %s. The ladder stops at the model's own window "
            "(%s) rather than at %dx the predicted ceiling (%s): a rung above "
            "the trained window measures rope scaling, not memory."
            % (len(out["rungs"]), comma(q), comma(ctx_len), OVERSHOOT,
               comma(OVERSHOOT * ceil0)))
    else:
        out["why"] = (
            "%d rungs, step %s, topping out at %s = %dx the predicted ceiling. "
            "The model's own window is %s, which this card cannot hold, so the "
            "collapse point is below it and sweeping to it would spend arms "
            "past the answer."
            % (len(out["rungs"]), comma(q), comma(top), OVERSHOOT,
               comma(ctx_len) if ctx_len else "UNKNOWN"))
    return out


def ladder_line(rec):
    """The ladder as one line: lever | dense | coarse, ceiling rung starred."""
    if not rec["rungs"]:
        return "(no rungs)"
    groups, order = {}, []
    q = rec["quantum"] or 0
    for r in rec["rungs"]:
        z = r["zone"]
        if z not in order:
            order.append(z)
        star = "*" if (rec["predicted_ceiling"]
                       and not r["above_predicted_ceiling"]
                       and r["c"] + q > rec["predicted_ceiling"]) else ""
        groups.setdefault(z, []).append(comma(r["c"]) + star)
    return "  |  ".join(" ".join(groups[z]) for z in order)


# ---------------------------------------------------------------------------
# THE STAGE GATE
# ---------------------------------------------------------------------------
#
# Two sources, both read at run time rather than copied here:
#
#   the arm files   scripts/arms/*.json carry `stage`, and every arm's server
#                   flags carry the capability that arm needs. An arm with
#                   `--spec-type draft-mtp` needs a drafter; an arm passing
#                   `reasoning_effort` needs an effort knob. That is DERIVED
#                   from the sweep definition, so an arm file edited tomorrow
#                   gates itself without anyone touching this script.
#
#   the stage files the sub-stages with no arm file (6a quality, 6c vision, 6d
#                   agents, 6e energy, 4 appetite) are gated by a sentence in
#                   stages/stage-N.md -- "## Stage 6c -- vision (if an mmproj
#                   exists)". This script greps that sentence and QUOTES it as
#                   the reason. That is the point: the prose stops being
#                   advisory the moment something reads it.
#
# USING A CAPABILITY IS NOT THE SAME AS MEASURING IT, and getting that
# backwards is the bug this comment exists to prevent. Every one of the 25
# ctx-ceiling arms passes `--spec-type draft-mtp` and `--mmproj`, because the
# reference RECIPE carried a drafter and a projector -- not because the ceiling
# sweep measures either. Gating on "the flag appears" skips Stage 2's entire
# sweep on any model without a draft head, which is the opposite of the job.
# So each arm file is asked which capabilities it is SWEEPING:
#
#   REQUIRED  the flag that supplies the capability VARIES across the file's
#             arms (spec-sweep.json steps --spec-type from none to draft-mtp;
#             effort-sweep.json steps reasoning_effort through its levels), OR
#             the file's own declared `name` says the capability is the subject
#             ("acceptance demonstration" holds its spec flags constant and is
#             still meaningless without a drafter). Absent -> the file is
#             SKIPPED, whole.
#
#   MODIFIER  the flag is constant across every arm: it is part of the
#             configuration under test, not the axis. Absent -> the flag is
#             DROPPED, the arms still run, and the plan states that the numbers
#             no longer include that component and are not comparable to the
#             reference campaign's.
#
# Both verdicts are printed with the evidence that produced them, because a
# heuristic nobody can audit is worse than a table nobody can derive.

ARM_CAP_FLAGS = (
    ("--spec-type", "drafter",
     lambda v: bool(v) and v.lower() not in ("none", "off")),
    ("--spec-model", "drafter", lambda v: True),
    ("--model-draft", "drafter", lambda v: True),
    ("--mmproj", "vision", lambda v: True),
    ("--chat-template-kwargs", "effort",
     lambda v: "reasoning_effort" in (v or "") or "thinking" in (v or "")),
    ("--reasoning-effort", "effort", lambda v: True),
)

# Flags whose VALUE varying across arms means the file sweeps that capability.
CAP_AXIS_FLAGS = {
    "drafter": ("--spec-type", "--spec-draft-n-max", "--spec-draft-p-min",
                "--spec-model", "--model-draft"),
    "effort": ("--chat-template-kwargs", "--reasoning-effort"),
    "vision": ("--mmproj", "--image-min-tokens", "--image-max-tokens"),
}

# ... and the words that name it as the file's subject when nothing varies.
CAP_SUBJECT_WORDS = {
    "drafter": ("accept", "specul", "mtp", "draft"),
    "effort": ("effort", "reasoning", "thinking"),
    "vision": ("vision", "image", "mmproj", "screenshot"),
}


def arm_needs(flags):
    """Capabilities one arm's server flags touch, and the flag values, so the
    caller can tell an axis from a constant."""
    touched, values = set(), {}
    for i, tok in enumerate(flags):
        nxt = flags[i + 1] if i + 1 < len(flags) else ""
        val = "" if nxt.startswith("-") else nxt
        if tok.startswith("-"):
            values.setdefault(tok, val or "<present>")
        for name, cap, test in ARM_CAP_FLAGS:
            if tok == name and test(val):
                touched.add(cap)
    return touched, values


def read_arm_files():
    root = os.path.join(paths.repo_root(), "scripts", "arms")
    out = []
    for path in sorted(glob.glob(os.path.join(root, "*.json"))):
        try:
            with io.open(path, "r", encoding="utf-8-sig") as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            continue
        arms, seen, efforts = [], {}, set()
        for a in (doc.get("arms") or []):
            flags = ((a.get("server") or {}).get("flags")) or []
            touched, values = arm_needs(flags)
            for k, v in values.items():
                seen.setdefault(k, set()).add(v)
                if k == "--chat-template-kwargs":
                    m = re.search(r'"reasoning_effort"\s*:\s*"([^"]+)"', v)
                    if m:
                        efforts.add(m.group(1))
            arms.append({"id": a.get("id"), "touches": sorted(touched)})
        name = ascii_only(str(doc.get("name") or "")).lower()
        required, modifier, why = {}, {}, {}
        for cap, axis in CAP_AXIS_FLAGS.items():
            if not any(cap in a["touches"] for a in arms):
                continue
            varying = [f for f in axis if len(seen.get(f, ())) > 1]
            if varying:
                required[cap] = True
                why[cap] = ("REQUIRED: %s varies across the arms (%s) -- this "
                            "file sweeps it"
                            % (", ".join(varying),
                               ", ".join(sorted(seen[varying[0]]))[:70]))
            elif any(w in name for w in CAP_SUBJECT_WORDS[cap]):
                required[cap] = True
                why[cap] = ("REQUIRED: the file's own name calls it the "
                            "subject -- %r" % name[:70])
            else:
                modifier[cap] = sorted(seen.get(axis[0], ("<present>",)))[0]
                why[cap] = ("MODIFIER: %s is the same in every arm (%s), so it "
                            "is part of the configuration under test, not the "
                            "axis" % (axis[0], modifier[cap]))
        out.append({"path": "scripts/arms/" + os.path.basename(path),
                    "stage": str(doc.get("stage") or "?"),
                    "name": name, "arms": arms,
                    "required": sorted(required), "modifier": modifier,
                    "why": why,
                    "effort_levels": sorted(efforts),
                    "varies_c": len(seen.get("-c", ())) > 1})
    return out


def gate_prose(stage, needle):
    """The sentence in stages/stage-N.md that states this gate, verbatim.

    The frontmatter `description:` restates every heading, so it is skipped:
    quoting it hands the reader the whole stage summary where one clause was
    wanted."""
    path = os.path.join(paths.repo_root(), "skills", "field-guide", "stages",
                        "stage-%s.md" % stage)
    try:
        with io.open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith(("description:", "name:")):
                    continue
                if needle in line:
                    return ascii_only(line.strip().lstrip("#").strip())
    except OSError:
        pass
    return None


PROSE_STAGES = [
    # (id, title, capability required or None, stage file, grep needle)
    ("1", "STRUCTURE -- runtime, files, KV arithmetic, one floor per quant",
     None, "1", None),
    ("2", "MEMORY MAP -- budget table, drafter pair, ceiling sweep",
     None, "2", None),
    ("4", "APPETITE PROBES -- two cheap probes per effort level",
     "effort", "4", "if the model has an effort/thinking knob"),
    ("5", "RECIPE LOCK -- no GPU, the gate", None, "5", None),
    ("6a", "quality -- perplexity ranking + accuracy smoke tests",
     None, "6", "## Stage 6a"),
    ("6c", "vision -- resolution map, critique loop, agent-attach matrix",
     "vision", "6", "## Stage 6c"),
    ("6d", "agents end-to-end", None, "6", "## Stage 6d"),
    ("6e", "energy -- per-recipe block and the J/token matrix",
     None, "6", "## Stage 6e"),
    ("7", "PUBLISH + review gates", None, "7", None),
]

SKIP_TEXT = {
    "drafter": ("This model ships NO draft head and no companion draft model: "
                "the profile records drafter=null, so there was nothing to "
                "speculate with. %s did not run. The report says the model "
                "offers no speculation -- NOT that speculation was measured and "
                "lost (rule 2)."),
    "vision": ("This model has NO projector: the profile records vision=null, "
               "so there is no mmproj to load and no image path to measure. %s "
               "did not run. The report says the model is text-only -- NOT that "
               "vision was tested and failed (rule 2, rule 19)."),
    "effort": ("This model exposes NO effort/thinking knob: the profile records "
               "chat_template.effort_knob false, so there are no levels to "
               "sweep. %s did not run, and the report carries no effort axis at "
               "all rather than one unlabeled level (rule 2, rule 16)."),
}


def gate_stages(caps, cap_source, arch_ok, arch, build_tag, rung_recs,
                arm_files, nothing_fits=False):
    rows = []

    blocked = None
    if arch_ok is False:
        blocked = (
            "CAMPAIGN CANNOT START. llama.cpp build %s does not list "
            "architecture %r among the architectures it can load, so every "
            "probe in every stage aborts at load with 'unknown model "
            "architecture'. Nothing below runs. Pick a file this build "
            "supports, or rebuild llama.cpp from a revision that has %r."
            % (build_tag or "(untagged)", arch, arch))
    elif nothing_fits:
        blocked = (
            "CAMPAIGN CANNOT START. Not one profiled file fits this card, at "
            "any window: the weights plus projector plus drafter are already "
            "over the budget before a single KV token is allocated. Nothing "
            "below runs. Pick a smaller quant -- and note that lowering the "
            "window does not help, because the shortfall is in the resident "
            "weights.")
    if blocked:
        for sid, title, _, _, _ in PROSE_STAGES:
            rows.append({"stage": sid, "title": title, "status": SKIPPED,
                         "needs": None, "why": blocked})
        for af in arm_files:
            rows.append({"stage": af["stage"], "title": af["path"],
                         "status": SKIPPED, "needs": None, "why": blocked,
                         "arms_total": len(af["arms"]), "arms_runnable": 0})
        return sorted(rows, key=lambda r: (r["stage"], r["title"])), blocked

    for sid, title, need, sfile, needle in PROSE_STAGES:
        prose = gate_prose(sfile, needle) if needle else None
        if need and need not in caps:
            why = SKIP_TEXT[need] % ("Stage %s (%s)" % (sid, title))
            if prose:
                why += "  The gate is stage-%s.md's own line: %r." % (sfile,
                                                                      prose)
            rows.append({"stage": sid, "title": title, "status": SKIPPED,
                         "needs": need, "why": why})
            continue
        why = ""
        if sid == "2":
            single = [r for r in rung_recs if len(r["rungs"]) == 1
                      and r["rungs"][0]["zone"] == "whole-window"]
            if single and len(single) == len(rung_recs):
                why = ("Runs, but the ceiling SWEEP collapses to one rung per "
                       "file: the whole window fits, so there is no ceiling to "
                       "find. Everything else in Stage 2 -- budget table, "
                       "drafter on/off VRAM pair, projector pair, desktop "
                       "slack, the two-constant model -- still runs.")
        elif sid == "6d":
            why = ("Gated by interview item 7 (which coding agents to test), "
                   "not by the model: nothing in the model profile decides it, "
                   "so this planner leaves it open.")
        elif sid == "6e":
            why = ("Gated by instrumentation, not by the model: rule 24 says a "
                   "stage whose power logger was not running is reported 'not "
                   "measured', and is NEVER re-run for watts.")
        if need and prose:
            why += ("  Runs: capability %r is present (from %s), and "
                    "stage-%s.md gates it with %r."
                    % (need, cap_source.get(need, "the profile"), sfile, prose))
        rows.append({"stage": sid, "title": title, "status": RUNS,
                     "needs": need, "why": why.strip() or None})

    for af in arm_files:
        missing_req = [c for c in af["required"] if c not in caps]
        dropped_mod = sorted(c for c in af["modifier"] if c not in caps)
        why_bits = []
        if missing_req:
            status = SKIPPED
            runnable = 0
            why_bits.append(SKIP_TEXT.get(missing_req[0], "%s did not run.")
                            % ("%s (all %d arms)"
                               % (af["path"], len(af["arms"]))))
            why_bits.append("The gate is DERIVED from the file itself -- %s."
                            % af["why"][missing_req[0]])
        else:
            status = RUNS
            runnable = len(af["arms"])
            if dropped_mod:
                why_bits.append(
                    "DROPPED, not swept: %s. Every arm in this file holds "
                    "those flags constant, so they are configuration and not "
                    "the axis -- the arms still run without them. The numbers "
                    "then describe a lighter configuration than the reference "
                    "campaign's (no projector or drafter resident, no effort "
                    "level selected) and are NOT comparable to it."
                    % "; ".join("%s (%s constant at %s)"
                                % (c, CAP_AXIS_FLAGS[c][0],
                                   af["modifier"][c])
                                for c in dropped_mod))
        if af["stage"] == "2" and af["varies_c"] and status != SKIPPED:
            why_bits.append(
                "Its %d hardcoded -c values are the REFERENCE campaign's, "
                "measured on a 27B over a 24 GB card. Run it with this plan's "
                "derived rungs instead -- see the RUNGS check above."
                % len(af["arms"]))
        rows.append({"stage": af["stage"], "title": af["path"],
                     "status": status, "needs": missing_req or None,
                     "why": "  ".join(why_bits) or None,
                     "arms_total": len(af["arms"]),
                     "arms_runnable": runnable,
                     "capability_verdicts": af["why"]})

    return sorted(rows, key=lambda r: (r["stage"], r["title"])), None


# ---------------------------------------------------------------------------
# THE ESTIMATE -- a planning aid, labeled DERIVED, arithmetic shown
# ---------------------------------------------------------------------------

_H1 = re.compile(r"^#\s*Stage\s+([0-7])\b.*?\(~\s*([\d.]+)\s*"
                 r"(?:[\u2013\u2014-]\s*([\d.]+)\s*)?(h|min)")
_NOGPU = re.compile(r"^#\s*Stage\s+([0-7])\b.*?\(\s*no GPU time")
_SKILL_ROW = re.compile(r"^\|\s*\*\*(\d)\*\*\s*\|[^|]*\|\s*~?\s*([\d.]+)\s*"
                        r"(h|min)\s*\|")


def stage_hours():
    """Published per-stage hours, read out of the stage files themselves."""
    out = {}
    sdir = os.path.join(paths.repo_root(), "skills", "field-guide", "stages")
    for path in sorted(glob.glob(os.path.join(sdir, "stage-*.md"))):
        try:
            with io.open(path, "r", encoding="utf-8", errors="replace") as fh:
                head = fh.read(4000)
        except OSError:
            continue
        src = "stages/" + os.path.basename(path)
        for line in head.splitlines():
            m = _H1.match(line)
            if m:
                lo = float(m.group(2))
                hi = float(m.group(3)) if m.group(3) else lo
                if m.group(4) == "min":
                    lo, hi = lo / 60.0, hi / 60.0
                out[m.group(1)] = {"low_h": lo, "high_h": hi, "source": src,
                                   "quote": ascii_only(line.strip())}
                break
            m = _NOGPU.match(line)
            if m:
                out[m.group(1)] = {"low_h": 0.0, "high_h": 0.0, "source": src,
                                   "quote": ascii_only(line.strip())}
                break
    skill = os.path.join(paths.repo_root(), "skills", "field-guide", "SKILL.md")
    try:
        with io.open(skill, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = _SKILL_ROW.match(line)
                if m and m.group(1) not in out:
                    v = float(m.group(2)) / (60.0 if m.group(3) == "min" else 1.0)
                    out[m.group(1)] = {"low_h": v, "high_h": v,
                                       "source": "SKILL.md campaign map",
                                       "quote": ascii_only(line.strip()[:100])}
    except OSError:
        pass
    return out


def estimate(rows, rung_recs, hours, arm_files, blocked=None, levels=None):
    """Rough GPU hours per stage. DERIVED, and every line shows its arithmetic."""
    if blocked:
        # A blocked campaign costs nothing, and quoting a stage file's headline
        # hours here would put a budget beside a campaign that cannot start.
        zero = [{"stage": s, "hours_low": 0.0, "hours_high": 0.0,
                 "basis": "0 h -- the campaign cannot start; see STAGES"}
                for s in ("1", "2", "3", "4", "5", "6", "7")]
        return ({"per_stage": zero, "total_low_h": 0.0, "total_high_h": 0.0,
                 "label": "DERIVED -- zero, because nothing runs."},
                ["  Stage %-2s  0.0 h     the campaign cannot start; see STAGES"
                 % s for s in ("1", "2", "3", "4", "5", "6", "7")])
    ref_arms = {}
    for af in arm_files:
        ref_arms[af["stage"]] = ref_arms.get(af["stage"], 0) + len(af["arms"])

    planned = {}
    for r in rows:
        if "arms_runnable" not in r:
            continue
        planned[r["stage"][0]] = planned.get(r["stage"][0], 0) + r["arms_runnable"]

    out, lines, total_lo, total_hi = [], [], 0.0, 0.0
    for sid in ("1", "2", "3", "4", "5", "6", "7"):
        pub = hours.get(sid)
        if not pub:
            out.append({"stage": sid, "hours_low": None, "hours_high": None,
                        "basis": "no published figure in the stage file"})
            lines.append("  Stage %-2s  UNKNOWN   no published figure to scale"
                         % sid)
            continue
        lo, hi, basis = pub["low_h"], pub["high_h"], None

        if sid == "2":
            ref, mine = ref_arms.get("2", 0), sum(len(r["rungs"])
                                                  for r in rung_recs)
            if ref and mine:
                per = pub["low_h"] / ref
                lo = hi = per * mine
                basis = ("%s publishes ~%g h for the reference campaign's %d "
                         "ceiling arms = %.1f min/rung; this plan derives %d "
                         "rungs -> %.1f h"
                         % (pub["source"], pub["low_h"], ref, per * 60, mine, lo))
        elif sid in ("3", "6"):
            ref, mine = ref_arms.get(sid, 0), planned.get(sid, 0)
            if ref:
                frac = mine / float(ref)
                lo, hi = pub["low_h"] * frac, pub["high_h"] * frac
                span = ("%g" % pub["low_h"] if pub["low_h"] == pub["high_h"]
                        else "%g-%g" % (pub["low_h"], pub["high_h"]))
                basis = ("%s publishes ~%s h across the reference campaign's %d "
                         "stage-%s arms; %d survive this model's capability "
                         "gate -> x%.2f -> %.1f-%.1f h"
                         % (pub["source"], span, ref, sid, mine, frac, lo, hi))
        elif sid == "4":
            if any(r["stage"] == "4" and r["status"] == SKIPPED for r in rows):
                lo = hi = 0.0
                basis = ("0 h -- Stage 4 is SKIPPED by the capability gate; "
                         "the reason is in STAGES above")
            elif levels:
                ref_lv = max((len(af.get("effort_levels") or ())
                              for af in arm_files), default=0)
                if ref_lv:
                    frac = len(levels) / float(ref_lv)
                    lo, hi = pub["low_h"] * frac, pub["high_h"] * frac
                    basis = ("%s publishes ~%g h for two probes at each of the "
                             "reference campaign's %d effort levels; this "
                             "model's template offers %d (%s) -> x%.2f -> "
                             "%.1f h"
                             % (pub["source"], pub["low_h"], ref_lv,
                                len(levels), ", ".join(levels), frac, lo))
        if basis is None:
            basis = ("%s: %s (CITED, not scaled -- nothing countable to scale "
                     "by)" % (pub["source"], pub["quote"]))
        out.append({"stage": sid, "hours_low": round(lo, 2),
                    "hours_high": round(hi, 2), "basis": basis})
        total_lo, total_hi = total_lo + lo, total_hi + hi
        lines.append("  Stage %-2s  %-9s %s"
                     % (sid, ("%.1f h" % lo) if abs(hi - lo) < 0.05
                        else "%.1f-%.1f h" % (lo, hi), basis))
    return ({"per_stage": out, "total_low_h": round(total_lo, 2),
             "total_high_h": round(total_hi, 2),
             "label": "DERIVED -- a planning aid, not a measurement. It scales "
                      "the stage files' own published hours by arm and rung "
                      "counts; it knows nothing about this card's speed."},
            lines)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def effort_levels(profiles):
    """The effort levels this model's chat template actually offers.

    The profiler records `chat_template.effort_knob` as an object with a
    `levels` list. Older/simpler writers record a bare bool, which says a knob
    exists and not how many notches it has -- then the count is UNKNOWN and the
    Stage-4 estimate is not scaled rather than scaled by a guess.
    """
    for p in profiles:
        knob = (p.get("chat_template") or {}).get("effort_knob")
        if isinstance(knob, dict):
            lv = knob.get("levels")
            if isinstance(lv, list) and lv:
                return [str(x) for x in lv], p["_label"]
    return None, None


def resolve_arch_support(prof, notes):
    """(True|False|None, why). The profile first; archs.py only to settle an
    unknown, and never a hard dependency -- it is written by another job."""
    val = prof.get("arch_supported")
    if isinstance(val, bool):
        return val, "profile.arch_supported (against build %s)" % (
            prof.get("build_tag") or "?")
    if isinstance(val, str) and val.lower() in ("true", "false"):
        return val.lower() == "true", "profile.arch_supported"
    arch = prof.get("arch")
    if _archs is None or not arch:
        notes.append("arch support UNKNOWN: the profile says %r and "
                     "scripts/lib/archs.py is not importable here" % (val,))
        return None, "UNKNOWN -- no roster available"
    try:
        roster = _archs.supported_archs()
        return (arch in roster), ("scripts/lib/archs.py roster of %d "
                                  "architectures, read from %s"
                                  % (len(roster), roster.where()))
    except Exception as exc:
        notes.append("scripts/lib/archs.py could not answer: %s" % exc)
        return None, "UNKNOWN -- archs.py raised %s" % type(exc).__name__


def plan_verdict(rep, blocked, fits, rung_recs, rows, est):
    """This tool's own one-line verdict.

    check-request.py's verdict answers "can this box fetch and hold it"; the
    question here is "is there a campaign to run", and reusing its sentence
    would have this script announce that access was proven when it never looked.
    """
    bad = [r for r in rep.rows if r["status"] == FAIL]
    unk = [r for r in rep.rows if r["status"] == UNKNOWN]
    if blocked:
        rest = ascii_only(blocked).split(". ", 1)
        return ("VERDICT: NO CAMPAIGN -- %s Every stage is skipped and the "
                "estimate is zero; see STAGES above."
                % (rest[1] if len(rest) > 1 else rest[0]))
    if bad:
        return ("VERDICT: NO PLAN -- %s. %s"
                % (", ".join(r["name"].lower() for r in bad),
                   bad[0]["fix"] or bad[0]["line"]))
    if unk:
        return ("VERDICT: PARTIAL PLAN -- %s could not be established, so the "
                "plan below is not one a campaign may spend hours on. %s"
                % (", ".join(r["name"].lower() for r in unk),
                   unk[0]["fix"] or "Resolve it before Stage 1."))
    runs = sum(1 for r in rows if r["status"] != SKIPPED)
    return ("VERDICT: PLANNED -- %d file%s, %d ceiling rung%s, %d of %d stage "
            "units run, ~%.1f-%.1f GPU hours (DERIVED)."
            % (len(fits), "" if len(fits) == 1 else "s",
               sum(len(r["rungs"]) for r in rung_recs),
               "" if sum(len(r["rungs"]) for r in rung_recs) == 1 else "s",
               runs, len(rows), est["total_low_h"], est["total_high_h"]))


def _wrap(text, width):
    words, line, out = ascii_only(text).split(), "", []
    for w in words:
        if line and len(line) + 1 + len(w) > width:
            out.append(line)
            line = w
        else:
            line = (line + " " + w) if line else w
    if line:
        out.append(line)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="plan-campaign.py",
        description="Turn results/<slug>/model-*.json + machine.json into "
                    "results/<slug>/plan.json: the fit, the rungs, the stage "
                    "gate, the estimate.",
        epilog="""examples:
  python scripts/plan-campaign.py --slug qwen38-27b-blind
  python scripts/plan-campaign.py --slug qwen38-27b-blind --cache-type q8_0 --json

exit: 0 the plan is complete   1 the campaign cannot start   2 something is
UNKNOWN -- an unsized fit is not a plan.""",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slug", required=True, help="campaign slug")
    ap.add_argument("--cache-type", default="f16", choices=sorted(CACHE_TYPES),
                    help="KV cache element type the rungs are derived for "
                         "(default f16)")
    ap.add_argument("--c-min", type=int, default=CR.DEFAULT_C_MIN, metavar="N",
                    help="smallest context the campaign must run at "
                         "(default %d, rule 21's cap)" % CR.DEFAULT_C_MIN)
    ap.add_argument("--no-projector", action="store_true",
                    help="do not charge the mmproj against the budget")
    ap.add_argument("--no-drafter", action="store_true",
                    help="do not charge the drafter against the budget")
    ap.add_argument("--no-network", action="store_true",
                    help="never ask the Hub for a projector/drafter size")
    ap.add_argument("--token", metavar="TOK", help="HF access token")
    ap.add_argument("--no-token", action="store_true",
                    help="ignore any token in the environment")
    ap.add_argument("--out", metavar="FILE",
                    help="where to write the plan (default "
                         "results/<slug>/plan.json)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan, write nothing")
    ap.add_argument("--json", action="store_true",
                    help="also print the plan record to stdout")
    a = ap.parse_args(argv)

    token, _ = CR.find_token(a.token, allow_env=not a.no_token)
    out = sys.stdout
    out.write("\nplan-campaign  %s\n" % a.slug)
    out.write("               KV %s, c_min %s\n\n"
              % (a.cache_type, comma(a.c_min)))

    rep = Report(6)
    notes = []

    # ---- 1  SLUG ---------------------------------------------------------
    rdir = results_dir(a.slug)
    if "/" in a.slug or "\\" in a.slug:
        rep.add("SLUG", FAIL, "%r is not a single path component" % a.slug,
                fix="AGENTS.md: the slug is the repo name, lowercased, -GGUF "
                    "dropped, no slashes")
    elif os.path.isdir(rdir):
        rep.add("SLUG", OK, a.slug, ["results dir: %s" % rdir])
    else:
        rep.add("SLUG", UNKNOWN, "%s has no results directory" % a.slug,
                ["would be: %s" % rdir],
                fix="python scripts/detect-machine.py --slug %s" % a.slug)

    # ---- 2  PROFILES -----------------------------------------------------
    profiles, broken = load_profiles(a.slug)
    detail = ["%-28s %-14s %-10s %s"
              % (p["_label"], p.get("arch") or "?", human(p.get("file_bytes")),
                 "caps: " + ",".join(p.get("capabilities") or ["?"]))
              for p in profiles]
    for name, why in broken:
        detail.append("%-28s UNREADABLE  %s" % (name, why))
    incomplete = [p for p in profiles if p["_missing"]]
    for p in incomplete:
        detail.append("%-28s MISSING %s" % (p["_label"], ", ".join(p["_missing"])))
    if not profiles:
        rep.add("PROFILES", UNKNOWN,
                "no results/%s/model-*.json: there is nothing to plan" % a.slug,
                detail + ["the plan needs one profile per model FILE -- the arch "
                          "string belongs to the file, not to the model"],
                fix=profile_writer_hint(a.slug))
    elif broken or incomplete:
        rep.add("PROFILES", UNKNOWN, "%d profile%s, %d incomplete"
                % (len(profiles), "" if len(profiles) == 1 else "s",
                   len(broken) + len(incomplete)), detail,
                fix="re-run the profiler: " + profile_writer_hint(a.slug))
    else:
        rep.add("PROFILES", OK, "%d model file%s profiled"
                % (len(profiles), "" if len(profiles) == 1 else "s"), detail)

    # ---- 3  ARCH ---------------------------------------------------------
    caps, cap_source = set(), {}
    for p in profiles:
        for c in (p.get("capabilities") or []):
            if c in CAPS:
                caps.add(c)
                cap_source.setdefault(c, p["_label"])
    arch_ok, arch_name, build_tag = None, None, None
    if profiles:
        detail, verdicts = [], []
        for p in profiles:
            ok, why = resolve_arch_support(p, notes)
            p["_arch_ok"] = ok
            verdicts.append(ok)
            detail.append("%-28s arch %-14s %-11s %s"
                          % (p["_label"], p.get("arch") or "?",
                             {True: "SUPPORTED", False: "UNSUPPORTED",
                              None: "UNKNOWN"}[ok], why))
        arch_name = profiles[0].get("arch")
        build_tag = profiles[0].get("build_tag")
        detail.append("capabilities across all files: %s"
                      % (", ".join(sorted(caps)) or "(none declared)"))
        if all(v is False for v in verdicts):
            arch_ok = False
            rep.add("ARCH", FAIL,
                    "this build cannot load %r -- the campaign cannot start"
                    % arch_name, detail,
                    fix="pick a file whose architecture this build lists, or "
                        "rebuild llama.cpp from a revision that has it")
        elif any(v is None for v in verdicts):
            rep.add("ARCH", UNKNOWN, "architecture support is UNPROVEN", detail,
                    fix="python scripts/lib/archs.py   (reads the roster out of "
                        "this build's libllama; absent, support stays UNKNOWN "
                        "and a load failure becomes a Stage-1 surprise)")
        else:
            arch_ok = True
            rep.add("ARCH", OK, "%r is loadable by build %s"
                    % (arch_name, build_tag or "(untagged)"), detail)
    else:
        rep.add("ARCH", SKIP, "no profiles to check")

    # ---- 4  FIT ----------------------------------------------------------
    board, reserve = budget(a.slug, notes)
    avail = None if board is None else board - reserve["max"]
    fits, rung_recs = [], []
    if not profiles:
        rep.add("FIT", UNKNOWN, "no profiles to size", notes)
    else:
        detail = []
        if arch_ok is False:
            detail.append("ARCH SAYS NO: the arithmetic below is real, and it "
                          "is academic -- this build cannot load the file at "
                          "all, so nothing here is a go-ahead.")
        if avail is not None:
            detail.append("budget = %s board - %s desktop reserve(max) = %s MiB"
                          % (comma(board), comma(reserve["max"]), comma(avail)))
        detail.extend(notes)
        for p in profiles:
            bpt, formula = kv_bytes(p, a.cache_type)
            pname, pbytes, phow = ((None, None, None) if a.no_projector else
                                   side_bytes(p, "vision", token, a.no_network,
                                              detail))
            dname, dbytes, dhow = ((None, None, None) if a.no_drafter else
                                   side_bytes(p, "drafter", token, a.no_network,
                                              detail))
            proj_mib = mib(pbytes) if pbytes else 0.0
            draft_mib = mib(dbytes) if dbytes else 0.0
            state_mib, state_how = fixed_state(p)
            row = fit_one(p, bpt, avail, proj_mib, draft_mib, a.c_min,
                          state_mib)
            row["fixed_state_how"] = state_how
            row["kv_formula"] = formula
            row["projector"] = {"file": pname, "mib": round(proj_mib, 1),
                                "how": phow}
            row["drafter"] = {"file": dname, "mib": round(draft_mib, 1),
                              "how": dhow}
            row["arch_supported"] = p.get("_arch_ok")
            row["context_length"] = p.get("context_length")
            # A component that EXISTS but could not be sized is not a zero. It
            # is the difference between a fit and a spill, and leaving the row
            # green with a footnote is how an optimistic total gets published
            # as a proven one (rule 3).
            row["unsized_components"] = [
                w for w, how, got in (("projector", phow, pbytes),
                                      ("drafter", dhow, dbytes))
                if how is not None and not got]
            fits.append(row)

            mark = ("FITS, %s MiB spare" % comma(row["spare_mib_at_c_min"])
                    if row["verdict"] == "FITS" else
                    "SPILLS by %s MiB" % comma(-row["spare_mib_at_c_min"])
                    if row["verdict"] == "SPILLS" else "? unsized")
            # "-" means the model has no such component; "?" means it has one
            # and nothing could size it. Printing both as "?" would turn a
            # known zero into an unknown, which is how an optimistic total
            # gets published as a proven fit.
            cell = (lambda how, val, m: "-" if how is None
                    else (comma(m) if val else "?"))
            detail.append("%-27s %9s w + %8s drf + %6s prj + %6s st + %8s kv "
                          "= %9s  %s"
                          % (_stem(p["_label"]), comma(row["weights_mib"]),
                             cell(dhow, dbytes, draft_mib),
                             cell(phow, pbytes, proj_mib),
                             comma(state_mib) if state_how else "-",
                             comma(row["kv_at_c_min_mib"]) if bpt else "?",
                             comma(row["total_at_c_min_mib"])
                             if row["total_at_c_min_mib"] is not None else "?",
                             mark))
            if state_how:
                detail.append("      fixed state: %s" % state_how)
            detail.append("      KV %s = %s B/token   %s"
                          % (a.cache_type,
                             comma(bpt) if bpt else "UNKNOWN", formula))
            if row["largest_c"] is not None:
                detail.append("      largest c that fits: %s with the drafter "
                              "aboard | %s without | model's own window %s"
                              % (comma(row["largest_c"]),
                                 comma(row["largest_c_drafter_off"]),
                                 comma(p["context_length"])
                                 if p.get("context_length") else "UNKNOWN"))
            if ((pbytes is None and isinstance(p.get("vision"), dict))
                    or (dbytes is None and isinstance(p.get("drafter"), dict))):
                detail.append("      NOTE: a resident component could not be "
                              "sized, so this total is OPTIMISTIC by that much")
        detail.append(NOT_COUNTED)

        if avail is None:
            rep.add("FIT", UNKNOWN, "no machine.json: this card is unmeasured",
                    detail,
                    fix="python scripts/detect-machine.py --slug %s   (writes "
                        "results/%s/machine.json; a guessed board is how a "
                        "spilling window gets stamped PASS -- rule 13)"
                        % (a.slug, a.slug))
        elif any(r["verdict"] == UNKNOWN for r in fits):
            rep.add("FIT", UNKNOWN, "%d of %d files could not be sized"
                    % (sum(1 for r in fits if r["verdict"] == UNKNOWN),
                       len(fits)), detail,
                    fix="the profile must carry kv_bytes_per_token: "
                        + profile_writer_hint(a.slug))
        elif any(r["unsized_components"] for r in fits):
            miss = sorted({c for r in fits for c in r["unsized_components"]})
            rep.add("FIT", UNKNOWN,
                    "the totals are OPTIMISTIC: %s could not be sized"
                    % " and ".join(miss), detail,
                    fix=("every one of those is resident VRAM for the whole "
                         "run (rule 13's scope is file+drafter+projector+"
                         "desktop). Drop --no-network so the size can be read "
                         "from the Hub, or have the profiler record "
                         "vision.file_bytes / drafter.file_bytes. A 'FITS' "
                         "with a component missing from the sum is not a fit."))
        elif not any(r["verdict"] == "FITS" for r in fits):
            rep.add("FIT", FAIL, "nothing fits at c=%s" % comma(a.c_min), detail,
                    fix="this card is the wrong size for these files -- pick a "
                        "smaller quant, or lower --c-min")
        else:
            rep.add("FIT", OK, "%d of %d file%s fit at c=%s"
                    % (sum(1 for r in fits if r["verdict"] == "FITS"),
                       len(fits), "" if len(fits) == 1 else "s",
                       comma(a.c_min)), detail)

    # ---- 5  RUNGS --------------------------------------------------------
    if not fits:
        rep.add("RUNGS", UNKNOWN, "no fit table, so no ladder",
                ["The rungs are derived FROM the fit: with no board size and no "
                 "KV figure there is no predicted ceiling to place them around, "
                 "and a ladder placed anywhere else is the 22 hardcoded numbers "
                 "again."])
    else:
        detail = []
        if arch_ok is False:
            detail.append("ARCH SAYS NO: these rungs describe a campaign that "
                          "cannot start. Kept because they become the plan the "
                          "moment a build that lists this architecture exists.")
        for p, row in zip(profiles, fits):
            why_no = None
            if row["largest_c"] is None:
                why_no = ("UNSIZED: %s -- no ceiling to place rungs around."
                          % ("no board size (machine.json is missing)"
                             if avail is None else
                             "no kv_bytes_per_token for %s" % a.cache_type))
            rec = derive_rungs(p["_label"], row["largest_c"],
                               row["largest_c_drafter_off"],
                               p.get("context_length"), a.cache_type, why_no)
            rec["ceiling_is_upper_bound"] = bool(row["unsized_components"])
            if row["unsized_components"]:
                rec["why"] = (
                    "CEILING IS AN UPPER BOUND, so this ladder sits too high: "
                    "%s resident VRAM that could not be sized and is missing "
                    "from the sum. Size it before spending arms on these rungs. "
                    % (" and ".join(row["unsized_components"])
                       + (" are" if len(row["unsized_components"]) > 1
                          else " is"))) + (rec["why"] or "")
            rung_recs.append(rec)
            detail.append("%-30s %s"
                          % (_stem(p["_label"]),
                             "%d rungs, step %s" % (len(rec["rungs"]),
                                                    comma(rec["quantum"]))
                             if rec["quantum"] else
                             "%d rung%s" % (len(rec["rungs"]),
                                            "" if len(rec["rungs"]) == 1
                                            else "s")))
            detail.append("      predicted ceiling %s (drafter on) | %s (off) "
                          "| model window %s"
                          % (comma(rec["predicted_ceiling"])
                             if rec["predicted_ceiling"] else "?",
                             comma(rec["predicted_ceiling_drafter_off"])
                             if rec["predicted_ceiling_drafter_off"] else "?",
                             comma(rec["model_context_length"])
                             if rec["model_context_length"] else "?"))
            if rec["rungs"]:
                detail.append("      %s" % ladder_line(rec))
            for chunk in _wrap(rec["why"] or "", 84):
                detail.append("      " + chunk)
            low = [r["c"] for r in rec["rungs"] if r["c"] < a.c_min]
            if low:
                detail.append("      below the rule-21 floor (%s): %s -- lever "
                              "probes for the two-constant fit, never recipe "
                              "candidates"
                              % (comma(a.c_min),
                                 ", ".join(comma(c) for c in low)))
        detail.append("zones: lever | dense | coarse    * = the rung just under "
                      "the predicted ceiling")
        detail.append("step rule: " + STEP_RULE)
        total = sum(len(r["rungs"]) for r in rung_recs)
        unreachable = [r for r in rung_recs
                       if r["collapse_point_reachable"] is False
                       and len(r["rungs"]) > 1]
        upper = [r for r in rung_recs if r.get("ceiling_is_upper_bound")]
        if total:
            rep.add("RUNGS", UNKNOWN if (unreachable or upper) else OK,
                    "%d rung%s across %d file%s"
                    % (total, "" if total == 1 else "s", len(rung_recs),
                       "" if len(rung_recs) == 1 else "s"), detail,
                    fix=("size the unsized resident components first -- a "
                         "ladder built on an upper-bound ceiling sweeps windows "
                         "the card cannot hold and reads as a collapse that is "
                         "really an arithmetic error") if upper else
                        ("rule 13 wants a collapse point and the model's own "
                         "window stops first -- publish the top rung as 'the "
                         "largest window this model offers', never as a "
                         "measured ceiling") if unreachable else None)
        else:
            rep.add("RUNGS", UNKNOWN, "no ladder could be derived", detail)

    # ---- 6  STAGES -------------------------------------------------------
    arm_files = read_arm_files()
    nothing_fits = bool(fits) and avail is not None and not any(
        r["verdict"] == "FITS" for r in fits)
    rows, blocked = gate_stages(caps, cap_source, arch_ok, arch_name, build_tag,
                                rung_recs, arm_files, nothing_fits)
    detail = []
    for r in rows:
        detail.append("Stage %-3s %-8s %s" % (r["stage"], r["status"],
                                              r["title"]))
        for chunk in _wrap(r["why"] or "", 86):
            detail.append("            " + chunk)
    n_skip = sum(1 for r in rows if r["status"] == SKIPPED)
    if not profiles:
        # With no profile there is no capabilities[] to gate on, and an empty
        # set silently reads as "this model has nothing" -- which would print a
        # confident list of skips about a model nobody has looked at.
        rep.add("STAGES", UNKNOWN,
                "no profiles: the capability gate has nothing to read", detail,
                fix=profile_writer_hint(a.slug))
    elif blocked:
        rep.add("STAGES", FAIL, "every stage skipped: the campaign cannot start",
                detail)
    elif n_skip:
        rep.add("STAGES", OK, "%d of %d units run, %d skipped by capability"
                % (len(rows) - n_skip, len(rows), n_skip), detail)
    else:
        rep.add("STAGES", OK, "all %d units run" % len(rows), detail)

    rep.render(out)

    # ---- the estimate ----------------------------------------------------
    hours = stage_hours()
    levels, _ = effort_levels(profiles)
    est, lines = estimate(rows, rung_recs, hours, arm_files, blocked,
                          levels if "effort" in caps else None)
    out.write("  ESTIMATE (DERIVED -- a planning aid, not a measurement)\n")
    for line in lines:
        out.write(ascii_only(line) + "\n")
    out.write("  Stage %-2s  %.1f-%.1f h   the whole campaign, on this plan\n\n"
              % ("*", est["total_low_h"], est["total_high_h"]))

    out.write(plan_verdict(rep, blocked, fits, rung_recs, rows, est) + "\n")

    plan = {
        "slug": a.slug,
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "generated_by": "scripts/plan-campaign.py",
        "cache_type": a.cache_type,
        "c_min": a.c_min,
        "machine": {"board_total_mib": board,
                    "desktop_reserve_mib": reserve,
                    "budget_mib": avail,
                    "source": ("results/%s/machine.json" % a.slug)
                              if board is not None else None},
        "models": [{"label": p["_label"], "file": p.get("file"),
                    "repo": p.get("repo"), "arch": p.get("arch"),
                    "arch_supported": p.get("_arch_ok"),
                    "context_length": p.get("context_length"),
                    "params_total": p.get("params_total"),
                    "bpw": p.get("bpw"),
                    "capabilities": p.get("capabilities"),
                    "build_tag": p.get("build_tag"),
                    "inspected_utc": p.get("inspected_utc"),
                    "profile": os.path.relpath(
                        p["_path"], paths.repo_root()).replace(os.sep, "/")}
                   for p in profiles],
        "capabilities": sorted(caps),
        "fit": fits,
        "rungs": {"step_rule": STEP_RULE, "cache_type": a.cache_type,
                  "per_file": rung_recs},
        "stages": rows,
        "estimate": est,
        "verdict": ascii_only(plan_verdict(rep, blocked, fits, rung_recs,
                                          rows, est)),
        "exit_code": rep.exit_code(),
        "provenance": {
            "board_total_mib": ("MEASURED (machine.json)" if board is not None
                                else "UNKNOWN (no machine.json)"),
            "desktop_reserve_mib": ("MEASURED (machine.json)" if reserve
                                    else "UNKNOWN"),
            "weights": "MEASURED (file_bytes from the GGUF profile)",
            "kv_bytes_per_token": "DERIVED by the model profiler, carried here",
            "context_length": "MEASURED (GGUF header, via the model profile)",
            "rungs": "DERIVED from the fit; the rule is in rungs.step_rule",
            "stages": "DERIVED from capabilities[] + scripts/arms/*.json server "
                      "flags + the stage files' own gate sentences",
            "estimate": "DERIVED from the stage files' published hours scaled "
                        "by arm and rung counts -- a planning aid, not a "
                        "measurement",
            "compute_buffers": "UNKNOWN -- counted nowhere above; Stage 2 "
                               "measures them",
        },
    }

    dest = a.out or os.path.join(rdir, "plan.json")
    if a.dry_run:
        out.write("  --dry-run: nothing written\n")
    elif not profiles:
        out.write("  no plan written: there is nothing to plan.\n"
                  "  FIX: %s\n" % ascii_only(profile_writer_hint(a.slug)))
    else:
        try:
            d = os.path.dirname(os.path.abspath(dest))
            if d and not os.path.isdir(d):
                os.makedirs(d)
            with io.open(dest, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(plan, indent=1, sort_keys=False))
                fh.write("\n")
            out.write("  wrote %s\n" % os.path.relpath(
                dest, paths.repo_root()).replace(os.sep, "/"))
        except OSError as exc:
            out.write("  could not write %s: %s\n" % (dest, exc))
    out.write("\n")

    if a.json:
        json.dump(plan, out, indent=1)
        out.write("\n")
    return rep.exit_code()


if __name__ == "__main__":
    sys.exit(main())
