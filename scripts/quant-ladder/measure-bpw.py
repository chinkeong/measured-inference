#!/usr/bin/env python3
"""Bits per weight, MEASURED: the denominator comes from the file, not a manifest.

    python scripts/quant-ladder/measure-bpw.py <file.gguf>
    python scripts/quant-ladder/measure-bpw.py <file.gguf> --json
    python scripts/quant-ladder/measure-bpw.py <file.gguf> --declared 27000000000
    python scripts/quant-ladder/measure-bpw.py --hf <repo-id> [--file name.gguf]
    python scripts/quant-ladder/measure-bpw.py <file.gguf> --backend openvino --device NPU
    python scripts/quant-ladder/measure-bpw.py --audit-manifest --backend openvino --device NPU

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

AND A THIRD NUMBER, WHEN THE BACKEND IS NAMED. Both figures above describe
the FILE. On four backends -- cuda, vulkan, metal and the ggml CPU one -- the
file is also what runs, so there is one number and this section is empty. On
the OpenVINO backend it is not: that backend requantises tensors at load
(ggml/src/ggml-openvino/ggml-openvino-extra.cpp:252-273, read 2026-08-29), so
`bpw` describes the download and `bpw_effective` describes the run, and on its
NPU device every quantized tensor becomes Q4_0_128 whatever the file held --
which makes a quant ladder there a set of arms that are the same weights.

`--backend` and `--device` turn that section on. With neither, `bpw_effective`
is reported as null WITH THE REASON rather than quietly set equal to `bpw`: a
null that says why is falsifiable and a wrong number is not. The table lives in
`scripts/lib/openvino_quant.py`, which also carries the shortest route to
ground truth -- four commented-out log lines in llama.cpp.

`--audit-manifest --backend openvino --device NPU` is the cheapest thing in
this repository (rule 25): it costs a header read per rung and no GPU at all,
and it says before the ladder runs whether two of its rungs are the same
weights.

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

# The OpenVINO conversion table. Guarded like every other cross-file import in
# this repository: without it the effective figure is null with a reason, which
# is a supported answer, where a traceback would take out the bpw measurement
# this script exists for.
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
try:
    import openvino_quant as ovq
except Exception as _exc:                                    # pragma: no cover
    ovq = None
    OVQ_WHY = ("scripts/lib/openvino_quant.py could not be imported (%s: %s), "
               "so no backend's effect on this file's tensor types can be "
               "established" % (type(_exc).__name__, _exc))
else:
    OVQ_WHY = None


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


def effective(hdr, gi, backend, device, label=None):
    """What the RUN holds, against what the file holds. Never a silent equal.

    Returns a dict whose `kind` is "passthrough", "rewrite" or "unknown" and
    whose `bpw_effective` is a number only in the first two cases. The tensor
    rows are built here, from gguf-inspect's block table, because
    openvino_quant.py keeps no second copy of it.
    """
    if ovq is None:
        return {"kind": "unknown", "backend": backend, "device": device,
                "bpw_effective": None, "why": OVQ_WHY}
    eff = ovq.backend_effect(backend, device)
    if eff["kind"] == "unknown":
        return {"kind": "unknown", "backend": eff.get("backend"),
                "device": None, "bpw_effective": None, "why": eff["why"]}
    if eff["kind"] == "passthrough":
        return {"kind": "passthrough", "backend": eff["backend"],
                "device": None, "bpw_effective": None,
                "why": "%s. bpw above IS the effective figure, by identity and "
                       "not by arithmetic." % eff["why"],
                "equals_bpw": True}

    rows = []
    for t in hdr["tensors"]:
        e = 1
        for d in t["dims"]:
            e *= d
        info = gi.GGML.get(t["type"])
        name, bs, bb = info if info else ("TYPE_%d" % t["type"], 0, 0)
        rows.append({"name": t["name"], "elements": e,
                     "ne0": t["dims"][0] if t["dims"] else 0, "type": name,
                     "bytes": (e // bs) * bb if (bs and bb) else 0})
    prof = ovq.model_profile(rows, eff["device"], label=label)
    if prof.get("bpw_effective") is None:
        return {"kind": "unknown", "backend": "openvino", "device": None,
                "bpw_effective": None, "why": prof.get("why")}
    return {
        "kind": "rewrite",
        "backend": "openvino",
        "device": prof["device"],
        "bpw_effective": prof["bpw_effective"],
        "bpw_effective_if_f32_scale": prof["bpw_effective_if_f32_scale"],
        "bpw_file_same_basis": prof["bpw_file_tensor_table"],
        "delta_bpw": prof["delta_bpw"],
        "tensors_rewritten": prof["tensors_rewritten"],
        "tensors": prof["tensors"],
        "basis": prof["basis"],
        "by_role": {k: {"bpw_file": v["bpw_file"],
                        "bpw_effective": v["bpw_effective"],
                        "elements": v["elements"], "tensors": v["tensors"],
                        "effective_types": v["effective_types"]}
                    for k, v in prof["by_role"].items()},
        "conversions": prof["conversions"],
        "unrecognised_source_types": prof["unrecognised_source_types"],
        "collapse": prof["collapse"],
        "signature": ovq.ladder_signature(prof),
        "why": eff["why"],
        "not_reported_by_the_backend":
            "the backend prints nothing about it: the four GGML_LOG_DEBUG "
            "lines that would are commented out at %s, and /props->description "
            "carries only the OpenVINO version string (%s)"
            % (ovq.SOURCE["commented_out_logging"],
               ovq.SOURCE["props_description"]),
        "ground_truth": ovq.GROUND_TRUTH["how"],
        "warnings": prof["warnings"],
    }


def measure(path=None, url=None, verbose=False, backend=None, device=None):
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

    eff = effective(hdr, gi, backend, device,
                    label=os.path.basename(path or url))
    if eff.get("equals_bpw"):
        # Said once, here, rather than recomputed: on a passthrough backend the
        # effective figure IS the file figure, and copying it is the whole
        # arithmetic. Anything else would invent a second number for one fact.
        eff["bpw_effective"] = bpw_size
        eff["bpw_file_same_basis"] = bpw_size
        eff["delta_bpw"] = 0.0

    return {
        "path": path or url,
        "effective": eff,
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
    _print_effective(m.get("effective") or {})
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


def _print_effective(eff):
    """The third number, and -- when it differs from the first two -- why.

    Says it plainly or says nothing was established. What it will never do is
    print a number equal to bpw without having checked that the backend leaves
    the file alone, which is the failure the whole block exists to catch.
    """
    kind = eff.get("kind")
    if not kind:
        return
    print()
    if kind == "unknown":
        print("  bpw, as the run holds it: NOT ESTABLISHED")
        for line in _wrap(eff.get("why") or "", 68):
            print("      %s" % line)
        return
    if kind == "passthrough":
        print("  bpw, as the run holds it: %.4f   <- the SAME number, on %s"
              % (eff["bpw_effective"], eff["backend"]))
        for line in _wrap(eff.get("why") or "", 68):
            print("      %s" % line)
        return

    print("  bpw, as the run holds it: %.4f   <- %s on %s, and it is NOT the "
          "file's" % (eff["bpw_effective"], eff["backend"], eff["device"]))
    print()
    print("  THE TWO DIFFER BY %+.4f bpw, and here is why."
          % (eff["bpw_effective"] - eff["bpw_file_same_basis"]))
    print("  The %s backend requantises tensors at load. %d of the file's %d "
          "tensors are" % (eff["backend"], eff["tensors_rewritten"],
                           eff["tensors"]))
    print("  rewritten before the first token, and nothing in the run says so.")
    print()
    print("  On the same tensor-table basis (no container overhead on either "
          "side):")
    print("      the file holds       : %.4f bpw" % eff["bpw_file_same_basis"])
    print("      the run holds        : %.4f bpw  (%.4f if the block scale is "
          "f32, not f16)"
          % (eff["bpw_effective"], eff["bpw_effective_if_f32_scale"]))
    print()
    print("  %-12s %8s %8s  %18s  %s"
          % ("role", "file", "run", "weights", "becomes"))
    for role in ("token_embd", "output", "block"):
        b = (eff.get("by_role") or {}).get(role)
        if not b:
            continue
        print("  %-12s %8.3f %8.3f  %18s  %s"
              % (role, b["bpw_file"] or 0, b["bpw_effective"] or 0,
                 "{:,}".format(b["elements"]),
                 ", ".join(sorted(b["effective_types"]))))
    changed = [c for c in (eff.get("conversions") or []) if c["changed"]]
    if changed:
        print()
        print("  the conversions that fired (rule numbers are %s):"
              % (ovq.SOURCE["conversion_table"] if ovq else "the table"))
        for c in changed:
            print("      rule %s  %-8s -> %-9s %4d tensor%s %18s weights  %s"
                  % (c["rule_n"], c["source"], c["effective"], c["tensors"],
                     " " if c["tensors"] == 1 else "s",
                     "{:,}".format(c["elements"]), "/".join(c["roles"])))
    col = eff.get("collapse") or {}
    if col.get("degenerate"):
        print()
        print("  DEGENERATE LADDER RUNG. %d distinct quantized types in this "
              "file's body" % col["distinct_in"])
        print("  tensors all become %s. Another rung whose body tensors also "
              "collapse to"
              % (col.get("effective_types_in_blocks") or ["?"])[0])
        print("  that type is the SAME WEIGHTS under a different filename, and "
              "comparing")
        print("  the two measures run-to-run variance (rule 30).")
    print()
    for line in _wrap(eff.get("not_reported_by_the_backend") or "", 72):
        print("  %s" % line)
    print()
    print("  the conditions that number depends on (rule 3):")
    for warn in eff.get("warnings") or []:
        first = True
        for line in _wrap(warn, 68):
            print("    %s %s" % ("-" if first else " ", line))
            first = False


def _wrap(text, width):
    """Wrap without importing textwrap for one call. Words, greedily."""
    out, line = [], ""
    for word in (text or "").split():
        if line and len(line) + 1 + len(word) > width:
            out.append(line)
            line = word
        else:
            line = (line + " " + word) if line else word
    if line:
        out.append(line)
    return out


def audit_manifest(manifest_path, tolerance_pct, backend=None, device=None):
    """Every rung in a ladder manifest: declared denominator vs the file's own.

    No GPU, no model load, no download - so this is runnable before a campaign
    commits an hour to anything (rule 25), and on any platform.

    With a backend that rewrites tensor types, it answers a second question the
    manifest cannot: whether two rungs are the same weights. That verdict costs
    one header read per rung and it is worth every hour it saves - an OpenVINO
    NPU ladder is degenerate by construction, and finding that out from a flat
    perplexity curve costs the whole ladder.
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
        m = measure(path=path, backend=backend, device=device)
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
    _audit_effective(rows, backend, device)
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


