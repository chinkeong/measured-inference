"""One GPU job at a time — enforced in the OS, not requested in prose.

    python gpu_lock.py status      # who holds the lock, what servers are live
    python gpu_lock.py kill        # kill every llama-server, clear a stale lock
    python gpu_lock.py release     # clear a stale lock, leave processes alone

WHY THIS FILE EXISTS. Rule 20 says "one GPU job at a time". It was a sentence
in AGENTS.md and nothing else, so it held exactly as long as every caller
remembered it. On 2026-08-29 it stopped holding and took the machine down:

    23:59:11  Windows - Virtual Memory Minimum Too Low (pagefile auto-grows)
    23:59:11  Volsnap 25 - shadow copies on C: deleted, storage could not grow
    00:04:15  Windows - Out of Virtual Memory
    00:04:16  Resource-Exhaustion-Detector 2004, then 16 more, every 1-3 min:
                llama-server.exe (41604) consumed 19,815,084,032 bytes
                llama-server.exe (37864) consumed 18,742,063,104 bytes
                llama-server.exe (41852) consumed 18,741,641,216 bytes
    00:23:38  last event ever written - the box is thrashing, UI is gone
    00:25:07  kernel's last checkpoint (EventLog 6008: shutdown was unexpected)
    00:31:59  power button, held by a human with no other option
    00:32:58  boot

Kernel-Power 41 recorded BugcheckCode = 0 and left no dump: not a crash, not a
driver, not hardware. Four llama-server processes (pids 41604, 36772, 41852,
37864) were alive at once on a 31.8 GB / 59.8 GB-commit machine. The top three
alone wanted ~53 GB. Nothing killed them because nothing was watching.

Three separate holes let that happen, and this module closes all three:

  1. NO MUTEX. Twenty scripts under scripts/ call subprocess.Popen on
     llama-server directly. Each one is correct alone. Any two at once is the
     incident. -> acquire(): a machine-wide lockfile with liveness checking,
     so the second caller fails in one second with a message naming the first.

  2. ORPHANS OUTLIVE THEIR PARENT. A detached or agent-spawned run whose parent
     dies leaves llama-server holding 18 GB forever; the next run starts on top
     of it. AGENTS.md's crash-resume step 3 already says "a detached
     llama-server may have outlived the session - kill it", which is a manual
     step that a fresh agent skips. -> serve(): the child is put in a Windows
     Job Object with KILL_ON_JOB_CLOSE, so it cannot outlive the process that
     started it, even on SIGKILL of the parent.

  3. NO CEILING. llama-server will happily commit until Windows dies rather
     than fail its own allocation. -> serve(): the same job object carries
     JOB_OBJECT_LIMIT_JOB_MEMORY. A runaway now dies with a clean allocation
     failure in ITS log instead of taking the desktop with it. On POSIX the
     equivalent is RLIMIT_AS on the child.

Plus a preflight the incident would have tripped at 23:59: refuse to launch
when system commit is already past COMMIT_REFUSE_FRAC of the limit. All four
guards are advisory-free — a caller that forgets serve() and calls Popen
directly is still unguarded, which is why every launcher in this repo was
converted. Grep for `subprocess.Popen` near a server binary before adding one.

WHAT THIS DOES NOT DO. It does not serialize a llama-server you started by
hand in another terminal, and it does not know about LM Studio. Those show up
in `status` as foreign servers and block acquire(), which is the most it can
honestly do.

Stdlib only, by design: this has to work on a bare box before setup.* runs.
"""

import ctypes
import errno
import json
import os
import platform
import subprocess
import sys
import tempfile
import time

# ---------------------------------------------------------------------------
# BUDGET. Defaults chosen against the machine in the incident above (31.8 GB
# RAM, 28 GB pagefile, 59.8 GB commit limit). One job at 0.75 x RAM = 23.8 GB
# against a 59.8 GB limit leaves the desktop the whole pagefile as slack, which
# is rule 14's anti-spill budget applied to host RAM instead of VRAM.
# ---------------------------------------------------------------------------
MEM_CAP_FRAC = 0.75          # per-job commit cap, as a fraction of physical RAM
COMMIT_REFUSE_FRAC = 0.55    # refuse to launch if system commit is already here
STALE_LOCK_GRACE_S = 5       # tolerate this much clock skew when stealing

