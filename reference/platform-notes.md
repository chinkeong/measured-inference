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

### `$PSScriptRoot` inside a dot-sourced function is the LIBRARY's directory

Verified on PS 5.1, 2026-08-30. Inside a function, `$PSScriptRoot` is the
directory of the file the function was **defined** in, not the directory of the
script that dot-sourced it, and it is bound inside a `param()` default as well.
That is what makes a path resolver legal in a library rather than only in a
runner: `Get-LlamaToolBin` in `scripts/quant-ladder/ladder-lib.ps1` and the
`-Manifest` default in `detectors.ps1` both derive from `$PSScriptRoot`, and
the archived `results/qwen38-27b-blind/work/*.ps1` runners that dot-source
`ladder-lib.ps1` by absolute path still resolve to the right repository.

**No launcher in `scripts/quant-ladder/` resolves `E:\AI\llama.cpp` any more
except `gemma-ppl-diag.ps1:25`, which still names it and is a live BLOCKER in
`scripts/verify/portability-audit.py` (69 blockers, 2026-08-30).** The library
resolves `llama-server`, `llama-perplexity` and `llama-tokenize` through
`Get-LlamaToolBin`: `-Explicit` → `$env:LLAMA_SERVER` (server only, exactly as
`paths.py`'s `llama_bin()` scopes it) → `$env:LLAMA_DIR` → `PATH` →
`<repo>/bin/llama.cpp/` (release and cmake layouts, with and without `.exe`),
skipping any candidate whose first bytes say it is a Linux ELF — which is the
state of `bin/llama.cpp/llama-server` in a checkout built under WSL.
`Get-LlamaServerBin` is the `llama-server` wrapper around it, and the
`ppl.exe` / `tokenize.exe` values in `ladder-manifest.json` are tool names put
through the same chain by `Get-Manifest` when the manifest loads, so
`run-ladder.ps1` launches a resolved path without knowing it. So either export
`LLAMA_SERVER` or `LLAMA_DIR`, or run `scripts/setup.ps1` so `bin/llama.cpp/`
holds a Windows build. A "not found" from these scripts lists every candidate
it tried and the reason it rejected each one, which is `scripts/lib/paths.py`'s
contract restated in PowerShell.

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
sudo apt-get install -y nvidia-cuda-toolkit cmake build-essential git \
                        python3-venv python-is-python3
./scripts/setup.sh --cuda            # shallow-clones the pinned tag, builds, ~10-25 min
./scripts/setup.sh --cuda --cuda-arch 121a-real   # DGX Spark GB10 -- see below; 121 is refused
MEASURED_INFERENCE_ALLOW_VULKAN=1 ./scripts/setup.sh   # deliberate, non-comparable
```

**`python3-venv` and `python-is-python3` are not optional on stock Ubuntu
24.04, which ships neither.** Without the first, `setup.sh` reaches step 11 and
dies with **exit 6** — `python -m venv failed. Ubuntu: sudo apt-get install -y
python3-venv` — after the ~10-25 minute CUDA build has already run. Without the
second, the setup itself is fine (its interpreter loop tries `python3` first
and only falls through to a bare `python`), but nothing else is: every `python
scripts/...` line in `README.md`, `PROMPTS.md` and the stage files is then
command-not-found. Both are one apt away and neither is worth discovering after
the build.

On an Intel box the answer is a different backend, not an override:

```bash
./scripts/setup.sh --openvino                          # CPU by default
./scripts/setup.sh --openvino --openvino-device GPU    # iGPU or Arc
./scripts/setup.sh --check-npu                         # prerequisites only; installs nothing
```

`--dry-run` prints the whole plan (flavor, assets or cmake line, venv) and
changes nothing. `--tag bNNNNN` pins the llama.cpp release so an Ubuntu rerun
matches the Windows campaign it is being compared against.

### SYMPTOM: the power CSV exists but is empty while the logger is running

`nvidia-smi -f <file>` **block-buffers on Linux** and flushes only when the
process exits. Measured 2026-08-30 (RTX 3090, driver 596.36, WSL2 Ubuntu
24.04): a `-f` logger showed 0 rows after 6 s and dumped all 13 at exit, while
the redirected form showed 7 rows after 3 s and 13 after 6 s. A file that
materialises only at exit defeats `scripts/power/attribute-power.py`, which
cannot integrate a window that has not been written, and reads as **no logger
at all** to `scripts/arms.py`, whose freshness check looks at the last row's own
timestamp and at the file's mtime.

```bash
stdbuf -oL nvidia-smi --query-gpu=... --format=csv,nounits -lms 500 > power.csv
```

`scripts/power/sample-power.sh` does that for you, keeps `-f` only as a
fallback, proves either mode by watching the file GROW before it reports
success, and recovers the destination from `/proc/<pid>/fd/1` — a redirected
logger has no path in its command line, and the kernel is the only thing that
knows where its stdout went. On Windows the preference is the other way round
and is correct there: `scripts/power/README.md` section 3.

### SYMPTOM: `arms.py` prints "power log : NONE" and the fix it offers is PowerShell

The remedy line is `pwsh scripts/power/sample-power.ps1 -Start -Csv ...` on
every platform, so on Linux the one place the sweep runner tells an operator how
to repair a missing power log names a file that will not run there. The POSIX
starter writes the same CSV, in the same place, with the same eleven columns in
the same order and one more after them (`clocks_event_reasons.active`, which
rule 28 wants and `sample-power.ps1` does not yet collect):

```bash
bash scripts/power/sample-power.sh start --csv results/<slug>/data/power/campaign-power.csv
```

Start it, then run the sweep. The sweep that already ran without it keeps
`power_logging: false` on its `sweep_start` line and that stays true of it: rule
24 wants the absence written down at the time it happened, not repaired
retroactively.

### SYMPTOM: `machine.json` says `null` for `pl_writable_without_elevation`

Expected when the campaign runs elevated, and it is not a regression. The field
is a claim about the **unelevated** case, and `scripts/detect-machine.py`'s
`pl_write_test()` declines to answer it from a root shell: a set that succeeds
because the shell was privileged says nothing about a user who is not. It also
declines when elevation could not be determined at all — the field is named for
a condition, so a process that cannot say whether it was elevated cannot fill
it, and nothing is set. The reason travels in the record beside the null, and
says which of the two it was. Only an unelevated process can
fill it — `python scripts/detect-machine.py` once as an ordinary user — and rule
28 applies, so an all-elevated campaign never learns the answer and cannot
recover it from the artefacts afterwards.

The same run records `elevated`, `sudo_nopasswd` and `privilege_path` in
`machine.json` and inside the `execution` block on every probe line. On all
three, **`null` means unrecorded, never unelevated**; each carries its
`MEASURED` / `DERIVED` / `UNKNOWN` reason in `execution.how`.

### SYMPTOM: the bootstrap needs `sudo` and there is no human at the keyboard

Launch the agent from a root shell, or from an account whose `sudo` needs no
password, and pre-flight step 3 stops being a human step. That is a supported
operating mode, chosen deliberately for a fully automated run and for the power
registers that read only as root. `PROMPTS.md`, "The elevated, fully-automated
flow", carries both paths and what each costs; `scripts/power/README.md` section
4 carries what elevation buys, the one field it forfeits, and how a reader
compares an elevated run against an unelevated one.

`sudo -n true` is the probe that answers whether this session can elevate
without prompting — it never prompts, and `true` sets nothing. **It is not
free.** Every `sudo` invocation is an authentication event on the box being
measured, so `scripts/bench/provenance.py` runs it **once per interpreter** and
answers every later arm launch of that sweep from the one probe. Measured
2026-08-30 (WSL2 Ubuntu 24.04, sudo 1.9.15p5, uid 1000 in group 27): three calls
left three `authpriv` records in the journal while `/var/log/auth.log` showed
one, because rsyslog collapses identical repeats — **count in the journal, not
the file**, or the probe reads as cheaper than it is. Rule 27. Under WSL see
"`sudo -n true` fails" below, which documents the no-password root path that is
the WSL init switching users rather than a sudo bypass.

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

Both setup scripts write the same 41-field record: `tag, flavor, arch, os,
os_version, host, assets, urls, installed_utc, built_from_source`, plus
gpu/driver, the `llama-server --version` line, `source_commit` for a source
build, and which tools exist. `scripts/detect-machine.py` reads `flavor` from it
as the measured backend (and `os` as a token — `linux`/`windows`/`macos`). Copy
flavor + tag into `campaign.md` and the report's conditions block.

The fields that carry a build's measurement conditions:

| Field | What it settles |
|---|---|
| `cuda_arch`, `cuda_arch_source`, `cuda_arch_override` | which CUDA kernels were compiled, and whether the value was a default, a flag, or a GB10 override |
| `gb10`, `compute_cap` | whether this is a DGX Spark, and by which signal |
| `openvino_version`, `openvino_build`, `openvino_root` | the exact runtime the binaries link against |
| `openvino_device`, `openvino_install_path` | `GGML_OPENVINO_DEVICE`, and prebuilt asset against source build |
| `openvino_runtime_sha256` + `_provenance` | the runtime bytes, and how they were checked |
| `openvino_requantises` | `true` on any OpenVINO build — the file on disk is not the weights that ran |
| `openvino_npu_quant_ladder_degenerate` | `true` on NPU: a quant ladder there compares identical weights |
| `multimodal_supported` | `false` on OpenVINO — text only, so a vision stage measures nothing |
| `cpu_gen`, `npu_status`, `npu_findings` | the silicon generation and every unmet NPU prerequisite |
| `needs_ld_library_path`, `ld_library_path` | the loader path a launcher must set (on Windows this is `PATH`) |

### SYMPTOM: an idempotent re-run of setup wiped `cuda_arch` / `assets` / `source_commit`

Fixed 2026-08-29 in both scripts. Measured against the pre-fix `setup.sh`: a
second run over an already-installed CUDA source build rewrote
`built_from_source: false, cuda_arch: null, source_commit: null,
build_seconds: null, tools: [], assets: [], urls: []` — seven provenance fields
deleted by a run that installed nothing, which is rule 3's strongest condition
erased by a no-op. Both scripts now carry those fields forward from the existing
record when they skip the install. If you have a record showing
`built_from_source: false` beside a `flavor` you know was built from source, it
was written by a pre-fix re-run: rebuild with `-f`, or restore the fields by hand
from the campaign log rather than publishing the false ones.

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

### SYMPTOM: probe-smoke-test.py prints red on a tree you have not touched

**The baseline is empty, so any red line is yours.** Measured 2026-08-30, on
this tree with nothing built:

```
0 NEW. 0 known, 89 start, of 89 checked.
```

`scripts/verify/smoke-baseline.json`'s `entries[]` carries nothing. It once
carried eighteen known failures — the tool ended `18 of 83 FAILED` and exited 0
until 2026-08-29 — and those eighteen were fixed rather than re-recorded; they
survive in the file's `cleared` block as history. So `--fail` ("any failure
fails", which is what a hook wants) and the bare run ("exit non-zero on NEW
alone") now agree, because there is nothing left for them to disagree about.
The roster comes from `git ls-files`, so **89 moves with the tree** — it read
87 an hour earlier, before two verify scripts were added — and it is not the
number to watch. NEW and known are.

Nothing is skipped: every check runs on every file and every failure is
printed. A row whose probe starts passing prints as `STALE … PASSES NOW -
delete this row`, and a row whose recorded cause has stopped being true counts
as NEW. To add one, prove it is older than your work (`git log -1
--format=%cd -- <path>`), then write the row — never by deleting a check.

**One file of the roster has no argument parser**, so `--help` is not answered by
it, it is RUN — and that is how a smoke test once overwrote a published result.
It is `scripts/lib/openvino_quant.py`, and the checker now names it, says
plainly that it is a LIBRARY rather than a probe (nothing under `scripts/lib`
is launched by a stage; it is on the roster because every probe imports from
it), and reports what it did to the tree: `git status --porcelain` unchanged
across its `--help`, measured around that one subprocess. `MEASURED_INFERENCE_DRY_RUN=1`
is set on both subprocesses, so nothing on the roster can take the card.

The one file that DID write during a run is fixed. Measured 2026-08-29: one run
rewrote the campaign's published 280,937-byte quant-ladder figure at the IMPORT
stage, because `scripts/quant-ladder/make-ladder-png.py` had its whole 400-line
body at module level — so importing it drew the figure, and the new untracked
file then tripped `instrument-guard.py`. Fixed 2026-08-30: that body sits in
`main()` behind a parser with `--out` and `--check` (`--check` loads every
source and runs every cross-check without drawing), importing it writes
nothing, and the checker reports it at the `--help` stage like any other probe.
If you are holding an untracked copy of the figure from before the fix, delete
it — a real run reproduces it byte for byte (md5 `11159d63` over three runs).

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

## Intel OpenVINO backend

In mainline llama.cpp at `ggml/src/ggml-openvino/`, merged 2026-03-14. It reads
GGUF directly — no conversion — and covers Intel CPU, iGPU, Arc and NPU through
one build. Install it with `./scripts/setup.sh --openvino` (Linux) or
`.\scripts\setup.ps1 -OpenVINO` (Windows). Everything below was read from the
merged source or measured against the vendor artefacts on 2026-08-29.

### SYMPTOM: two quants score the same perplexity on an NPU, or a quant ladder shows no spread

**The arms are the same weights.** OpenVINO requantises the file before it runs
it, on every device, and says nothing. `ggml-openvino-extra.cpp:252-273`:

```
token_embd.weight -> F16 if (NPU and source Q6_K), else Q8_0_C   [ALWAYS, any device]
output.weight     -> Q8_0_C                                      [ALWAYS, any device]
if NPU            -> Q4_0_128   UNCONDITIONALLY, whatever the tensor type was
else Q6_K, Q5_K   -> Q8_0_C
```

So on NPU every quantized tensor other than those two collapses to one
representation: Q8_0, Q4_K_M, Q5_K, Q6_K and Q4_1 all become Q4_0_128, and even
Q4_0 is re-blocked from 32 to 128 weights per block — four times fewer scales
than the file carries. **A quant ladder on NPU is degenerate (rule 30); run it
on CPU or GPU.** It is a real rewrite, not a reinterpretation:
`requantize_to_buffers` (`ggml-quants.cpp:841`) dequantises to F32 and
re-quantises, and the `no_requant` escape is `use_bias`, asserted test-only at
`ggml-quants.cpp:1016`.

`Q8_0_C` and `Q4_0_C` are **channel-wise** — `weights_per_block = tensor->ne[0]`,
one scale per row — so `Q6_K -> Q8_0_C` is more bits at a *coarser* scale
granularity. Do not describe it as an upgrade; it is a different quantisation,
and which way it moves perplexity is a measurement, not a deduction.

`bin/llama.cpp/INSTALL.json` records `openvino_requantises: true` and
`openvino_npu_quant_ladder_degenerate` so a planner does not have to re-derive
this from the source tree.

### SYMPTOM: nothing in the log says a tensor changed type

There is nothing to find. The four `GGML_LOG_DEBUG` lines that would report it
are **commented out** at `ggml-openvino.cpp:332-346`, and `/props->description`
carries only `ov::get_openvino_version().description`
(`ggml-openvino.cpp:1546`) — the version string, nothing about quantisation.

Two things you can capture instead:

- `GGML_LOG_INFO("OpenVINO: using device %s\n", ...)` at
  `ggml-openvino.cpp:1526`, emitted once in `ggml_openvino_init()`. It prints the
  **resolved** device *after* availability fallback, so it is the one line that
  catches a silent NPU→CPU downgrade. Grep the server log for it on every launch.
- `GGML_OPENVINO_DUMP_IR=1` dumps the graph that actually ran. That is the proof
  of which tensor types executed; the filename is not.

### SYMPTOM: `llama-server` exits at once, or `error while loading shared libraries: libopenvino.so`

The runtime lives in its own versioned prefix so the active version stays
swappable, so it is not on the default loader path. `setup.sh` writes
`bin/llama.cpp/openvino-env.sh` (and `setup.ps1` writes `openvino-env.ps1`) with
the loader path and `GGML_OPENVINO_DEVICE` already set — source it before any
launch, or read `ld_library_path` out of `INSTALL.json`.

The runtime is the tarball, not the apt package: `/opt/intel/openvino_2026.3.1`
with an `/opt/intel/openvino` symlink. Pinned at **2026.3.1**, full build string
`2026.3.1.22476.56d9685302d`. Verified 2026-08-29, 110,961,409 bytes, sha256
`cb84d1cc…f96eb21b` for `openvino_toolkit_ubuntu24_..._x86_64.tgz`.

### SYMPTOM: the OpenVINO download is an HTML page named `.tgz`

Patch releases live in their **own** directory —
`.../openvino/packages/2026.3.1/linux/`, not `.../2026.3/linux/`. The shortened
prefix answers **200 with an HTML directory page**, not 404, so a wrong URL
downloads a web page under the archive's name and fails later at `tar`. Both
setup scripts check the sha256 against a pinned constant and the published
`.sha256` sidecar, which is what turns this into an error at download time.

### SYMPTOM: `machine.json` says `backend: cpu` on a box you built with `--openvino`

`scripts/detect-machine.py` carries `openvino` in its `BACKENDS` tuple as of
2026-08-29, so it reads that flavor out of `INSTALL.json` as the **measured**
backend and `--backend openvino` is accepted. A `cpu` reading therefore means the
record was not read, not that the tuple is short — the usual causes are no
`bin/llama.cpp/INSTALL.json` at all, or a record whose `os` token names a
different platform than the one running, which detect-machine reports as a
foreign build and refuses to trust. Check `backend` in `machine.json` against
`flavor` in `INSTALL.json` before either reaches a report; on an Intel box with
no NVIDIA card and no `rocm-smi` the fallback chain ends at `derived: cpu`, which
is a plausible-looking wrong answer rather than a blank.

### SYMPTOM: the second concurrent chat session hangs or errors on OpenVINO

`GGML_OPENVINO_STATEFUL_EXECUTION=1` is experimental, faster on CPU and GPU, and
**limits `llama-server` to ONE chat session**. Do not set it under a sweep that
uses parallel slots; if you do set it, it is an arm condition and travels with
every number from that arm (rule 3). Separately, `llama-server` on **NPU** cannot
handle parallel sequences at all: `--parallel 1`.

### SYMPTOM: an NPU run uses a context you did not ask for, and the fit is wrong

**`llama-server` on NPU needs an explicit `-c`.** Without one it defaults to the
model's training context, which is usually far larger than intended and moves
both the fit and the speed. Rule 3 — the window travels with the number; rule 16
— the window sets the effort ceiling, and a level whose appetite exceeds it
truncates rather than degrading.

### SYMPTOM: a vision stage on OpenVINO produces nothing

Multimodal is incomplete in this backend: it is **text-only** today.
`INSTALL.json` records `multimodal_supported: false`. Skip the vision stages and
say so, rather than shipping a stage that measured nothing (rule 2, rule 19 —
hallucinated "sight" is the worst outcome).

### What to expect: OpenVINO wins prefill, ties decode

CITED, 2026-04-05, Arc A770, Llama-3.2-1B: pp512 **16,305** (OpenVINO) against
**6,234** (Vulkan); tg128 **88.67** against **119.60**. So prefill is 3-4x and
token generation ties or loses. Decode on an iGPU is bandwidth-bound and
near-identical across Vulkan, SYCL and OpenVINO — the constant in rule 10 is what
moves, not the backend. Plan the arms accordingly: OpenVINO earns its place on
prompt-heavy work, not on long generations.

---

## Intel NPU

Run `./scripts/setup.sh --check-npu` (or `.\scripts\setup.ps1 -CheckNPU`). It
installs nothing, downloads nothing, and exits 7 when a prerequisite is unmet.

### SYMPTOM: SIGSEGV in `libopenvino_intel_npu_plugin.so`

**Arrow Lake.** Its NPU segfaults inside the OpenVINO NPU plugin — confirmed by
an Intel engineer on 2026-07-21, still open. There is no flag for it and it is
not a configuration problem. **Lunar Lake and Panther Lake work**; llama.cpp
validates the OpenVINO NPU path on a Core Ultra 5 238V (Lunar Lake), Ubuntu
24.04, NPU driver 1.35.0. A campaign pointed at an Arrow Lake NPU loses the day
and produces nothing, so run the Intel arms on GPU or CPU there.

Telling the parts apart, from the marketing model number (both setup scripts
classify on this, and default to caution on anything they do not recognise):

| Model number | Silicon | NPU |
|---|---|---|
| Core Ultra `1xx` (155H, 165U) | Meteor Lake | present, but the OpenVINO NPU path is validated on Lunar Lake — label any number from it unvalidated |
| Core Ultra `2xx` **V** (238V, 268V) | Lunar Lake | works |
| Core Ultra `2xx` H/HX/U/K/KF (265H, 285K, 225U) | **Arrow Lake** | **SIGSEGV — do not use** |
| Core Ultra `3xx` and Ultra X`n` `3xx` (355H, X7 358H) | Panther Lake | works |

### SYMPTOM: the NPU driver will not install on Ubuntu 22.04

It is not published for it. `intel/linux-npu-driver` **dropped 22.04 at
v1.28.0**, and v1.35.0 (published 2026-07-24) ships a single asset,
`linux-npu-driver-v1.35.0.20260722-29947505341-ubuntu2404.tar.gz`. Ubuntu 24.04
is the NPU platform; 22.04 can still run OpenVINO on CPU and GPU with the
`ubuntu22` runtime build, which `setup.sh` selects automatically from
`/etc/os-release`.

### SYMPTOM: `/dev/accel/accel0` is missing, or exists but cannot be opened

Missing means the `intel_vpu` kernel module is not loaded — it is in-tree from
Linux 6.7; check `modprobe intel_vpu` and `dmesg | grep -i vpu`. Present but
unopenable is a group problem, not a driver problem:

```bash
sudo usermod -a -G render $USER   # then log out and back in -- the group is read at login
```

The user-space half is the release tarball, not apt: `dpkg -i ./*.deb` for
`intel-driver-compiler-npu`, `intel-fw-npu` and `intel-level-zero-npu`, plus
`libtbb12`. `--check-npu` names whichever of these is missing, one line each.

---

## NVIDIA DGX Spark (GB10)

Detected by either of two independent signals (rule 4): the `nvidia-smi` board
name matching `GB10`, or `compute_cap` reporting `12.1`, which no other shipping
part does. Recorded as `gb10` and `compute_cap` in `INSTALL.json`.

### SYMPTOM: `setup.sh` exits 3 — "`-DCMAKE_CUDA_ARCHITECTURES=120` is refused"

Working as designed, and the refusal is the point. `120`, `120f` and `native`
are the workarounds that circulate for GB10; they all configure, compile and
run, and they all lose **`MMVQ_PARAMETERS_GB10`** — the GB10 matrix-vector kernel
parameters. The result is a working server that decodes slower, with no error
and nothing in the log, from a flag that until 2026-08-29 reached no artefact in
this repo. The architecture that keeps those kernels is **`121a-real`**, and
nothing else:

```bash
./scripts/setup.sh --cuda --cuda-arch 121a-real   # also the default once GB10 is detected
MEASURED_INFERENCE_ALLOW_CUDA_ARCH=1 ./scripts/setup.sh --cuda --cuda-arch 120  # deliberate, recorded
```

The override sets `cuda_arch_override: true` in `INSTALL.json`. No number from
such a build is comparable to a `121a-real` one (rule 30).

### SYMPTOM: no CUDA build exists for this box at any llama.cpp release

There is **no official Linux aarch64 CUDA binary**, at any tag. On a GB10 the
source build is not one option of two — it is the only one, and `setup.sh --cuda`
is the whole path. Without `--cuda` the script takes the `ubuntu-vulkan-arm64`
asset, and section 4's gate refuses to install it on an NVIDIA GPU. (Until
2026-08-29 this box got a CPU-only build silently: the aarch64 branch tested for
`vulkan-capable`, which `nvidia-smi` never sets.)

### SYMPTOM: VRAM readings look wrong, or a fit ceiling comes out absurd

**GB10 has 128 GB of unified memory and no discrete board.** `nvidia-smi` VRAM
sampling and the `board_total_mib - reserve` fit arithmetic **both fail
silently** there, which is worse than failing loudly: the numbers arrive, they
are wrong, and nothing marks them. Do not derive rule 13's ceilings from either
on this machine — measure the fit by loading, and state the memory as unified
with the host RAM figure beside it. Bandwidth is 273 GB/s, which is the number
rule 10's decode estimate takes.

Note the vendor-native alternative (vLLM with NVFP4) and what switching buys
before committing a campaign to llama.cpp here.

### SYMPTOM: `machine.json` says `memory_topology: system` on a Windows box with an Intel Arc part

The box has a GPU and has been profiled as a machine without one, which is the
worst of the three wrong answers because it is the only one that does not
refuse: `shared-igpu` refuses until somebody records the driver's share cap
with `--igpu-share-limit-mib N`, `discrete` refuses until somebody records a
board size with `--board-total-mib N`, and `system` prices the fit against host
RAM and **PASSES**.

CAUSE. On Windows there is no `/sys/class/drm` and no Intel vendor tool that
answers, and `Win32_VideoController`'s `AdapterRAM` is 32 bits wide and wrong
above 4 GB — so `board_total_mib` is 0 and the adapter NAME is the whole of the
evidence. Until 2026-08-30 the name test required `arc\s+\d+\w*\s+graphics`,
a plain space where every string Windows actually returns writes `Arc(TM)`
(`Intel(R) Arc(TM) B390 Graphics`). So no Arc-branded part matched at all; 0 is
falsy, so the miss then fell past the step-7 board-is-a-fraction-of-host-RAM
test as well, and the box landed on the CPU-only fallback.

FIX. Re-run `python scripts/detect-machine.py --slug <slug>` and read
`provenance.memory_topology` — it names the adapter string it matched and the
branch it took. The patched classifier separates the trademark mark from the
space (`Arc(TM)`, `Arc(R)`, `Arc™`, `Arc®` and a plain `Arc` all match) and asks
the BOARD question first, because both vendors sell the iGPU and the add-in
card under one brand: `Arc Pro`, `Arc A<nnn>` (Alchemist shipped discrete only)
and `Arc B5xx` through `B9xx` are boards — the pattern is `b[5-9]\d{2}[a-z]?`,
so the four bands above the shipped B570/B580 are claimed in advance — while
the Core Ultra's integrated Battlemage parts are `B3xx`. A box listing both
runs its campaign on the board. Then give it the size it cannot read:
`--board-total-mib N` on a board, `--igpu-share-limit-mib N` on an iGPU — and
note that an iGPU's share limit is NOT `MemTotal`.

The same symptom has an AMD shape, with the same cause and the same fix:
`rocm-smi` does not exist on Windows either, so the adapter name is again the
whole of the evidence. Until 2026-08-30 a Ryzen box answered `system` in all
three shapes — `AMD Radeon(TM) Graphics` alone (the APU's iGPU), that string
beside `AMD Radeon(TM) RX 7900 XTX`, and the board with no APU listed. All
three now classify from the name: `Radeon Pro`, `Radeon RX`, `Instinct` and
`MI<nnn>` are boards, `AMD Radeon(TM) Graphics` alone is an iGPU, and the pair
is `discrete` because that is the part the campaign runs on. The
`shared-igpu-radeon` and `discrete-radeon` fixtures in
`python scripts/detect-machine.py --self-test` pin the first two, and that
self-test is the first member of `scripts/verify/run-all.py`.

---

## Per-platform hardware notes

- **NVIDIA/CUDA** (reference campaign): everything in the stage files applies
  directly.
- **Intel Arc dGPU**: `setup.sh --openvino --openvino-device GPU` is the tuned
  path and wins prefill 3-4x; the Vulkan build is the comparison arm (SYCL has
  known Battlemage perf bugs; IPEX-LLM archived). Verify KV-quant support in the
  build. Read the OpenVINO section above before designing a quant arm — the file
  is not the weights that ran. **On Windows the topology is derived from the
  adapter NAME and the board size is unreadable**, so the campaign needs
  `python scripts/detect-machine.py --slug <slug> --board-total-mib N` before
  any fit resolves; `check-request.py`'s memory plan refuses on
  `board_total_mib: 0` rather than passing.
- **Intel iGPU (unified memory)**: the window is borrowed RAM, not a wall —
  document the Shared GPU Memory Override path; the effort ceiling is patience,
  not memory. State RAM speed/channels with every number. Decode here is
  bandwidth-bound and near-identical across Vulkan, SYCL and OpenVINO, so pick
  the backend on prefill and on what the campaign is measuring. **On Windows
  the topology is derived from the adapter NAME**, `Arc B3xx` and `Arc <n>V`
  parts being integrated where `Arc Pro` / `A<nnn>` / `B5xx`–`B9xx` are boards;
  the driver's share cap is unreadable, so the campaign needs
  `python scripts/detect-machine.py --slug <slug> --igpu-share-limit-mib N` —
  which is NOT `MemTotal` — before any fit resolves.
- **AMD Radeon, on Windows**: `rocm-smi` does not ship there, so **the topology
  is derived from the adapter NAME** exactly as it is for Intel. `AMD
  Radeon(TM) Graphics` alone is an APU's iGPU and needs
  `python scripts/detect-machine.py --slug <slug> --igpu-share-limit-mib N`;
  a `Radeon RX` / `Radeon Pro` / `Instinct` / `MI<nnn>` string is a board and
  needs `--board-total-mib N`; a box listing both is the board. On Linux
  `rocm-smi` answers and neither flag is needed. `check-request.py`'s memory
  plan refuses on the unrecorded size rather than passing.
- **Intel NPU**: Lunar Lake and Panther Lake only — Arrow Lake segfaults. Needs
  an explicit `-c`, `--parallel 1`, and Ubuntu 24.04. No quant ladder: every
  arm is the same weights. Full entries in "Intel NPU" above.
- **DGX Spark / GB10 (Ubuntu ARM)**: `setup.sh --cuda --cuda-arch 121a-real`,
  which is the default once GB10 is detected — `120`, `120f`, `121` and `native`
  are refused because they silently lose `MMVQ_PARAMETERS_GB10`. There is no
  official Linux aarch64 CUDA binary, so the source build is the only path;
  without `--cuda` the script takes the `ubuntu-vulkan-arm64` asset and the
  backend gate refuses it. (Until 2026-08-29 this box got a CPU-only build
  silently: the aarch64 branch tested for `vulkan-capable`, which `nvidia-smi`
  never sets.) Unified memory: `nvidia-smi` VRAM and the fit arithmetic both lie.
  Note the vendor-native alternative (vLLM/NVFP4) with what switching buys.
- **Apple Silicon (Metal)**: in scope — `setup.sh` fetches the official
  `macos-arm64` release (Metal built in; no `-ngl` spill risk, unified memory).
  The "VRAM" ceiling is the Metal working-set limit
  (`recommendedMaxWorkingSetSize`, ~66-75% of RAM by default); state total RAM
  with every number and watch for swap, not spill. Intel Macs get the CPU-only
  official build — treat like the CPU path or build Metal from source.
- **OpenVINO**: implemented — `setup.sh --openvino` / `setup.ps1 -OpenVINO`
  install the pinned 2026.3.1 runtime and take the prebuilt
  `ubuntu-openvino-2026.3.1-x64` (or `win-openvino-2026.3.1-x64`) llama.cpp
  asset, falling back to `-DGGML_OPENVINO=ON` from source on Linux when a
  release publishes none. Section "Intel OpenVINO backend" above carries the
  traps. OVMS with int4-ov weights remains an unexplored second Intel path;
  benchmark it against this one before assuming either.

### Energy counters by platform (rule 24 tiers)

- **NVIDIA**: NVML via `nvidia-smi --query-gpu=power.draw` — in-band GPU board.
  Start the logger with `scripts/power/sample-power.ps1` on Windows or
  `scripts/power/sample-power.sh` on POSIX; both write the same CSV. Never with
  a bare `-f` on Linux — see "the power CSV exists but is empty" above. Reading
  board power needs no elevation; setting a cap with `nvidia-smi -pl` does, and
  it moves every watt taken afterwards.
- **Intel Arc/iGPU**: HWiNFO64 (sensor logging to CSV) on Windows, or RAPL on
  Linux (package scope).
- **Apple Silicon**: `sudo powermetrics --samplers gpu_power,cpu_power -i 1000`.
- If no counter is readable without installing something on a borrowed machine,
  **mark the energy work unmeasured** rather than estimating from TDP.
