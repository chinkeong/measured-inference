"""What quant is this file REALLY? Read the GGUF header, local or remote.

    python gguf-inspect.py <path-to.gguf>
    python gguf-inspect.py --hf <repo-id> [--file name.gguf]

WHY THIS EXISTS. A GGUF's filename is a claim, not a measurement. This
campaign's quant ladder is indexed by BITS PER WEIGHT, and a file called
`q2_0` may be nothing of the sort: llama.cpp quantisers routinely keep the
embedding, output and attention tensors at much higher precision than the
name suggests, so two files both called "Q2" can differ by half a bit per
weight and by a great deal of quality. UD-IQ2_S measures 2.481 bpw on this
rig; UD-Q2_K_XL is a different number again. The name settles nothing.

So before a file joins the ladder it gets read: every tensor, its dtype, its
shape, and the arithmetic that turns those into an effective bits-per-weight.

REMOTE MODE. A GGUF stores its metadata and its complete tensor table in a
header at the FRONT of the file, so the answer can be had with an HTTP range
request instead of a multi-gigabyte download. That matters when the machine is
mid-measurement: downloading tens of gigabytes is exactly the host load that
corrupts a speed probe (rule 27), and this campaign has already lost one run
to that. Decide whether a file is worth downloading before downloading it.

FORMAT. Little-endian: magic "GGUF", u32 version, u64 tensor_count,
u64 kv_count, then kv_count key/value pairs, then tensor_count records of
{name, u32 n_dims, u64 dims[n_dims], u32 type, u64 offset}.
"""

import argparse
import json
import os
import struct
import sys
import urllib.request

# ggml type -> (name, block size in elements, bytes per block)
GGML = {
    0: ("F32", 1, 4), 1: ("F16", 1, 2),
    2: ("Q4_0", 32, 18), 3: ("Q4_1", 32, 20),
    6: ("Q5_0", 32, 22), 7: ("Q5_1", 32, 24),
    8: ("Q8_0", 32, 34), 9: ("Q8_1", 32, 40),
    10: ("Q2_K", 256, 84), 11: ("Q3_K", 256, 110), 12: ("Q4_K", 256, 144),
    13: ("Q5_K", 256, 176), 14: ("Q6_K", 256, 210), 15: ("Q8_K", 256, 292),
    16: ("IQ2_XXS", 256, 66), 17: ("IQ2_XS", 256, 74), 18: ("IQ3_XXS", 256, 98),
    19: ("IQ1_S", 256, 50), 20: ("IQ4_NL", 32, 18), 21: ("IQ3_S", 256, 110),
    22: ("IQ2_S", 256, 82), 23: ("IQ4_XS", 256, 136), 24: ("I8", 1, 1),
    25: ("I16", 1, 2), 26: ("I32", 1, 4), 27: ("I64", 1, 8), 28: ("F64", 1, 8),
    29: ("IQ1_M", 256, 56), 30: ("BF16", 1, 2),
    34: ("TQ1_0", 256, 54), 35: ("TQ2_0", 256, 66),
    36: ("MXFP4", 32, 17),
    # Q2_0: 18 bytes per 64 weights = 2.25 bpw exactly. llama-quantize lists it
    # as ftype "41 or Q2_0 : 2.25 bpw quantization (group 64)"; the tensor-type
    # id is 42. Derived independently here from file-size residual arithmetic
    # as 2.2536 bpw before the table was consulted, the excess being header
    # overhead - the two agree, which is why the figure is trusted.
    42: ("Q2_0", 64, 18),
}

# GGUF metadata value types
T_U8, T_I8, T_U16, T_I16, T_U32, T_I32, T_F32, T_BOOL, T_STR, T_ARR, T_U64, \
    T_I64, T_F64 = range(13)
FIXED = {T_U8: ("<B", 1), T_I8: ("<b", 1), T_U16: ("<H", 2), T_I16: ("<h", 2),
         T_U32: ("<I", 4), T_I32: ("<i", 4), T_F32: ("<f", 4),
         T_BOOL: ("<?", 1), T_U64: ("<Q", 8), T_I64: ("<q", 8),
         T_F64: ("<d", 8)}