_WINDOWS = os.name == "nt"

LOCK_PATH = os.environ.get(
    "MEASURED_INFERENCE_LOCK",
    os.path.join(os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                              "..", "..")),
                 ".gpu-lock.json"))

# Every llama.cpp tool that can hold the card. A lock that only knows
# llama-server reports "servers: none" while llama-perplexity holds 13 GB,
# and AGENTS.md's crash-recovery step 3 tells a resuming agent to trust it.
SERVER_TOOLS = ("llama-server", "llama-perplexity", "llama-cli", "llama-bench",
                "llama-tokenize", "llama-mtmd-cli", "llama-completion")
SERVER_NAMES = tuple(n + e for n in SERVER_TOOLS for e in ("", ".exe"))

_held = None      # our lock payload, once acquired
_jobs = []        # job-object handles kept alive for the life of this process


class GpuBusy(RuntimeError):
    """Another GPU job holds the lock, or a foreign llama-server is live."""


# ---------------------------------------------------------------------------
# Win32 / POSIX primitives
# ---------------------------------------------------------------------------

if _WINDOWS:
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    PROCESS_SET_QUOTA = 0x0100
    PROCESS_TERMINATE = 0x0001

    JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    JobObjectExtendedLimitInformation = 9

    class _FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", ctypes.c_uint32),
                    ("dwHighDateTime", ctypes.c_uint32)]

    class _MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_uint32),
                    ("dwMemoryLoad", ctypes.c_uint32),
                    ("ullTotalPhys", ctypes.c_uint64),
                    ("ullAvailPhys", ctypes.c_uint64),
                    ("ullTotalPageFile", ctypes.c_uint64),
                    ("ullAvailPageFile", ctypes.c_uint64),
                    ("ullTotalVirtual", ctypes.c_uint64),
                    ("ullAvailVirtual", ctypes.c_uint64),
                    ("ullAvailExtendedVirtual", ctypes.c_uint64)]

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [("ReadOperationCount", ctypes.c_uint64),
                    ("WriteOperationCount", ctypes.c_uint64),
                    ("OtherOperationCount", ctypes.c_uint64),
                    ("ReadTransferCount", ctypes.c_uint64),
                    ("WriteTransferCount", ctypes.c_uint64),
                    ("OtherTransferCount", ctypes.c_uint64)]

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                    ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", ctypes.c_uint32),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", ctypes.c_uint32),
                    ("Affinity", ctypes.POINTER(ctypes.c_ulong)),
                    ("PriorityClass", ctypes.c_uint32),
                    ("SchedulingClass", ctypes.c_uint32)]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
                    ("IoInfo", _IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]


def _memory_status():
    """(total_phys, commit_limit, commit_used) in bytes, or None if unknown."""
    if _WINDOWS:
        st = _MEMORYSTATUSEX()
        st.dwLength = ctypes.sizeof(st)
        if not _k32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return None
        return (st.ullTotalPhys,
                st.ullTotalPageFile,
                st.ullTotalPageFile - st.ullAvailPageFile)
    try:
        info = {}
        with open("/proc/meminfo") as fh:
            for line in fh:
                k, _, v = line.partition(":")
                info[k] = int(v.split()[0]) * 1024
        total = info["MemTotal"]
        limit = total + info.get("SwapTotal", 0)
        used = limit - info.get("MemAvailable", info["MemFree"]) - info.get("SwapFree", 0)
        return (total, limit, used)
    except Exception:
        return None


def mem_cap_bytes():
    """Per-job commit cap. MEASURED_INFERENCE_MEM_CAP_GB overrides."""
    override = os.environ.get("MEASURED_INFERENCE_MEM_CAP_GB")
    if override:
        return int(float(override) * (1 << 30))
    st = _memory_status()
    if not st:
        return 0
    return int(st[0] * MEM_CAP_FRAC)


def _alive(pid):
    if pid is None or pid <= 0:
        return False
    if _WINDOWS:
        h = _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return False
        code = ctypes.c_uint32()
        ok = _k32.GetExitCodeProcess(ctypes.c_void_p(h), ctypes.byref(code))
        _k32.CloseHandle(ctypes.c_void_p(h))
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(int(pid), 0)
    except OSError as e:
        return e.errno == errno.EPERM
    return True


