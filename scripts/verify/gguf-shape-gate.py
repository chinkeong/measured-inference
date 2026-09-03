#!/usr/bin/env python3
"""Does a candidate GGUF have the SHAPE the roster's anchor has?

    python scripts/verify/gguf-shape-gate.py --self-test
    python scripts/verify/gguf-shape-gate.py --file models/Some-9B-Q8_0.gguf --profile qwen35-9b
    python scripts/verify/gguf-shape-gate.py --url https://huggingface.co/<repo>/resolve/main/x.gguf --profile qwen35-9b
    python scripts/verify/gguf-shape-gate.py --file a.gguf --reference models/Qwen3.5-9B-MTP-Q8_0.gguf
    python scripts/verify/gguf-shape-gate.py --file models/Qwen3.5-9B-MTP-Q8_0.gguf --write-profile qwen35-9b

WHY THIS EXISTS. Third-party GGUF conversions silently drop the multi-token
prediction layer. The model card does not say so, the filename does not say so,
and the model loads and generates perfectly well without it - it is simply a
different model from the one the roster thinks it is measuring. This repository
has now been bitten three times:

  2026-08  ornith-1.5-9b-mtp Stage 0 - lmstudio-community's Q8_0 at 9.53 GB
           against unsloth's at 9.79 GB. Caught by SIZE, before download.
  2026-09  qwen35-9b-family roster - the same two sizes, the same lineage,
           caught the same way and recorded as "the first trap".
  2026-09  Jackrong/Qwopus3.5-9B-v3-GGUF - block_count 32, nextn_predict_layers
           absent, 427 tensors against the anchor's 442, the 15 missing being
           exactly all of blk.32. Its OWN config.json declares
           mtp_num_hidden_layers: 1 against num_hidden_layers: 32, so the
           upstream weights have the layer and the conversion lost it.

Twice the file size caught it. Size is a good first filter and it is NOT a gate:
it is a single scalar standing in for a tensor manifest, it moves with quant
mix, and a re-quantised file with the layer restored can land on either number.
The gate is the HEADER. A GGUF's key-value block and tensor directory sit in the
first few megabytes, so this check costs a ranged read - no download, no card,
no weights.

WHAT IT ASSERTS, and why each one is here rather than implied by the others:

  general.architecture        the coarse gate; wrong arch, nothing else matters
  <arch>.block_count          the headline symptom - 33 vs 32
  <arch>.nextn_predict_layers absent entirely on a dropped-MTP file, and it is
                              the only key that names the feature by intent
  tensor_count                catches a drop that left the count key intact
  blk.<last>.nextn.eh_proj.weight
                              the layer's own weight, by name. block_count is a
                              CLAIM in the KV block; this is the tensor actually
                              being there. A converter that writes 33 and emits
                              32 blocks passes every check above and fails this
  context_length, embedding_length, head_count, head_count_kv,
  key_length, value_length    the TIER 1 fields: KV arithmetic, the fit table
                              and the roofline are properties of the shape, so
                              a roster that shares them measures them ONCE

With --reference, it additionally diffs the FULL tensor manifest - every name,
every shape, every per-tensor quant type. That is the strongest form: the
DeepSeek-V4-Pro distill passed it with zero differences against the anchor, and
a plain Q8_0 vs an Unsloth-Dynamic Q8_K_XL would fail it on per-tensor types
while passing every scalar field above.

WHAT IT DOES NOT DO. It says nothing about whether the model is any GOOD, and
nothing about TIER 2 conditions - chat template, BOS handling, sampler defaults
- which differ legitimately between arms and travel with the number instead
(rule 3). A pass here means "this file may enter the roster", not "this file is
comparable in every respect".

EXIT CODES
  0 pass . 1 fail (a real shape mismatch) . 2 usage . 4 could not read the file

No GPU, no weights and no network in --self-test, which is the mode run-all.py
runs: the fixtures are GGUF headers built byte by byte in memory.
"""

import argparse
import hashlib
import json
import os
import struct
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PROFILES = os.path.join(HERE, "gguf-profiles.json")

MAGIC = b"GGUF"
HEAD_BYTES = 12 << 20  # 12 MiB: comfortably past the tensor directory of a 9B

(T_U8, T_I8, T_U16, T_I16, T_U32, T_I32, T_F32, T_BOOL, T_STR, T_ARR, T_U64,
 T_I64, T_F64) = range(13)

