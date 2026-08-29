#!/usr/bin/env python3
"""A llama-server that answers arms.py truthfully and never touches the card.

    python scripts/verify/fake-llama-server.py -m any/path.gguf --port 18123
    python scripts/verify/fake-llama-server.py --help

WHY THIS EXISTS. Every bug this repository found on 2026-08-29 - RLIMIT_AS
aborting every GPU arm on Linux, --resume marking a retried arm failed
forever, 33 probes running main() at import time - was found by spending real
GPU hours on it. Each one is catchable in seconds by a runner talking to a
server that only PRETENDS to have weights. This is that server: the sweep
runner launches it, polls it, probes it and stops it exactly as it would
llama-server, and the whole lane costs no VRAM, no model file and no watts.

WHAT IT IMPERSONATES, and nothing more:

    GET  /health                 {"status":"ok"} once it is ready
    GET  /props                  the model path it was launched with
    GET  /v1/models              the same, in the OpenAI shape
    POST /v1/chat/completions    a canned answer with a full timings block

The timings block carries every field arms.py's REQUIRED_TIMINGS names
(prompt_n, predicted_n, prompt_ms, predicted_ms, predicted_per_second), plus
prompt_per_second and the rule-11 drafting pair, and it is COMPUTED FROM THE
REQUEST: prompt_n is the prompt's own length in nominal tokens and predicted_n
is the max_tokens the runner asked for. A test can therefore assert that the
runner recorded what it actually asked for, rather than a constant this file
made up.

THE ARGV IT ACCEPTS is llama-server's, as arms.py builds it:

    <bin> -m <model> <every flag the arm file carries> --host H --port P

Flags it does not know are IGNORED, by design and by name, because an arm file
carries complete flag lists reconstructed from the .ps1 originals (--jinja,
-ngl 99, --spec-type draft-mtp, --mmproj ...) and a stub that rejected one
would fail the sweep for the wrong reason. Parsing is hand-rolled rather than
argparse for one specific reason: argparse resolves "-md draft.gguf" - the
llama.cpp draft-model flag - as "-m" with the value "d", which would silently
launch this stub against the wrong model path. Exact token matching cannot.

THE SAD PATHS ARE THE POINT. A happy-path stub only proves the runner works
when nothing is wrong, which is the case nobody needs a test for. Every
failure mode below is one this runner is supposed to survive:

    --die-on-start        exit non-zero before binding      -> ARM FAILED
    --hang                bind, but never report healthy    -> health TIMEOUT
    --truncate            finish_reason=length              -> rule 7 notice
    --drop-timings FIELD  omit a REQUIRED_TIMINGS field     -> rule 25 abort
    --slow-first-probe    first probe reads low, later ones do not
                                                            -> rule 12 discard
    --fail-if-exists P    exit non-zero only while P exists -> a failed arm
                          that SUCCEEDS on the rerun, with its spec hash
                          unchanged, which is the only way to test that
                          --resume does not mark it failed forever
    --reserve-va GB       reserve GB of ADDRESS SPACE and serve anyway, the
                          one thing about a CUDA process a python stub can
                          honestly imitate -> the 2026-08-29 RLIMIT_AS abort

NO ORPHANS (rule 20). On Windows the sweep runner reaches this process through
a .cmd shim, and terminating a shim kills cmd.exe while leaving its child
listening on the port - measured 2026-08-29: still alive 5 s after terminate,
which is precisely the leftover server that answers the NEXT arm's probes and
records perfect-looking numbers under the wrong flags. So this process watches
its own parent and exits within a quarter second of losing it, and gives up
unconditionally after --max-life seconds.

STDLIB ONLY, no GPU, no model file: -m is recorded and echoed, never opened.
"""

import ctypes
import json
import os
import socket
import sys
import threading
import time

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# The five fields arms.py refuses to record a sweep without (arms.py:203). Kept
# spelled out here rather than imported: this file must run standing alone, and
# a copy that drifts is exactly what --drop-timings exists to detect.
REQUIRED_TIMINGS = ("prompt_n", "predicted_n", "prompt_ms", "predicted_ms",
                    "predicted_per_second")

