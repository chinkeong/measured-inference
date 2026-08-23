---
name: field-guide
description: >
  Run a full measurement campaign against a new local LLM and produce a published
  field-guide HTML report. Trigger when the user gives a HuggingFace model/GGUF URL
  and asks for "a report", "a field guide", "measure this model", or "sweep the
  hardware for best settings". Interviews once, then runs autonomously for hours
  to days: hardware sweep, speed/quality/context/effort/vision/agent measurements,
  every number condition-labeled, output like templates/example-report.html.
---

# field-guide — the campaign skill

You are about to run a measurement campaign. The product is a single-page HTML
field guide for one model on one machine, in which **every recommendation carries
the number that justifies it**. `templates/example-report.html` is a complete,
real example (Qwen3.8-27B on an RTX 3090); `templates/REPORT-SPEC.md` defines the
structure; `methodology/METHODOLOGY.md` is the law — read all three before Phase 0.

The prime directive, from the person you are working for:
**no reader may ever measure less than the report promised them.**

## Phase 0 — the interview (the ONLY time you may ask questions)

Ask everything up front, in ONE round. After this, run autonomously to the end;
never block on the user. Confirm auto-detected facts rather than asking open
questions.

1. **Model**: the HF URL(s). Resolve the repo file listing (HF API
   `/api/models/<repo>/tree/main`) and propose which quants to measure (a Q4-class
   primary + challengers: same-size alternates, one smaller IQ-class, vendor
   variants) and whether an mmproj/vision projector exists. Confirm the set.
   **Prove access before the interview closes**: a gated or private repo fails
   at Phase-1 download time, when the no-questions rule has already locked you
   out of asking. Test with a range request on one chosen file
   (`curl -sI -r 0-1023 <resolve-url>` → expect 206/200, not 401/403; the
   listing API itself succeeds on gated repos, so listing is not proof). If it
   401s, ask for an HF token in this same round and confirm it works
   (`Authorization: Bearer <token>`) before proceeding.
2. **Machine**: auto-detect (GPU via nvidia-smi / lspci, VRAM, RAM speed+channels,
   CPU threads, OS, disk free) and present the detection for confirmation. RAM
   channels matter: single-stick machines halve every offload/iGPU estimate.
3. **Use cases**: text coding / vision-screenshot loops / coding agents / long
   context? This decides which optional phases run.
4. **Time budget**: overnight (~8 h) vs. multi-day. Present the concrete plan
   it buys and confirm that, not the hours:
   - **overnight** = primary + 1 challenger get the full treatment (n=200
     accuracy each, full PPL on those two); remaining proposed quants get
     load-and-speed probes only; Phase 7 runs at 2 runs × 3 levels on one file.
   - **multi-day** = every proposed quant gets the full treatment (n=200 per
     arm, full PPL on every file), plus the Phase 4 ceiling sweep per file and
     Phase 7 accuracy per effort level.
     Anything below overnight is a smoke test: say so in the report, and never
     publish a quant ranking from it.
5. **Philosophy**: quality-first (ship max effort where the window allows — the
   default) or latency-first. Also: does the model expose an effort/thinking knob
   (check the chat template) — if yes, Phase 7 runs.
6. **Publish target**: results/<slug>/index.html always; plus a git remote / site
   directory if the user names one. **`<slug>` = the model repo name,
   lowercased, as a single path component** — no slashes, `-GGUF` suffix
   dropped: `huggingface.co/unsloth/SomeNew-32B-GGUF` → `somenew-32b`. Confirm
   it in this round and record it in `campaign.md`; after a crash, reuse that
   exact slug rather than deriving a second one.
7. **Coding agents** (feeds Phases 8–9): auto-detect installed agents (probe
   PATH for `opencode`, `aider`, `qwen`, `pi`, `dsh`, `claude`, …) and present
   the detected roster. Confirm which to test, and whether missing ones may be
   installed for the campaign (npm/pip, user-scope only — the machine may be
   borrowed). If the answer is "none", Phases 8's agent-attach matrix and Phase 9
   are skipped and the report says so explicitly.

