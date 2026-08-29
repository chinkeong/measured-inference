#!/usr/bin/env python3
"""The measurements ledger: every number under results/, with the conditions
that make it falsifiable, and a gate that REFUSES to compare two rows whose
conditions do not permit it.

    A CATALOGUE says   "Qwen3.8-27B does 86.91 t/s".
    A LEDGER says      "on machine M, build B, at conditions C, on 2026-08-23:
                        86.91 t/s".

Rule 30 forbids the first across sweeps -- absolutes do not travel, only ratios
do -- and the second is what every campaign already produces, one directory at
a time, and never accumulates. This file accumulates it, and then refuses the
comparisons the rules forbid, naming the field that differs.

GENERATED, NEVER HAND-EDITED. `build` derives every row from results/*/ so the
ledger cannot drift from the measurements it summarises: delete it and rebuild
and you get the same bytes. JSONL, not a spreadsheet -- diffable, greppable,
and every change lands in a commit with a date.

    python scripts/ledger.py build            # derive results/ledger.jsonl
    python scripts/ledger.py check            # rows unfit to be compared
    python scripts/ledger.py rows   --metric throughput.decode
    python scripts/ledger.py compare --metric composite.mean
    python scripts/ledger.py compare --metric throughput.decode --ratio
    python scripts/ledger.py compare --metric ppl --where backend=openvino
    python scripts/ledger.py selftest         # no GPU, no network, no model

WHAT THE GATE IS FOR. A retracted 83-86 t/s band reached a published page
because two throughput figures from different sweeps were put in one sentence.
Nothing in the artefacts stopped it; the rule lived in a human head. Here it is
a function that exits non-zero.

THE BACKEND IS PART OF THE KEY, and it is the newest part. Every number in
results/qwen38-27b-blind/ was measured through CUDA, on one box, and no
artefact said so - which was survivable while there was one backend. llama.cpp
now ships an OpenVINO backend in mainline (ggml/src/ggml-openvino/, merged
2026-03-14) that will decode the same GGUF on the same box through a CPU, an
iGPU or an NPU, and it does not run the weights that are in the file: it
rewrites them first, silently, before the first token
(ggml-openvino-extra.cpp:252-273). So `backend` and the RESOLVED `device` sit
in the comparability key beside the machine, the build and the sweep, and a
row that does not name them cannot enter a comparison. See LADDER_* below for
the refusal that no assertion overrides: a quant ladder on OpenVINO NPU, where
every arm decodes as Q4_0_128 and the ladder therefore has one arm.

WHAT THE LEDGER ADDS TO A MODEL CATALOGUE. The columns nobody publishes, all of
them already measured by this harness and thrown away at the end of each
campaign: reasoning appetite (`appetite.*`, mean output tokens per answer at a
named effort level), the usable prompt budget (`conditions.ctx` on every row,
and `vram.slack` beside it), and the practical output ceiling (`truncation.*`
against `conditions.max_tokens` -- how many answers the cap cut off).
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import textwrap

# v2 added two fields to every row and to the comparability key: `backend`
# and the resolved `device`. A v1 ledger carries neither, so every comparison
# against it refuses -- correctly, and uselessly. load_ledger() says so.
SCHEMA = "measured-inference/ledger.jsonl v2"
HERE = os.path.dirname(os.path.abspath(__file__))
# The ledger reads results/ and nothing else. It resolves no model, no server
# binary and no campaign, so it needs none of scripts/lib/paths.py and does not
# import it: one fewer thing that can fail on a fresh clone.
REPO = os.path.dirname(HERE)
DEFAULT_OUT = os.path.join("results", "ledger.jsonl")

ABSENT = object()


# ---------------------------------------------------------------------------
# THE COMPARABILITY GATE
#
# One table. Each metric class says which fields must MATCH before two rows may
# stand in one comparison, which conditions rule 3 names for that class, and
# whether the class travels between sweeps. Everything else in this file exists
# to fill this table with rows.
# ---------------------------------------------------------------------------

CLASSES = {
    "accuracy": {
        "gate": ("backend", "device",
                 "conditions.suite_hash", "conditions.datasets",
                 "conditions.samples", "conditions.seed",
                 "conditions.max_tokens", "conditions.temperature",
                 "conditions.top_k", "conditions.top_p"),
        "thin": ("conditions.truncated_n", "conditions.scorer"),
        "rules": "rules 21 and 23",
        "why": ("two scores compare only if the same prompts were asked under "
                "the same sampling with the same cap: rule 23 pins the suite "
                "hash, rule 21 pins the scored set, rule 7 makes the cap a "
                "condition because an answer that hit it scores zero"),
        "travels": True,
    },
    "appetite": {
        "gate": ("backend", "device",
                 "conditions.suite_hash", "conditions.datasets",
                 "conditions.samples", "conditions.seed",
                 "conditions.max_tokens", "conditions.temperature"),
        "thin": ("conditions.truncated_n",),
        "rules": "rules 16, 21 and 23",
        "why": ("appetite is tokens spent per answer on a fixed question set, "
                "so it compares only against the same questions at the same "
                "cap -- and a cap the appetite reached truncated it (rule 16)"),
        "travels": True,
    },
    "count": {
        "gate": ("backend", "device",
                 "conditions.suite_hash", "conditions.datasets",
                 "conditions.samples", "conditions.max_tokens"),
        "thin": (),
        "rules": "rules 7 and 21",
        "why": ("a truncation count is a count of the same questions against "
                "the same cap, or it is two different numbers"),
        "travels": True,
    },
    "throughput": {
        "gate": ("backend", "device",
                 "machine", "build", "conditions.sweep"),
        "thin": ("conditions.depth", "conditions.token_regime",
                 "conditions.desktop_state", "conditions.prior_state",
                 "conditions.temperature", "conditions.ctx"),
        "rules": "rule 30",
        "why": ("throughput on this rig has two levels about 13% apart and "
                "nothing recorded predicts which one a session gets, so an "
                "absolute compares only inside ONE sweep, on one machine, "
                "against one build -- across sweeps only the RATIO travels"),
        "travels": False,
    },
    "acceptance": {
        # NOT gated on the sweep, and that is a measurement, not an oversight:
        # rule 30 eliminated the drafter as a cause of the two levels by
        # showing acceptance and mean draft length bit-identical across
        # sessions. Sampling IS gated -- rule 3: acceptance is a property of
        # which token the drafter must guess, so temperature moves it.
        "gate": ("backend", "device",
                 "machine", "build", "conditions.spec", "conditions.kv",
                 "conditions.temperature", "conditions.top_k",
                 "conditions.top_p"),
        "thin": ("conditions.depth", "conditions.ctx"),
        "rules": "rules 11, 3 and 30",
        "why": ("acceptance reproduces across sessions where throughput does "
                "not, so it travels between sweeps on one machine and build "
                "-- but only at one sampling, and only published beside the "
                "mean draft length (rule 11)"),
        "travels": True,
        "companion": {"acceptance": "draft_len.mean"},
    },
    "memory": {
        "gate": ("backend", "device",
                 "machine", "build", "conditions.ctx", "conditions.model"),
        "thin": ("conditions.desktop_state", "conditions.depth"),
        "rules": "rules 13 and 14",
        "why": ("a footprint is scoped to file + drafter + projector + "
                "desktop at one window; change the window and it is a "
                "different number, not a worse one"),
        "travels": True,
    },
    "energy": {
        "gate": ("backend", "device",
                 "machine", "build", "conditions.sweep", "conditions.tier",
                 "conditions.phase"),
        "thin": ("conditions.idle_w_used", "conditions.coverage"),
        "rules": "rules 24 and 30",
        "why": ("every watt carries its instrumentation tier and every joule "
                "its phase (rule 24); the joules also ride the throughput the "
                "sweep produced, so rule 30 binds them too"),
        "travels": False,
    },
    "load": {
        "gate": ("backend", "device",
                 "machine", "build", "conditions.model", "conditions.ctx"),
        "thin": (),
        "rules": "rule 13",
        "why": "whether a configuration loads at all is a property of the box",
        "travels": True,
    },
    "ratio": {
        # A ratio is computed inside one sweep and is the thing rule 30 says
        # travels. It is gated on WHAT was divided by WHAT, never on where --
        # except for the backend, which is not a "where": two backends running
        # one file are two experiments, and on OpenVINO they are not even the
        # same weights.
        "gate": ("backend", "device",
                 "conditions.of_metric", "conditions.numerator",
                 "conditions.denominator", "conditions.model"),
        "thin": (),
        "rules": "rule 30",
        "why": ("ratios are robust where levels are not: the same five-arm "
                "sweep run last-to-first kept every relationship's sign and "
                "rough size while its baseline arm moved 11.7%"),
        "travels": True,
    },
}

# What to do about it, printed under every refusal, keyed by the gate field.
REMEDY = {
    "conditions.sweep": (
        "run the arms in ONE sweep -- scripts/arms.py stamps \"sweep\" on "
        "every ledger line -- or compare them as ratios: --ratio"),
    "machine": (
        "record the box with the number: scripts/bench/provenance.py's "
        "toolchain block, or results/<slug>/machine.json from "
        "scripts/detect-machine.py"),
    "build": (
        "record the build with the number: provenance.server_build() parses "
        "`llama-server --version` into build + commit"),
    "conditions.suite_hash": (
        "run both arms against the same frozen suite "
        "(scripts/bench/suites/rule21-n25.json, hash 1cdf54f8eb9d3f8f)"),
    "conditions.datasets": (
        "run the whole 7-benchmark suite in both arms; a narrowed --datasets "
        "run keeps the FULL suite's hash while measuring a different set"),
    "conditions.max_tokens": (
        "rule 7: raise the cap and rerun the OTHER arm too, never compare a "
        "16,384-cap score against a 32,768-cap one"),
    "conditions.tier": (
        "rule 24: name the instrumentation tier beside the watts"),
    "conditions.phase": (
        "rule 24: attribute every joule to prefill or decode"),
    "backend": (
        "record what decoded: scripts/bench/provenance.py's toolchain() now "
        "writes an \"execution\" block (backend, resolved device, cuda_arch, "
        "openvino_version, stateful_execution, build tag). On Linux with an "
        "NVIDIA card the backend is NOT derivable -- scripts/setup.sh "
        "installs the VULKAN build unless --cuda is given -- so pass "
        "backend= to toolchain(), or install through setup.sh so "
        "bin/llama.cpp/INSTALL.json describes the binary that runs"),
    "device": (
        "on OpenVINO, capture the server log and let "
        "provenance.openvino_device() read \"OpenVINO: using device X\" out "
        "of it (ggml-openvino.cpp:1526). GGML_OPENVINO_DEVICE is what was "
        "ASKED for; that line is what was GIVEN, and a silent NPU -> CPU "
        "fallback is exactly the difference"),
}

# Printed under a refusal on a field that is not specific to one metric class.
FIELD_WHY = {
    "backend": (
        "the backend is not a setting, it is a different experiment: it "
        "changes prefill, decode, acceptance and the VRAM ceiling for reasons "
        "that have nothing to do with the model (scripts/setup.sh says the "
        "same thing in prose and refuses the substitution), and on OpenVINO "
        "it changes the WEIGHTS -- the file on disk is not what ran"),
    "device": (
        "one OpenVINO build decodes on CPU, on an iGPU or on an NPU, and the "
        "three are different silicon with different quantisation: on NPU "
        "every quantized tensor is rewritten to Q4_0_128 whatever the file "
        "said (ggml-openvino-extra.cpp:252-273). The device that ran is read "
        "from the server log, never from the environment variable that asked "
        "for it"),
}


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def get(obj, dotted):
    """row["a"]["b"] for "a.b", or ABSENT. Never raises."""
    cur = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return ABSENT
        cur = cur[part]
    return cur


def present(value):
    """A field is present when it carries something a reader could falsify."""
    return value is not ABSENT and value not in (None, "", [], {})


def show(value):
    if value is ABSENT or value is None:
        return "<not named>"
    if isinstance(value, (list, tuple)):
        return ",".join(str(v) for v in value)
    return str(value)


def num(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def fmt(value):
    n = num(value)
    return show(value) if n is None else ("%.6g" % n)


def wrap(text, indent="      ", width=79):
    """A paragraph a tired operator can read at 2am, not a 400-column line."""
    return textwrap.fill(" ".join(str(text).split()), width=width,
                         initial_indent=indent, subsequent_indent=indent)


def sha16(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def rel(path):
    try:
        return os.path.relpath(path, REPO).replace(os.sep, "/")
    except ValueError:                                   # another drive letter
        return os.path.abspath(path).replace(os.sep, "/")


def canon(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def flag_value(flags, name):
    """The value after a flag in an argv-shaped list, or None."""
    flags = [str(f) for f in flags or []]
    for i, f in enumerate(flags):
        if f == name and i + 1 < len(flags):
            return flags[i + 1]
        if f.startswith(name + "="):
            return f.split("=", 1)[1]
    return None


def spec_flags(flags):
    """Every --spec-* flag WITH its value, in order, as one string."""
    flags = [str(f) for f in flags or []]
    out, take = [], False
    for f in flags:
        if f.startswith("--spec"):
            out.append(f)
            take = "=" not in f
        elif take:
            out.append(f)
            take = False
    return " ".join(out) or None


def scalars(mapping, drop=()):
    """The keys of a dict that are worth carrying as conditions.

    Scalars and short string lists ride along; probe arrays and rating matrices
    do not -- a condition a reader cannot read in one line is not a condition.
    """
    out = {}
    for k, v in (mapping or {}).items():
        if k in drop:
            continue
        if isinstance(v, (str, int, float, bool)) or v is None:
            if isinstance(v, str) and len(v) > 400:
                out[k + "_sha256"] = sha16(v)
                out[k + "_chars"] = len(v)
            else:
                out[k] = v
        elif (isinstance(v, list) and len(v) <= 12
              and all(isinstance(x, (str, int, float, bool)) for x in v)):
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# machine and build identity
#
# Two artefact families name the box in two shapes. Both are reduced to one
# canonical string, because the gate compares strings and a rig that is the
# same rig must produce the same string in both.
# ---------------------------------------------------------------------------

def machine_id(gpu=None, driver=None, os_name=None):
    """gpu | driver | os. Absent parts become "?" and never match.

    The hostname is deliberately NOT in this id. What moves a throughput number
    is the card, its driver and the OS scheduler; provenance.py records all
    three and no hostname, bench.py records all four, and gating on the
    hostname would refuse every comparison between them while naming no
    physical difference. `check` reports the missing hostname instead.
    """
    parts = [gpu, driver, os_name]
    if not any(parts):
        return None
    return " | ".join(p or "?" for p in parts)


_BUILD_RE = re.compile(r"version:\s*(\S+).*?build\s+(\d+).*?commit\s+([0-9a-f]+)",
                       re.S)


def build_id(version=None, build=None, commit=None, raw=None):
    """llama.cpp <version> build <n> commit <sha>, from either shape."""
    if raw and not (version and build and commit):
        m = _BUILD_RE.search(raw)
        if m:
            version, build, commit = m.group(1), m.group(2), m.group(3)
    if not any((version, build, commit)):
        return None
    return "llama.cpp %s build %s commit %s" % (version or "?", build or "?",
                                                commit or "?")


def from_provenance(block):
    """(machine, build, fields) out of scripts/bench/provenance.py's block."""
    if not isinstance(block, dict):
        return None, None, {}
    gpu = block.get("gpu") if isinstance(block.get("gpu"), dict) else {}
    lc = block.get("llama_cpp") if isinstance(block.get("llama_cpp"), dict) else {}
    mid = machine_id(gpu.get("name"), gpu.get("driver"), block.get("platform"))
    bid = build_id(lc.get("version"), lc.get("build"), lc.get("commit"),
                   lc.get("raw"))
    fields = {"gpu": gpu.get("name"), "driver": gpu.get("driver"),
              "os": block.get("platform"), "host": None,
              "power_limit_w": gpu.get("power_limit_w") or gpu.get("raw"),
              "python": block.get("python")}
    return mid, bid, {k: v for k, v in fields.items() if v is not None}