# Flags this stub understands: token -> (attribute, takes a value?). EXACT
# match only. Everything else in the argv is ignored and reported through
# /props, so a test can assert what the arm file actually passed.
FLAGS = {
    "-m":                 ("model", True),
    "--model":            ("model", True),
    "--host":             ("host", True),
    "--port":             ("port", True),
    "--ready-after":      ("ready_after", True),
    "--rate":             ("rate", True),
    "--prompt-rate":      ("prompt_rate", True),
    "--default-predict":  ("default_predict", True),
    "--chars-per-token":  ("chars_per_token", True),
    "--slow-factor":      ("slow_factor", True),
    "--draft-accept":     ("draft_accept", True),
    "--drop-timings":     ("drop_timings", True),
    "--launch-log":       ("launch_log", True),
    "--reserve-va":       ("reserve_va", True),
    "--fail-if-exists":   ("fail_if_exists", True),
    "--exit-code":        ("exit_code", True),
    "--max-life":         ("max_life", True),
    "--slow-first-probe": ("slow_first_probe", False),
    "--die-on-start":     ("die_on_start", False),
    "--hang":             ("hang", False),
    "--truncate":         ("truncate", False),
}

DEFAULTS = {
    "model": None, "host": "127.0.0.1", "port": 8080,
    "ready_after": 0.0,        # seconds of "loading model" before /health is ok
    "rate": 100.0,             # nominal predicted_per_second
    "prompt_rate": 2000.0,     # nominal prompt_per_second
    "default_predict": 64,     # predicted_n when the request caps nothing
    "chars_per_token": 4,      # prompt chars -> nominal prompt_n
    "slow_factor": 0.55,       # rule 12's ramp: 45% low, the measured worst case
    "draft_accept": None,      # emit the rule-11 drafting pair at this acceptance
    "drop_timings": [],        # REQUIRED_TIMINGS fields to omit
    "launch_log": None, "fail_if_exists": None,
    "reserve_va": 0.0,         # GB of address space to reserve, CUDA-style
    "exit_code": 1, "max_life": 600.0,
    "slow_first_probe": False, "die_on_start": False,
    "hang": False, "truncate": False,
}

_FLOAT = ("ready_after", "rate", "prompt_rate", "slow_factor", "draft_accept",
          "max_life", "reserve_va")
_INT = ("port", "default_predict", "chars_per_token", "exit_code")

_WORDS = ("the quick brown fox jumps over the lazy dog while the sweep runner "
          "records every timing it was handed and nothing it was not").split()


def usage():
    return (
        "fake-llama-server.py - a llama-server that answers arms.py and never "
        "touches the card\n\n"
        "usage: fake-llama-server.py -m MODEL [--host H] [--port P]\n"
        "                            [any llama-server flags, ignored by name]\n"
        "                            [failure injection]\n\n"
        "failure injection:\n"
        "  --die-on-start          exit --exit-code N (default 1) immediately\n"
        "  --hang                  bind the port, never report healthy\n"
        "  --ready-after S         report loading-model for S seconds first\n"
        "  --truncate              answer with finish_reason=length\n"
        "  --drop-timings FIELD    omit that timings field (repeatable, or\n"
        "                          comma-separated); one of: %s\n"
        "  --slow-first-probe      first completion reports rate x --slow-factor\n"
        "  --fail-if-exists PATH   exit non-zero while PATH exists\n\n"
        "shape:\n"
        "  --rate F                predicted_per_second (default 100)\n"
        "  --prompt-rate F         prompt_per_second (default 2000)\n"
        "  --default-predict N     predicted_n when the request caps nothing\n"
        "  --chars-per-token N     prompt chars per nominal token (default 4)\n"
        "  --draft-accept F        emit draft_n / draft_n_accepted at this\n"
        "                          acceptance (rule 11 pair)\n"
        "  --launch-log PATH       append one JSON line per launch\n"
        "  --reserve-va GB         reserve GB of address space before serving\n"
        "  --max-life S            self-destruct after S seconds (default 600)\n"
        % ", ".join(REQUIRED_TIMINGS))


