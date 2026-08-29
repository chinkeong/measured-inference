#!/usr/bin/env python3
"""Does scripts/arms.py still do what a sweep depends on? Asked without a GPU.

    python scripts/verify/test-arms.py
    python scripts/verify/test-arms.py --only resume --keep
    python scripts/verify/test-arms.py --jobs 1        # strictly serial

WHY THIS EXISTS. On 2026-08-29 this repository found three bugs, and paid for
every one of them in GPU hours:

  * RLIMIT_AS aborted EVERY arm on Linux. gpu_lock capped the child's ADDRESS
    SPACE at 75% of RAM; CUDA reserves tens of GB of address space whatever it
    uses, so a 3.6 GB model that loads fine unguarded died with SIGABRT.
  * --resume marked a retried arm failed forever. read_ledger set failed=True
    stickily, so an arm that failed once and SUCCEEDED on the rerun was skipped
    as failed on the next resume - and its measurements were never counted.
  * 33 probes called main() at module level, so probe-smoke-test.py - the CHEAP
    pre-check - ran real GPU jobs when it imported them, once orphaning a
    llama-perplexity holding 13.79 GB.

All three are findable in seconds against a server that has no weights. This
lane is that: real arms.py subprocesses, a real ledger, a real heartbeat, and
scripts/verify/fake-llama-server.py standing in for llama-server.

WHAT EACH TEST PROTECTS, by the rule it belongs to:

  clean-sweep        one ledger line per probe, each carrying t_start_iso and
                     label - the fields scripts/power/attribute-power.py joins
                     energy on, and rule 28 says a field not written during the
                     run cannot be recovered at any price
  heartbeat          rule 20: where is it now, and does it say "finished"
  resume-skips       --resume costs at most the arm in flight
  resume-after-retry THE 2026-08-29 BUG. An arm that failed and then succeeded
                     is complete, not failed. Written so it fails against the
                     old sticky-failed read_ledger.
  discard-first      rule 12: the ramp probe is dropped from the summary and
                     STILL written to the ledger
  parse-check        rule 25: a server that does not report the timings the
                     ledger is built on stops the sweep at the FIRST probe,
                     before the other arms cost anything
  failed-arm-continues  an arm that will not load is a result; the sweep
                     records it and goes to the next arm
  alternate-order    rule 30: the order reverses on the second pass, and the
                     order actually used is on every line
  truncation-notice  rule 7: finish_reason=length is a condition, reported
  save-responses     rule 28 again, on the one artifact that cannot be
                     recovered at any price: the generated TEXT is written
                     beside the ledger BY DEFAULT, named so it joins back to
                     its arm/pass/probe, and its bytes are the characters the
                     ledger counted. Two zero-byte accept-*.txt files under
                     results/qwen38-27b-blind/data/ are what its absence
                     looked like
  address-space-reservation  a server that reserves 32 GB of address space and
                     commits none of it still runs - the RLIMIT_AS shape
  plan-rungs         an arm file takes its -c ladder from the campaign plan
                     rather than hardcoding one, and every ledger line says
                     which rung of which plan produced it (rules 3 and 28)
  plan-missing-is-fatal  THE HARDCODED-LADDER BUG. An arm file that names a
                     rung source and finds no plan.json launches nothing,
                     writes nothing and names the command that writes one.
                     A silent fallback is how a 27B's ladder gets run against
                     a 1.7B whose whole window is below its bottom rung

HOW THE STUB PASSES paths.llama_bin(). That resolver does not merely check
that a candidate exists: _unusable() rejects a file that is not executable on
POSIX, and rejects an ELF on Windows or a PE on POSIX. A .py file is neither
ELF nor PE, so the sandbox writes a one-line PLATFORM-NATIVE SHIM beside it -
llama-server.cmd on Windows, an exec'd /bin/sh script chmod 755 elsewhere -
and points $LLAMA_SERVER at that. Both pass _unusable for the right reason
rather than by luck, and resolver-accepts-stub asserts it rather than assuming
it. The Windows shim costs one thing: terminating it kills cmd.exe and leaves
the stub listening (measured: alive 5.00 s after terminate), which is exactly
the leftover server that would answer the next arm's probes - so the stub
watches its parent and exits with it (measured: gone in 0.25 s).

WHY A MIRRORED REPO. Each test runs arms.py from a COPY of the three files it
needs (arms.py, lib/paths.py, bench/gpu_lock.py) inside a temp directory, and
copies them fresh every run so nothing can go stale. That is not squeamishness:
arms.py writes its ledger to <repo>/results/<slug>/data/arms/, its heartbeat to
<repo>/results/<slug>/work/, and gpu_lock takes <repo>/.gpu-lock.json - the
MACHINE-WIDE one-job lock. A lane that ran in place would scribble on a real
campaign's ledger and could take the lock out from under a live sweep. In the
mirror, repo_root() and LOCK_PATH both resolve inside the temp directory.

WHAT THIS DOES NOT CHECK. That llama-server behaves the way the stub does -
the stub is a fixture, not evidence about llama.cpp - and nothing about
numbers being correct. It answers one question: given a server that responds,
does the runner record, resume, discard, order and stop the way the rules
require? Stdlib only, no pip, no GPU, no model file.
"""

import argparse
import json
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STUB = os.path.join(REPO, "scripts", "verify", "fake-llama-server.py")

# The three files arms.py needs to run. Copied, never imported from the repo:
# see WHY A MIRRORED REPO above.
MIRROR = ("scripts/arms.py", "scripts/lib/paths.py", "scripts/bench/gpu_lock.py")

SLUG = "lane-campaign"
MODEL_NAME = "lane-model.gguf"
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

# arms.py:203 - the fields the ledger is built on.
REQUIRED_TIMINGS = ("prompt_n", "predicted_n", "prompt_ms", "predicted_ms",
                    "predicted_per_second")


class Failure(Exception):
    """One assertion in one test."""


def need(cond, msg):
    if not cond:
        raise Failure(msg)


def free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def port_open(port, timeout_s=0.25):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout_s)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False
    finally:
        s.close()


def http_json(url, payload=None, timeout_s=10):
    """(status, parsed body). Stdlib only - the lane may not assume requests."""
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except ValueError:
            return e.code, {}


def nominal_prompt_n(text, chars_per_token=4):
    """What the stub will report for this prompt: ceil(chars / 4), never 0."""
    return max(1, int(math.ceil(len(text) / float(chars_per_token))))


# ---------------------------------------------------------------------------
# The sandbox: a repo-shaped temp directory arms.py can be run inside
# ---------------------------------------------------------------------------

