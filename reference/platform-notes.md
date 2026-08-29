---
name: platform-notes
description: Platform-specific traps, equivalents and diagnostics for Windows/PowerShell 5.1, POSIX (Linux/macOS), WSL2, and each accelerator family. Grep by symptom or by the exact error text; do not read whole.
---

# Platform notes — grep by symptom

Every entry leads with the symptom, the exact error text, or the platform
question an agent would search for. Diagnosed failures with a measured
signature live in `failure-library.md`; this file holds what changes with the
platform: the traps, the equivalents, and the commands that actually work.

---

## Windows / PowerShell 5.1

**Reference machines run Windows PowerShell 5.1** (`powershell.exe`), not
PowerShell 7. Every reference script in `scripts/reference-3090/` is 5.1
PowerShell. Assume 5.1 unless the campaign proves otherwise: `$PSVersionTable`.

### SYMPTOM: a function returns extra junk, or an array where one value was expected

`Write-Output` inside a PowerShell function **pollutes the function's return
value** — every uncaptured expression is emitted into the pipeline. Use
`Write-Host` for logging inside functions. Full entry: `failure-library.md`,
"Write-Output pollutes a function's return value".

### SYMPTOM: a detached script dies immediately, or produces an empty log

The script never parsed. **Parse-check before detaching:**

```powershell
[scriptblock]::Create((Get-Content -Raw .\run.ps1)) | Out-Null   # throws on a parse error
```

### SYMPTOM: git commit message is mangled, or `--chat-template-kwargs` JSON is rejected

Double quotes inside git commit messages get mangled by 5.1's argument parsing.
JSON arguments containing `{"key":"value"}` never survive a PowerShell quoting
rule intact. The reference campaign's fix: **build the argv in Python** and
launch from there (`results/qwen38-27b-blind/work/rule21-arm.py` was written for
exactly this), or use a here-string for the commit message.

### SYMPTOM: a native tool "fails" with red error records but exit code 0

Native `stderr` wraps as PowerShell error records (`NativeCommandError`), which
sets `$?` to `$false` even on success. Do not redirect a native executable's
stderr inside 5.1 unless you must; check `$LASTEXITCODE`, not `$?`.

### SYMPTOM: `nvidia-smi` per-process memory shows `[N/A]` or "Insufficient Permissions"

Windows `nvidia-smi` is **per-process blind**, and its `memory.used` counts
dedicated VRAM only — it cannot see a spill. The counters that do work:

```powershell
# totals + who's on the GPU (dedicated only - spill NOT visible here):
nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv
# the spill itself - total shared GPU memory in use:
(Get-Counter '\GPU Process Memory(*)\Shared Usage').CounterSamples |
  Measure-Object CookedValue -Sum   # divide Sum by 1MB; growing = spilling
# per-process dedicated commitment - this is what caught the compositor (dwm)
# holding 3.6 GiB during a browser-UI session:
(Get-Counter '\GPU Process Memory(*)\Dedicated Usage').CounterSamples |
  Where-Object { $_.CookedValue -gt 200MB }
# or Task Manager - Performance - GPU: the dedicated/shared split; and under
# Performance - Memory, RAM speed and "Slots used" (the RAM-channel check)
```

`Get-Counter '\GPU Process Memory(*)\...'` costs ~1.2 s on the reference machine
and is the **only** way to get llama-server's dedicated/shared split on Windows.

### SYMPTOM: spill instead of a clean out-of-memory error

Document and set **NVIDIA Control Panel → Manage 3D Settings → Program Settings
→ llama-server.exe → CUDA — Sysmem Fallback Policy → Prefer No Sysmem
Fallback.** With it set, an over-budget load fails loudly at startup instead of
running at half speed all day. Full entry: `failure-library.md`, "silent VRAM
spill".

### SYMPTOM: a long foreground run loses its output / stops flushing

Foreground-to-background handoff of a long `powershell.exe … *> log` call loses
output flushing. **Launch long runs detached** with `Start-Process` and
`-RedirectStandardOutput`, and poll the script's own row file (written with
`Add-Content`, which flushes) rather than the console log.

### Detaching, the Windows way

