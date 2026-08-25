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

D = r"E:\AI\measured-inference\results\qwen38-27b-blind\data\quant-ladder"
SCRIPTS = r"E:\AI\measured-inference\scripts\quant-ladder\detectors.ps1"
TIMEOUT = 15

ORDER = ["UD-IQ4_XS", "UD-Q3_K_XL", "UD-IQ3_XXS", "UD-Q2_K_XL", "UD-IQ2_S",
         "UD-IQ2_XXS", "UD-IQ1_M", "UD-IQ1_S", "NVFP4-MTP-VERY-LOW",
         "gemma-4-12B-QAT-Q4_0"]
BPW = {"UD-IQ4_XS": 4.223, "UD-Q3_K_XL": 3.895, "UD-IQ3_XXS": 3.240,
       "UD-Q2_K_XL": 2.912, "UD-IQ2_S": 2.481, "UD-IQ2_XXS": 2.153,
       "UD-IQ1_M": 1.994, "UD-IQ1_S": 1.835, "NVFP4-MTP-VERY-LOW": 4.404,
       "gemma-4-12B-QAT-Q4_0": 4.651}


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
    """Return (program, shape). How the file is built depends on what it did."""
    fenced = "```" in raw[:400]
    body = strip_fences(raw) if fenced else raw
    head = body.lstrip()[:200]
    if "// dijkstra.js" in head or head.startswith("class MinHeap"):
        return body, ("RESTARTED-fenced" if fenced else "RESTARTED")
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


def main():
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


main()
