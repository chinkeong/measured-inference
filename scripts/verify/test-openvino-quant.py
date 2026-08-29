#!/usr/bin/env python3
"""Does scripts/lib/openvino_quant.py's ARITHMETIC hold? Asked without a GPU.

    python scripts/verify/test-openvino-quant.py
    python scripts/verify/test-openvino-quant.py --only groundtruth
    python scripts/verify/test-openvino-quant.py --list

WHY THIS EXISTS. Every `bpw_effective` this repository can publish against an
OpenVINO run comes out of that module, and until 2026-08-30 the only thing that
touched it was scripts/verify/probe-smoke-test.py, which imports it to prove it
LOADS. Loading is not arithmetic. A module whose whole job is to say that
6.5625 bits per weight in the file is 8.0104 bits per weight in memory had no
test that either number was right, and a wrong one is worse than no module at
all: it produces a figure that looks measured, carries a source reference, and
is off by the size of the rewrite it exists to describe.

WHAT IT IS GROUNDED IN, and this is the part that makes it a test rather than a
restatement. `results/openvino-groundtruth/` holds a MEASURED run - llama.cpp
d7bd3bf, OpenVINO 2026.3.1, device CPU, gemma-4-E2B-it-Q6_K.gguf, 600 per-tensor
records off a patched build. Its `requant.log` is READ HERE, all 600 lines, and
the module is made to predict every one of them:

    316 REQUANT, every one to Q8_0_C     284 SHARED     0 KEPT
    block_size 1536, 2048, 256, 4096, 6144, 12288 - the ROW WIDTH, never 32

The block_size line is the load-bearing one. `Q8_0_C` does not exist in the
GGUF format, and whether it is channel-wise or block-32 is the whole difference
between "Q6_K -> Q8_0_C adds bits and removes scales" and "Q6_K -> Q8_0_C is an
upgrade". The run settles it, so `_channelwise_bytes` is checked against the
six widths that were logged rather than against the six the source implies.

WHAT THIS MUST NOT CLAIM, taken from that directory's own README and repeated
here because a test file is where a caveat goes to be forgotten:

  * NOTHING ABOUT THE NPU. `Q4_0_128` and the F16 `token_embd.weight` case are
    the two rules that make a quant ladder degenerate and both are NPU-only.
    The tests below check that the module APPLIES them as its source table
    says; they are DERIVED-FROM-SOURCE and no run in this repository has ever
    exercised them. A green line here is not hardware evidence.
  * NOTHING ABOUT THE GPU DEVICE.
  * 0 KEPT IS UNTESTED, NOT DISPROVEN. A pure-Q6_K file leaves nothing eligible
    to keep, so the `default: return nullopt` branch had nothing to catch.
    `kept-branch-is-a-different-branch` exercises it on a mixed file and says
    plainly that the run did not.
  * `output.weight` WAS NEVER EXERCISED. Gemma ties it to `token_embd.weight`,
    so it never reached the buffer path. Rule 3 is checked from the table, not
    from the run, and the groundtruth replay expects no `output.weight` record.

WHAT IS A FIXTURE HERE, said out loud so no number below is mistaken for a
measurement. `requant.log` records each tensor's NAME and, for a rewrite, its
block_size - which is `ne[0]`, the row width. It does not record the second
dimension, so the replay gives every tensor ONE ROW. Channel-wise bits per
weight is a function of `ne[0]` alone, so the per-tensor geometry is exact and
only the whole-model aggregate is fixture-shaped; the replay therefore asserts
the census and the per-tensor conversions, and quotes no aggregate bpw. Source
types are assigned the same way: Q6_K for the 316 (the README's "pure-Q6_K
file", and `groundtruth-discriminates` shows the module would predict a KEPT
record for any other quantized type, which the run did not produce) and F32 for
the 284, where the module's answer is identical for every name in
NOT_QUANTIZED.

THE GGUF BLOCK TABLE IS IMPORTED, NOT COPIED. openvino_quant.py refuses to keep
one - "a second copy of it is a second thing that can be wrong" - so where a
file's own byte count is needed it comes from `GGML` in
scripts/quant-ladder/gguf-inspect.py, the same table the rest of the campaign
sizes tensors with.

Stdlib only, no pip, no GPU, no model file, no network. It reads three
files: the module under test, results/openvino-groundtruth/requant.log, and
scripts/quant-ladder/gguf-inspect.py for the block table above - the last one
on first use only, which every full run reaches through `blocked-bytes`.
"""

import argparse
import importlib.util
import io
import os
import re
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODULE = os.path.join(REPO, "scripts", "lib", "openvino_quant.py")
INSPECT = os.path.join(REPO, "scripts", "quant-ladder", "gguf-inspect.py")
REQUANT_LOG = os.path.join(REPO, "results", "openvino-groundtruth", "requant.log")

# The module under test, imported by name off scripts/lib - the same way every
# probe reaches it, so an import that only works from a test harness cannot
# pass here.
sys.path.insert(0, os.path.join(REPO, "scripts", "lib"))
import openvino_quant as ov                                            # noqa: E402


