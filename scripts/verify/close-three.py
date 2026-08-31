"""Close three register entries the page still lists as never measured.

    python close-three.py --task ram|power|all

The published register carries these as open, and two of them are admissions
rather than gaps:

1. SYSTEM RAM UNDER EITHER LOAD MODE. The page says outright that the 15 GB
   saving attributed to `--load-mode none` is "an inherited figure, not a
   reading taken here". An inherited number sitting in a recipe block is
   exactly what rule 3's transport clause is about: it arrived without its
   conditions and nobody on this machine has ever checked it. Cost: minutes.

2. BOARD POWER FOR ANY FILE BELOW 4 BITS. The 19-arm power matrix predates the
   quantisation ladder and all three of its quant arms are 4-bit, so nothing
   on the page prices the energy of UD-Q2_K_XL or anything smaller - while the
   page recommends UD-Q2_K_XL as the 16 GB pick and the full-window pick. A
   recommendation whose energy has never been measured is a recommendation
   with a hole in it.

WHAT IS MEASURED AND WHAT IS NOT. Every joule here is IN-BAND GPU BOARD POWER
as NVML reports it. The power supply's conversion loss, the processor, system
memory, drives and the display are excluded and unmeasured. This may never be
called system power (the campaign's standing rule, and the reason the wall-
power register entry stays open until somebody buys a plug meter).

Rule 27 applies to the power arms: they are speed measurements underneath, so
the host must be quiet, and quiet_report() is recorded per arm.
"""

import argparse
import io
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts", "bench"))
import refarm
import gpu_lock

UNS = os.environ.get("MODEL_DIR", r"C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF")
OUT = os.path.join(ROOT, "results", "qwen38-27b-blind", "data", "register")
PORT = 1266
BASE = "http://127.0.0.1:%d" % PORT

PROMPT = ("Write a single self-contained JavaScript module that implements a "
          "fixed-window rate limiter with a pluggable clock, a per-key limit, and "
          "an eviction sweep that runs at most once per window. Include JSDoc on "
          "every exported symbol, plus a short usage example. Code only.")
NPREDICT = 700


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def save(name, obj):
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, name)
    json.dump(obj, io.open(p, "w", encoding="utf-8"), indent=1, default=str)
    log("-> %s" % p)


def ps(cmd):
    """One PowerShell command -> its stdout, or None when there is no host.

    Guarded because until 2026-08-31 it was not. On this bare-metal Ubuntu
    26.04.1 box there is no `powershell` and no `pwsh`, and both callers below
    invoked this OUTSIDE their try/except, so subprocess.run's
    FileNotFoundError went straight up through sys_free_mib() - the first
    statement of task_ram()'s loop - and killed the whole script, including the
    power task that runs after it. Measured that day: `python3
    scripts/verify/close-three.py` exits 1 on an uncaught traceback. The
    branches below no longer call this off Windows at all, so the guard is a
    second line of defence rather than the fix; it stays because a reader that
    cannot read must return "no number", never take a run down with it - and
    this crash landed AFTER the rule-20 lock was taken and a server launched,
    i.e. after GPU time had already been spent.
    """
    try:
        return subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace").stdout.strip()
    except OSError:
        return None


