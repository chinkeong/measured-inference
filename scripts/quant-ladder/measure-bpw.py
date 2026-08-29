#!/usr/bin/env python3
"""Bits per weight, MEASURED: the denominator comes from the file, not a manifest.

    python scripts/quant-ladder/measure-bpw.py <file.gguf>
    python scripts/quant-ladder/measure-bpw.py <file.gguf> --json
    python scripts/quant-ladder/measure-bpw.py <file.gguf> --declared 27000000000
    python scripts/quant-ladder/measure-bpw.py --hf <repo-id> [--file name.gguf]
    python scripts/quant-ladder/measure-bpw.py --audit-manifest [<manifest.json>]

WHY THIS FILE EXISTS. The quant ladder publishes a column headed "Bits per
weight (measured)". Until this file existed the number behind it was

    bpw = file_bytes * 8 / <a parameter count typed into ladder-manifest.json>

and the typed count was the model's MARKETING size - 27000000000 for a file
whose own tensor table sums to 27,320,697,856 elements. A round number nobody
counted is not a measurement, so a column headed "measured" was carrying a
derived number: rule 1 allows measured, cited or labeled-derived, and there is
no fourth category. The declared denominator is 1.17% small, which pushes every
bpw on the ladder 1.19% high - larger than the gaps the ladder is asked to
resolve between adjacent rungs, and in the direction that flatters the file.

WHAT IT MEASURES. Two independent cheap metrics, rule 4, from the same ranged
read of the header:

    bpw_from_size    = file_bytes * 8 / sum(tensor elements)
    bpw_from_tensors = sum(bytes implied by each tensor's dtype and shape)
                       * 8 / sum(tensor elements)

The first is the number a reader cares about - what a byte on disk buys. The
second knows nothing about the file's length; it is arithmetic over the tensor
table alone. They agree to within the header's own overhead (a few thousandths
of a bit), and when they DISAGREE the file is not what its table says it is:
an unrecognised ggml type id, a split file, or trailing data. So the agreement
is reported as a number, and a disagreement is said out loud rather than
averaged away.

WHERE THE LOGIC LIVES, AND WHY HERE. run-ladder.ps1 is PowerShell 5.1 and runs
on exactly one operating system; a Linux clone of this campaign has no ladder
runner at all yet. Putting the arithmetic in PowerShell would have made the
correct denominator a Windows-only privilege. So the measurement is Python -
stdlib only, no pip, importable and runnable on Windows, Linux and macOS - and
run-ladder.ps1 is now a fifteen-line shim that calls this and reads one JSON
line back. Any future POSIX runner calls the same script and gets the same
number, and `--audit-manifest` checks a whole manifest without a GPU, a model
load or a full download.

NO SECOND PARSER. The GGUF header parsing and the bpw arithmetic are
gguf-inspect.py's, loaded from the file next door and called with its printing
captured. This file adds no arithmetic of its own precisely so that the ladder
and the inspector can never drift into two different answers for one file.

COST. A GGUF stores its metadata and its complete tensor table at the FRONT of
the file, so a local read touches ~11 MiB of a 13 GiB file and a remote one
costs the same over HTTP range requests. Nothing is downloaded, nothing is
loaded, no GPU is touched.
"""

import argparse
import contextlib
import importlib.util
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
INSPECTOR = os.path.join(HERE, "gguf-inspect.py")


def load_inspector():
    """gguf-inspect.py, imported. Its name has a hyphen, so it is loaded by path.

    Everything below is a thin wrapper on its Reader/parse/report. That is the
    point: one implementation of the GGUF format in this repository, not two.
    """
    if not os.path.exists(INSPECTOR):
        raise SystemExit("measure-bpw.py: gguf-inspect.py is missing from %s"
                         % HERE)
    spec = importlib.util.spec_from_file_location("gguf_inspect", INSPECTOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)          # guarded by __name__ == "__main__"
    return mod