def _audit_effective(rows, backend, device):
    """Which rungs of this ladder are the same weights once the backend loads.

    Silent unless a backend was named and that backend rewrites: with no
    --backend there is nothing to say, and saying "probably fine" would be the
    fourth provenance category rule 1 does not have.
    """
    if not rows or ovq is None:
        return
    effs = [(name, m.get("effective") or {}) for name, m, _c in rows]
    if not any(e.get("kind") == "rewrite" for _n, e in effs):
        return
    print("%s on %s rewrites tensor types at load, so the rungs above describe "
          "downloads." % (backend, device))
    print("What each rung RUNS:")
    print()
    print("  %-22s %10s %10s %9s   %s"
          % ("rung", "bpw(file)", "bpw(run)", "delta", "body tensors become"))
    for name, e in effs:
        if e.get("kind") != "rewrite":
            print("  %-22s   not established: %s" % (name, (e.get("why") or "")[:40]))
            continue
        col = e.get("collapse") or {}
        bad = e.get("unrecognised_source_types")
        print("  %-22s %10.4f %10.4f %+9.4f   %s%s"
              % (name, e["bpw_file_same_basis"], e["bpw_effective"],
                 e["delta_bpw"],
                 ", ".join(col.get("effective_types_in_blocks") or ["?"]),
                 "" if not bad else
                 "   <-- bpw(file) and delta are LOW: %s not in the block table"
                 % ", ".join(bad)))
    print()
    groups = {}
    for name, e in effs:
        sig = e.get("signature")
        if sig:
            groups.setdefault(sig, []).append(name)
    same = [g for g in groups.values() if len(g) > 1]
    if same:
        print("THESE RUNGS ARE THE SAME WEIGHTS. Running them as separate arms "
              "measures")
        print("run-to-run variance and nothing else (rule 30):")
        for g in same:
            print("    %s" % ", ".join(sorted(g)))
        print()
        print("%d rung(s) in this manifest run %d distinct set(s) of weights "
              "on %s." % (len(effs), len(groups), device))
        return
    print("%d rung(s), %d distinct set(s) of weights on %s: every arm is a "
          "different arm." % (len(effs), len(groups), device))


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
    ap.add_argument("--backend",
                    help="the backend the effective figure is scoped to: cuda, "
                         "vulkan, metal, cpu, openvino. Without it, "
                         "bpw_effective is null and says why - it is never "
                         "quietly set equal to bpw")
    ap.add_argument("--device",
                    help="OpenVINO device - CPU, GPU, GPU.0, GPU.1, NPU (what "
                         "GGML_OPENVINO_DEVICE takes; it is read when this is "
                         "not given). On NPU every quantized tensor is "
                         "rewritten to Q4_0_128 at load")
    ap.add_argument("--tolerance-pct", type=float, default=0.1,
                    help="audit: how far a declared count may sit from the "
                         "file's own before it is called OFF (default 0.1)")
    a = ap.parse_args()

    backend, device = a.backend, a.device
    if backend and backend.strip().lower() == "openvino" and not device \
            and ovq is not None:
        device, _how = ovq.device_from_env()

    if a.audit_manifest is not None:
        path = a.audit_manifest or os.path.join(HERE, "ladder-manifest.json")
        return audit_manifest(path, a.tolerance_pct, backend, device)

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

    m = measure(path=a.path, url=url, verbose=a.verbose,
                backend=backend, device=device)
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