def _start_time(pid):
    """Process creation time, to survive PID reuse. None if unavailable."""
    if _WINDOWS:
        h = _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return None
        c, e, k, u = _FILETIME(), _FILETIME(), _FILETIME(), _FILETIME()
        ok = _k32.GetProcessTimes(ctypes.c_void_p(h), ctypes.byref(c), ctypes.byref(e),
                                  ctypes.byref(k), ctypes.byref(u))
        _k32.CloseHandle(ctypes.c_void_p(h))
        if not ok:
            return None
        return (c.dwHighDateTime << 32) | c.dwLowDateTime
    try:
        with open("/proc/%d/stat" % int(pid)) as fh:
            return int(fh.read().rsplit(")", 1)[1].split()[19])
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Foreign servers — anything running llama-server that we did not start
# ---------------------------------------------------------------------------

def _posix_tool_name(pid, comm):
    """The llama.cpp tool this pid IS, under its real name, or None. POSIX only.

    Linux caps /proc/<pid>/comm at 15 characters (TASK_COMM_LEN is 16 including
    the NUL), so the kernel reports the two 16-character names in SERVER_TOOLS
    as `llama-perplexit` and `llama-completio`. Measured on bare-metal Ubuntu
    26.04 on 2026-08-31: comparing that for equality against SERVER_NAMES
    matched nothing, and every caller of live_servers() went blind at once —
    `status` printed "servers: none" and exited 0 while llama-perplexity held
    the card, which is the exact "is the card idle" check AGENTS.md's
    crash-recovery step 3 tells a resuming agent to trust; `kill` reported
    "killed 0 llama-server process(es)" and left them running; acquire()'s
    allow_foreign refusal never fired, so a sweep would launch a server on top
    of a resident perplexity pass — rule 20 defeated by a string length, and
    the host-commit shape of the 2026-08-29 incident this file was written for;
    and detect-machine.py, which uses live_servers() as its "is a model
    resident" gate, wrote desktop_reserve_mib stamped MEASURED with the note
    "with no llama.cpp process live" while a 13 GB perplexity model sat inside
    the memory.used reading — a wrong number wearing rule 1's MEASURED label,
    and it is the rule-14 anti-spill fence every rule-13 fit is priced against.
    rule 6 ranks quants with llama-perplexity over 294,912 token positions, so
    the tool the kernel truncates is also the longest-lived GPU job a campaign
    ever runs. scripts/quant-ladder/run-ladder.py measured this on 2026-08-30
    and worked around it locally, declining to patch another workstream's file;
    this is that fix, made once in the place both callers share.

    /proc/<pid>/exe is the exact test and needs no magic constant: it is the
    kernel's own link to the running image, untruncated, so its basename is the
    real tool name — and the real name is what we report, because a status line
    or a refusal message naming `llama-perplexit` sends an operator grepping for
    a process that does not exist. The comm test still runs when exe does not
    settle it, because exe can be unreadable (another user's process, without
    CAP_SYS_PTRACE) and it can legitimately disagree with the launched name (a
    wrapper script keeps the script's name in comm while exe is the interpreter;
    a symlinked launch keeps the link's name in comm while exe is the target).
    Both are consulted rather than one, because the asymmetry is not close: a
    false positive costs one refused launch and an operator ten seconds, a false
    negative is two resident models and a host that stops responding.

    The shape that false positive actually takes, so nobody has to rediscover it
    from a refusal message: a process whose name merely BEGINS with a tool name
    and runs past 15 characters is reported under the tool name it truncates to,
    even when /proc/<pid>/exe says otherwise. In the wild that is a versioned
    build — `llama-perplexity-b10717` reported as `llama-perplexity` — which is a
    process you positively want this gate to catch, so the behaviour is right and
    only the label is approximate. `pid` in the message is the exact thing; if it
    names a process you did not expect, `readlink /proc/<pid>/exe` settles it.
    """
    try:
        exe = os.path.basename(os.readlink("/proc/%d/exe" % pid))
        # The kernel appends " (deleted)" when the image was replaced under the
        # running process — a llama.cpp rebuild landing during a multi-hour
        # perplexity pass, which is a normal thing to do to this repo's bin/.
        if exe.endswith(" (deleted)"):
            exe = exe[:-len(" (deleted)")]
        if exe in SERVER_NAMES:
            return exe
    except OSError:
        pass
    for want in SERVER_NAMES:
        # comm is only ever cut AT 15 characters, so a shorter comm is complete
        # and has to match whole; only a full-length one may be a prefix. That
        # keeps `llama-bench` from matching some other tool's first 11 letters.
        if comm == want or (len(comm) >= 15 and want.startswith(comm)):
            return want
    return None