def measure(path=None, url=None, verbose=False):
    """Read one GGUF header and return its measured bits per weight.

    Exactly one of `path` (local file) and `url` (HTTP, ranged) is given.
    """
    gi = load_inspector()
    if (path is None) == (url is None):
        raise ValueError("give exactly one of path, url")
    rd = gi.Reader(url, remote=True) if url else gi.Reader(path)
    hdr = gi.parse(rd)
    # report() prints a page of tables and RETURNS the numbers. The tables are
    # for a human at a prompt; here only the return value is wanted, so its
    # stdout goes to a buffer (kept, and printed under --verbose) rather than
    # into the JSON line a caller is parsing.
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rep = gi.report(hdr, rd.size, path or url)
    if verbose:
        sys.stderr.write(buf.getvalue())

    # An unrecognised ggml type id contributes elements but zero bytes, so the
    # tensor-table figure would read low and the two metrics would disagree for
    # a reason that is not the file's fault. Say which case this is.
    unknown = sorted(k for k in rep["by_type"] if k.startswith("TYPE_"))
    bpw_size = rep["bpw_from_size"]
    bpw_tensors = rep["bpw_from_tensors"]
    agree = None
    if bpw_size and bpw_tensors:
        agree = 100.0 * (bpw_size - bpw_tensors) / bpw_tensors

    return {
        "path": path or url,
        "name": rep["name"],
        "arch": rep["arch"],
        "file_type": rep["file_type"],
        "size_bytes": rep["size_bytes"],
        "params": rep["params"],
        "params_source": "gguf-header",
        "n_tensors": len(hdr["tensors"]),
        "bpw": bpw_size,
        "bpw_from_tensors": bpw_tensors,
        "agreement_pct": agree,
        "tensor_table_complete": not unknown,
        "unknown_types": unknown,
        "header_bytes_read": rd.fetched,
    }


def compare(m, declared):
    """What the hand-typed denominator did to the number, as numbers."""
    declared = int(declared)
    if declared <= 0:
        raise ValueError("declared parameter count must be positive")
    bpw_declared = m["size_bytes"] * 8.0 / declared
    return {
        "params_declared": declared,
        "bpw_declared": bpw_declared,
        "params_error_pct": 100.0 * (declared - m["params"]) / m["params"],
        "bpw_inflation_pct": 100.0 * (bpw_declared - m["bpw"]) / m["bpw"],
    }


def _print_human(m, cmp_=None):
    print("file        : %s" % m["path"])
    print("name / arch : %s / %s" % (m["name"], m["arch"]))
    print("size        : %d bytes (%.3f GiB)"
          % (m["size_bytes"], m["size_bytes"] / 1024.0 ** 3))
    print("parameters  : %d  (%.3f B, summed over %d tensors in the file's "
          "own header)" % (m["params"], m["params"] / 1e9, m["n_tensors"]))
    print()
    print("  bpw, from file size    : %.4f   <- MEASURED, this is the column"
          % m["bpw"])
    print("  bpw, from tensor table : %.4f   <- independent check (rule 4)"
          % m["bpw_from_tensors"])
    if m["agreement_pct"] is not None:
        print("  they agree to          : %+.4f%%%s"
              % (m["agreement_pct"],
                 "" if m["tensor_table_complete"]
                 else "   (INCOMPLETE: unknown ggml types %s - the tensor-table"
                      " figure reads low, trust the file-size one)"
                      % ", ".join(m["unknown_types"])))
    if cmp_:
        print()
        print("  declared parameters    : %d" % cmp_["params_declared"])
        print("  bpw from the declared  : %.4f" % cmp_["bpw_declared"])
        print("  the declared count is  : %+.3f%% off the file's own"
              % cmp_["params_error_pct"])
        print("  so the published bpw   : %+.3f%% %s"
              % (cmp_["bpw_inflation_pct"],
                 "INFLATED" if cmp_["bpw_inflation_pct"] > 0 else "understated"))
    print()
    print("header bytes read: %.2f MiB of %.2f GiB"
          % (m["header_bytes_read"] / 1024.0 ** 2,
             m["size_bytes"] / 1024.0 ** 3))


