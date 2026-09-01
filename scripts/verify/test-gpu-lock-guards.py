#!/usr/bin/env python3
"""Drive gpu_lock's three fail-closed guards. No GPU, no weights, no network.

Each of these was a fail-OPEN: a condition the lock could not evaluate was
being reported as the safe answer, which is the one input on which a caller
starts a second GPU job on an occupied card (rule 20).

  1. live_servers() swallowed every exception and returned [] -- "I could not
     look" published as "nothing is running".
  2. acquire()'s corpse-steal `continue` jumped past both the deadline check
     and the sleep, so an unlinkable stale lockfile became an unbounded
     100%-CPU spin that never raised and never honoured wait_s.
  3. `kill` deleted the lockfile of a LIVE holder it had not killed and could
     not kill -- the holder is the Python launcher, never a llama.cpp binary,
     so kill_servers() cannot see it.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "scripts", "bench"))

FAILED = []


def check(name, ok, detail=""):
    print("  %-5s %s%s" % ("ok" if ok else "FAIL", name,
                           "" if ok else "  <- " + detail))
    if not ok:
        FAILED.append(name)


def main():
    tmp = tempfile.mkdtemp(prefix="gpulock-guards-")
    os.environ["MEASURED_INFERENCE_LOCK"] = os.path.join(tmp, "lock.json")
    import gpu_lock

    print("1. live_servers() must RAISE, not return [], when it cannot look")
    real_run = gpu_lock.subprocess.run

    def boom(*a, **k):
        raise OSError("ps is not available on this box")
    gpu_lock.subprocess.run = boom
    try:
        try:
            gpu_lock.live_servers()
            check("raises ServerScanFailed", False, "returned instead of raising")
        except gpu_lock.ServerScanFailed:
            check("raises ServerScanFailed", True)
        except Exception as e:
            check("raises ServerScanFailed", False, "raised %r" % e)

        # ... and status must then exit NON-ZERO, because its exit code is read
        # by campaign-watchdog.sh as "is the card idle".
        rc = gpu_lock._cmd_status()
        check("status exits non-zero on an unreadable scan", rc != 0,
              "exit %s would publish UNKNOWN as an idle card" % rc)

        # ... and acquire() must refuse rather than assume an empty card.
        try:
            gpu_lock.acquire("guard-test", wait_s=0)
            check("acquire refuses when the scan fails", False, "it acquired")
        except gpu_lock.GpuBusy:
            check("acquire refuses when the scan fails", True)
        except gpu_lock.ServerScanFailed:
            check("acquire refuses when the scan fails", True)
        finally:
            gpu_lock._held = None
    finally:
        gpu_lock.subprocess.run = real_run

    print("2. acquire() must not spin forever on an unlinkable stale lockfile")
    # A DIRECTORY at the lock path: os.open(O_EXCL) fails, holder() reads no
    # live pid, and os.unlink() cannot remove it. The old code looped here with
    # no sleep and no deadline check.
    lockdir = os.path.join(tmp, "asdir")
    os.environ["MEASURED_INFERENCE_LOCK"] = lockdir
    os.makedirs(lockdir, exist_ok=True)
    code = (
        "import os,sys;os.environ['MEASURED_INFERENCE_LOCK']=%r;"
        "sys.path.insert(0,%r);import gpu_lock;\n"
        "try:\n"
        "    gpu_lock.acquire('spin-test', wait_s=0)\n"
        "    print('ACQUIRED')\n"
        "except gpu_lock.GpuBusy:\n"
        "    print('REFUSED')\n"
        "except Exception as e:\n"
        "    print('RAISED %%s' %% type(e).__name__)\n"
        % (lockdir, os.path.join(REPO, "scripts", "bench")))
    try:
        r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                           text=True, timeout=25)
        out = (r.stdout or "").strip().splitlines()[-1:] or [""]
        check("returns within the deadline instead of spinning", True,
              "")
        check("and it refuses rather than acquiring", "ACQUIRED" not in out[0],
              "got %r" % out[0])
    except subprocess.TimeoutExpired:
        check("returns within the deadline instead of spinning", False,
              "still running after 25 s -- the unbounded spin is back")

    print("3. kill must refuse a LIVE holder it cannot kill")
    os.environ["MEASURED_INFERENCE_LOCK"] = os.path.join(tmp, "live.json")
    import importlib
    importlib.reload(gpu_lock)
    # A lock record naming a pid that IS alive and is not a llama.cpp tool:
    # this process. That is exactly the launcher case.
    import json
    json.dump({"pid": os.getpid(), "tag": "pretend-launcher",
               "acquired": "now", "argv": "python bench.py"},
              open(gpu_lock.LOCK_PATH, "w"))
    argv0 = list(sys.argv)
    sys.argv = ["gpu_lock.py", "kill"]
    try:
        rc = gpu_lock._cmd_kill()
        check("kill refuses while a live holder owns the lock", rc != 0,
              "exit %s -- it removed a live holder's lock" % rc)
        check("and the lockfile survives the refusal",
              os.path.exists(gpu_lock.LOCK_PATH),
              "the lock was deleted anyway")
        sys.argv = ["gpu_lock.py", "kill", "--force"]
        rc = gpu_lock._cmd_kill()
        check("kill --force still clears it", rc == 0 and
              not os.path.exists(gpu_lock.LOCK_PATH))
    finally:
        sys.argv = argv0

    print()
    if FAILED:
        print("%d FAILED: %s" % (len(FAILED), ", ".join(FAILED)))
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