def live_servers():
    """[(pid, name)] for every llama.cpp process on this machine.

    name is the tool's real name, never the kernel's 15-character truncation —
    callers print it into status lines and refusal messages.
    """
    out = []
    try:
        if _WINDOWS:
            raw = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=30).stdout
            for line in raw.splitlines():
                parts = [p.strip('"') for p in line.split('","')]
                if len(parts) >= 2 and parts[0].lower() in (
                        n.lower() for n in SERVER_NAMES):
                    out.append((int(parts[1]), parts[0]))
        else:
            raw = subprocess.run(["ps", "-eo", "pid=,comm="],
                                 capture_output=True, text=True, timeout=30).stdout
            for line in raw.split("\n"):
                bits = line.split(None, 1)
                if len(bits) != 2:
                    continue
                # The pid parse used to run only on a line that had already
                # matched a name; it now runs on every line, so it needs its own
                # guard — one odd line raising into the outer `except` would
                # return an empty server list, which is the blindness above
                # wearing a different mask.
                try:
                    pid = int(bits[0])
                except ValueError:
                    continue
                name = _posix_tool_name(pid, os.path.basename(bits[1].strip()))
                if name:
                    out.append((pid, name))
    except Exception:
        pass
    return out


def kill_servers():
    """Kill every llama-server on the machine. Returns the pids killed."""
    killed = []
    for pid, _ in live_servers():
        try:
            if _WINDOWS:
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                               capture_output=True, timeout=30)
            else:
                os.kill(pid, 9)
            killed.append(pid)
        except Exception:
            pass
    return killed


# ---------------------------------------------------------------------------
# The lock
# ---------------------------------------------------------------------------

def holder():
    """The live lock payload, or None. Clears the file if the holder is dead."""
    try:
        # utf-8-sig, not utf-8: gpu-lock.ps1 writes this file with PowerShell
        # 5.1's Out-File -Encoding utf8, which emits a BOM. Reading it as plain
        # utf-8 raises, holder() returns None, and BOTH sides think the lock is
        # free — the exact double-acquire this file exists to stop. Caught by
        # the cross-language round-trip test, not by either side alone.
        with open(LOCK_PATH, "r", encoding="utf-8-sig") as fh:
            rec = json.load(fh)
    except (OSError, ValueError):
        return None
    pid = rec.get("pid")
    if not _alive(pid):
        return None
    want = rec.get("start_time")
    got = _start_time(pid)
    if want is not None and got is not None and want != got:
        return None                      # PID was reused; the lock is stale
    return rec


DRY_RUN_ENV = "MEASURED_INFERENCE_DRY_RUN"


class DryRunViolation(RuntimeError):
    """A dry run tried to take the GPU.

    scripts/verify/probe-smoke-test.py imports every probe's top level to check
    that it parses and loads. A probe whose module level calls main() launches a
    real job under that import. The `if __name__ == "__main__":` guards are the
    first defence; this is the second, because a guard can regress and an
    orphaned server holding the card is what this module exists to prevent.
    """


def _refuse_if_dry_run(what):
    if os.environ.get(DRY_RUN_ENV):
        raise DryRunViolation(
            "%s called while %s=1. Real work ran under a dry run - almost always "
            "a probe missing its `if __name__ == \"__main__\":` guard, so "
            "importing it executed main(). Add the guard; do not unset the "
            "variable." % (what, DRY_RUN_ENV))