def parse_argv(argv):
    """(options, ignored) from a llama-server command line.

    Exact token matching, never a prefix and never argparse: "-md" is
    llama.cpp's draft-model flag and argparse would read it as "-m" with the
    value "d". Unknown flags and their values fall through to `ignored`, which
    is what lets an arm file's complete flag list run unmodified.
    """
    opt = dict(DEFAULTS)
    opt["drop_timings"] = []
    ignored, i = [], 0
    while i < len(argv):
        tok = argv[i]
        if tok in ("-h", "--help"):
            opt["help"] = True
            return opt, ignored
        if tok in FLAGS:
            name, takes_value = FLAGS[tok]
            if not takes_value:
                opt[name] = True
                i += 1
                continue
            if i + 1 >= len(argv):
                raise SystemExit("fake-llama-server: %s needs a value" % tok)
            val = argv[i + 1]
            if name == "drop_timings":
                opt[name].extend(v for v in val.split(",") if v)
            elif name in _FLOAT:
                opt[name] = float(val)
            elif name in _INT:
                opt[name] = int(val)
            else:
                opt[name] = val
            i += 2
            continue
        ignored.append(tok)
        i += 1
    return opt, ignored


# ---------------------------------------------------------------------------
# Staying dead when the runner is done with us (rule 20)
# ---------------------------------------------------------------------------

def watch_parent_and_clock(max_life_s):
    """Exit when the launching process goes away, or after max_life_s.

    Two ways this process can be left holding a port, both measured:

      * Windows: arms.py terminates the .cmd shim, which kills cmd.exe and
        leaves this child running. Verified 2026-08-29: without this watch the
        child was still alive 5.00 s after terminate(); with it, gone in 0.25 s.
      * either OS: the lane itself is killed, and nothing sends us a signal.

    A leftover server is the one failure arms.py cannot detect after the fact -
    it answers the next arm's probes and the ledger records ITS numbers under
    another arm's flags - so this is not optional politeness.
    """
    ppid = os.getppid()

    def _wait():
        if os.name == "nt":
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            handle = k32.OpenProcess(0x00100000, False, ppid)   # SYNCHRONIZE
            if handle:
                k32.WaitForSingleObject(ctypes.c_void_p(handle), 0xFFFFFFFF)
                os._exit(0)
        while True:
            time.sleep(0.25)
            if os.getppid() != ppid:      # reparented: the launcher is gone
                os._exit(0)

    def _clock():
        time.sleep(max_life_s)
        sys.stderr.write("fake-llama-server: --max-life %.0f s reached, "
                         "exiting so nothing is left holding the port\n"
                         % max_life_s)
        sys.stderr.flush()
        os._exit(0)

    for target in (_wait, _clock):
        threading.Thread(target=target, daemon=True).start()


def reserve_address_space(gb):
    """Reserve gb of ADDRESS SPACE, committing none of it. Returns the handle.

    The one thing about a CUDA process this stub can honestly imitate. A
    llama-server on a GPU reserves tens of gigabytes of virtual address space
    for unified memory whatever it actually uses, and on 2026-08-29 that is
    what killed every arm on Linux: gpu_lock set RLIMIT_AS - a cap on ADDRESS
    SPACE, not on committed pages - to 75% of RAM, and a 3.6 GB model that
    loads fine unguarded aborted with SIGABRT inside common_init_from_params.

    A reservation is not memory: PROT_NONE / MEM_RESERVE commits no pages and
    touches no card. But it is counted by RLIMIT_AS, and it is NOT counted by a
    Windows job object's commit limit - which is exactly why Linux broke and
    Windows did not. So an arm that carries --reserve-va passes here and dies
    under the bug, on the platform that had it.
    """
    n = int(float(gb) * (1 << 30))
    if n <= 0:
        return None
    if os.name == "nt":
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.VirtualAlloc.restype = ctypes.c_void_p
        k32.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
                                     ctypes.c_uint32, ctypes.c_uint32]
        MEM_RESERVE, PAGE_NOACCESS = 0x00002000, 0x01
        addr = k32.VirtualAlloc(None, ctypes.c_size_t(n), MEM_RESERVE,
                                PAGE_NOACCESS)
        if not addr:
            raise OSError("VirtualAlloc(MEM_RESERVE, %d) failed, error %d"
                          % (n, ctypes.get_last_error()))
        return addr
    import mmap
    anon = getattr(mmap, "MAP_ANONYMOUS", getattr(mmap, "MAP_ANON", 0x20))
    return mmap.mmap(-1, n, flags=mmap.MAP_PRIVATE | anon, prot=0)


# ---------------------------------------------------------------------------
# The answers
# ---------------------------------------------------------------------------

def canned_text(n_words):
    """Deterministic body text, so response_chars is a function of the cap."""
    n_words = max(1, min(int(n_words), 4096))
    return " ".join(_WORDS[i % len(_WORDS)] for i in range(n_words))


