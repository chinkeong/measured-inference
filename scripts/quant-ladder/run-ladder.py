#!/usr/bin/env python3
"""The quant ladder on any platform - perplexity over 294,912 token positions.

    python scripts/quant-ladder/run-ladder.py --dry-run     # plan, resolve, gate-proof
    python scripts/quant-ladder/run-ladder.py               # run until exhausted
    python scripts/quant-ladder/run-ladder.py --once        # exactly one rung
    python scripts/quant-ladder/run-ladder.py --only UD-IQ1_S
    python scripts/quant-ladder/run-ladder.py --outdir <dir> --manifest <file>

WHY THIS FILE EXISTS. METHODOLOGY rule 6 ranks quants by perplexity over
294,912 token positions - not by accuracy, which at n<=25 detects only
~20-point collapses - and until this file existed the only runner that could
produce that number was `run-ladder.ps1`, Windows PowerShell, which
`skills/field-guide/stages/stage-6.md` named as the ladder runner with no POSIX
equivalent shipped. Those two sentences together said that a Linux campaign
could not rank its quants at all. This file is that equivalent, and
`stage-6.md` names it as the runner (Stage 6a, "It is stdlib-only and runs on
Linux, macOS and Windows"). It is Python and stdlib-only, so one file serves
Linux, macOS and Windows, and `run-ladder.ps1` stays exactly where it is as the
Windows original and the reference for behaviour.

WHAT IT GUARANTEES, each one verifiable without a GPU (`--dry-run`):

  CORPUS GATE - the corpus named by the manifest is hashed and checked against
                the manifest's `corpus_md5` before anything else runs. A ladder
                that silently changes its corpus is comparing nothing (rule 23).
  GPU GATE    - the manifest's coordination gate (another session's runner PID,
                no llama-* process, board VRAM under the cap) AND rule 20's
                machine-wide mutex. Every child - llama-perplexity and
                llama-tokenize both - is launched through
                `scripts/bench/gpu_lock.py`, never bare Popen, so it is capped,
                cannot outlive this process, and cannot start beside another
                GPU job.
  FILE GATE   - a rung is measured only when its file exists AND its byte size
                is unchanged across a recheck window, re-confirmed after the
                GPU gate opens. This runner never downloads, moves or deletes a
                weight file.
  RESUMABLE   - a rung whose RESULT or FAILED line is already in the ledger is
                skipped. Kill and restart at will (rule 20). This is the
                property that makes an 8-hour ladder survive a lost session.
  ONE AT A TIME - `--once` measures exactly one rung per invocation, for a
                platform that kills long tasks.
  ANCHOR GATE - a `rig-gate` rung is re-measured first and compared against its
                published anchor; outside `tolerance_pct` with
                `abort_on_drift` the whole campaign halts, and a `pair_with`
                rung must still RESOLVE its partner by `pair_min_gap_pct` or
                the rig is declared unable to rank quants today.

CONDITIONS, fixed by the manifest and never by this file: `-ngl 99 -c 8192
-fa on --load-mode mmap`, f16 KV (llama.cpp's default, so no flag), 36 chunks
of 8,192 = 294,912 token positions, the md5-pinned wikitext-2-raw test split.

THREE DELIBERATE DIFFERENCES FROM run-ladder.ps1, each one a defect fixed
rather than a behaviour dropped:

 1. PATHS ARE RESOLVED, NOT TYPED. run-ladder.ps1 reads `E:\\AI\\llama.cpp\\
    llama-perplexity.exe`, `E:\\AI\\measured-inference\\corpora\\...` and an
    absolute `outdir` straight out of the manifest. On a fresh clone every one
    of those is wrong. Here the manifest's literal is offered to
    `scripts/lib/paths.py` as a hint and the resolution chain decides - so the
    same manifest runs unedited on the reference rig and on a rented box.
 2. THE DENOMINATOR IS MEASURED. bits-per-weight is `bytes * 8 / params`, and
    `params` comes from `measure-bpw.py`, which sums the file's own GGUF tensor
    table. The manifest's typed 27,000,000,000 is 1.174% below the 27,320,697,856
    the IQ4_XS file actually contains, which inflates its published bpw by
    1.188% - larger than the gaps a ladder is asked to resolve between adjacent
    rungs, and not a constant offset, so it does not cancel. When the header
    read fails the manifest literal is used and the line says
    `params_src=manifest-declared`: rule 1 has three categories, measured,
    cited and labeled-derived, and no fourth.
 3. NO THOUSANDS SEPARATORS IN THE LEDGER. PowerShell's `N4` format writes
    `PPL=1,159.7186`, and `summarize.py`'s `float()` rejects that string and
    silently drops the row. Every value below 1,000 is byte-identical either
    way; above it, this runner's line parses and the PowerShell one does not.

Everything else is the PowerShell runner's behaviour: the same manifest, the
same ledger file, the same RESULT / RIGGATE / RIGPAIR / PASS2-ENABLE / NOTE /
FAILED / ABORT line shapes, the same streamed re-scan from the top after every
completion, the same conditional pass-2 enablement and `enable-<name>.flag`
override, the same three-attempts-then-FAILED retry, the same deadline. One
field is added to RESULT: `runner=`, because a campaign measured half on
Windows and half on Linux must be able to say which line came from which
(rule 3, and rule 28 - a field not written during the run is unrecoverable).

DETECTORS remain Windows-only. `detectors.ps1` needs a PowerShell host; where
one exists this runner calls it exactly as run-ladder.ps1 does, and where none
does it writes a NOTE line into the ledger saying the disqualifier probes did
not run. A skipped axis that says nothing reads as a measured negative
(rule 2).

Stdlib only. Python 3.8+. Linux, macOS and Windows.
"""

import argparse
import hashlib
import importlib.util
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(_ROOT, "scripts", "lib"))
sys.path.insert(0, os.path.join(_ROOT, "scripts", "bench"))
import paths                                            # noqa: E402
import gpu_lock                                         # noqa: E402

LN2 = math.log(2.0)
GIB = float(1 << 30)
PPL_TIMEOUT_S = 5400        # 90 min, as run-ladder.ps1
TOKENIZE_TIMEOUT_S = 600
LEDGER_RETRIES = 15
LEDGER_RETRY_S = 2

_mbpw_cache = []


# ---------------------------------------------------------------------------
# logging and the ledger
# ---------------------------------------------------------------------------

def log(msg):
    print("[%s] %s" % (time.strftime("%m-%d %H:%M:%S"), msg), flush=True)