```powershell
Start-Process powershell -WindowStyle Hidden `
  -ArgumentList "-NoProfile","-ExecutionPolicy","Bypass","-File",".\run.ps1" `
  -RedirectStandardOutput .\run.log -RedirectStandardError .\run.err
```

Harness background tasks may be killed near 10 minutes; a detached process is
not. Watch the log for a DONE marker. `Stop-Process -Name llama-server` ends a
stranded server.

### Two 5.1 limits that forced a rewrite into Python

Both are full entries in `failure-library.md` — they look like model or server
problems and are neither:

- `Invoke-RestMethod` cannot POST the ~261 KB body a 1440p PNG data-URI
  produces. The request never reaches the server and throws no useful error.
- `[datetime]::TryParseExact` overload resolution breaks the power integrator.
  **Use the Python integrator** (`attribute-power.py`, or the campaign's
  `power-integrate.py`), never the PowerShell one.

---

## POSIX (Linux / macOS)

Every reference script is PowerShell. **`scripts/probe-config.sh` is the ported
seed to adapt from** — it also defaults `-ngl` correctly, which
`probe-config.ps1` does not.

### SYMPTOM: `setup.sh` exits 3 — "the backend on offer is 'vulkan', not CUDA"

Working as designed. There are no official Linux CUDA binaries at any arch, so
the only NVIDIA-on-Linux options are a source build or a different backend, and
a backend swap moves every throughput, acceptance and VRAM number for a reason
that has nothing to do with the model (rule 3; rule 30 — never compare across).
The script refuses rather than installing a Vulkan build quietly, as it used to.

```bash
sudo apt-get install -y nvidia-cuda-toolkit cmake build-essential git
./scripts/setup.sh --cuda            # shallow-clones the pinned tag, builds, ~10-25 min
./scripts/setup.sh --cuda --cuda-arch 121   # DGX Spark GB10, when 'native' is unsupported
MEASURED_INFERENCE_ALLOW_VULKAN=1 ./scripts/setup.sh   # deliberate, non-comparable
```

`--dry-run` prints the whole plan (flavor, assets or cmake line, venv) and
changes nothing. `--tag bNNNNN` pins the llama.cpp release so an Ubuntu rerun
matches the Windows campaign it is being compared against.

### SYMPTOM: perplexity or a suite hash disagrees with the published one

Check the bytes before the model: `setup.sh`/`setup.ps1` compare every file
under `corpora/` and `scripts/bench/datasets-frozen/` against its committed blob
size and exit 5 on a mismatch. Git-for-Windows defaults to `core.autocrlf=true`,
which rewrites `corpora/wikitext-2-raw-test.raw` from 1,290,590 bytes to
1,294,948 — a different file under rule 6's whole quant ranking. The repo's
`.gitattributes` (`* -text`) prevents it; clones made before it existed need
`git config core.autocrlf false && git rm --cached -r . && git reset --hard`.
Note `meetingbank_test.jsonl` is legitimately CRLF **in git** — matching the
commit is the test, not the absence of CR bytes.

### The build's own record: `bin/llama.cpp/INSTALL.json`

Both setup scripts write it: `tag, flavor, arch, os, os_version, host, assets,
urls, installed_utc, built_from_source, cuda_arch`, plus gpu/driver, the
`llama-server --version` line, `source_commit` for a source build, and which
tools exist. `scripts/detect-machine.py` reads `flavor` from it as the measured
backend (and `os` as a token — `linux`/`windows`/`macos`). Copy flavor + tag
into `campaign.md` and the report's conditions block.

- **Detach**: `setsid nohup ./run.sh > run.log 2>&1 &` (or `nohup … &`); poll
  the log for a DONE marker, same as the Windows path.
- **Parse-check before detaching**: `bash -n script.sh` (the `[scriptblock]`
  equivalent); `set -euo pipefail` at the top of every runner.
- **VRAM/spill diagnostics**: NVIDIA `nvidia-smi --query-gpu=memory.used
  --format=csv -l 1` (no Get-Counter needed — per-process is visible via
  `nvidia-smi --query-compute-apps=pid,used_memory --format=csv`); Intel
  `intel_gpu_top`; Apple `powermetrics --samplers gpu_power` plus Metal
  working-set (there is no spill — watch swap with `vm_stat`).