_FIXED = {
    T_U8: ("<B", 1), T_I8: ("<b", 1), T_U16: ("<H", 2), T_I16: ("<h", 2),
    T_U32: ("<I", 4), T_I32: ("<i", 4), T_F32: ("<f", 4), T_U64: ("<Q", 8),
    T_I64: ("<q", 8), T_F64: ("<d", 8),
}

# The scalar fields a roster shares. Suffixes are appended to the architecture
# name found in the file, because a GGUF namespaces them under it.
SHAPE_KEYS = (
    "block_count",
    "context_length",
    "embedding_length",
    "attention.head_count",
    "attention.head_count_kv",
    "attention.key_length",
    "attention.value_length",
    "nextn_predict_layers",
)


class GGUFError(Exception):
    """The bytes are not a GGUF this script can read."""


class _Reader:
    def __init__(self, buf):
        self.b = buf
        self.o = 0

    def raw(self, n):
        if n < 0 or self.o + n > len(self.b):
            raise GGUFError(
                "header runs past the %d bytes read - re-read with a larger "
                "--head-bytes" % len(self.b))
        v = self.b[self.o:self.o + n]
        self.o += n
        return v

    def u32(self):
        return struct.unpack("<I", self.raw(4))[0]

    def u64(self):
        return struct.unpack("<Q", self.raw(8))[0]

    def string(self):
        n = self.u64()
        if n > (1 << 26):
            raise GGUFError("implausible string length %d - not a GGUF" % n)
        return self.raw(n).decode("utf-8", "replace")

    def value(self, t):
        if t in _FIXED:
            fmt, size = _FIXED[t]
            return struct.unpack(fmt, self.raw(size))[0]
        if t == T_BOOL:
            return bool(self.raw(1)[0])
        if t == T_STR:
            return self.string()
        if t == T_ARR:
            et = self.u32()
            n = self.u64()
            if n > (1 << 28):
                raise GGUFError("implausible array length %d" % n)
            return [self.value(et) for _ in range(n)]
        raise GGUFError("unknown GGUF value type %d" % t)


def parse_header(buf):
    """KV block + tensor directory from the head of a GGUF. Never the weights."""
    r = _Reader(buf)
    if r.raw(4) != MAGIC:
        raise GGUFError("no GGUF magic - this is not a GGUF file")
    version = r.u32()
    n_tensors = r.u64()
    n_kv = r.u64()
    if n_kv > 100000 or n_tensors > 1000000:
        raise GGUFError("implausible counts (kv=%d tensors=%d)" % (n_kv, n_tensors))

    kv = {}
    for _ in range(n_kv):
        k = r.string()
        kv[k] = r.value(r.u32())

    tensors = []
    truncated = False
    try:
        for _ in range(n_tensors):
            name = r.string()
            nd = r.u32()
            if nd > 8:
                raise GGUFError("tensor %r claims %d dimensions" % (name, nd))
            dims = [r.u64() for _ in range(nd)]
            ttype = r.u32()
            r.u64()  # offset, unused: we never touch the tensor data
            tensors.append((name, tuple(dims), ttype))
    except GGUFError:
        truncated = True

    return {
        "version": version,
        "tensor_count_declared": n_tensors,
        "kv_count": n_kv,
        "kv": kv,
        "tensors": tensors,
        "tensor_directory_truncated": truncated,
    }


def describe(hdr):
    """The comparable facts, flattened. This is what a profile stores."""
    kv = hdr["kv"]
    arch = kv.get("general.architecture")
    if not arch:
        raise GGUFError("no general.architecture in the KV block")

    shape = {"general.architecture": arch}
    for suffix in SHAPE_KEYS:
        shape["%s.%s" % (arch, suffix)] = kv.get("%s.%s" % (arch, suffix))

    names = [t[0] for t in hdr["tensors"]]
    blocks = set()
    for n in names:
        if n.startswith("blk."):
            part = n.split(".", 2)
            if len(part) > 1 and part[1].isdigit():
                blocks.add(int(part[1]))
    last = max(blocks) if blocks else None

    params = 0
    for _, dims, _t in hdr["tensors"]:
        p = 1
        for d in dims:
            p *= d
        params += p

    return {
        "shape": shape,
        "tensor_count": hdr["tensor_count_declared"],
        "tensor_count_parsed": len(names),
        "tensor_directory_truncated": hdr["tensor_directory_truncated"],
        "last_block": last,
        "mtp_tensor": ("blk.%d.nextn.eh_proj.weight" % last) in names if last is not None else False,
        "nextn_tensor_names": sorted(n for n in names if "nextn" in n),
        "total_params": params,
        "manifest": sorted((n, list(d), t) for n, d, t in hdr["tensors"]),
    }


