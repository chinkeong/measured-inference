---
name: stage-6
description: Load when executing Stage 6 (CHARACTERIZATION, ~6-10 h, locked recipes only) — sub-stages 6a quality (PPL + accuracy), 6b effort with blind judging, 6c vision, 6d agents end-to-end, 6e energy. The only stage allowed to spend hours.
---

# Stage 6 — CHARACTERIZATION (~6–10 h, locked recipes only)
The only stage allowed to spend hours. Every arm below runs on a Stage-5 recipe,
at a Stage-5 cap, inside a Stage-5 window. Checkpoint-commit each sub-stage.

## Stage 6a — quality: rank with perplexity, smoke-test with accuracy
- **Perplexity ranks quants — the survivors of the Stage-1 gate only**
  (METHODOLOGY rule 6 — the wikitext-2-raw test split, 294,912 token positions
  = 36 × 8,192-token chunks). This is NOT an arm sweep: perplexity runs
  `llama-perplexity`, a different tool, which `scripts/arms.py` does not drive.
  The runner is `powershell -NoProfile -ExecutionPolicy Bypass -File
  scripts/quant-ladder/run-ladder.ps1 -Manifest <manifest>`, one rung per quant
  file on the model of `scripts/quant-ladder/ladder-manifest.json`; it is
  resumable (a rung whose RESULT or FAILED line is already in the ledger is
  skipped) and `-Once` does one rung per invocation if the platform kills long
  tasks. **That runner is Windows PowerShell and this repo ships no POSIX
  equivalent** — a Linux campaign drives `llama-perplexity` itself at the
  manifest's conditions (`-ngl 99 -c 8192 -fa on --load-mode mmap`, f16 KV, the
  md5-pinned corpus), and budgets that port before the hours. The report's
  ranking table lists the screened-out files too, marked "screened out at the
  Stage-1 gate" with their screen numbers, so no reader mistakes a pruned file
  for an untested one. Verify the KV-quant claim while here (fp16 vs q8_0
  cache). **q4_0 K-cache is not a free next step** — never recommend it without
  its own measured PPL check; absent the check, say "unverified here".
- **Size ladder (optional, when the use case asks "how small can this model
  go")**: `scripts/quant-ladder/` is the reusable runner — manifest-driven,
  streamed (test a rung only when its file is on disk AND byte-stable),
  anchor-gated (re-run one known quant first; abort on >0.5% drift), GPU-gated
  (never starts while another job holds the card). Protocol: PPL ranks the
  rungs, detector probes disqualify (repetition, format collapse, template
  sanity); include a right-hand rung that clearly fails; cross-model rungs use
  bits-per-byte + rule-21 scored benchmarks, never raw PPL (rule 6).
- **Spot-read long greedy transcripts for repetition loops** before trusting
  their tokens or timings — greedy makes a loop deterministic, and a looping
  transcript inflates t/s and token counts with garbage.
- **Accuracy smoke-tests** (scripts/bench/bench.py, `--greedy --score`): n=200 on
  a checkable dataset for the chosen quants. Statistics law: n≤25 detects only
  ~20-pt collapses; 1–3-pt quant gaps need thousands — never present small-n
  accuracy as a ranking.
- **The budget rule**: the cap comes from the Stage-5 lock, which set it from
  Stage 4's appetite distribution — high enough that the longest thinker cannot
  hit it. Report truncation counts anyway; if an arm truncates, the lock was
  wrong: RAISE the cap and rerun that arm only (greedy determinism) — NEVER
  filter to non-truncating questions (selection bias).

## Stage 6b — effort (if the model has a thinking/effort knob)
Runs at each level's best-fit locked recipe, at the Stage-5 cap. A level Stage 5
listed "not offered" is not run here — it is reported as not offered, with its
measured appetite.

Run: `python scripts/arms.py --arms scripts/arms/effort-sweep.json` — eleven
arms merging three of the originals: `effort-pass1-*` (one run per level,
thinking and answer saved separately), `effort-pass2-*` (the same levels at
fresh sampling → the second independent sample per level that blind judging
needs), and `tune-ctx-probe-*` (the largest-fast-context search — Stage 2's map
now answers that question without the search). Accuracy per level, and the
xhigh rerun that removes a truncation artifact — the artifact Stage 5 exists to
prevent — ride in the same file as `bench_arms`, which arms.py does not run:
`scripts/bench/bench.py --no-spawn` scores them against the launched server.
Pulling the HTML answer out of each sweep output has NO runner equivalent
(`extract-html.ps1`: post-processing, no GPU). **effort-sweep.json is
RECONSTRUCTED** — its flag sets were derived from `serve-menu-example.bat`, not
read off the launcher the originals called, so check them before publishing a
number from these arms. The Windows originals are archived in
`scripts/reference-3090/`.

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
- Accuracy per level via the **standard benchmark protocol** (METHODOLOGY rule
  21: SEED=42, N=25 per benchmark, 16,384 cap, the 7-benchmark suite, normalized
  Mean as the headline). Per-cell = smoke test; the Mean and categorical
  collapses are the claims. Escalate suspicious cells to n=200. **Each effort
  runs AT its best-fit locked recipe**; if Stage 4's appetite for a level exceeds
  rule 21's 16,384 cap, Stage 5 already raised the cap and the serving `-c`
  before this arm started — record both on the table.
- Publish the **window-sets-the-effort-ceiling table** straight from the map:
  Stage 4's measured appetite per level against each Stage-5 recipe's window,
  with the offered / not-offered verdict per cell. It is derived arithmetic over
  numbers you already have — no new GPU time.

## Stage 6c — vision (if an mmproj exists)
- Resolution→token map (`--image-min-tokens` / `--image-max-tokens`); measure a
  real 4K screenshot's prompt_tokens.
- **The critique loop proof**: render something with the model's own code (the
  Stage-6b effort outputs work), headless-screenshot it, send it back, judge
  whether the critique names real content. Multi-image test with one intentionally broken
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
- **Agent-attach matrix** (on the locked vision recipe): for every coding agent
  confirmed in interview item 7,
  test headless image attachment with a question only answerable by seeing the
  image; verdicts PASS / FAIL-honest / FAIL-hallucinated (flag hallucination
  loudly). Known traps: capability must be declared in OpenCode (`attachment` +
  `modalities`) and Qwen Code (`capabilities.vision`); DSH needs client-side
  maxTokens or long replies truncate. Use the invocation matrix below.