def proc_mem(pid):
    """Working set and private bytes for one process, in MiB.

    Windows reports the pair (WorkingSet64, PrivateMemorySize64). Linux has no
    field that means either one, so /proc/<pid>/status supplies the nearest
    STAND-INS, and they are not the same concepts:

      VmRSS  stands in for WorkingSet64. Both are resident pages, private and
             shared counted together; this is the close one.
      VmData stands in for PrivateMemorySize64, and this one is loose. Windows
             counts private bytes COMMITTED - charged against the commit limit
             whether resident or not - while VmData is the size of the private
             data segment, i.e. anonymous address space, resident or not.

    Neither Linux field counts a file-backed mapping as private, which is the
    property this task is built on: under `--load-mode mmap` the weights are
    page cache and show up in VmRSS alone, while `--load-mode none` reads them
    into anonymous memory so they show up in BOTH. VmSize (the whole address
    space) is the fallback on a kernel that omits VmData. Rule 3: the number
    carries its conditions, and "working set" in a row measured here means the
    Linux figure - not comparable cell-for-cell against a Windows run's column
    of the same name.
    """
    if os.name == "nt":
        out = ps("$p=Get-Process -Id %d -ErrorAction SilentlyContinue; "
                 "if($p){'{0} {1}' -f "
                 "$p.WorkingSet64,$p.PrivateMemorySize64}" % pid)
        try:
            w, pv = out.split()
            return round(int(w) / 1024 ** 2), round(int(pv) / 1024 ** 2)
        except Exception:
            return None, None
    fields = {}
    try:
        with open("/proc/%d/status" % int(pid)) as fh:
            for line in fh:
                k, _, v = line.partition(":")
                parts = v.split()
                if len(parts) == 2 and parts[0].isdigit() and parts[1] == "kB":
                    fields[k.strip()] = int(parts[0]) // 1024     # kB -> MiB
    except OSError:
        return None, None
    private = fields.get("VmData")
    if private is None:
        private = fields.get("VmSize")
    return fields.get("VmRSS"), private


def sys_free_mib():
    """Host RAM still allocatable, in MiB. None when nothing can read it.

    Windows answers with Win32_OperatingSystem.FreePhysicalMemory (kB). Linux
    answers with MemAvailable from /proc/meminfo, parsed exactly the way
    scripts/detect-machine.py's host_meminfo() parses it (kB // 1024 -> MiB),
    so the two readers on this box cannot disagree about the same kernel line.
    MemFree is deliberately not a fallback: on a machine that has just read a
    20 GB GGUF, MemFree sits near zero while that 20 GB is reclaimable page
    cache, which would price the mmap arm as if it had eaten the host.

    The consequence travels with the number (rule 3). `sys_ram_consumed_mib`
    is a DROP IN MemAvailable, so weights that are page cache - the mmap arm -
    still count as available, while `--load-mode none`'s anonymous copy does
    not. That is the right comparison for "does none really cost 15 GB more
    than mmap", and it is not the quantity the Windows column holds; rows from
    the two platforms do not subtract from each other.
    """
    if os.name == "nt":
        out = ps("(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory")
        try:
            return round(int(out) / 1024)
        except Exception:
            return None
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                k, _, v = line.partition(":")
                if k.strip() != "MemAvailable":
                    continue
                parts = v.split()
                if parts and parts[0].isdigit():
                    return int(parts[0]) // 1024                  # kB -> MiB
    except OSError:
        return None
    return None            # no MemAvailable line: kernel older than 3.14


def smi_used():
    return float(subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        capture_output=True, text=True).stdout.strip().splitlines()[0])