def from_bench_machine(machine, backend):
    """(machine, build, fields) out of a bench.py artefact's own blocks."""
    machine = machine or {}
    backend = backend or {}
    gpu_raw = machine.get("gpu") or ""
    gpu_name, driver = (gpu_raw.split(", ", 1) + [None])[:2] if gpu_raw \
        else (None, None)
    mid = machine_id(gpu_name or None, driver, machine.get("os"))
    bid = build_id(raw=backend.get("version") or machine.get("llama_cpp"))
    fields = {"gpu": gpu_name, "driver": driver, "os": machine.get("os"),
              "host": machine.get("host"), "cpu": machine.get("cpu"),
              "server_bin": backend.get("server_bin"),
              "engine": backend.get("engine")}
    return mid, bid, {k: v for k, v in fields.items() if v is not None}


# ---------------------------------------------------------------------------
# THE EXECUTION CONTEXT: what decoded, and on which device
#
# Two fields, in the comparability key of every class, and neither of them is
# in a single artefact this repository wrote before 2026-08-29.
#
#   backend   cuda | openvino | vulkan | sycl | rocm | metal | cpu
#   device    the RESOLVED device, which on OpenVINO is read out of the server
#             log (ggml-openvino.cpp:1526) and never out of the environment
#             variable that asked for it
#
# Both come from scripts/bench/provenance.py's execution block when the probe
# recorded one. Where it did not, they are DERIVED from the box, and only
# where the derivation is not a guess: an NVIDIA card on Windows means CUDA,
# because scripts/setup.ps1 installs that build and refuses to substitute
# another. An NVIDIA card on LINUX means nothing at all -- scripts/setup.sh
# installs the Vulkan build unless --cuda is passed -- so such a row stays
# unnamed and blocked, which is the correct answer for exactly the machine
# this repository is being ported to.
#
# This module still reads results/ and nothing else: it does not open a server
# log, because a log under work/ is declared scratch and a number whose source
# is re-creatable scratch has no source. Parsing that log is provenance.py's
# job, at run time, into the artefact.
# ---------------------------------------------------------------------------

BACKENDS = ("cuda", "openvino", "vulkan", "sycl", "rocm", "metal", "cpu")

# The prefixes provenance.py writes when a field could not be read. They are
# values, not absences, and reading one of them as a device is how
# "NOT RECORDED" becomes a comparison.
_ABSENCE_PREFIXES = ("NOT RECORDED", "NOT SET", "UNKNOWN", "NOT NAMED",
                     "NOT APPLICABLE")


def named(value):
    """The recorded value, or None when the artefact wrote down an absence."""
    if value in (None, "", [], {}):
        return None
    if not isinstance(value, str):
        return value
    v = value.strip()
    return None if v.upper().startswith(_ABSENCE_PREFIXES) else v


# The execution fields that are CONDITIONS of the number rather than part of
# its identity: they ride in conditions, where rule 3 wants them, and a reader
# can select on them with --where.
EXEC_CONDITIONS = ("device_asked", "cuda_arch", "openvino_version",
                   "stateful_execution", "build_tag", "npu_quant_collapse")


def from_execution(block):
    """(backend, device, conditions) out of provenance.py's execution block."""
    if not isinstance(block, dict):
        return None, None, {}
    be = named(block.get("backend"))
    be = be.lower() if isinstance(be, str) else None
    if be not in BACKENDS:
        be = None
    dev = named(block.get("device"))
    cond = {}
    for k in EXEC_CONDITIONS:
        v = named(block.get(k))
        if v is not None:
            cond[k] = v
    warn = block.get("warnings")
    if isinstance(warn, list) and warn:
        # A silent NPU -> CPU fallback is recorded there, and it travels with
        # the row: a reader comparing two devices has to know that one of them
        # was not the device the run asked for.
        cond["execution_warnings"] = len(warn)
        cond["execution_warning_1"] = str(warn[0])[:300]
    return be, dev, cond


def derive_backend(machine_fields):
    """(backend, how) from the box alone -- only where it is not a guess."""
    fields = machine_fields or {}
    os_name = str(fields.get("os") or "").lower()
    gpu = str(fields.get("gpu") or "").lower()
    if "darwin" in os_name or "macos" in os_name:
        return "metal", ("DERIVED: macOS, where Metal is compiled into the "
                         "official arm64 llama.cpp build (scripts/setup.sh, "
                         "PAT_MACOS_ARM64)")
    if os_name.startswith("windows") and "nvidia" in gpu:
        return "cuda", ("DERIVED: an NVIDIA card on Windows, where "
                        "scripts/setup.ps1 installs the CUDA build and "
                        "refuses to substitute another")
    if "nvidia" in gpu:
        return None, ("UNKNOWN: an NVIDIA card on a non-Windows box says "
                      "nothing about the backend -- scripts/setup.sh installs "
                      "the VULKAN build on Linux unless --cuda is given, "
                      "because there are no official Linux CUDA binaries")
    return None, ("UNKNOWN: nothing this row records about its box names a "
                  "backend")


def derive_device(backend, machine_fields):
    """(device, how) once the backend is known. OpenVINO is never derived."""
    gpu = named((machine_fields or {}).get("gpu"))
    if backend in ("cuda", "rocm", "vulkan", "sycl", "metal"):
        if gpu:
            return gpu, ("DERIVED: the %s build decodes on the card this row "
                         "names" % backend)
        return None, ("UNKNOWN: a %s row whose artefact names no card names "
                      "no device either" % backend)
    if backend == "cpu":
        return "CPU", "DERIVED: the cpu build has one device"
    if backend == "openvino":
        return None, ("UNKNOWN: an OpenVINO device is never derived. One "
                      "build decodes on CPU, on an iGPU or on an NPU, the "
                      "environment variable says only what was asked for, and "
                      "the device that was given is printed once, in the "
                      "server log (ggml-openvino.cpp:1526)")
    return None, ("UNKNOWN: the backend is unnamed, so its device cannot be "
                  "named")


# ---------------------------------------------------------------------------
# THE QUANT LADDER GUARD
#
# A refusal no field match can cure, because these rows are not mislabelled --
# the ladder does not exist. On OpenVINO the backend rewrites the weights
# before the first token (ggml/src/ggml-openvino/ggml-openvino-extra.cpp lines
# 252-273, through requantize_to_buffers at ggml-quants.cpp:841, which
# dequantises to F32 and re-quantises):
#
#   token_embd.weight -> F16 on NPU from a Q6_K source, otherwise Q8_0_C
#   output.weight     -> Q8_0_C on every device, always
#   on NPU            -> Q4_0_128 for every other quantized tensor, whatever
#                        the file said; even a Q4_0 file is re-blocked from 32
#                        weights per scale to 128
#   elsewhere         -> Q6_K and Q5_K both become Q8_0_C
#
# So a quant ladder on NPU has ONE arm, run several times under several file
# names, and a ladder that puts an OpenVINO arm beside a CUDA arm compares a
# rewritten model against the file.
# ---------------------------------------------------------------------------

# GGUF quantisation tokens as they appear in file names: IQ4_XS, Q4_K_M, Q8_0,
# Q2_K_XL, F16. Anchored on non-alphanumerics at both ends, so "Qwen3" and
# "QAT" do not become quantisations.
QUANT_RE = re.compile(r"(?<![0-9A-Za-z])"
                      r"(I?Q[0-9](?:_[0-9A-Za-z]+){0,3}|BF16|F16|F32|MXFP4)"
                      r"(?![0-9A-Za-z])")

LADDER_SOURCE = ("ggml/src/ggml-openvino/ggml-openvino-extra.cpp:252-273; the "
                 "rewrite itself is requantize_to_buffers at "
                 "ggml-quants.cpp:841, which dequantises to F32 and "
                 "re-quantises")


def quant_of(name):
    """The quantisation a model name declares, longest match, or None."""
    if not name:
        return None
    text = str(name).upper()
    for suffix in (".GGUF", ".BIN"):
        if text.endswith(suffix):
            text = text[:-len(suffix)]
    hits = QUANT_RE.findall(text)
    return max(hits, key=len) if hits else None


def row_quant(r):
    """This row's quantisation, from whichever field carries the model name."""
    for cand in (r.get("model_file"), (r.get("conditions") or {}).get("model"),
                 r.get("model_label"), r.get("model_path")):
        q = quant_of(cand)
        if q:
            return q
    return None


def ladder_guard(rows):
    """Refusals that no --assert-same can reach.

    Empty unless these rows form a quant ladder -- two or more quantisations
    of a model, side by side -- and at least one of them ran on OpenVINO.
    """
    arms = {}
    for r in rows:
        q = row_quant(r)
        if q:
            arms.setdefault(q, []).append(r)
    if len(arms) < 2:
        return []
    ov = [r for r in rows if r.get("backend") == "openvino"]
    if not ov:
        return []
    npu = [r for r in ov
           if str(r.get("device") or "").upper().startswith("NPU")]
    others = [r for r in rows
              if r.get("backend") and r.get("backend") != "openvino"]
    out = []
    if npu:
        out.append({"kind": "npu-ladder", "severity": "REFUSED",
                    "arms": arms, "rows": npu})
    if others:
        out.append({"kind": "mixed-backend-ladder", "severity": "REFUSED",
                    "arms": arms, "rows": ov + others,
                    "other_backends": sorted({r["backend"] for r in others})})
    if not npu and not others:
        out.append({"kind": "openvino-ladder", "severity": "WARNING",
                    "arms": arms, "rows": ov})
    return out


