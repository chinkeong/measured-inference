#!/usr/bin/env python3
"""What the OpenVINO backend LOADS, when the file on disk says something else.

    from openvino_quant import backend_effect, effective_type, model_profile

    backend_effect("openvino", "NPU")        -> the backend rewrites; here is how
    effective_type("output", "Q6_K", "NPU")  -> Q8_0_C, and the rule that did it
    model_profile(tensors, "NPU")            -> what a ladder arm really measures

WHY THIS FILE EXISTS. `bits_per_weight` in this repository is measured from the
GGUF -- file bytes times eight over the parameter count summed from the tensor
table -- and then ASSUMED to describe the weights that ran. On every ggml
backend this campaign has used, that assumption holds: the file's block layouts
are what the kernels consume. On the OpenVINO backend it is false. The backend
REQUANTISES tensors at load, silently, and a quant ladder run on its NPU device
is a ladder whose arms are the same weights.

That makes it a rule 3 problem and a rule 30 problem at once. Rule 3: a number
without its conditions is unfalsifiable, and "4.82 bits per weight" published
against an OpenVINO run carries a condition -- the backend rewrote it -- that
nothing in the artefact records. Rule 30: arms compare only inside one sweep,
and an OpenVINO arm is not comparable to a CUDA arm even when the file is
byte-identical, because the weights are not.

THE SOURCE, READ 2026-08-29 from ggml-org/llama.cpp master. The OpenVINO
backend was merged 2026-03-14 and lives at `ggml/src/ggml-openvino/`. The
conversion table is `ggml-openvino-extra.cpp:252-273`:

    token_embd.weight -> F16 if (NPU and the file's type is Q6_K), else Q8_0_C
                                                            [ALWAYS, any device]
    output.weight     -> Q8_0_C                             [ALWAYS, any device]
    if the device is NPU -> Q4_0_128, whatever the tensor's type was
    otherwise, Q6_K and Q5_K -> Q8_0_C

It is a real rewrite and not a reinterpretation: `requantize_to_buffers`
(`ggml/src/ggml-openvino/ggml-quants.cpp:841`) dequantises to F32 and
re-quantises from there. The one escape, `no_requant`, is gated on `use_bias`
and is asserted test-only at `ggml-quants.cpp:1016`.

TWO OF THE THREE EFFECTIVE TYPES DO NOT EXIST IN THE GGUF FORMAT.

  * `Q8_0_C` and `Q4_0_C` are CHANNEL-WISE: `weights_per_block = tensor->ne[0]`,
    one scale for a whole ROW. A 5,120-wide row carries one scale where the
    file's Q8_0 carried 160. So Q6_K -> Q8_0_C is MORE BITS AT COARSER SCALE
    GRANULARITY. It is not an upgrade, it is not lossless, and it must never be
    described as either -- 6.56 bpw with a scale every 256 weights and 8.00 bpw
    with a scale every 5,120 weights are two different representations and
    neither dominates the other. `describe_change()` below returns wording that
    holds this line; use it rather than inventing a verb.
  * `Q4_0_128` is `weights_per_block = 128`. The file's Q4_0 is block-32. Same
    name, four times fewer scales, a different representation -- so a Q4_0 file
    on the NPU is rewritten too, and the rewrite is invisible in the name.

WHAT THIS MEANS FOR A LADDER. On NPU every quantized tensor that is not
`token_embd.weight` or `output.weight` becomes Q4_0_128 regardless of what the
file held. Q8_0, Q6_K, Q5_K, Q4_K_M, Q4_1 and Q4_0 all collapse to one
representation; the only thing that can still separate two arms is
`token_embd.weight`, and only when exactly one of them shipped it as Q6_K. A
QUANT LADDER ON THE NPU IS DEGENERATE. `model_profile()` computes the collapse
and `compare_arms()` names the arms that are the same weights.

AND IT IS SILENT. The four `GGML_LOG_DEBUG` lines that would report a tensor
changing type are written and COMMENTED OUT at `ggml-openvino.cpp:332-346`.
`/props->description` carries only `ov::get_openvino_version().description`
(`ggml-openvino.cpp:1546`) -- the version string, nothing about quantisation.
Exactly one line is capturable from an ordinary run:

    GGML_LOG_INFO("OpenVINO: using device %s\\n", ...)   ggml-openvino.cpp:1526

emitted once in `ggml_openvino_init()`, printing the RESOLVED device AFTER
availability fallback. It does not say a tensor was rewritten, but it does
catch a silent NPU -> CPU downgrade, which changes which conversion rules fired
and therefore changes every number below. Capture it. A profile computed for
NPU against a run that fell back to CPU is the wrong profile, and nothing else
in the log will say so.

THE CHEAP ROUTE TO GROUND TRUTH, if you want a record instead of this table.
The per-tensor requantisation logging already exists. It is fully written and
commented out at `ggml/src/ggml-openvino/ggml-openvino.cpp:332-346`.
UNCOMMENT THOSE FOUR LINES and build with debug logging on:

    sed -n '332,346p' ggml/src/ggml-openvino/ggml-openvino.cpp   # look first
    # uncomment the four GGML_LOG_DEBUG calls
    cmake -B build -DGGML_OPENVINO=ON -DCMAKE_BUILD_TYPE=RelWithDebInfo
    cmake --build build -j
    ./build/bin/llama-cli -m model.gguf -v -n 1 2>&1 | tee requant.log

That gives an authoritative per-tensor record at load time -- name, type in,
type out -- against which everything this module computes is checkable. It
costs one build. `GGML_OPENVINO_DUMP_IR=1` is the second witness (rule 4): it
writes the OpenVINO IR that actually ran, and the IR's constant types are the
answer independent of any log line.

WHAT THIS MODULE WILL NOT DO. It will not size a tensor from the GGUF's own
block table. That table lives in `scripts/quant-ladder/gguf-inspect.py` and a
second copy of it is a second thing that can be wrong; every function here that
needs a source tensor's byte count takes it from the caller, who already has
it. It owns the layouts of the three types the OpenVINO backend INVENTS, and
nothing else.

Stdlib only. Python 3.8+. No network, no GPU, no model load.
"""