class Sandbox(object):

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="arms-lane-")
        self.runs = 0
        for rel in MIRROR:
            dst = os.path.join(self.root, *rel.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(os.path.join(REPO, *rel.split("/")), dst)

        self.models_dir = os.path.join(self.root, "models")
        os.makedirs(self.models_dir, exist_ok=True)
        self.model = os.path.join(self.models_dir, MODEL_NAME)
        # Never opened by anything: the stub echoes -m and reads no weights.
        with open(self.model, "wb") as fh:
            fh.write(b"GGUF\x00\x00\x00\x03not a model, and never read\n")

        camp = os.path.join(self.root, "results", SLUG)
        os.makedirs(camp, exist_ok=True)
        self.write_file(os.path.join(camp, "campaign.json"), json.dumps({
            "slug": SLUG, "model_dir": self.models_dir,
            "models": [self.model]}, indent=2))
        # Fabricated, and inert: nothing in this lane reads the card. It is
        # here because arms.py copies machine.json into every sweep_start line
        # (rule 3, the conditions travel with the numbers) and the clean-sweep
        # test asserts that it did.
        self.write_file(os.path.join(camp, "machine.json"), json.dumps({
            "board_total_mib": 24576,
            "desktop_reserve_mib": {"min": 412, "max": 1796, "n": 9,
                                    "date": "2026-08-27"},
            "note": "FIXTURE - written by scripts/verify/test-arms.py, "
                    "measured on nothing"}, indent=2))

        self.launcher = self._write_launcher()
        self.launch_log = os.path.join(self.root, "launches.jsonl")
        self.arm_dir = os.path.join(self.root, "arms")
        os.makedirs(self.arm_dir, exist_ok=True)

        self.env = dict(os.environ)
        # arms.py REFUSES to run with this set and --dry-run absent, and the
        # smoke test exports it. The lane wants a real launch, so it goes.
        self.env.pop("MEASURED_INFERENCE_DRY_RUN", None)
        self.env["LLAMA_SERVER"] = self.launcher
        self.env["MODEL_DIR"] = self.models_dir
        self.env["MEASURED_INFERENCE_SLUG"] = SLUG
        # The machine-wide lock, pinned inside the sandbox. gpu_lock would
        # already resolve it here from the mirrored file's own location; saying
        # so out loud means a future change to that derivation cannot make this
        # lane reach for a live campaign's lock.
        self.env["MEASURED_INFERENCE_LOCK"] = os.path.join(self.root,
                                                           ".gpu-lock.json")
        # gpu_lock.preflight() refuses to launch when the job's commit cap
        # would not fit in the headroom left. The default cap is 0.75 x RAM,
        # which is right for a 27B model and absurd for a python stub; 2 GB
        # keeps the guard live without making a busy desktop fail the lane.
        self.env["MEASURED_INFERENCE_MEM_CAP_GB"] = "2"
        self.env["PYTHONIOENCODING"] = "utf-8"

    # -- construction helpers ------------------------------------------------

    @staticmethod
    def write_file(path, text):
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        return path

    def _write_launcher(self):
        """A shim paths._unusable() accepts on this platform. See the header."""
        bindir = os.path.join(self.root, "bin")
        os.makedirs(bindir, exist_ok=True)
        if os.name == "nt":
            # CreateProcess runs a .cmd through cmd.exe; a .py file it cannot
            # run at all. Magic bytes are '@"C:' - not ELF - so _unusable()
            # passes it.
            path = os.path.join(bindir, "llama-server.cmd")
            self.write_file(path, '@"%s" "%s" %%*\n' % (sys.executable, STUB))
        else:
            # exec, so the stub IS the child arms.py holds: terminate() reaches
            # it directly. Magic bytes are '#!/b' - not MZ - and 0755 satisfies
            # _unusable()'s os.access(X_OK) check.
            path = os.path.join(bindir, "llama-server")
            self.write_file(path, '#!/bin/sh\nexec "%s" "%s" "$@"\n'
                        % (sys.executable, STUB))
            os.chmod(path, 0o755)
        return path

    def plan_path(self):
        return os.path.join(self.root, "results", SLUG, "plan.json")

    def write_plan(self, per_file, **extra):
        """A results/<slug>/plan.json in the shape scripts/plan-campaign.py
        writes: slug, machine, and rungs.per_file[] each carrying a rungs[]
        list of {c, zone, deep_fill_tokens, above_predicted_ceiling}.

        A FIXTURE, and only a fixture: it proves what arms.py does with a
        plan, never that plan-campaign.py's arithmetic is right. The rung
        VALUES here are small enough for a stub to load instantly and are not
        anybody's real ceiling.
        """
        plan = {"slug": SLUG,
                "generated_utc": "2026-08-29T00:00:00Z",
                "generated_by": "scripts/plan-campaign.py",
                "cache_type": "q8_0", "c_min": 1024,
                "machine": {"board_total_mib": 24576, "budget_mib": 22780},
                "rungs": {"step_rule": "FIXTURE - test-arms.py wrote this",
                          "cache_type": "q8_0", "per_file": per_file},
                "verdict": "VERDICT: PLANNED (fixture)", "exit_code": 0}
        plan.update(extra)
        return self.write_file(self.plan_path(), json.dumps(plan, indent=1))

    @staticmethod
    def rung_record(label, cs, ceiling, window, zones=None, why="fixture"):
        zones = list(zones or ["dense"] * len(cs))
        return {"file": label, "cache_type": "q8_0",
                "predicted_ceiling": ceiling,
                "predicted_ceiling_drafter_off": ceiling,
                "model_context_length": window, "quantum": 1024,
                "top": max(cs), "why": why, "collapse_point_reachable": True,
                "rungs": [{"c": c, "zone": z,
                           "deep_fill_tokens": int(c * 0.9),
                           "above_predicted_ceiling": c > ceiling}
                          for c, z in zip(cs, zones)]}

    def arm_file(self, stem, arms, port, order="alternate", defaults=None):
        """Write an arm file. Stub flags shared by every arm live in defaults."""
        base = {
            "repeat": 1, "discard_first": False,
            "host": "127.0.0.1", "port": port,
            "stop_grace_s": 0, "settle_s": 0,
            "health_timeout_s": 20, "request_timeout_s": 60,
            "sampling": {"temperature": 0, "top_k": 1},
            "probe": {"n_predict": 48},
            "server": {"flags": [
                "-ngl", "99", "-c", "4096",          # keeps arm_warnings quiet
                "--launch-log", self.launch_log,
                "--max-life", "120"]},
        }
        base.update(defaults or {})
        spec = {"name": "lane " + stem, "slug": SLUG, "order": order,
                "models": [MODEL_NAME], "defaults": base, "arms": arms}
        return self.write_file(os.path.join(self.arm_dir, stem + ".json"),
                           json.dumps(spec, indent=2))

    @staticmethod
    def arm(arm_id, flags=(), probes=None, **extra):
        a = {"id": arm_id, "sweep": "lane",
             "server": {"model": MODEL_NAME, "flags": list(flags)},
             "probes": list(probes or [{"id": "p1", "prompt": "lane probe"}])}
        a.update(extra)
        return a

    # -- running -------------------------------------------------------------

    def popen(self, *args):
        """arms.py, output to a file so a watcher cannot deadlock the pipe."""
        self.runs += 1
        log = os.path.join(self.root, "run%d.log" % self.runs)
        fh = open(log, "w", encoding="utf-8", errors="replace")
        cmd = [sys.executable, os.path.join(self.root, "scripts", "arms.py")]
        cmd += [str(a) for a in args]
        proc = subprocess.Popen(cmd, cwd=self.root, env=self.env,
                                stdout=fh, stderr=subprocess.STDOUT)
        proc._lane_log = log
        proc._lane_fh = fh
        return proc

    def wait(self, proc, timeout_s=180):
        try:
            proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=30)
            raise Failure("arms.py did not finish in %d s" % timeout_s)
        finally:
            proc._lane_fh.close()
        out = open(proc._lane_log, encoding="utf-8", errors="replace").read()
        if "cannot start:" in out:
            raise Failure(
                "gpu_lock refused to start this sweep - the lane cannot run "
                "while another GPU job or a foreign llama-server holds the "
                "machine, and neither can a real sweep:\n%s"
                % out[out.index("cannot start:"):][:400])
        return proc.returncode, out

    def run(self, *args, **kw):
        return self.wait(self.popen(*args), **kw)

    # -- reading what it wrote ----------------------------------------------

    def ledger(self, stem):
        path = os.path.join(self.root, "results", SLUG, "data", "arms",
                            stem + ".jsonl")
        if not os.path.exists(path):
            raise Failure("no ledger at %s - arms.py wrote nothing" % path)
        out = []
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    out.append(json.loads(line))
        return out

    def probes(self, stem):
        return [r for r in self.ledger(stem) if r.get("kind") == "probe"]

    def responses_dir(self, stem):
        return os.path.join(self.root, "results", SLUG, "data", "arms",
                            stem + "-responses")

    def heartbeat_path(self):
        return os.path.join(self.root, "results", SLUG, "work",
                            "heartbeat.json")

    def heartbeat(self):
        """The heartbeat, or None. Tolerates the atomic replace mid-read."""
        try:
            with open(self.heartbeat_path(), encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    def server_log(self, stem, arm_id, rep=1):
        path = os.path.join(self.root, "results", SLUG, "work", "arms", stem,
                            "%s-rep%d.log" % (arm_id, rep))
        if not os.path.exists(path):
            raise Failure("no server log at %s" % path)
        return open(path, encoding="utf-8", errors="replace").read()

    def launches(self):
        if not os.path.exists(self.launch_log):
            return []
        with open(self.launch_log, encoding="utf-8") as fh:
            return [json.loads(ln) for ln in fh if ln.strip()]

    def cleanup(self):
        for _ in range(5):
            shutil.rmtree(self.root, ignore_errors=True)
            if not os.path.isdir(self.root):
                return
            time.sleep(0.2)


# ---------------------------------------------------------------------------
# Shared assertions
# ---------------------------------------------------------------------------

def assert_timings_complete(rec, where):
    t = rec.get("timings") or {}
    for field in REQUIRED_TIMINGS:
        need(t.get(field) is not None,
             "%s: timings.%s missing - the ledger is built on it (rule 25)"
             % (where, field))


def assert_energy_join(rec, where):
    """rule 28: the fields attribute-power.py joins a sweep to its watts on."""
    need(ISO_RE.match(rec.get("t_start_iso") or ""),
         "%s: t_start_iso is %r, not an ISO-Z instant - the energy join has no "
         "request start and cannot be recovered later (rule 28)"
         % (where, rec.get("t_start_iso")))
    want = "%s/%s" % (rec.get("arm"), rec.get("probe"))
    need(rec.get("label") == want,
         "%s: label is %r, expected %r" % (where, rec.get("label"), want))


# ---------------------------------------------------------------------------
# The tests
# ---------------------------------------------------------------------------

def t_resolver_accepts_stub(sb):
    """paths.llama_bin() must ACCEPT the shim, not merely find it.

    _unusable() rejects a non-executable file, an ELF on Windows and a PE on
    POSIX. If this fails, every other test fails for a reason that has nothing
    to do with arms.py, so it is asked first and asked directly.
    """
    code = ("import sys, os;"
            "sys.path.insert(0, os.path.join(sys.argv[1], 'scripts'));"
            "from lib import paths;"
            "print(paths.llama_bin('llama-server'))")
    p = subprocess.run([sys.executable, "-c", code, sb.root],
                       cwd=sb.root, env=sb.env, capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       timeout=60)
    need(p.returncode == 0,
         "paths.llama_bin() refused the stub shim:\n%s" % (p.stderr or "")[-600:])
    got = (p.stdout or "").strip()
    need(os.path.normcase(got) == os.path.normcase(sb.launcher),
         "llama_bin resolved %r, expected the shim %r" % (got, sb.launcher))
    return "llama_bin() accepts %s" % os.path.basename(sb.launcher)


def t_stub_contract(sb):
    """The stub answers /health, /props and a completion, and leaves no orphan.

    Driven directly, with no arms.py in the way: if the fixture is wrong, every
    assertion downstream is measuring the fixture.
    """
    port = free_port()
    proc = subprocess.Popen(
        [sb.launcher, "-m", sb.model, "--host", "127.0.0.1", "--port",
         str(port), "--ready-after", "1", "--draft-accept", "0.9",
         "--max-life", "60",
         # a flag list of the shape a real arm carries, all of it unknown
         "-ngl", "99", "-c", "4096", "--jinja", "--spec-type", "draft-mtp",
         "-md", "draft-model.gguf"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        saw_loading = False
        deadline = time.time() + 20
        status = None
        while time.time() < deadline:
            try:
                code, body = http_json("http://127.0.0.1:%d/health" % port,
                                       timeout_s=2)
            except (urllib.error.URLError, OSError):
                time.sleep(0.05)
                continue
            status = body.get("status")
            if code == 503:
                saw_loading = True
            if status == "ok":
                break
            time.sleep(0.05)
        need(status == "ok", "the stub never became healthy (last: %r)" % status)
        need(saw_loading,
             "--ready-after 1 never reported a loading state, so the health "
             "poll and its timeout path are untested")

        code, props = http_json("http://127.0.0.1:%d/props" % port)
        need(code == 200 and props.get("model_path") == sb.model,
             "/props reported model_path %r, expected %r"
             % (props.get("model_path"), sb.model))
        ignored = props.get("fake_llama_server", {}).get("ignored_flags") or []
        need("-md" in ignored and "draft-model.gguf" in ignored,
             "-md was not ignored as an unknown flag: %r. argparse would have "
             "read it as -m with the value 'd' and served the wrong model."
             % ignored)

        prompt = "count the tokens in this prompt, please" * 3
        code, resp = http_json(
            "http://127.0.0.1:%d/v1/chat/completions" % port,
            {"messages": [{"role": "user", "content": prompt}],
             "max_tokens": 37, "temperature": 0, "stream": False})
        need(code == 200, "chat completion returned HTTP %s" % code)
        choice = (resp.get("choices") or [{}])[0]
        need((choice.get("message") or {}).get("content"),
             "no choices[0].message.content in the response")
        need(choice.get("finish_reason") == "stop",
             "finish_reason %r" % choice.get("finish_reason"))
        need(isinstance(resp.get("usage"), dict), "no usage block")
        t = resp.get("timings") or {}
        for field in REQUIRED_TIMINGS:
            need(t.get(field) is not None, "timings.%s missing" % field)
        need(t["prompt_n"] == nominal_prompt_n(prompt),
             "prompt_n %s, expected %s from a %d-char prompt"
             % (t["prompt_n"], nominal_prompt_n(prompt), len(prompt)))
        need(t["predicted_n"] == 37,
             "predicted_n %s, expected the 37 max_tokens asked for"
             % t["predicted_n"])
        need(t.get("draft_n") and t.get("draft_n_accepted"),
             "--draft-accept produced no rule-11 drafting pair: %r" % t)
    finally:
        proc.terminate()
        proc.wait(timeout=30)
    # The Windows shim dies before its child does; the stub's parent watch is
    # what stops a leftover server from answering the next arm's probes.
    for _ in range(40):
        if not port_open(port):
            break
        time.sleep(0.25)
    need(not port_open(port),
         "port %d was still serving 10 s after the launcher was terminated - "
         "an orphan like that answers the NEXT arm and the ledger records its "
         "numbers under the wrong flags" % port)
    return "health/props/completion answer, nothing orphaned"


def t_clean_sweep(sb):
    """Two arms, four probes: one ledger line each, with the energy fields."""
    port = free_port()
    pa, pb = "arm a asks this", "arm b asks a somewhat longer question than a"
    arms = [
        sb.arm("arm-a", probes=[{"id": "p1", "prompt": pa, "n_predict": 48},
                                {"id": "p2", "prompt": pa + "!", "n_predict": 32}]),
        sb.arm("arm-b", probes=[{"id": "p1", "prompt": pb, "n_predict": 48},
                                {"id": "p2", "prompt": pb + "?", "n_predict": 32}]),
    ]
    f = sb.arm_file("clean", arms, port)

    # watch the heartbeat WHILE it runs (rule 20)
    proc = sb.popen("--arms", f, "--slug", SLUG)
    seen = []
    while proc.poll() is None:
        rec = sb.heartbeat()
        if rec:
            seen.append(rec)
        time.sleep(0.05)
    rc, out = sb.wait(proc)
    need(rc == 0, "clean sweep exited %d:\n%s" % (rc, out[-1200:]))

    live = [r for r in seen if r.get("state") != "finished"]
    need(live, "heartbeat.json never showed a live state during the run - an "
               "agent resuming after a session loss reads it instead of three "
               "thousand log lines (rule 20)")
    need(live[-1].get("pid") == proc.pid,
         "heartbeat pid %r is not the running sweep's %d"
         % (live[-1].get("pid"), proc.pid))
    need(live[-1].get("arm") in ("arm-a", "arm-b"),
         "heartbeat named arm %r" % live[-1].get("arm"))
    final = sb.heartbeat()
    need(final and final.get("state") == "finished",
         "heartbeat state at the end is %r, not 'finished'"
         % (final or {}).get("state"))
    need(final["done"] == final["total"] == 4,
         "heartbeat finished at %s/%s of 4 probes"
         % (final.get("done"), final.get("total")))

    recs = sb.probes("clean")
    need(len(recs) == 4, "expected 4 probe lines, got %d" % len(recs))
    need([(r["arm"], r["probe"]) for r in recs] ==
         [("arm-a", "p1"), ("arm-a", "p2"), ("arm-b", "p1"), ("arm-b", "p2")],
         "probe lines are %r" % [(r["arm"], r["probe"]) for r in recs])
    prompts = {("arm-a", "p1"): pa, ("arm-a", "p2"): pa + "!",
               ("arm-b", "p1"): pb, ("arm-b", "p2"): pb + "?"}
    for r in recs:
        where = "%s/%s" % (r["arm"], r["probe"])
        assert_timings_complete(r, where)
        assert_energy_join(r, where)
        need(r["discarded"] is False, "%s: discarded %r" % (where, r["discarded"]))
        need(r["truncated"] is False and r["finish_reason"] == "stop",
             "%s: finish_reason %r" % (where, r["finish_reason"]))
        need(isinstance(r.get("usage"), dict), "%s: no usage block" % where)
        text = prompts[(r["arm"], r["probe"])]
        need(r["prompt_chars"] == len(text),
             "%s: prompt_chars %s, prompt is %d chars"
             % (where, r["prompt_chars"], len(text)))
        need(r["timings"]["prompt_n"] == nominal_prompt_n(text),
             "%s: recorded prompt_n %s for a prompt worth %s - the runner did "
             "not record the prompt it actually sent"
             % (where, r["timings"]["prompt_n"], nominal_prompt_n(text)))
        need(r["timings"]["predicted_n"] == r["n_predict"],
             "%s: asked for n_predict %s, recorded predicted_n %s"
             % (where, r["n_predict"], r["timings"]["predicted_n"]))
        need(r["request"].get("max_tokens") == r["n_predict"],
             "%s: the recorded request does not carry the cap" % where)

    start = [r for r in sb.ledger("clean") if r.get("kind") == "sweep_start"][0]
    need((start.get("machine") or {}).get("board_total_mib") == 24576,
         "sweep_start carries no machine block - rule 3's conditions have to "
         "travel in the same file as the numbers")
    launches = sb.launches()
    need(len(launches) == 2, "expected 2 server launches, got %d" % len(launches))
    for rec in launches:
        need(rec["model"] == sb.model,
             "a server was launched with model %r, not the resolved %r"
             % (rec["model"], sb.model))
        need(rec["port"] == port, "server launched on port %s" % rec["port"])
    return "4 probe lines, t_start_iso + label on each, heartbeat finished"


def t_resume_skips(sb):
    """--resume costs at most the arm in flight."""
    port = free_port()
    arms = [sb.arm("arm-a"), sb.arm("arm-b")]
    f = sb.arm_file("resume", arms, port)
    rc, out = sb.run("--arms", f, "--slug", SLUG)
    need(rc == 0, "first pass exited %d:\n%s" % (rc, out[-1200:]))
    need(len(sb.probes("resume")) == 2, "first pass wrote %d probe lines"
         % len(sb.probes("resume")))
    n_launches = len(sb.launches())

    rc, out = sb.run("--arms", f, "--slug", SLUG, "--resume")
    need(rc == 0, "resume exited %d:\n%s" % (rc, out[-1200:]))
    need(out.count("SKIPPED, already complete") == 2,
         "expected both units skipped as complete, output was:\n%s" % out[-1200:])
    need(len(sb.probes("resume")) == 2,
         "resume re-recorded probes: %d lines now" % len(sb.probes("resume")))
    need(len(sb.launches()) == n_launches,
         "resume launched a server for a unit the ledger already had")
    return "both completed units skipped, nothing relaunched"


def t_resume_after_retry(sb):
    """THE 2026-08-29 BUG: a failed arm that later SUCCEEDED is not failed.

    The arm file never changes - so its spec hash never changes - and the
    injected failure is switched off by deleting a file the stub looks for.
    Against the old sticky read_ledger the third run printed "SKIPPED, the
    ledger records it FAILED", counted the arm as failed and exited 1, and the
    measurements from run 2 were never counted.
    """
    port = free_port()
    trigger = os.path.join(sb.root, "make-it-fail")
    sb.write_file(trigger, "delete me and the arm loads\n")
    arms = [sb.arm("flaky", flags=["--fail-if-exists", trigger])]
    f = sb.arm_file("retry", arms, port)

    rc, out = sb.run("--arms", f, "--slug", SLUG)
    need(rc == 1, "the injected failure did not fail the arm (exit %d):\n%s"
         % (rc, out[-1200:]))
    failed = [r for r in sb.ledger("retry") if r.get("kind") == "arm_failed"]
    need(len(failed) == 1, "expected one arm_failed line, got %d" % len(failed))
    need(not sb.probes("retry"), "a failed arm wrote a probe line")

    os.remove(trigger)
    rc, out = sb.run("--arms", f, "--slug", SLUG)
    need(rc == 0, "the retry did not succeed (exit %d):\n%s" % (rc, out[-1200:]))
    need(len(sb.probes("retry")) == 1,
         "the retry wrote %d probe lines" % len(sb.probes("retry")))
    need(failed[0]["spec_sha"] == sb.probes("retry")[0]["spec_sha"],
         "the arm spec changed between the failure and the retry, so this "
         "test would pass for the wrong reason")

    rc, out = sb.run("--arms", f, "--slug", SLUG, "--resume")
    need("records it FAILED" not in out,
         "STICKY FAILED: --resume skipped an arm that failed once and "
         "SUCCEEDED on the rerun. Its measurements are in the ledger and the "
         "runner refuses to count them. Output:\n%s" % out[-1200:])
    need("SKIPPED, already complete" in out,
         "resume did not treat the retried arm as complete:\n%s" % out[-1200:])
    need(rc == 0, "resume after a successful retry exited %d, so the sweep "
                  "reports a failure that has already been fixed" % rc)
    need(len(sb.probes("retry")) == 1,
         "resume reran a completed arm: %d probe lines"
         % len(sb.probes("retry")))
    return "failed-then-succeeded arm resumes as complete, not as failed"


def t_discard_first(sb):
    """rule 12: the ramp probe is discarded from the summary AND written."""
    port = free_port()
    arms = [sb.arm("ramp", flags=["--slow-first-probe"],
                   probes=[{"id": "ramp-probe", "prompt": "first, cold"},
                           {"id": "kept-probe", "prompt": "second, warm"}],
                   discard_first=True)]
    f = sb.arm_file("discard", arms, port)
    rc, out = sb.run("--arms", f, "--slug", SLUG)
    need(rc == 0, "sweep exited %d:\n%s" % (rc, out[-1200:]))

    recs = sb.probes("discard")
    need(len(recs) == 2,
         "the discarded probe must STILL be written (rule 12): %d lines"
         % len(recs))
    need(recs[0]["discarded"] is True and recs[0]["probe"] == "ramp-probe",
         "the first probe is not flagged discarded: %r"
         % [(r["probe"], r["discarded"]) for r in recs])
    need(recs[1]["discarded"] is False,
         "the second probe was discarded too: %r" % recs[1]["discarded"])
    slow = recs[0]["timings"]["predicted_per_second"]
    fast = recs[1]["timings"]["predicted_per_second"]
    need(slow < fast,
         "the ramp probe did not read low (%.2f vs %.2f t/s), so this test "
         "proves nothing about why rule 12 exists" % (slow, fast))
    need("[DISCARDED, rule 12]" in out, "the run never said it discarded one")
    need("(1 discarded)" in out,
         "the summary does not report the discard:\n%s" % out[-800:])
    need("%.2f" % fast in out and "%.2f" % ((slow + fast) / 2) not in out,
         "the summary averaged the discarded probe in - the whole point of "
         "rule 12 is that it does not")
    return "ramp probe written, flagged, and kept out of the mean"


def t_parse_check_stops_the_sweep(sb):
    """rule 25: a missing timings field stops the sweep at the FIRST probe."""
    port = free_port()
    arms = [sb.arm("arm-broken",
                   flags=["--drop-timings", "predicted_per_second"]),
            sb.arm("arm-never-runs")]
    f = sb.arm_file("parsecheck", arms, port)
    rc, out = sb.run("--arms", f, "--slug", SLUG)
    need(rc == 2, "expected exit 2 from the parse check, got %d:\n%s"
         % (rc, out[-1200:]))
    need("PARSE CHECK FAILED" in out, "the run did not say why it stopped")

    led = sb.ledger("parsecheck")
    bad = [r for r in led if r.get("kind") == "parse_check_failed"]
    need(len(bad) == 1, "expected one parse_check_failed line, got %d" % len(bad))
    need(any("predicted_per_second" in p for p in bad[0]["problems"]),
         "the failure does not name the missing field: %r" % bad[0]["problems"])
    need(not any(r.get("arm") == "arm-never-runs" for r in led),
         "the second arm ran anyway - rule 25 buys the map with ONE cheap "
         "probe, before the expensive part")
    need(len(sb.launches()) == 1,
         "%d servers were launched; the second arm must never load"
         % len(sb.launches()))
    return "stopped on probe 1, second arm never launched"


def t_failed_arm_continues(sb):
    """An arm that will not load is a result, not a reason to stop."""
    port = free_port()
    arms = [sb.arm("arm-dies", flags=["--die-on-start", "--exit-code", "3"]),
            sb.arm("arm-hangs", flags=["--hang"], health_timeout_s=3),
            sb.arm("arm-ok")]
    f = sb.arm_file("failures", arms, port)
    rc, out = sb.run("--arms", f, "--slug", SLUG)
    need(rc == 1, "expected exit 1 (arms failed, sweep completed), got %d:\n%s"
         % (rc, out[-1500:]))

    led = sb.ledger("failures")
    failed = {r["arm"]: r for r in led if r.get("kind") == "arm_failed"}
    need(set(failed) == {"arm-dies", "arm-hangs"},
         "arm_failed lines for %r" % sorted(failed))
    need("exited with code 3" in failed["arm-dies"]["error"],
         "the exit code is not in the record: %r" % failed["arm-dies"]["error"])
    tail = " ".join(failed["arm-dies"].get("server_log_tail") or [])
    need("injected failure" in tail,
         "the server's own last words were not captured: %r" % tail[-200:])
    need("did not become healthy in 3 s" in failed["arm-hangs"]["error"],
         "the health timeout is not recorded: %r" % failed["arm-hangs"]["error"])

    ok = sb.probes("failures")
    need(len(ok) == 1 and ok[0]["arm"] == "arm-ok",
         "the sweep did not continue to the arm after the failures: %r"
         % [(r["arm"], r["probe"]) for r in ok])
    assert_timings_complete(ok[0], "arm-ok/p1")
    need(out.count("ARM FAILED") == 2, "expected two ARM FAILED notices")
    need("FAILED arms: arm-dies/pass1, arm-hangs/pass1" in out,
         "the summary does not name both failed arms:\n%s" % out[-600:])
    return "two arms failed (exit + health timeout), the third still ran"


def t_alternate_order(sb):
    """rule 30: pass 2 runs the group backwards, and the order is recorded."""
    port = free_port()
    arms = [sb.arm("arm-first", repeat=2), sb.arm("arm-second", repeat=2)]
    f = sb.arm_file("order", arms, port, order="alternate")
    rc, out = sb.run("--arms", f, "--slug", SLUG)
    need(rc == 0, "sweep exited %d:\n%s" % (rc, out[-1200:]))

    recs = sb.probes("order")
    need(len(recs) == 4, "expected 4 probe lines, got %d" % len(recs))
    ran = [(r["rep"], r["arm"]) for r in recs]
    need(ran == [(1, "arm-first"), (1, "arm-second"),
                 (2, "arm-second"), (2, "arm-first")],
         "the second pass did not reverse: %r - an arm's POSITION can then "
         "masquerade as a property of the arm (rule 30)" % ran)
    for r in recs:
        need(r["order_mode"] == "alternate", "order_mode %r" % r["order_mode"])
        want = (["arm-first", "arm-second"] if r["rep"] == 1
                else ["arm-second", "arm-first"])
        need(r["order"] == want,
             "pass %d line records order %r, expected %r"
             % (r["rep"], r["order"], want))
        need(r["order"][r["pos"]] == r["arm"],
             "pos %d does not point at %s in %r"
             % (r["pos"], r["arm"], r["order"]))
    plan = [r for r in sb.ledger("order")
            if r.get("kind") == "sweep_start"][0]["plan"]
    need([p["order"] for p in plan] == [["arm-first", "arm-second"],
                                        ["arm-second", "arm-first"]],
         "the sweep_start plan does not carry both passes: %r" % plan)
    return "pass 2 reversed, and every line carries the order it ran in"


def t_address_space_reservation(sb):
    """A server that reserves 32 GB of ADDRESS SPACE must still run.

    THE 2026-08-29 LINUX BUG, in the only form a stub can honestly carry it.
    gpu_lock capped the child's RLIMIT_AS at a fraction of RAM. RLIMIT_AS caps
    ADDRESS SPACE, and a CUDA process reserves tens of GB of it whatever it
    uses, so a 3.6 GB model that loaded fine unguarded died with SIGABRT and
    every GPU arm on Linux failed.

    This test is platform-honest rather than platform-specific: the stub
    reserves without committing on both, and only a guard that counts the
    wrong thing fails it. On Linux with MEASURED_INFERENCE_RLIMIT_AS=1 - the
    variable that turns the old behaviour back on - it fails, which is the
    proof it discriminates. On Windows the job object counts committed pages,
    so it passes, which is exactly why Windows was unaffected.
    """
    port = free_port()
    arms = [sb.arm("cuda-shaped", flags=["--reserve-va", "32"])]
    f = sb.arm_file("addrspace", arms, port)
    rc, out = sb.run("--arms", f, "--slug", SLUG)
    log = ""
    try:
        log = sb.server_log("addrspace", "cuda-shaped")
    except Failure:
        pass
    need(rc == 0,
         "a server that reserved 32 GB of address space (and committed none "
         "of it) could not run this arm - that is the RLIMIT_AS shape: an "
         "address-space cap is not a memory cap, and every CUDA process "
         "reserves in bulk. exit %d\n%s\n--- server log ---\n%s"
         % (rc, out[-800:], log[-500:]))
    recs = sb.probes("addrspace")
    need(len(recs) == 1, "expected one probe line, got %d" % len(recs))
    need("reserved 32.0 GB of address space" in log,
         "the stub did not report the reservation, so this test proved "
         "nothing:\n%s" % log[-500:])
    return "32 GB reserved, 0 committed, arm still ran"


def t_truncation_notice(sb):
    """rule 7: a truncation is a condition, recorded and said out loud."""
    port = free_port()
    arms = [sb.arm("capped", flags=["--truncate"],
                   probes=[{"id": "p1", "prompt": "write until the cap",
                            "n_predict": 24}])]
    f = sb.arm_file("truncate", arms, port)
    rc, out = sb.run("--arms", f, "--slug", SLUG)
    need(rc == 0, "a truncation is not a failure; exit was %d" % rc)
    rec = sb.probes("truncate")[0]
    need(rec["finish_reason"] == "length" and rec["truncated"] is True,
         "the record does not carry the truncation: finish_reason %r, "
         "truncated %r" % (rec["finish_reason"], rec["truncated"]))
    need("finish_reason=length" in out and "raise the cap" in out,
         "the run did not print the rule-7 notice:\n%s" % out[-600:])
    return "finish_reason=length recorded and reported"


def t_save_responses(sb):
    """rule 28: the generated TEXT is kept, joined to its line, and by default.

    response_chars alone can say how much was generated and nothing about
    what. Stage 4's appetite count, Stage 6b's blind judging, rule 20's
    repetition spot-read and any max-coherent-output column all read the body,
    and the body cannot be recovered after the server stops. So this asserts
    three things: saving happens with NO flag asked for, the file joins back to
    its ledger line by name and by path, and its bytes are exactly the
    characters the ledger counted.
    """
    port = free_port()
    arms = [sb.arm("arm-a", probes=[{"id": "p1", "prompt": "say something",
                                     "n_predict": 48},
                                    {"id": "p2", "prompt": "say more",
                                     "n_predict": 32}])]
    f = sb.arm_file("saved", arms, port)
    rc, out = sb.run("--arms", f, "--slug", SLUG)       # no flag: the DEFAULT
    need(rc == 0, "sweep exited %d:\n%s" % (rc, out[-1200:]))

    ddir = sb.responses_dir("saved")
    need(os.path.isdir(ddir),
         "no responses directory at %s - the run kept response_chars and threw "
         "the text away, which is the state rule 28 calls unrecoverable" % ddir)
    got = sorted(os.listdir(ddir))
    want = ["arm-a__rep1__00-p1.txt", "arm-a__rep1__01-p2.txt"]
    need(got == want, "responses are named %r, expected %r - the name IS the "
                      "join back to arm/pass/probe" % (got, want))

    ledger_dir = os.path.dirname(os.path.join(
        sb.root, "results", SLUG, "data", "arms", "saved.jsonl"))
    for r in sb.probes("saved"):
        where = "%s/%s" % (r["arm"], r["probe"])
        need(r.get("response_saved") is True,
             "%s: response_saved is %r" % (where, r.get("response_saved")))
        need(r.get("response_save_error") is None,
             "%s: response_save_error %r" % (where, r.get("response_save_error")))
        rel = r.get("response_file")
        need(rel == "saved-responses/%s"
             % ("arm-a__rep1__%02d-%s.txt" % (r["probe_index"], r["probe"])),
             "%s: response_file is %r" % (where, rel))
        path = os.path.join(ledger_dir, *rel.split("/"))
        need(os.path.exists(path),
             "%s: response_file %r does not resolve from the ledger's own "
             "directory - the path has to survive the campaign being moved"
             % (where, rel))
        body = open(path, encoding="utf-8").read()
        need(len(body) == r["response_chars"],
             "%s: the saved file is %d chars, the ledger counted %d - they are "
             "supposed to be the same text" % (where, len(body),
                                               r["response_chars"]))
        need(body.strip(),
             "%s: the saved file is EMPTY while the ledger says %d chars were "
             "generated - a zero-byte artifact is exactly what a discarded "
             "body looks like" % (where, r["response_chars"]))
        need(r.get("empty_answer") is False,
             "%s: empty_answer %r for a %d-char body"
             % (where, r.get("empty_answer"), r["response_chars"]))

    start = [r for r in sb.ledger("saved") if r.get("kind") == "sweep_start"][0]
    need(start.get("save_responses") is True,
         "sweep_start does not record that the text was kept - whether it was "
         "is a condition of every later claim about content (rule 3)")

    # ... and the opt-out really opts out, loudly.
    arms2 = [sb.arm("arm-a", probes=[{"id": "p1", "prompt": "quiet",
                                      "n_predict": 16}])]
    f2 = sb.arm_file("unsaved", arms2, free_port())
    rc, out2 = sb.run("--arms", f2, "--slug", SLUG, "--no-save-responses")
    need(rc == 0, "opt-out sweep exited %d:\n%s" % (rc, out2[-1200:]))
    need(not os.path.exists(sb.responses_dir("unsaved")),
         "--no-save-responses still created %s" % sb.responses_dir("unsaved"))
    rec = sb.probes("unsaved")[0]
    need(rec.get("response_file") is None and rec.get("response_saved") is False,
         "--no-save-responses left response_file %r / response_saved %r"
         % (rec.get("response_file"), rec.get("response_saved")))
    need(rec.get("response_chars") > 0,
         "the opt-out dropped response_chars too - it is only supposed to drop "
         "the text")
    need("NOT SAVED" in out2,
         "the opt-out run never says the text is gone:\n%s" % out2[-600:])
    return "2 bodies saved by default, named by arm/pass/probe; opt-out is loud"


def _rung_arm_file(sb, stem, port, rungs=None, extra_arms=()):
    """One plan-driven template arm, plus whatever else the test wants.

    The stub's own flags go on the ARM rather than in defaults, because
    defaults are prepended: a "-c 4096" there would be the FIRST -c in the
    list and would win over the rung the template resolves.
    """
    tmpl = {"id": "rung-c{rung.c}", "sweep": "ladder",
            "rungs": dict({"from": "plan", "file": MODEL_NAME,
                           "reference_rungs": [9999]}, **(rungs or {})),
            "server": {"model": MODEL_NAME,
                       "flags": ["-ngl", "99", "-c", "{rung.c}",
                                 "--launch-log", sb.launch_log,
                                 "--max-life", "120"]},
            "probes": [{"id": "p1", "prompt": "lane probe",
                        "n_predict": "{rung.deep_fill_tokens}"}]}
    return sb.arm_file(stem, [tmpl] + list(extra_arms), port,
                       order="fixed",
                       defaults={"server": {"flags": []}, "probe": {}})


def t_plan_rungs(sb):
    """An arm file may take its -c ladder from results/<slug>/plan.json.

    THE HARDCODED-LADDER BUG. scripts/arms/ctx-ceiling.json used to carry 25
    arms at 18 distinct -c values from 122,880 to 262,144, every one of them
    sized for one 27B on one 24 GB card; run against a smaller model they
    sweep windows it has never had. The ladder is DERIVED now, and this
    asserts the three things that
    makes true: the rungs come out of the plan, the placeholder substitution
    reaches the id, the flags AND an integer probe field, and every ledger
    line says which rung of which plan it is (rules 3 and 28).
    """
    port = free_port()
    sb.write_plan([sb.rung_record(MODEL_NAME, [2048, 3072, 5120],
                                  ceiling=4096, window=8192,
                                  zones=["lever", "dense", "coarse"],
                                  why="FIXTURE ladder, three rungs")])
    f = _rung_arm_file(sb, "rungs", port)

    rc, out = sb.run("--arms", f, "--slug", SLUG, "--dry-run")
    need(rc == 0, "--dry-run exited %d:\n%s" % (rc, out[-1500:]))
    for want in ("2048 (lever)", "3072 (dense)", "5120 (coarse)",
                 "rung-c2048", "rung-c5120", "plan rung 2 of 3"):
        need(want in out,
             "--dry-run does not show the resolved ladder: %r missing.\n%s"
             % (want, out[:2500]))

    rc, out = sb.run("--arms", f, "--slug", SLUG)
    need(rc == 0, "sweep exited %d:\n%s" % (rc, out[-1500:]))

    recs = sb.probes("rungs")
    need([r["arm"] for r in recs] == ["rung-c2048", "rung-c3072",
                                      "rung-c5120"],
         "the ladder did not expand into one arm per rung, ascending: %r"
         % [r["arm"] for r in recs])
    for rec, (c, zone) in zip(recs, [(2048, "lever"), (3072, "dense"),
                                     (5120, "coarse")]):
        where = "arm %s" % rec["arm"]
        need(rec["ctx_size"] == c,
             "%s: ledger ctx_size %r, expected %d - the window is a condition "
             "every number travels with (rule 3)"
             % (where, rec.get("ctx_size"), c))
        need(rec["ctx_source"] == "plan",
             "%s: ctx_source %r, expected 'plan' - a DERIVED rung and a "
             "literal are not the same claim" % (where, rec.get("ctx_source")))
        rung = rec.get("rung") or {}
        need(rung.get("zone") == zone and rung.get("c") == c,
             "%s: rung record is %r" % (where, rung))
        need(rung.get("plan", "").endswith("plan.json"),
             "%s: the line does not name the plan it came from: %r"
             % (where, rung.get("plan")))
        need(rung.get("template") == "rung-c{rung.c}",
             "%s: the line does not name the template: %r"
             % (where, rung.get("template")))
        # "{rung.c}" is the whole flag value, so it must arrive as a NUMBER,
        # and "{rung.deep_fill_tokens}" as an integer n_predict.
        need(rec["request"].get("max_tokens") == int(c * 0.9),
             "%s: max_tokens %r, expected the rung's deep_fill_tokens %d - a "
             "placeholder that is the whole string must keep the value's type"
             % (where, rec["request"].get("max_tokens"), int(c * 0.9)))

    launched = [l["argv"] for l in sb.launches()]
    for argv, c in zip(launched, (2048, 3072, 5120)):
        need(str(c) in argv[argv.index("-c") + 1],
             "llama-server was launched with -c %s, not %d"
             % (argv[argv.index("-c") + 1], c))

    start = [r for r in sb.ledger("rungs") if r.get("kind") == "sweep_start"][0]
    cp = start.get("campaign_plan") or {}
    need(cp.get("generated_utc") == "2026-08-29T00:00:00Z" and cp.get("path"),
         "sweep_start does not carry the plan it derived the ladder from: %r"
         % cp)
    need(start.get("plan") and start["plan"][0].get("order"),
         "the per-pass arm ORDER plan was lost from sweep_start: %r"
         % start.get("plan"))
    lad = (start.get("ladders") or [{}])[0]
    need(lad.get("c") == [2048, 3072, 5120] and lad.get("reference_rungs"),
         "sweep_start does not record the resolved ladder and the reference "
         "one it replaced: %r" % lad)

    # Re-running plan-campaign.py after a fresh desktop-reserve reading moves
    # predicted_ceiling without necessarily moving a single rung: the rungs
    # snap to a quantum, so the same three -c values come back under a new
    # timestamp and a new ceiling. If the plan's metadata counted as an arm
    # change, that would re-spend a completed ladder for nothing - so
    # spec_hash covers the flag list, where the -c actually is, and NOT the
    # rung provenance carried beside it. Only a changed -c reruns an arm.
    n = len(sb.launches())
    sb.write_plan([sb.rung_record(MODEL_NAME, [2048, 3072, 5120],
                                  ceiling=4200, window=8192,
                                  zones=["lever", "dense", "coarse"],
                                  why="FIXTURE ladder, re-derived")],
                  generated_utc="2026-08-30T12:00:00Z")
    rc, out = sb.run("--arms", f, "--slug", SLUG, "--resume")
    need(rc == 0, "--resume exited %d:\n%s" % (rc, out[-1200:]))
    need(len(sb.probes("rungs")) == 3,
         "--resume re-ran the ladder after the plan was regenerated with the "
         "SAME rungs: %d probe lines" % len(sb.probes("rungs")))
    need(len(sb.launches()) == n,
         "--resume relaunched a server for an unchanged rung")
    return "3 rungs resolved from plan.json, on the argv and on every line"


def t_plan_missing_is_fatal(sb):
    """No plan.json -> the sweep REFUSES, and names the command that writes one.

    The one behaviour that must never regress. A silent fall back to a
    hardcoded -c is how a ladder derived for a 27B on a 24 GB card gets run
    against a 1.7B whose whole window sits below its bottom rung - and the
    ledger would record those readings as though the ladder had been derived
    for it (rule 1). So: nothing launched, nothing written, and an error a
    stranger at 2am can act on without reading any source.
    """
    port = free_port()
    f = _rung_arm_file(sb, "noplan", port)
    need(not os.path.exists(sb.plan_path()),
         "the sandbox already has a plan.json; this test needs none")

    rc, out = sb.run("--arms", f, "--slug", SLUG)
    need(rc != 0, "the sweep exited 0 with no plan - it fell back:\n%s"
         % out[-1500:])
    for want in ("plan-campaign.py --slug %s" % SLUG, "rung-c{rung.c}",
                 os.path.join("results", SLUG, "plan.json").replace("\\", "\\"),
                 "NO fallback"):
        need(want in out,
             "the refusal does not name %r - it has to be actionable without "
             "reading arms.py:\n%s" % (want, out[-1500:]))
    need(not sb.launches(),
         "a server was launched before the plan was checked: %r"
         % sb.launches())
    ledger = os.path.join(sb.root, "results", SLUG, "data", "arms",
                          "noplan.jsonl")
    need(not os.path.exists(ledger),
         "a ledger was written for a sweep that cannot run: %s" % ledger)

    # --dry-run reports the same thing rather than raising, and still refuses.
    rc, out = sb.run("--arms", f, "--slug", SLUG, "--dry-run")
    need(rc == 2, "--dry-run exited %d, expected 2:\n%s" % (rc, out[-900:]))
    need("UNRESOLVED" in out and "plan-campaign.py" in out,
         "--dry-run hid the missing plan:\n%s" % out[-900:])

    # A plan that exists but knows nothing about this file is the same class
    # of failure, and must not resolve to some other file's ladder.
    sb.write_plan([sb.rung_record("SOME-OTHER-QUANT", [4096], 4096, 8192)])
    rc, out = sb.run("--arms", f, "--slug", SLUG)
    need(rc != 0, "a plan with no record for this file was accepted:\n%s"
         % out[-1200:])
    need("SOME-OTHER-QUANT" in out,
         "the error does not say which files the plan DOES hold:\n%s"
         % out[-1200:])
    return "refused, named plan-campaign.py, launched and wrote nothing"


TESTS = (
    ("resolver-accepts-stub", t_resolver_accepts_stub),
    ("stub-contract", t_stub_contract),
    ("clean-sweep+heartbeat", t_clean_sweep),
    ("resume-skips", t_resume_skips),
    ("resume-after-retry", t_resume_after_retry),
    ("discard-first", t_discard_first),
    ("parse-check", t_parse_check_stops_the_sweep),
    ("failed-arm-continues", t_failed_arm_continues),
    ("alternate-order", t_alternate_order),
    ("truncation-notice", t_truncation_notice),
    ("save-responses", t_save_responses),
    ("address-space-reservation", t_address_space_reservation),
    ("plan-rungs", t_plan_rungs),
    ("plan-missing-is-fatal", t_plan_missing_is_fatal),
)


def run_one(name, fn, keep):
    """(name, seconds, note, error, kept_sandbox). Never raises."""
    t0, sb, note, err = time.time(), None, None, None
    try:
        sb = Sandbox()
        note = fn(sb)
    except Failure as exc:
        err = str(exc)
    except Exception as exc:                   # a broken test is a failed test
        import traceback
        err = "%s: %s\n%s" % (type(exc).__name__, exc,
                              traceback.format_exc()[-900:])
    kept = None
    if sb is not None:
        if keep:
            kept = sb.root
        else:
            sb.cleanup()
    return name, time.time() - t0, note, err, kept


def main():
    ap = argparse.ArgumentParser(
        description="Drive real scripts/arms.py subprocesses against a stub "
                    "llama-server. No GPU, no model, no pip.")
    ap.add_argument("--only", metavar="SUBSTRING", default=None,
                    help="run only tests whose name contains this")
    ap.add_argument("--keep", action="store_true",
                    help="keep each test's sandbox directory and print it")
    ap.add_argument("--jobs", type=int, default=4, metavar="N",
                    help="tests to run at once (default 4; --jobs 1 for "
                         "strictly serial). Each test owns a separate sandbox, "
                         "a separate lock file and its own port, so this is "
                         "concurrency between SANDBOXES - it does not weaken "
                         "rule 20, which is about one job on one GPU, and "
                         "there is no GPU here.")
    ap.add_argument("--list", action="store_true", help="list the tests")
    a = ap.parse_args()

    if a.list:
        for name, fn in TESTS:
            print("%-26s %s" % (name, (fn.__doc__ or "").splitlines()[0]))
        return 0

    chosen = [(n, f) for n, f in TESTS if not a.only or a.only in n]
    if not chosen:
        print("no test matches %r" % a.only)
        return 2
    jobs = max(1, min(int(a.jobs), len(chosen)))

    print("=" * 78)
    print("ARMS TEST LANE - real arms.py, stub llama-server, no GPU")
    print("=" * 78)
    print("python   : %s" % sys.executable)
    print("stub     : %s" % os.path.relpath(STUB, REPO))
    print("mirroring: %s" % ", ".join(MIRROR))
    print("jobs     : %d (elapsed times below overlap)\n" % jobs)

    failures, t_all = [], time.time()
    if jobs == 1:
        results = [run_one(n, f, a.keep) for n, f in chosen]
    else:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            # collected in submission order, so the output is the same list
            # whatever order they finish in
            results = list(pool.map(lambda nf: run_one(nf[0], nf[1], a.keep),
                                    chosen))
    for name, secs, note, err, kept in results:
        if err is None:
            print("  ok    %-26s %5.1fs  %s" % (name, secs, note))
        else:
            print("  FAIL  %-26s %5.1fs" % (name, secs))
            for line in err.strip().splitlines():
                print("        | %s" % line[:150])
            failures.append(name)
        if kept:
            print("        sandbox kept: %s" % kept)

    print()
    print("=" * 78)
    if failures:
        print("%d of %d FAILED in %.0f s: %s"
              % (len(failures), len(chosen), time.time() - t_all,
                 ", ".join(failures)))
        print("Each one is a sweep behaviour something in results/ depends on.")
    else:
        print("all %d passed in %.0f s - ledger, resume, discard, parse check, "
              "failure handling\nand arm order, checked without a GPU."
              % (len(chosen), time.time() - t_all))
    print("=" * 78)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