Record all answers in `results/<slug>/campaign.md` (the campaign log — append
decisions, findings, and timestamps to it throughout; it is your recovery point
after any restart).

## Standing rules (memorize before Phase 1)

- **Measured, cited, or labeled**: every number in the report is (a) measured on
  this machine, (b) cited to a source URL found via live search, or (c) explicitly
  marked as derived arithmetic. No fourth category.
- **Conditions travel with numbers**: decode t/s means nothing without content
  type, context depth, sampling temp, and desktop state. The example report's
  §06 band table is the pattern.
- **Long jobs run detached** (`Start-Process` a runner script writing to a log)
  because harness background tasks may be killed near 10 minutes. Watch logs via
  polling/monitor on a DONE marker. Make every long script **resumable** (skip
  work whose output log already shows a final result).
- **Checkpoint commits** after every completed phase — the machine may be shared
  or crash.
- **PowerShell 5.1 traps** (Windows): `Write-Output` inside a function pollutes
  its return value (use `Write-Host` for logs); parse-check scripts before
  detaching (`[scriptblock]::Create((Get-Content -Raw file))`); double quotes
  inside git commit messages get mangled; native stderr wraps as error records.
- **POSIX equivalents** (Linux/macOS — every reference script is PowerShell;
  `scripts/probe-config.sh` is the ported seed to adapt from):
  - Detach: `setsid nohup ./run.sh > run.log 2>&1 &` (or `nohup … &`); poll the
    log for a DONE marker, same as the Windows path.
  - Parse-check before detaching: `bash -n script.sh` (the `[scriptblock]`
    equivalent); `set -euo pipefail` at the top of every runner.
  - VRAM/spill diagnostics: NVIDIA `nvidia-smi --query-gpu=memory.used
    --format=csv -l 1` (no Get-Counter needed — per-process is visible via
    `nvidia-smi --query-compute-apps=pid,used_memory --format=csv`); Intel
    `intel_gpu_top`; Apple `powermetrics --samplers gpu_power` plus Metal
    working-set (there is no spill — watch swap with `vm_stat`).
  - Process control: `pkill -f llama-server` for the `Stop-Process` calls.
- **The GPU is single-file**: one measurement job at a time; serialize via
  completion markers.
- **Verify your own probes**: a metric that divides tokens by wall time including
  prefill will lie to you at depth. Prefer the server's own `timings` fields
  (prompt_per_second / predicted_per_second / draft acceptance).

## The phases

Run in order. Each phase ends with: results appended to `campaign.md`, raw logs in
`results/<slug>/data/`, and a checkpoint commit. Scripts in
`scripts/reference-3090/` are the proven implementations from the reference
campaign — **adapt paths/models into `results/<slug>/work/`, do not edit the
references**.

### Phase 1 — acquire (network, parallel with nothing)
`scripts/setup.ps1|sh` fetches a llama.cpp build into `bin/` for this platform.
Download the chosen quants + mmproj into `models/` (curl, resumable, verify byte
sizes against the HF listing). Download nothing you won't measure.
**Start the Phase 10 power logger now** (Phase 10, Step 0 — the detached 500 ms
`nvidia-smi` CSV): it is nearly free and it turns every phase below into power
data instead of a rerun. Take the cold idle baseline before the first load.