import os

# ---------------------------------------------------------------------------
# where every fact below came from
# ---------------------------------------------------------------------------

SOURCE = {
    "repo": "ggml-org/llama.cpp",
    "ref": "master",
    "read_utc": "2026-08-29",
    "backend_merged": "2026-03-14",
    "conversion_table": "ggml/src/ggml-openvino/ggml-openvino-extra.cpp:252-273",
    "requantiser": "ggml/src/ggml-openvino/ggml-quants.cpp:841 "
                   "(requantize_to_buffers: dequantises to F32, re-quantises)",
    "no_requant_escape": "ggml/src/ggml-openvino/ggml-quants.cpp:1016 "
                         "(gated on use_bias, asserted test-only)",
    "commented_out_logging": "ggml/src/ggml-openvino/ggml-openvino.cpp:332-346",
    "device_log_line": "ggml/src/ggml-openvino/ggml-openvino.cpp:1526",
    "props_description": "ggml/src/ggml-openvino/ggml-openvino.cpp:1546",
    "props_description_holds": "ov::get_openvino_version().description -- the "
                               "OpenVINO version string, and nothing about "
                               "quantisation",
    "runtime_pinned": "OpenVINO 2026.3.1 (2026.3.1.22476.56d9685302d)",
    "note": "line numbers are from master as read on the date above; when "
            "upstream moves, re-read the file named in conversion_table before "
            "trusting anything here",
}

# The ground-truth route, exposed so a script can print it rather than a reader
# having to find this docstring. See the module docstring for the full recipe.
GROUND_TRUTH = {
    "how": "uncomment the four GGML_LOG_DEBUG calls at %s and build with debug "
           "logging: they are already written, they name every tensor whose "
           "type changed, and they cost one build"
           % "ggml/src/ggml-openvino/ggml-openvino.cpp:332-346",
    "second_witness": "GGML_OPENVINO_DUMP_IR=1 writes the OpenVINO IR that "
                      "actually ran; its constant types are the answer without "
                      "any log line (rule 4: two cheap witnesses)",
    "what_an_ordinary_run_tells_you": "one line, and it names the RESOLVED "
                                      "device after availability fallback. Not "
                                      "the quantisation -- but a silent "
                                      "NPU -> CPU fallback changes which rules "
                                      "fired, so capture it",
}


# ---------------------------------------------------------------------------
# devices
# ---------------------------------------------------------------------------

# GGML_OPENVINO_DEVICE. GPU.0 / GPU.1 select a specific GPU and behave as GPU
# for every conversion rule -- the table branches on NPU and on nothing else.
OPENVINO_DEVICES = ("CPU", "GPU", "NPU")
DEVICE_ENV = "GGML_OPENVINO_DEVICE"


def normalise_device(device):
    """('NPU', why) for any spelling of an OpenVINO device, or (None, why).

    Never guesses. An unset device is not CPU: the backend picks one and prints
    what it picked, and picking here would put a number in the artefact that
    describes a device nobody selected.
    """
    if device is None or str(device).strip() == "":
        return None, ("no OpenVINO device given. The backend resolves one "
                      "itself and prints it (%s); until that line is read, "
                      "which conversion rules fired is not known"
                      % SOURCE["device_log_line"])
    d = str(device).strip().upper()
    head = d.split(".", 1)[0]
    if head not in OPENVINO_DEVICES:
        return None, ("%r is not an OpenVINO device: %s sets one of %s "
                      "(GPU.0 / GPU.1 select a specific GPU)"
                      % (device, DEVICE_ENV, ", ".join(OPENVINO_DEVICES)))
    if head == "GPU" and d != "GPU":
        return "GPU", ("%s, read as GPU: the conversion table branches on NPU "
                       "and on nothing else, so GPU.0 and GPU.1 convert "
                       "identically" % d)
    return head, "%s, given explicitly" % d


def device_from_env(env=None):
    """(device, how) from GGML_OPENVINO_DEVICE, or (None, why)."""
    env = os.environ if env is None else env
    raw = env.get(DEVICE_ENV)
    if not raw:
        return None, ("%s is not set in this environment" % DEVICE_ENV)
    dev, why = normalise_device(raw)
    return dev, "%s=%s: %s" % (DEVICE_ENV, raw, why)


# ---------------------------------------------------------------------------
# backends: which ones load the file's own layouts, and which rewrite them
# ---------------------------------------------------------------------------