# ---------------------------------------------------------------------------
# rows
# ---------------------------------------------------------------------------

def row(campaign, source, extractor, metric, klass, value, unit,
        date=None, conditions=None, machine=None, build=None,
        machine_fields=None, build_fields=None, model=None, label=None,
        provenance="MEASURED", note=None, backend=None, device=None):
    """One measurement, with everything needed to refuse to misuse it."""
    conditions = {k: v for k, v in (conditions or {}).items() if v is not None}
    # An artefact that names the backend wins; otherwise the box is asked, and
    # it answers only where the answer is not a guess. Either way the row says
    # which of the two happened, so a reader can throw out the derivation
    # without throwing out the measurement (rule 1).
    if backend:
        backend_how = "RECORDED: named by the artefact this row came from"
    else:
        backend, backend_how = derive_backend(machine_fields)
    if device:
        device_how = "RECORDED: named by the artefact this row came from"
    else:
        device, device_how = derive_device(backend, machine_fields)
    rec = {
        "campaign": campaign,
        "model_file": os.path.basename(model.replace("\\", "/")) if model else None,
        "model_path": model,
        "model_label": label,
        "machine": machine,
        "build": build,
        "backend": backend,
        "device": device,
        "metric": metric,
        "class": klass,
        "value": value,
        "unit": unit,
        "date": date,
        "conditions": conditions,
        "source": source,
        "extractor": extractor,
        "provenance": provenance,
        "machine_fields": machine_fields or {},
        "build_fields": build_fields or {},
        "backend_source": backend_how,
        "device_source": device_how,
    }
    if note:
        rec["note"] = note
    ident = canon([campaign, rec["model_path"], machine, build, backend,
                   device, metric, conditions, date, source])
    rec["row"] = hashlib.sha1(ident.encode("utf-8")).hexdigest()[:12]
    return rec


# ---------------------------------------------------------------------------
# extractor 1: the rule-21 benchmark artefact (scripts/bench/bench.py)
# ---------------------------------------------------------------------------

def is_bench(doc):
    return (isinstance(doc, dict) and "suite_hash" in doc
            and isinstance(doc.get("results"), dict))


BENCH_METRICS = (
    # artefact key, metric prefix, unit, class
    ("score", "accuracy", "score 0-100", "accuracy"),
    ("tok_s", "throughput", "t/s", "throughput"),
    ("ttft", "latency.ttft", "s", "throughput"),
    ("tokens", "appetite", "tokens", "appetite"),
    ("truncated_n", "truncation", "answers", "count"),
)


def extract_bench(doc, source, campaign):
    backend = doc.get("backend") or {}
    settings = doc.get("settings") or {}
    prov = doc.get("provenance") or doc.get("toolchain")
    be, dev, exec_cond = from_execution(
        (prov or {}).get("execution") if isinstance(prov, dict) else None)
    # bench.py's own backend block is the second place to look: it already
    # holds the engine, the server binary and the window, and a build that
    # records what it decoded with puts it here.
    be = be or named(backend.get("backend"))
    dev = dev or named(backend.get("device"))
    results = doc.get("results") or {}
    comp = doc.get("composite") or {}
    rule7 = doc.get("rule7_rerun") or {}
    by_ds = doc.get("max_tokens_by_dataset") or {}
    datasets = doc.get("datasets") or sorted(results)
    mid, bid, mfields = from_bench_machine(doc.get("machine"), backend)
    bfields = {"version": backend.get("version"),
               "server_bin": backend.get("server_bin")}
    date = doc.get("date")
    model = doc.get("model_key")
    label = doc.get("model_label")

    base = {
        "suite_hash": doc.get("suite_hash"),
        # Rule 21 votes the scored SET, not just the hash: a --suite run
        # narrowed by --datasets keeps the full suite's hash while asking a
        # different set of questions. Both are conditions, and only both
        # together make two Means comparable.
        "datasets": list(datasets),
        "scored_set": list(comp.get("included") or []),
        "samples": settings.get("samples"),
        "seed": settings.get("seed"),
        "max_tokens": settings.get("max_tokens"),
        "max_prompt_tokens": settings.get("max_prompt_tokens"),
        "temperature": settings.get("temperature"),
        "top_k": settings.get("top_k"),
        "top_p": settings.get("top_p"),
        "presence_penalty": settings.get("presence_penalty"),
        "ctx": backend.get("ctx"),
        "engine": backend.get("engine"),
        "server_args": backend.get("server_args"),
        "speculative": doc.get("speculative"),
        "judged": bool(doc.get("judge") or doc.get("judge_panel")),
        "protocol": doc.get("protocol"),
        "model": os.path.basename((model or "").replace("\\", "/")) or None,
        # A bench artefact does not say which sweep it belongs to. Left
        # explicitly None so the gate can say "not named" rather than guess.
        "sweep": None,
    }
    base.update(exec_cond)
    out = []
    for ds, res in sorted(results.items()):
        if not isinstance(res, dict):
            continue
        cond = dict(base, dataset=ds, n=res.get("n"),
                    scorer=res.get("scorer"),
                    graded_n=res.get("graded_n"),
                    truncated_n=res.get("truncated_n"),
                    prompt_truncated_n=res.get("prompt_truncated_n"),
                    unscored_reason=res.get("unscored_reason"),
                    seat_spread=res.get("mean_seat_spread"))
        if ds in by_ds:
            cond["max_tokens"] = by_ds[ds]
        if ds in (rule7.get("rerun_datasets") or []):
            cond["rule7_rerun"] = True
            if rule7.get("rerun_ctx"):
                cond["ctx"] = rule7["rerun_ctx"]
        for key, prefix, unit, klass in BENCH_METRICS:
            if res.get(key) is None:
                continue
            out.append(row(campaign, source, "bench-suite/v1",
                           "%s.%s" % (prefix, ds), klass, res[key], unit,
                           date=date, conditions=cond, machine=mid, build=bid,
                           machine_fields=mfields, build_fields=bfields,
                           model=model, label=label, backend=be, device=dev))
    for key, metric, note in (
            ("composite", "composite.mean",
             "composite index, never an accuracy (rule 21)"),
            ("composite_5", "composite.mean_5",
             "the five-benchmark Mean, published beside the seven-benchmark "
             "one so neither comparison breaks (rule 21)")):
        blk = doc.get(key) or {}
        if blk.get("mean") is None:
            continue
        cond = dict(base, scored_set=list(blk.get("included") or []),
                    composite_label=blk.get("label"))
        out.append(row(campaign, source, "bench-suite/v1", metric, "accuracy",
                       blk["mean"], "index 0-100", date=date, conditions=cond,
                       machine=mid, build=bid, machine_fields=mfields,
                       build_fields=bfields, model=model, label=label,
                       backend=be, device=dev,
                       provenance="DERIVED: mean of the scored set",
                       note=note))
    return out


# ---------------------------------------------------------------------------
# extractor 2: an arm sweep -- {"model":…, "arms":[{…}, …]}
#
# The de-facto shape of every probe sweep in this repo: attribute-power.py's
# energy arms, the drafter and ts-pick sweeps, the head-to-heads, the power-cap
# ladder. One FILE is one SWEEP, which is what rule 30 needs: those arms ran
# back to back, in one session, against one server-per-arm.
# ---------------------------------------------------------------------------

# metric -> the arm keys that carry it, best first
ARM_METRICS = (
    ("throughput.decode", ("mean_tps", "decode_tps", "mean_tps_at_depth"),
     "t/s", "throughput", None),
    ("throughput.prefill", ("prefill_tps", "prompt_tps"),
     "t/s", "throughput", None),
    ("acceptance", ("acceptance", "accept_rate"),
     "fraction", "acceptance", None),
    ("draft_len.mean", ("mean_accepted_len", "draft_len", "accepted_per_pass"),
     "tokens", "acceptance", None),
    ("vram.after_load", ("vram_after_load_mib", "vram_mib", "vram_load"),
     "MiB", "memory", None),
    ("vram.peak", ("vram_peak", "peak_mib"), "MiB", "memory", None),
    ("vram.at_depth", ("vram_depth",), "MiB", "memory", None),
    ("vram.slack", ("slack_mib",), "MiB", "memory", None),
    ("power.mean_w", ("mean_w",), "W", "energy", "window"),
    ("power.peak_w", ("peak_w",), "W", "energy", "window"),
    ("energy.j_total", ("j_total",), "J", "energy", "total"),
    ("energy.j_decode", ("j_decode",), "J", "energy", "decode"),
    ("energy.j_prefill", ("j_prefill",), "J", "energy", "prefill"),
    ("energy.j_per_token", ("j_per_tok",), "J", "energy", "decode"),
    ("energy.j_per_decode_token", ("j_per_decode_token",), "J", "energy",
     "decode"),
    ("energy.j_per_decode_token_net", ("j_per_decode_token_net",), "J",
     "energy", "decode"),
    ("energy.wh_per_answer_net", ("wh_per_answer_net",), "Wh", "energy",
     "total"),
    ("energy.tokens_per_kwh", ("tokens_per_kwh",), "tokens/kWh", "energy",
     "total"),
)
_ARM_METRIC_KEYS = {k for _, keys, _, _, _ in ARM_METRICS for k in keys}

ARM_LABEL_KEYS = ("arm", "label", "id", "name", "cap", "fa", "drafter")
ARM_BULK = ("probes", "per_pos_rate", "fa_log_lines", "log", "logs",
            "rows", "events", "power_files", "samples")
# Promoted to the row itself, so they are not also copied into conditions:
# the gate compares FIELDS, and one value in two places is one refactor from
# being two values.
PROMOTED = ("backend", "device", "execution")


def is_arm_sweep(doc):
    arms = doc.get("arms") if isinstance(doc, dict) else None
    if not isinstance(arms, list) or not arms:
        return False
    first = arms[0]
    return isinstance(first, dict) and any(k in first for k in _ARM_METRIC_KEYS)


def arm_label(arm, index):
    for k in ARM_LABEL_KEYS:
        if arm.get(k) not in (None, ""):
            return str(arm[k])
    return "arm[%d]" % index


def extract_arm_sweep(doc, source, campaign, sweep, arms=None, extra=None,
                      date=None):
    arms = doc.get("arms") if arms is None else arms
    prov = doc.get("provenance") or doc.get("toolchain")
    mid, bid, mfields = from_provenance(prov)
    bfields = {}
    if isinstance(prov, dict) and isinstance(prov.get("llama_cpp"), dict):
        bfields = {k: prov["llama_cpp"].get(k)
                   for k in ("version", "build", "commit")}
    model = doc.get("model") or doc.get("model_key")
    doc_be, doc_dev, exec_cond = from_execution(
        (prov or {}).get("execution") if isinstance(prov, dict) else None)
    doc_be = doc_be or named(doc.get("backend"))
    doc_dev = doc_dev or named(doc.get("device"))
    doc_cond = scalars(doc, drop=("arms", "provenance", "toolchain", "model",
                                  "results") + ARM_BULK + PROMOTED)
    doc_cond.update(exec_cond)
    date = date or doc.get("generated") or doc.get("date") or doc.get("t")

    out = []
    for i, arm in enumerate(arms):
        if not isinstance(arm, dict):
            continue
        label = arm_label(arm, i)
        armfile = arm.get("file") or arm.get("model")
        cond = dict(doc_cond)
        for k, v in (extra or {}).items():
            cond.setdefault(k, v)          # fills gaps, never overrides
        cond.update(scalars(arm, drop=ARM_BULK + PROMOTED))
        # An ARM may carry its own execution context: a sweep whose arms are
        # backends is exactly the sweep this repository is about to run, and
        # the arm wins over the file it sits in.
        arm_be, arm_dev, arm_exec = from_execution(arm.get("execution"))
        be = arm_be or named(arm.get("backend")) or doc_be
        dev = arm_dev or named(arm.get("device")) or doc_dev
        cond.update(arm_exec)
        cond["sweep"] = sweep
        cond["arm"] = label
        cond["arm_pos"] = i
        cond["model"] = os.path.basename(
            str(armfile or model or "").replace("\\", "/")) or None
        if isinstance(arm.get("probes"), list):
            cond["probes"] = len(arm["probes"])
        for metric, keys, unit, klass, phase in ARM_METRICS:
            for k in keys:
                if arm.get(k) is None:
                    continue
                c = dict(cond)
                if phase:
                    c["phase"] = phase
                for consumed in _ARM_METRIC_KEYS:
                    c.pop(consumed, None)
                out.append(row(campaign, source, "arm-sweep/v1", metric, klass,
                               arm[k], unit, date=date, conditions=c,
                               machine=mid, build=bid, machine_fields=mfields,
                               build_fields=bfields, backend=be, device=dev,
                               model=armfile or model, label=label))
                break
    return out


