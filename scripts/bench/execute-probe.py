"""A6 — execute the code the detectors only ever read.

    python execute-probe.py

WHY. This campaign publishes `verdict=PASS` for every rung's probe-A output on
the strength of FOUR LEXICAL CHECKS: no immediate repeats, no line loops, no
tail n-grams, a well-formed fenced block. Not one of them runs the program. The
judge panel already found the gap in the other direction — an answer that reads
perfectly and does nothing — and an independent tester reports sub-4-bit files
failing at runtime while looking fine on the page. A PASS that was never
executed is a claim about prose, not about code.

WHAT PROBE A ACTUALLY ASKED. It is a CONTINUATION task, not "write a program":
the prompt supplies a file header and the opening of `class MinHeap` up to
`push(node, pri) {`, then asks for the rest — MinHeap, Graph, dijkstra,
reconstructPath, buildDemoGraph and a worked example printing A→H — and says
"Output raw code only - no prose, no markdown fences, no commentary."

So an output that begins `this.a.push({ node, pri });` is CORRECT: it is
continuing mid-method. Reading that as truncation would be the error. Three
distinct behaviours appear across the rungs and each is scored here:
  CONTINUED  — resumed mid-method as instructed (prefix + output is the program)
  RESTARTED  — re-emitted the whole file from its own header (output is the
               program, and the instruction was not followed)
  FENCED     — emitted ``` markers the prompt explicitly forbade

Each rung is assembled into a runnable program by its own shape, then executed
under node with a wall-clock timeout. What is reported is what a reader would
experience: does it parse, does it run, does it print the answer it promised.
The demo graph is model-generated, so there is no fixed correct cost to check
against — the honest test is completion and output shape, not a golden value.
"""

import glob
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
D = os.path.join(ROOT, "results", "qwen38-27b-blind", "data", "quant-ladder")
SCRIPTS = os.path.join(ROOT, "scripts", "quant-ladder", "detectors.ps1")
TIMEOUT = 15

ORDER = ["UD-IQ4_XS", "UD-Q3_K_XL", "UD-IQ3_XXS", "UD-Q2_K_XL", "QAT-Q2_0",
         "UD-IQ2_S", "UD-IQ2_XXS", "UD-IQ1_M", "UD-IQ1_S", "NVFP4-MTP-VERY-LOW",
         "gemma-4-12B-QAT-Q4_0"]
# QAT-Q2_0 is sdkyuan/qwen3.8-27B-qat-q2_0-gguf: quantisation-aware TRAINED,
# not post-training quantised like every UD- rung, and 2.595 bpw on this
# ladder's fixed 27e9-parameter convention. It is listed in bpw order, but the
# reader has to be told it was MADE differently - otherwise the x-axis appears
# to explain a result that method may explain instead.
BPW = {"UD-IQ4_XS": 4.223, "UD-Q3_K_XL": 3.895, "UD-IQ3_XXS": 3.240,
       "UD-Q2_K_XL": 2.912, "QAT-Q2_0": 2.595, "UD-IQ2_S": 2.481,
       "UD-IQ2_XXS": 2.153, "UD-IQ1_M": 1.994, "UD-IQ1_S": 1.835,
       "NVFP4-MTP-VERY-LOW": 4.404, "gemma-4-12B-QAT-Q4_0": 4.651}


def prefix():
    """The code the prompt already supplied, recovered from the probe script."""
    c = open(SCRIPTS, encoding="utf-8", errors="replace").read()
    m = re.search(r"\$PROBE_A\s*=\s*@['\"](.*?)['\"]@", c, re.S)
    if not m:
        sys.exit("could not recover the probe-A prompt")
    p = m.group(1)
    i = p.find("// dijkstra.js")
    return p[i:] if i >= 0 else ""


def strip_fences(t):
    t = re.sub(r"^\s*```[a-zA-Z]*\s*", "", t)
    t = re.sub(r"```\s*$", "", t.rstrip())
    return re.sub(r"^```[a-zA-Z]*\s*$", "", t, flags=re.M)