def _load_by_path(name, path):
    """Import a module whose filename is not an identifier (gguf-inspect.py)."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ggml type name -> (elements per block, bytes per block). Imported, never
# copied: see THE GGUF BLOCK TABLE IS IMPORTED in the header. Built on FIRST
# USE rather than at import, because importing this file must do no work -
# which is the defect scripts/quant-ladder/make-ladder-png.py shipped, and a
# test file is a poor place to repeat it.
_GGML_BY_NAME = {}


def ggml_block(type_name):
    """(elements per block, bytes per block) for one ggml type name."""
    if not _GGML_BY_NAME:
        for t in _load_by_path("gguf_inspect", INSPECT).GGML.values():
            _GGML_BY_NAME[t[0]] = (t[1], t[2])
    return _GGML_BY_NAME[type_name]


# ---------------------------------------------------------------------------
# THE MEASURED RUN, as constants, each one traceable to a line in
# results/openvino-groundtruth/README.md. Nothing here is derived.
# ---------------------------------------------------------------------------

MEASURED_REQUANT = 316
MEASURED_SHARED = 284
MEASURED_KEPT = 0
MEASURED_TOTAL = 600
MEASURED_TARGET = "Q8_0_C"          # every one of the 316
# Every block_size the run logged. It is the ROW WIDTH in each record, and 32 -
# what a block-32 Q8_0 would have shown - appears nowhere in 600 lines.
MEASURED_BLOCK_SIZES = (256, 1536, 2048, 4096, 6144, 12288)
MEASURED_N_LAYER = 35
MEASURED_N_EMBD = 1536
# The file's own type, from the run's header line `print_info: file type = Q6_K`.
MEASURED_FILE_TYPE = "Q6_K"


class Failure(Exception):
    """One assertion in one test."""


def need(cond, msg):
    if not cond:
        raise Failure(msg)


def close(a, b, tol=1e-9):
    return abs(float(a) - float(b)) <= tol


# ---------------------------------------------------------------------------
# The groundtruth log, parsed once
# ---------------------------------------------------------------------------

# `..REQUANT ggml_backend_openvino_buffer_set_tensor: blk.0.attn_q.weight to
#  Q8_0_C (u8, block_size=1536)` - the leading dots are the loader's progress
# meter, printed on the same line, and are stripped rather than matched.
RECORD_RE = re.compile(
    r"^\.*(REQUANT|SHARED|KEPT) ggml_backend_openvino_buffer_set_tensor: "
    r"(\S+?)(?: to (\S+) \(\w+, block_size=(\d+)\))?\s*$")


def read_groundtruth():
    """[(verdict, tensor name, target type or None, block_size or None)] x 600.

    Raises rather than returns short: a replay against half a log would pass
    every assertion below for the wrong reason.
    """
    if not os.path.exists(REQUANT_LOG):
        raise Failure("no %s - the measured run is the ground truth for every "
                      "assertion in this file" % REQUANT_LOG)
    out = []
    for line in io.open(REQUANT_LOG, encoding="utf-8", errors="replace"):
        m = RECORD_RE.match(line.rstrip("\n"))
        if not m:
            continue
        verdict, name, target, block = m.groups()
        out.append((verdict, name, target,
                    int(block) if block is not None else None))
    need(len(out) == MEASURED_TOTAL,
         "parsed %d per-tensor records from %s, the run recorded %d - the log "
         "or this file's regex has moved" % (len(out), REQUANT_LOG,
                                             MEASURED_TOTAL))
    return out


def groundtruth_tensors(records, requant_type=MEASURED_FILE_TYPE):
    """The 600 records as a model_profile() tensor table. A FIXTURE - see the
    header: one row each, because the log carries ne[0] and not ne[1].

    `requant_type` is the type the file gave the 316 rewritten tensors. Q6_K by
    default, which is what the README calls the model; passing anything else is
    how `groundtruth-discriminates` shows the module is reading the type rather
    than the verdict.
    """
    tensors = []
    for verdict, name, _target, block in records:
        if verdict == "REQUANT":
            ne0 = block
            src = requant_type
        else:
            # SHARED: passed through unchanged. The log does not carry the
            # type; llama.cpp keeps norm and scale tensors at F32, and every
            # name in NOT_QUANTIZED converts identically, so the fixture is
            # safe for the question being asked. ne[0] is not logged for these
            # either - it is unused, because nothing rewrites them.
            ne0 = MEASURED_N_EMBD
            src = "F32"
        block_elems, block_bytes = ggml_block(src)
        elements = ne0
        tensors.append({
            "name": name, "elements": elements, "ne0": ne0, "type": src,
            "bytes": elements / float(block_elems) * block_bytes})
    return tensors


# ---------------------------------------------------------------------------
# 1. the channel-wise layout, against the six widths the run logged
# ---------------------------------------------------------------------------

def t_channelwise_bytes():
    """ONE SCALE PER ROW: weights_per_block = ne[0], measured, not inferred.

    This is the module's load-bearing claim. If Q8_0_C were block-32 like the
    GGUF's Q8_0, then Q6_K -> Q8_0_C would be more bits at the SAME scale
    granularity, which is close enough to an upgrade that the module's refusal
    to call it one would be wrong. The run settles it: block_size is the row
    width in all 316 records and never 32.
    """
    seen = set()
    for ne0 in MEASURED_BLOCK_SIZES:
        for rows in (1, 7, 4096):
            elements = rows * ne0
            got = ov._channelwise_bytes(elements, ne0, 8, 16)
            # DERIVED, in one line, from the definition: 8 bits a weight plus
            # one fp16 scale for each ROW.
            want = elements * 1.0 + rows * 2.0
            need(close(got, want),
                 "_channelwise_bytes(%d, ne0=%d, 8, 16) = %r, one scale per "
                 "row makes it %r" % (elements, ne0, got, want))

            # And it must NOT be the file's block-32 geometry. A Q8_0 of the
            # same tensor carries elements/32 scales; the two agree only at
            # ne0 == 32, which the run never logged.
            block32 = elements * 1.0 + (elements / 32.0) * 2.0
            need(not close(got, block32),
                 "at ne0=%d the channel-wise byte count equals the block-32 "
                 "one (%r) - the whole distinction the measured run settled "
                 "has gone" % (ne0, got))
            need(got < block32,
                 "channel-wise (%r) is not smaller than block-32 (%r) at "
                 "ne0=%d, so it is not carrying FEWER scales" % (got, block32, ne0))
            seen.add(ne0)

    need(32 not in MEASURED_BLOCK_SIZES,
         "32 is in the measured block-size set, which is the one width that "
         "would make Q8_0_C the file's own Q8_0 geometry")

    # The 4 bits-a-weight sibling, same geometry.
    need(close(ov._channelwise_bytes(4096 * 5120, 5120, 4, 16),
               4096 * 5120 / 2.0 + 4096 * 2.0),
         "Q4_0_C's channel-wise arithmetic does not follow the same rule")

    # ne0 = 0 is the shape a caller gets from a tensor table that lost its
    # dims. It must not divide by zero, and it must not silently claim one
    # scale for a million weights either - it claims one, for one row.
    need(close(ov._channelwise_bytes(1000, 0, 8, 16), 1000 + 2.0),
         "ne0=0 does not fall back to a single row")
    return "6 measured widths x 3 row counts: one fp16 scale per ROW, never per 32"


# ---------------------------------------------------------------------------
# 2. the blocked layout
# ---------------------------------------------------------------------------

def t_blocked_bytes():
    """Q4_0_128 is block-128, and the file's Q4_0 is block-32. Four times fewer
    scales over the same weights, and the NAME barely moves - which is why the
    module carries a `block_change` note for exactly that pair."""
    for elements in (128, 1280, 1536 * 8):
        got = ov._blocked_bytes(elements, 128, 4, 16)
        want = elements * 0.5 + (elements / 128.0) * 2.0
        need(close(got, want),
             "_blocked_bytes(%d, 128, 4, 16) = %r, expected %r"
             % (elements, got, want))

    # The file's Q4_0, sized from the SAME imported block table the rest of the
    # campaign uses: 32 weights in 18 bytes.
    q40_elems, q40_bytes = ggml_block("Q4_0")
    need((q40_elems, q40_bytes) == (32, 18),
         "the imported block table no longer says Q4_0 is 32 weights in 18 "
         "bytes: %r" % ((q40_elems, q40_bytes),))
    elements = 128 * 100
    file_scales = elements / float(q40_elems)
    npu_scales = elements / 128.0
    need(close(file_scales / npu_scales, 4.0),
         "Q4_0 -> Q4_0_128 is not a factor of four in scale count: %r"
         % (file_scales / npu_scales))

    # Bits per weight, both ways, and they have to agree with the byte counts.
    need(close(ov.effective_bpw("Q4_0_128", 5120), 4.0 + 16.0 / 128.0),
         "Q4_0_128 bpw is not 4 + scale/128")
    need(close(ov.effective_bpw("Q4_0_128", 1536),
               ov.effective_bpw("Q4_0_128", 12288)),
         "Q4_0_128's bits per weight moved with the row width - it is a "
         "FIXED block size and must not")
    return "block-128 arithmetic, and 4x fewer scales than the file's Q4_0"


# ---------------------------------------------------------------------------
# 3. bytes and bits per weight are the same statement
# ---------------------------------------------------------------------------

def t_bytes_and_bpw_agree():
    """effective_bytes() and effective_bpw() are two views of one layout.

    They are separate functions with separate lambdas in EFFECTIVE_LAYOUT, so
    an edit can move one and leave the other; every published figure uses both.
    """
    for name in sorted(ov.EFFECTIVE_LAYOUT):
        for ne0 in MEASURED_BLOCK_SIZES:
            for rows in (1, 33):
                elements = rows * ne0
                by = ov.effective_bytes(name, elements, ne0)
                bp = ov.effective_bpw(name, ne0)
                need(close(by * 8.0 / elements, bp, 1e-9),
                     "%s at ne0=%d, %d row(s): bytes say %.6f bpw, bpw() says "
                     "%.6f" % (name, ne0, rows, by * 8.0 / elements, bp))
    need(ov.effective_bpw("NOT_A_TYPE", 1536) is None
         and ov.effective_bytes("NOT_A_TYPE", 10, 1536) is None,
         "an unknown effective type does not come back None, so a caller gets "
         "arithmetic on a layout nobody wrote")
    # F16 is the one type with no scale at all, and the NPU token_embd case
    # turns on it: 2 bytes a weight, flat.
    need(close(ov.effective_bytes("F16", 1536, 1536), 3072.0)
         and close(ov.effective_bpw("F16", 1536), 16.0),
         "F16 no longer costs 16 bits a weight with no scale")
    return ("bytes x 8 / elements == bpw for %d types x 6 widths"
            % len(ov.EFFECTIVE_LAYOUT))


# ---------------------------------------------------------------------------
# 4. the conversion table, rule by rule
# ---------------------------------------------------------------------------

def t_conversion_table():
    """Every rule at ggml-openvino-extra.cpp:252-273, and FIRST MATCH WINS.

    Rules 1 and 4 are NPU-only and DERIVED FROM SOURCE - no run in this
    repository has exercised them (results/openvino-groundtruth/README.md,
    "What it does not prove"). Rules 2, 3, 5 and 6 are the non-NPU rows, and
    the measured run confirms 2 and 5.
    """
    # rule 1 - token_embd.weight is F16 on NPU when the FILE says Q6_K
    r = ov.effective_type("token_embd", "Q6_K", "NPU")
    need(r["rule_n"] == 1 and r["effective"] == "F16" and r["changed"],
         "rule 1: token_embd Q6_K on NPU gave %r" % r)
    need("expands rather than re-quantises" in (r.get("note") or ""),
         "rule 1 lost the note that says this is the one case that EXPANDS")

    # rule 1 is conditional on the type: Q4_K on NPU falls through to rule 2
    r = ov.effective_type("token_embd", "Q4_K", "NPU")
    need(r["rule_n"] == 2 and r["effective"] == "Q8_0_C",
         "rule 1 fired for a non-Q6_K token_embd on NPU, or rule 2 did not "
         "catch it: %r" % r)

    # rule 2 - token_embd.weight is Q8_0_C on every other device, any type
    for dev in ("CPU", "GPU", "GPU.0", "GPU.1"):
        for src in ("Q6_K", "Q4_K", "Q8_0", "F16"):
            r = ov.effective_type("token_embd", src, dev)
            need(r["rule_n"] == 2 and r["effective"] == "Q8_0_C",
                 "rule 2: token_embd %s on %s gave %r" % (src, dev, r))

    # rule 3 - output.weight is Q8_0_C on EVERY device, any type. Untested by
    # the run: Gemma ties output.weight to token_embd, so it never reached the
    # buffer path. This checks the table, and the table only.
    for dev in ("CPU", "GPU", "NPU"):
        for src in ("Q6_K", "Q4_K", "Q8_0", "F32"):
            r = ov.effective_type("output", src, dev)
            need(r["rule_n"] == 3 and r["effective"] == "Q8_0_C",
                 "rule 3: output.weight %s on %s gave %r" % (src, dev, r))

    # rule 4 - on NPU every OTHER quantized tensor becomes Q4_0_128,
    # unconditionally. DERIVED FROM SOURCE.
    for src in ("Q8_0", "Q6_K", "Q5_K", "Q4_K", "Q4_1", "Q4_0", "IQ2_XXS"):
        r = ov.effective_type("block", src, "NPU")
        need(r["rule_n"] == 4 and r["effective"] == "Q4_0_128",
             "rule 4: block %s on NPU gave %r" % (src, r))
    need("block_change" in ov.effective_type("block", "Q4_0", "NPU"),
         "Q4_0 -> Q4_0_128 does not carry the block_change note, and the NAME "
         "is the only thing that barely moves in that conversion")
    # ... and NOT on an unquantized one. A norm rewritten to Q4_0_128 would be
    # a fabricated 4-bit tensor in a profile.
    for src in ov.NOT_QUANTIZED:
        r = ov.effective_type("block", src, "NPU")
        need(r["rule_n"] == 6 and r["effective"] == src and not r["changed"],
             "rule 4 fired on %s, which carries no quantisation: %r" % (src, r))

    # rule 5 - off NPU, Q6_K and Q5_K become Q8_0_C. CONFIRMED by the run.
    for dev in ("CPU", "GPU"):
        for src in ("Q6_K", "Q5_K"):
            r = ov.effective_type("block", src, dev)
            need(r["rule_n"] == 5 and r["effective"] == "Q8_0_C" and r["changed"],
                 "rule 5: block %s on %s gave %r" % (src, dev, r))
            need("MORE BITS AT COARSER SCALE GRANULARITY" in (r.get("note") or ""),
                 "rule 5 lost the wording that refuses to call this an "
                 "upgrade: %r" % r.get("note"))

    # rule 6 - everything else loads as the file holds it
    for dev in ("CPU", "GPU"):
        for src in ("Q8_0", "Q4_K", "Q4_0", "IQ4_XS", "F32", "F16"):
            r = ov.effective_type("block", src, dev)
            need(r["rule_n"] == 6 and r["effective"] == src
                 and not r["changed"] and r.get("note") is None,
                 "rule 6: block %s on %s gave %r" % (src, dev, r))

    # The device is never guessed, in either direction.
    r = ov.effective_type("block", "Q6_K", None)
    need(r["effective"] is None and r["changed"] is None and "device" in r["why"],
         "an unset device produced an answer instead of a reason: %r" % r)
    r = ov.effective_type("block", "Q6_K", "TPU")
    need(r["effective"] is None, "an unknown device produced an answer: %r" % r)

    try:
        ov.effective_type("norm", "F32", "CPU")
    except ValueError:
        pass
    else:
        raise Failure("an unknown role did not raise ValueError, so a "
                      "misspelled bucket converts as `block`")

    # Every rule in the table is reachable, and the table still ends in a
    # catch-all per role. An unreachable rule is a rule that was read wrong.
    seen = set()
    for role in ov.ROLES:
        for dev in ("CPU", "GPU", "NPU"):
            for src in ("Q6_K", "Q5_K", "Q4_K", "Q8_0", "F32"):
                got = ov.effective_type(role, src, dev)
                need(got["rule_n"] is not None,
                     "role=%s src=%s dev=%s fell through the table: %r"
                     % (role, src, dev, got))
                seen.add(got["rule_n"])
    need(seen == set(c["n"] for c in ov.CONVERSIONS),
         "rules %r are in CONVERSIONS and nothing reaches them"
         % sorted(set(c["n"] for c in ov.CONVERSIONS) - seen))
    return ("%d rules, first-match order, every one of them reachable"
            % len(seen))


# ---------------------------------------------------------------------------
# 5. which tensor is which
# ---------------------------------------------------------------------------

def t_role_of():
    """The table names two tensors and buckets everything else, so role_of is
    literal on purpose. Grounded: `output_norm.weight` is SHARED in the run -
    a classifier that put it in the `output` bucket would have this module
    reporting an F32 norm rewritten to Q8_0_C, which did not happen.
    """
    need(ov.role_of("token_embd.weight") == "token_embd", "token_embd.weight")
    need(ov.role_of("output.weight") == "output", "output.weight")
    for name in ("output_norm.weight", "blk.0.attn_output.weight",
                 "per_layer_model_proj.weight", "blk.34.proj.weight",
                 "token_embd.weight.bias", "", None):
        need(ov.role_of(name) == "block",
             "role_of(%r) is not `block`, and the conversion table names "
             "exactly two tensors" % (name,))

    # The run says so too: output_norm.weight is one of the 284 that passed
    # through, and if this module called it `output` it would predict Q8_0_C.
    names = dict((n, v) for v, n, _t, _b in read_groundtruth())
    need(names.get("output_norm.weight") == "SHARED",
         "the measured run no longer records output_norm.weight as SHARED")
    r = ov.effective_type(ov.role_of("output_norm.weight"), "F32", "CPU")
    need(not r["changed"],
         "the module rewrites output_norm.weight, and the run passed it "
         "through untouched: %r" % r)
    return "two named tensors, everything else `block`; output_norm checked "\
           "against the run"


# ---------------------------------------------------------------------------
# 6. the measured run, replayed through model_profile()
# ---------------------------------------------------------------------------

def t_groundtruth_replay():
    """All 600 records: does the module predict what the backend did?

    Device CPU, so rules 2, 5 and 6 are the only ones that can fire. Every
    number asserted here is a line in results/openvino-groundtruth/README.md.
    """
    records = read_groundtruth()
    counts = {}
    for verdict, _n, _t, _b in records:
        counts[verdict] = counts.get(verdict, 0) + 1
    need(counts.get("REQUANT") == MEASURED_REQUANT
         and counts.get("SHARED") == MEASURED_SHARED
         and counts.get("KEPT", 0) == MEASURED_KEPT,
         "the log no longer holds %d REQUANT / %d SHARED / %d KEPT: %r"
         % (MEASURED_REQUANT, MEASURED_SHARED, MEASURED_KEPT, counts))

    targets = set(t for v, _n, t, _b in records if v == "REQUANT")
    need(targets == {MEASURED_TARGET},
         "the run rewrote to %r, not to %s alone" % (sorted(targets),
                                                     MEASURED_TARGET))
    blocks = set(b for v, _n, _t, b in records if v == "REQUANT")
    need(blocks == set(MEASURED_BLOCK_SIZES),
         "the logged block sizes are %r, the README records %r"
         % (sorted(blocks), sorted(MEASURED_BLOCK_SIZES)))
    need(32 not in blocks,
         "a block_size of 32 appears in the log - Q8_0_C would then be the "
         "file's own Q8_0 geometry and the module's central claim would be "
         "wrong")

    # The census the README derives from the architecture: 35 layers x 9 weight
    # classes + token_embd once; 35 x 8 norm and scale classes + 4 model-level.
    def census(verdict):
        out = {}
        for v, name, _t, _b in records:
            if v != verdict:
                continue
            key = re.sub(r"^blk\.\d+\.", "blk.N.", name)
            out[key] = out.get(key, 0) + 1
        return out
    req, sha = census("REQUANT"), census("SHARED")
    per_layer_req = [k for k, n in req.items() if k.startswith("blk.N.")]
    need(len(per_layer_req) == 9 and all(req[k] == MEASURED_N_LAYER
                                         for k in per_layer_req),
         "the rewritten set is not 35 layers x 9 weight classes: %r" % req)
    need(req.get("token_embd.weight") == 1 and len(req) == 10,
         "the rewritten set is not the nine classes plus token_embd: %r"
         % sorted(req))
    per_layer_sha = [k for k, n in sha.items() if k.startswith("blk.N.")]
    need(len(per_layer_sha) == 8 and all(sha[k] == MEASURED_N_LAYER
                                         for k in per_layer_sha),
         "the shared set is not 35 layers x 8 norm and scale classes: %r" % sha)
    need(len(sha) - len(per_layer_sha) == 4,
         "the shared set no longer has exactly four model-level tensors: %r"
         % sorted(k for k in sha if not k.startswith("blk.N.")))
    need("output.weight" not in req and "output.weight" not in sha,
         "output.weight appears in the log - Gemma ties it to token_embd, "
         "which is why the README calls rule 3 unexercised")

    # Now the module's own answer, tensor for tensor.
    tensors = groundtruth_tensors(records)
    prof = ov.model_profile(tensors, "CPU", label="openvino-groundtruth")
    need(prof["tensors"] == MEASURED_TOTAL,
         "profiled %d tensors, the run recorded %d" % (prof["tensors"],
                                                       MEASURED_TOTAL))
    need(prof["tensors_rewritten"] == MEASURED_REQUANT,
         "the module rewrites %d of the 600; the backend rewrote %d"
         % (prof["tensors_rewritten"], MEASURED_REQUANT))
    need(prof["effective_types"].get(MEASURED_TARGET) == MEASURED_REQUANT,
         "the module does not send all %d to %s: %r"
         % (MEASURED_REQUANT, MEASURED_TARGET, prof["effective_types"]))
    need(prof["effective_types"].get("F32") == MEASURED_SHARED,
         "the module does not leave all %d shared tensors alone: %r"
         % (MEASURED_SHARED, prof["effective_types"]))

    # Per record, not just in aggregate: same name, same verdict.
    by_name = {}
    for t in tensors:
        role = ov.role_of(t["name"])
        by_name[t["name"]] = ov.effective_type(role, t["type"], "CPU")
    wrong = []
    for verdict, name, target, _b in records:
        got = by_name[name]
        predicted = "REQUANT" if got["changed"] else "SHARED"
        if predicted != verdict or (verdict == "REQUANT"
                                    and got["effective"] != target):
            wrong.append((name, verdict, target, predicted, got["effective"]))
    need(not wrong,
         "%d of %d records disagree with the module. First five: %r"
         % (len(wrong), len(records), wrong[:5]))

    # KEPT is what a quantized tensor left alone by rule 6 would have been,
    # and there are none - which is what the README says a pure-Q6_K file
    # should produce, and is NOT evidence the branch works.
    kept = [t for t in tensors
            if ov.is_quantized(t["type"])
            and not by_name[t["name"]]["changed"]]
    need(not kept,
         "the module predicts %d KEPT record(s) and the run logged 0: %r"
         % (len(kept), [t["name"] for t in kept[:5]]))

    need(prof["collapse"]["degenerate"] is False,
         "a CPU profile came back degenerate - rule 4 is NPU-only")
    need(prof["device"] == "CPU" and prof["backend"] == "openvino",
         "the profile does not carry the device it was computed for: %r"
         % [prof.get("device"), prof.get("backend")])
    return ("600 records replayed: %d REQUANT all to %s, %d SHARED, %d KEPT, "
            "every name agreeing" % (MEASURED_REQUANT, MEASURED_TARGET,
                                     MEASURED_SHARED, MEASURED_KEPT))


def t_groundtruth_discriminates():
    """The replay passes because the module READS THE TYPE, not because it
    agrees with everything.

    Retype the 316 as Q8_0 and rule 5 stops firing: the module then predicts
    315 KEPT records on CPU - the 316 less token_embd.weight, which rule 2
    rewrites whatever type it arrives as, and which is asserted separately
    below. The run logged zero, which is how the fixture's "these were Q6_K"
    assumption is checked rather than assumed.
    """
    records = read_groundtruth()
    tensors = groundtruth_tensors(records, requant_type="Q8_0")
    prof = ov.model_profile(tensors, "CPU")
    need(prof["tensors_rewritten"] == 1,
         "with a Q8_0 body only token_embd.weight should still be rewritten "
         "(rule 2); the module rewrote %d" % prof["tensors_rewritten"])
    kept = MEASURED_REQUANT - 1
    need(prof["effective_types"].get("Q8_0") == kept,
         "the module does not leave the %d Q8_0 body tensors alone: %r"
         % (kept, prof["effective_types"]))
    need(kept != MEASURED_KEPT,
         "this control asserts nothing: it predicts the same KEPT count the "
         "run measured")
    return ("retyped to Q8_0 the module predicts %d KEPT; the run logged %d, "
            "so the 316 were Q6_K or Q5_K" % (kept, MEASURED_KEPT))


def t_kept_branch_is_a_different_branch():
    """0 KEPT IS UNTESTED, NOT DISPROVEN - and here is the branch, exercised.

    A pure-Q6_K file leaves nothing eligible to keep, so the run could not
    reach `default: return nullopt`. A mixed file does: on CPU, Q4_K body
    tensors are rule 6 and Q6_K body tensors are rule 5, in one profile.
    Nothing in this test is evidence about the backend; it is evidence that
    the module has the branch and that it is not the one the run exercised.
    """
    tensors = [
        {"name": "token_embd.weight", "elements": 1536, "ne0": 1536,
         "type": "Q6_K", "bytes": 1536 / 256.0 * 210},
        {"name": "blk.0.ffn_down.weight", "elements": 12288, "ne0": 12288,
         "type": "Q6_K", "bytes": 12288 / 256.0 * 210},
        {"name": "blk.0.attn_q.weight", "elements": 1536, "ne0": 1536,
         "type": "Q4_K", "bytes": 1536 / 256.0 * 144},
        {"name": "blk.0.attn_k.weight", "elements": 1536, "ne0": 1536,
         "type": "Q8_0", "bytes": 1536 / 32.0 * 34},
        {"name": "blk.0.attn_norm.weight", "elements": 1536, "ne0": 1536,
         "type": "F32", "bytes": 1536 * 4},
    ]
    prof = ov.model_profile(tensors, "CPU")
    kept = [c for c in prof["conversions"]
            if not c["changed"] and ov.is_quantized(c["source"])]
    need(sorted(c["source"] for c in kept) == ["Q4_K", "Q8_0"],
         "the KEPT branch did not catch the two ineligible quantized types: %r"
         % [(c["source"], c["effective"]) for c in prof["conversions"]])
    need(all(c["rule_n"] == 6 for c in kept),
         "the kept tensors did not come out of rule 6: %r"
         % [(c["source"], c["rule_n"]) for c in kept])
    need(prof["collapse"]["distinct_in"] == 3
         and prof["collapse"]["distinct_out"] == 3,
         "three quantized types went in and the CPU profile does not report "
         "three coming out: %r" % prof["collapse"])
    need(prof["collapse"]["degenerate"] is False,
         "a CPU profile is degenerate, and only rule 4 collapses a ladder")

    # The same file on NPU is the opposite: three in, one out.
    npu = ov.model_profile(tensors, "NPU")
    need(npu["collapse"]["distinct_in"] == 3
         and npu["collapse"]["distinct_out"] == 1
         and npu["collapse"]["degenerate"] is True,
         "the same file on NPU is not reported degenerate: %r" % npu["collapse"])
    return "rule 6 catches Q4_K and Q8_0 on CPU - the branch 0 KEPT left untested"


# ---------------------------------------------------------------------------
# 7. the collapse: a quant ladder on the NPU is degenerate
# ---------------------------------------------------------------------------

def _arm(body_type, embd_type="Q4_K", n_layer=4):
    """One ladder arm as a tensor table: a token_embd plus a body of one type.

    Bytes come from the imported GGUF block table, so the FILE figure in each
    profile is the real one for that type.
    """
    def size(t, elements):
        be, bb = ggml_block(t)
        return elements / float(be) * bb
    out = [{"name": "token_embd.weight", "elements": 262144 * 1536,
            "ne0": 1536, "type": embd_type,
            "bytes": size(embd_type, 262144 * 1536)}]
    for i in range(n_layer):
        for cls, ne0, rows in (("attn_q", 1536, 2048), ("ffn_down", 12288, 1536)):
            out.append({"name": "blk.%d.%s.weight" % (i, cls),
                        "elements": ne0 * rows, "ne0": ne0, "type": body_type,
                        "bytes": size(body_type, ne0 * rows)})
        out.append({"name": "blk.%d.attn_norm.weight" % i, "elements": 1536,
                    "ne0": 1536, "type": "F32", "bytes": 1536 * 4})
    return out


def t_npu_collapse_and_compare_arms():
    """A LADDER ON THE NPU MEASURES ITS token_embd AND NOTHING ELSE.

    DERIVED FROM SOURCE. Rule 4 is NPU-only and no run in this repository has
    exercised it; this asserts that the module computes the collapse its table
    implies, and that compare_arms() names the arms before they are run rather
    than after they produce a flat curve (rule 25).
    """
    arms = {"q8": _arm("Q8_0"), "q6k": _arm("Q6_K"),
            "q4km": _arm("Q4_K"), "q4_0": _arm("Q4_0")}
    npu = dict((k, ov.model_profile(v, "NPU", label=k))
               for k, v in arms.items())

    for k, p in npu.items():
        need(p["collapse"]["effective_types_in_blocks"] == ["Q4_0_128"],
             "%s: the NPU body did not collapse to Q4_0_128: %r"
             % (k, p["collapse"]))
        need("Rule 30" in (p["collapse"]["note"] or "")
             or p["collapse"]["distinct_in"] == 1,
             "%s: a single-type file reported as a collapse: %r"
             % (k, p["collapse"]))
    need(all(p["collapse"]["degenerate"] is False for p in npu.values()),
         "one file holding one quantized type is not a collapse of a ladder - "
         "degenerate must describe the FILE, not the sweep")

    cmp_ = ov.compare_arms(npu)
    need(cmp_["arms"] == 4 and cmp_["distinct_weight_sets"] == 1,
         "four NPU arms differing only in body type run %d distinct weight "
         "set(s); rule 4 makes it 1: %r"
         % (cmp_["distinct_weight_sets"], cmp_["groups"]))
    need(sorted(list(cmp_["identical_arms"].values())[0])
         == ["q4_0", "q4km", "q6k", "q8"],
         "compare_arms did not name all four as identical: %r"
         % cmp_["identical_arms"])
    need("BYTE-IDENTICAL" in cmp_["verdict"] and "variance" in cmp_["verdict"],
         "the verdict does not say what running these as rungs would measure: "
         "%r" % cmp_["verdict"])

    # The one thing that can still separate two NPU arms: token_embd, and only
    # when exactly one of them shipped it as Q6_K (rule 1).
    split = dict(npu)
    split["q6k-embd"] = ov.model_profile(_arm("Q4_K", embd_type="Q6_K"),
                                         "NPU", label="q6k-embd")
    c2 = ov.compare_arms(split)
    need(c2["distinct_weight_sets"] == 2,
         "a Q6_K token_embd on NPU does not separate an arm: %r" % c2["groups"])
    need(ov.ladder_signature(split["q6k-embd"])
         != ov.ladder_signature(split["q4km"]),
         "the two signatures are equal, so rule 1 changed nothing")

    # And OFF the NPU the same four arms are four different things.
    cpu = dict((k, ov.model_profile(v, "CPU", label=k)) for k, v in arms.items())
    c3 = ov.compare_arms(cpu)
    need(c3["distinct_weight_sets"] > 1,
         "the same four files collapse on CPU too, and rule 4 is NPU-only: %r"
         % c3["groups"])
    need(all(p["collapse"]["degenerate"] is False for p in cpu.values()),
         "a CPU profile came back degenerate")
    return ("4 NPU arms -> 1 weight set; a Q6_K token_embd splits it to 2; the "
            "same 4 stay distinct on CPU")


def t_ladder_signature():
    """Two arms are the same weights when their signature is, and a byte total
    is not a signature: two different files can round to the same count."""
    a = ov.model_profile(_arm("Q6_K"), "CPU", label="a")
    b = ov.model_profile(_arm("Q5_K"), "CPU", label="b")
    need(ov.ladder_signature(a) == ov.ladder_signature(b),
         "Q6_K and Q5_K bodies both become Q8_0_C off NPU (rule 5), so these "
         "run the same weights and must share a signature")
    need(a["bpw_file_tensor_table"] != b["bpw_file_tensor_table"],
         "this test proves nothing: the two files have the same bits per "
         "weight to begin with")
    need(ov.ladder_signature(a) != ov.ladder_signature(
        ov.model_profile(_arm("Q4_K"), "CPU", label="c")),
         "a Q4_K body is NOT rewritten off NPU and must not share a signature "
         "with a Q6_K one")
    need(ov.ladder_signature(ov.model_profile(_arm("Q6_K"), None)) is None,
         "a profile with no resolved device produced a signature, which would "
         "group arms by a device nobody selected")
    need(ov.ladder_signature(a).startswith("CPU|"),
         "the signature does not carry the device: %r" % ov.ladder_signature(a))
    return "signature groups by effective type, and refuses without a device"


# ---------------------------------------------------------------------------
# 8. the scale width, and the sensitivity that is carried past the doubt
# ---------------------------------------------------------------------------

def t_scale_bits_sensitivity():
    """SCALE_BITS = 16, read from source; the f32 figure rides along anyway.

    The module computes `bpw_effective_if_f32_scale` on every profile and says
    a bound that costs nothing to carry is worth carrying past the day it
    stopped being needed. That makes it two arithmetic paths, and the second
    one has no caller to notice when it breaks.
    """
    need(ov.SCALE_BITS == 16,
         "SCALE_BITS is %r; the source reading at %s says fp16"
         % (ov.SCALE_BITS, ov.SOURCE["scale_element_type"]))

    tensors = _arm("Q6_K")
    p16 = ov.model_profile(tensors, "CPU")
    p32 = ov.model_profile(tensors, "CPU", scale_bits=32)
    need(close(p16["bpw_effective_if_f32_scale"], p32["bpw_effective"], 1e-12),
         "the f32 sensitivity carried on the 16-bit profile (%r) is not the "
         "figure a 32-bit profile computes (%r)"
         % (p16["bpw_effective_if_f32_scale"], p32["bpw_effective"]))
    need(p32["bpw_effective"] > p16["bpw_effective"],
         "a 32-bit scale is not dearer than a 16-bit one: %r vs %r"
         % (p32["bpw_effective"], p16["bpw_effective"]))
    need(p16["scale_bits"] == 16 and p32["scale_bits"] == 32,
         "the profile does not record which scale width produced its number")

    # And by how much, derived: one extra 16-bit scale per ROW on every
    # channel-wise tensor, spread over every weight in the model.
    rewritten = [t for t in tensors
                 if ov.effective_type(ov.role_of(t["name"]), t["type"],
                                      "CPU")["changed"]]
    extra_bits = sum(t["elements"] // t["ne0"] * 16 for t in rewritten)
    params = sum(t["elements"] for t in tensors)
    need(close(p32["bpw_effective"] - p16["bpw_effective"],
               extra_bits / float(params), 1e-9),
         "the 16 -> 32 bit move costs %.9f bpw; one extra scale per rewritten "
         "row over %d params is %.9f"
         % (p32["bpw_effective"] - p16["bpw_effective"], params,
            extra_bits / float(params)))

    # A single channel-wise tensor, at each measured width, both ways.
    for ne0 in MEASURED_BLOCK_SIZES:
        need(close(ov.effective_bpw("Q8_0_C", ne0, 32)
                   - ov.effective_bpw("Q8_0_C", ne0, 16), 16.0 / ne0),
             "at ne0=%d the scale-width difference is not 16 bits over the "
             "row" % ne0)
    # Q4_0_128 is a FIXED block, so the same move costs the same everywhere.
    need(close(ov.effective_bpw("Q4_0_128", 1536, 32)
               - ov.effective_bpw("Q4_0_128", 1536, 16), 16.0 / 128.0),
         "Q4_0_128's scale-width sensitivity is not 16 bits per 128 weights")
    # F16 carries no scale, so it cannot move at all.
    need(close(ov.effective_bpw("F16", 1536, 32),
               ov.effective_bpw("F16", 1536, 16)),
         "F16's bits per weight moved with the scale width, and F16 has no "
         "scale")

    warn = " ".join(p16["warnings"])
    need("16 bits" in warn and "32-bit scale" in warn,
         "the profile's warnings no longer state the scale width and the "
         "alternative: %r" % p16["warnings"])
    return "f32 sensitivity == a 32-bit profile, and the delta is one scale a row"


# ---------------------------------------------------------------------------
# 9. what a profile refuses to do
# ---------------------------------------------------------------------------

def t_profile_refuses_and_warns():
    """The conditions travel with the number, or there is no number.

    Rule 3: a figure without its conditions is unfalsifiable. This module's
    conditions are the device, the scale width, and that the whole thing is
    DERIVED from a table - so a profile that lost any of them would publish a
    bits-per-weight nobody can falsify.
    """
    p = ov.model_profile(_arm("Q6_K"), None)
    need(p["bpw_effective"] is None and p["why"],
         "an unset device produced a bits-per-weight: %r" % p)

    try:
        ov.model_profile([{"name": "x", "elements": 10, "ne0": 5,
                           "type": "Q6_K"}], "CPU")
    except KeyError as exc:
        need("bytes" in str(exc),
             "the missing key is not named in the error: %s" % exc)
    else:
        raise Failure("a tensor with no `bytes` contributed a silent zero "
                      "instead of raising")

    p = ov.model_profile(_arm("Q6_K"), "CPU")
    warn = " ".join(p["warnings"])
    need("DERIVED from a table" in warn,
         "the profile no longer says it is derived: %r" % p["warnings"])
    for token in (ov.MEASURED["run_utc"], ov.MEASURED["device"],
                  ov.MEASURED["evidence"], str(ov.MEASURED["requant"]),
                  str(ov.MEASURED["shared"]), str(ov.MEASURED["kept"])):
        need(token in warn,
             "the profile's provenance warning does not carry %r: %r"
             % (token, p["warnings"]))
    need("NOTHING about NPU or GPU" in warn,
         "the profile stopped saying what the measured run does not cover")

    npu = ov.model_profile(_arm("Q6_K"), "NPU")
    nwarn = " ".join(npu["warnings"])
    need("NPU is a REQUEST, not a fact" in nwarn
         and ov.SOURCE["device_log_line"] in nwarn,
         "an NPU profile does not warn that the device is a request and name "
         "the line that reports the resolved one: %r" % npu["warnings"])

    # A ggml type the CALLER's block table could not name must break the FILE
    # figure loudly and leave the EFFECTIVE one standing, because only the file
    # side needs a block table. Both shapes gguf-inspect.py can hand over: a
    # numbered fallback, and a name nobody has registered.
    odd = [{"name": "blk.0.attn_q.weight", "elements": 1536, "ne0": 1536,
            "type": "TYPE_42", "bytes": 0},
           {"name": "blk.1.attn_q.weight", "elements": 1536, "ne0": 1536,
            "type": "NF4", "bytes": 0}]
    p = ov.model_profile(odd, "NPU")
    need(p["unrecognised_source_types"] == ["NF4", "TYPE_42"],
         "an unnameable ggml type was not flagged: %r"
         % p["unrecognised_source_types"])
    need(p["tensors_rewritten"] == 2,
         "an unnameable type was not treated as quantized on NPU, which is "
         "the assumption that OVERSTATES the rewrite and is the safe one")
    need(any("bpw_file_tensor_table above reads LOW" in w for w in p["warnings"]),
         "the unknown type does not warn that the FILE figure is wrong: %r"
         % p["warnings"])
    need(p["bpw_effective"] is not None,
         "the effective figure went away too, and the rewritten type is known")

    # backend_effect: the three kinds, and no fourth.
    need(ov.backend_effect("cuda")["kind"] == "passthrough", "cuda")
    need(ov.backend_effect("openvino", "NPU")["kind"] == "rewrite", "openvino NPU")
    need(ov.backend_effect("openvino")["kind"] == "unknown",
         "openvino with no device is not `unknown`, so a device nobody "
         "selected decides which rules fired")
    need(ov.backend_effect("rocm")["kind"] == "unknown", "rocm")
    need(ov.backend_effect(None)["kind"] == "unknown", "no backend")
    kinds = set(ov.backend_effect(b)["kind"]
                for b in ("cuda", "vulkan", "metal", "cpu", "openvino",
                          "rocm", "sycl", "nonsense", None, ""))
    need(kinds <= {"passthrough", "rewrite", "unknown"},
         "backend_effect grew a fourth kind: %r" % sorted(kinds))
    return "no device, no number; missing bytes raises; provenance in every warning"


# ---------------------------------------------------------------------------
# 10. the sentence the module is not allowed to write
# ---------------------------------------------------------------------------

def t_describe_change_never_says_upgrade():
    """Q6_K -> Q8_0_C adds bits AND removes scales, and which is closer to the
    F32 original is a perplexity question nobody here has measured. The module
    owns the wording so a caller cannot invent a verb; this owns the wording's
    shape."""
    banned = ("upgrade", "lossless", "better", "improves", "improvement")
    for src in ("Q6_K", "Q5_K", "Q4_K", "Q8_0", "IQ2_XXS"):
        note = ov.describe_change(src, "Q8_0_C") or ""
        need(note, "no wording for %s -> Q8_0_C" % src)
        low = note.lower()
        for word in banned:
            need(word not in low or "not an upgrade" in low
                 or "not lossless" in low,
                 "%s -> Q8_0_C is described with %r: %r" % (src, word, note))
        need("ROW" in note or "row" in note,
             "the wording for %s -> Q8_0_C does not mention the row, which is "
             "the whole change: %r" % (src, note))
    need(ov.describe_change("Q6_K", "Q6_K") is None,
         "a conversion that changed nothing produced wording")
    note = ov.describe_change("Q4_K", "Q4_0_128") or ""
    need("identical weights" in note,
         "the Q4_0_128 wording no longer says two files land on the same "
         "weights: %r" % note)
    return "no upgrade, no lossless; the row is named in every Q8_0_C sentence"


TESTS = (
    ("channelwise-bytes", t_channelwise_bytes),
    ("blocked-bytes", t_blocked_bytes),
    ("bytes-and-bpw-agree", t_bytes_and_bpw_agree),
    ("conversion-table", t_conversion_table),
    ("role-of", t_role_of),
    ("groundtruth-replay", t_groundtruth_replay),
    ("groundtruth-discriminates", t_groundtruth_discriminates),
    ("kept-branch-is-a-different-branch", t_kept_branch_is_a_different_branch),
    ("npu-collapse", t_npu_collapse_and_compare_arms),
    ("ladder-signature", t_ladder_signature),
    ("scale-bits-sensitivity", t_scale_bits_sensitivity),
    ("profile-refuses-and-warns", t_profile_refuses_and_warns),
    ("describe-change", t_describe_change_never_says_upgrade),
)


def run_one(name, fn):
    """(name, seconds, note, error). Never raises."""
    t0, note, err = time.time(), None, None
    try:
        note = fn()
    except Failure as exc:
        err = str(exc)
    except Exception as exc:                   # a broken test is a failed test
        import traceback
        err = "%s: %s\n%s" % (type(exc).__name__, exc,
                              traceback.format_exc()[-900:])
    return name, time.time() - t0, note, err


def main():
    ap = argparse.ArgumentParser(
        description="Check scripts/lib/openvino_quant.py's arithmetic against "
                    "results/openvino-groundtruth/. No GPU, no model, no pip.")
    ap.add_argument("--only", metavar="SUBSTRING", default=None,
                    help="run only tests whose name contains this")
    ap.add_argument("--list", action="store_true", help="list the tests")
    a = ap.parse_args()

    if a.list:
        for name, fn in TESTS:
            print("%-34s %s" % (name, (fn.__doc__ or "").splitlines()[0]))
        return 0

    chosen = [(n, f) for n, f in TESTS if not a.only or a.only in n]
    if not chosen:
        print("no test matches %r" % a.only)
        return 2

    print("=" * 78)
    print("OPENVINO QUANT ARITHMETIC - the table, and the run that checked it")
    print("=" * 78)
    print("module   : %s" % os.path.relpath(MODULE, REPO).replace("\\", "/"))
    print("ground   : %s" % os.path.relpath(REQUANT_LOG, REPO).replace("\\", "/"))
    print("measured : %d REQUANT (all %s), %d SHARED, %d KEPT on device %s"
          % (MEASURED_REQUANT, MEASURED_TARGET, MEASURED_SHARED, MEASURED_KEPT,
             ov.MEASURED["device"]))
    print("NOT measured anywhere: the NPU rules (Q4_0_128, the F16 token_embd "
          "case), the GPU\n          device, the KEPT branch and "
          "output.weight. Those tests read the\n          source table and "
          "say so; a green line below is not hardware evidence.\n")

    failures, t_all = [], time.time()
    for name, fn in chosen:
        name, secs, note, err = run_one(name, fn)
        if err is None:
            print("  ok    %-34s %5.2fs  %s" % (name, secs, note))
        else:
            print("  FAIL  %-34s %5.2fs" % (name, secs))
            for line in err.strip().splitlines():
                print("        | %s" % line[:150])
            failures.append(name)

    print()
    print("=" * 78)
    if failures:
        print("%d of %d FAILED in %.1f s: %s"
              % (len(failures), len(chosen), time.time() - t_all,
                 ", ".join(failures)))
        print("Every bpw_effective this repository can publish comes out of "
              "this arithmetic.")
    else:
        print("all %d passed in %.1f s - channel-wise and blocked layouts, the "
              "six\nconversion rules, the 600-record replay, the NPU collapse "
              "and the f32 scale." % (len(chosen), time.time() - t_all))
    print("=" * 78)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