def post(payload, timeout=1800):
    req = urllib.request.Request(BASE + "/v1/chat/completions",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def serve(model, extra, tag, ctx=32768):
    args = [refarm.server_bin(), "-m", model, "--alias", "m", "-ngl", "99",
            "-c", str(ctx), "--parallel", "1", "-fa", "on",
            "-ctk", "q8_0", "-ctv", "q8_0", "--jinja", "--reasoning", "off",
            "--host", "127.0.0.1", "--port", str(PORT)] + extra
    os.makedirs(os.path.join(OUT, "close3-logs"), exist_ok=True)
    lf = io.open(os.path.join(OUT, "close3-logs", "%s.log" % tag), "a",
                 encoding="utf-8", errors="replace")
    p = gpu_lock.serve(args, stdout=lf, stderr=subprocess.STDOUT)
    t0 = time.time()
    while time.time() - t0 < 900:
        if p.poll() is not None:
            lf.close()
            return None, None
        try:
            with urllib.request.urlopen(BASE + "/health", timeout=2) as r:
                if json.loads(r.read().decode()).get("status") == "ok":
                    return p, lf
        except Exception:
            pass
        time.sleep(2)
    return None, None


def kill(p, lf):
    if p and p.poll() is None:
        p.terminate()
        try:
            p.wait(timeout=30)
        except subprocess.TimeoutExpired:
            p.kill()
    try:
        if lf:
            lf.close()
    except Exception:
        pass
    for _ in range(30):
        time.sleep(1)
        if smi_used() < 2400:
            return


class PowerSampler(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.rows, self.stop = [], False

    def run(self):
        while not self.stop:
            try:
                o = subprocess.run(
                    ["nvidia-smi",
                     "--query-gpu=power.draw,clocks.sm,temperature.gpu",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=10).stdout
                w, c, t = [float(x) for x in o.strip().splitlines()[0].split(",")]
                self.rows.append((time.time(), w, c, t))
            except Exception:
                pass
            time.sleep(0.2)


# ------------------------------------------------------------------ 1. RAM
def task_ram():
    """Does --load-mode none really cost 15 GB more system RAM than mmap?"""
    log("TASK ram: the inherited 15 GB figure, measured here for the first time")
    model = os.path.join(UNS, "Qwen3.8-27B-UD-IQ4_XS.gguf")
    rows = []
    for mode in ("none", "mmap", "auto"):
        free_before = sys_free_mib()
        t0 = time.time()
        p, lf = serve(model, ["--load-mode", mode], "ram-%s" % mode)
        load_s = round(time.time() - t0, 1)
        if not p:
            log("  %-5s FAILED TO LOAD" % mode)
            rows.append({"mode": mode, "loaded": False})
            continue
        time.sleep(3)
        ws, pv = proc_mem(p.pid)
        vram = smi_used()
        try:
            r = post({"model": "m", "temperature": 0, "top_k": 1,
                      "max_tokens": NPREDICT, "cache_prompt": True,
                      "messages": [{"role": "user", "content": PROMPT}]})
            tps = r.get("timings", {}).get("predicted_per_second")
        except Exception as e:
            tps = None
            log("  probe failed: %s" % e)
        ws2, pv2 = proc_mem(p.pid)
        free_after = sys_free_mib()
        kill(p, lf)
        rows.append({"mode": mode, "loaded": True, "load_seconds": load_s,
                     "working_set_mib_after_load": ws,
                     "private_bytes_mib_after_load": pv,
                     "working_set_mib_after_probe": ws2,
                     "private_bytes_mib_after_probe": pv2,
                     "sys_free_before_mib": free_before,
                     "sys_free_after_mib": free_after,
                     "sys_ram_consumed_mib": (free_before - free_after)
                     if (free_before and free_after) else None,
                     "vram_mib": vram, "tps": round(tps, 2) if tps else None})
        log("  %-5s load %5.1fs  working set %6s MiB  private %6s MiB  "
            "sys RAM used %6s MiB  vram %5.0f  %s t/s"
            % (mode, load_s, ws2, pv2,
               (free_before - free_after) if (free_before and free_after) else "?",
               vram, round(tps, 2) if tps else "-"))
        save("loadmode-ram.json", {"date": time.strftime("%Y-%m-%d %H:%M"),
                                   "model": os.path.basename(model), "rows": rows})

    ok = [r for r in rows if r.get("loaded")]
    if len(ok) >= 2:
        by = {r["mode"]: r for r in ok}
        if "none" in by and "mmap" in by:
            a = by["none"].get("working_set_mib_after_probe") or 0
            b = by["mmap"].get("working_set_mib_after_probe") or 0
            log("")
            log("  none vs mmap working set: %d vs %d MiB  (difference %+d MiB)"
                % (a, b, a - b))
            log("  the page's INHERITED claim is a 15 GB (15,360 MiB) saving.")
            log("  measured difference is %+d MiB." % (a - b))
    save("loadmode-ram.json", {"date": time.strftime("%Y-%m-%d %H:%M"),
                               "model": os.path.basename(model), "rows": rows,
                               "inherited_claim_mib": 15360})
    log("TASK ram: done")


# ---------------------------------------------------------------- 2. POWER
def task_power():
    """Joules per decode token for the sub-4-bit files the page recommends."""
    log("TASK power: board energy for files below 4 bits (register: never priced)")
    files = [
        ("UD-IQ4_XS", os.path.join(UNS, "Qwen3.8-27B-UD-IQ4_XS.gguf"), 4.223),
        ("UD-Q3_K_XL", os.path.join(UNS, "Qwen3.8-27B-UD-Q3_K_XL.gguf"), 3.895),
        ("UD-IQ3_XXS", os.path.join(UNS, "Qwen3.8-27B-UD-IQ3_XXS.gguf"), 3.240),
        ("UD-Q2_K_XL", os.path.join(UNS, "Qwen3.8-27B-UD-Q2_K_XL.gguf"), 2.912),
        ("UD-IQ2_S", os.path.join(UNS, "Qwen3.8-27B-UD-IQ2_S.gguf"), 2.481),
    ]
    drafter = ["--spec-type", "draft-mtp", "--spec-draft-n-max", "4",
               "--spec-draft-p-min", "0.75"]
    rows = []
    for name, path, bpw in files:
        if not os.path.exists(path):
            log("  %-12s MISSING" % name)
            continue
        q = refarm.quiet_report()
        extra = drafter if name != "UD-IQ2_S" else ["--spec-type", "none"]
        note = "" if name != "UD-IQ2_S" else " (no MTP layers - drafter off)"
        p, lf = serve(path, extra, "pow-%s" % name)
        if not p:
            log("  %-12s FAILED TO LOAD" % name)
            rows.append({"file": name, "loaded": False})
            continue
        s = PowerSampler()
        s.start()
        probes = []
        try:
            post({"model": "m", "temperature": 0, "top_k": 1,
                  "max_tokens": NPREDICT, "cache_prompt": True,
                  "messages": [{"role": "user", "content": PROMPT}]})  # rule 12
            time.sleep(3)
            for _ in range(3):
                t0 = time.time()
                r = post({"model": "m", "temperature": 0, "top_k": 1,
                          "max_tokens": NPREDICT, "cache_prompt": True,
                          "messages": [{"role": "user", "content": PROMPT}]})
                t1 = time.time()
                t = r.get("timings", {})
                win = [x for x in s.rows if t0 <= x[0] <= t1]
                if not win:
                    continue
                mw = sum(x[1] for x in win) / len(win)
                dec_s = t.get("predicted_ms", 0) / 1000.0
                n = t.get("predicted_n") or 0
                probes.append({
                    "tps": round(t.get("predicted_per_second", 0), 2),
                    "mean_w": round(mw, 1),
                    "peak_w": round(max(x[1] for x in win), 1),
                    "sm_mhz": round(sum(x[2] for x in win) / len(win)),
                    "temp": round(sum(x[3] for x in win) / len(win), 1),
                    "decode_s": round(dec_s, 2), "predicted_n": n,
                    "j_per_tok": round(mw * dec_s / n, 4) if n else None})
                time.sleep(2)
        except Exception as e:
            log("  probe failed: %s" % e)
        finally:
            s.stop = True
            s.join(timeout=2)
            kill(p, lf)
        if not probes:
            rows.append({"file": name, "bpw": bpw, "loaded": True, "probes": []})
            continue
        jm = sum(x["j_per_tok"] for x in probes if x["j_per_tok"]) / len(probes)
        tm = sum(x["tps"] for x in probes) / len(probes)
        wm = sum(x["mean_w"] for x in probes) / len(probes)
        rows.append({"file": name, "bpw": bpw, "loaded": True,
                     "drafter": "n4/p0.75" if name != "UD-IQ2_S" else "none",
                     "j_per_tok": round(jm, 4), "tps": round(tm, 2),
                     "mean_w": round(wm, 1), "host": q["status"],
                     "probes": probes})
        log("  %-12s %5.3f bpw  %6.2f t/s  %5.1f W  %6.4f J/token%s"
            % (name, bpw, tm, wm, jm, note))
        save("subq4-power.json", {"date": time.strftime("%Y-%m-%d %H:%M"),
                                  "tier": "in-band GPU board power (NVML) only; "
                                          "PSU, CPU, RAM, drives, display excluded",
                                  "rows": rows})
    save("subq4-power.json", {"date": time.strftime("%Y-%m-%d %H:%M"),
                              "tier": "in-band GPU board power (NVML) only; "
                                      "PSU, CPU, RAM, drives, display excluded",
                              "rows": rows})
    log("TASK power: done")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="all", choices=["ram", "power", "all"])
    a = ap.parse_args()
    log("host: %s" % refarm.quiet_report()["status"])
    if a.task in ("all", "ram"):
        task_ram()
    if a.task in ("all", "power"):
        task_power()
    log("DONE")


if __name__ == "__main__":
    main()