class Reader(object):
    """Byte source that fetches on demand, so a remote file costs only its header."""

    def __init__(self, src, remote=False, chunk=1 << 20):
        self.src, self.remote, self.chunk = src, remote, chunk
        self.pos, self.buf, self.base = 0, b"", 0
        self.fetched = 0
        self.size = None
        if remote:
            rq = urllib.request.Request(src, method="HEAD")
            with urllib.request.urlopen(rq, timeout=60) as r:
                self.size = int(r.headers.get("Content-Length") or 0)
                self.final_url = r.url
        else:
            self.size = os.path.getsize(src)
            self.fh = open(src, "rb")

    def _fill(self, need):
        want = max(need, self.chunk)
        start = self.base + len(self.buf)
        if self.remote:
            end = min(start + want, self.size) - 1
            if start > end:
                raise EOFError("past end of file")
            rq = urllib.request.Request(self.final_url,
                                        headers={"Range": "bytes=%d-%d" % (start, end)})
            with urllib.request.urlopen(rq, timeout=120) as r:
                data = r.read()
        else:
            self.fh.seek(start)
            data = self.fh.read(want)
        if not data:
            raise EOFError("no data")
        self.fetched += len(data)
        self.buf += data

    def read(self, n):
        while self.pos - self.base + n > len(self.buf):
            self._fill(self.pos - self.base + n - len(self.buf))
        off = self.pos - self.base
        out = self.buf[off:off + n]
        self.pos += n
        if off > (8 << 20):                     # keep the window small
            self.buf = self.buf[off:]
            self.base = self.pos - (len(out))
            self.base = self.pos - len(out)
        return out

    def u32(self):
        return struct.unpack("<I", self.read(4))[0]

    def u64(self):
        return struct.unpack("<Q", self.read(8))[0]

    def string(self):
        n = self.u64()
        return self.read(n).decode("utf-8", "replace")

    def value(self, t):
        if t in FIXED:
            f, n = FIXED[t]
            return struct.unpack(f, self.read(n))[0]
        if t == T_STR:
            return self.string()
        if t == T_ARR:
            et = self.u32()
            n = self.u64()
            if et == T_STR:
                return [self.string() for _ in range(n)]
            if et in FIXED:
                f, w = FIXED[et]
                raw = self.read(n * w)
                return list(struct.unpack("<%d%s" % (n, f[1]), raw))
            raise ValueError("array of type %d" % et)
        raise ValueError("value type %d" % t)


def parse(reader):
    magic = reader.read(4)
    if magic != b"GGUF":
        raise ValueError("not a GGUF file (magic %r)" % magic)
    ver = reader.u32()
    n_tensors = reader.u64()
    n_kv = reader.u64()
    kv = {}
    for _ in range(n_kv):
        k = reader.string()
        t = reader.u32()
        try:
            kv[k] = reader.value(t)
        except ValueError:
            kv[k] = "<unparsed type %d>" % t
    tensors = []
    for _ in range(n_tensors):
        name = reader.string()
        nd = reader.u32()
        dims = [reader.u64() for _ in range(nd)]
        ttype = reader.u32()
        reader.u64()                              # offset
        tensors.append({"name": name, "dims": dims, "type": ttype})
    return {"version": ver, "kv": kv, "tensors": tensors}


def classify(name):
    """Which tensors carry the model's weight, and which are the expensive
    exceptions quantisers routinely keep at high precision."""
    n = name.lower()
    if "token_embd" in n or "tok_embeddings" in n:
        return "embedding"
    if n.startswith("output.") or "output_norm" in n or n == "output.weight":
        return "output"
    if "norm" in n:
        return "norm"
    if "attn" in n:
        return "attention"
    if "ffn" in n or "feed_forward" in n or "mlp" in n:
        return "ffn"
    return "other"


