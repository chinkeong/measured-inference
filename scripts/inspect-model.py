#!/usr/bin/env python3
"""Read a model's GGUF header and write results/<slug>/model-<label>.json.

    python scripts/inspect-model.py unsloth/Qwen3.8-27B-GGUF --quant UD-Q4_K_M
    python scripts/inspect-model.py LiquidAI/LFM2-1.2B-GGUF --file LFM2-1.2B-Q4_K_M.gguf --json

WHY THIS FILE EXISTS. `scripts/detect-machine.py` measures the MACHINE and
`scripts/lib/paths.py` refuses to default a board size, so no number in this
repository is arithmetic on a remembered card any more. The MODEL half was
never done. It is still one worked example, hardcoded:

  * `scripts/arms/*.json` hold 23 distinct `-c` values from 32,768 to 262,144
    and three logical model names -- two quants and a projector. Every rung is
    a fact about one 27B with a 262,144-token window on a 24 GB card. Carried
    to `unsloth/Qwen3-1.7B-GGUF`, whose header says the window is 40,960, the
    lower half of that ladder is unreachable and the upper half does not exist.
  * `check-request.py` gets KV bytes/token from a `config.json` written for
    transformers, whose vocabulary for "which layers hold a cache" is not the
    GGUF's. On `ibm-granite/granite-4.0-h-tiny-GGUF` -- a repo with no
    config.json of its own, so the base repo's is used -- `layer_types` reads
    `36 x "mamba" + 4 x "attention"`, none of which contains the substring
    "full", and the check prints

        KV bytes/token = 2 x 0 full-attn x 4 kv-heads x 128 head-dim x 2 B = 0
        KV at c=16,384: 0 B = 0 MiB

    on a model whose window is 1,048,576. Zero is not conservative, it is a
    green light for every context. The same file's own header carries
    `granitehybrid.attention.head_count_kv` as a 40-entry per-layer array with
    exactly four non-zero entries -- 8,192 B/token, MEASURED, and 8 GiB at a
    full window.
  * Stage 3 sweeps a drafter whether or not the model has one, Stage 6 assumes
    a projector, Stage 4 assumes an effort knob. The stage files say "if the
    model has..." in PROSE, and prose gates nothing.

Everything those assumptions stand in for is written down in the file itself.
A GGUF keeps its metadata and its COMPLETE tensor table in a header at the
FRONT, so the answers cost a few ranged GETs -- 1 MiB for an mmproj, 4 MiB for
a Granite, 11 MiB against a 16 GB Qwen whose 248,320-token vocabulary is most
of what gets read. Nothing is downloaded. Nothing is executed. No GPU is
touched.

WHAT IT PROMISES.

  * Every field is MEASURED (read out of the header), DERIVED (arithmetic on
    something measured, with the arithmetic printed), CITED (the Hub's own
    listing) or UNKNOWN with a `why`. There is no fifth category and nothing is
    guessed -- rule 1, enforced by `Record` below exactly as
    `detect-machine.py`'s `Profile` enforces it for the machine.
  * A field it cannot establish is written as null WITH its why, never dropped.
    A missing key reads as "not applicable" to whoever finds the artefact
    later, which is how numbers come to look comparable when they are not.
  * ONE artefact per model FILE, not per model. The architecture string belongs
    to the file: this campaign has already met the same weights shipped as
    `GraniteForCausalLM` failing to load while `LlamaForCausalLM` loaded, and a
    per-model record cannot express that.
  * `arch_supported` is answered against THIS build, by
    `scripts/lib/archs.py`, and carries the build tag. When archs.py is absent
    or cannot read the table the answer is `unknown` -- never `false`, because
    a false rejects a model this build loads fine and the campaign re-picks for
    no reason.

THE READ IS BOUNDED. `HeaderReader` refuses to fetch past MAX_HEADER_BYTES and
aborts if the host answers 200 to a ranged GET. A GGUF whose `kv_count` is
corrupt must not turn a header read into a 16 GB download on a machine that is
mid-measurement -- this campaign has already lost one run to exactly that host
load (rule 3's "desktop state travels with the number").

WHAT IT DOES NOT DO. It does not pick quants, size the board, or write
`plan.json`. It reports what the file IS. The fit arithmetic and the stage
gating read this artefact and belong elsewhere.

Stdlib only -- urllib, not requests, for the same reason check-request.py is:
Stage 0 runs before `.venv` is guaranteed to exist. jinja2 is used if it
happens to be importable and skipped, loudly, if it is not.
Python 3.8+. Linux, macOS, Windows.
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
import os
import re
import sys
import textwrap
import urllib.parse

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "lib"))
import paths                                                    # noqa: E402


# ---------------------------------------------------------------------------
# the two scripts this one is built out of
# ---------------------------------------------------------------------------
#
# Both have hyphens in their names, so neither is importable by `import`. They
# are loaded by path rather than copied, because a second GGUF parser and a
# second Hub client are two more things that can disagree with the first pair.
# What comes from where:
#
#   quant-ladder/gguf-inspect.py   Reader (byte source), parse() (the GGUF
#                                  format), GGML (the ggml block-layout table).
#                                  The format parser is NOT reimplemented here.
#   check-request.py               _open() (token on the Hub, token stripped
#                                  across the CDN redirect), find_token(),
#                                  list_tree(), group_gguf(), match_quant(),
#                                  parse_repo(), derive_slug(), and its
#                                  NetworkDown / HttpFail split.
#
# Only two things are re-implemented: HeaderReader._fill (12 lines, so the
# ranged GETs can carry a token, refuse a 200, stop at a byte ceiling and feed
# a running hash) and one 24-line Record class whose original is named below.

def _sibling(relpath, name):
    """Import a hyphenated sibling script by path. SystemExit if it is gone."""
    full = os.path.join(_HERE, relpath)
    if not os.path.isfile(full):
        raise SystemExit(
            "%s is missing.\n%s is built out of it and does not carry a copy: "
            "restore the file or re-clone." % (full, os.path.basename(__file__)))
    spec = importlib.util.spec_from_file_location(name, full)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


gguf = _sibling(os.path.join("quant-ladder", "gguf-inspect.py"), "_gguf_inspect")
hf = _sibling("check-request.py", "_check_request")

# archs.py is another workstream's file and may not exist yet. Its absence is
# reported as UNKNOWN support, which is a supported answer; guessing "true"
# would wave through a `zaya` and guessing "false" would veto a working model.
try:
    import archs                                                # noqa: E402
except Exception as _exc:                                       # pragma: no cover
    archs = None
    ARCHS_WHY = "scripts/lib/archs.py could not be imported (%s: %s)" % (
        type(_exc).__name__, _exc)
else:
    ARCHS_WHY = None

# openvino_quant.py ships with this file, so its absence is a broken clone
# rather than a workstream that has not landed. It is still guarded, and for
# the same reason archs.py is: a traceback here would take out the whole
# inspection, and a missing table is a supported answer -- bpw_effective goes
# null WITH the reason, which is exactly what the field is for.
try:
    import openvino_quant as ovq                              # noqa: E402
except Exception as _exc:                                     # pragma: no cover
    ovq = None
    OVQ_WHY = ("scripts/lib/openvino_quant.py could not be imported (%s: %s), "
               "so no backend's effect on the file's tensor types can be "
               "established" % (type(_exc).__name__, _exc))
else:
    OVQ_WHY = None

SCHEMA = "measured-inference/model.json v1"

# The read ceiling. The largest real header met so far is 11 MiB (a 248,320
# token vocabulary carried in every shard of unsloth/Qwen3.8-27B-GGUF); 64 MiB
# is six times that and still nothing anybody would notice. Past it the header
# is not big, it is wrong, and the correct move is to stop rather than to keep
# ranging into a 50 GB file.
MAX_HEADER_BYTES = 64 << 20

# 1 MiB chunks, matching gguf-inspect. Bigger chunks make fewer round trips and
# fetch more bytes than the header needs; the byte count is the thing being
# minimised here, so the small chunk wins.
CHUNK = 1 << 20

# KV cache element sizes, taken from the ggml block-layout table in
# gguf-inspect.py rather than typed in again. bytes-per-element = bytes-per-
# block / values-per-block, so:
#     f16   type 1   1 value  /  2 B  = 2.0
#     q8_0  type 8   32 values / 34 B = 1.0625   (the fp16 scale is the 0.0625)
#     q4_0  type 2   32 values / 18 B = 0.5625
# The q8_0 figure is not 1.0 and getting it wrong understates a full cache by
# 6.25%: check-request.py carries the same correction and the reference
# campaign's published 34,816 B/token is that 6.25% over 32,768.
CACHE_KINDS = (("f16", 1), ("q8_0", 8), ("q4_0", 2))

# How a drafter announces itself in a filename. MTP (multi-token prediction),
# EAGLE and dflash heads all ship as an ordinary GGUF beside the weights, and
# the only thing separating one from a second quant is its name and its tensor
# count. Matched as a delimited token so `Draft` in a model's own name does not
# make the model its own drafter.
DRAFTER_TOKENS = ("mtp", "eagle", "eagle3", "dflash", "draft", "drafter",
                  "nextn", "medusa", "spec")
DRAFTER_RE = re.compile(r"(?:^|[-._/])(%s)(?:$|[-._/])"
                        % "|".join(DRAFTER_TOKENS), re.IGNORECASE)

# GGUFs in a model repo that are not models. An importance matrix ships as a
# .gguf and lists like one -- unsloth/Qwen3.8-27B-GGUF's imatrix_unsloth.gguf
# is 13 MB of calibration statistics with no architecture and no tensors a
# server would load -- so it must not appear in the roster a campaign picks
# from. Named exactly, never inferred from size: a 1.2B Q4 is smaller than
# some imatrix files.
NOT_A_MODEL = re.compile(r"imatrix|\.imatrix\b", re.IGNORECASE)

# Jinja delimiters, and string literals inside them. A chat template is hunted
# for its knobs by looking at what the template CODE references, never at the
# prose it prints: "keep your thinking brief" is a sentence the model is told,
# not a knob the server can set.
JINJA_BLOCK = re.compile(r"\{\{.*?\}\}|\{%-?.*?-?%\}", re.S)
JINJA_STR = re.compile(r"'[^']*'|\"[^\"]*\"")

# The names a template actually uses for the two knobs llama-server can drive
# through --chat-template-kwargs. Detected as identifiers in template code, not
# as substrings: `\benable_thinking\b` does not fire inside a sentence, and
# `thinking` must not fire inside `enable_thinking`.
EFFORT_MARKERS = ("reasoning_effort", "thinking_budget", "effort")
THINKING_MARKERS = ("enable_thinking", "add_thinking", "thinking")


# ---------------------------------------------------------------------------
# the record
# ---------------------------------------------------------------------------

class Record(object):
    """Values plus a provenance entry for every one of them.

    The four-method API is `detect-machine.py`'s `Profile` (that file, class
    Profile), reproduced rather than imported: importing detect-machine.py
    drags `gpu_lock` and the nvidia-smi plumbing into a script whose entire
    contract is that it touches no GPU. The contract it enforces is the same
    one -- a value cannot be set without a label saying where it came from, so
    rule 1 is structural here instead of remembered.
    """

    def __init__(self):
        self.values = {}
        self.prov = {}

    def measured(self, key, value, how, **extra):
        self.values[key] = value
        self.prov[key] = dict({"how": "MEASURED: " + how}, **extra)

    def derived(self, key, value, how, **extra):
        self.values[key] = value
        self.prov[key] = dict({"how": "DERIVED: " + how}, **extra)

    def cited(self, key, value, how, **extra):
        self.values[key] = value
        self.prov[key] = dict({"how": "CITED: " + how}, **extra)

    def unknown(self, key, why, **extra):
        self.values[key] = None
        self.prov[key] = dict({"how": "UNKNOWN", "why": why}, **extra)

    def note(self, key, **extra):
        if key in self.prov:
            self.prov[key].update(extra)

    def label(self, key):
        return (self.prov.get(key, {}).get("how", "") or "-").split(":")[0]


# ---------------------------------------------------------------------------
# the bounded, authenticated, self-hashing header read
# ---------------------------------------------------------------------------

class HeaderRefused(Exception):
    """The host would not serve a range, or the header ran past the ceiling."""


class HeaderReader(gguf.Reader):
    """gguf-inspect's Reader with a token, a ceiling and a running hash.

    Everything about the GGUF format -- read/u32/u64/string/value, and parse()
    itself -- is inherited unchanged. Only the byte fetch is replaced, for four
    reasons the original had no need of:

      * a gated repo needs `Authorization` on the Hub and must NOT have it on
        the pre-signed CDN host the /resolve redirect lands on. check-request's
        _Redirects handler already strips it; using its _open() is how that
        stays in one place.
      * a host that ignores `Range` answers 200 with the whole body. Reading
        that is a multi-gigabyte download started by a script whose promise is
        that it never downloads. The status is checked BEFORE any read.
      * the first request doubles as the size probe: `Content-Range` names the
        total, so no separate HEAD is spent and the 206 is itself the proof
        that real bytes were served (check-request's ACCESS check, same idea).
      * `sha256_head` has to be the hash of exactly the bytes the parse
        consumed. parse() reads strictly forward from offset 0, so hashing
        inside read() gives sha256(file[0:header_end]) and nothing else.
    """

    def __init__(self, url, token=None, chunk=CHUNK, max_bytes=MAX_HEADER_BYTES):
        self.src = url
        self.remote = True
        self.chunk = chunk
        self.max_bytes = max_bytes
        self.pos, self.buf, self.base = 0, b"", 0
        self.fetched = 0
        self.requests = 0
        self.size = None
        self.final_url = url
        self.token = token
        self.host = urllib.parse.urlsplit(url).hostname
        self.digest = hashlib.sha256()

    def _fill(self, need):
        want = max(need, self.chunk)
        start = self.base + len(self.buf)
        if self.size is not None and start >= self.size:
            raise EOFError("past end of file")
        if start + want > self.max_bytes:
            raise HeaderRefused(
                "the header would run past %d MiB. A GGUF header is metadata "
                "and a tensor table; one this size means the file is not a "
                "GGUF or its counts are corrupt. Refusing to keep ranging "
                "into it." % (self.max_bytes >> 20))
        end = start + want - 1
        if self.size is not None:
            end = min(end, self.size - 1)
        # The token goes to the Hub and nowhere else. Once the first request
        # has resolved to the pre-signed CDN URL the signature is the
        # credential, and _open() would not forward the header across the
        # redirect anyway -- this makes it explicit rather than incidental.
        tok = self.token if (urllib.parse.urlsplit(self.final_url).hostname
                             == self.host) else None
        r = hf._open(self.final_url, tok,
                     {"Range": "bytes=%d-%d" % (start, end)}, timeout=120)
        try:
            status = getattr(r, "status", None) or r.getcode()
            if status != 206:
                raise HeaderRefused(
                    "asked for bytes %d-%d and got HTTP %s, not 206: this host "
                    "does not honour Range, so reading the header would mean "
                    "downloading the whole file. Refusing."
                    % (start, end, status))
            if self.size is None:
                self.size = _total_from_content_range(r.headers)
                self.final_url = r.url
            data = r.read()
        finally:
            r.close()
        if not data:
            raise EOFError("no data at offset %d" % start)
        self.requests += 1
        self.fetched += len(data)
        self.buf += data

    def read(self, n):
        out = gguf.Reader.read(self, n)
        self.digest.update(out)
        return out

    def cost(self):
        return {"bytes_fetched": self.fetched, "requests": self.requests,
                "header_bytes": self.pos, "file_bytes": self.size,
                "sha256_head": self.digest.hexdigest()}


def _total_from_content_range(headers):
    """The file's real size, from `Content-Range: bytes 0-1048575/16464440224`.

    Content-Length on a 206 is the length of the SLICE. Sizing a model from it
    would report every file as 1 MiB.
    """
    cr = headers.get("Content-Range") or ""
    m = re.search(r"/(\d+)\s*$", cr)
    if m:
        return int(m.group(1))
    n = headers.get("x-linked-size") or headers.get("X-Linked-Size")
    if n and str(n).isdigit():
        return int(n)
    return None


def read_header(repo, filename, token):
    """(parsed header, reader) for one file in one repo. Costs its header."""
    url = hf.RESOLVE % (repo, urllib.parse.quote(filename))
    rd = HeaderReader(url, token)
    return gguf.parse(rd), rd


# ---------------------------------------------------------------------------
# the header, read as a model
# ---------------------------------------------------------------------------

def kvget(kv, arch, suffix, default=None):
    """`<arch>.<suffix>`, the way every GGUF namespaces its own hyperparameters."""
    return kv.get("%s.%s" % (arch, suffix), default)


def tensor_totals(tensors):
    """(elements, bytes-implied-by-the-tensor-table, unrecognised type ids).

    Elements is the parameter count, summed from the shapes the file declares.
    That is the difference between a MEASURED bits-per-weight and one divided
    by a parameter count somebody typed in off a model card: `general.name` on
    unsloth/Qwen3.8-27B-GGUF says 27B and the tensor table says 27.006B, and
    only one of those is checkable.
    """
    elems, nbytes, unknown = 0, 0, set()
    for t in tensors:
        e = 1
        for d in t["dims"]:
            e *= d
        info = gguf.GGML.get(t["type"])
        if info is None:
            unknown.add(t["type"])
        else:
            _, bs, bb = info
            nbytes += (e // bs) * bb if bs and bb else 0
        elems += e
    return elems, nbytes, sorted(unknown)


def cache_element_bytes(kind):
    """Bytes per cached value for a KV cache type, from ggml's block layout."""
    for name, tid in CACHE_KINDS:
        if name == kind:
            _, per_block, block_bytes = gguf.GGML[tid]
            return block_bytes / float(per_block)
    raise KeyError(kind)


def attention_shape(kv, arch, rec):
    """head_count, head_count_kv, head_dim, embedding_length -- and their whys.

    head_dim is `<arch>.attention.key_length` when the file states it and
    embedding_length/head_count otherwise. The two are NOT interchangeable and
    the fallback is the wrong answer whenever the model has one: gemma-3-4b
    declares key_length 256 while embedding_length/head_count is 2560/8 = 320,
    a 25% overstatement of every KV figure downstream.
    """
    n_head = kvget(kv, arch, "attention.head_count")
    n_kv = kvget(kv, arch, "attention.head_count_kv", n_head)
    n_embd = kvget(kv, arch, "embedding_length")
    k_len = kvget(kv, arch, "attention.key_length")
    v_len = kvget(kv, arch, "attention.value_length")

    if isinstance(n_head, list):
        rec.measured("head_count", _uniform(n_head),
                     "%s.attention.head_count, a per-layer array" % arch,
                     per_layer=n_head)
    elif isinstance(n_head, int):
        rec.measured("head_count", n_head, "%s.attention.head_count" % arch)
    else:
        rec.unknown("head_count",
                    "%s.attention.head_count is not in the header" % arch)

    if isinstance(n_kv, list):
        nz = sorted(set(x for x in n_kv if x))
        rec.measured("head_count_kv", nz[0] if len(nz) == 1 else None,
                     "%s.attention.head_count_kv, a per-layer array of %d "
                     "(zero on the layers that hold no K/V)" % (arch, len(n_kv)),
                     per_layer=n_kv,
                     why=None if len(nz) == 1 else
                     "the array holds %d different non-zero widths %s; the "
                     "scalar field cannot express that, see kv_arithmetic"
                     % (len(nz), nz))
        if len(nz) != 1:
            rec.values["head_count_kv"] = None
    elif isinstance(n_kv, int):
        rec.measured("head_count_kv", n_kv,
                     "%s.attention.head_count_kv" % arch
                     if kvget(kv, arch, "attention.head_count_kv") is not None
                     else "%s.attention.head_count_kv absent; the file states "
                          "head_count only, so every head carries its own K/V "
                          "(no GQA)" % arch)
    else:
        rec.unknown("head_count_kv",
                    "neither %s.attention.head_count_kv nor .head_count is in "
                    "the header" % arch)

    if isinstance(n_embd, int):
        rec.measured("embedding_length", n_embd, "%s.embedding_length" % arch)
    else:
        rec.unknown("embedding_length",
                    "%s.embedding_length is not in the header" % arch)

    head_dim = None
    if isinstance(k_len, int) and k_len > 0:
        head_dim = k_len
        rec.measured("head_dim", k_len,
                     "%s.attention.key_length" % arch,
                     value_length=v_len,
                     note=None if v_len in (None, k_len) else
                     "value_length is %s, not %s: K and V are different widths "
                     "and the KV arithmetic below adds them separately rather "
                     "than doubling one" % (v_len, k_len))
    else:
        h = rec.values.get("head_count")
        if isinstance(n_embd, int) and isinstance(h, int) and h > 0:
            head_dim = n_embd // h
            rec.derived("head_dim", head_dim,
                        "%s.attention.key_length is absent: "
                        "embedding_length / head_count = %d / %d = %d"
                        % (arch, n_embd, h, head_dim))
        else:
            rec.unknown("head_dim",
                        "no %s.attention.key_length, and embedding_length / "
                        "head_count cannot be formed either" % arch)
    return head_dim, (v_len if isinstance(v_len, int) else head_dim)


def _uniform(seq):
    vals = set(seq)
    return seq[0] if len(vals) == 1 else None


def full_attention_layers(kv, arch, rec):
    """How many layers actually hold a per-token K/V, and how that was decided.

    This is the field that decides whether a window fits, and it is the one a
    hardcoded plan gets most wrong. Four sources, best first:

      1. a per-layer `head_count_kv` ARRAY. Exact, and the only one that is a
         measurement: LiquidAI/LFM2-1.2B says [0,0,8,0,0,8,0,0,8,0,8,0,8,0,8,0]
         -- 6 attention layers of 16 -- and ibm-granite/granite-4.0-h-tiny says
         4 of 40.
      2. `full_attention_interval`. Derived, exact for the models that state
         it: unsloth/Qwen3.8-27B has block_count 65, nextn_predict_layers 1 and
         interval 4, so 64 real layers give 16 full-attention ones, which is
         the count the reference campaign published.
      3. a sliding_window with NO per-layer pattern in the header. gemma3 is
         6:1 global-to-sliding in llama.cpp's code and says nothing about it in
         the file, so the honest answer is every layer counted as full
         attention, marked as an UPPER BOUND. Overstating fails safe against a
         spill and unsafe against the campaign, so it is labelled, loudly,
         rather than quietly corrected with a number from memory.
      4. nothing hybrid in the header at all: a plain transformer, every layer.
    """
    blocks = kvget(kv, arch, "block_count")
    nextn = kvget(kv, arch, "nextn_predict_layers") or 0
    per_layer = kvget(kv, arch, "attention.head_count_kv")
    interval = kvget(kv, arch, "full_attention_interval")
    window = kvget(kv, arch, "attention.sliding_window")
    recurrent = any(k.startswith("%s.ssm." % arch) or
                    k.startswith("%s.shortconv." % arch) or
                    k.startswith("%s.wkv." % arch) for k in kv)

    if isinstance(blocks, int):
        rec.measured("block_count", blocks, "%s.block_count" % arch,
                     nextn_predict_layers=nextn or None)
    else:
        rec.unknown("block_count", "%s.block_count is not in the header" % arch)
        return None, "no block_count", True, {}

    detail = {"block_count": blocks, "nextn_predict_layers": nextn,
              "sliding_window": window, "recurrent_keys": recurrent}

    if isinstance(per_layer, list) and per_layer:
        full = sum(1 for x in per_layer if x)
        detail["per_layer_head_count_kv"] = per_layer
        return full, ("%d of %d layers, counted from the per-layer "
                      "%s.attention.head_count_kv array (the other %d hold no "
                      "K/V cache)" % (full, len(per_layer), arch,
                                      len(per_layer) - full)), False, detail

    body = blocks - nextn if isinstance(nextn, int) else blocks
    if isinstance(interval, int) and interval > 1:
        full = body // interval
        return full, ("%d of %d layers (%s.full_attention_interval %d; "
                      "block_count %d less %d nextn/MTP layer%s, which predict "
                      "and hold no cache for the main model). The other %d are "
                      "linear/gated-delta and carry a FIXED state, counted "
                      "separately below."
                      % (full, body, arch, interval, blocks, nextn,
                         "" if nextn == 1 else "s", body - full)), False, detail

    if isinstance(window, int) and window > 0:
        return body, ("ALL %d layers counted as full attention. The file "
                      "declares %s.attention.sliding_window %d but no "
                      "per-layer pattern, so which layers are global cannot be "
                      "read out of it. This is an UPPER BOUND: the real figure "
                      "is lower by however many layers slide."
                      % (body, arch, window)), True, detail

    if recurrent:
        return body, ("ALL %d layers counted as full attention. The file has "
                      "recurrent/convolution hyperparameters, so some layers "
                      "almost certainly hold a fixed state instead of a cache, "
                      "but neither a per-layer head_count_kv array nor a "
                      "full_attention_interval is present to say which. UPPER "
                      "BOUND." % body), True, detail

    return body, ("all %d layers (plain transformer%s)"
                  % (body, "" if not nextn else
                     "; block_count %d less %d nextn/MTP layer%s"
                     % (blocks, nextn, "" if nextn == 1 else "s"))), False, detail


def kv_arithmetic(kv, arch, rec, head_dim, v_dim):
    """kv_bytes_per_token for f16/q8_0/q4_0, with the arithmetic printed.

    stage-1.md's formula, which check-request.py already implements against
    config.json:

        KV bytes/token = 2 x full-attention layers x n_kv_heads x head_dim
                           x bytes-per-element

    The 2 is K and V. It is written here as (key_length + value_length) so the
    handful of architectures whose K and V are different widths are not
    silently doubled from the wrong one; where they are equal -- which is every
    model this has been run against -- the two forms are the same number.
    """
    full, how, upper, detail = full_attention_layers(kv, arch, rec)
    per_layer = detail.get("per_layer_head_count_kv")
    n_kv = rec.values.get("head_count_kv")

    art = {"formula": None, "full_attention_layers": full,
           "full_attention_layers_how": how, "upper_bound": upper,
           "lines": [], "recurrent_state": None}
    art.update({k: v for k, v in detail.items()
                if k in ("block_count", "nextn_predict_layers",
                         "sliding_window", "per_layer_head_count_kv")})

    if not isinstance(head_dim, int) or not isinstance(full, int):
        rec.unknown("kv_bytes_per_token",
                    "head_dim or the full-attention layer count could not be "
                    "established, so the cache cannot be sized")
        art["recurrent_state"] = recurrent_state(kv, arch, detail, full)
        return art

    # cached values per token = sum over cached layers of kv_heads x (k+v)
    if isinstance(per_layer, list):
        values = sum(x * (head_dim + v_dim) for x in per_layer)
        formula = ("KV values/token = sum over %d layers of "
                   "head_count_kv[i] x (key_length %d + value_length %d) = %d"
                   % (len(per_layer), head_dim, v_dim, values))
    elif isinstance(n_kv, int):
        values = full * n_kv * (head_dim + v_dim)
        formula = ("KV values/token = %d full-attn layers x %d kv-heads x "
                   "(key_length %d + value_length %d) = %d"
                   % (full, n_kv, head_dim, v_dim, values))
    else:
        rec.unknown("kv_bytes_per_token",
                    "head_count_kv is not a single number for this file, so "
                    "the per-layer array in kv_arithmetic is the only correct "
                    "source and it is not present either")
        art["recurrent_state"] = recurrent_state(kv, arch, detail, full)
        return art

    out, lines = {}, [formula]
    for kind, _tid in CACHE_KINDS:
        eb = cache_element_bytes(kind)
        out[kind] = int(round(values * eb))
        lines.append("  %-5s %d values x %s B = %s B/token"
                     % (kind, values, _trim(eb), hf.comma(out[kind])))
    lines.append("  full-attention layers: %s" % how)
    art["formula"] = formula
    art["lines"] = lines
    art["values_per_token"] = values

    how_str = ("stage-1.md's formula: %s, then x bytes-per-element from ggml's "
               "block layout (f16 2, q8_0 34/32, q4_0 18/32)" % formula)
    # `formula` is a key of its own as well as part of `how`: the planner that
    # reads this artefact looks for provenance.kv_bytes_per_token.formula
    # before it falls back to parsing `how`, and a consumer that has to parse a
    # sentence to find the arithmetic will eventually parse it wrong.
    full_formula = "%s; %s" % (formula, " / ".join(lines[1:-1]))
    if upper:
        rec.derived("kv_bytes_per_token", out, how_str, formula=full_formula,
                    upper_bound=True, why_upper_bound=how, lines=lines)
    else:
        rec.derived("kv_bytes_per_token", out, how_str, formula=full_formula,
                    lines=lines)
    art["recurrent_state"] = recurrent_state(kv, arch, detail, full)
    return art


def _trim(x):
    return ("%.4f" % x).rstrip("0").rstrip(".")


def recurrent_state(kv, arch, detail, full):
    """The fixed, context-INDEPENDENT state the non-attention layers hold.

    stage-1.md is explicit that a linear/gated-delta layer's state is a
    constant and must be carried as one rather than folded into a per-token
    figure. It is reported here and deliberately kept OUT of
    kv_bytes_per_token, which is per-token by definition.

    The size is DERIVED from llama.cpp's own shape -- n_embd_r() + n_embd_s(),
    i.e. (d_conv - 1) x (d_inner + 2 x n_group x d_state) + d_state x d_inner
    elements per recurrent layer, at 4 B (f32) -- and it is NOT confirmed
    against this build. check-request.py computes the same quantity from
    config.json with a different grouping and lands 1.25% higher on the
    reference model (158,859,264 B against 156,893,184 B, 152 MiB against 150).
    Two derivations that close to each other are corroboration, not proof:
    both are recorded, neither is presented as measured, and a llama-server
    startup log at Stage 1 settles which allocator shape is right.
    """
    blocks = detail.get("block_count")
    if not isinstance(blocks, int) or not isinstance(full, int):
        return None
    body = blocks - (detail.get("nextn_predict_layers") or 0)
    n_rec = body - full
    if n_rec <= 0:
        return None

    keys = {k.split(".", 1)[1]: v for k, v in kv.items()
            if k.startswith("%s.ssm." % arch)
            or k.startswith("%s.shortconv." % arch)}
    out = {"recurrent_layers": n_rec, "header_keys": keys,
           "bytes_per_sequence": None, "formula": None,
           "why": None, "verified": False}

    l_cache = kvget(kv, arch, "shortconv.l_cache")
    n_embd = kvget(kv, arch, "embedding_length")
    d_conv = kvget(kv, arch, "ssm.conv_kernel")
    d_inner = kvget(kv, arch, "ssm.inner_size")
    d_state = kvget(kv, arch, "ssm.state_size")
    n_group = kvget(kv, arch, "ssm.group_count") or 1

    second_opinion = None
    if isinstance(l_cache, int) and isinstance(n_embd, int):
        elems = n_embd * (l_cache - 1)
        out["formula"] = ("short-conv layer: embedding_length %d x "
                          "(l_cache %d - 1) = %d elements x 4 B (f32)"
                          % (n_embd, l_cache, elems))
    elif all(isinstance(v, int) for v in (d_conv, d_inner, d_state)):
        elems = ((d_conv - 1) * (d_inner + 2 * n_group * d_state)
                 + d_state * d_inner)
        out["formula"] = ("(conv_kernel %d - 1) x (inner_size %d + 2 x "
                          "group_count %d x state_size %d) + state_size %d x "
                          "inner_size %d = %d elements x 4 B (f32)"
                          % (d_conv, d_inner, n_group, d_state, d_state,
                             d_inner, elems))
        second_opinion = ("check-request.py computes the same quantity from "
                          "config.json with a different grouping and lands "
                          "1.25% higher on the reference model (152 MiB "
                          "against 150); the two are recorded rather than "
                          "reconciled by picking one")
    else:
        out["why"] = ("%d layers hold a fixed state this header does not "
                      "describe: NOT counted, so any fit built on "
                      "kv_bytes_per_token alone is optimistic by that much"
                      % n_rec)
        return out

    out["bytes_per_sequence"] = elems * 4 * n_rec
    out["why"] = ("DERIVED from llama.cpp's n_embd_r()+n_embd_s() shape, "
                  "UNVERIFIED against this build -- a llama-server startup log "
                  "at Stage 1 settles it. Context-INDEPENDENT: add it to a fit "
                  "once, never per token."
                  + ("  " + second_opinion if second_opinion else ""))
    return out


# ---------------------------------------------------------------------------
# architecture support, against THIS build
# ---------------------------------------------------------------------------

def install_meta():
    """(what setup.sh/setup.ps1 recorded about this build, or {}, and a why).

    One reader for one file. `build_tag` scopes every architecture-support
    answer to it and `resolve_backend` reads its `flavor`; detect-machine.py
    reads the same key for the machine artefact, so the model record and the
    machine record cannot end up naming two different backends.
    """
    p = os.path.join(paths.repo_root(), "bin", "llama.cpp", "INSTALL.json")
    try:
        with open(p, "r", encoding="utf-8-sig") as fh:
            return (json.load(fh) or {}), None
    except (OSError, ValueError) as exc:
        return {}, ("bin/llama.cpp/INSTALL.json is absent or unreadable (%s: %s)"
                    % (type(exc).__name__, exc))


def build_tag():
    """(tag, where). The build every support answer is scoped to."""
    data, why = install_meta()
    if not data:
        return None, "bin/llama.cpp/INSTALL.json is absent or unreadable"
    bits = [data.get("tag"), data.get("flavor"), data.get("os")]
    return data.get("tag"), "/".join(b for b in bits if b)


def support(kind, name):
    """(true|false|unknown, how, extra) for one arch or projector name.

    Never guesses in either direction. archs.py raises rather than returning an
    empty set precisely so that "I could not read the table" cannot be mistaken
    for "nothing is supported", and that distinction is carried through here.
    """
    if name is None:
        return None, "no name to check", {}
    if archs is None:
        return "unknown", ARCHS_WHY, {}
    try:
        r = archs.roster(kind)
    except Exception as exc:
        return "unknown", ("archs.%s could not be read: %s: %s"
                           % (kind, type(exc).__name__, exc)), {}
    extra = {"roster": r.where(), "roster_count": len(r),
             "build_tag": r.install_tag}
    if name in r:
        return True, ("%r is in %s" % (name, r.where())), extra
    err = None
    try:
        err = archs.load_error(kind, name)
    except Exception:
        pass
    if err:
        extra["load_error"] = err["text"]
        extra["load_error_source"] = "%s +%d" % (os.path.basename(err["source"]),
                                                 err["offset"])
        extra["load_error_note"] = err.get("note")
    return False, ("%r is NOT in %s -- this build cannot load it"
                   % (name, r.where())), extra


# ---------------------------------------------------------------------------
# the backend, and the bits per weight that survive it
# ---------------------------------------------------------------------------
#
# `bpw` above is the file's: file_bytes x 8 / params_total, MEASURED off the
# header, and the right answer to "what did I download". It has also been read
# as the answer to a second question -- how many bits a weight does the RUN
# hold -- and on one backend those are different numbers. The OpenVINO backend
# requantises tensors at load (ggml-openvino-extra.cpp:252-273, read
# 2026-08-29): token_embd.weight and output.weight are rewritten on EVERY
# device, and on NPU every quantized tensor becomes Q4_0_128 whatever the file
# held. Nothing in the run says so -- the four log lines that would are
# commented out, and /props->description carries the OpenVINO version string
# and nothing else -- so this artefact is the only place the discrepancy gets
# recorded, and it is recorded here.
#
# scripts/lib/openvino_quant.py owns the table and the arithmetic. This file
# owns only the decision about WHICH backend the answer is scoped to, and the
# refusal to answer when that is not known.

def resolve_backend(args):
    """(backend, device, how, device_how). Never defaults to anything.

    Order: the operator's --backend, then bin/llama.cpp/INSTALL.json's flavor
    (the file setup.sh and setup.ps1 write, and the same key detect-machine.py
    reads for the machine artefact, so the two records cannot name two
    different backends), then nothing. Nothing is a supported answer and
    produces a null bpw_effective carrying its reason; guessing cuda because
    most of this campaign ran on CUDA would put a number in the artefact that
    describes a machine nobody named.
    """
    if args.backend:
        backend = args.backend.strip().lower()
        how = "--backend %s, stated on the command line" % args.backend
    else:
        meta, why = install_meta()
        flavor = str(meta.get("flavor") or "").lower()
        if flavor:
            backend = flavor
            how = ("bin/llama.cpp/INSTALL.json's flavor, written by the setup "
                   "script that installed this build (tag %s, os %s, host %s)"
                   % (meta.get("tag"), meta.get("os"), meta.get("host")))
        else:
            backend = None
            how = (why or "bin/llama.cpp/INSTALL.json records no flavor, so "
                          "the build in bin/ does not name its backend")

    device, device_how = None, None
    if args.device:
        device = args.device
        device_how = "--device %s, stated on the command line" % args.device
    elif backend == "openvino" and ovq is not None:
        device, device_how = ovq.device_from_env()
    return backend, device, how, device_how


def effective_bits(rec, all_tensors, backend, device, how, device_how):
    """bpw_effective: the bits a weight the RUN holds, or null and the reason.

    Three outcomes, and there is no fourth:

      passthrough backend  bpw_effective IS bpw, by identity rather than by
                           arithmetic -- the kernels consume the file's own
                           block layouts, so there is nothing to recompute.
      openvino             the conversion table applied to every tensor, with
                           the per-role breakdown and the note that the backend
                           does not report any of it.
      backend unknown      null, with the reason. A bpw_effective that quietly
                           equals bpw is the exact failure this field exists to
                           stop, so it is never the fallback.
    """
    if ovq is None:
        rec.unknown("bpw_effective", OVQ_WHY, backend=backend)
        return None
    eff = ovq.backend_effect(backend, device)

    if eff["kind"] == "unknown":
        rec.unknown("bpw_effective", eff["why"], backend=eff.get("backend"),
                    backend_how=how, device_how=device_how,
                    bpw_is_unaffected="bpw above is MEASURED off this file and "
                                      "remains the right answer to what you "
                                      "downloaded")
        return None

    if eff["kind"] == "passthrough":
        bpw = rec.values.get("bpw")
        if bpw is None:
            rec.unknown("bpw_effective",
                        "the %s backend loads the file's own tensor types, so "
                        "bpw_effective would be bpw -- and bpw itself is null: "
                        "%s" % (eff["backend"],
                                rec.prov.get("bpw", {}).get("why", "")),
                        backend=eff["backend"], backend_how=how)
            return None
        rec.derived("bpw_effective", bpw,
                    "bpw_effective = bpw on the %s backend, by identity and not "
                    "by arithmetic: %s. The weights that run are the weights in "
                    "the file." % (eff["backend"], eff["why"]),
                    backend=eff["backend"], backend_how=how,
                    rewrites_tensor_types=False,
                    the_one_backend_that_does=ovq.SOURCE["conversion_table"])
        return None

    # --- openvino: the table, applied -------------------------------------
    # The tensor rows are built HERE, from gguf-inspect's block table, because
    # openvino_quant.py deliberately keeps no second copy of it: it owns the
    # layouts of the types the backend invents and nothing about the GGUF.
    rows, missing = [], 0
    for t in all_tensors:
        e = 1
        for d in t["dims"]:
            e *= d
        info = gguf.GGML.get(t["type"])
        if info is None:
            missing += 1
            name, bs, bb = "TYPE_%d" % t["type"], 0, 0
        else:
            name, bs, bb = info
        rows.append({"name": t["name"], "elements": e,
                     "ne0": t["dims"][0] if t["dims"] else 0,
                     "type": name,
                     "bytes": (e // bs) * bb if (bs and bb) else 0})
    prof = ovq.model_profile(rows, eff["device"], label=rec.values.get("label"))
    if prof.get("bpw_effective") is None:
        rec.unknown("bpw_effective", prof.get("why") or "the profile is empty",
                    backend="openvino", backend_how=how)
        return prof

    by_role = {}
    for k, v in prof["by_role"].items():
        by_role[k] = {
            "tensors": v["tensors"], "elements": v["elements"],
            "bpw_file": round(v["bpw_file"], 4) if v["bpw_file"] else None,
            "bpw_effective": (round(v["bpw_effective"], 4)
                              if v["bpw_effective"] else None),
            "source_types": v["source_types"],
            "effective_types": v["effective_types"],
            "rules_fired": v["rules"]}

    rec.derived("bpw_effective", round(prof["bpw_effective"], 4),
                "the OpenVINO conversion table (%s) applied to all %d tensor "
                "records on device %s, %d of which are rewritten at load: "
                "effective_bytes x 8 / params_total = %d x 8 / %d"
                % (ovq.SOURCE["conversion_table"], prof["tensors"],
                   prof["device"], prof["tensors_rewritten"],
                   prof["effective_bytes"], prof["params_total"]),
                backend="openvino", backend_how=how,
                device=prof["device"],
                device_how=device_how or prof["device_how"],
                rewrites_tensor_types=True,
                basis=prof["basis"],
                bpw_file_tensor_table=round(prof["bpw_file_tensor_table"], 4),
                delta_bpw=round(prof["delta_bpw"], 4),
                bpw_effective_if_f32_scale=round(
                    prof["bpw_effective_if_f32_scale"], 4),
                scale_bits=prof["scale_bits"],
                by_role=by_role,
                conversions=prof["conversions"],
                unrecognised_source_types=prof["unrecognised_source_types"],
                named_tensors=prof["named_tensors"],
                effective_types=prof["effective_types"],
                collapse=prof["collapse"],
                not_reported_by_the_backend=(
                    "the OpenVINO backend prints nothing about any of this. "
                    "The four GGML_LOG_DEBUG lines that would name every "
                    "rewritten tensor are written and COMMENTED OUT at %s; "
                    "/props->description carries only "
                    "ov::get_openvino_version().description (%s). The one "
                    "capturable line is the resolved device at %s -- capture "
                    "it, because a silent NPU to CPU fallback changes which "
                    "rules fired and therefore changes this number."
                    % (ovq.SOURCE["commented_out_logging"],
                       ovq.SOURCE["props_description"],
                       ovq.SOURCE["device_log_line"])),
                ground_truth=ovq.GROUND_TRUTH["how"],
                ground_truth_measured=ovq.MEASURED,
                warnings=prof["warnings"],
                unrecognised_ggml_type_records=missing or None)
    return prof


# ---------------------------------------------------------------------------
# the chat template
# ---------------------------------------------------------------------------

def template_code(text):
    """Only what is INSIDE the Jinja delimiters, with string literals blanked.

    Both halves matter. A template's prose says "Reasoning effort is set to
    low" whether or not any knob exists, and its own string literals name the
    levels rather than reference them. Searching the raw text finds knobs on
    models that have none.
    """
    return "\n".join(JINJA_STR.sub("''", b) for b in JINJA_BLOCK.findall(text))


def template_levels(text):
    """The literal values a template compares an effort variable against."""
    levels = set()
    for block in JINJA_BLOCK.findall(text):
        if not re.search(r"\b\w*effort\w*\b", JINJA_STR.sub("''", block)):
            continue
        for lit in JINJA_STR.findall(block):
            v = lit[1:-1].strip()
            if v and len(v) <= 12 and re.match(r"^[a-z][a-z0-9_-]*$", v):
                levels.add(v)
    return sorted(levels)


def analyse_template(text, rec):
    """{present, sha256, effort_knob, jinja_ok, why} for the tokenizer template."""
    if not text:
        rec.unknown("chat_template",
                    "tokenizer.chat_template is not in the header: the server "
                    "will need --chat-template or --jinja with a file, and no "
                    "effort knob can exist")
        rec.values["chat_template"] = {
            "present": False, "sha256": None, "effort_knob": None,
            "jinja_ok": None,
            "why": "tokenizer.chat_template is not in the header"}
        return None

    code = template_code(text)
    found = {}
    for name in set(EFFORT_MARKERS + THINKING_MARKERS):
        n = len(re.findall(r"\b%s\b" % re.escape(name), code))
        if n:
            found[name] = n

    knob = None
    for name in EFFORT_MARKERS:
        if name in found:
            levels = template_levels(text)
            knob = {"kwarg": name, "kind": "levels", "levels": levels,
                    "references": found[name],
                    "how": ("llama-server --chat-template-kwargs "
                            "'{\"%s\":\"<level>\"}' -- a SERVER flag, not a "
                            "request field: llama-server ignores a per-request "
                            "%s, so each level is its own launch"
                            % (name, name))}
            break
    if knob is None:
        for name in THINKING_MARKERS:
            if name in found:
                knob = {"kwarg": name, "kind": "boolean",
                        "levels": [True, False], "references": found[name],
                        "how": ("llama-server --chat-template-kwargs "
                                "'{\"%s\":false}'. An ON/OFF knob, not a "
                                "graded one: an effort SWEEP has two arms "
                                "here, not four" % name)}
                break

    jinja_ok, why = None, None
    try:
        import jinja2
    except ImportError:
        why = ("jinja2 is not importable and is deliberately not a dependency "
               "of this repository (stdlib + requests): the template was NOT "
               "compile-checked")
    else:
        try:
            jinja2.Environment().from_string(text)
            jinja_ok = True
            why = ("compiled by jinja2 %s. llama.cpp renders with minja, not "
                   "jinja2, so this is corroboration and not proof"
                   % jinja2.__version__)
        except Exception as exc:
            jinja_ok = False
            why = ("jinja2 %s could not compile it: %s: %s. llama.cpp uses "
                   "minja, whose feature set differs, so this is a warning to "
                   "test --jinja at Stage 1 rather than a verdict"
                   % (jinja2.__version__, type(exc).__name__, exc))

    tpl = {"present": True,
           "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
           "chars": len(text),
           "effort_knob": knob,
           "markers_found": found or None,
           "jinja_ok": jinja_ok,
           "why": why}
    rec.measured("chat_template", tpl,
                 "tokenizer.chat_template, %d chars; knobs detected as "
                 "identifiers in template CODE (string literals and prose "
                 "excluded), never as substrings of the whole text" % len(text))
    return knob


# ---------------------------------------------------------------------------
# siblings: the projector and the draft head
# ---------------------------------------------------------------------------

def inspect_sibling(repo, group, token, cost):
    """Read one sibling's header. (kv, error-string)."""
    try:
        hdr, rd = read_header(repo, group["files"][0], token)
    except (hf.NetworkDown, hf.HttpFail, HeaderRefused, ValueError,
            EOFError) as exc:
        return None, "%s: %s" % (type(exc).__name__, exc)
    cost.append({"file": group["files"][0], "bytes": rd.fetched,
                 "requests": rd.requests})
    return hdr["kv"], None


def find_vision(repo, groups, token, rec, cost):
    """The mmproj sibling, its projector type, and whether this build has it."""
    cands = [g for g in groups if g["mmproj"]]
    if not cands:
        rec.unknown("vision",
                    "no mmproj*.gguf in the repo listing: this model has no "
                    "vision projector to load, so the vision stage has nothing "
                    "to measure")
        return
    # More than one is normal (mmproj-F16 / mmproj-BF16 / mmproj-F32). They are
    # precisions of one projector; the smallest is the one a 24 GB board wants
    # and they all declare the same projector_type, which is what gates.
    pick = sorted(cands, key=lambda g: (g["bytes"] or 0, g["name"]))[0]
    kv, err = inspect_sibling(repo, pick, token, cost)
    if kv is None:
        rec.unknown("vision", "mmproj found (%s) but its header could not be "
                              "read: %s" % (pick["name"], err))
        return
    ptype = kv.get("clip.projector_type")
    ok, how, extra = support("projectors", ptype)
    rec.measured("vision",
                 {"mmproj_file": pick["name"],
                  "mmproj_bytes": pick["bytes"],
                  "projector_type": ptype,
                  "supported": ok,
                  "alternatives": [g["name"] for g in cands
                                   if g["name"] != pick["name"]] or None},
                 "clip.projector_type from %s; support %s" % (pick["name"], how),
                 **extra)


def find_drafter(repo, groups, token, rec, cost, main_name, main_arch):
    """A speculative-decoding head shipped beside the weights, or null.

    Rule 11 makes acceptance and mean draft length publishable numbers, and
    Stage 3 sweeps a drafter -- on a model that has none, that whole sweep is
    hours of GPU spent measuring nothing. A draft head is an ordinary GGUF: the
    only things separating it from a second quant are its name and a tensor
    count in the tens rather than the hundreds. Both are checked.
    """
    cands = [g for g in groups
             if not g["mmproj"] and g["name"] != main_name
             and DRAFTER_RE.search("/" + g["name"])]
    if not cands:
        rec.unknown("drafter",
                    "no sibling GGUF whose path carries an MTP/EAGLE/draft "
                    "token: this repo ships no draft head, so speculative "
                    "decoding has nothing to accept from")
        return
    pick = sorted(cands, key=lambda g: (g["bytes"] or 0, g["name"]))[0]
    kv, err = inspect_sibling(repo, pick, token, cost)
    if kv is None:
        rec.unknown("drafter", "a draft head is listed (%s) but its header "
                               "could not be read: %s" % (pick["name"], err))
        return
    arch = kv.get("general.architecture")
    ok, how, extra = support("archs", arch)
    rec.measured("drafter",
                 {"file": pick["name"], "file_bytes": pick["bytes"],
                  "arch": arch, "supported": ok,
                  "same_arch_as_target": (arch == main_arch),
                  "others": [g["name"] for g in cands
                             if g["name"] != pick["name"]] or None},
                 "general.architecture from %s; support %s" % (pick["name"], how),
                 **extra)


# ---------------------------------------------------------------------------
# assembling one file's record
# ---------------------------------------------------------------------------

def quant_label(group, kv, repo, explicit=None):
    """The <label> in model-<label>.json.

    The file's own name minus the model's name -- `general.basename` when the
    header carries one, the repo name otherwise -- so
    Qwen3.8-27B-UD-Q4_K_M.gguf becomes UD-Q4_K_M and the artefact is named the
    way the arms files, the campaign log and the report all name a quant.
    """
    if explicit:
        return re.sub(r"[^A-Za-z0-9._+-]", "_", explicit)
    stem = hf._stem(group["name"])
    base = kv.get("general.basename")
    size = kv.get("general.size_label")
    # The LONGEST prefix that actually matches, not the first one tried.
    # ZAYA1-8B-Q4_K_M.gguf carries general.basename "ZAYA1" and
    # general.size_label "8B": stripping the basename alone leaves "8B-Q4_K_M",
    # a size masquerading as a quant label in every filename downstream.
    cands = [base, ("%s-%s" % (base, size)) if (base and size) else None,
             hf.derive_slug(repo), repo.rstrip("/").split("/")[-1]]
    hits = [c for c in cands
            if c and len(c) < len(stem) and stem.lower().startswith(c.lower())]
    if hits:
        stem = stem[len(max(hits, key=len)):].lstrip("-._")
    return re.sub(r"[^A-Za-z0-9._+-]", "_", stem or hf._stem(group["name"]))


def inspect_file(repo, group, groups, token, args, log):
    """Everything about one model FILE. Returns the record dict."""
    rec = Record()
    cost = []

    hdr, rd = read_header(repo, group["files"][0], token)
    kv, tensors = hdr["kv"], hdr["tensors"]
    cost.append({"file": group["files"][0], "bytes": rd.fetched,
                 "requests": rd.requests})

    # --- the shards -------------------------------------------------------
    # A sharded quant is ONE model. Sizing the first shard alone understates a
    # 27B BF16 by 4.7 GB and its parameter count by 31 tensors; split.count
    # says how many there are and split.tensors.count says how many tensors
    # they hold between them, so both are checked rather than assumed.
    split_n = kv.get("split.count") or 1
    split_tensors = kv.get("split.tensors.count")
    all_tensors = list(tensors)
    shard_bytes = [rd.size]
    if len(group["files"]) > 1:
        for extra_file in group["files"][1:]:
            shdr, srd = read_header(repo, extra_file, token)
            all_tensors.extend(shdr["tensors"])
            shard_bytes.append(srd.size)
            cost.append({"file": extra_file, "bytes": srd.fetched,
                         "requests": srd.requests})
    short = None
    if isinstance(split_n, int) and split_n != len(group["files"]):
        # The file says how many pieces it has. If the listing produced fewer,
        # every total below is a total of an incomplete model, and saying so is
        # the whole difference between a measurement and a plausible number.
        short = ("split.count says %d shards; the repo listing grouped %d (%s)"
                 % (split_n, len(group["files"]), ", ".join(group["files"])))

    arch = kv.get("general.architecture")
    if arch:
        rec.measured("arch", arch, "general.architecture in the GGUF header")
    else:
        rec.unknown("arch", "general.architecture is not in the header; this "
                            "file declares no architecture at all")

    ok, how, extra = support("archs", arch)
    tag, tag_where = build_tag()
    if ok is None:
        rec.unknown("arch_supported", "there is no architecture string to check")
    elif ok == "unknown":
        rec.unknown("arch_supported", how)
    else:
        rec.measured("arch_supported", bool(ok), how, **extra)
    if tag:
        rec.measured("build_tag", tag, "bin/llama.cpp/INSTALL.json (%s)" % tag_where)
    else:
        rec.unknown("build_tag", tag_where)

    # --- the file itself --------------------------------------------------
    rec.cited("repo", repo, "the repo id given on the command line")
    rec.cited("file", group["name"],
              "huggingface.co/api/models/%s/tree/main" % repo,
              shards=group["files"] if len(group["files"]) > 1 else None)
    if group.get("sized"):
        rec.cited("file_bytes", group["bytes"],
                  "the Hub tree listing's size for %s"
                  % ("all %d shards summed" % len(group["files"])
                     if len(group["files"]) > 1 else "this file"),
                  content_range_bytes=sum(b for b in shard_bytes if b),
                  agrees=(group["bytes"] == sum(b for b in shard_bytes if b)))
    else:
        total = sum(b for b in shard_bytes if b)
        rec.measured("file_bytes", total,
                     "Content-Range on the ranged GET (the listing gave no size)")

    rec.measured("sha256_head", rd.digest.hexdigest(),
                 "sha256 of bytes 0..%d of %s -- exactly the header this "
                 "inspection parsed, nothing after the tensor table"
                 % (rd.pos, group["files"][0]))
    oid = (group.get("lfs_oid") or None)
    if oid:
        rec.cited("sha256_file", oid,
                  "the Hub listing's LFS oid: sha256 of the WHOLE file, for "
                  "verifying a download that has not happened yet")
    rec.measured("inspected_utc",
                 datetime.datetime.now(datetime.timezone.utc)
                 .strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "wall clock at the read")

    # --- the parameter count, and the bpw it makes checkable ---------------
    elems, table_bytes, unknown_types = tensor_totals(all_tensors)
    complete = ((not split_tensors) or (len(all_tensors) == split_tensors)) \
        and not short
    if elems and complete:
        rec.measured("params_total", elems,
                     "summed the product of every tensor's dims over all %d "
                     "tensor records in the table%s"
                     % (len(all_tensors),
                        " (%d shards, and split.tensors.count agrees)"
                        % len(group["files"])
                        if len(group["files"]) > 1 else ""))
    elif elems:
        rec.measured("params_total", elems,
                     "summed over %d tensor records" % len(all_tensors),
                     why="INCOMPLETE: %s"
                         % (short or "split.tensors.count says %s and %d were "
                                     "read" % (split_tensors, len(all_tensors))))
    else:
        rec.unknown("params_total", "the tensor table is empty")

    fb = rec.values.get("file_bytes")
    if elems and fb:
        rec.derived("bpw", round(fb * 8.0 / elems, 4),
                    "file_bytes x 8 / params_total = %d x 8 / %d"
                    % (fb, elems),
                    from_tensor_table=(round(table_bytes * 8.0 / elems, 4)
                                       if not unknown_types else None),
                    unknown_ggml_type_ids=unknown_types or None,
                    why=None if not unknown_types else
                    "the tensor-table cross-check is unavailable: ggml type "
                    "ids %s are not in gguf-inspect.py's block table, so its "
                    "bpw would be understated" % unknown_types)
    else:
        rec.unknown("bpw", "needs both file_bytes and params_total")

    # --- and the bits per weight that survive the backend -----------------
    backend, device, b_how, d_how = resolve_backend(args)
    if backend:
        rec.cited("backend", backend, b_how, device=device, device_how=d_how)
    else:
        rec.unknown("backend", b_how)
    effective_bits(rec, all_tensors, backend, device, b_how, d_how)

    # --- the shape --------------------------------------------------------
    ctx = kvget(kv, arch, "context_length") if arch else None
    if isinstance(ctx, int):
        rec.measured("context_length", ctx,
                     "%s.context_length in the header -- the file's own "
                     "trained window, not a model card's claim" % arch,
                     rope_scaling_type=kvget(kv, arch, "rope.scaling.type"),
                     rope_scaling_factor=kvget(kv, arch, "rope.scaling.factor"))
    else:
        rec.unknown("context_length",
                    "%s.context_length is not in the header" % arch)

    head_dim, v_dim = (None, None)
    if arch:
        head_dim, v_dim = attention_shape(kv, arch, rec)
        art = kv_arithmetic(kv, arch, rec, head_dim, v_dim)
    else:
        for k in ("block_count", "head_count", "head_count_kv", "head_dim",
                  "embedding_length", "kv_bytes_per_token"):
            rec.unknown(k, "no general.architecture, so the per-architecture "
                           "hyperparameter keys cannot even be named")
        art = {}

    knob = analyse_template(kv.get("tokenizer.chat_template"), rec)

    # --- siblings ---------------------------------------------------------
    # A projector inspected on its own is its own vision record and has no
    # siblings to look for: a drafter belongs to the weights, not to the mmproj
    # beside them, and reporting the repo's MTP head under a projector's
    # capabilities would gate the speculative stage off the wrong file.
    is_projector = (kv.get("general.type") == "mmproj" or arch == "clip"
                    or "clip.projector_type" in kv)
    if is_projector:
        ptype = kv.get("clip.projector_type")
        ok, how, extra = support("projectors", ptype)
        rec.measured("vision",
                     {"mmproj_file": group["name"],
                      "mmproj_bytes": rec.values.get("file_bytes"),
                      "projector_type": ptype, "supported": ok,
                      "alternatives": None},
                     "clip.projector_type in this file's own header; support "
                     "%s" % how, **extra)
        rec.unknown("drafter",
                    "this file IS the projector: a draft head belongs to the "
                    "weights it drafts for, so inspect the model file to find "
                    "one")
    elif args.no_siblings:
        for k in ("vision", "drafter"):
            rec.unknown(k, "--no-siblings: the repo's other GGUFs were not read")
    else:
        find_vision(repo, groups, token, rec, cost)
        find_drafter(repo, groups, token, rec, cost, group["name"], arch)

    # --- what the stages may gate on --------------------------------------
    caps, why = [], {}
    if is_projector:
        why["text"] = ("general.type is %r: this file is a projector, not a "
                       "text model -- it is loaded with --mmproj beside one"
                       % (kv.get("general.type") or arch))
    else:
        caps.append("text")
    vis = rec.values.get("vision")
    if vis and vis.get("supported") is not False:
        caps.append("vision")
    elif vis:
        why["vision"] = ("projector type %r is not in this build's table, so "
                         "the mmproj cannot be loaded"
                         % vis.get("projector_type"))
    else:
        why["vision"] = rec.prov.get("vision", {}).get("why")
    dr = rec.values.get("drafter")
    if dr and dr.get("supported") is not False:
        caps.append("drafter")
    elif dr:
        why["drafter"] = ("the draft head declares arch %r, which this build "
                          "cannot load" % dr.get("arch"))
    else:
        why["drafter"] = rec.prov.get("drafter", {}).get("why")
    if knob:
        caps.append("effort")
    elif (rec.values.get("chat_template") or {}).get("present"):
        why["effort"] = ("the chat template compiles but references no "
                         "reasoning_effort / enable_thinking / thinking "
                         "variable: there is no level for an effort sweep to "
                         "sweep, and --chat-template-kwargs would be ignored")
    else:
        why["effort"] = (rec.prov.get("chat_template", {}).get("why")
                         or "there is no chat template to carry a knob")
    rec.derived("capabilities", caps,
                "follows from arch/vision/drafter/chat_template above; these "
                "are what gate the stages",
                not_present=why)
    rec.derived("label", quant_label(group, kv, repo, args.label),
                "the file name with the model's own name stripped off it -- "
                "the name the arms files and the campaign log use for a quant")

    return assemble(rec, art, cost)


def assemble(rec, art, cost):
    """The artefact, ordered so a human reads the important part first."""
    order = ("repo", "file", "file_bytes", "sha256_head", "sha256_file",
             "inspected_utc", "build_tag", "backend", "arch", "arch_supported",
             "params_total", "bpw", "bpw_effective",
             "context_length", "block_count",
             "head_count", "head_count_kv", "head_dim", "embedding_length",
             "kv_bytes_per_token", "vision", "drafter", "chat_template",
             "capabilities")
    out = {"_schema": SCHEMA, "label": rec.values.get("label")}
    for k in order:
        if k in rec.values:
            out[k] = rec.values[k]
    for k in sorted(rec.values):
        out.setdefault(k, rec.values[k])
    out["kv_arithmetic"] = art or None
    out["read_cost"] = {
        "bytes_fetched": sum(c["bytes"] for c in cost),
        "http_requests": sum(c["requests"] for c in cost),
        "per_file": cost,
        "note": "ranged GETs against the file headers; nothing was downloaded",
    }
    out["provenance"] = {k: rec.prov[k] for k in order if k in rec.prov}
    for k in sorted(rec.prov):
        out["provenance"].setdefault(k, rec.prov[k])
    try:
        me = os.path.relpath(os.path.abspath(__file__),
                             paths.repo_root()).replace("\\", "/")
    except ValueError:                                          # other drive
        me = os.path.abspath(__file__).replace("\\", "/")
    out["tool_versions"] = {
        "python": "%d.%d.%d" % sys.version_info[:3],
        "inspect_model": me,
        "gguf_reader": "scripts/quant-ladder/gguf-inspect.py",
        "hf_client": "scripts/check-request.py",
        "archs": None if archs is None else "scripts/lib/archs.py",
    }
    return out


# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------

def summarize_effective(rec_dict, prov, w):
    """Why bpw_effective is what it is -- the part a reader has to see.

    When the two figures differ this is the whole finding, and when the field
    is null the REASON is the finding, so neither is truncated to fit a column
    the way the scalar fields above are.
    """
    p = prov.get("bpw_effective") or {}
    if rec_dict.get("bpw_effective") is None:
        for chunk in textwrap.wrap(p.get("why") or "", 74):
            w("      %s\n" % chunk)
        return
    if not p.get("rewrites_tensor_types"):
        w("      the %s backend loads the file's own tensor types: "
          "bpw_effective is bpw, unchanged\n" % p.get("backend"))
        return

    w("      %s on %s REWRITES tensor types at load. Same tensor-table basis, "
      "so\n      the difference is the requantisation and nothing else:\n"
      % (p.get("backend"), p.get("device")))
    w("        file %.4f bpw -> effective %.4f bpw  (%+.4f, and %.4f if the "
      "block scale is f32)\n"
      % (p.get("bpw_file_tensor_table"), rec_dict["bpw_effective"],
         p.get("delta_bpw"), p.get("bpw_effective_if_f32_scale")))
    for role in ("token_embd", "output", "block"):
        b = (p.get("by_role") or {}).get(role)
        if not b:
            continue
        w("        %-11s %6.3f -> %6.3f bpw over %s weights (%d tensor%s)\n"
          % (role, b["bpw_file"] or 0, b["bpw_effective"] or 0,
             hf.comma(b["elements"]), b["tensors"],
             "" if b["tensors"] == 1 else "s"))
    changed = [c for c in (p.get("conversions") or []) if c["changed"]]
    if changed:
        w("      the conversions that fired, by weights:\n")
        for c in changed[:6]:
            w("        rule %s  %-8s -> %-9s %4d tensor%s %18s weights  %s\n"
              % (c["rule_n"], c["source"], c["effective"], c["tensors"],
                 " " if c["tensors"] == 1 else "s",
                 hf.comma(c["elements"]), "/".join(c["roles"])))
        if len(changed) > 6:
            w("        ... and %d more pair%s, all in the artefact\n"
              % (len(changed) - 6, "" if len(changed) - 6 == 1 else "s"))
    for c in changed:
        if c.get("note") and c["source"] in ("Q6_K", "Q5_K") \
                and c["effective"] == "Q8_0_C":
            w("      %s -> Q8_0_C is MORE BITS AT COARSER SCALE GRANULARITY -- "
              "one scale per\n      ROW, not per 256 weights. Not lossless, "
              "and not an upgrade.\n" % c["source"])
            break
    col = p.get("collapse") or {}
    if col.get("degenerate"):
        w("      DEGENERATE: %d distinct quantized types in the body tensors "
          "all become %s.\n"
          % (col["distinct_in"],
             (col.get("effective_types_in_blocks") or ["?"])[0]))
        w("      A quant ladder on this device compares arms that are the same "
          "weights (rule 30).\n")
    for chunk in textwrap.wrap(p.get("not_reported_by_the_backend") or "", 74):
        w("      %s\n" % chunk)
    for warn in p.get("warnings") or []:
        first = True
        for chunk in textwrap.wrap(warn, 71):
            w("      %s %s\n" % ("-" if first else " ", chunk))
            first = False


def summarize(rec_dict, out):
    w = lambda s: out.write(hf.ascii_only(s))
    prov = rec_dict.get("provenance") or {}

    def line(key):
        val = rec_dict.get(key)
        p = prov.get(key) or {}
        label = (p.get("how") or "-").split(":")[0]
        if val is None:
            w("  %-20s null      (%s)\n" % (key, (p.get("why") or "")[:88]))
        else:
            w("  %-20s %-9s %s\n" % (key, label, val))

    for key in ("backend", "arch", "arch_supported", "params_total", "bpw",
                "bpw_effective"):
        line(key)
    summarize_effective(rec_dict, prov, w)
    for key in ("context_length", "block_count", "head_count",
                "head_count_kv", "head_dim", "embedding_length"):
        line(key)

    kvb = rec_dict.get("kv_bytes_per_token")
    art = rec_dict.get("kv_arithmetic") or {}
    if kvb:
        w("  %-20s %-9s %s\n"
          % ("kv_bytes_per_token", "DERIVED",
             "  ".join("%s %s" % (k, hf.comma(v)) for k, v in kvb.items())))
        for line in art.get("lines") or []:
            w("      %s\n" % line)
        ctx = rec_dict.get("context_length")
        if ctx:
            w("      a FULL %s-token window costs %s MiB of f16 KV%s\n"
              % (hf.comma(ctx), hf.comma(int(kvb["f16"] * ctx / 1024 / 1024)),
                 " -- AN UPPER BOUND, see above" if art.get("upper_bound")
                 else ""))
    else:
        w("  %-20s null      (%s)\n"
          % ("kv_bytes_per_token",
             ((prov.get("kv_bytes_per_token") or {}).get("why") or "")[:88]))
    rs = art.get("recurrent_state")
    if rs:
        w("      + %d recurrent layers hold a FIXED state: %s\n"
          % (rs["recurrent_layers"],
             ("%s per sequence, context-independent, DERIVED and unverified"
              % hf.human(rs["bytes_per_sequence"]))
             if rs.get("bytes_per_sequence") else "size not in the header"))

    for key in ("vision", "drafter"):
        val = rec_dict.get(key)
        if val is None:
            w("  %-20s null      (%s)\n"
              % (key, ((prov.get(key) or {}).get("why") or "")[:88]))
        else:
            w("  %-20s MEASURED  %s\n" % (key, json.dumps(val, sort_keys=True)))
    tpl = rec_dict.get("chat_template") or {}
    knob = tpl.get("effort_knob") or {}
    w("  %-20s %-9s present=%s jinja_ok=%s knob=%s\n"
      % ("chat_template", "MEASURED" if tpl.get("present") else "UNKNOWN",
         tpl.get("present"), tpl.get("jinja_ok"),
         ("%s (%s)" % (knob["kwarg"], knob["kind"])) if knob else None))
    if knob.get("levels"):
        w("      an effort sweep on this model has %d arms: %s\n"
          % (len(knob["levels"]), knob["levels"]))
    w("  %-20s %-9s %s\n"
      % ("capabilities", "DERIVED", rec_dict.get("capabilities")))
    for k, v in sorted(((rec_dict.get("provenance") or {})
                        .get("capabilities", {}).get("not_present") or {}).items()):
        if v:
            w("      no %-8s %s\n" % (k, v[:80]))
    cost = rec_dict.get("read_cost") or {}
    w("\n  read %s bytes in %d ranged GET%s across %d file%s -- %s of a "
      "%s byte model\n"
      % (hf.comma(cost.get("bytes_fetched", 0)),
         cost.get("http_requests", 0),
         "" if cost.get("http_requests") == 1 else "s",
         len(cost.get("per_file") or []),
         "" if len(cost.get("per_file") or []) == 1 else "s",
         hf.human(cost.get("bytes_fetched", 0)),
         hf.comma(rec_dict.get("file_bytes") or 0)))


def write_record(rec_dict, slug, label, log):
    """results/<slug>/model-<label>.json, keeping any earlier one."""
    out_dir = os.path.join(paths.repo_root(), "results", slug)
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
        log("created %s" % out_dir)
    path = os.path.join(out_dir, "model-%s.json" % label)
    if os.path.exists(path):
        # Same reason detect-machine.py keeps the previous machine.json: an
        # earlier inspection may have been taken against a different llama.cpp
        # build, and rule 28 says a record that existed cannot be recovered
        # once it is gone.
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        kept = os.path.join(out_dir, "model-%s-%s.json" % (label, stamp))
        os.replace(path, kept)
        log("kept the previous inspection as %s" % os.path.basename(kept))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(rec_dict, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def choose(groups, args):
    """Which model files to inspect. Refuses to pick one for you.

    paths.py refuses to default a board size and _slug_for() refuses to pick
    between two campaigns, for the same reason: picking silently is how a
    number ends up describing something nobody chose. A repo with 27 quants
    gets its list printed and an exit 2, not a guess.
    """
    pool = [g for g in groups if not g["mmproj"] and not NOT_A_MODEL.search(
        os.path.basename(g["name"]))]
    picked, missing = [], []
    # --file reaches every GGUF including an mmproj: naming a file exactly is
    # an explicit intent, and inspecting a projector on its own is a fair thing
    # to want. --quant and the no-argument case see the model files only.
    for name in args.file or []:
        hit = [g for g in groups if name in g["files"] or g["name"] == name]
        (picked.extend(hit) if hit else missing.append(name))
    for label in args.quant or []:
        hit = hf.match_quant(pool, label)
        if len(hit) == 1:
            picked.append(hit[0])
        elif not hit:
            missing.append(label)
        else:
            raise SystemExit(
                "--quant %r is ambiguous, it matches %d files:\n  %s\n"
                "Name one exactly with --file."
                % (label, len(hit), "\n  ".join(g["name"] for g in hit)))
    if missing:
        raise SystemExit(
            "not in the listing: %s\nthe repo offers:\n  %s"
            % (", ".join(repr(m) for m in missing),
               "\n  ".join(hf._stem(g["name"]) for g in pool)))
    if picked:
        seen, out = set(), []
        for g in picked:
            if g["name"] not in seen:
                seen.add(g["name"])
                out.append(g)
        return out
    if len(pool) == 1:
        return pool
    raise SystemExit(
        "%d model files in this repo. Name the one you mean with --quant "
        "<label> or --file <name> (both repeatable):\n  %s"
        % (len(pool), "\n  ".join("%-44s %s" % (hf._stem(g["name"]),
                                                hf.human(g["bytes"]))
                                  for g in pool)))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        epilog="Fields that cannot be established are written as null with a "
               "'why' in provenance -- never guessed, never dropped. Nothing "
               "is downloaded: the read is the file's header.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repo", help="org/repo, or a huggingface.co URL")
    ap.add_argument("--file", action="append",
                    help="exact .gguf filename in the repo (repeatable)")
    ap.add_argument("--quant", action="append",
                    help="quant label, e.g. UD-Q4_K_M (repeatable)")
    ap.add_argument("--label", help="override the <label> in model-<label>.json")
    ap.add_argument("--slug", help="results/<slug>/ to write into "
                                   "(default: the repo name, -GGUF dropped)")
    ap.add_argument("--json", action="store_true",
                    help="print the record and write nothing")
    ap.add_argument("--token", help="HF token for a gated repo")
    ap.add_argument("--no-token", action="store_true",
                    help="ignore $HF_TOKEN and the cached token")
    ap.add_argument("--no-siblings", action="store_true",
                    help="skip the mmproj and draft-head reads")
    ap.add_argument("--backend",
                    help="the backend bpw_effective is scoped to: cuda, "
                         "vulkan, metal, cpu, openvino. Default: whatever "
                         "bin/llama.cpp/INSTALL.json says was installed; with "
                         "neither, bpw_effective is null and says why")
    ap.add_argument("--device",
                    help="OpenVINO device -- CPU, GPU, GPU.0, GPU.1 or NPU "
                         "(the values GGML_OPENVINO_DEVICE takes, and it is "
                         "read when this is not given). On NPU every quantized "
                         "tensor is rewritten to Q4_0_128 at load")
    args = ap.parse_args(argv)

    out = sys.stdout
    log = (lambda s: None) if args.json else (
        lambda s: out.write(hf.ascii_only("  %s\n" % s)))

    repo = hf.parse_repo(args.repo)
    slug = args.slug or os.environ.get(paths.SLUG_ENV) or hf.derive_slug(repo)
    token, where = hf.find_token(args.token, allow_env=not args.no_token)
    if not args.json:
        out.write("\n  %s   %s\n\n" % (repo, hf.token_label(token, where)))

    try:
        entries = hf.list_tree(repo, token)
    except hf.HttpFail as exc:
        raise SystemExit("%s: the Hub answered %s %s%s"
                         % (repo, exc.code, exc.reason,
                            ("  " + exc.message) if exc.message else ""))
    except hf.NetworkDown as exc:
        raise SystemExit("%s: no network (%s). This read needs the Hub; there "
                         "is no offline path to a header that is not on disk."
                         % (repo, exc))
    groups = hf.group_gguf(entries)
    if not groups:
        raise SystemExit("%s lists no .gguf files at all" % repo)
    by_name = {}
    for e in entries:
        oid = (e.get("lfs") or {}).get("oid")
        if oid:
            by_name[e.get("path")] = oid
    for g in groups:
        if len(g["files"]) == 1:
            g["lfs_oid"] = by_name.get(g["files"][0])

    rc = 0
    for group in choose(groups, args):
        try:
            rec_dict = inspect_file(repo, group, groups, token, args, log)
        except hf.HttpFail as exc:
            # The listing answering 200 is not proof of access: a gated repo
            # lists fine and 401s the bytes. That is check-request's ACCESS
            # check, met here at the moment the first range is served.
            out.write(hf.ascii_only(
                "  %s: the Hub answered %s %s%s\n%s\n"
                % (group["name"], exc.code, exc.reason,
                   ("  " + exc.message) if exc.message else "",
                   "  FIX: pass --token, or set $HF_TOKEN, and accept the "
                   "licence on the model page first."
                   if exc.code in (401, 403) else "")))
            rc = max(rc, 1)
            continue
        except hf.NetworkDown as exc:
            out.write(hf.ascii_only("  %s: no network (%s)\n"
                                    % (group["name"], exc)))
            rc = max(rc, 2)
            continue
        except HeaderRefused as exc:
            out.write(hf.ascii_only("  %s: %s\n" % (group["name"], exc)))
            rc = max(rc, 1)
            continue
        except (ValueError, EOFError) as exc:     # not a GGUF / truncated
            out.write(hf.ascii_only(
                "  %s: %s -- the bytes served are not a GGUF header\n"
                % (group["name"], exc)))
            rc = max(rc, 1)
            continue

        label = rec_dict["label"]
        if args.json:
            json.dump(rec_dict, out, indent=2, ensure_ascii=False)
            out.write("\n")
        else:
            out.write(hf.ascii_only("  %s\n  %s\n"
                                    % (group["name"], "-" * 72)))
            summarize(rec_dict, out)
            path = write_record(rec_dict, slug, label, log)
            out.write("\n  -> %s\n\n" % path)

        if rec_dict.get("arch_supported") is False:
            err = ((rec_dict.get("provenance") or {})
                   .get("arch_supported", {}).get("load_error"))
            if not args.json:
                out.write(hf.ascii_only(
                    "  THIS BUILD CANNOT LOAD IT. %s\n  Downloading it costs "
                    "%s and a probe slot for an error at load time.\n\n"
                    % (err or "the architecture is not in LLM_ARCH_NAMES.",
                       hf.human(rec_dict.get("file_bytes") or 0))))
            rc = max(rc, 1)
        elif rec_dict.get("arch_supported") is None:
            rc = max(rc, 2)
    return rc


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
