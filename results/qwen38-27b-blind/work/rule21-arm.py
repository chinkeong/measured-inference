"""Run one rule-21 arm of the Qwen3.8-27B UD-IQ4_XS effort sweep.

    python -u rule21-arm.py <effort> [suite.json] [tag]

Everything the server needs that isn't a bench.py default goes through
--server-args as ONE string; building the argv list here (instead of on a
PowerShell command line) is what keeps the JSON in
--chat-template-kwargs {"reasoning_effort":"..."} intact: subprocess'
list2cmdline escapes the inner quotes and llama-server's CRT parser
un-escapes them, with no shell in between.

Artifacts (run JSON, transcripts, PNG, llama-server log, wall time) are copied
into results/qwen38-27b-blind/data/rule21/ under an arm-<tag>- prefix.
"""

import datetime
import json
import os
import shutil
import sys
import time

BENCH = r"E:\AI\measured-inference\scripts\bench"
OUT = r"E:\AI\measured-inference\results\qwen38-27b-blind\data\rule21"
MODEL = r"C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-IQ4_XS.gguf"
SRV = r"E:\AI\llama.cpp\llama-server.exe"
PORT = "1236"

try:
    sys.stdout.reconfigure(line_buffering=True)
except AttributeError:
    pass


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: rule21-arm.py <effort> [suite.json] [tag] [datasets]")
    effort = sys.argv[1]
    suite = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        BENCH, "suites", "rule21-n25.json")
    tag = sys.argv[3] if len(sys.argv) > 3 else effort
    # optional 4th arg: narrow the suite to these datasets (rule 7 re-runs)
    only = sys.argv[4] if len(sys.argv) > 4 else None

    os.chdir(BENCH)
    sys.path.insert(0, BENCH)
    resdir = os.path.join(BENCH, "results")
    os.makedirs(resdir, exist_ok=True)
    before = set(os.listdir(resdir))

    sargs = ('-ctk q8_0 -ctv q8_0 --chat-template-kwargs '
             '{"reasoning_effort":"%s"}' % effort)
    sys.argv = ["bench.py",
                "--model", MODEL,
                "--server-bin", SRV,
                "--suite", suite,
                "--rule21",
                "--transcripts",
                "--port", PORT,
                "--server-args", sargs]
    if only:
        sys.argv += ["--datasets", only]

    print("=== ARM %s (reasoning_effort=%s) ===" % (tag, effort))
    if only:
        print("datasets    : %s (narrowed)" % only)
    print("suite       : %s" % suite)
    print("server-args : %s" % sargs)
    print("started     : %s" % datetime.datetime.now().isoformat(timespec="seconds"))

    import bench
    t0 = time.time()
    try:
        bench.main()
    except SystemExit as e:
        print("bench.main() exited: %s" % e)
    except BaseException as e:                      # noqa: BLE001 - report, then still copy
        print("bench.main() raised: %r" % (e,))
        raise
    finally:
        wall = time.time() - t0
        print("wall_s=%.1f  (%.2f h)" % (wall, wall / 3600.0))
        os.makedirs(OUT, exist_ok=True)
        for f in sorted(set(os.listdir(resdir)) - before):
            shutil.copy2(os.path.join(resdir, f),
                         os.path.join(OUT, "arm-%s-%s" % (tag, f)))
            print("copied %s" % f)
        log = os.path.join(resdir, "llama-server.log")
        if os.path.exists(log):
            shutil.copy2(log, os.path.join(OUT, "arm-%s-llama-server.log" % tag))
        meta = {"arm": tag, "effort": effort, "wall_s": round(wall, 1),
                "wall_h": round(wall / 3600.0, 3), "suite": suite,
                "server_args": sargs, "model": MODEL,
                "finished": datetime.datetime.now().isoformat(timespec="seconds")}
        with open(os.path.join(OUT, "arm-%s-wall.json" % tag), "w",
                  encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        print("ARM %s DONE" % tag)


main()