### Phase 2 — foundation & sanity
- Read the model's `config.json`: layer count, full-attention pattern, KV
  heads/head_dim → compute **KV bytes/token** (the budget-table backbone):

  **KV bytes/token = 2 × full-attention layers × n_kv_heads × head_dim ×
  bytes-per-element** — 2 = K and V; bytes-per-element = 2 for fp16 cache, 1
  for `q8_0`. For a plain transformer, full-attention layers = all layers. For
  hybrids (the reference model is Gated-DeltaNet + full attention every 4th
  layer) count only the full-attention ones; linear/gated-delta layers carry a
  fixed-size state, and sliding-window layers cap at their window — note both
  as separate constants rather than folding them into the per-token figure.
  Sanity-check the result against the server's reported KV size at a known
  `-c`; if they disagree, trust the server and say why in `campaign.md`.

  If the GGUF repo has no `config.json` (common for quant-only repos), read the
  base model repo it was converted from, or take the values from llama-server's
  own GGUF metadata dump at load time (`n_layer`, `n_head_kv`, `n_embd_head_k` /
  `n_embd_head_v` in the startup log).
- **The -ngl trap**: llama.cpp counts the output layer as layer n+1. Always use
  `-ngl 99`; verify with a baseline probe that decode ≈ bandwidth ÷ file-size ×
  0.7 (reference: `probe-config.ps1` — note its header warning: it defaults to
  `-ngl 64` and relies on callers passing `-ngl 99`; POSIX seed:
  `scripts/probe-config.sh`, which defaults correctly). If it lands far low with
  high CPU and ~60% GPU util, an output layer is on the CPU.
- Spill prevention: document "Prefer No Sysmem Fallback" (NVIDIA) or platform
  equivalent; record the machine's idle VRAM (desktop overhead).
- Discover the effort/thinking knob (`--chat-template-kwargs`) and the sampling
  the model card recommends.

### Phase 3 — speed: baseline, speculation, the acceptance curve
- Baseline (no spec) at temp 0, short code probe → the **floor**.
- Discover drafting options (built-in MTP head? companion draft model?
  DFlash-style heads?). **Name every mechanism available and mark each
  measured or unmeasured** — an omitted alternative reads as nonexistent.
  Sweep n-max × p-min on a realistic code probe (~10 configs; reference:
  `spec-sweep.ps1`). Expect high p-min to win at real acceptance rates.
- **Declare the token regime with every speed**: thinking tokens and answer
  tokens decode at different rates under speculation (blind reproduction:
  same file, same depth, 39 vs ~70 t/s across regimes; verbatim-copy answers
  hit 148.7). A t/s number without its regime is a different measurement in
  disguise.
- **The acceptance demonstration**: same flags, novel-code probe vs
  copy-this-text-verbatim probe (reference: `accept-demo.ps1`). The spread IS the
  speed story; any published speedup without its acceptance rate is unfalsifiable.
- Record floor / real-work band / ceiling for the report's spec strip.

### Phase 4 — memory: budgets and the two ceilings
- Budget table from KV arithmetic (context × KV-type × largest fitting quant).
- **Ceiling sweep** (reference: `ctx-limit-sweep.ps1`, `iq4-ctx-sweep.ps1`): step
  `-c` upward with short probes + VRAM readings. Report BOTH ceilings: fully
  resident (dedicated VRAM fills) and shallow-safe (probes stay fast on
  overcommitted windows), plus the collapse point. Label per file, per
  mmproj-on/off, AND per drafter-on/off — a ceiling belongs to a
  configuration, not a file. **Measure the drafter's VRAM bill as an on/off
  pair** (reference: 1,008 MiB fixed + 5,120 B per window token + 898 MiB at
  n-max 10 vs 4 — the reference guide's "no VRAM cost" was a published error
  a blind run caught). **No window is labeled resident/safe without at least
  one deep-fill probe near its top** — a shallow probe on an overcommitted
  window reads fast right up until deep pages are touched (measured collapse:
  8.0 t/s at 91k fill). State the desktop-slack rule **using this model's
  computed KV cost from Phase 2**, not a remembered constant (reference
  model: each 32k of q8 window ≈ 1 GiB, projector ≈ 0.9 GiB ≈ 27k tokens —
  reference finding, recompute per model).
- Ship desktop-safe defaults; fence bare-desktop configs loudly (a browser UI
  once pushed the Windows compositor to 3.6 GiB and halved a "fitting" config).