def build_completion(opt, state, body):
    """The chat-completion response, computed from the request that asked."""
    messages = body.get("messages") or []
    prompt = ""
    for m in messages:
        if isinstance(m, dict) and isinstance(m.get("content"), str):
            prompt += m["content"]

    cpt = max(1, int(opt["chars_per_token"]))
    prompt_n = max(1, -(-len(prompt) // cpt))          # ceil, never zero
    asked = body.get("max_tokens")
    predicted_n = int(asked) if isinstance(asked, int) and asked > 0 \
        else int(opt["default_predict"])

    with state["lock"]:
        state["completions"] += 1
        nth = state["completions"]
    # rule 12: the first probe after a load reads up to 45% low because the
    # clocks are still ramping. --slow-first-probe reproduces exactly that, so
    # a test can prove the discarded probe is BOTH dropped from the summary and
    # written to the ledger.
    rate = float(opt["rate"])
    if opt["slow_first_probe"] and nth == 1:
        rate *= float(opt["slow_factor"])
    prompt_rate = float(opt["prompt_rate"])

    timings = {
        "prompt_n": prompt_n,
        "prompt_ms": round(1000.0 * prompt_n / prompt_rate, 3),
        "prompt_per_second": round(prompt_rate, 3),
        "predicted_n": predicted_n,
        "predicted_ms": round(1000.0 * predicted_n / rate, 3),
        "predicted_per_second": round(rate, 3),
        "cache_n": 0,
    }
    if opt["draft_accept"] is not None:
        # rule 11: acceptance AND mean draft length, and the numbers have to be
        # self-consistent - predicted_n - draft_n_accepted is the verify-pass
        # count arms.py divides by, so it must stay above zero.
        acc = min(0.99, max(0.01, float(opt["draft_accept"])))
        accepted = max(1, int(predicted_n * 0.7))
        timings["draft_n"] = max(1, int(round(accepted / acc)))
        timings["draft_n_accepted"] = accepted
    for field in opt["drop_timings"]:
        timings.pop(field, None)

    finish = "length" if opt["truncate"] else "stop"
    content = canned_text(predicted_n)
    return {
        "id": "chatcmpl-fake-%d" % nth,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": os.path.basename(opt["model"] or "unknown.gguf"),
        "choices": [{"index": 0, "finish_reason": finish,
                     "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": prompt_n, "completion_tokens": predicted_n,
                  "total_tokens": prompt_n + predicted_n},
        "timings": timings,
    }


def make_handler(opt, ignored, state):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "fake-llama.cpp/0"

        def _send(self, code, payload):
            blob = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(blob)))
            self.end_headers()
            self.wfile.write(blob)

        def _ready(self):
            if opt["hang"]:
                return False
            return (time.time() - state["t0"]) >= float(opt["ready_after"])

        def log_message(self, fmt, *args):
            # one terse line per request, to stderr, which arms.py folds into
            # the arm's own log - so log_tail() has something to show
            sys.stderr.write("[fake-llama] %s\n" % (fmt % args))
            sys.stderr.flush()

        def do_GET(self):
            path = self.path.split("?")[0].rstrip("/") or "/"
            if path == "/health":
                if self._ready():
                    return self._send(200, {"status": "ok"})
                return self._send(503, {"status": "loading model",
                                        "error": {"code": 503,
                                                  "message": "Loading model"}})
            if path == "/props":
                return self._send(200, {
                    "model_path": opt["model"],
                    "total_slots": 1,
                    "chat_template": "{{ fake }}",
                    "default_generation_settings": {
                        "n_ctx": 4096, "temperature": 1.0, "top_p": 0.95,
                        "n_predict": int(opt["default_predict"])},
                    # not llama-server's, deliberately: this is what the stub
                    # was told, so a test can assert the right model and the
                    # right flags reached the process that answered the probes
                    "fake_llama_server": {
                        "argv": state["argv"], "ignored_flags": ignored,
                        "completions_served": state["completions"],
                        "pid": os.getpid()},
                })
            if path == "/v1/models":
                return self._send(200, {"object": "list", "data": [
                    {"id": os.path.basename(opt["model"] or "unknown.gguf"),
                     "object": "model", "owned_by": "fake-llama-server"}]})
            return self._send(404, {"error": {
                "code": 404, "message": "not found: %s" % path}})

        def do_POST(self):
            path = self.path.split("?")[0].rstrip("/") or "/"
            if path not in ("/v1/chat/completions", "/chat/completions"):
                return self._send(404, {"error": {
                    "code": 404, "message": "not found: %s" % path}})
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            except (ValueError, UnicodeDecodeError) as exc:
                return self._send(400, {"error": {"code": 400,
                                                  "message": str(exc)}})
            if not isinstance(body, dict):
                return self._send(400, {"error": {
                    "code": 400, "message": "body is not an object"}})
            return self._send(200, build_completion(opt, state, body))

    return Handler


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    opt, ignored = parse_argv(argv)
    if opt.get("help"):
        print(usage())
        return 0

    bad = [f for f in opt["drop_timings"] if f not in REQUIRED_TIMINGS]
    if bad:
        sys.stderr.write("fake-llama-server: --drop-timings %s is not one of "
                         "%s\n" % (", ".join(bad), ", ".join(REQUIRED_TIMINGS)))
        return 2
    if not opt["model"]:
        sys.stderr.write("fake-llama-server: error: no model specified "
                         "(-m/--model)\n")
        return 2

    if opt["launch_log"]:
        try:
            with open(opt["launch_log"], "a", encoding="utf-8",
                      newline="\n") as fh:
                fh.write(json.dumps({
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "pid": os.getpid(), "model": opt["model"],
                    "host": opt["host"], "port": int(opt["port"]),
                    "argv": argv, "ignored_flags": ignored,
                    "die_on_start": bool(opt["die_on_start"]),
                }, ensure_ascii=False) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        except OSError as exc:
            sys.stderr.write("fake-llama-server: launch log: %s\n" % exc)

    # The two "this arm will not load" injections, before anything binds.
    # --fail-if-exists is the one that matters most: it flips an arm between
    # failing and succeeding WITHOUT changing a byte of the arm file, which is
    # the only honest way to test that a retried arm is not skipped as failed.
    if opt["fail_if_exists"] and os.path.exists(opt["fail_if_exists"]):
        sys.stderr.write("fake-llama-server: injected failure: %s exists\n"
                         % opt["fail_if_exists"])
        sys.stderr.write("error: failed to load model '%s'\n" % opt["model"])
        return int(opt["exit_code"])
    if opt["die_on_start"]:
        sys.stderr.write("fake-llama-server: injected failure: --die-on-start\n")
        sys.stderr.write("error: failed to load model '%s'\n" % opt["model"])
        return int(opt["exit_code"])

    # Before binding, exactly where a real server reserves its address space.
    reservation = None
    if float(opt["reserve_va"]) > 0:
        try:
            reservation = reserve_address_space(opt["reserve_va"])
        except (OSError, ValueError, MemoryError) as exc:
            sys.stderr.write(
                "fake-llama-server: could not reserve %.1f GB of ADDRESS SPACE "
                "(%s).\nThat is the 2026-08-29 shape: an address-space cap "
                "kills a process that reserves and never commits, which is "
                "every CUDA process there is.\n" % (float(opt["reserve_va"]), exc))
            return int(opt["exit_code"])
        sys.stderr.write("fake-llama-server: reserved %.1f GB of address "
                         "space, committed none of it\n"
                         % float(opt["reserve_va"]))

    state = {"t0": time.time(), "completions": 0, "argv": argv,
             "reservation": reservation is not None,
             "lock": threading.Lock()}
    watch_parent_and_clock(float(opt["max_life"]))

    ThreadingHTTPServer.address_family = socket.AF_INET
    ThreadingHTTPServer.daemon_threads = True
    try:
        httpd = ThreadingHTTPServer((opt["host"], int(opt["port"])),
                                    make_handler(opt, ignored, state))
    except OSError as exc:
        sys.stderr.write("fake-llama-server: cannot bind %s:%s: %s\n"
                         % (opt["host"], opt["port"], exc))
        return 2

    sys.stderr.write("fake-llama-server: model %s\n" % opt["model"])
    sys.stderr.write("fake-llama-server: ignoring %d llama-server flag(s): %s\n"
                     % (len(ignored), " ".join(ignored) or "(none)"))
    sys.stderr.write("main: server is listening on http://%s:%s - starting the "
                     "main loop\n" % (opt["host"], opt["port"]))
    sys.stderr.flush()
    try:
        httpd.serve_forever(poll_interval=0.05)
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
