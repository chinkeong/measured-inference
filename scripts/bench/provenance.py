# -*- coding: utf-8 -*-
"""What was this measurement taken WITH? Recorded once, by every probe.

WHY THIS EXISTS, and it is a defect this campaign published rather than a
precaution. On 2026-08-28 one configuration - UD-IQ4_XS, n-max 10 / p-min 0.5,
-c 32768, -ngl 99, --parallel 1, -fa on, KV q8_0, greedy, 700 predicted tokens,
the same prompt - was found to read 80.0 t/s where the archive held 86.91,
87.4, 93.9 and 106.2 for the identical flags. Probe pacing explained 6.9 points
of a 25-point gap. Every other candidate was ruled out because the conditions
matched. The one remaining candidate was the llama.cpp build, AND IT COULD NOT
BE CHECKED: the 2026-08-21 server logs on disk are zero bytes, and only three
artefacts in the entire repository recorded a build string at all.

A throughput number whose toolchain is not recorded cannot be compared with a
later one. It is not reproducible, and this campaign had been publishing those.

Rule 3 says the conditions travel with the number. The server binary IS a
condition - arguably the strongest one, because it changes what the same flags
do - and it was the one condition nothing captured.

WHAT IS CAPTURED, and why each:

  llama.cpp build and commit   the binary that did the decoding
  binary size and mtime        catches a rebuilt binary that kept its version
                               string, which a version string alone cannot
  NVIDIA driver version        owns the clock and power behaviour under the cap
  GPU name and board limit     the card, and whether its cap is at stock
  model file size and mtime    catches a re-quantised file under the same name
  python version and platform  the harness itself

ABSENCE IS RECORDED, NEVER OMITTED. Every field that cannot be read is written
as an explicit "NOT RECORDED: <reason>" string rather than dropped, because a
missing key reads as "not applicable" to whoever finds the artefact later, and
that is exactly how the 2026-08-21 numbers came to look comparable when they
were not.
"""
import os
import platform
import re
import subprocess
import sys


def _run(args, timeout=20):
    try:
        p = subprocess.run(args, capture_output=True, text=True,
                           timeout=timeout)
        return ((p.stdout or "") + (p.stderr or "")).strip()
    except Exception as exc:
        return "NOT RECORDED: %s: %s" % (type(exc).__name__, exc)


def _stat(path):
    """Size and mtime of a file, so a rebuild that kept its version string is
    still visible."""
    try:
        st = os.stat(path)
        return {"path": path, "bytes": st.st_size,
                "mtime": __import__("time").strftime(
                    "%Y-%m-%d %H:%M:%S", __import__("time").localtime(st.st_mtime))}
    except Exception as exc:
        return {"path": path,
                "bytes": "NOT RECORDED: %s" % type(exc).__name__,
                "mtime": "NOT RECORDED: %s" % type(exc).__name__}


def server_build(server_path):
    """llama.cpp build and commit, read from the binary that will run.

    Parsed from `llama-server --version`, which prints e.g.
        version: 0.1.2-dev (build 10502, commit 0adcc3bb5)
    The raw line is kept alongside the parsed fields, so a format change
    degrades to 'the raw string is still here' rather than to silence.
    """
    raw = _run([server_path, "--version"])
    out = {"raw": raw, "binary": _stat(server_path)}
    # The launcher is a stub - 9,216 bytes on this rig - so its own mtime says
    # nothing about the code that decodes. Stat the compute libraries beside
    # it, which are where a rebuild actually lands. This is what ruled the
    # build out as the cause of the 2026-08-28 throughput gap: every ggml
    # library was dated 2026-08-19, unchanged across every measurement in
    # question.
    try:
        d = os.path.dirname(os.path.abspath(server_path))
        libs = sorted(f for f in os.listdir(d)
                      if f.lower().startswith("ggml")
                      and f.lower().endswith((".dll", ".so")))
        out["compute_libraries"] = [_stat(os.path.join(d, f)) for f in libs]
        if not libs:
            out["compute_libraries"] = ("NOT RECORDED: no ggml libraries "
                                        "found beside the server binary")
    except Exception as exc:
        out["compute_libraries"] = ("NOT RECORDED: %s: %s"
                                    % (type(exc).__name__, exc))
    m = re.search(r"build\s+(\d+)", raw)
    out["build"] = m.group(1) if m else "NOT RECORDED: no build number in --version output"
    m = re.search(r"commit\s+([0-9a-f]+)", raw)
    out["commit"] = m.group(1) if m else "NOT RECORDED: no commit in --version output"
    m = re.search(r"version:\s*(\S+)", raw)
    out["version"] = m.group(1) if m else "NOT RECORDED: no version in --version output"
    return out


def gpu_state():
    """Driver, card, and whether the board limit is at its stock value.

    The cap is persistent hardware state that survives the process, so an
    artefact that does not record it cannot prove it was measured at stock.
    """
    q = ("driver_version,name,power.limit,power.default_limit,"
         "memory.total,clocks.max.sm")
    raw = _run(["nvidia-smi", "--query-gpu=" + q,
                "--format=csv,noheader,nounits"])
    if raw.startswith("NOT RECORDED"):
        return {"raw": raw}
    parts = [x.strip() for x in raw.split(",")]
    if len(parts) < 6:
        return {"raw": raw,
                "note": "NOT RECORDED: unexpected nvidia-smi field count"}
    out = {"raw": raw, "driver": parts[0], "name": parts[1],
           "power_limit_w": parts[2], "power_default_limit_w": parts[3],
           "memory_total_mib": parts[4], "max_sm_mhz": parts[5]}
    try:
        out["cap_at_stock"] = abs(float(parts[2]) - float(parts[3])) < 1.0
    except ValueError:
        out["cap_at_stock"] = "NOT RECORDED: power limits unparseable"
    return out


def toolchain(server_path=None, model_path=None):
    """The whole provenance block. Call once per probe and put it in the
    artefact, at the top level, beside the conditions."""
    block = {
        "recorded_by": "scripts/bench/provenance.py",
        "why": "rule 3 - the conditions travel with the number, and the "
               "server binary is a condition. A throughput figure whose "
               "build is unrecorded cannot be compared with a later one.",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "gpu": gpu_state(),
    }
    block["llama_cpp"] = (server_build(server_path) if server_path
                          else "NOT RECORDED: probe passed no server path")
    block["model_file"] = (_stat(model_path) if model_path
                           else "NOT RECORDED: probe passed no model path")
    return block


USAGE = """print this machine's toolchain block, the way a probe records it

    python provenance.py [llama-server] [model.gguf]

Both arguments are optional: the server is resolved through scripts/lib/paths
($LLAMA_SERVER, $LLAMA_DIR, PATH, <repo>/bin/llama.cpp) when it is omitted."""

if __name__ == "__main__":
    import json
    # --help must answer without resolving anything: a help request that needs
    # a toolchain installed is a help request nobody can read on a fresh clone.
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        print(USAGE)
        sys.exit(0)
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "lib"))
    import paths
    sp = paths.llama_bin("llama-server",
                         sys.argv[1] if len(sys.argv) > 1 else None)
    mp = sys.argv[2] if len(sys.argv) > 2 else None
    print(json.dumps(toolchain(sp, mp), indent=2))