def assemble(raw, pre):
    """Return (program, shape). How the file is built depends on what it did.

    A FOURTH SHAPE, found 2026-08-26 by the QAT-Q2_0 rung. The prompt's prefix
    ends mid-method at `push(node, pri) {`, and a model may RE-EMIT that line
    before continuing rather than continuing from it. Concatenating prefix and
    output then duplicates the signature and node reports
    `SyntaxError: Unexpected token '{'` — a fault of the join, not of the code.

    That very nearly went into the ladder as `executes = False` for a file whose
    program is correct: strip the duplicated line and it prints
    "Shortest path from A to H: A -> C -> D -> F -> H, Total cost: 50". A probe
    that blames the model for the harness's own splice is worse than no probe,
    because it reads as a measurement.

    Only QAT-Q2_0 shows this shape; every other rung was re-checked and its
    published result is unchanged.
    """
    fenced = "```" in raw[:400]
    body = strip_fences(raw) if fenced else raw
    head = body.lstrip()[:200]
    if "// dijkstra.js" in head or head.startswith("class MinHeap"):
        return body, ("RESTARTED-fenced" if fenced else "RESTARTED")
    pre_last = [l for l in pre.rstrip().split("\n") if l.strip()]
    out_first = body.lstrip().split("\n")[0].strip()
    if pre_last and out_first and pre_last[-1].strip() == out_first:
        deduped = "\n".join(body.lstrip().split("\n")[1:])
        return (pre.rstrip() + "\n" + deduped,
                ("RE-EMITTED-fenced" if fenced else "RE-EMITTED"))
    return pre + body, ("CONTINUED-fenced" if fenced else "CONTINUED")


def run(program):
    fd, path = tempfile.mkstemp(suffix=".js", dir=tempfile.gettempdir())
    os.close(fd)
    open(path, "w", encoding="utf-8").write(program)
    try:
        p = subprocess.run(["node", path], capture_output=True, text=True,
                           timeout=TIMEOUT, encoding="utf-8", errors="replace")
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return -99, "", "TIMEOUT after %ds — did not terminate" % TIMEOUT
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def check(rc, out, err):
    if rc == -99:
        return "HANGS", "never terminated"
    if rc != 0:
        first = (err.splitlines() or [""])[0]
        kind = "THROWS"
        for k in ("SyntaxError", "ReferenceError", "TypeError", "RangeError"):
            if k in err:
                kind = k.upper() if k == "SyntaxError" else "THROWS"
                first = next((l.strip() for l in err.splitlines() if k in l), first)
                break
        return ("SYNTAX" if "SyntaxError" in err else kind), first[:110]
    lower = out.lower()
    has_path = "->" in out or "→" in out
    has_cost = "cost" in lower
    if has_path and has_cost:
        return "RUNS", (out.splitlines() or [""])[-1][:110]
    if out:
        return "RUNS-PARTIAL", "no path/cost line: " + (out.splitlines() or [""])[-1][:80]
    return "SILENT", "exit 0 but printed nothing"


USAGE = """\
A6 - assemble each quant rung's probe-A answer into a runnable program and
EXECUTE it under node, because every published PASS for that probe came from
four lexical checks and not one of them ran the code.

    python scripts/bench/execute-probe.py

Positional arguments: none. The rung order, the bpw table and the 15-second
timeout are pinned in this file; the prompt prefix those answers continue from
is recovered out of scripts/quant-ladder/detectors.ps1.

No environment variables. No server, no model, no GPU - but `node` must be on
PATH, and this runs model-generated JavaScript on this machine.

Example:
  python scripts/bench/execute-probe.py

Reads results/qwen38-27b-blind/data/quant-ladder/det-<rung>-probeA.txt. Writes
.../quant-ladder/execute-probe.json and prints one row per rung: which of the
four shapes the answer took, whether it ran, and the last line it printed.
"""


def main():
    # A help request must never start work. This script has no argument parser,
    # so without this line --help falls through, executes eleven rungs of
    # model-written JavaScript under node and overwrites execute-probe.json.
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        print(USAGE.rstrip())
        return

    pre = prefix()
    print("Probe-A code, EXECUTED under node %s. Timeout %ds.\n"
          % (subprocess.run(["node", "--version"], capture_output=True,
                            text=True).stdout.strip(), TIMEOUT))
    print("%-22s %6s  %-16s %-13s %s"
          % ("file", "bpw", "followed prompt", "result", "detail"))
    rows = []
    for name in ORDER:
        f = os.path.join(D, "det-%s-probeA.txt" % name)
        if not os.path.exists(f):
            continue
        raw = open(f, encoding="utf-8", errors="replace").read()
        prog, shape = assemble(raw, pre)
        rc, out, err = run(prog)
        res, detail = check(rc, out, err)
        rows.append({"file": name, "bpw": BPW.get(name), "shape": shape,
                     "result": res, "detail": detail})
        print("%-22s %6s  %-16s %-13s %s"
              % (name, BPW.get(name, "?"), shape, res, detail))
    out = os.path.join(D, "execute-probe.json")
    json.dump({"node": subprocess.run(["node", "--version"], capture_output=True,
                                      text=True).stdout.strip(),
               "timeout_s": TIMEOUT, "results": rows},
              open(out, "w", encoding="utf-8"), indent=1)
    print("\n-> %s" % out)
    ran = sum(1 for r in rows if r["result"] == "RUNS")
    print("%d of %d produced a working program." % (ran, len(rows)))


if __name__ == "__main__":
    main()