def check(cand, ref, compare_manifest):
    """Return a list of failure strings. Empty means pass."""
    bad = []

    if cand["tensor_directory_truncated"]:
        bad.append("tensor directory was cut off before the end - read more bytes")

    for key, want in ref["shape"].items():
        got = cand["shape"].get(key)
        if got != want:
            bad.append("%s: expected %r, file has %r" % (key, want, got))

    if cand["tensor_count"] != ref["tensor_count"]:
        bad.append("tensor_count: expected %d, file has %d (%+d)"
                   % (ref["tensor_count"], cand["tensor_count"],
                      cand["tensor_count"] - ref["tensor_count"]))

    if ref.get("mtp_tensor") and not cand.get("mtp_tensor"):
        bad.append("blk.%s.nextn.eh_proj.weight is ABSENT - the MTP layer was "
                   "dropped by the conversion, whatever block_count claims"
                   % cand.get("last_block"))

    if ref.get("total_params") and cand.get("total_params") != ref["total_params"]:
        bad.append("total params: expected %d, file has %d (%+d)"
                   % (ref["total_params"], cand["total_params"],
                      cand["total_params"] - ref["total_params"]))

    if compare_manifest and "manifest" in ref:
        cm = {(n, tuple(d)): t for n, d, t in cand["manifest"]}
        rm = {(n, tuple(d)): t for n, d, t in ref["manifest"]}
        missing = sorted(set(rm) - set(cm))
        extra = sorted(set(cm) - set(rm))
        retyped = sorted(k for k in set(cm) & set(rm) if cm[k] != rm[k])
        for n, d in missing[:12]:
            bad.append("tensor MISSING: %s %s" % (n, list(d)))
        if len(missing) > 12:
            bad.append("... and %d more missing tensors" % (len(missing) - 12))
        for n, d in extra[:12]:
            bad.append("tensor UNEXPECTED: %s %s" % (n, list(d)))
        if len(extra) > 12:
            bad.append("... and %d more unexpected tensors" % (len(extra) - 12))
        for n, d in retyped[:12]:
            bad.append("tensor QUANT DIFFERS: %s %s ref=%d file=%d"
                       % (n, list(d), rm[(n, d)], cm[(n, d)]))
        if len(retyped) > 12:
            bad.append("... and %d more retyped tensors" % (len(retyped) - 12))

    return bad


def read_local(path, head_bytes):
    try:
        with open(path, "rb") as fh:
            return fh.read(head_bytes)
    except OSError as e:
        print("cannot read %s: %s" % (path, e), file=sys.stderr)
        sys.exit(4)


def read_ranged(url, head_bytes):
    req = urllib.request.Request(url, headers={"Range": "bytes=0-%d" % (head_bytes - 1)})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            if resp.status not in (200, 206):
                print("HTTP %s for %s" % (resp.status, url), file=sys.stderr)
                sys.exit(4)
            if resp.status == 200:
                print("NOTE: server ignored Range and is sending the whole file; "
                      "reading only the first %d bytes." % head_bytes, file=sys.stderr)
            return resp.read(head_bytes)
    except Exception as e:  # noqa: BLE001 - any transport failure is exit 4
        print("cannot fetch %s: %s" % (url, e), file=sys.stderr)
        sys.exit(4)


# ----------------------------------------------------------------- self-test

def _s(text):
    b = text.encode()
    return struct.pack("<Q", len(b)) + b


def _kv(key, vtype, value):
    out = _s(key) + struct.pack("<I", vtype)
    if vtype == T_STR:
        return out + _s(value)
    if vtype == T_U32:
        return out + struct.pack("<I", value)
    raise AssertionError("fixture only needs str/u32")


def _tensor(name, dims, ttype, offset=0):
    out = _s(name) + struct.pack("<I", len(dims))
    for d in dims:
        out += struct.pack("<Q", d)
    return out + struct.pack("<I", ttype) + struct.pack("<Q", offset)