def audit_manifest(manifest_path, tolerance_pct):
    """Every rung in a ladder manifest: declared denominator vs the file's own.

    No GPU, no model load, no download - so this is runnable before a campaign
    commits an hour to anything (rule 25), and on any platform.
    """
    with io.open(manifest_path, encoding="utf-8-sig") as fh:
        man = json.load(fh)
    rungs = man.get("rungs") or []
    print("manifest: %s" % manifest_path)
    print("%d rung(s); tolerance %.2f%%\n" % (len(rungs), tolerance_pct))
    hdr = ("%-22s %14s %14s %8s   %8s %8s %8s"
           % ("rung", "declared", "header", "d.par%", "bpw(dec)", "bpw(hdr)",
              "d.bpw%"))
    print(hdr)
    print("-" * len(hdr))
    bad, missing, rows = 0, 0, []
    for r in rungs:
        name = r.get("name", "?")
        path = r.get("path", "")
        if not path or not os.path.exists(path):
            print("%-22s %14s   file not present - not measured"
                  % (name, r.get("params", "?")))
            missing += 1
            continue
        m = measure(path=path)
        c = compare(m, r["params"])
        rows.append((name, m, c))
        flag = "" if abs(c["params_error_pct"]) <= tolerance_pct else "  <-- OFF"
        if flag:
            bad += 1
        print("%-22s %14d %14d %+7.3f%%   %8.4f %8.4f %+7.3f%%%s"
              % (name, c["params_declared"], m["params"],
                 c["params_error_pct"], c["bpw_declared"], m["bpw"],
                 c["bpw_inflation_pct"], flag))
    print()
    if missing:
        print("%d rung(s) had no file on this machine and were not measured."
              % missing)
    if bad:
        print("%d rung(s) declare a parameter count the file does not agree "
              "with. A bpw computed from those is DERIVED, not measured, and "
              "rule 1 will not let it be published under a 'measured' heading."
              % bad)
        return 1
    if rows:
        print("Every measured rung's declared count matches its file within "
              "%.2f%%." % tolerance_pct)
    return 0


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", nargs="?", help="a local .gguf file")
    ap.add_argument("--hf", help="huggingface repo id (reads the header by "
                                 "HTTP range request; downloads nothing)")
    ap.add_argument("--file", help="gguf filename inside the repo")
    ap.add_argument("--declared", type=int, default=None,
                    help="a hand-typed parameter count to compare against")
    ap.add_argument("--json", action="store_true",
                    help="one JSON object on one line - what run-ladder.ps1 "
                         "and any POSIX runner read")
    ap.add_argument("--verbose", action="store_true",
                    help="also write gguf-inspect's full per-dtype tables to "
                         "stderr")
    ap.add_argument("--audit-manifest", nargs="?", const="", metavar="FILE",
                    help="audit every rung of a ladder manifest (default: "
                         "ladder-manifest.json beside this script)")
    ap.add_argument("--tolerance-pct", type=float, default=0.1,
                    help="audit: how far a declared count may sit from the "
                         "file's own before it is called OFF (default 0.1)")
    a = ap.parse_args()

    if a.audit_manifest is not None:
        path = a.audit_manifest or os.path.join(HERE, "ladder-manifest.json")
        return audit_manifest(path, a.tolerance_pct)

    url = None
    if a.hf:
        import urllib.request
        fn = a.file
        if not fn:
            with urllib.request.urlopen(
                    "https://huggingface.co/api/models/" + a.hf, timeout=60) as r:
                meta = json.loads(r.read().decode())
            cands = [s["rfilename"] for s in meta.get("siblings", [])
                     if s["rfilename"].endswith(".gguf")
                     and "mmproj" not in s["rfilename"].lower()]
            if not cands:
                return _die("no non-mmproj .gguf in %s" % a.hf)
            fn = sorted(cands)[0]
        url = "https://huggingface.co/%s/resolve/main/%s" % (a.hf, fn)
    elif not a.path:
        return _die("give a .gguf path, --hf <repo>, or --audit-manifest")

    m = measure(path=a.path, url=url, verbose=a.verbose)
    c = compare(m, a.declared) if a.declared else None
    if a.json:
        out = dict(m)
        if c:
            out.update(c)
        print(json.dumps(out))
    else:
        _print_human(m, c)
    return 0


def _die(msg):
    sys.stderr.write("measure-bpw.py: %s\n" % msg)
    return 2


if __name__ == "__main__":
    sys.exit(main())