- **Process control**: `pkill -f llama-server` for the `Stop-Process` calls.
- **Power logger** (Stage 0's instrumentation, POSIX form):

```bash
nohup nvidia-smi --query-gpu=timestamp,power.draw,power.draw.instant,\
clocks.current.sm,clocks.current.memory,utilization.gpu,utilization.memory,\
memory.used,memory.reserved,temperature.gpu,pstate \
  --format=csv -lms 500 > results/<slug>/data/power/campaign-power.csv &
```

- **RAPL energy** (Intel, no NVML): `/sys/class/powercap/intel-rapl/*/energy_uj`,
  differenced over the window — J = ΔµJ/1e6, kWh = J/3.6e6. RAPL is **package**
  scope, not board: label the tier (rule 24).
- **Power capping** on Linux may need `nvidia-smi -pm 1` before `-pl <W>`.

### SYMPTOM: the aider run talks to the wrong machine — `ip route show default`, zeros for hours

`GW=$(ip route show default | awk '{print $3}')` is the **WSL2** idiom: WSL2 is
NAT, so field 3 is the `vEthernet (WSL)` gateway, which is the Windows host, and
the same address is routable from inside the container. **On native Linux the
identical command returns the LAN router.** Nothing fails at launch — the
benchmark starts, talks to a router, and surfaces hours later as Stage-6 zeros.
Fixed 2026-08-29 in `scripts/agentic/aider-bench.sh` and
`aider-bench-detached.sh`; copy the shape into anything else that needs the host:

```bash
# platform, not assumption: both markers are WSL2-only, either alone is enough
if [ -n "${WSL_DISTRO_NAME:-}" ] ||
   grep -qi microsoft /proc/sys/kernel/osrelease 2>/dev/null; then …
```

**Two addresses, never one.** `HOST_ADDR` is how the shell reaches the server;
`CONTAINER_ADDR` is how the container does. On WSL2 they are the same string —
which is why one variable survived for as long as only WSL2 ran this. On native
Linux `HOST_ADDR` is `127.0.0.1`, and 127.0.0.1 inside a container is the
container: it needs `host.docker.internal` plus
`--add-host=host.docker.internal:host-gateway` (Docker ≥ 20.10). Both are
printed before anything starts and both are overridable — `LLAMA_HOST`,
`LLAMA_CONTAINER_HOST`. A host-side `HTTP 200` does **not** prove the container
can reach the model, so the scripts curl the real URL from inside the real image
before launching (`AIDER_BENCH_SKIP_CONTAINER_CHECK=1` skips it). Related, and a
different failure: WSL2 in **mirrored** networking mode also puts the LAN router
on the default route — set `LLAMA_HOST` explicitly there.

### SYMPTOM: probe-smoke-test.py fails 18 of 83 on a tree you have not touched

Known failures, all eighteen, recorded in `scripts/verify/smoke-baseline.json`
with a reason, a bucket and a date. Until 2026-08-29 the tool ended `18 of 83
FAILED` and exited 0; it now reports them as `known`, reports anything else as
`NEW`, and **exits non-zero on NEW alone** — `--fail` restores
"any failure fails", which is what a hook wants and what makes the overnight
pre-check red on a clean tree. Read the summary, not the colour:

```bash
python scripts/verify/probe-smoke-test.py            # 0 NEW → exit 0
python scripts/verify/probe-smoke-test.py --fail     # 18 known → exit 1
```

Nothing is skipped: every check still runs on every file and every failure is
still printed. A row whose probe starts passing prints as `STALE … PASSES NOW -
delete this row`, and a row whose recorded cause has stopped being true counts
as NEW. To add one, prove it is older than your work (`git log -1
--format=%cd -- <path>`), then write the row — never by deleting a check.

**Ten of the eighteen end in a missing `llama-server` path and are still not
"environment".** Each has no argument parser, so `--help` is not answered, it is
RUN, and the missing binary is only where the run stops first; building
llama.cpp moves the stop point rather than clearing the row (DERIVED — measured
only on a box with no build). That is the same class as the destroyed result
`scripts/quant-ladder/three-file-12gb-fit.py` documents. Twenty-five of the 83
are in that state; the checker prints the count, sets
`MEASURED_INFERENCE_DRY_RUN=1` on both subprocesses so none of them can take the
card, and diffs `git status --porcelain` around the run so a file a probe writes
is named in the output. Measured 2026-08-29: one run wrote the campaign's
280,937-byte quant-ladder figure at the IMPORT stage, from
`scripts/quant-ladder/make-ladder-png.py`, whose whole body is top level and
which the checker calls a library module — and the new untracked figure then
trips `instrument-guard.py`. Delete it; any run remakes it.

---

## WSL2

Full validated log: `agentic/setup-log.md`. Rule 22 carries the summary.

### SYMPTOM: from WSL, `localhost` / `127.0.0.1` cannot reach a server on the Windows host

WSL2 networking is **NAT mode** unless a `.wslconfig` enables mirrored mode.
The host is the **`vEthernet (WSL)` gateway** — the reference machine's is
`192.168.128.1`, confirmed via `ip route | grep default`. Never `localhost`.
`/etc/resolv.conf`'s `10.255.255.254` is the DNS-tunnel address, **not** the
host — a common misread. The Wi-Fi LAN IP works too but changes with DHCP.
Do not port this idiom to a script that also runs on native Linux: there the
same default route is the LAN router — POSIX above, "the aider run talks to the
wrong machine".

### SYMPTOM: `sudo -n true` fails — password required, and the session cannot prompt

WSL exposes a documented no-password root path: `wsl -d <distro> -u root -e bash
-lc "<cmd>"`. That is the WSL init switching users, not a sudo bypass. Check
`systemd` is PID 1 (`/etc/wsl.conf` with `systemd=true`) before relying on
`systemctl`. After adding a user to a new group, `wsl --terminate <distro>` is
required to pick it up.

### SYMPTOM: `TCP_DENIED/403` in a squid access log; the container cannot reach the model

Pier's egress sidecar allows destination ports **80 and 443 only**
(`Safe_ports` ACL), and this is not configurable through Pier. **The
llama-server must listen on port 80.** Windows does not reserve ports < 1024
for administrators, so this needs no elevation. squid `dstdomain` does match a
bare IP literal — no hostname or `dst` ACL needed.

---

## Per-platform hardware notes

- **NVIDIA/CUDA** (reference campaign): everything in the stage files applies
  directly.
- **Intel Arc dGPU**: llama.cpp Vulkan build (SYCL has known Battlemage perf
  bugs; IPEX-LLM archived). Verify KV-quant support in the build.
- **Intel iGPU (unified memory)**: the window is borrowed RAM, not a wall —
  document the Shared GPU Memory Override path; the effort ceiling is patience,
  not memory. State RAM speed/channels with every number.
- **DGX Spark / GB10 (Ubuntu ARM)**: `setup.sh --cuda --cuda-arch 121` when
  `native` is unsupported; without `--cuda` it takes the `ubuntu-vulkan-arm64`
  asset and falls back to the CPU one only if that is absent. (Until 2026-08-29
  this box got a CPU-only build silently: the aarch64 branch tested for
  `vulkan-capable`, which `nvidia-smi` never sets.) Note the vendor-native
  alternative (vLLM/NVFP4) with what switching buys.
- **Apple Silicon (Metal)**: in scope — `setup.sh` fetches the official
  `macos-arm64` release (Metal built in; no `-ngl` spill risk, unified memory).
  The "VRAM" ceiling is the Metal working-set limit
  (`recommendedMaxWorkingSetSize`, ~66-75% of RAM by default); state total RAM
  with every number and watch for swap, not spill. Intel Macs get the CPU-only
  official build — treat like the CPU path or build Metal from source.
- **OpenVINO (future)**: not yet implemented — record the intent: OVMS with
  int4-ov weights as Intel's tuned path; benchmark against Vulkan llama.cpp.

### Energy counters by platform (rule 24 tiers)

- **NVIDIA**: NVML via `nvidia-smi --query-gpu=power.draw` — in-band GPU board.
- **Intel Arc/iGPU**: HWiNFO64 (sensor logging to CSV) on Windows, or RAPL on
  Linux (package scope).
- **Apple Silicon**: `sudo powermetrics --samplers gpu_power,cpu_power -i 1000`.
- If no counter is readable without installing something on a borrowed machine,
  **mark the energy work unmeasured** rather than estimating from TDP.