def build_fixture(blocks, with_mtp, arch="qwen35", claim_blocks=None,
                  head_dim=256, bad_magic=False, truncate=None):
    """A minimal but REAL GGUF header. Fixtures, not mocks: the same parser
    that reads a 9 GB file off HuggingFace reads these bytes."""
    kvs = [
        _kv("general.architecture", T_STR, arch),
        _kv("%s.block_count" % arch, T_U32, claim_blocks if claim_blocks is not None else blocks),
        _kv("%s.context_length" % arch, T_U32, 262144),
        _kv("%s.embedding_length" % arch, T_U32, 4096),
        _kv("%s.attention.head_count" % arch, T_U32, 16),
        _kv("%s.attention.head_count_kv" % arch, T_U32, 4),
        _kv("%s.attention.key_length" % arch, T_U32, head_dim),
        _kv("%s.attention.value_length" % arch, T_U32, head_dim),
    ]
    if with_mtp:
        kvs.append(_kv("%s.nextn_predict_layers" % arch, T_U32, 1))

    tensors = [_tensor("token_embd.weight", (4096, 248320), 8)]
    for i in range(blocks):
        tensors.append(_tensor("blk.%d.attn_q.weight" % i, (4096, 4096), 8))
        tensors.append(_tensor("blk.%d.ffn_up.weight" % i, (4096, 12288), 8))
        if with_mtp and i == blocks - 1:
            tensors.append(_tensor("blk.%d.nextn.eh_proj.weight" % i, (8192, 4096), 8))
            tensors.append(_tensor("blk.%d.nextn.enorm.weight" % i, (4096,), 0))

    body = b"".join(kvs) + b"".join(tensors)
    head = (b"XXXX" if bad_magic else MAGIC) + struct.pack("<I", 3) \
        + struct.pack("<Q", len(tensors)) + struct.pack("<Q", len(kvs))
    blob = head + body
    return blob[:truncate] if truncate else blob


def self_test():
    cases = []

    def case(name, ok, detail=""):
        cases.append((name, ok, detail))

    anchor = describe(parse_header(build_fixture(33, True)))

    # 1. identical file passes, manifest diff included
    same = describe(parse_header(build_fixture(33, True)))
    bad = check(same, anchor, True)
    case("identical 33-block MTP file passes", not bad, "; ".join(bad))

    # 2. the real trap: MTP dropped, block_count honestly 32
    dropped = describe(parse_header(build_fixture(32, False)))
    bad = check(dropped, anchor, True)
    case("32-block MTP-dropped file fails", bool(bad))
    case("  ...and names block_count",
         any("block_count" in b for b in bad))
    case("  ...and names nextn_predict_layers",
         any("nextn_predict_layers" in b for b in bad))
    case("  ...and names tensor_count",
         any("tensor_count" in b for b in bad))

    # 3. the subtle one: KV block CLAIMS 33, tensors say otherwise. Every
    #    scalar check passes; only the tensor-name assertion catches it.
    liar = describe(parse_header(build_fixture(32, False, claim_blocks=33)))
    bad = check(liar, anchor, False)
    case("file claiming block_count 33 with 32 blocks still fails", bool(bad))
    case("  ...via the eh_proj tensor assertion",
         any("eh_proj" in b for b in bad))

    # 4. wrong architecture
    bad = check(describe(parse_header(build_fixture(33, True, arch="llama"))), anchor, False)
    case("wrong architecture fails", any("architecture" in b for b in bad))

    # 5. right blocks, wrong head_dim - a TIER 1 shape field
    bad = check(describe(parse_header(build_fixture(33, True, head_dim=128))), anchor, False)
    case("wrong head_dim fails", any("key_length" in b for b in bad))

    # 6. corrupt input is an error, not a traceback
    try:
        parse_header(build_fixture(33, True, bad_magic=True))
        case("non-GGUF bytes rejected", False, "no GGUFError raised")
    except GGUFError:
        case("non-GGUF bytes rejected", True)

    # 7. a header cut short is reported, not silently short-read
    cut = describe(parse_header(build_fixture(33, True, truncate=400)))
    case("truncated tensor directory is flagged", cut["tensor_directory_truncated"])
    case("  ...and fails the gate",
         any("cut off" in b for b in check(cut, anchor, False)))

    width = max(len(n) for n, _, _ in cases)
    failed = 0
    for name, ok, *rest in cases:
        detail = rest[0] if rest and rest[0] else ""
        print("  %-*s %s%s" % (width, name, "ok" if ok else "FAIL",
                               ("  " + detail) if detail and not ok else ""))
        failed += 0 if ok else 1
    print("\n%d passed, %d failed" % (len(cases) - failed, failed))
    return 1 if failed else 0