def stamp():
    """The PowerShell 's' date format: sortable, local, no offset."""
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def ledger_append(path, line):
    """Append one ledger line, or spill it beside the file rather than lose it.

    A dropped ledger line is silent data loss: the measurement happened and the
    report would never know. run-ladder.ps1 earned this on 2026-08-23 when a
    `tail -f` from Git Bash opened the file without FILE_SHARE_WRITE and blocked
    two appends - the same hazard exists here on Windows, so the same retry and
    the same `.spill` fallback.
    """
    for _ in range(LEDGER_RETRIES):
        try:
            with io.open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            print(line, flush=True)
            return True
        except OSError:
            time.sleep(LEDGER_RETRY_S)
    try:
        with io.open(path + ".spill", "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass
    print("  LEDGER LOCKED - line spilled to %s.spill" % path, flush=True)
    print(line, flush=True)
    return False


def ledger_lines(path):
    """Every line of the ledger. utf-8-sig: PowerShell 5.1 stamps a BOM."""
    if not os.path.isfile(path):
        return []
    try:
        with io.open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
            return fh.read().splitlines()
    except OSError:
        return []


def ledger_has(path, needle):
    """Test-LedgerHas: does any line contain this substring."""
    return any(needle in ln for ln in ledger_lines(path))


def ledger_field(path, name, key):
    """Get-LedgerField: one key=value out of the LAST RESULT line for a rung."""
    pat = re.compile(r"^\ufeff?RESULT\s+" + re.escape(name) + r"\s")
    hit = None
    for ln in ledger_lines(path):
        if pat.match(ln):
            hit = ln
    if hit is None:
        return None
    m = re.search(re.escape(key) + r"=([^\s|]+)", hit)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# resolution - the manifest says what, this machine says where
# ---------------------------------------------------------------------------

def leaf(p):
    """The file name of a path written for EITHER platform.

    os.path.basename("C:\\models\\x.gguf") returns the whole string on Linux,
    because a backslash is a legal filename character there. Every manifest in
    this repository was written on Windows, so every lookup by name and every
    `file=` field would be garbage without this.
    """
    return re.split(r"[\\/]", str(p))[-1]


def load_manifest(path):
    with io.open(path, "r", encoding="utf-8-sig") as fh:
        man = json.load(fh)
    for key in ("rungs", "ppl", "gate", "file_gate"):
        if key not in man:
            raise SystemExit("%s has no %r - not a ladder manifest." % (path, key))
    return man


def resolve_bin(tool, hint):
    """A llama.cpp tool, with the manifest's literal offered as a hint only."""
    return paths.llama_bin(tool, explicit=hint if hint and os.path.isfile(hint)
                           else None)


def resolve_corpus(man):
    """The frozen corpus: the manifest's path, else <repo>/corpora/<name>."""
    want = str(man.get("corpus") or "")
    if want and os.path.isfile(want):
        return os.path.abspath(want)
    cand = os.path.join(paths.repo_root(), "corpora", leaf(want) or
                        "wikitext-2-raw-test.raw")
    if os.path.isfile(cand):
        return os.path.abspath(cand)
    raise SystemExit(
        "the frozen corpus is missing. The manifest names\n  %s\nand this "
        "machine has no such file; <repo>/corpora/%s does not exist either.\n"
        "Rule 23: two reports compare only if their inputs match, so this "
        "runner will not substitute one." % (want, leaf(want)))


def check_corpus(path, man):
    """Hash the corpus against the manifest's pin. Returns (ok, detail).

    run-ladder.ps1 checks only that the file exists. The md5 is IN the manifest
    and nothing reads it, which means a corpus swapped for a same-named file
    produces a full ladder of numbers that rank nothing against the anchors
    they are printed beside.
    """
    size = os.path.getsize(path)
    h = hashlib.md5()
    with io.open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    got = h.hexdigest()
    want = str(man.get("corpus_md5") or "").lower()
    want_b = man.get("corpus_bytes")
    if not want:
        return True, ("md5 %s (%d bytes) - the manifest pins no md5, so this "
                      "is recorded, not checked" % (got, size))
    if got != want:
        return False, ("md5 %s but the manifest pins %s (%d bytes on disk, "
                       "manifest says %s)" % (got, want, size, want_b))
    if want_b is not None and int(want_b) != size:
        return False, ("md5 matches but the size does not: %d bytes on disk, "
                       "manifest says %s" % (size, want_b))
    return True, "md5 %s, %d bytes - matches the manifest pin" % (got, size)


def resolve_model(rung):
    """The rung's weight file on THIS machine, or None if it is not here yet.

    A missing weight is not an error: the file gate exists precisely because
    another session may still be downloading it. paths.model_path raises
    SystemExit when it finds nothing, which is right for a caller that cannot
    proceed and wrong for this one.
    """
    raw = str(rung.get("path") or "")
    if raw and os.path.isfile(raw):
        return os.path.abspath(raw)
    try:
        return paths.model_path(leaf(raw))
    except SystemExit:
        return None


def measure_bpw_module():
    if not _mbpw_cache:
        src = os.path.join(HERE, "measure-bpw.py")
        if not os.path.isfile(src):
            raise SystemExit("measure-bpw.py is missing from %s" % HERE)
        spec = importlib.util.spec_from_file_location("measure_bpw", src)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)     # guarded by __name__ == "__main__"
        _mbpw_cache.append(mod)
    return _mbpw_cache[0]


def header_params(model_path, quiet=False):
    """The file's OWN parameter count, summed over its GGUF tensor table.

    ~11 MiB of a 13 GiB file, no GPU, no model load. None on any failure; the
    caller then falls back to the manifest literal and LABELS the line.
    """
    try:
        m = measure_bpw_module().measure(path=model_path)
    except Exception as exc:                             # noqa: BLE001
        if not quiet:
            log("  bpw: header read failed: %s" % exc)
        return None
    if not m.get("params") or int(m["params"]) <= 0:
        if not quiet:
            log("  bpw: measure-bpw.py returned no parameter count")
        return None
    return m


# ---------------------------------------------------------------------------
# the gates
# ---------------------------------------------------------------------------