## Per-agent headless invocations (reference campaign, verbatim)
Configs are printed in full in the example report's coding-agents appendices —
apply those first (base URL `http://localhost:1234/v1`, the model id the server
reports). One-shot test commands as run on the reference machine; drop the image
argument for Stage 6d's text-only pass:

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

## Stage 6d — agents end-to-end
Verify each coding agent confirmed in interview item 7 against the served model
with a one-shot request (matrix above, text-only) using exactly the configs the
report will print — served from a locked recipe, so what the reader copies is
what was tested. Fix and document, don't paper over (the reference campaign
found a missing `--alias` and a missing routing block this way).

## Stage 6e — energy (the logger has been running since Stage 0)
Executes **METHODOLOGY rule 24** — read it before this sub-stage; it defines
every metric and every label below. Deliverables: the per-recipe energy block for
REPORT-SPEC §3 (the recipes chapter), the per-effort split for §9 (effort and
energy), and the **per-axis J/token matrix**, which is what turns energy from
trivia into an argument.

**Step 0 was Stage 0**: the 500 ms logger started at campaign start and the cold
no-server idle baseline was taken before the first load. If the logger was NOT
running for a stage, that stage's rows are "not measured" — do not re-run hours
of work for watts, and do not estimate them.

**Step 1 — baselines, dated, both flavors.** Cold, no-server idle from Stage 0
(reference 2026-08-22: **33.2 W**) and loaded-idle from Stage 1, taken with the
server up and idle (reference: **30.7–31.1 W** — a resident model costs almost
nothing until asked). Both carry date and tier label in `campaign.md`; every
idle-subtracted figure downstream depends on them. If either was taken on a board
still cooling from earlier work it reads high (one reference log's first 10
samples averaged 58.0 W against the 33.2 W cold reading) — re-take it cold, or
state which it was.

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
Drop the first post-idle request from every arm and say so — that is
`attribute-power.py --drop-first`. The tooling is `scripts/power/`, documented
in its README: `capture-request.ps1` stamps `t_start` before the POST and
appends the request-event JSONL carrying `prompt_ms` / `predicted_ms` — the
join point — and `python scripts/power/attribute-power.py --power <power.csv>
--events <events.jsonl> --idle-w <Step 1 loaded idle> --drop-first --json
<out.json>` integrates the windows and emits the metrics (`--selftest` checks
its arithmetic with no GPU). Any JSONL carrying `t_start_iso`, `prompt_ms`,
`predicted_ms`, `prompt_n`, `predicted_n` and `label` works, so a harness
already recording those needs no PowerShell — and `scripts/arms.py`'s
per-probe ledger carries all six, verified on Linux 2026-08-29. Pass
`--events results/<slug>/data/arms/<stem>.jsonl` and every arm sweep is
already an energy arm; only the power CSV still needs a sampler. The integrator
is Python because the PowerShell one tripped over 5.1's `TryParseExact` overload
resolution.

**Step 3 — the per-axis J/token matrix** (rule 24's axis clause; this is the
sub-stage's real product). One row per arm, columns: mean W · J/token decode ·
J/prompt-token · tokens/kWh · EDP · verdict. Axes, each measured or carrying an
explicit "not measured" row: **quant** (each candidate file), **drafter**
(`--spec-type` off vs each tuned config — expect t/s up at flat W, so J/token
down; quantify), **KV dtype** (f16 vs q8_0), **`--parallel`** (1 vs 2,
aggregate — batching amortizes a fixed draw), **depth** (reuse Stage 3's depth
ladder: t/s falls; does W fall with it?), **effort level** (Stage 6b), and
**token regime** (thinking vs answer — same server, different J/token). If the
logger from Stage 0 was running during those stages, most of this matrix is a
query over CSV you already have.

**Step 4 — the power cap.** `nvidia-smi -pl <W>` (3090 stock 350 W; Linux may
need `-pm 1` first) is the one knob that directly buys efficiency — sweep it
(e.g. 350 / 300 / 250 / 200 W) into the same matrix. It needs an elevated
shell: if the campaign cannot elevate, do **not** estimate — print the command
and the stock cap in the report and mark it "unmeasured on this machine
(requires administrator)".

**Step 5 — per-recipe energy** for REPORT-SPEC §3: one identical real
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
  machine, **mark the energy work unmeasured** rather than estimating from TDP.
- **Wall tier**: if a PDU or plug meter exists, log it too and report both
  tiers — that is the only way to state PSU + system overhead as measured.
  Absent one, the report says the overhead is excluded and unmeasured.