# ---------------------------------------------------------------------- main

def load_profiles():
    if not os.path.exists(PROFILES):
        return {}
    with open(PROFILES) as fh:
        return json.load(fh)


def main():
    ap = argparse.ArgumentParser(
        description="Assert a GGUF has the roster anchor's shape.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", help="local GGUF to check")
    ap.add_argument("--url", help="remote GGUF to check by ranged read")
    ap.add_argument("--reference", help="local GGUF or URL to compare against")
    ap.add_argument("--profile", help="named profile from gguf-profiles.json")
    ap.add_argument("--write-profile", metavar="NAME",
                    help="record --file as NAME in gguf-profiles.json")
    ap.add_argument("--list-profiles", action="store_true")
    ap.add_argument("--head-bytes", type=int, default=HEAD_BYTES)
    ap.add_argument("--no-manifest", action="store_true",
                    help="skip the per-tensor manifest diff (--reference only)")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()

    if a.self_test:
        return self_test()

    profiles = load_profiles()

    if a.list_profiles:
        if not profiles:
            print("no profiles recorded yet (%s)" % PROFILES)
        for name, p in sorted(profiles.items()):
            print("%-16s %s  block_count=%s tensors=%s"
                  % (name, p["shape"].get("general.architecture"),
                     next((v for k, v in p["shape"].items() if k.endswith(".block_count")), "?"),
                     p.get("tensor_count")))
        return 0

    if not (a.file or a.url):
        ap.error("give --file or --url (or --self-test)")

    src = a.file or a.url
    buf = read_local(a.file, a.head_bytes) if a.file else read_ranged(a.url, a.head_bytes)
    try:
        cand = describe(parse_header(buf))
    except GGUFError as e:
        print("FAIL  %s\n      %s" % (src, e))
        return 1

    if a.write_profile:
        profiles[a.write_profile] = cand
        with open(PROFILES, "w") as fh:
            json.dump(profiles, fh, indent=1, sort_keys=True)
            fh.write("\n")
        print("recorded profile %r from %s" % (a.write_profile, src))
        print("  tensors=%d params=%d sha256(manifest)=%s"
              % (cand["tensor_count"], cand["total_params"],
                 hashlib.sha256(json.dumps(cand["manifest"]).encode()).hexdigest()[:16]))
        return 0

    compare_manifest = False
    if a.reference:
        rbuf = (read_ranged(a.reference, a.head_bytes)
                if a.reference.startswith(("http://", "https://"))
                else read_local(a.reference, a.head_bytes))
        ref = describe(parse_header(rbuf))
        ref_label = a.reference
        compare_manifest = not a.no_manifest
    elif a.profile:
        if a.profile not in profiles:
            print("no such profile %r; have: %s"
                  % (a.profile, ", ".join(sorted(profiles)) or "(none)"), file=sys.stderr)
            return 2
        ref = profiles[a.profile]
        ref_label = "profile %r" % a.profile
        compare_manifest = "manifest" in ref and not a.no_manifest
    else:
        ap.error("give --reference or --profile to check against")

    bad = check(cand, ref, compare_manifest)

    print("candidate : %s" % src)
    print("reference : %s" % ref_label)
    print("  arch=%s block_count=%s nextn=%s tensors=%d params=%d mtp_tensor=%s"
          % (cand["shape"].get("general.architecture"),
             next((v for k, v in cand["shape"].items() if k.endswith(".block_count")), "?"),
             next((v for k, v in cand["shape"].items() if k.endswith(".nextn_predict_layers")), None),
             cand["tensor_count"], cand["total_params"], cand["mtp_tensor"]))

    if not bad:
        print("\nPASS - shape matches%s." % (" including every tensor" if compare_manifest else ""))
        return 0
    print("\nFAIL - %d mismatch%s:" % (len(bad), "" if len(bad) == 1 else "es"))
    for b in bad:
        print("  - %s" % b)
    return 1


if __name__ == "__main__":
    sys.exit(main())