def acquire(tag, wait_s=0, allow_foreign=False):
    """Take the machine-wide GPU lock. Raises GpuBusy if someone else has it.

    tag           free text naming the job, shown to whoever collides with you
    wait_s        seconds to keep retrying before giving up (default: fail fast)
    allow_foreign don't refuse when an llama-server we didn't start is live
                  (only for callers that deliberately attach to one, e.g.
                  bench.py --no-serve)
    """
    _refuse_if_dry_run("gpu_lock.acquire()")
    global _held
    if _held is not None:
        return _held

    deadline = time.time() + max(0, wait_s)
    while True:
        cur = holder()
        if cur is None:
            rec = {"pid": os.getpid(),
                   "start_time": _start_time(os.getpid()),
                   "tag": tag,
                   "argv": " ".join(sys.argv),
                   "host": platform.node(),
                   "acquired": time.strftime("%Y-%m-%dT%H:%M:%S")}
            try:
                fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                # Either a live holder raced us, or the file is a corpse holder()
                # already judged dead. Steal only the corpse.
                if holder() is None:
                    try:
                        os.unlink(LOCK_PATH)
                    except OSError:
                        pass
                    continue
                cur = holder()
            else:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(rec, fh, indent=2)
                _held = rec
                break

        if time.time() >= deadline:
            raise GpuBusy(
                "another GPU job holds the lock — rule 20, one GPU job at a "
                "time.\n"
                "  holder : pid %s, tag %r, since %s\n"
                "  command: %s\n"
                "  lock   : %s\n"
                "Wait for it, or if you are sure it is dead:  "
                "python gpu_lock.py kill"
                % (cur.get("pid"), cur.get("tag"), cur.get("acquired"),
                   cur.get("argv"), LOCK_PATH))
        time.sleep(2)

    if not allow_foreign:
        foreign = live_servers()
        if foreign:
            release()
            raise GpuBusy(
                "llama-server is already running (pid %s) and this process did "
                "not start it.\n"
                "Starting an arm on top of another arm's weights silently "
                "mislabels every result, and two resident models is how the "
                "2026-08-29 host OOM happened.\n"
                "Stop it first:  python gpu_lock.py kill"
                % ", ".join(str(p) for p, _ in foreign))
    return _held


def release():
    """Drop the lock if we hold it. Safe to call twice."""
    global _held
    if _held is None:
        return
    try:
        cur = holder()
        if cur and cur.get("pid") == os.getpid():
            os.unlink(LOCK_PATH)
    except OSError:
        pass
    _held = None


class guard(object):
    """with gpu_lock.guard("depth-series"): ...  — lock for the whole block."""

    def __init__(self, tag, wait_s=0, allow_foreign=False):
        self.tag, self.wait_s, self.allow_foreign = tag, wait_s, allow_foreign

    def __enter__(self):
        return acquire(self.tag, self.wait_s, self.allow_foreign)

    def __exit__(self, *exc):
        release()
        return False


# ---------------------------------------------------------------------------
# The guarded spawn
# ---------------------------------------------------------------------------

def preflight(cap=None):
    """Refuse to launch into a machine that is already out of headroom.

    This is the guard the incident would have tripped at 23:59:11, twenty-four
    minutes before the hang, while the desktop was still responsive.
    """
    st = _memory_status()
    if not st:
        return
    total, limit, used = st
    cap = mem_cap_bytes() if cap is None else cap
    gb = float(1 << 30)
    if used > limit * COMMIT_REFUSE_FRAC:
        raise GpuBusy(
            "system commit is already %.1f GB of %.1f GB (%.0f%%) — refusing to "
            "load a model into that.\n"
            "Something else on this box is holding memory; find it before "
            "starting a run, or the host hangs and the campaign dies with it.\n"
            "  python gpu_lock.py status"
            % (used / gb, limit / gb, 100.0 * used / limit))
    if cap and used + cap > limit * 0.90:
        raise GpuBusy(
            "commit headroom too small: %.1f GB free of a %.1f GB limit, and "
            "this job is capped at %.1f GB.\n"
            "Free memory, or lower the cap with MEASURED_INFERENCE_MEM_CAP_GB "
            "(and record the change — it is a condition, rule 3)."
            % ((limit - used) / gb, limit / gb, cap / gb))