# The requantisation is implemented inside the OpenVINO backend's own load
# path. The four backends below consume the GGUF's block layouts directly, so
# their effective bits per weight IS the file's -- trivially, by identity, and
# not by arithmetic. They are the four covered by the source reading of
# 2026-08-29 recorded in SOURCE, and they are listed BY NAME rather than
# assumed by exclusion: a backend nobody has read the load path of gets
# UNKNOWN, not a free pass for looking similar.
PASSTHROUGH_BACKENDS = {
    "cuda": "no load-time type rewrite: the CUDA backend dequantises the "
            "file's own ggml block layouts in its kernels",
    "vulkan": "no load-time type rewrite: the Vulkan backend dequantises the "
              "file's own ggml block layouts in its shaders",
    "metal": "no load-time type rewrite: the Metal backend dequantises the "
             "file's own ggml block layouts in its kernels",
    "cpu": "no load-time type rewrite: the ggml CPU backend consumes the "
           "file's own block layouts directly",
}
BACKEND_ALIASES = {"cpu-ggml": "cpu", "ggml-cpu": "cpu", "cpu_ggml": "cpu",
                   "openvino-genai": "openvino"}

# Backends this repository has NOT read the source of. Saying "probably
# passthrough" about one of these would be the fourth category rule 1 does not
# have. The why names the file that settles it.
UNREAD_BACKENDS = ("rocm", "hip", "sycl", "cann", "musa", "opencl", "webgpu",
                   "blas", "rpc")


def backend_effect(backend, device=None):
    """What `backend` does to a file's tensor types at load.

    Returns a dict whose `kind` is one of:

      "passthrough"  the weights that run are the weights in the file
      "rewrite"      the backend requantises; `device` decides which rules fire
      "unknown"      nobody read this backend's load path; `why` says so

    `kind` is the thing to branch on. There is no fourth value and no default:
    an unrecognised backend name comes back "unknown" with the reason, because
    a bits-per-weight silently equal to the file's is exactly the failure this
    module exists to stop.
    """
    if backend is None or str(backend).strip() == "":
        return {"kind": "unknown", "backend": None, "device": None,
                "why": "no backend given, and bits per weight cannot be "
                       "attributed to a run without one. Pass --backend, or "
                       "let bin/llama.cpp/INSTALL.json name the build."}
    b = str(backend).strip().lower()
    b = BACKEND_ALIASES.get(b, b)

    if b in PASSTHROUGH_BACKENDS:
        return {"kind": "passthrough", "backend": b, "device": None,
                "why": PASSTHROUGH_BACKENDS[b],
                "source_ref": SOURCE["conversion_table"]}

    if b == "openvino":
        dev, why = normalise_device(device)
        if dev is None:
            return {"kind": "unknown", "backend": "openvino", "device": None,
                    "why": "the OpenVINO backend rewrites tensor types at load "
                           "(%s) and which rules fire depends on the device: "
                           "%s" % (SOURCE["conversion_table"], why)}
        return {"kind": "rewrite", "backend": "openvino", "device": dev,
                "why": "the OpenVINO backend requantises at load (%s); on %s "
                       "the rules below fire" % (SOURCE["conversion_table"], dev),
                "device_how": why,
                "source_ref": SOURCE["conversion_table"]}

    if b in UNREAD_BACKENDS:
        return {"kind": "unknown", "backend": b, "device": None,
                "why": "nothing in this repository has read the %s backend's "
                       "load path, so whether it rewrites tensor types is not "
                       "known. It is not recorded as passthrough on the "
                       "strength of resembling one that is. To settle it, find "
                       "that backend's tensor-set path under ggml/src/ and "
                       "look for a requantise step -- the OpenVINO one is at "
                       "%s -- then add the backend to PASSTHROUGH_BACKENDS "
                       "with the file and line."
                       % (b, SOURCE["conversion_table"])}

    return {"kind": "unknown", "backend": b, "device": None,
            "why": "%r is not a backend this module knows. Known: %s; "
                   "rewrites: openvino; unread: %s."
                   % (backend, ", ".join(sorted(PASSTHROUGH_BACKENDS)),
                      ", ".join(UNREAD_BACKENDS))}


# ---------------------------------------------------------------------------
# tensor roles
# ---------------------------------------------------------------------------

ROLES = ("token_embd", "output", "block")


def role_of(name):
    """Which of the conversion table's three cases a tensor name falls into.

    The table names exactly two tensors and treats everything else as one
    bucket, so this is deliberately literal rather than a classifier: a
    heuristic that put `output_norm.weight` in the `output` bucket would report
    an F32 norm being rewritten to Q8_0_C, which does not happen.
    """
    n = (name or "").strip()
    if n == "token_embd.weight":
        return "token_embd"
    if n == "output.weight":
        return "output"
    return "block"


# ---------------------------------------------------------------------------
# the types the backend invents, and their layouts
# ---------------------------------------------------------------------------

# ggml type names that carry no quantisation. Anything else in a GGUF is
# quantized, and the NPU rule fires on it. An unrecognised name is treated as
# quantized AND flagged, because on the NPU the blanket rule is the common case
# and calling a quantized tensor unquantized would understate the rewrite.
NOT_QUANTIZED = ("F32", "F16", "BF16", "F64", "I8", "I16", "I32", "I64")