# ---------------------------------------------------------------------------
# extractor 3: an arms.py per-probe ledger -- results/<slug>/data/*.jsonl
#
# The go-forward path. Every line already carries the sweep, the arm, the pass,
# the window and where the window came from, so the gate has everything it
# needs without a single inference.
# ---------------------------------------------------------------------------

def extract_arms_ledger(lines, source, campaign):
    header, out = {}, []
    for rec in lines:
        if rec.get("kind") == "sweep_start":
            header = rec
            continue
        if rec.get("kind") not in ("probe", "arm_failed"):
            continue
        t = rec.get("timings") or {}
        draft = rec.get("drafting") or {}
        vram = rec.get("vram") or {}
        flags = rec.get("flags") or rec.get("flags_resolved") or []
        sweep = "%s:%s" % (rec.get("armfile") or header.get("armfile") or "?",
                           rec.get("sweep") or "?")
        prov = header.get("provenance") or header.get("toolchain")
        mid, bid, mfields = from_provenance(prov)
        # arms.py writes the header once and every probe line afterwards, so
        # the execution context can arrive on either: the probe wins, because
        # a sweep may relaunch the server on another device between arms.
        be, dev, exec_cond = from_execution(
            (prov or {}).get("execution") if isinstance(prov, dict) else None)
        p_be, p_dev, p_exec = from_execution(rec.get("execution"))
        be = p_be or named(rec.get("backend")) or be
        dev = p_dev or named(rec.get("device")) or dev
        exec_cond = dict(exec_cond, **p_exec)
        cond = {
            "sweep": sweep, "arm": rec.get("arm"), "rep": rec.get("rep"),
            "arm_pos": rec.get("pos"), "order_mode": rec.get("order_mode"),
            "probe": rec.get("probe"), "probe_index": rec.get("probe_index"),
            # Rule 12 counts from the SERVER LOAD, not from the arm, and after
            # a mid-arm --resume the two stop agreeing: probe_index 1 can be
            # the first thing a fresh server answered. arms.py discards by
            # this number, so it is the only field on the row that says which
            # reading was taken on ramping clocks. A field that never reaches
            # a row cannot do its job.
            "load_probe_index": rec.get("load_probe_index"),
            "ctx": rec.get("ctx_size"), "ctx_source": rec.get("ctx_source"),
            "flags": " ".join(str(f) for f in flags) or None,
            # Pulled out by name because the gate compares FIELDS: the drafter
            # and the K/V type are conditions of acceptance (rules 3 and 11),
            # and re-parsing a flags array at compare time is one refactor
            # from being parsed wrongly.
            "spec": spec_flags(flags),
            "kv": flag_value(flags, "-ctk") or flag_value(flags, "--cache-type-k"),
            "model": os.path.basename(str(rec.get("model_path")
                                          or rec.get("model")
                                          or "").replace("\\", "/")) or None,
            "depth": t.get("prompt_n"),
            "n_predict": rec.get("n_predict"),
            "predicted_n": t.get("predicted_n"),
            "truncated": rec.get("truncated"),
            "empty_answer": rec.get("empty_answer"),
            "discarded": rec.get("discarded"),
            "prompt_sha256": rec.get("prompt_sha256"),
            "spec_sha": rec.get("spec_sha"),
            "server_bin": rec.get("server_bin"),
        }
        cond.update(exec_cond)
        req = rec.get("request") or {}
        for k in ("temperature", "top_k", "top_p", "seed"):
            if req.get(k) is not None:
                cond[k] = req[k]
        model = rec.get("model_path") or rec.get("model")
        date = rec.get("ts") or rec.get("t_start_iso")
        common = dict(campaign=campaign, source=source,
                      extractor="arms-ledger/v1", date=date, conditions=cond,
                      machine=mid, build=bid, machine_fields=mfields,
                      backend=be, device=dev,
                      model=model, label=rec.get("arm"))
        if rec.get("kind") == "arm_failed":
            out.append(row(metric="load.failed", klass="load", value=1,
                           unit="arms", note=str(rec.get("error"))[:200],
                           **common))
            continue
        # Rule 12: the first post-prefill probe reads up to 45% low on ramping
        # clocks and the sweep discards it. It stays in the ledger, flagged,
        # because a discarded reading is a fact about the run.
        for metric, key, unit, klass in (
                ("throughput.decode", "predicted_per_second", "t/s",
                 "throughput"),
                ("throughput.prefill", "prompt_per_second", "t/s",
                 "throughput")):
            if t.get(key) is not None:
                out.append(row(metric=metric, klass=klass, value=t[key],
                               unit=unit, **common))
        for metric, key, unit in (("acceptance", "acceptance", "fraction"),
                                  ("draft_len.mean", "accepted_per_pass",
                                   "tokens")):
            if draft.get(key) is not None:
                out.append(row(metric=metric, klass="acceptance",
                               value=draft[key], unit=unit, **common))
        if vram.get("peak_mib") is not None:
            out.append(row(metric="vram.peak", klass="memory",
                           value=vram["peak_mib"], unit="MiB", **common))
    return out


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

SKIP_DIRS = {"__pycache__", "packets", "ratings", "events", "logs",
             "close3-logs", "cpu-logs", "drafter-window-logs", "fa-logs",
             "hostcorr-logs", "needle-logs", "ngram-logs", "powercap-logs",
             "probelen-logs", "promptab-logs", "refarm-logs", "resolution-logs",
             "sampling-logs", "samplerband-logs"}


def campaign_dirs(results_dir):
    for name in sorted(os.listdir(results_dir)):
        path = os.path.join(results_dir, name)
        if os.path.isdir(path):
            yield name, path


def data_dir_of(camp_path):
    """The campaign's own data_dir, per results/TEMPLATE-campaign.json.

    work/ is declared scratch by that template -- "safe to lose" -- so nothing
    under it may become a ledger row: a number whose source is re-creatable
    scratch has no source.
    """
    cfg = os.path.join(camp_path, "campaign.json")
    if os.path.isfile(cfg):
        try:
            with open(cfg, encoding="utf-8") as fh:
                d = json.load(fh)
            if d.get("data_dir"):
                return os.path.join(camp_path, d["data_dir"])
        except (ValueError, OSError):
            pass
    return os.path.join(camp_path, "data")


def read_jsonl(path):
    out = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue                      # a torn last line is a crash, not data
    return out


class Sweep(object):
    """One arm-sweep artefact, before it is known whether it survives.

    An artefact that re-emits ONE arm of a sweep says nothing about the arms
    running together, which is the only thing rule 30 accepts as grounds for
    an absolute comparison. attribute-power.py writes both shapes -- the whole
    sweep and a file per arm -- so the same joules appear up to three times.
    """

    def __init__(self, path, doc, arms, extras=None, dates=None):
        self.path = path
        self.doc = doc
        self.arms = arms
        self.extras = extras or [{} for _ in arms]
        self.dates = dates or [None for _ in arms]
        self.labels = {arm_label(a, i) for i, a in enumerate(arms)
                       if isinstance(a, dict)}
        self.merged = {}
        self.superseded_by = None

    def doc_fields(self):
        return scalars(self.doc, drop=("arms", "provenance", "toolchain",
                                       "model", "results") + ARM_BULK
                                      + PROMOTED)


def supersede(sweeps, log):
    """Drop artefacts whose arms are a strict subset of another's, IN THE SAME
    DIRECTORY, and fold their file-level conditions into the survivor.

    Same directory only: `register/` holds a dozen unrelated sweeps, and
    pooling their file-level fields would attach one probe's instrumentation
    tier to another probe's watts. The subset relation is the evidence that
    two artefacts describe the same run.
    """
    by_dir = {}
    for s in sweeps:
        by_dir.setdefault(os.path.dirname(s.path), []).append(s)
    for group in by_dir.values():
        for s in group:
            bigger = [b for b in group if b is not s and s.labels < b.labels]
            if bigger:
                s.superseded_by = max(bigger, key=lambda b: (len(b.labels),
                                                             b.path))
    for s in sweeps:
        if s.superseded_by is None:
            continue
        win = s.superseded_by
        while win.superseded_by is not None:
            win = win.superseded_by
        for k, v in s.doc_fields().items():
            win.merged.setdefault(k, v)
        win.merged["merged_from_n"] = win.merged.get("merged_from_n", 0) + 1
        shown = win.merged.setdefault("merged_from", [])
        if len(shown) < 4:
            shown.append(os.path.basename(s.path))
        log("  %s: superseded by %s (%d arms vs %d); its file-level "
            "conditions were folded in"
            % (rel(s.path), os.path.basename(win.path), len(s.labels),
               len(win.labels)))
    return [s for s in sweeps if s.superseded_by is None]


def scan_campaign(name, camp_path, log):
    """Every row this campaign's data directory can support."""
    rows, seen_sources = [], 0
    data = data_dir_of(camp_path)
    if not os.path.isdir(data):
        log("  %s: no data directory at %s" % (name, rel(data)))
        return rows, 0
    sweeps = []
    files = []
    for root, dirs, names in os.walk(data):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for fn in sorted(names):
            if fn.endswith("_transcripts.json"):
                continue
            if fn.endswith((".json", ".jsonl")):
                files.append(os.path.join(root, fn))

    # Pass 1: read every artefact and decide what it is. Arm sweeps are held
    # back, because whether one of them is a redundant re-emission of another
    # is only knowable once its whole directory has been read.
    for path in [p for p in files if p.endswith(".jsonl")]:
        lines = read_jsonl(path)
        if not lines:
            continue
        if any(r.get("kind") in ("probe", "sweep_start", "arm_failed")
               for r in lines):
            got = extract_arms_ledger(lines, rel(path), name)
            if got:
                seen_sources += 1
                rows += got
        elif all(isinstance(r.get("arm"), dict) for r in lines):
            sweeps.append(Sweep(path, {}, [r["arm"] for r in lines],
                                extras=[scalars(r, drop=("arm",))
                                        for r in lines],
                                dates=[r.get("t") for r in lines]))

    for path in [p for p in files if p.endswith(".json")]:
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (ValueError, OSError, UnicodeDecodeError):
            continue
        if not isinstance(doc, dict):
            continue
        if is_bench(doc):
            got = extract_bench(doc, rel(path), name)
            if got:
                seen_sources += 1
                rows += got
        elif is_arm_sweep(doc):
            sweeps.append(Sweep(path, doc, doc["arms"]))

    # Pass 2: emit the arm sweeps that survived supersession.
    for s in supersede(sweeps, log):
        source = rel(s.path)
        sweep = os.path.splitext(os.path.basename(s.path))[0]
        got = []
        if s.doc:
            got = extract_arm_sweep(s.doc, source, name, sweep,
                                    extra=s.merged)
        else:
            for arm, extra, date in zip(s.arms, s.extras, s.dates):
                got += extract_arm_sweep({}, source, name, sweep, arms=[arm],
                                         extra=dict(s.merged, **extra),
                                         date=date)
        if got:
            seen_sources += 1
            rows += got

    # The campaign's own machine profile fills in rows whose artefact names no
    # box. It is the campaign's declaration about its rig, so it is evidence --
    # but it is weaker evidence than a provenance block written by the probe,
    # and `check` says so on every row that used it.
    mach = os.path.join(camp_path, "machine.json")
    if os.path.isfile(mach):
        try:
            with open(mach, encoding="utf-8") as fh:
                prof = json.load(fh)
        except (ValueError, OSError):
            prof = None
        if isinstance(prof, dict):
            mid = machine_id(prof.get("gpu_name"), prof.get("driver"),
                             prof.get("os"))
            # detect-machine.py records the backend of the build INSTALLED on
            # this box, with how it knows (MEASURED from INSTALL.json, DERIVED
            # from the platform, or UNKNOWN). That is a weaker claim than a
            # probe recording what it launched -- a campaign can run a
            # different binary than bin/llama.cpp holds -- so the row says
            # where the answer came from.
            prof_backend = named(prof.get("backend"))
            prof_how = ((prof.get("provenance") or {}).get("backend")
                        or {}).get("how")
            filled, filled_be = 0, 0
            for r in rows:
                if not r["machine"] and mid:
                    r["machine"] = mid
                    r["machine_fields"] = {"gpu": prof.get("gpu_name"),
                                           "driver": prof.get("driver"),
                                           "os": prof.get("os"),
                                           "host": prof.get("host")}
                    r["conditions"]["machine_source"] = "campaign machine.json"
                    filled += 1
                if not r["backend"] and prof_backend:
                    r["backend"] = prof_backend
                    r["backend_source"] = (
                        "campaign machine.json: the backend of the build "
                        "INSTALLED on this box, not one this probe recorded "
                        "(%s)" % (prof_how or "no provenance recorded there"))
                    if not r["device"]:
                        dev, how = derive_device(prof_backend,
                                                 r["machine_fields"])
                        if dev:
                            r["device"], r["device_source"] = dev, how
                    filled_be += 1
            if filled:
                log("  %s: %d row(s) took their machine from machine.json"
                    % (name, filled))
            if filled_be:
                log("  %s: %d row(s) took their backend from machine.json"
                    % (name, filled_be))
    return rows, seen_sources