def _cap_child(proc, cap):
    """Put proc in a job object: commit cap + dies when we die. Windows only."""
    if not _WINDOWS or not cap:
        return False
    job = _k32.CreateJobObjectW(None, None)
    if not job:
        return False
    info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = (JOB_OBJECT_LIMIT_JOB_MEMORY |
                                             JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
    info.JobMemoryLimit = ctypes.c_size_t(cap).value
    if not _k32.SetInformationJobObject(ctypes.c_void_p(job),
                                        JobObjectExtendedLimitInformation,
                                        ctypes.byref(info), ctypes.sizeof(info)):
        _k32.CloseHandle(ctypes.c_void_p(job))
        return False
    h = _k32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, proc.pid)
    if not h:
        _k32.CloseHandle(ctypes.c_void_p(job))
        return False
    ok = _k32.AssignProcessToJobObject(ctypes.c_void_p(job), ctypes.c_void_p(h))
    _k32.CloseHandle(ctypes.c_void_p(h))
    if not ok:
        _k32.CloseHandle(ctypes.c_void_p(job))
        return False
    _jobs.append(job)   # keep the handle: closing it kills the child
    return True


RLIMIT_ENV = "MEASURED_INFERENCE_RLIMIT_AS"
_rlimit_note_printed = [False]


def _posix_rlimit_wanted():
    """Should a POSIX child get RLIMIT_AS? By default no, and that is deliberate.

    RLIMIT_AS caps VIRTUAL ADDRESS SPACE, not committed memory. A CUDA process
    reserves tens of gigabytes of address space for unified memory whatever it
    actually uses, so ANY RLIMIT_AS a GPU job would tolerate is larger than the
    cap is meant to be, and any cap worth setting kills the job at model load.

    Measured 2026-08-29 under WSL2 Ubuntu 24.04 on an RTX 3090: a 3.6 GB model
    that loads fine unguarded aborts with SIGABRT under a 12.5 GB RLIMIT_AS,
    inside common_init_from_params. The Windows path is unaffected — a job
    object's commit limit counts committed pages, which is the thing we mean.

    So on POSIX the memory guard is preflight() plus the one-job lock, and the
    rlimit is opt-in for CPU-only runs where it does express the right thing.
    """
    import os as _os
    if _os.environ.get(RLIMIT_ENV):
        return True
    if not _rlimit_note_printed[0]:
        _rlimit_note_printed[0] = True
        sys.stderr.write(
            "[gpu_lock] POSIX: no RLIMIT_AS on the child (it caps address "
            "space, which CUDA reserves in bulk and would abort at model "
            "load). preflight() and the one-job lock still apply. Set %s=1 "
            "to force it on a CPU-only run." % RLIMIT_ENV + os.linesep)
    return False


def _rlimit_preexec(cap):
    def _apply():
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
    return _apply


def serve(args, tag=None, cap=None, require_lock=True, **kw):
    """subprocess.Popen for a llama-server, with the three guards attached.

    Drop-in for subprocess.Popen(args, ...): same arguments, same return.

      * refuses unless this process holds the GPU lock (require_lock=False for
        a caller that manages the lock itself at a coarser grain)
      * preflight() on system commit headroom
      * child gets a commit cap and CANNOT outlive this process

    A caller that has not acquired the lock gets it implicitly, tagged `tag`
    or argv[0], and keeps it until the process exits — deliberately sticky,
    because a probe that starts a second server after stopping the first is
    still one GPU job and should not race anyone in between.
    """
    _refuse_if_dry_run("gpu_lock.serve()")
    if require_lock and _held is None:
        acquire(tag or os.path.basename(sys.argv[0] or "gpu-job"))
    cap = mem_cap_bytes() if cap is None else cap
    preflight(cap)
    if not _WINDOWS and cap and _posix_rlimit_wanted():
        kw.setdefault("preexec_fn", _rlimit_preexec(cap))
    proc = subprocess.Popen(args, **kw)
    if not _cap_child(proc, cap):
        # Non-fatal: the lock and preflight still hold. Say so, loudly, because
        # an uncapped child is exactly the 2026-08-29 shape.
        if _WINDOWS and cap:
            sys.stderr.write(
                "gpu_lock: WARNING — could not job-cap llama-server pid %d; it "
                "is uncapped and may outlive this script. Watch it.\n" % proc.pid)
    return proc


