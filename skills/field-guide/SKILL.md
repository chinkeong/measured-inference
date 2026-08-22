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
2. **Machine**: auto-detect (GPU via nvidia-smi / lspci, VRAM, RAM speed+channels,
   CPU threads, OS, disk free) and present the detection for confirmation. RAM
   channels matter: single-stick machines halve every offload/iGPU estimate.
3. **Use cases**: text coding / vision-screenshot loops / coding agents / long
   context? This decides which optional phases run.
4. **Time budget**: overnight (~8 h) vs. multi-day. Sets n for accuracy runs
   (n=200 baseline) and how many quants get the full treatment.
5. **Philosophy**: quality-first (ship max effort where the window allows — the
   default) or latency-first. Also: does the model expose an effort/thinking knob
   (check the chat template) — if yes, Phase 7 runs.
6. **Publish target**: results/<slug>/index.html always; plus a git remote / site
   directory if the user names one.
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

### Phase 2 — foundation & sanity
- Read the model's `config.json`: layer count, full-attention pattern, KV
  heads/head_dim → compute **KV bytes/token** (the budget-table backbone).
- **The -ngl trap**: llama.cpp counts the output layer as layer n+1. Always use
  `-ngl 99`; verify with a baseline probe that decode ≈ bandwidth ÷ file-size ×
  0.7 (reference: `probe-config.ps1`). If it lands far low with high CPU and
  ~60% GPU util, an output layer is on the CPU.
- Spill prevention: document "Prefer No Sysmem Fallback" (NVIDIA) or platform
  equivalent; record the machine's idle VRAM (desktop overhead).
- Discover the effort/thinking knob (`--chat-template-kwargs`) and the sampling
  the model card recommends.

### Phase 3 — speed: baseline, speculation, the acceptance curve
- Baseline (no spec) at temp 0, short code probe → the **floor**.
- Discover drafting options (built-in MTP head? companion draft model?). Sweep
  n-max × p-min on a realistic code probe (~10 configs; reference:
  `spec-sweep.ps1`). Expect high p-min to win at real acceptance rates.
- **The acceptance demonstration**: same flags, novel-code probe vs
  copy-this-text-verbatim probe (reference: `accept-demo.ps1`). The spread IS the
  speed story; any published speedup without its acceptance rate is unfalsifiable.
- Record floor / real-work band / ceiling for the report's spec strip.

### Phase 4 — memory: budgets and the two ceilings
- Budget table from KV arithmetic (context × KV-type × largest fitting quant).
- **Ceiling sweep** (reference: `ctx-limit-sweep.ps1`, `iq4-ctx-sweep.ps1`): step
  `-c` upward with short probes + VRAM readings. Report BOTH ceilings: fully
  resident (dedicated VRAM fills) and shallow-safe (probes stay fast on
  overcommitted windows), plus the collapse point. Label per file and per
  mmproj-on/off; state the desktop-slack rule (each 32k of window ≈ 1 GiB).
- Ship desktop-safe defaults; fence bare-desktop configs loudly (a browser UI
  once pushed the Windows compositor to 3.6 GiB and halved a "fitting" config).

### Phase 5 — depth
Depth/prefill series (reference: `nuance-suite.ps1` part 1): fixed probes at
increasing prompt depths; report decode and prefill vs depth with acceptance
shown steady (or not). Use server timings, never wall-clock-including-prefill.

### Phase 6 — quality: rank with perplexity, smoke-test with accuracy
- **Perplexity ranks quants** (~330k token positions; reference:
  `ppl-compare.ps1`, resumable, one model per invocation if the platform kills
  long tasks). Verify the KV-quant claim while here (fp16 vs q8_0 cache).
- **Accuracy smoke-tests** (scripts/bench/bench.py, `--greedy --score`): n=200 on
  a checkable dataset for the chosen quants. Statistics law: n≤25 detects only
  ~20-pt collapses; 1–3-pt quant gaps need thousands — never present small-n
  accuracy as a ranking.
- **The budget rule**: cap high enough that the longest thinker cannot hit it;
  report truncation counts; if an arm truncates, RAISE the cap and rerun that arm
  only (greedy determinism) — NEVER filter to non-truncating questions
  (selection bias).

### Phase 7 — effort (if the model has a thinking/effort knob)
- Cost: 2 runs per level on a hard generative task (a complex single-file page
  spec works; see the example's aquarium prompt) — tokens, wall, t/s.
- Quality: **blind-judge the outputs with subagents** (spec-compliance checklist
  + real-bug audit + within-set ranking allowed to declare ties). n=2 honesty:
  report variance, don't crown noise.
- Accuracy per level at n=200 with clean caps.
- Derive the **window-sets-the-effort-ceiling table**: measured thinking appetite
  per level vs. each recipe's context window.

### Phase 8 — vision (if an mmproj exists)
- Resolution→token map (`--image-min-tokens` / `--image-max-tokens`); measure a
  real 4K screenshot's prompt_tokens.
- **The critique loop proof**: render something with the model's own code (Phase
  7 outputs work), Chrome-headless screenshot it, send it back, judge whether the
  critique names real content. Multi-image test with one intentionally broken
  page as the discriminator.
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

### Phase 10 — power
Sample watts under load (nvidia-smi / platform equivalent) → kWh per answer per
effort level. Cheap, delightful, expectation-setting.

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