def sort_key(r):
    return (r["campaign"], r["source"], r["metric"], canon(r["conditions"]),
            r["row"])


def build_rows(results_dir, log):
    rows, sources = [], 0
    for name, path in campaign_dirs(results_dir):
        got, n = scan_campaign(name, path, log)
        log("  %-28s %5d row(s) from %d artefact(s)" % (name, len(got), n))
        rows += got
        sources += n
    rows.sort(key=sort_key)
    return rows, sources


ROW_ORDER = ("row", "campaign", "model_file", "model_label", "machine",
             "build", "backend", "device", "metric", "class", "value", "unit",
             "date", "conditions", "source", "extractor", "provenance", "note",
             "model_path", "machine_fields", "build_fields", "backend_source",
             "device_source")


def dump_row(r):
    ordered = {k: r[k] for k in ROW_ORDER if k in r}
    for k in r:
        ordered.setdefault(k, r[k])
    return json.dumps(ordered, ensure_ascii=False, separators=(",", ":"))


def git_head():
    try:
        out = subprocess.run(["git", "-C", REPO, "rev-parse", "--short", "HEAD"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             timeout=10)
        return out.stdout.decode().strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def render_ledger(rows, results_dir, sources):
    body = "\n".join(dump_row(r) for r in rows)
    header = {
        "kind": "header",
        "_schema": SCHEMA,
        "_generated_by": "scripts/ledger.py -- GENERATED, never hand-edited. "
                         "Rebuild instead of editing: python scripts/ledger.py "
                         "build",
        "generated_utc": datetime.datetime.now(
            datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo_head": git_head(),
        "results_dir": rel(results_dir),
        "campaigns": sorted({r["campaign"] for r in rows}),
        "artefacts": sources,
        "rows": len(rows),
        "metrics": sorted({r["metric"] for r in rows}),
        "classes": sorted({r["class"] for r in rows}),
        # Hand-edit any row and this stops matching, which is how `check`
        # notices that the ledger stopped being generated.
        "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
    }
    return json.dumps(header, ensure_ascii=False) + "\n" + body + "\n"


def load_ledger(path):
    if not os.path.isfile(path):
        sys.exit("no ledger at %s -- run: python scripts/ledger.py build"
                 % rel(path))
    recs = read_jsonl(path)
    if not recs or recs[0].get("kind") != "header":
        sys.exit("%s has no header line; rebuild it" % rel(path))
    schema = recs[0].get("_schema")
    if schema != SCHEMA:
        print(wrap("NOTE: %s was generated under %r; this tool writes %r. Its "
                   "rows predate the backend and device fields, so every "
                   "comparison refuses on them until it is rebuilt:"
                   % (rel(path), schema, SCHEMA), indent=""))
        print("    python scripts/ledger.py build\n")
    return recs[0], recs[1:]


def cmd_build(args):
    results_dir = args.results or os.path.join(REPO, "results")
    if not os.path.isdir(results_dir):
        sys.exit("no results directory at %s" % rel(results_dir))
    log = (lambda s: None) if args.quiet else (lambda s: print(s))
    log("scanning %s" % rel(results_dir))
    rows, sources = build_rows(results_dir, log)
    text = render_ledger(rows, results_dir, sources)
    if args.stdout:
        sys.stdout.write(text)
        return 0
    out = args.out or os.path.join(REPO, DEFAULT_OUT)
    body_new = "\n".join(dump_row(r) for r in rows)
    if os.path.isfile(out):
        old_header, old_rows = load_ledger(out)
        body_old = "\n".join(dump_row(r) for r in old_rows)
        if body_old == body_new and not args.force:
            print("\n%d row(s), unchanged -- %s not rewritten (--force to "
                  "restamp the date)" % (len(rows), rel(out)))
            return 0
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print("\n%d row(s) from %d artefact(s) -> %s"
          % (len(rows), sources, rel(out)))
    print("commit it: the diff IS the record of what changed and when.")
    return 0


# ---------------------------------------------------------------------------
# check -- rows that must never reach a comparison (rule 3)
# ---------------------------------------------------------------------------

def check_row(r):
    """(blocking, thin) -- the fields this row is missing, by severity."""
    spec = CLASSES.get(r.get("class"))
    if not spec:
        return ["class %r is not in the gate table" % r.get("class")], []
    blocking = [f for f in spec["gate"] if not present(get(r, f))]
    thin = [f for f in spec["thin"] if not present(get(r, f))]
    if not present(get(r, "machine_fields.host")):
        thin.append("machine_fields.host")
    if not present(get(r, "date")):
        blocking.append("date")
    return blocking, thin


def cmd_check(args):
    path = args.ledger or os.path.join(REPO, DEFAULT_OUT)
    header, rows = load_ledger(path)
    body = "\n".join(dump_row(r) for r in rows)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    print("ledger  : %s" % rel(path))
    print("rows    : %d in %d campaign(s), generated %s from %s"
          % (len(rows), len(header.get("campaigns") or []),
             header.get("generated_utc"), header.get("repo_head") or "?"))
    edited = digest != header.get("body_sha256")
    print("integrity: %s" % ("HAND-EDITED OR TRUNCATED -- body_sha256 does not "
                             "match; rebuild before trusting a single row"
                             if edited else "generated, matches body_sha256"))

    blocked, thinned = {}, {}
    for r in rows:
        b, t = check_row(r)
        for f in b:
            blocked.setdefault((r["class"], f), []).append(r)
        for f in t:
            thinned.setdefault((r["class"], f), []).append(r)

    print("\nBLOCKING -- the gate needs this field and the row does not carry "
          "it, so\nthe row can never enter a comparison of its class "
          "(rule 3: a number without\nits conditions is unfalsifiable).")
    if not blocked:
        print("  none.")
    for (klass, field), rs in sorted(blocked.items(),
                                     key=lambda kv: -len(kv[1])):
        spec = CLASSES.get(klass, {})
        print("\n  %-10s %-28s %4d row(s)   [%s]"
              % (klass, field, len(rs), spec.get("rules", "")))
        for src in sorted({r["source"] for r in rs})[:args.examples]:
            print("      %s" % src)
        extra = len({r["source"] for r in rs}) - args.examples
        if extra > 0:
            print("      ... and %d more artefact(s)" % extra)
        if field in REMEDY:
            print(wrap("FIX: %s" % REMEDY[field]))

    print("\nTHIN -- the row compares, but a condition rule 3 names for its "
          "class is\nabsent, so every comparison it enters inherits the gap.")
    if not thinned:
        print("  none.")
    for (klass, field), rs in sorted(thinned.items(),
                                     key=lambda kv: -len(kv[1])):
        print("  %-10s %-30s %4d row(s)" % (klass, field, len(rs)))

    print("\nDEGENERATE BY CONSTRUCTION -- a group of rows that looks "
          "like a ladder but\nis one arm repeated, because the backend "
          "rewrote the weights before it ran\nthem. No field match cures "
          "these; the comparison does not exist.")
    groups, degenerate = {}, 0
    for r in rows:
        sweep = get(r, "conditions.sweep")
        key = (r["campaign"], show(sweep) if present(sweep) else r["source"])
        groups.setdefault(key, []).append(r)
    for key in sorted(groups):
        for g in ladder_guard(groups[key]):
            if g["severity"] == "REFUSED":
                degenerate += 1
            print("  %-8s %s  in %s" % (g["severity"], key[0], key[1]))
            print("           %s" % LADDER_TITLE[g["kind"]])
            print("           arms: %s" % ", ".join(sorted(g["arms"])))
    if not degenerate:
        print("  no refused ladder. %d group(s) of rows were checked."
              % len(groups))

    n_bad = len({r["row"] for rs in blocked.values() for r in rs})
    print("\n%d of %d row(s) are BLOCKED from comparison; %d artefact(s) "
          "produced them."
          % (n_bad, len(rows),
             len({r["source"] for rs in blocked.values() for r in rs})))
    if degenerate:
        print("%d ladder(s) are degenerate by construction." % degenerate)
    if edited or ((n_bad or degenerate) and not args.warn_only):
        return 1
    return 0


# ---------------------------------------------------------------------------
# selection
# ---------------------------------------------------------------------------

def parse_where(pairs):
    out = []
    for p in pairs or []:
        if "=" not in p:
            sys.exit("--where takes field=value (got %r)" % p)
        k, v = p.split("=", 1)
        out.append((k.strip(), v.strip()))
    return out


def select(rows, args):
    out = []
    where = parse_where(args.where)
    for r in rows:
        if args.metric and r["metric"] != args.metric:
            continue
        if args.klass and r["class"] != args.klass:
            continue
        if args.campaign and r["campaign"] != args.campaign:
            continue
        if args.model and args.model not in (r.get("model_file") or ""):
            continue
        if args.source and args.source not in r["source"]:
            continue
        ok = True
        for k, v in where:
            got_v = get(r, k)
            if v == "":
                ok = ok and not present(got_v)
            else:
                ok = ok and show(got_v) == v
        if ok:
            out.append(r)
    return out


def varying(rows, skip=()):
    """The condition keys that actually differ across these rows."""
    keys = set()
    for r in rows:
        keys |= set(r["conditions"])
    out = []
    for k in sorted(keys):
        if k in skip:
            continue
        vals = {show(r["conditions"].get(k)) for r in rows}
        if len(vals) > 1:
            out.append(k)
    return out


def with_label(rows, columns):
    """Put the arm's own name in front when the rows carry different ones.

    A table of three numbers that does not say which arm each one is is a
    table a reader cannot use -- and a table whose rows ran on two backends
    without saying so is worse, because it looks usable.
    """
    out = list(columns)
    front = []
    for field in ("model_label", "backend", "device"):
        key = "@" + field
        if len({r.get(field) for r in rows}) > 1 and key not in out:
            front.append(key)
    return front + out


def print_table(rows, columns, indent="  "):
    head = ["row", "value", "unit"] + [c.lstrip("@") for c in columns] \
        + ["date", "source"]
    body = []
    for r in rows:
        cells = [show(r.get(c[1:])) if c.startswith("@")
                 else show(r["conditions"].get(c)) for c in columns]
        body.append([r["row"], fmt(r["value"]), r["unit"] or ""] + cells
                    + [(r["date"] or "")[:19], r["source"]])
    widths = [max(len(str(x)) for x in [h] + [b[i] for b in body])
              for i, h in enumerate(head)]
    # Everything is clipped except the last column, which is the source path:
    # a row whose provenance is elided is a row a reader cannot go and check.
    widths = [min(w, 34) for w in widths[:-1]] + widths[-1:]

    def line(cells):
        return indent + "  ".join(str(c)[:w].ljust(w)
                                  for c, w in zip(cells, widths)).rstrip()
    print(line(head))
    print(indent + "  ".join("-" * w for w in widths))
    for b in body:
        print(line(b))


def cmd_rows(args):
    path = args.ledger or os.path.join(REPO, DEFAULT_OUT)
    _, rows = load_ledger(path)
    picked = select(rows, args)
    if args.json:
        for r in picked[:args.limit]:
            print(dump_row(r))
        return 0
    if not picked:
        print("no rows match.")
        return 0
    cols = varying(picked, skip=("prompt_sha256", "spec_sha", "server_args",
                                 "flags", "conditions"))[:args.columns]
    shown = picked[:args.limit]
    print("%d row(s); showing %d" % (len(picked), len(shown)))
    print_table(shown, with_label(shown, cols))
    return 0


# ---------------------------------------------------------------------------
# THE GATE
# ---------------------------------------------------------------------------

def gate(rows, asserted=()):
    """(ok, refusals). A refusal names the field and what it holds.

    Two failure modes, and they are different failures:
      NOT NAMED  the field is absent on some rows. Two rows that do not name
                 their sweep are not thereby in the same sweep -- unknown is
                 never equal to unknown.
      DIFFERS    the field is named on every row and the values disagree.
    """
    klass = rows[0]["class"]
    spec = CLASSES[klass]
    refusals = []
    for field in spec["gate"]:
        if field in asserted:
            continue
        missing = [r for r in rows if not present(get(r, field))]
        values = {}
        for r in rows:
            v = get(r, field)
            if present(v):
                values.setdefault(show(v), []).append(r)
        if missing:
            refusals.append({"field": field, "why": "NOT NAMED",
                             "rows": missing, "values": values})
        elif len(values) > 1:
            refusals.append({"field": field, "why": "DIFFERS",
                             "rows": [], "values": values})
    return (not refusals), refusals


def selector_flags(args):
    """The flags that produced this selection, so a suggested command keeps it.

    A remedy that silently widens the selection it is repairing is worse than
    no remedy: it refuses again, on different rows, and reads like a bug.
    """
    out = []
    for flag, value in (("--metric", args.metric), ("--class", args.klass),
                        ("--campaign", args.campaign), ("--model", args.model),
                        ("--source", args.source)):
        if value:
            out.append('%s "%s"' % (flag, value))
    for w in (args.where or []):
        out.append('--where "%s"' % w)
    return " ".join(out)


def print_refusal(metric, klass, rows, refusals, asserted, sel=""):
    spec = CLASSES[klass]
    print("REFUSED. %d row(s) of %s (class %s) may not stand in one "
          "comparison." % (len(rows), metric, klass))
    print("\n%s: %s" % (spec["rules"], spec["why"]))
    print("\nThe field(s) that stop it:")
    for ref in refusals:
        print("\n  %s  %s" % (ref["field"], ref["why"]))
        if ref["why"] == "NOT NAMED":
            print("      %d of %d row(s) carry no value for it:"
                  % (len(ref["rows"]), len(rows)))
            for src in sorted({r["source"] for r in ref["rows"]})[:4]:
                print("        %s" % src)
            if ref["values"]:
                print("      the other row(s) hold: %s"
                      % "; ".join(sorted(ref["values"])[:3]))
            print("      unknown is not equal to unknown: two rows that do "
                  "not name this")
            print("      field are not thereby the same.")
        else:
            for val, rs in sorted(ref["values"].items(),
                                  key=lambda kv: -len(kv[1]))[:6]:
                print("      %4d row(s)  %s" % (len(rs), val[:88]))
        if ref["field"] in FIELD_WHY:
            print(wrap(FIELD_WHY[ref["field"]]))
        if ref["field"] in REMEDY:
            print(wrap("FIX: %s" % REMEDY[ref["field"]]))
    if not spec["travels"]:
        print("\n  This class does not travel between sweeps at all. The "
              "comparison that\n  IS legal here is the ratio inside each "
              "sweep, which does travel:")
        print("      python scripts/ledger.py compare %s --ratio" % sel)
    biggest = largest_group(rows, refusals, asserted)
    if biggest:
        field, val, rs = biggest
        print("\n  The largest comparison this refusal still allows: %d row(s) "
              "with\n  %s=%s" % (len(rs), field, val[:60]))
        print("      python scripts/ledger.py compare %s --where \"%s=%s\""
              % (sel, field, val))
    print("\n  Override only with evidence you hold and the ledger does not:")
    print("      --assert-same %s" % " ".join(r["field"] for r in refusals))
    print("  The assertion is printed above the result, every time.")


LADDER_TITLE = {
    "npu-ladder": "a quant ladder on OpenVINO NPU, where every arm is "
                  "Q4_0_128",
    "mixed-backend-ladder": "a quant ladder mixing an OpenVINO arm with a "
                            "non-OpenVINO one",
    "openvino-ladder": "a quant ladder on OpenVINO, where part of every arm "
                       "is the same Q8_0_C tensors",
}


def _ladder_arms(ref):
    print("\n  the arms, by the quantisation each row's model name declares:")
    for q in sorted(ref["arms"]):
        rs = ref["arms"][q]
        backends = sorted({str(r.get("backend") or "backend not named")
                           for r in rs})
        devices = sorted({str(r.get("device") or "device not named")
                          for r in rs})
        print("      %-10s %3d row(s)   %s on %s"
              % (q, len(rs), "/".join(backends), "/".join(devices)))


def print_ladder(refusals, sel=""):
    """Refuse a ladder whose arms are not different weights, and say why.

    Nothing here is a field mismatch, so nothing here has an override: the
    rows are labelled correctly and the files really are different files. What
    ran was the same weights.
    """
    for ref in refusals:
        if ref["kind"] == "npu-ladder":
            print("REFUSED. A quant ladder on OpenVINO NPU has one arm: every "
                  "file in it\ndecoded as Q4_0_128.")
            _ladder_arms(ref)
            print("\n  WHY. llama.cpp's OpenVINO backend rewrites every "
                  "quantized tensor before\n  the first token. On NPU each "
                  "one becomes Q4_0_128 whatever the file said,\n  and even "
                  "a Q4_0 file is re-blocked from 32 weights per scale to "
                  "128 -\n  four times fewer scales than the file carries. "
                  "token_embd.weight and\n  output.weight are Q8_0_C on "
                  "every arm and on every device.")
            print(wrap(LADDER_SOURCE))
            print("\n  So these arms are the same weights under different "
                  "names. A difference\n  between them is session noise "
                  "(rule 30); a similarity is arithmetic, not a\n  finding. "
                  "Published, it tells a reader that quantisation does not "
                  "matter on\n  an NPU, which is not what was measured "
                  "(rule 2).")
            print("\n  There is no --assert-same for this. The rows are not "
                  "mislabelled and no\n  evidence held outside the ledger "
                  "changes what ran: the ladder does not exist.")
            print("\n  WHAT TO DO INSTEAD")
            print("    - rank the quants where the file survives contact "
                  "with the runtime -\n      CUDA, Vulkan, or CPU - and "
                  "publish the ranking as a property of that\n      backend "
                  "(rule 6: perplexity over 294,912 token positions).")
            print("    - on NPU measure ONE arm, and label it \"Q4_0_128, "
                  "requantised from\n      <file>\" rather than by the file "
                  "name.")
            print("    - to see the rewrite: GGML_OPENVINO_DUMP_IR=1 dumps "
                  "what actually ran.\n      Nothing else reports it - the "
                  "debug lines that would are commented out\n      at "
                  "ggml-openvino.cpp:332-346.")
        elif ref["kind"] == "mixed-backend-ladder":
            print("REFUSED. An OpenVINO arm and a %s arm are in one quant "
                  "ladder, and they did\nnot run the same weights."
                  % "/".join(ref["other_backends"]))
            _ladder_arms(ref)
            print("\n  WHY. The %s arm ran the file. The OpenVINO arm ran a "
                  "rewrite of it:\n  token_embd.weight and output.weight "
                  "become Q8_0_C, and Q6_K and Q5_K\n  tensors become "
                  "Q8_0_C, before the first token."
                  % "/".join(ref["other_backends"]))
            print(wrap(LADDER_SOURCE))
            print("\n  A ladder across those two measures the runtime at "
                  "least as much as the\n  quantisation, and nothing "
                  "recorded separates the two. Split it: one\n  ladder per "
                  "backend, each published with its backend named.")
            print("\n  WHAT TO DO INSTEAD")
            print("      python scripts/ledger.py compare %s --where "
                  "\"backend=openvino\"" % sel)
            print("      python scripts/ledger.py compare %s --where "
                  "\"backend=%s\"" % (sel, ref["other_backends"][0]))
        else:
            print("WARNING. This quant ladder ran on OpenVINO, so part of "
                  "every arm is the\nsame weights.")
            _ladder_arms(ref)
            print("\n  token_embd.weight and output.weight are Q8_0_C on "
                  "every arm whatever the\n  file said, and any Q6_K or "
                  "Q5_K tensor became Q8_0_C, so the ladder\n  measures a "
                  "narrower difference than the file names promise. Name the\n"
                  "  requantisation beside every number (rule 2).")
            print(wrap(LADDER_SOURCE))


def largest_group(rows, refusals, asserted):
    """The biggest subset one --where would rescue, or None."""
    best = None
    for ref in refusals:
        for val, rs in ref["values"].items():
            if len(rs) > 1 and (best is None or len(rs) > len(best[2])):
                best = (ref["field"], val, rs)
    return best


def print_permitted(metric, klass, rows, asserted, columns):
    spec = CLASSES[klass]
    print("PERMITTED. %d row(s) of %s (class %s) share every field %s "
          "requires." % (len(rows), metric, klass, spec["rules"]))
    if asserted:
        print("\n  ASSERTED BY THE OPERATOR, not by any artefact: %s treated "
              "as equal.\n  Nothing in the ledger establishes that. If the "
              "assertion is wrong, every\n  number below is wrong."
              % ", ".join(asserted))
    print("\n  matched: %s"
          % "; ".join("%s=%s" % (f, show(get(rows[0], f)))
                      for f in spec["gate"] if f not in asserted)[:220])
    cols = columns or varying(rows, skip=("prompt_sha256", "spec_sha",
                                          "flags", "server_args"))[:4]
    print()
    print_table(rows, with_label(rows, cols))
    vals = [num(r["value"]) for r in rows if num(r["value"]) is not None]
    if len(vals) > 1:
        lo, hi = min(vals), max(vals)
        span = ("%.3g%%" % ((hi - lo) / lo * 100.0)) if lo else "n/a"
        print("\n  span %s to %s -- %s of the low value. Rule 26: printed "
              "precision\n  respects the noise floor the campaign published; "
              "this tool does not know it." % (fmt(lo), fmt(hi), span))
    ov = [r for r in rows if r.get("backend") == "openvino"]
    if ov:
        print("\n  These %d row(s) ran on OpenVINO, which rewrites the file's "
              "weights before\n  it runs them, so every number above "
              "describes weights that are not the\n  ones in the GGUF: "
              "token_embd.weight and output.weight are Q8_0_C on every\n  "
              "device, Q6_K and Q5_K become Q8_0_C, and on NPU every other "
              "quantized\n  tensor becomes Q4_0_128. Say so beside the "
              "number (rule 2)." % len(ov))
        print(wrap(LADDER_SOURCE, indent="      "))
    comp = spec.get("companion", {})
    if metric in comp:
        print("\n  Rule 11: publish %s beside this, always -- acceptance IS "
              "the speedup,\n  but mean draft length is the throughput "
              "predictor." % comp[metric])


def cmd_compare(args):
    path = args.ledger or os.path.join(REPO, DEFAULT_OUT)
    _, rows = load_ledger(path)
    picked = select(rows, args)
    if not picked:
        print("no rows match.")
        return 0
    # The ladder guard runs BEFORE the field gate, and it is the more
    # fundamental refusal: the gate asks whether two rows may be compared,
    # this asks whether the second row is a second measurement at all.
    guards = ladder_guard(picked)
    refused = [g for g in guards if g["severity"] == "REFUSED"]
    if refused:
        print_ladder(refused, selector_flags(args))
        return 2
    for g in guards:
        print_ladder([g], selector_flags(args))
        print()
    classes = {r["class"] for r in picked}
    if len(classes) > 1:
        print("REFUSED. These rows span %d metric classes (%s) and each has "
              "its own\ngate. Narrow with --metric or --class."
              % (len(classes), ", ".join(sorted(classes))))
        return 2
    metrics = sorted({r["metric"] for r in picked})
    if len(metrics) > 1 and not args.ratio:
        print("REFUSED. %d different metrics selected (%s). A comparison is "
              "between\nlike and like; narrow with --metric."
              % (len(metrics), ", ".join(metrics[:6])))
        return 2
    if args.ratio:
        return compare_ratio(picked, args)
    if len(picked) < 2:
        print("only 1 row matches; nothing to compare.")
        print_table(picked, with_label(picked, varying(picked)[:4]))
        return 0
    asserted = tuple(args.assert_same or ())
    ok, refusals = gate(picked, asserted=asserted)
    if not ok:
        print_refusal(metrics[0], picked[0]["class"], picked, refusals,
                      asserted, selector_flags(args))
        return 2
    print_permitted(metrics[0], picked[0]["class"], picked, asserted,
                    args.column)
    return 0


# ---------------------------------------------------------------------------
# ratios -- the thing that travels
# ---------------------------------------------------------------------------

def compare_ratio(picked, args):
    metric = sorted({r["metric"] for r in picked})[0]
    picked = [r for r in picked if r["metric"] == metric]
    unnamed = [r for r in picked if not present(get(r, "conditions.sweep"))]
    if unnamed:
        print("REFUSED. A ratio is defined INSIDE one sweep, and %d of %d "
              "row(s) do not\nname a sweep. rule 30: compare arms inside one "
              "sweep, never across two." % (len(unnamed), len(picked)))
        for src in sorted({r["source"] for r in unnamed})[:5]:
            print("    %s" % src)
        print("  FIX: %s" % REMEDY["conditions.sweep"])
        return 2

    sweeps = {}
    for r in picked:
        sweeps.setdefault(r["conditions"]["sweep"], []).append(r)
    ratio_rows = []
    print("Ratios inside each sweep. rule 30: %s\n" % CLASSES["ratio"]["why"])
    for sweep in sorted(sweeps):
        rs = sorted(sweeps[sweep],
                    key=lambda r: (r["conditions"].get("arm_pos") or 0))
        base = None
        if args.baseline:
            for r in rs:
                if args.baseline in show(r["conditions"].get("arm")):
                    base = r
                    break
            if base is None:
                print("  %s: no arm matching --baseline %r; skipped"
                      % (sweep, args.baseline))
                continue
        else:
            base = rs[0]
        b = num(base["value"])
        if not b:
            print("  %s: baseline %s has no usable value; skipped"
                  % (sweep, base["row"]))
            continue
        print("  sweep %s   baseline %s = %s %s"
              % (sweep, show(base["conditions"].get("arm")), fmt(b),
                 base["unit"] or ""))
        for r in rs:
            v = num(r["value"])
            if v is None or r is base:
                continue
            ratio = v / b
            ratio_rows.append(row(
                r["campaign"], r["source"], "ledger/ratio", "ratio", "ratio",
                round(ratio, 6), "ratio", date=r["date"],
                conditions={"of_metric": metric,
                            "numerator": show(r["conditions"].get("arm")),
                            "denominator": show(base["conditions"].get("arm")),
                            "model": r["conditions"].get("model"),
                            "sweep": sweep},
                machine=r["machine"], build=r["build"],
                # A ratio inherits the execution context of the rows it
                # divided. Two ratios from two backends are two claims about
                # two runtimes, and rule 30's "ratios travel" was measured on
                # one of them.
                backend=r.get("backend"), device=r.get("device"),
                model=r["model_path"], label=r["model_label"],
                provenance="DERIVED: this row's value divided by the "
                           "baseline arm's, inside one sweep"))
            print("      %-16s %10s  %+8.1f%%   against %s"
                  % (show(r["conditions"].get("arm")), fmt(v),
                     (ratio - 1.0) * 100.0,
                     show(base["conditions"].get("arm"))))
        print()

    if len(sweeps) < 2:
        print("Only one sweep here, so there is nothing to carry the ratio to.")
        return 0

    groups = {}
    for r in ratio_rows:
        key = (r["conditions"]["numerator"], r["conditions"]["denominator"],
               r["conditions"]["model"])
        groups.setdefault(key, []).append(r)
    print("Do the ratios travel? Each pair, across %d sweeps:" % len(sweeps))
    print()
    worst = 0.0
    for key in sorted(groups):
        rs = groups[key]
        if len(rs) < 2:
            continue
        ok, refusals = gate(rs)
        if not ok:
            print("  %s / %s: REFUSED on %s"
                  % (key[0], key[1], ", ".join(r["field"] for r in refusals)))
            continue
        vals = [r["value"] for r in rs]
        spread = max(vals) - min(vals)
        worst = max(worst, spread)
        print("  %-16s / %-16s  %-24s sign %s, spread %.3f"
              % (key[0], key[1],
                 " ".join("%+8.1f%%" % ((v - 1) * 100) for v in vals),
                 "HELD" if len({v > 1 for v in vals}) == 1 else "FLIPPED",
                 spread))
    print("\nPERMITTED: a ratio is gated on WHAT was divided by WHAT, never on "
          "where.\nThat is rule 30's whole operating consequence -- the "
          "absolutes above would\nbe refused across these sweeps, and the "
          "ratios are not.")
    return 0


# ---------------------------------------------------------------------------
# selftest -- no GPU, no network, no model, no results directory needed
# ---------------------------------------------------------------------------

PASSED, FAILED = [], []


def check(name, got, want):
    ok = got == want
    (PASSED if ok else FAILED).append(name)
    print("  %s %s: got %r%s" % ("ok  " if ok else "FAIL", name, got,
                                 "" if ok else ", want %r" % (want,)))


def _fixture(tmp):
    """A synthetic campaign carrying METHODOLOGY rule 30's own evidence.

    Two passes of one five-arm sweep, the second run last-to-first. The
    baseline arm moves 76.32 -> 67.41 t/s (-11.7%) while every relationship
    keeps its sign and rough size. Absolutes must be refused across the two;
    ratios must be permitted.
    """
    camp = os.path.join(tmp, "results", "synth-rule30")
    os.makedirs(os.path.join(camp, "data"))
    prov = {"recorded_by": "scripts/bench/provenance.py",
            "platform": "Linux-6.8.0-x86_64",
            "python": "3.11.9",
            "gpu": {"name": "NVIDIA GeForce RTX 3090", "driver": "596.36"},
            "llama_cpp": {"version": "0.1.2-dev", "build": "10502",
                          "commit": "0adcc3bb5"},
            # The block provenance.py writes. It is not decoration on a Linux
            # artefact: an NVIDIA card on Linux does not imply CUDA, because
            # scripts/setup.sh installs the Vulkan build unless --cuda is
            # given, so a Linux row without this block is refused by design.
            "execution": {"backend": "cuda",
                          "device": "NVIDIA GeForce RTX 3090",
                          "cuda_arch": "86", "build_tag": "b10502"}}
    passes = [
        ("forward", 76.32, {"B-f16": -8.9, "C-180k": -3.1, "E-n4-p0": 8.4}),
        ("reverse", 67.41, {"B-f16": -8.2, "C-180k": -4.7, "E-n4-p0": 13.2}),
    ]
    # Sampling on every arm, not in a prose "conditions" line: rule 3 makes it
    # a condition of the acceptance figure, and the gate can only read fields.
    sampling = {"temperature": 0.0, "top_k": 1, "top_p": 1.0,
                "spec": "--spec-type draft-mtp --spec-draft-n-max 10 "
                        "--spec-draft-p-min 0.5"}
    for name, baseline, moves in passes:
        arms = [dict(sampling, arm="A-baseline", mean_tps=baseline, ctx=32768,
                     kv="q8_0", acceptance=0.5159, mean_accepted_len=4.035)]
        for arm, pct in moves.items():
            arms.append(dict(
                sampling, arm=arm,
                mean_tps=round(baseline * (1 + pct / 100.0), 2),
                ctx=180224 if "180k" in arm else 32768,
                kv="f16" if "f16" in arm else "q8_0",
                acceptance=0.5159, mean_accepted_len=4.035))
        doc = {"model": "/m/Qwen3.8-27B-UD-IQ4_XS.gguf",
               "conditions": "greedy, temp 0 / top_k 1, 400 predicted tokens",
               "date": "2026-08-28T0%d:00:00Z" % (1 if name == "forward" else 2),
               "arms": arms}
        if name == "reverse":
            doc["arms"] = list(reversed(doc["arms"]))
        doc["provenance"] = prov
        with open(os.path.join(camp, "data", "ts-pick-%s.json" % name), "w",
                  encoding="utf-8") as fh:
            json.dump(doc, fh)
    # One artefact that names no box at all, so `check` has something to block.
    with open(os.path.join(camp, "data", "no-provenance.json"), "w",
              encoding="utf-8") as fh:
        json.dump({"model": "/m/Qwen3.8-27B-UD-IQ4_XS.gguf",
                   "date": "2026-08-28T03:00:00Z",
                   "arms": [{"arm": "X", "mean_tps": 80.0, "ctx": 32768}]}, fh)
    # An arms.py per-probe ledger, the go-forward shape.
    led = [{"kind": "sweep_start", "slug": "synth-rule30", "armfile": "spec",
            "provenance": prov},
           {"kind": "probe", "armfile": "spec", "sweep": "spec-sweep",
            "arm": "n10-p05", "rep": 1, "pos": 0, "probe": "code",
            "ctx_size": 32768, "ctx_source": "literal",
            "model_path": "/m/Qwen3.8-27B-UD-IQ4_XS.gguf",
            "flags": ["-ngl", "99", "-ctk", "q8_0", "-ctv", "q8_0",
                      "--spec-type", "draft-mtp",
                      "--spec-draft-n-max", "10", "--spec-draft-p-min", "0.5"],
            "ts": "2026-08-28T04:00:00Z",
            "request": {"temperature": 0.0, "top_k": 1, "top_p": 1.0},
            "timings": {"predicted_per_second": 76.32, "prompt_per_second": 22.9,
                        "prompt_n": 4, "predicted_n": 400},
            "drafting": {"acceptance": 0.5159, "accepted_per_pass": 4.035},
            "vram": {"peak_mib": 18195}},
           {"kind": "arm_failed", "armfile": "spec", "sweep": "spec-sweep",
            "arm": "c262144", "rep": 1, "ctx_size": 262144,
            "model_path": "/m/Qwen3.8-27B-UD-IQ4_XS.gguf",
            "ts": "2026-08-28T04:05:00Z", "error": "failed to allocate"}]
    with open(os.path.join(camp, "data", "spec.jsonl"), "w",
              encoding="utf-8") as fh:
        for r in led:
            fh.write(json.dumps(r) + "\n")
    return os.path.join(tmp, "results")


def _fixture_openvino(tmp):
    """A synthetic campaign whose arms are backends and quantisations.

    Every throughput value below is INVENTED, and it has to be: this repo
    measures no OpenVINO device yet. They are here only so that rows exist to
    refuse, and the refusals under test do not read a single one of them --
    they read the backend, the device and the file name. The NPU arms are
    given near-identical values on purpose, because that is what a ladder
    looks like when the four files decoded as the same Q4_0_128 weights.
    """
    camp = os.path.join(tmp, "results", "synth-openvino")
    os.makedirs(os.path.join(camp, "data"))
    base_prov = {"recorded_by": "scripts/bench/provenance.py",
                 "platform": "Linux-6.14.0-x86_64",
                 "python": "3.12.3",
                 "gpu": {"raw": "NOT RECORDED: FileNotFoundError: nvidia-smi"},
                 "llama_cpp": {"version": "0.1.2-dev", "build": "10679",
                               "commit": "9f2b1c4aa"}}
    npu_exec = {"backend": "openvino", "device": "NPU", "device_asked": "NPU",
                "openvino_version": "2026.3.1",
                "stateful_execution": "NOT SET", "build_tag": "b10679",
                "npu_quant_collapse": "Q4_0_128",
                "warnings": ["On NPU every quantized tensor except the "
                             "embeddings and the output projection becomes "
                             "Q4_0_128, whatever the file was."]}
    files = {
        # Four files, one set of weights: the ladder that must be refused.
        "ov-npu-quant-ladder.json": {
            "model": "/m/Qwen3.8-27B-UD-IQ4_XS.gguf",
            "date": "2026-08-29T09:00:00Z",
            "conditions": "-c 8192 (NPU needs an explicit -c), --parallel 1",
            "provenance": dict(base_prov, execution=npu_exec),
            "arms": [
                {"arm": "npu-iq4xs", "file": "/m/Qwen3.8-27B-UD-IQ4_XS.gguf",
                 "mean_tps": 11.2},
                {"arm": "npu-q4km", "file": "/m/Qwen3.8-27B-Q4_K_M.gguf",
                 "mean_tps": 11.1},
                {"arm": "npu-q6k", "file": "/m/Qwen3.8-27B-Q6_K.gguf",
                 "mean_tps": 11.3},
                {"arm": "npu-q8", "file": "/m/Qwen3.8-27B-Q8_0.gguf",
                 "mean_tps": 11.0}]},
        # One sweep, two backends, two quantisations: refused twice over.
        "ov-vs-cuda-ladder.json": {
            "model": "/m/Qwen3.8-27B-Q4_K_M.gguf",
            "date": "2026-08-29T10:00:00Z",
            "provenance": base_prov,
            "arms": [
                {"arm": "openvino-gpu-q4km",
                 "file": "/m/Qwen3.8-27B-Q4_K_M.gguf", "mean_tps": 9.4,
                 "execution": {"backend": "openvino", "device": "GPU.0",
                               "openvino_version": "2026.3.1"}},
                {"arm": "cuda-q6k", "file": "/m/Qwen3.8-27B-Q6_K.gguf",
                 "mean_tps": 41.8,
                 "execution": {"backend": "cuda",
                               "device": "NVIDIA GeForce RTX 3090",
                               "cuda_arch": "86"}}]},
        # Two quants on an iGPU: not degenerate, but not what the file names
        # promise either, because both arms' Q6_K tensors became Q8_0_C.
        "ov-gpu-quant-ladder.json": {
            "model": "/m/Qwen3.8-27B-Q6_K.gguf",
            "date": "2026-08-29T11:00:00Z",
            "provenance": dict(base_prov, execution={
                "backend": "openvino", "device": "GPU.1",
                "device_asked": "GPU.1", "openvino_version": "2026.3.1"}),
            "arms": [
                {"arm": "gpu-q6k", "file": "/m/Qwen3.8-27B-Q6_K.gguf",
                 "mean_tps": 14.6},
                {"arm": "gpu-q5km", "file": "/m/Qwen3.8-27B-Q5_K_M.gguf",
                 "mean_tps": 15.1}]},
    }
    for fn, doc in files.items():
        with open(os.path.join(camp, "data", fn), "w", encoding="utf-8") as fh:
            json.dump(doc, fh)

    # The silent fallback, in the go-forward shape: the run asked for NPU and
    # the server log said CPU, so the row is a CPU row.
    fallback_exec = {
        "backend": "openvino", "device": "CPU", "device_asked": "NPU",
        "openvino_version": "2026.3.1", "build_tag": "b10679",
        "warnings": ["SILENT FALLBACK: GGML_OPENVINO_DEVICE asked for NPU and "
                     "the backend resolved CPU. Every number from this run is "
                     "a CPU number."]}
    led = [{"kind": "sweep_start", "slug": "synth-openvino",
            "armfile": "ov-device", "provenance": base_prov},
           {"kind": "probe", "armfile": "ov-device", "sweep": "ov-device",
            "arm": "asked-npu", "rep": 1, "pos": 0, "probe": "code",
            "ctx_size": 8192, "ctx_source": "literal",
            "model_path": "/m/Qwen3.8-27B-UD-IQ4_XS.gguf",
            "flags": ["-c", "8192", "--parallel", "1"],
            "ts": "2026-08-29T12:00:00Z",
            "execution": fallback_exec,
            "request": {"temperature": 0.0, "top_k": 1, "top_p": 1.0},
            "timings": {"predicted_per_second": 6.8, "prompt_per_second": 92.0,
                        "prompt_n": 4, "predicted_n": 400}}]
    with open(os.path.join(camp, "data", "ov-device.jsonl"), "w",
              encoding="utf-8") as fh:
        for r in led:
            fh.write(json.dumps(r) + "\n")
    return os.path.join(tmp, "results")


def cmd_selftest(args):
    import tempfile
    import shutil
    tmp = tempfile.mkdtemp(prefix="ledger-selftest-")
    try:
        results = _fixture(tmp)
        rows, sources = build_rows(results, lambda s: None)
        print("\nbuild")
        check("artefacts read", sources, 4)
        check("rows built", len(rows), 31)
        again, _ = build_rows(results, lambda s: None)
        check("build is deterministic",
              [r["row"] for r in rows], [r["row"] for r in again])

        tps = [r for r in rows if r["metric"] == "throughput.decode"
               and r["extractor"] == "arm-sweep/v1"]
        forward = [r for r in tps if "forward" in r["source"]]
        reverse = [r for r in tps if "reverse" in r["source"]]
        nobox = [r for r in tps if "no-provenance" in r["source"]]

        print("\nthe gate")
        ok, _ = gate(forward)
        check("one sweep, one machine, one build -> permitted", ok, True)
        ok, refusals = gate(forward + reverse)
        check("absolutes across two sweeps -> refused", ok, False)
        check("refused BY NAME on the sweep",
              [(r["field"], r["why"]) for r in refusals],
              [("conditions.sweep", "DIFFERS")])
        ok, refusals = gate(forward + nobox)
        check("a row naming no box -> refused on machine and build",
              sorted((r["field"], r["why"]) for r in refusals),
              [("backend", "NOT NAMED"), ("build", "NOT NAMED"),
               ("conditions.sweep", "DIFFERS"), ("device", "NOT NAMED"),
               ("machine", "NOT NAMED")])

        print("\nratios travel where absolutes do not")
        base_f = [r for r in forward if r["conditions"]["arm"] == "A-baseline"][0]
        base_r = [r for r in reverse if r["conditions"]["arm"] == "A-baseline"][0]
        check("the baseline arm moved between sweeps",
              round((base_r["value"] - base_f["value"]) / base_f["value"] * 100, 1),
              -11.7)
        for arm, want_f, want_r in (("B-f16", -8.9, -8.2),
                                    ("C-180k", -3.1, -4.7),
                                    ("E-n4-p0", 8.4, 13.2)):
            f = [r for r in forward if r["conditions"]["arm"] == arm][0]
            v = [r for r in reverse if r["conditions"]["arm"] == arm][0]
            check("%s ratio, forward" % arm,
                  round((f["value"] / base_f["value"] - 1) * 100, 1), want_f)
            check("%s ratio, reverse" % arm,
                  round((v["value"] / base_r["value"] - 1) * 100, 1), want_r)

        print("\nacceptance is not gated on the sweep (rule 30 eliminated the "
              "drafter)")
        acc = [r for r in rows if r["metric"] == "acceptance"
               and r["extractor"] == "arm-sweep/v1"
               and "no-provenance" not in r["source"]]
        ok, refusals = gate([r for r in acc
                             if r["conditions"]["arm"] == "A-baseline"])
        check("acceptance compares across two sweeps", ok, True)

        print("\ncheck")
        blocked = [r for r in rows if check_row(r)[0]]
        check("only the box-less artefact's rows are blocked",
              sorted({os.path.basename(r["source"]) for r in blocked}),
              ["no-provenance.json"])
        thin = {f for r in rows for f in check_row(r)[1]}
        check("every row is thin on the hostname",
              "machine_fields.host" in thin, True)

        print("\narms.py ledger")
        led = [r for r in rows if r["extractor"] == "arms-ledger/v1"]
        check("probe + failed arm produce rows", len(led), 6)
        check("the failed arm is a result, not a silence",
              [r["metric"] for r in led if r["class"] == "load"],
              ["load.failed"])
        check("the sweep rides every line",
              sorted({r["conditions"]["sweep"] for r in led}),
              ["spec:spec-sweep"])

        print("\nthe execution context")
        check("the artefact's execution block names the backend",
              sorted({r["backend"] for r in tps if "no-provenance"
                      not in r["source"]}), ["cuda"])
        check("an NVIDIA card on Linux is NOT derived into a backend",
              derive_backend({"os": "Linux-6.8.0-x86_64",
                              "gpu": "NVIDIA GeForce RTX 3090"})[0], None)
        check("an NVIDIA card on Windows is, and the row says so",
              derive_backend({"os": "Windows-10-10.0.26200-SP0",
                              "gpu": "NVIDIA GeForce RTX 3090"})[0], "cuda")
        check("an OpenVINO device is never derived",
              derive_device("openvino", {"gpu": "Intel Arc A770"})[0], None)

        ov_results = _fixture_openvino(os.path.join(tmp, "ov"))
        ovrows, _ = build_rows(ov_results, lambda s: None)
        by_arm = {}
        for r in ovrows:
            if r["metric"] == "throughput.decode":
                by_arm.setdefault(r["conditions"].get("arm"), []).append(r)
        check("the resolved device beats the variable that asked for it",
              [(r["device"], r["conditions"].get("device_asked"))
               for r in by_arm["asked-npu"]], [("CPU", "NPU")])
        check("the fallback warning travels with the row",
              by_arm["asked-npu"][0]["conditions"]["execution_warning_1"][:16],
              "SILENT FALLBACK:")
        check("an ARM may carry its own backend",
              sorted((a, by_arm[a][0]["backend"], by_arm[a][0]["device"])
                     for a in ("cuda-q6k", "openvino-gpu-q4km")),
              [("cuda-q6k", "cuda", "NVIDIA GeForce RTX 3090"),
               ("openvino-gpu-q4km", "openvino", "GPU.0")])

        print("\nbackend and device are in the comparability key")
        ok, refusals = gate(by_arm["cuda-q6k"] + by_arm["openvino-gpu-q4km"])
        check("a CUDA arm beside an OpenVINO arm -> refused, by name",
              sorted((r["field"], r["why"]) for r in refusals),
              [("backend", "DIFFERS"), ("device", "DIFFERS")])
        ok, _ = gate(by_arm["gpu-q6k"] + by_arm["gpu-q5km"])
        check("two arms on one device -> the backend does not stop them",
              ok, True)
        ok, refusals = gate(by_arm["npu-iq4xs"] + by_arm["asked-npu"])
        check("one file, two OpenVINO devices -> refused on the device",
              [(r["field"], r["why"]) for r in refusals],
              [("device", "DIFFERS"), ("conditions.sweep", "DIFFERS")])

        print("\nthe quant ladder guard")
        npu_rows = [r for a in ("npu-iq4xs", "npu-q4km", "npu-q6k", "npu-q8")
                    for r in by_arm[a]]
        check("four files on NPU -> REFUSED as one arm repeated",
              [(g["kind"], g["severity"]) for g in ladder_guard(npu_rows)],
              [("npu-ladder", "REFUSED")])
        check("the refusal names every arm it refuses",
              sorted(ladder_guard(npu_rows)[0]["arms"]),
              ["IQ4_XS", "Q4_K_M", "Q6_K", "Q8_0"])
        check("ONE quantisation, two devices, is not a ladder",
              ladder_guard(by_arm["npu-iq4xs"] + by_arm["asked-npu"]), [])
        check("an OpenVINO arm beside a CUDA arm -> REFUSED as a ladder too",
              [(g["kind"], g["severity"]) for g in
               ladder_guard(by_arm["cuda-q6k"] + by_arm["openvino-gpu-q4km"])],
              [("mixed-backend-ladder", "REFUSED")])
        check("an all-OpenVINO iGPU ladder is a WARNING, not a refusal",
              [(g["kind"], g["severity"]) for g in
               ladder_guard(by_arm["gpu-q6k"] + by_arm["gpu-q5km"])],
              [("openvino-ladder", "WARNING")])
        check("a ladder with no OpenVINO row is not this guard's business",
              ladder_guard([{"backend": "cuda", "device": "RTX 3090",
                             "model_file": "m-Q4_K_M.gguf", "conditions": {}},
                            {"backend": "cuda", "device": "RTX 3090",
                             "model_file": "m-Q6_K.gguf", "conditions": {}}]),
              [])
        check("quantisations are read out of file names, not guessed",
              [quant_of(n) for n in ("Qwen3.8-27B-UD-IQ4_XS.gguf",
                                     "gemma-4-12B-it-QAT-Q4_0.gguf",
                                     "Qwen3.8-27B-UD-Q2_K_XL.gguf",
                                     "Qwen3.8-27B.gguf")],
              ["IQ4_XS", "Q4_0", "Q2_K_XL", None])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%d passed, %d failed" % (len(PASSED), len(FAILED)))
    return 1 if FAILED else 0


# ---------------------------------------------------------------------------
# cli
# ---------------------------------------------------------------------------

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # `--check` is what the brief calls this mode and what a tired operator
    # types. Accept it as the subcommand it is.
    if argv and argv[0] == "--check":
        argv[0] = "check"

    ap = argparse.ArgumentParser(
        prog="ledger.py", description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="A number without its conditions is unfalsifiable (rule 3), "
               "and absolutes do not travel between sweeps (rule 30). This "
               "tool makes both executable.")
    sub = ap.add_subparsers(dest="cmd")

    b = sub.add_parser("build", help="derive the ledger from results/*/")
    b.add_argument("--results", help="results directory (default: results/)")
    b.add_argument("--out", help="output path (default: %s)" % DEFAULT_OUT)
    b.add_argument("--stdout", action="store_true", help="print, do not write")
    b.add_argument("--force", action="store_true",
                   help="rewrite even when no row changed")
    b.add_argument("--quiet", action="store_true")

    c = sub.add_parser("check", help="rows unfit to enter a comparison")
    c.add_argument("--ledger")
    c.add_argument("--warn-only", action="store_true",
                   help="exit 0 even with blocked rows")
    c.add_argument("--examples", type=int, default=3)

    for name, helptext in (("rows", "list rows"),
                           ("compare", "put rows side by side, or refuse")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--ledger")
        p.add_argument("--metric")
        p.add_argument("--class", dest="klass")
        p.add_argument("--campaign")
        p.add_argument("--model", help="substring of the model file name")
        p.add_argument("--source", help="substring of the source path")
        p.add_argument("--where", action="append", metavar="FIELD=VALUE",
                       help="dotted field, e.g. conditions.ctx=32768; an "
                            "empty value selects rows that do not name it")
        if name == "rows":
            p.add_argument("--limit", type=int, default=40)
            p.add_argument("--columns", type=int, default=5)
            p.add_argument("--json", action="store_true")
        else:
            p.add_argument("--ratio", action="store_true",
                           help="compare RATIOS inside each sweep instead of "
                                "absolutes across them (rule 30)")
            p.add_argument("--baseline",
                           help="arm to divide by, matched as a substring")
            p.add_argument("--column", action="append",
                           help="condition column to show")
            p.add_argument("--assert-same", action="append", metavar="FIELD",
                           help="treat FIELD as equal on evidence the ledger "
                                "does not hold; printed above the result")

    sub.add_parser("selftest", help="fixtures only: no GPU, no model, no net")

    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_help()
        return 0
    return {"build": cmd_build, "check": cmd_check, "rows": cmd_rows,
            "compare": cmd_compare, "selftest": cmd_selftest}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