# Back-compat alias so a converted call site reads like the one it replaced.
popen = serve


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cmd_status():
    gb = float(1 << 30)
    st = _memory_status()
    if st:
        total, limit, used = st
        print("memory : %.1f GB RAM | commit %.1f / %.1f GB (%.0f%%) | "
              "per-job cap %.1f GB"
              % (total / gb, used / gb, limit / gb, 100.0 * used / limit,
                 mem_cap_bytes() / gb))
    cur = holder()
    print("lock   : %s" % LOCK_PATH)
    if cur:
        print("         HELD by pid %s, tag %r, since %s"
              % (cur.get("pid"), cur.get("tag"), cur.get("acquired")))
        print("         %s" % cur.get("argv"))
    else:
        print("         free")
    servers = live_servers()
    if servers:
        print("servers: %d LIVE — %s"
              % (len(servers), ", ".join("%s(%d)" % (n, p) for p, n in servers)))
    else:
        print("servers: none")
    return 0 if (cur is None and not servers) else 1


def _cmd_kill():
    killed = kill_servers()
    print("killed %d llama-server process(es)%s"
          % (len(killed), (": " + ", ".join(map(str, killed))) if killed else ""))
    try:
        os.unlink(LOCK_PATH)
        print("cleared lock %s" % LOCK_PATH)
    except OSError:
        print("lock already clear")
    return 0


def _cmd_release():
    cur = holder()
    if cur:
        print("refusing: lock is held by a LIVE pid %s (tag %r). Stop it first, "
              "or use `kill`." % (cur.get("pid"), cur.get("tag")))
        return 1
    try:
        os.unlink(LOCK_PATH)
        print("cleared stale lock %s" % LOCK_PATH)
    except OSError:
        print("lock already clear")
    return 0


USAGE = """\
The machine-wide GPU mutex rule 20 rests on: one job at a time, a commit cap on
every child, and no server outliving the process that started it. Every
launcher in this repo goes through gpu_lock.serve(); run directly, this file is
the operator console for the lock those launchers take.

    python scripts/bench/gpu_lock.py status     # the default
    python scripts/bench/gpu_lock.py kill
    python scripts/bench/gpu_lock.py release

Subcommands (default: status, which is also what an unrecognised word gets):
  status    memory and commit headroom, who holds the lock, and every live
            llama.cpp tool. Exits 0 only when the lock is free AND no server is
            running - that is the "is the card idle" check AGENTS.md's crash
            recovery tells a resuming agent to run before deciding anything.
  kill      terminate every live llama.cpp tool (llama-server,
            llama-perplexity, llama-cli, llama-bench, llama-tokenize,
            llama-mtmd-cli, llama-completion), then clear the lock.
  release   clear a STALE lock and nothing else. It refuses while a live pid
            holds it, and it never touches a process.

Positional arguments: the subcommand, and nothing else.

THE LOCK FILE is JSON naming the holding pid, that pid's start time (so a
reused pid cannot inherit the lock), the job's tag, its argv and when it was
acquired. It lives at <repo>/.gpu-lock.json unless MEASURED_INFERENCE_LOCK says
otherwise. A lock whose pid is dead is stale and the next acquire() takes it; a
lock whose pid is alive fails the second caller in about a second, with a
message naming the first.

Environment, all optional:
  MEASURED_INFERENCE_LOCK        the lockfile path (default <repo>/.gpu-lock.json)
  MEASURED_INFERENCE_MEM_CAP_GB  per-job commit cap (default 0.75 x RAM)
  MEASURED_INFERENCE_DRY_RUN=1   acquire() and serve() refuse the card outright
  MEASURED_INFERENCE_RLIMIT_AS=1 POSIX only: opt in to RLIMIT_AS on the child

Example:
  python scripts/bench/gpu_lock.py status

Takes the card: never - no subcommand here loads a model. `status` only reads;
`kill` terminates processes and deletes the lockfile; `release` deletes the
lockfile. Nothing under results/ is written.
"""


if __name__ == "__main__":
    # Answered BEFORE the dispatch below, because that dispatch sends every
    # unrecognised word - "--help" included - to status. Help is the one word
    # that must not quietly mean something else.
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        print(USAGE.rstrip())
        sys.exit(0)
    cmd = (sys.argv[1] if len(sys.argv) > 1 else "status").lower()
    sys.exit({"status": _cmd_status,
              "kill": _cmd_kill,
              "release": _cmd_release}.get(cmd, _cmd_status)())