# The per-block scale is fp16, as it is in ggml's own Q4_0 and Q8_0. This is
# the one number below that is an ASSUMPTION rather than a line of source, and
# it is carried as one: `model_profile(..., scale_bits=32)` re-runs the whole
# profile with an f32 scale, and every profile reports both figures so the
# assumption is bounded rather than hidden. On Q4_0_128 the choice is worth
# 0.125 bpw of 4.125 (3.0%); on the channel-wise types, one scale per row of
# 5,120 makes it 0.003 bpw (0.04%) and it does not matter at all.
SCALE_BITS = 16
SCALE_BITS_WHY = ("ASSUMED fp16, by analogy with ggml's own Q4_0 and Q8_0 "
                  "block layouts and with %s's 'four times fewer scales' "
                  "re-blocking. Not read out of the source. Bounded: every "
                  "profile carries the f32-scale figure beside it."
                  % SOURCE["conversion_table"])


def _channelwise_bytes(elements, ne0, weight_bits, scale_bits):
    """One scale per ROW. `weights_per_block = tensor->ne[0]`."""
    rows = 1 if not ne0 else max(1, elements // ne0)
    return elements * weight_bits / 8.0 + rows * scale_bits / 8.0


def _blocked_bytes(elements, block, weight_bits, scale_bits):
    """A fixed block size, one scale per block."""
    blocks = elements / float(block)
    return elements * weight_bits / 8.0 + blocks * scale_bits / 8.0


# The three types the OpenVINO backend can produce, plus Q4_0_C for
# completeness: the backend defines it channel-wise alongside Q8_0_C, and the
# conversion table at ggml-openvino-extra.cpp:252-273 does not produce it.
EFFECTIVE_LAYOUT = {
    "F16": {
        "weights_per_block": 1,
        "weight_bits": 16,
        "scale_bits": 0,
        "granularity": "none -- F16 carries no scale",
        "bytes": lambda e, ne0, sb: e * 2.0,
        "bpw": lambda ne0, sb: 16.0,
        "produced_by_table": True,
    },
    "Q8_0_C": {
        "weights_per_block": "ne[0]",
        "weight_bits": 8,
        "scale_bits": SCALE_BITS,
        "granularity": "CHANNEL-WISE: one scale per ROW, weights_per_block = "
                       "tensor->ne[0]",
        "bytes": lambda e, ne0, sb: _channelwise_bytes(e, ne0, 8, sb),
        "bpw": lambda ne0, sb: 8.0 + (sb / float(ne0) if ne0 else 0.0),
        "produced_by_table": True,
    },
    "Q4_0_C": {
        "weights_per_block": "ne[0]",
        "weight_bits": 4,
        "scale_bits": SCALE_BITS,
        "granularity": "CHANNEL-WISE: one scale per ROW, weights_per_block = "
                       "tensor->ne[0]",
        "bytes": lambda e, ne0, sb: _channelwise_bytes(e, ne0, 4, sb),
        "bpw": lambda ne0, sb: 4.0 + (sb / float(ne0) if ne0 else 0.0),
        "produced_by_table": False,
    },
    "Q4_0_128": {
        "weights_per_block": 128,
        "weight_bits": 4,
        "scale_bits": SCALE_BITS,
        "granularity": "block-128: one scale per 128 weights. The GGUF's Q4_0 "
                       "is block-32, so this is FOUR TIMES FEWER SCALES than "
                       "the file even when the file was already Q4_0",
        "bytes": lambda e, ne0, sb: _blocked_bytes(e, 128, 4, sb),
        "bpw": lambda ne0, sb: 4.0 + sb / 128.0,
        "produced_by_table": True,
    },
}


def effective_bpw(effective, ne0, scale_bits=SCALE_BITS):
    """Bits per weight of one effective type on a row of width `ne0`."""
    lay = EFFECTIVE_LAYOUT.get(effective)
    if lay is None:
        return None
    return lay["bpw"](ne0, scale_bits)


def effective_bytes(effective, elements, ne0, scale_bits=SCALE_BITS):
    """Bytes one tensor occupies once the backend has rewritten it."""
    lay = EFFECTIVE_LAYOUT.get(effective)
    if lay is None:
        return None
    return lay["bytes"](elements, ne0, scale_bits)


# ---------------------------------------------------------------------------
# the conversion table, as data
# ---------------------------------------------------------------------------

# ggml-openvino-extra.cpp:252-273, in source order. FIRST MATCH WINS, exactly
# as the branches do there. `device: None` means any device, `source: None`
# means any type, `source: "QUANTIZED"` means any type not in NOT_QUANTIZED,
# and `effective: None` means the tensor is left as the file has it.
CONVERSIONS = (
    {"n": 1, "role": "token_embd", "device": "NPU", "source": ("Q6_K",),
     "effective": "F16",
     "rule": "token_embd.weight is F16 on NPU when the file's type is Q6_K"},
    {"n": 2, "role": "token_embd", "device": None, "source": None,
     "effective": "Q8_0_C",
     "rule": "token_embd.weight is Q8_0_C on EVERY device, whatever the file "
             "holds"},
    {"n": 3, "role": "output", "device": None, "source": None,
     "effective": "Q8_0_C",
     "rule": "output.weight is Q8_0_C on EVERY device, whatever the file "
             "holds"},
    {"n": 4, "role": "block", "device": "NPU", "source": "QUANTIZED",
     "effective": "Q4_0_128",
     "rule": "on NPU every other quantized tensor becomes Q4_0_128, "
             "UNCONDITIONALLY, whatever its type was"},
    {"n": 5, "role": "block", "device": None, "source": ("Q6_K", "Q5_K"),
     "effective": "Q8_0_C",
     "rule": "off NPU, Q6_K and Q5_K become Q8_0_C"},
    {"n": 6, "role": "block", "device": None, "source": None,
     "effective": None,
     "rule": "everything else is loaded as the file holds it"},
)


def is_quantized(source_type):
    """Whether the NPU blanket rule fires on this ggml type name."""
    return str(source_type or "").upper() not in NOT_QUANTIZED


def effective_type(role, source_type, device):
    """The type the OpenVINO backend actually loads, and the rule that did it.

        effective_type("output", "Q6_K", "GPU")
        {'effective': 'Q8_0_C', 'changed': True, 'rule_n': 3, ...}

    `role` is one of ROLES (see role_of), `source_type` is the ggml type NAME
    the file declares ("Q4_K", "Q6_K", "F32", ...), `device` is CPU / GPU / NPU
    or a GPU.n spelling. Raises ValueError on an unknown role and returns a
    dict with `effective: None` and a `why` when the device cannot be resolved
    -- never a guess, in either direction.
    """
    if role not in ROLES:
        raise ValueError("role must be one of %s, not %r" % (ROLES, role))
    src = str(source_type or "").upper()
    dev, dev_why = normalise_device(device)
    if dev is None:
        return {"role": role, "source": src or None, "device": None,
                "effective": None, "changed": None, "rule_n": None,
                "rule": None, "source_ref": SOURCE["conversion_table"],
                "why": dev_why}

    for c in CONVERSIONS:
        if c["role"] != role:
            continue
        if c["device"] is not None and c["device"] != dev:
            continue
        want = c["source"]
        if want == "QUANTIZED":
            if not is_quantized(src):
                continue
        elif want is not None and src not in want:
            continue

        eff = c["effective"] or src
        out = {"role": role, "source": src or None, "device": dev,
               "effective": eff, "changed": (eff != src),
               "rule_n": c["n"], "rule": c["rule"],
               "source_ref": SOURCE["conversion_table"],
               "device_how": dev_why}
        lay = EFFECTIVE_LAYOUT.get(eff)
        if lay:
            out["weights_per_block"] = lay["weights_per_block"]
            out["granularity"] = lay["granularity"]
        if eff == src and c["effective"] is not None:
            # Rule fired and the NAME did not change. Q4_0 -> Q4_0_128 is
            # caught by the name; nothing here is, but the check is kept so a
            # future upstream rule that renames to itself cannot slip past.
            out["changed"] = False
        if src == "Q4_0" and eff == "Q4_0_128":
            out["block_change"] = ("Q4_0 in the file is block-32; Q4_0_128 is "
                                   "block-128. The name barely moves and the "
                                   "representation does: four times fewer "
                                   "scales over the same weights")
        note = describe_change(src, eff)
        if note:
            out["note"] = note
        return out

    # CONVERSIONS ends with a catch-all per role, so this is unreachable unless
    # the table is edited badly. Say which case fell through rather than
    # returning the source type as though nothing happened.
    return {"role": role, "source": src or None, "device": dev,
            "effective": None, "changed": None, "rule_n": None, "rule": None,
            "source_ref": SOURCE["conversion_table"],
            "why": "no rule in CONVERSIONS matched role=%r source=%r device=%r; "
                   "the table has lost its catch-all and must be re-read "
                   "against %s" % (role, src, dev, SOURCE["conversion_table"])}


def describe_change(source_type, effective):
    """Wording for one conversion that does not call any of it an upgrade.

    Q6_K -> Q8_0_C adds bits and removes scales. Whether that helps is an
    empirical question this module cannot answer and this repository has not
    measured, so the sentence states both movements and stops.
    """
    src, eff = str(source_type or "").upper(), str(effective or "").upper()
    if src == eff:
        return None
    if eff == "Q8_0_C" and src in ("Q6_K", "Q5_K", "Q4_K", "Q3_K", "Q2_K",
                                   "Q4_0", "Q4_1", "Q5_0", "Q5_1",
                                   "IQ4_XS", "IQ4_NL", "IQ3_S", "IQ3_XXS",
                                   "IQ2_S", "IQ2_XS", "IQ2_XXS", "IQ1_S",
                                   "IQ1_M"):
        return ("%s -> Q8_0_C is MORE BITS AT COARSER SCALE GRANULARITY: 8 bits "
                "a weight against %s's, with one scale per ROW where the file "
                "had one per block. Not lossless, not an upgrade -- the two "
                "representations are different, and which is closer to the "
                "F32 original is a perplexity question, not an arithmetic one."
                % (src, src))
    if eff == "Q8_0_C" and src == "Q8_0":
        return ("Q8_0 -> Q8_0_C keeps 8 bits a weight and replaces one scale "
                "per 32 weights with one scale per ROW. Same width, coarser "
                "scales.")
    if eff == "Q4_0_128":
        return ("%s -> Q4_0_128 is 4 bits a weight with one scale per 128. "
                "Every quantized tensor on the NPU lands here, so two files "
                "that differ only in this bucket run identical weights." % src)
    if eff == "F16":
        return ("Q6_K -> F16 on the NPU is the one case where the backend "
                "expands rather than re-quantises: 16 bits a weight, no scale, "
                "and 2.4x the bytes of the Q6_K the file held.")
    return None


# ---------------------------------------------------------------------------
# a whole model: what a ladder arm actually measures
# ---------------------------------------------------------------------------

REQUIRED_TENSOR_KEYS = ("name", "elements", "ne0", "type", "bytes")


def model_profile(tensors, device, label=None, scale_bits=SCALE_BITS):
    """Apply the table to a whole tensor table. What the arm really is.

    `tensors` is an iterable of dicts, each carrying:

        name      the GGUF tensor name          ("token_embd.weight")
        elements  the product of its dims       (1271398400)
        ne0       dims[0], the ROW WIDTH        (5120)
        type      the ggml type NAME            ("Q4_K")
        bytes     the bytes the FILE gives it   (elements // block * block_bytes)

    `bytes` comes from the caller because the GGUF block table lives in
    `scripts/quant-ladder/gguf-inspect.py` and this module keeps no second copy
    of it (see the module docstring). A tensor missing any key raises KeyError
    naming it, rather than contributing a silent zero.

    Returns a dict carrying `bpw_effective`, the per-role breakdown, the
    conditions that number depends on, and `collapse` -- how many distinct
    source types went in and how many distinct effective types came out, which
    is the whole question for a quant ladder.
    """
    dev, dev_why = normalise_device(device)
    if dev is None:
        return {"label": label, "device": None, "bpw_effective": None,
                "why": dev_why, "source_ref": SOURCE["conversion_table"]}

    rows, warnings = [], []
    by_role = {}
    src_types, eff_types = {}, {}
    total_elems = 0
    total_src_bytes = 0.0
    total_eff_bytes = 0.0
    total_eff_bytes_f32 = 0.0
    rewritten = 0
    n_tensors = 0
    census = {}
    unknown_names = set()

    for t in tensors:
        for k in REQUIRED_TENSOR_KEYS:
            if k not in t:
                raise KeyError(
                    "tensor %r has no %r. model_profile needs %s; `bytes` is "
                    "the FILE's byte count for that tensor and comes from the "
                    "caller's ggml block table, not from here."
                    % (t.get("name", "<unnamed>"), k,
                       ", ".join(REQUIRED_TENSOR_KEYS)))
        name, elems, ne0 = t["name"], int(t["elements"]), int(t["ne0"] or 0)
        src = str(t["type"]).upper()
        src_bytes = float(t["bytes"])
        role = role_of(name)
        eff = effective_type(role, src, dev)
        e_name = eff["effective"]

        if src.startswith("TYPE_") or (src not in NOT_QUANTIZED
                                       and not src.startswith(("Q", "IQ", "TQ",
                                                               "MXFP"))):
            unknown_names.add(src)

        if e_name == src:
            eff_bytes = src_bytes
            eff_bytes_f32 = src_bytes
        else:
            eff_bytes = effective_bytes(e_name, elems, ne0, scale_bits)
            eff_bytes_f32 = effective_bytes(e_name, elems, ne0, 32)
            rewritten += 1

        n_tensors += 1
        total_elems += elems
        total_src_bytes += src_bytes
        total_eff_bytes += eff_bytes
        total_eff_bytes_f32 += eff_bytes_f32

        src_types[src] = src_types.get(src, 0) + 1
        eff_types[e_name] = eff_types.get(e_name, 0) + 1

        # The census is the compact answer to "what actually happened to this
        # file": one row per (source type -> effective type) pair, with the
        # weight count that makes a pair matter or not.
        c = census.setdefault((src, e_name, eff.get("rule_n")), {
            "source": src, "effective": e_name, "changed": e_name != src,
            "tensors": 0, "elements": 0, "roles": set(),
            "note": eff.get("note"), "rule_n": eff.get("rule_n")})
        c["tensors"] += 1
        c["elements"] += elems
        c["roles"].add(role)

        b = by_role.setdefault(role, {"tensors": 0, "elements": 0,
                                      "file_bytes": 0.0,
                                      "effective_bytes": 0.0,
                                      "source_types": {},
                                      "effective_types": {},
                                      "rules": set()})
        b["tensors"] += 1
        b["elements"] += elems
        b["file_bytes"] += src_bytes
        b["effective_bytes"] += eff_bytes
        b["source_types"][src] = b["source_types"].get(src, 0) + 1
        b["effective_types"][e_name] = b["effective_types"].get(e_name, 0) + 1
        if eff.get("rule_n"):
            b["rules"].add(eff["rule_n"])

        if role != "block":
            rows.append({"name": name, "elements": elems, "ne0": ne0,
                         "source": src, "effective": e_name,
                         "file_bytes": int(src_bytes),
                         "effective_bytes": int(round(eff_bytes)),
                         "bpw_file": src_bytes * 8.0 / elems if elems else None,
                         "bpw_effective": (eff_bytes * 8.0 / elems
                                           if elems else None),
                         "rule_n": eff.get("rule_n"),
                         "rule": eff.get("rule"),
                         "note": eff.get("note")})

    for b in by_role.values():
        b["rules"] = sorted(b["rules"])
        b["bpw_file"] = (b["file_bytes"] * 8.0 / b["elements"]
                         if b["elements"] else None)
        b["bpw_effective"] = (b["effective_bytes"] * 8.0 / b["elements"]
                              if b["elements"] else None)
        b["file_bytes"] = int(b["file_bytes"])
        b["effective_bytes"] = int(round(b["effective_bytes"]))

    rows_census = []
    for c in sorted(census.values(),
                    key=lambda x: (not x["changed"], -x["elements"],
                                   x["rule_n"] or 0)):
        c = dict(c)
        c["roles"] = sorted(c["roles"])
        rows_census.append(c)

    bpw_file = total_src_bytes * 8.0 / total_elems if total_elems else None
    bpw_eff = total_eff_bytes * 8.0 / total_elems if total_elems else None
    bpw_eff_f32 = (total_eff_bytes_f32 * 8.0 / total_elems
                   if total_elems else None)

    # The collapse. Only the `block` bucket can carry a ladder's difference:
    # token_embd and output are pinned by rules 2 and 3 on every device.
    blocks = by_role.get("block", {})
    block_src = set(k for k in blocks.get("source_types", {})
                    if is_quantized(k))
    block_eff = set(k for k in blocks.get("effective_types", {})
                    if is_quantized(k))
    degenerate = bool(dev == "NPU" and len(block_src) > 1 and len(block_eff) == 1)
    collapse = {
        "quantized_source_types_in_blocks": sorted(block_src),
        "effective_types_in_blocks": sorted(block_eff),
        "distinct_in": len(block_src),
        "distinct_out": len(block_eff),
        "degenerate": degenerate,
        "note": None,
    }
    if degenerate:
        collapse["note"] = (
            "%d distinct quantized types in this file's body tensors collapse "
            "to one (%s). Every quantized block tensor runs at the same "
            "representation, so a ladder rung built on this file measures its "
            "token_embd.weight and nothing else. Rule 30: arms compare inside "
            "one sweep, and on NPU these arms are not different arms."
            % (len(block_src), sorted(block_eff)[0] if block_eff else "?"))
    elif dev == "NPU":
        collapse["note"] = ("on NPU every quantized body tensor is rewritten to "
                            "Q4_0_128 (rule 4); this file's body already held "
                            "%d distinct quantized type(s)" % len(block_src))
    else:
        collapse["note"] = ("on %s only Q6_K and Q5_K body tensors are "
                            "rewritten (rule 5); the rest load as the file "
                            "holds them" % dev)

    # Conditions. Every one of these, changed, changes the number above.
    if dev == "NPU":
        warnings.append(
            "NPU is a REQUEST, not a fact. ggml_openvino_init() prints the "
            "RESOLVED device after availability fallback (%s). If the NPU was "
            "unavailable the run was CPU, rule 4 never fired, and this whole "
            "profile is the wrong one. Capture that line."
            % SOURCE["device_log_line"])
        warnings.append(
            "NPU needs an explicit -c or it defaults to the model's training "
            "context, and llama-server on NPU cannot serve parallel "
            "sequences. Arrow Lake SIGSEGVs in "
            "libopenvino_intel_npu_plugin.so (confirmed by an Intel engineer "
            "2026-07-21, still open); Lunar Lake and Panther Lake work.")
    warnings.append(
        "the per-block scale width is %d bits, %s With a 32-bit scale the "
        "figure is %s bpw instead."
        % (scale_bits, SCALE_BITS_WHY,
           "%.4f" % bpw_eff_f32 if bpw_eff_f32 else "null"))
    warnings.append(
        "DERIVED from a table, not read from the run. The authoritative record "
        "is four commented-out log lines away: %s" % GROUND_TRUTH["how"])
    if unknown_names:
        warnings.append(
            "ggml type name(s) %s are not in the caller's block table, so the "
            "bytes they contributed are ZERO and bpw_file_tensor_table above "
            "reads LOW -- which makes delta_bpw wrong by the same amount. They "
            "were treated as quantized for the conversion, which is the "
            "assumption that OVERSTATES the rewrite on NPU. The effective "
            "figure survives (the rewritten type is known); the FILE figure "
            "beside it does not. Add the type to the block table in "
            "scripts/quant-ladder/gguf-inspect.py before quoting the delta."
            % sorted(unknown_names))

    return {
        "label": label,
        "backend": "openvino",
        "device": dev,
        "device_how": dev_why,
        "source_ref": SOURCE["conversion_table"],
        "tensors": n_tensors,
        "tensors_rewritten": rewritten,
        "params_total": total_elems,
        "file_bytes_tensor_table": int(total_src_bytes),
        "effective_bytes": int(round(total_eff_bytes)),
        "bpw_file_tensor_table": bpw_file,
        "bpw_effective": bpw_eff,
        "bpw_effective_if_f32_scale": bpw_eff_f32,
        "delta_bpw": (bpw_eff - bpw_file
                      if (bpw_eff is not None and bpw_file is not None)
                      else None),
        "scale_bits": scale_bits,
        "by_role": by_role,
        "named_tensors": rows,
        "source_types": src_types,
        "effective_types": eff_types,
        "unrecognised_source_types": sorted(unknown_names) or None,
        "conversions": rows_census,
        "collapse": collapse,
        "warnings": warnings,
        "basis": ("both figures are TENSOR-TABLE sums over the same tensors, "
                  "so their difference is the requantisation alone and carries "
                  "no container overhead. bpw computed from FILE SIZE is "
                  "larger by the header and padding; compare like with like."),
    }


def ladder_signature(profile):
    """A hashable fingerprint of the weights a profile actually runs.

    Two arms with the same signature are the same weights. Built from the
    effective type of every tensor bucket rather than from a byte total,
    because two different files can round to the same byte count.
    """
    if not profile or profile.get("bpw_effective") is None:
        return None
    parts = []
    for role in ROLES:
        b = profile["by_role"].get(role)
        if not b:
            continue
        parts.append("%s=%s" % (role, ",".join(
            "%s:%d" % (k, v) for k, v in sorted(b["effective_types"].items()))))
    return "%s|%s" % (profile.get("device"), ";".join(parts))


def compare_arms(profiles):
    """Which of these ladder arms are the same weights, and which are not.

    `profiles` is a mapping of arm label -> model_profile() output. Returns the
    grouping plus a verdict, so a sweep can be refused before it is run rather
    than explained after it has produced a flat curve (rule 25: cheap probes
    buy the map).
    """
    groups = {}
    for label, prof in profiles.items():
        sig = ladder_signature(prof)
        groups.setdefault(sig, []).append(label)
    identical = {sig: sorted(labels) for sig, labels in groups.items()
                 if len(labels) > 1}
    n_arms = len(profiles)
    n_distinct = len(groups)
    verdict = ("%d arm(s) run %d distinct set(s) of weights"
               % (n_arms, n_distinct))
    if identical:
        worst = max(identical.values(), key=len)
        verdict += (". %s are BYTE-IDENTICAL after the backend's rewrite: "
                    "running them as separate rungs measures nothing but run-"
                    "to-run variance" % ", ".join(worst))
    return {"arms": n_arms, "distinct_weight_sets": n_distinct,
            "groups": {sig: sorted(labels) for sig, labels in groups.items()},
            "identical_arms": identical, "verdict": verdict,
            "source_ref": SOURCE["conversion_table"]}


# ---------------------------------------------------------------------------
# the table, at a prompt
# ---------------------------------------------------------------------------

def _print_table(out):
    """`python scripts/lib/openvino_quant.py` -- the table and its provenance.

    A new agent on a fresh box needs this before it needs any of the functions,
    and a table that can only be read by importing it is a table nobody reads.
    """
    w = out.write
    w("\nWHAT THE OPENVINO BACKEND LOADS, AND THE FILE IT IS READ FROM\n")
    w("=" * 74 + "\n")
    for k in ("repo", "ref", "read_utc", "backend_merged", "runtime_pinned",
              "conversion_table", "requantiser", "no_requant_escape"):
        w("  %-20s %s\n" % (k, SOURCE[k]))
    w("\nTHE CONVERSION TABLE, in source order -- FIRST MATCH WINS\n")
    w("-" * 74 + "\n")
    for c in CONVERSIONS:
        src = ("any type" if c["source"] is None else
               "any quantized type" if c["source"] == "QUANTIZED" else
               " or ".join(c["source"]))
        w("  rule %d  %-11s %-4s %-18s -> %s\n"
          % (c["n"], c["role"], c["device"] or "any", src,
             c["effective"] or "unchanged"))
        w("          %s\n" % c["rule"])
    w("\nTHE TYPES IT INVENTS -- two of these do not exist in the GGUF format\n")
    w("-" * 74 + "\n")
    for name in ("F16", "Q8_0_C", "Q4_0_C", "Q4_0_128"):
        lay = EFFECTIVE_LAYOUT[name]
        bpw = effective_bpw(name, 5120)
        w("  %-9s %-6s weights/block  %6.4f bpw on a 5,120-wide row%s\n"
          % (name, lay["weights_per_block"], bpw,
             "" if lay["produced_by_table"] else
             "   (NOT produced by the table above)"))
        w("            %s\n" % lay["granularity"])
    w("\n  The per-block scale is %d bits. %s\n" % (SCALE_BITS, SCALE_BITS_WHY))
    w("\nQ6_K -> Q8_0_C IS NOT AN UPGRADE\n")
    w("-" * 74 + "\n")
    w("  %s\n" % describe_change("Q6_K", "Q8_0_C"))
    w("\nIT IS SILENT\n")
    w("-" * 74 + "\n")
    w("  the per-tensor logging   COMMENTED OUT at %s\n"
      % SOURCE["commented_out_logging"])
    w("  /props->description      %s: %s\n"
      % (SOURCE["props_description"], SOURCE["props_description_holds"]))
    w("  the one capturable line  %s: %s\n"
      % (SOURCE["device_log_line"],
         GROUND_TRUTH["what_an_ordinary_run_tells_you"]))
    w("\nTHE CHEAP ROUTE TO GROUND TRUTH\n")
    w("-" * 74 + "\n")
    w("  %s\n" % GROUND_TRUTH["how"])
    w("  %s\n" % GROUND_TRUTH["second_witness"])
    w("\nWHICH BACKENDS THIS IS SCOPED TO\n")
    w("-" * 74 + "\n")
    for b in sorted(PASSTHROUGH_BACKENDS):
        w("  %-10s passthrough -- %s\n" % (b, PASSTHROUGH_BACKENDS[b]))
    w("  %-10s REWRITES -- see the table above\n" % "openvino")
    w("  %-10s not read: %s\n"
      % ("unread", ", ".join(UNREAD_BACKENDS)))
    w("\n  %s\n\n" % SOURCE["note"])


if __name__ == "__main__":
    import sys as _sys
    _print_table(_sys.stdout)