### Phase 5 — depth
Depth/prefill series (reference: `nuance-suite.ps1` part 1): fixed probes at
increasing prompt depths; report decode and prefill vs depth with acceptance
shown steady (or not). Use server timings, never wall-clock-including-prefill.
Declare the series' parity (drafter on/off, projector on/off, token regime) —
two series with mismatched parity are different experiments, not one curve.

### Phase 6 — quality: rank with perplexity, smoke-test with accuracy
- **Perplexity ranks quants** (METHODOLOGY rule 6 — the wikitext-2-raw test
  split, 294,912 token positions = 36 × 8,192-token chunks; reference:
  `ppl-compare.ps1`, resumable, one model per invocation if the platform
  kills long tasks). Verify the KV-quant claim while here (fp16 vs q8_0
  cache). **q4_0 K-cache is not a free next step** — never recommend it
  without its own measured PPL check; absent the check, say "unverified
  here".
- **Spot-read long greedy transcripts for repetition loops** before trusting
  their tokens or timings — greedy makes a loop deterministic, and a looping
  transcript inflates t/s and token counts with garbage.
- **Accuracy smoke-tests** (scripts/bench/bench.py, `--greedy --score`): n=200 on
  a checkable dataset for the chosen quants. Statistics law: n≤25 detects only
  ~20-pt collapses; 1–3-pt quant gaps need thousands — never present small-n
  accuracy as a ranking.
- **The budget rule**: cap high enough that the longest thinker cannot hit it;
  report truncation counts; if an arm truncates, RAISE the cap and rerun that arm
  only (greedy determinism) — NEVER filter to non-truncating questions
  (selection bias).

### Phase 7 — effort (if the model has a thinking/effort knob)
References: `sweep-efforts.ps1` (pass 1: one run per level, saves thinking +
answer), `sweep-pass2.ps1` (pass 2 at fresh sampling → the second independent
sample per level), `sweep-tune.ps1` (finds the largest fast context first, then
sweeps there), `extract-html.ps1` (pulls the HTML answer out of each sweep
output), `effort-gsm8k.ps1` + `xhigh-16k.ps1` (accuracy per level, and the
rerun that removes a truncation artifact).

- Cost: 2 runs per level on a hard generative task — tokens, wall, t/s. The
  reference task ships as `templates/effort-task-example.md` (the aquarium
  page: one self-contained HTML file, a mandated CONFIG object, and a long
  checkable requirement list). Reuse it, or write one with the same shape: a
  single deliverable file, and requirements a judge can tick off one by one.
- Quality: **blind-judge the outputs with subagents.**
  1. **Independent judges**: one fresh subagent per output, no shared context,
     each seeing only the task spec and one candidate — never the set at once,
     never the campaign log.
  2. **Score /100 against a spec checklist**, weighted: 60 compliance (each
     numbered requirement met/partial/missed), 25 correctness (real bugs found
     by reading and by running the page), 15 craft (structure, readability,
     the CONFIG object actually being tunable).
  3. **Blind and randomize**: strip effort labels and any thinking traces,
     rename files to opaque ids (`candidate-a` … ), shuffle the order per
     judge, and only re-attach labels after every score is in. Ties are a
     legitimate verdict — at n=2 per level, say "tie" rather than crowning
     noise, and report the within-level spread beside the mean.
- Accuracy per level via the **standard benchmark protocol** (METHODOLOGY rule 21: SEED=42, N=25 per benchmark, 16,384 cap, the 7-benchmark suite, normalized Mean as the headline). Per-cell = smoke test; the Mean and categorical collapses are the claims. Escalate suspicious cells to n=200.
- Derive the **window-sets-the-effort-ceiling table**: measured thinking appetite
  per level vs. each recipe's context window.

### Phase 8 — vision (if an mmproj exists)
- Resolution→token map (`--image-min-tokens` / `--image-max-tokens`); measure a
  real 4K screenshot's prompt_tokens.