def vram_used_mib():
    """Board VRAM in use, or -1 when nvidia-smi cannot be read."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=30).stdout
        for line in out.splitlines():
            line = line.strip()
            if line:
                return int(line)
    except Exception:                                    # noqa: BLE001
        pass
    return -1


def _proc_start_epoch(pid):
    """Wall-clock start time of a pid, in epoch seconds. None if unknowable."""
    if os.name == "nt":
        raw = gpu_lock._start_time(pid)                  # FILETIME ticks
        if raw is None:
            return None
        # 100-ns intervals since 1601-01-01 UTC
        return raw / 1e7 - 11644473600.0
    try:
        with open("/proc/%d/stat" % int(pid)) as fh:
            jiffies = int(fh.read().rsplit(")", 1)[1].split()[19])
        btime = None
        with open("/proc/stat") as fh:
            for line in fh:
                if line.startswith("btime "):
                    btime = int(line.split()[1])
                    break
        if btime is None:
            return None
        return btime + jiffies / float(os.sysconf("SC_CLK_TCK"))
    except Exception:                                    # noqa: BLE001
        return None


def _iso_epoch(text):
    """An ISO timestamp with offset -> epoch seconds. None if unparseable."""
    import datetime
    s = str(text).strip()
    # .NET's 'o' format writes SEVEN fractional digits; datetime takes six.
    s = re.sub(r"(\.\d{6})\d+", r"\1", s)
    try:
        return datetime.datetime.fromisoformat(s).timestamp()
    except ValueError:
        return None


def live_llama(gate):
    """Every llama-* process on this box, around a POSIX `comm` truncation.

    Linux caps /proc/<pid>/comm at 15 characters (TASK_COMM_LEN is 16 including
    the NUL), so `ps -eo comm=` reports `llama-perplexity` - the exact tool this
    runner launches, and `llama-completion` with it - as `llama-perplexit`.
    Reported here 2026-08-30, when gpu_lock.live_servers() compared that against
    its full 16-character name and matched nothing, so on Linux this gate could
    open while a perplexity pass held 13 GB of the card. This function's prefix
    match closed it here only, and said so: `gpu_lock.py` was deliberately not
    edited, because it belonged to another workstream and the defect was worth
    reporting rather than patching in passing.

    FIXED AT THE SOURCE 2026-08-31, on the first bare-metal Ubuntu run, where the
    same truncation was measured blinding `status`, `kill`, acquire()'s foreign
    refusal and detect-machine.py's desktop-reserve gate all at once:
    gpu_lock._posix_tool_name() now resolves /proc/<pid>/exe first and falls back
    to this same prefix rule, and returns the real untruncated name. So the
    `found` dict above already arrives complete and correctly labelled.

    This pass is kept anyway, and it is not redundant: it matches against the
    manifest's own `llama_procs` list, which a ladder may widen beyond
    gpu_lock.SERVER_TOOLS, and `setdefault` cannot overwrite a name gpu_lock has
    already supplied. Verified against the fixed module on 2026-08-31: same pids,
    same real names, no duplicates.
    """
    # live_servers() raises ServerScanFailed rather than returning [] when it
    # cannot look, so this propagates by design: the ladder must not start an
    # arm on an unverified card (rule 20).
    found = dict((p, n) for p, n in gpu_lock.live_servers())
    if os.name == "nt":
        return sorted(found.items())
    names = [str(x) for x in (gate.get("llama_procs") or gpu_lock.SERVER_TOOLS)]
    try:
        raw = subprocess.run(["ps", "-eo", "pid=,comm="], capture_output=True,
                             text=True, timeout=30).stdout
    except Exception:                                    # noqa: BLE001
        raw = ""
    for line in raw.splitlines():
        bits = line.split(None, 1)
        if len(bits) != 2:
            continue
        try:
            pid = int(bits[0])
        except ValueError:
            continue
        comm = os.path.basename(bits[1].strip())
        for want in names:
            if comm == want or (len(comm) >= 15 and want.startswith(comm)):
                found.setdefault(pid, comm)
                break
    return sorted(found.items())


def manifest_gate(gate, quiet=False):
    """The coordination gate run-ladder.ps1 defines. (open, why).

    THREE conditions, all required: the other session's runner PID is dead (or
    is a recycled PID naming a different process, proven by start time), no
    llama-* process of any kind exists, and board VRAM is under the cap.
    """
    pid = gate.get("holder_pid")
    if pid:
        alive = gpu_lock._alive(int(pid))
        if alive:
            same = True
            want = gate.get("holder_start_iso")
            if want:
                want_e = _iso_epoch(want)
                got_e = _proc_start_epoch(int(pid))
                if want_e is not None and got_e is not None:
                    same = abs(want_e - got_e) <= 2.0
            if same:
                return False, ("holder PID %s still alive (%s)"
                               % (pid, gate.get("holder_what") or "another session"))
    live = live_llama(gate)
    if live:
        return False, ("llama process alive: %s"
                       % ", ".join("%s/%d" % (n, p) for p, n in live))
    used = vram_used_mib()
    if used < 0:
        return False, ("nvidia-smi unreadable - this gate cannot prove the "
                       "card is free, so it stays shut")
    cap = int(gate.get("max_vram_mib") or 2000)
    if used >= cap:
        return False, "VRAM %d MiB >= %d MiB" % (used, cap)
    return True, "VRAM %d MiB" % used


def wait_gate(gate, deadline, poll_s):
    """Block until the manifest gate opens. False if the deadline arrives."""
    n = 0
    while True:
        ok, why = manifest_gate(gate, quiet=(n > 0 and n % 10 != 0))
        if ok:
            if n:
                log("  gate: OPEN - %s" % why)
            return True
        if time.time() >= deadline:
            log("GPU gate never opened before the deadline (%s)" % why)
            return False
        if n == 0:
            log("  gate: CLOSED - %s" % why)
            log("waiting on the GPU gate (poll %ss)..." % poll_s)
        n += 1
        time.sleep(poll_s)


def file_stable(path, recheck_s, skip_sleep=False):
    """Byte size when the file exists AND has stopped growing; else None."""
    if not path or not os.path.isfile(path):
        return None
    s1 = os.path.getsize(path)
    if s1 <= 0:
        return None
    if skip_sleep:
        return s1
    log("  file: present %s bytes (%.3f GiB) - rechecking in %ss"
        % ("{:,}".format(s1), s1 / GIB, recheck_s))
    time.sleep(recheck_s)
    if not os.path.isfile(path):
        log("  file: vanished during the recheck")
        return None
    s2 = os.path.getsize(path)
    if s2 != s1:
        log("  file: STILL GROWING %s -> %s bytes - not ready"
            % ("{:,}".format(s1), "{:,}".format(s2)))
        return None
    log("  file: STABLE at %s bytes (%.3f GiB)" % ("{:,}".format(s2), s2 / GIB))
    return s2


# ---------------------------------------------------------------------------
# the two child processes - both through gpu_lock, never bare Popen
# ---------------------------------------------------------------------------

def run_tokenize(ctx, model_path, name):
    """This model's OWN token count for the corpus - rule 6 needs it for bpb.

    Vocab-level work, no GPU compute, but llama-tokenize is on gpu_lock's
    SERVER_TOOLS list and this process already holds the lock, so it is
    launched through serve() like everything else: capped, and dead when this
    process dies.
    """
    argv = [ctx["tokenize_bin"], "-m", model_path, "-f", ctx["corpus"],
            "--show-count", "--ids"]
    out = os.path.join(ctx["scratch"], "tok-%s.txt" % name)
    err = os.path.join(ctx["scratch"], "tok-%s.err" % name)
    try:
        with io.open(out, "wb") as fo, io.open(err, "wb") as fe:
            proc = gpu_lock.serve(argv, tag="quant-ladder:tokenize",
                                  stdout=fo, stderr=fe)
            try:
                proc.wait(timeout=TOKENIZE_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                log("  tokenize: TIMEOUT (%ss) - killing" % TOKENIZE_TIMEOUT_S)
                proc.kill()
                return None
    except gpu_lock.DryRunViolation:
        raise
    except Exception as exc:                             # noqa: BLE001
        log("  tokenize: launch failed: %s" % exc)
        return None
    # --ids emits the whole corpus as ONE ~1.7 MB line; read the tail by
    # seeking rather than walking the file backwards for a newline.
    n = None
    try:
        with io.open(out, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            take = min(4096, fh.tell())
            fh.seek(-take, os.SEEK_END)
            tail = fh.read(take).decode("ascii", "replace")
        m = re.search(r"(?i)total number of tokens:\s*(\d+)", tail)
        if m:
            n = int(m.group(1))
    except OSError as exc:
        log("  tokenize: tail read failed: %s" % exc)
    for f in (out, err):
        try:
            os.unlink(f)
        except OSError:
            pass
    log("  tokenize: %s" % ("{:,} tokens".format(n) if n else "no count parsed"))
    return n


def run_perplexity(ctx, model_path, name, chunks):
    """One llama-perplexity pass at the manifest's conditions."""
    log_err = os.path.join(ctx["outdir"], "ppl-%s.log" % name)
    log_out = os.path.join(ctx["outdir"], "ppl-%s.out.log" % name)
    argv = ([ctx["ppl_bin"], "-m", model_path, "-f", ctx["corpus"]]
            + [str(x) for x in ctx["ppl_flags"]])
    if chunks:
        argv += ["--chunks", str(chunks)]
    log("  ppl: %s" % " ".join(argv))
    t0 = time.time()
    code = -1
    try:
        with io.open(log_out, "wb") as fo, io.open(log_err, "wb") as fe:
            proc = gpu_lock.serve(argv, tag="quant-ladder:%s" % name,
                                  stdout=fo, stderr=fe)
            try:
                code = proc.wait(timeout=PPL_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                log("  ppl: TIMEOUT (90 min) - killing")
                proc.kill()
                return {"ok": False, "reason": "timeout",
                        "wall_s": round(time.time() - t0, 1)}
    except gpu_lock.DryRunViolation:
        raise
    except Exception as exc:                             # noqa: BLE001
        log("  ppl: launch failed: %s" % exc)
        return {"ok": False, "reason": "launch",
                "wall_s": round(time.time() - t0, 1)}
    wall = round(time.time() - t0, 1)

    txt = ""
    for f in (log_err, log_out):
        if os.path.isfile(f):
            with io.open(f, "r", encoding="utf-8", errors="replace") as fh:
                txt += fh.read()
    fin = re.search(r"Final estimate:\s*PPL\s*=\s*([0-9.]+)\s*\+/-\s*([0-9.]+)", txt)
    chk = re.search(r"calculating perplexity over\s+(\d+)\s+chunks,\s*n_ctx=(\d+)", txt)
    if not fin:
        why = "no-final-estimate"
        if re.search(r"(?i)error loading model|failed to load|invalid magic|"
                     r"tensor .* data is not within the file bounds", txt):
            why = "model-load-failed (file may still be incomplete)"
        log("  ppl: FAILED exit=%s reason=%s" % (code, why))
        for line in txt.splitlines()[-8:]:
            log("    | " + line)
        return {"ok": False, "reason": why, "wall_s": wall}
    return {"ok": True,
            "ppl": float(fin.group(1)),
            "err": float(fin.group(2)),
            "chunks": int(chk.group(1)) if chk else 0,
            "n_ctx": int(chk.group(2)) if chk else 0,
            "wall_s": wall,
            "exit": code}


# ---------------------------------------------------------------------------
# one rung
# ---------------------------------------------------------------------------

def measure_rung(ctx, rung, model_path, size_bytes):
    """Denominator, token count, perplexity, one RESULT line. One GPU job."""
    name = str(rung["name"])
    log("--- RUNG %s (%s) %.3f GiB ---"
        % (name, rung.get("role"), size_bytes / GIB))

    # Denominator first: it is cheap, it needs no GPU, and a rung whose header
    # cannot be read should say so now and not after an hour of perplexity.
    declared = rung.get("params")
    hp = header_params(model_path)
    if hp:
        params = int(hp["params"])
        params_src = "gguf-header"
        bpw_tensors = "%.4f" % hp["bpw_from_tensors"]
        if int(hp["size_bytes"]) != int(size_bytes):
            log("  bpw: WARNING file size moved between the gate (%d) and the "
                "header read (%d)" % (size_bytes, hp["size_bytes"]))
        if declared:
            log("  bpw: params=%d from the file's own header (manifest declared "
                "%d, %.3f%% off); tensor-table cross-check %.4f bpw"
                % (params, int(declared),
                   100.0 * (float(declared) - params) / params,
                   hp["bpw_from_tensors"]))
        else:
            log("  bpw: params=%d from the file's own header; tensor-table "
                "cross-check %.4f bpw" % (params, hp["bpw_from_tensors"]))
        # Rule 4: two cheap metrics that AGREE beat one expensive metric, so a
        # disagreement is said out loud rather than averaged away. An
        # unrecognised ggml type id contributes elements but zero bytes, which
        # drags bpw_tensors far below the figure a reader should use - measured
        # 2026-08-29, the NVFP4 file's TYPE_40 tensors put the two 1,180% apart.
        agree = hp.get("agreement_pct")
        if not hp.get("tensor_table_complete"):
            log("  bpw: cross-check INCOMPLETE - unrecognised ggml types %s. "
                "bpw_tensors reads low; the file-size figure is the one to "
                "publish." % ", ".join(hp.get("unknown_types") or []))
            ledger_append(
                ctx["ledger"],
                "NOTE %s | bpw cross-check INCOMPLETE: unrecognised ggml types "
                "%s, so bpw_tensors=%.4f reads low against bpw=%.4f (%.1f%% "
                "apart). The file-size figure is the measured one; the "
                "tensor-table figure is not a second witness for this file "
                "(rule 4). | ts=%s"
                % (name, ", ".join(hp.get("unknown_types") or []),
                   hp["bpw_from_tensors"], size_bytes * 8.0 / params,
                   agree if agree is not None else float("nan"), stamp()))
        elif agree is not None and abs(agree) > 1.0:
            ledger_append(
                ctx["ledger"],
                "NOTE %s | bpw cross-check DISAGREES by %.3f%%: %.4f from the "
                "file size against %.4f from the tensor table, with every ggml "
                "type recognised. Header overhead alone is a few thousandths "
                "of a bit, so this file is not what its table says it is - a "
                "split file, or trailing data (rule 4). | ts=%s"
                % (name, agree, size_bytes * 8.0 / params,
                   hp["bpw_from_tensors"], stamp()))
    elif declared:
        params = int(declared)
        params_src = "manifest-declared"
        # 'na', not 0: a zero in a bits-per-weight column is a number, and a
        # number nobody measured is the failure this labelling exists to stop.
        bpw_tensors = "na"
        log("  bpw: FALLBACK to the manifest's declared %d - this rung's bpw "
            "is DERIVED, not measured (rule 1), and the ledger says so" % params)
    else:
        log("  bpw: no header read and no declared parameter count - this rung "
            "has no denominator and is not measurable")
        return {"ok": False, "reason": "no-parameter-count", "wall_s": 0.0}

    with gpu_lock.guard("quant-ladder:%s" % name):
        ntok = run_tokenize(ctx, model_path, name)
        res = run_perplexity(ctx, model_path, name, rung.get("chunks"))
    if not res["ok"]:
        return res

    eval_tok = int(res["chunks"]) * int(res["n_ctx"])
    tok_src = "tokenize"
    if not ntok:
        ntok = eval_tok
        tok_src = "eval"
    bpw = size_bytes * 8.0 / params
    bpb = (math.log(res["ppl"]) * ntok) / (LN2 * ctx["corpus_bytes"])
    comparable = "yes" if rung.get("ppl_comparable", True) is not False \
        else "NO-different-tokenizer"

    # params= is the denominator actually used; params_src= says which of rule
    # 1's three categories the bpw beside it belongs to; params_declared= keeps
    # the manifest's number so the correction stays auditable; bpw_tensors= is
    # the independent second measurement (rule 4). All written NOW, because a
    # field not written during the run cannot be recovered (rule 28).
    line = ("RESULT %s | role=%s | file=%s | bytes=%d | GiB=%.3f | params=%d | "
            "params_src=%s | params_declared=%s | bpw=%.4f | bpw_tensors=%s | "
            "PPL=%.4f | err=%.5f | chunks=%d | n_ctx=%d | eval_tokens=%d | "
            "tokens=%d | tok_src=%s | bpb=%.4f | ppl_comparable=%s | "
            "wall_s=%s | ts=%s | runner=run-ladder.py"
            % (name, rung.get("role"), leaf(model_path), size_bytes,
               size_bytes / GIB, params, params_src,
               int(declared) if declared else "none", bpw, bpw_tensors,
               res["ppl"], res["err"], res["chunks"], res["n_ctx"], eval_tok,
               ntok, tok_src, bpb, comparable, res["wall_s"], stamp()))
    ledger_append(ctx["ledger"], line)
    return res


# ---------------------------------------------------------------------------
# anchor gate and conditional pass 2
# ---------------------------------------------------------------------------

def check_rig_gate(ctx, rung, res):
    """The anchor check. False means the campaign halts."""
    exp = rung.get("expected_ppl")
    if exp is None:
        return True
    exp = float(exp)
    tol = float(rung.get("tolerance_pct", 0.5))
    rel = 100.0 * abs(res["ppl"] - exp) / exp
    verdict = "PASS" if rel <= tol else "DRIFT"
    ledger_append(ctx["ledger"],
                  "RIGGATE %s | expected=%.4f | measured=%.4f | delta_pct=%.3f "
                  "| tol_pct=%s | %s" % (rung["name"], exp, res["ppl"], rel,
                                         tol, verdict))
    if verdict == "DRIFT" and rung.get("abort_on_drift"):
        ledger_append(ctx["ledger"],
                      "ABORT RIG-DRIFT %s: measured %.4f vs expected %.4f "
                      "(%.3f%% > %s%%). Campaign halted; nothing else measured."
                      % (rung["name"], res["ppl"], exp, rel, tol))
        return False
    partner = rung.get("pair_with")
    if partner:
        other = ledger_field(ctx["ledger"], str(partner), "PPL")
        if other:
            gap = 100.0 * (res["ppl"] - float(other)) / float(other)
            floor = float(rung.get("pair_min_gap_pct", 0.0))
            ok = "RESOLVED" if gap >= floor else "COLLAPSED"
            ledger_append(ctx["ledger"],
                          "RIGPAIR %s vs %s | gap_pct=%.3f | min=%s | %s"
                          % (rung["name"], partner, gap, floor, ok))
            if ok == "COLLAPSED":
                ledger_append(ctx["ledger"],
                              "ABORT RIG-RESOLUTION: the two anchors no longer "
                              "separate; the rig cannot rank quants today.")
                return False
    return True


def update_conditionals(ctx, rungs):
    """Pass 2 is conditional: enable an infill rung only where the curve steepens.

    Relative PPL gap across the bracket >= factor x the gap of the pair above.
    Mechanical, logged, and overridable by hand with an enable-<name>.flag file.
    """
    for r in rungs:
        if not r.get("conditional"):
            continue
        flag = os.path.join(ctx["outdir"], "enable-%s.flag" % r["name"])
        if os.path.exists(flag):
            continue
        c = r.get("condition") or {}
        try:
            a = ledger_field(ctx["ledger"], str(c["between"][0]), "PPL")
            b = ledger_field(ctx["ledger"], str(c["between"][1]), "PPL")
            x = ledger_field(ctx["ledger"], str(c["reference_pair"][0]), "PPL")
            y = ledger_field(ctx["ledger"], str(c["reference_pair"][1]), "PPL")
        except (KeyError, IndexError):
            continue
        if not (a and b and x and y):
            continue
        gap = (float(b) - float(a)) / float(a)
        ref = (float(y) - float(x)) / float(x)
        ratio = gap / ref if ref > 0 else 999.0
        factor = float(c.get("factor", 1.5))
        if ratio >= factor:
            with io.open(flag, "w", encoding="utf-8") as fh:
                fh.write("auto-enabled %s: gap(%s->%s)=%.2f%% is %.2fx "
                         "gap(%s->%s)=%.2f%%\n"
                         % (stamp(), c["between"][0], c["between"][1],
                            gap * 100, ratio, c["reference_pair"][0],
                            c["reference_pair"][1], ref * 100))
            ledger_append(ctx["ledger"],
                          "PASS2-ENABLE %s | bracket_gap_pct=%.3f | "
                          "ref_gap_pct=%.3f | ratio=%.2f | factor=%s | ENABLED"
                          % (r["name"], gap * 100, ref * 100, ratio, factor))
        else:
            log("pass2 %s: not enabled (ratio %.2f < %s)"
                % (r["name"], ratio, factor))


def rung_enabled(ctx, rung):
    if rung.get("enabled"):
        return True
    return os.path.exists(os.path.join(ctx["outdir"],
                                       "enable-%s.flag" % rung["name"]))


def run_detectors(ctx, name):
    """detectors.ps1, where a PowerShell host exists; a NOTE line where it does not.

    Perplexity RANKS the rungs; detectors DISQUALIFY them - a quant can hold a
    respectable PPL and still loop, lose its chat template, or fail to close a
    fenced block. Those probes are PowerShell and stay PowerShell. Where none
    can run, the ledger says the axis was not measured, because a silently
    skipped axis reads to a report writer as a measured negative (rule 2).
    """
    script = os.path.join(HERE, "detectors.ps1")
    host = shutil.which("pwsh") or shutil.which("powershell")
    if not host or not os.path.isfile(script):
        ledger_append(
            ctx["ledger"],
            "NOTE %s | detectors NOT RUN: %s. Perplexity ranks this rung; the "
            "disqualifier probes (repetition D1-D4, exact-JSON echo, fenced "
            "block) did not run, so this rung carries a rank and NO "
            "disqualifier evidence. Run detectors.ps1 on a PowerShell host, or "
            "report the rung as undisqualified rather than as passing. | ts=%s"
            % (name, "no PowerShell host on this machine" if not host
               else "detectors.ps1 is missing", stamp()))
        return
    log("  running detectors for %s" % name)
    p = subprocess.run([host, "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-File", script, "-Manifest", ctx["manifest_path"],
                        "-Only", name, "-SkipGate"])
    # A non-zero exit is the same reading as no PowerShell host: the axis was
    # not measured. detectors.ps1 writes its verdicts into its OWN ledger, so
    # without this line THIS ledger would carry a perplexity rank for the rung
    # and nothing at all about the disqualifier probes - a skipped axis read as
    # a measured negative, which the paragraph above forbids.
    if p.returncode != 0:
        ledger_append(
            ctx["ledger"],
            "NOTE %s | detectors EXITED %d: the probe pass did not complete. "
            "Read the detector ledger beside this one before treating the rung "
            "as undisqualified - detectors.ps1 writes a DETECT row for what it "
            "reached, and a rung with no row was not probed. This rung's rank "
            "stands; its disqualifier axis does not. | ts=%s"
            % (name, p.returncode, stamp()))


# ---------------------------------------------------------------------------
# the plan
# ---------------------------------------------------------------------------

def rung_state(ctx, rung):
    """What the ledger already says about this rung."""
    name = rung["name"]
    if ledger_has(ctx["ledger"], "RESULT %s " % name):
        return "DONE"
    if ledger_has(ctx["ledger"], "FAILED %s " % name):
        return "FAILED"
    if not rung_enabled(ctx, rung):
        return "disabled"
    return "pending"


def pending_rungs(ctx, rungs, all_rungs=None):
    """Manifest order, minus everything the ledger has already settled.

    Rig gates first and absolutely: until every rig-gate rung has a RESULT
    line, nothing else is runnable, because a ladder measured on a drifting
    rig ranks nothing. `all_rungs` is the WHOLE manifest even when `--only`
    has narrowed what may run - otherwise `--only` on a pass-1 rung would
    quietly measure it on an unverified rig, which is the one thing the anchor
    gate exists to prevent.
    """
    gates_done = all(
        ledger_has(ctx["ledger"], "RESULT %s " % r["name"])
        for r in (all_rungs if all_rungs is not None else rungs)
        if r.get("role") == "rig-gate")
    out = []
    for r in sorted(rungs, key=lambda x: int(x.get("order", 0))):
        if rung_state(ctx, r) != "pending":
            continue
        if not gates_done and r.get("role") != "rig-gate":
            continue
        out.append(r)
    return out, gates_done


def print_plan(ctx, man, rungs, all_rungs, measure_headers=True):
    """Everything a run would resolve, before a single GPU second is spent."""
    print("PLAN")
    print("  manifest        %s" % ctx["manifest_path"])
    print("  campaign / slug %s / %s"
          % (man.get("campaign", "?"), ctx["slug"]))
    print("  repo root       %s" % paths.repo_root())
    print("  outdir          %s%s"
          % (ctx["outdir"], "" if os.path.isdir(ctx["outdir"])
             else "   (would be created)"))
    if ctx["manifest_outdir"] and os.path.normcase(os.path.abspath(
            ctx["manifest_outdir"])) != os.path.normcase(ctx["outdir"]):
        print("                  manifest names %s - NOT used; the outdir is "
              "derived from this repo" % ctx["manifest_outdir"])
    print("  ledger          %s%s"
          % (ctx["ledger"], "" if os.path.isfile(ctx["ledger"])
             else "   (new)"))
    print("  heartbeat       %s" % ctx["heartbeat"])
    print()
    print("  llama-perplexity %s" % ctx["ppl_bin"])
    print("  llama-tokenize   %s" % ctx["tokenize_bin"])
    print("  corpus           %s" % ctx["corpus"])
    print("  corpus gate      %s  [%s]"
          % ("PASS" if ctx["corpus_ok"] else "FAIL", ctx["corpus_detail"]))
    print()
    ppl = man.get("ppl") or {}
    print("  ppl flags        %s" % " ".join(str(x) for x in ctx["ppl_flags"]))
    print("  KV               %s" % ppl.get("kv", "f16 (llama.cpp default)"))
    gate = man.get("gate") or {}
    ok, why = manifest_gate(gate)
    print("  manifest gate    %s - %s" % ("OPEN" if ok else "CLOSED", why))
    held = gpu_lock.holder()
    print("  rule-20 lock     %s"
          % ("free" if not held else "HELD by pid %s, tag %r since %s"
             % (held.get("pid"), held.get("tag"), held.get("acquired"))))
    print()

    n_ctx = 0
    flags = [str(x) for x in ctx["ppl_flags"]]
    if "-c" in flags:
        try:
            n_ctx = int(flags[flags.index("-c") + 1])
        except (IndexError, ValueError):
            n_ctx = 0
    hdr = ("  %-24s %5s %-12s %-9s %13s %9s %9s"
           % ("rung", "order", "role", "state", "file", "GiB", "bpw"))
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for r in sorted(rungs, key=lambda x: int(x.get("order", 0))):
        state = rung_state(ctx, r)
        mp = resolve_model(r)
        size = os.path.getsize(mp) if mp else 0
        bpw = "?"
        if mp and measure_headers:
            hp = header_params(mp, quiet=True)
            if hp:
                bpw = "%.4f" % hp["bpw"]
        print("  %-24s %5s %-12s %-9s %13s %9s %9s"
              % (r["name"], r.get("order"), r.get("role"), state,
                 "present" if mp else "MISSING",
                 "%.3f" % (size / GIB) if size else "-", bpw))
        if mp:
            print("      %s" % mp)
        want = r.get("chunks")
        if want and n_ctx and int(want) * n_ctx != 294912:
            print("      NOTE chunks %s x n_ctx %s = %s token positions, not "
                  "rule 6's 294,912" % (want, n_ctx, int(want) * n_ctx))
    print()
    pend, gates_done = pending_rungs(ctx, rungs, all_rungs)
    print("  rig gates complete: %s" % ("yes" if gates_done else "NO - "
                                        "nothing else is runnable until they are"))
    print("  pending queue (%d): %s"
          % (len(pend), ", ".join(r["name"] for r in pend) or "(none - every "
             "rung has a RESULT or FAILED line; the manifest is exhausted)"))
    return pend


def write_heartbeat(ctx, npass, pending, gates_done):
    try:
        with io.open(ctx["heartbeat"], "w", encoding="utf-8") as fh:
            fh.write("%s pass=%d pending=%d gatesDone=%s vram=%dMiB pid=%d "
                     "runner=run-ladder.py\n"
                     % (stamp(), npass, pending, gates_done, vram_used_mib(),
                        os.getpid()))
    except OSError:
        pass


# ---------------------------------------------------------------------------
# the loop
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest",
                    default=os.path.join(HERE, "ladder-manifest.json"),
                    help="ladder manifest (default: the one beside this script)")
    ap.add_argument("--outdir", default=None,
                    help="where the ledger and logs go (default: "
                         "<repo>/results/<slug>/data/quant-ladder)")
    ap.add_argument("--slug", default=None,
                    help="campaign slug; default is the manifest's")
    ap.add_argument("--deadline-minutes", type=int, default=480,
                    help="stop starting new rungs after this long (default 480)")
    ap.add_argument("--once", action="store_true",
                    help="measure exactly one rung and exit - for a platform "
                         "that kills long tasks")
    ap.add_argument("--only", default=None,
                    help="restrict to one rung by name")
    ap.add_argument("--no-detectors", action="store_true",
                    help="skip the PowerShell disqualifier probes after each rung")
    ap.add_argument("--dry-run", action="store_true",
                    help="resolve everything, print the plan, prove the GPU "
                         "gate refuses - and launch nothing")
    ap.add_argument("--list", action="store_true",
                    help="the plan without the header reads or the gate proof")
    args = ap.parse_args()

    # A dry run must never take the GPU. gpu_lock refuses outright under this
    # variable, which turns "the plan accidentally launched something" from a
    # wasted hour into a stack trace.
    if args.dry_run:
        os.environ.setdefault(gpu_lock.DRY_RUN_ENV, "1")
    elif os.environ.get(gpu_lock.DRY_RUN_ENV):
        raise SystemExit(
            "%s is set in the environment but --dry-run was not passed. Every "
            "launch would raise DryRunViolation partway through the ladder, "
            "after the file gate had already waited. Pass --dry-run, or unset "
            "the variable deliberately." % gpu_lock.DRY_RUN_ENV)

    man = load_manifest(os.path.abspath(args.manifest))
    slug = args.slug or man.get("slug") or "unknown"
    outdir = os.path.abspath(args.outdir) if args.outdir else os.path.join(
        paths.repo_root(), "results", slug, "data", "quant-ladder")
    ppl = man.get("ppl") or {}
    tok = man.get("tokenize") or {}
    corpus = resolve_corpus(man)
    corpus_ok, corpus_detail = check_corpus(corpus, man)

    ctx = {
        "manifest_path": os.path.abspath(args.manifest),
        "manifest_outdir": man.get("outdir"),
        "slug": slug,
        "outdir": outdir,
        "ledger": os.path.join(outdir, "results.txt"),
        "heartbeat": os.path.join(outdir, "heartbeat.txt"),
        "scratch": outdir,
        "corpus": corpus,
        "corpus_bytes": os.path.getsize(corpus),
        "corpus_ok": corpus_ok,
        "corpus_detail": corpus_detail,
        "ppl_bin": resolve_bin("llama-perplexity", ppl.get("exe")),
        "tokenize_bin": resolve_bin("llama-tokenize", tok.get("exe")),
        "ppl_flags": ppl.get("flags") or ["-ngl", "99", "-c", "8192",
                                          "-fa", "on", "--load-mode", "mmap"],
    }
    all_rungs = man["rungs"]
    rungs = all_rungs
    if args.only:
        rungs = [r for r in rungs if r["name"] == args.only]
        if not rungs:
            raise SystemExit("--only %r matches no rung in %s"
                             % (args.only, ctx["manifest_path"]))
        # --only narrows what RUNS; it may not narrow what the rig has to
        # prove. A pass-1 rung measured before the anchors are back is a
        # number with no rig behind it (rule 3).
        missing = [r["name"] for r in all_rungs if r.get("role") == "rig-gate"
                   and not ledger_has(ctx["ledger"], "RESULT %s " % r["name"])]
        if missing and rungs[0].get("role") != "rig-gate":
            raise SystemExit(
                "--only %s, but the rig gate(s) %s have no RESULT line in\n"
                "  %s\n"
                "A rung measured before the anchors are re-confirmed is a "
                "number with no rig behind it. Run the gates first:\n"
                "    python %s --only %s"
                % (args.only, ", ".join(missing), ctx["ledger"],
                   os.path.relpath(os.path.abspath(__file__),
                                   paths.repo_root()).replace("\\", "/"),
                   missing[0]))

    if args.list or args.dry_run:
        pend = print_plan(ctx, man, rungs, all_rungs,
                          measure_headers=not args.list)
        if not ctx["corpus_ok"]:
            print()
            print("CORPUS GATE FAILS - a real run stops here (rule 23).")
            return 1
        if args.list:
            return 0
        # The gate proof. This calls the SAME measure_rung() a real run calls;
        # under MEASURED_INFERENCE_DRY_RUN gpu_lock.guard() refuses before any
        # child is spawned, which is the property being demonstrated.
        print()
        print("GPU GATE PROOF (%s=1)" % gpu_lock.DRY_RUN_ENV)
        target = None
        for r in pend:
            mp = resolve_model(r)
            if mp:
                target = (r, mp)
                break
        if not target:
            print("  not exercised: no pending rung has its weight file on "
                  "this machine, so there is nothing this run would launch.")
            return 0
        r, mp = target
        print("  first rung this run would measure: %s" % r["name"])
        try:
            measure_rung(ctx, r, mp, os.path.getsize(mp))
        except gpu_lock.DryRunViolation as exc:
            print("  REFUSED, as it must:")
            for line in str(exc).splitlines():
                print("    %s" % line)
            print("  No child process was spawned and no ledger line was "
                  "written.")
            return 0
        print("  NOT REFUSED - the launch path bypassed gpu_lock. That is a "
              "rule-20 defect in this file.")
        return 1

    if not ctx["corpus_ok"]:
        log("FATAL: the frozen corpus does not match the manifest's pin - %s"
            % ctx["corpus_detail"])
        log("Rule 23: a ladder that silently changes its corpus is comparing "
            "nothing. Restore the pinned file or re-pin the manifest "
            "deliberately.")
        return 1

    if not os.path.isdir(outdir):
        os.makedirs(outdir)
    if not os.path.isfile(ctx["ledger"]):
        with io.open(ctx["ledger"], "w", encoding="utf-8") as fh:
            fh.write("# quant-ladder ledger - opened %s\n" % stamp())

    gate = man.get("gate") or {}
    poll_s = int(gate.get("poll_s") or 60)
    fg = man.get("file_gate") or {}
    recheck_s = int(fg.get("recheck_s") or 60)
    min_frac = float(fg.get("min_frac_of_expected") or 0.95)
    suspect_max = int(fg.get("suspect_passes_before_accept") or 20)
    deadline = time.time() + args.deadline_minutes * 60

    log("=== quant-ladder runner up (run-ladder.py). deadline %s. manifest %s ==="
        % (time.strftime("%m-%d %H:%M", time.localtime(deadline)),
           ctx["manifest_path"]))
    log("corpus %s (%s bytes) - %s"
        % (ctx["corpus"], "{:,}".format(ctx["corpus_bytes"]), ctx["corpus_detail"]))
    log("llama-perplexity %s" % ctx["ppl_bin"])

    attempts, suspect, npass = {}, {}, 0
    rc = 0
    while True:
        npass += 1
        if time.time() >= deadline:
            log("DEADLINE reached - stopping")
            break
        if ledger_has(ctx["ledger"], "ABORT "):
            log("ABORT line present in the ledger - stopping")
            break

        update_conditionals(ctx, rungs)
        pend, gates_done = pending_rungs(ctx, rungs, all_rungs)
        write_heartbeat(ctx, npass, len(pend), gates_done)

        if not pend:
            if gates_done:
                log("MANIFEST EXHAUSTED - every rung has a RESULT or FAILED line")
                break
            if args.once:
                log("--once: nothing runnable right now")
                break
            log("nothing runnable (pass %d); sleeping %ss" % (npass, poll_s))
            time.sleep(poll_s)
            continue

        progressed = False
        for r in pend:
            if time.time() >= deadline:
                break
            name = str(r["name"])
            log("checking %s (order %s, %s)" % (name, r.get("order"), r.get("role")))
            mp = resolve_model(r)
            if not mp:
                continue
            size = file_stable(mp, recheck_s)
            if not size:
                continue

            expected_gib = float(r.get("expected_gib") or 0)
            if expected_gib and size < expected_gib * GIB * min_frac:
                suspect[name] = suspect.get(name, 0) + 1
                if suspect[name] < suspect_max:
                    log("  %s: stable but only %.3f GiB vs expected %s GiB - "
                        "holding (%d passes)"
                        % (name, size / GIB, expected_gib, suspect[name]))
                    continue
                log("  %s: SIZE-DEVIATION accepted after %d stable passes "
                    "(%.3f GiB vs expected %s)"
                    % (name, suspect[name], size / GIB, expected_gib))
                ledger_append(ctx["ledger"],
                              "NOTE %s | size %.3f GiB is %.1f%% of the expected "
                              "%s GiB - measured anyway after %d stable rechecks"
                              % (name, size / GIB,
                                 100.0 * size / (GIB * expected_gib),
                                 expected_gib, suspect[name]))

            if not wait_gate(gate, deadline, poll_s):
                break
            # The GPU wait can be long: re-confirm the file did not change.
            size2 = os.path.getsize(mp)
            if size2 != size:
                log("  %s: file changed while waiting for the GPU - skipping "
                    "this pass" % name)
                continue

            try:
                res = measure_rung(ctx, r, mp, size)
            except gpu_lock.GpuBusy as exc:
                log("  %s: the rule-20 lock is held - %s" % (name, exc))
                break
            if not res["ok"]:
                attempts[name] = attempts.get(name, 0) + 1
                log("  %s: attempt %d failed (%s)"
                    % (name, attempts[name], res["reason"]))
                if attempts[name] >= 3:
                    ledger_append(ctx["ledger"],
                                  "FAILED %s | reason=%s | attempts=%d | ts=%s"
                                  % (name, res["reason"], attempts[name], stamp()))
                progressed = True
                break

            if r.get("role") == "rig-gate" and not check_rig_gate(ctx, r, res):
                log("RIG GATE FAILED - halting the campaign")
                return 2

            if not args.no_detectors:
                run_detectors(ctx, name)

            progressed = True
            break

        if args.once:
            log("--once: done")
            break
        if not progressed:
            log("no rung was runnable this pass; sleeping %ss" % poll_s)
            time.sleep(poll_s)

    left, _ = pending_rungs(ctx, rungs, all_rungs)
    if left:
        # Earned by the quant-ladder deadline exit of 2026-08-23: a clean exit
        # with work outstanding reads to every completion-based watcher as
        # success, and 2.5 hours of idle GPU followed.
        log("!!! EXITING WITH %d RUNG(S) PENDING: %s"
            % (len(left), ", ".join(r["name"] for r in left)))
        log("!!! This is NOT a completed ladder. Re-run to continue; every "
            "rung with a RESULT or FAILED line is skipped.")
        if not args.once:
            rc = 3
    log("RUN-LADDER DONE")
    return rc


if __name__ == "__main__":
    sys.exit(main())