def report(hdr, size_bytes, label):
    ts = hdr["tensors"]
    total_elems, total_bytes = 0, 0
    by_type, by_group = {}, {}
    unknown = set()
    for t in ts:
        e = 1
        for d in t["dims"]:
            e *= d
        info = GGML.get(t["type"])
        if info is None:
            unknown.add(t["type"])
            tn, bs, bb = "TYPE_%d" % t["type"], 1, 0
        else:
            tn, bs, bb = info
        nb = (e // bs) * bb if bs and bb else 0
        total_elems += e
        total_bytes += nb
        a = by_type.setdefault(tn, {"tensors": 0, "elems": 0, "bytes": 0})
        a["tensors"] += 1
        a["elems"] += e
        a["bytes"] += nb
        g = by_group.setdefault(classify(t["name"]),
                                {"elems": 0, "bytes": 0, "types": {}})
        g["elems"] += e
        g["bytes"] += nb
        g["types"][tn] = g["types"].get(tn, 0) + 1

    kv = hdr["kv"]
    arch = kv.get("general.architecture", "?")
    ftype = kv.get("general.file_type", "?")
    name = kv.get("general.name", "?")

    print("=" * 78)
    print("%s" % label)
    print("=" * 78)
    print("  name          : %s" % name)
    print("  architecture  : %s" % arch)
    print("  gguf version  : %s   tensors: %d   kv pairs: %d"
          % (hdr["version"], len(ts), len(kv)))
    print("  general.file_type (the file's OWN label): %s" % ftype)
    if size_bytes:
        print("  file size     : %.2f GiB (%d bytes)"
              % (size_bytes / 1024 ** 3, size_bytes))
    print()
    print("  parameters    : %.3f B (%d elements across all tensors)"
          % (total_elems / 1e9, total_elems))
    if size_bytes:
        bpw_file = size_bytes * 8.0 / total_elems
        print("  BITS PER WEIGHT, from file size : **%.3f bpw**" % bpw_file)
    bpw_t = total_bytes * 8.0 / total_elems if total_elems else 0
    print("  BITS PER WEIGHT, from tensor table: %.3f bpw" % bpw_t)
    print()
    print("  %-10s %8s %14s %12s  %s" % ("dtype", "tensors", "elements",
                                         "bpw", "share of weights"))
    for tn, a in sorted(by_type.items(), key=lambda kvp: -kvp[1]["elems"]):
        bp = a["bytes"] * 8.0 / a["elems"] if a["elems"] else 0
        print("  %-10s %8d %14d %10.2f    %5.1f%%"
              % (tn, a["tensors"], a["elems"], bp, a["elems"] / total_elems * 100))
    print()
    print("  where the bits went, by role:")
    for g, a in sorted(by_group.items(), key=lambda kvp: -kvp[1]["elems"]):
        bp = a["bytes"] * 8.0 / a["elems"] if a["elems"] else 0
        mix = ", ".join("%s x%d" % (k, v) for k, v in
                        sorted(a["types"].items(), key=lambda x: -x[1]))
        print("  %-10s %6.1f%% of weights  %6.2f bpw   %s"
              % (g, a["elems"] / total_elems * 100, bp, mix))
    if unknown:
        print("\n  WARNING: unrecognised ggml type ids %s - bpw from the tensor"
              % sorted(unknown))
        print("  table is understated; trust the file-size figure.")
    return {"name": name, "arch": arch, "file_type": ftype,
            "params": total_elems, "size_bytes": size_bytes,
            "bpw_from_size": (size_bytes * 8.0 / total_elems) if size_bytes else None,
            "bpw_from_tensors": bpw_t,
            "by_type": by_type, "by_group": by_group,
            "kv": {k: v for k, v in kv.items()
                   if not isinstance(v, list) or len(v) < 16}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?")
    ap.add_argument("--hf", help="huggingface repo id")
    ap.add_argument("--file", help="gguf filename inside the repo")
    ap.add_argument("--out", help="write the report as json here")
    a = ap.parse_args()

    if a.hf:
        fn = a.file
        if not fn:
            with urllib.request.urlopen(
                    "https://huggingface.co/api/models/" + a.hf, timeout=60) as r:
                meta = json.loads(r.read().decode())
            cands = [s["rfilename"] for s in meta.get("siblings", [])
                     if s["rfilename"].endswith(".gguf")
                     and "mmproj" not in s["rfilename"].lower()]
            if not cands:
                sys.exit("no non-mmproj .gguf in %s" % a.hf)
            fn = sorted(cands)[0]
        url = "https://huggingface.co/%s/resolve/main/%s" % (a.hf, fn)
        rd = Reader(url, remote=True)
        label = "%s :: %s   (header read remotely)" % (a.hf, fn)
    else:
        if not a.path:
            sys.exit("give a path or --hf")
        rd = Reader(a.path)
        label = a.path
    hdr = parse(rd)
    rep = report(hdr, rd.size, label)
    print("\n  header bytes actually read: %.2f MiB of %.2f GiB"
          % (rd.fetched / 1024 ** 2, (rd.size or 0) / 1024 ** 3))
    if a.out:
        json.dump(rep, open(a.out, "w", encoding="utf-8"), indent=1, default=str)
        print("  -> %s" % a.out)


if __name__ == "__main__":
    main()