- **The critique loop proof**: render something with the model's own code (Phase
  7 outputs work), headless-screenshot it, send it back, judge whether the
  critique names real content. Multi-image test with one intentionally broken
  page as the discriminator.
  **Detect the browser before relying on it** — do not assume Chrome. Try, in
  order: `chrome`/`google-chrome`/`chromium` on PATH; then stock Edge, which
  needs no install on Windows
  (`msedge --headless=new --disable-gpu --screenshot=shot.png --window-size=1920,1080 file:///…`,
  same flags as Chrome — `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`);
  then Playwright/Puppeteer if either is already present. If none exists,
  **do not install a browser on a borrowed machine and do not fake the loop**:
  run the still-valid parts (resolution→token map, agent-attach matrix with a
  pre-made image), and record in `campaign.md` and the report that the critique
  loop was not measured on this machine and why. An unmeasured loop is reported
  as unmeasured — never as a pass.
- **Agent-attach matrix**: for every coding agent confirmed in interview item 7,
  test headless image attachment with a question only answerable by seeing the
  image; verdicts PASS / FAIL-honest / FAIL-hallucinated (flag hallucination
  loudly). Known traps: capability must be declared in OpenCode (`attachment` +
  `modalities`) and Qwen Code (`capabilities.vision`); DSH needs client-side
  maxTokens or long replies truncate. Use the invocation matrix below.

### Per-agent headless invocations (reference campaign, verbatim)
Configs are printed in full in the example report's coding-agents appendices —
apply those first (base URL `http://localhost:1234/v1`, the model id the server
reports). One-shot test commands as run on the reference machine; drop the image
argument for the Phase 9 text-only pass:

| Agent | One-shot + image attach | Config gate for vision |
|---|---|---|
| OpenCode | `opencode run "@shot.png <question>" --model llamacpp/<id>` | model must declare `"attachment": true` + `"modalities": {"input": ["text","image"]}` in opencode.json — a bare model entry reads the PNG as bytes (verified v1.18.21, issue #15728) |
| aider | `aider --model openai/<id> --edit-format diff --timeout 3600 --message "<question>" shot.png` | `supports_vision: true` in `.aider.model.metadata.json` |
| Qwen Code | `qwen -p "@shot.png <question>"` | model declared in settings.json `modelProviders` with `capabilities: {vision: true}` — env-vars-only setup silently drops images |
| Pi | `pi --model llamacpp/<id> --no-session -p "<task>" shot.png` | provider's models.json must list `"image"` in `input`; set client-side `maxTokens` |
| DeepSeek Harness | no attach flag — reference the image path inside the task text | settings.yaml model `input: [text, image]`; BOTH the provider block and the `agent-default-model` routing block (else MISSING_CREDENTIAL); client-side `maxTokens` required |

Judging: the probe question must be unanswerable without the pixels (e.g. "how
many fish are on screen and what color is the seahorse"). PASS = names real
content; FAIL-honest = says it cannot see an image; FAIL-hallucinated =
confidently describes content that isn't there. Agent CLIs drift: if a command
errors, verify flags against the installed version's `--help` and document the
delta — **never publish a FAIL produced by an invocation you invented**.

### Phase 9 — agents end-to-end
Verify each coding agent confirmed in interview item 7 against the served model
with a one-shot request (matrix above, text-only) using exactly the configs the
report will print. Fix and document, don't paper over (the reference campaign
found a missing `--alias` and a missing routing block this way).

### Phase 10 — power (the logger starts at Phase 1, not here)
Executes **METHODOLOGY rule 24** — read it before this phase; it defines every
metric and every label below. Deliverables: the per-recipe energy block for
REPORT-SPEC §8, the per-effort split for §4, and the **per-axis J/token
matrix**, which is what turns energy from trivia into an argument.

**Step 0 — start the logger at campaign start and leave it running.** A 500 ms
CSV log costs one process and a few MB a day, and it retroactively converts
every later phase into power data: the spec sweep, the ceiling sweep, the depth
series, the rule-21 suite and the effort runs all become energy arms *for free*
if the log was already running when they ran. Rerunning them later for watts is
hours you do not need to spend. Start it detached at the top of Phase 1:

```powershell
# Windows — detached; survives harness session restarts
$q = "timestamp,power.draw,power.draw.instant,clocks.current.sm," +
     "clocks.current.memory,utilization.gpu,utilization.memory," +
     "memory.used,memory.reserved,temperature.gpu,pstate"
Start-Process nvidia-smi -WindowStyle Hidden `
  -ArgumentList "--query-gpu=$q","--format=csv","-lms","500" `
  -RedirectStandardOutput results/<slug>/data/power/campaign-power.csv
```
```bash
# POSIX
nohup nvidia-smi --query-gpu=timestamp,power.draw,power.draw.instant,\
clocks.current.sm,clocks.current.memory,utilization.gpu,utilization.memory,\
memory.used,memory.reserved,temperature.gpu,pstate \
  --format=csv -lms 500 > results/<slug>/data/power/campaign-power.csv &
```
Clocks, pstate and util are in the query on purpose: they are how you prove a
low-watt sample was a **ramping** board (rule 24's clock-ramp caveat) rather
than an efficient one. One file per phase is fine — record each filename and
its start time in `campaign.md`, and restart the logger after any reboot.

**Step 1 — baselines first, dated, both flavors.** Before the model loads:
board idle, no server, n≥15 samples (reference 2026-08-22: **33.2 W**). Once
the server is up and idle: loaded-idle (reference: **30.7–31.1 W** — a resident
model costs almost nothing until asked). Both go in `campaign.md` with date and
tier label; every idle-subtracted figure downstream depends on them. Take the
baseline **cold** — a board still cooling from the previous phase reads high
(one reference log's first 10 samples averaged 58.0 W against the 33.2 W cold
reading) — or state which it was.

**Step 2 — join to server timings; never average a whole run.** For every
measured request, record the request's start timestamp alongside the server's
`timings` block. Then:
- prefill window = `[t0, t0 + prompt_ms/1000]` → mean W over those samples ×
  window seconds = **J_prefill**; ÷ `prompt_n` = **J per prompt-token**.
- decode window = `[t0 + prompt_ms/1000, + predicted_ms/1000]` → **J_decode**;
  ÷ `predicted_n` = **J/token**; `predicted_n ÷ (J_decode/3.6e6)` =
  **tokens/kWh**; `J_decode × decode-seconds` = **EDP (J·s)**.
- **Wh/answer = (J_prefill + J_decode)/3600**, reported twice: gross, and
  idle-subtracted (subtract loaded-idle W over the same windows).
Drop the first post-idle request from every arm and say so. Reference
integrator to adapt: `results/qwen38-27b-blind/work/power-integrate.py` —
**use the Python one**; the PowerShell version tripped over 5.1's
`TryParseExact` overload resolution.

**Step 3 — the per-axis J/token matrix** (rule 24's axis clause; this is the
phase's real product). One row per arm, columns: mean W · J/token decode ·
J/prompt-token · tokens/kWh · EDP · verdict. Axes, each measured or carrying an
explicit "not measured" row: **quant** (each candidate file), **drafter**
(`--spec-type` off vs each tuned config — expect t/s up at flat W, so J/token
down; quantify), **KV dtype** (f16 vs q8_0), **`--parallel`** (1 vs 2,
aggregate — batching amortizes a fixed draw), **depth** (reuse the Phase 5
series: t/s falls; does W fall with it?), **effort level** (Phase 7), and
**token regime** (thinking vs answer — same server, different J/token). If the
log from Step 0 was running during those phases, most of this matrix is a query
over CSV you already have.

**Step 4 — the power cap.** `nvidia-smi -pl <W>` (3090 stock 350 W; Linux may
need `-pm 1` first) is the one knob that directly buys efficiency — sweep it
(e.g. 350 / 300 / 250 / 200 W) into the same matrix. It needs an elevated
shell: if the campaign cannot elevate, do **not** estimate — print the command
and the stock cap in the report and mark it "unmeasured on this machine
(requires administrator)".

**Step 5 — per-recipe energy** for REPORT-SPEC §8: one identical real
generation per shipped recipe (a real answer, not an idle server), integrated
as in Step 2. Label the tier on the table: on an NVML-only machine, "in-band
GPU board power (NVML); PSU losses and PUE excluded" — never call it system
power. Short windows understate sustained load (reference: 10 s recipe probes
read 277–287 W where multi-minute runs sustained 344 W, because the early
samples catch the ramp) — quote the per-1k-token figures for planning and say
which is which.

- **Non-NVIDIA**: Intel Arc/iGPU — HWiNFO64 (sensor logging to CSV) on Windows,
  or RAPL on Linux (`/sys/class/powercap/intel-rapl/*/energy_uj`, differenced
  over the window: J = ΔµJ/1e6, kWh = J/3.6e6); Apple Silicon —
  `sudo powermetrics --samplers gpu_power,cpu_power -i 1000`. All three are
  in-band tiers with different scopes (RAPL is package, not board) — label
  which. If no counter is readable without installing something on a borrowed
  machine, **mark the phase unmeasured** rather than estimating from TDP.
- **Wall tier**: if a PDU or plug meter exists, log it too and report both
  tiers — that is the only way to state PSU + system overhead as measured.
  Absent one, the report says the overhead is excluded and unmeasured.

### Phase 11 — the report
Build `results/<slug>/index.html` per `templates/REPORT-SPEC.md`, using
`templates/example-report.html` as the structural exemplar. Then run THREE
review passes with fresh subagents before calling it done: numeric consistency
(against the campaign log's canonical numbers), structural (TOC/anchors/tags),
and reader-experience (can a first-time reader reach a confident config decision
without contradictions?). Apply must-fixes; commit; publish per the interview.

## Per-platform notes
- **NVIDIA/CUDA** (reference campaign): everything above applies directly.
- **Intel Arc dGPU**: llama.cpp Vulkan build (SYCL has known Battlemage perf
  bugs; IPEX-LLM archived). Verify KV-quant support in the build.
- **Intel iGPU (unified memory)**: the window is borrowed RAM, not a wall —
  document the Shared GPU Memory Override path; the effort ceiling is patience,
  not memory. State RAM speed/channels with every number.
- **DGX Spark / GB10 (Ubuntu ARM)**: llama-server ARM build; note the
  vendor-native alternative (vLLM/NVFP4) with what switching buys.
- **Apple Silicon (Metal)**: in scope — `setup.sh` fetches the official
  `macos-arm64` release (Metal built in; no `-ngl` spill risk, unified memory).
  The "VRAM" ceiling is the Metal working-set limit
  (`recommendedMaxWorkingSetSize`, ~66-75% of RAM by default); state total RAM
  with every number and watch for swap, not spill. Intel Macs get the CPU-only
  official build — treat like the CPU path or build Metal from source.
- **OpenVINO (future)**: not yet implemented — record the intent: OVMS with
  int4-ov weights as Intel's tuned path; benchmark against Vulkan llama.cpp.

## Failure library (diagnose before blaming hardware)
Silent VRAM spill (dedicated pinned + shared growing + flat-slow decode at every
window) · the -ngl off-by-one (survives reboot, high CPU, ~60% GPU util) ·
client max_tokens cut-offs (empty answers with completed thinking) · benchmark
budget truncation · Windows nvidia-smi per-process blindness (use the
Get-Counter GPU Process Memory counters) · busy-spin CPU is normal, CPU+slow is
not. The example report's §10 documents each with its measured signature.
