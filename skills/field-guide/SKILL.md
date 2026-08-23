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
structure; `methodology/METHODOLOGY.md` is the law — read all three before Stage 0.

The prime directive, from the person you are working for:
**no reader may ever measure less than the report promised them.**

The campaign's shape, in one line (METHODOLOGY rule 25):
**cheap probes buy the map, the map locks the recipes, only locked recipes earn
expensive hours.**

## Stage 0 — the interview (the ONLY time you may ask questions)

Ask everything up front, in ONE round. After this, run autonomously to the end;
never block on the user. Confirm auto-detected facts rather than asking open
questions.

1. **Model**: the HF URL(s). Resolve the repo file listing (HF API
   `/api/models/<repo>/tree/main`) and propose which quants to measure (a Q4-class
   primary + challengers: same-size alternates, one smaller IQ-class, vendor
   variants) and whether an mmproj/vision projector exists. Confirm the set.
   **Prove access before the interview closes**: a gated or private repo fails
   at Stage-1 download time, when the no-questions rule has already locked you
   out of asking. Test with a range request on one chosen file
   (`curl -sI -r 0-1023 <resolve-url>` → expect 206/200, not 401/403; the
   listing API itself succeeds on gated repos, so listing is not proof). If it
   401s, ask for an HF token in this same round and confirm it works
   (`Authorization: Bearer <token>`) before proceeding.
2. **Machine**: auto-detect (GPU via nvidia-smi / lspci, VRAM, RAM speed+channels,
   CPU threads, OS, disk free) and present the detection for confirmation. RAM
   channels matter: single-stick machines halve every offload/iGPU estimate.
3. **Use cases**: text coding / vision-screenshot loops / coding agents / long
   context? This decides which optional Stage-6 work runs.
4. **Time budget**: overnight (~8 h) vs. multi-day. Present the concrete plan
   it buys and confirm that, not the hours. Stages 0–5 (the map and the recipe
   lock, ~4 h) run in every budget — they are what makes the expensive hours
   safe; the budget buys Stage 6:
   - **overnight** = primary + 1 challenger get the full treatment (n=200
     accuracy each, full PPL on those two); remaining surviving quants get
     load-and-speed probes only; effort quality runs at 2 runs × 3 levels on
     one file.
   - **multi-day** = every surviving quant gets the full treatment (n=200 per
     arm, full PPL on every file), plus the Stage-2 ceiling sweep per file and
     Stage-6 accuracy per effort level.
     Anything below overnight is a smoke test: say so in the report, and never
     publish a quant ranking from it.
5. **Philosophy**: quality-first (ship max effort where the window allows — the
   default) or latency-first. Also: does the model expose an effort/thinking knob
   (check the chat template) — if yes, Stage 4's appetite probes and Stage 6's
   effort arms run.
6. **Publish target**: results/<slug>/index.html always; plus a git remote / site
   directory if the user names one. **`<slug>` = the model repo name,
   lowercased, as a single path component** — no slashes, `-GGUF` suffix
   dropped: `huggingface.co/unsloth/SomeNew-32B-GGUF` → `somenew-32b`. Confirm
   it in this round and record it in `campaign.md`; after a crash, reuse that
   exact slug rather than deriving a second one.
7. **Coding agents** (feeds Stage 6): auto-detect installed agents (probe
   PATH for `opencode`, `aider`, `qwen`, `pi`, `dsh`, `claude`, …) and present
   the detected roster. Confirm which to test, and whether missing ones may be
   installed for the campaign (npm/pip, user-scope only — the machine may be
   borrowed). If the answer is "none", Stage 6's agent-attach matrix and its
   end-to-end agent pass are skipped and the report says so explicitly.

Record all answers in `results/<slug>/campaign.md` (the campaign log — append
decisions, findings, and timestamps to it throughout; it is your recovery point
after any restart).

## Standing rules (memorize before Stage 1)

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
- **Checkpoint commits** after every completed stage — the machine may be shared
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

## The stages

Run in order. Each stage ends with: results appended to `campaign.md`, raw logs in
`results/<slug>/data/`, and a checkpoint commit. Scripts in
`scripts/reference-3090/` are the proven implementations from the reference
campaign — **adapt paths/models into `results/<slug>/work/`, do not edit the
references**.

**The sequencing law — METHODOLOGY rule 25, read it before Stage 1.** Cheap
probes buy the map; the map locks the recipes; only locked recipes earn
expensive hours. Stages 1–4 are cheap and buy information (~4 h all together).
Stage 5 turns that information into locked recipes and spends no GPU at all.
Stage 6 is the only stage allowed to spend hours, and it spends them exclusively
on locked recipes. The reference campaign inverted this: it ran an xhigh effort
arm for 21 minutes and ~120 Wh inside a 65,536-token window, and only afterwards
measured that xhigh's thinking appetite is 61–76k tokens. The arm truncated; the
deliverable was zero. The probes that would have prevented it cost minutes.

**The over-measurement guard**: every planned run must name the recipe decision
or the reader-facing number that consumes its result. A run whose output nothing
consumes is cut, not "kept for completeness". The noise floor obeys the same
rule — replicate ONE config across arms to establish it, never every arm.

**Old numbering → stages.** A `campaign.md` written under the old phase numbers
is still resumable: find the phase its last entry names, read the stage that owns
that work now, continue there, and append a line recording the renumbering.

| Old phase | Where that work lives now |
|---|---|
| Phase 0 — interview | **Stage 0** (plus the power logger + cold idle baseline, moved up from Phase 1) |
| Phase 1 — acquire | **Stage 1** (acquire); its power-logger step → **Stage 0** |
| Phase 2 — foundation & sanity | **Stage 1** |
| Phase 3 — speed, speculation, acceptance | the floor probe → **Stage 1**; drafter sweeps, token regimes, acceptance → **Stage 3** |
| Phase 4 — memory, budgets, two ceilings | **Stage 2** |
| Phase 5 — depth | **Stage 3** (as the cooled depth ladder) |
| Phase 6 — quality (PPL, accuracy) | short PPL screen → **Stage 1** (pruning gate); full PPL ranking + accuracy suite → **Stage 6** |
| Phase 7 — effort | thinking-appetite measurement → **Stage 4**; effort arms, blind judging, per-level accuracy → **Stage 6** |
| Phase 8 — vision | projector VRAM pair → **Stage 2**; resolution map, critique loop, agent-attach matrix → **Stage 6** |
| Phase 9 — agents end-to-end | **Stage 6** |
| Phase 10 — power | logger + baselines → **Stage 0**; energy matrix + per-recipe energy → **Stage 6** |
| Phase 11 — the report | **Stage 7** |
| *(no old equivalent)* | **Stage 5 — RECIPE LOCK**: the gate the reference campaign did not have |

### Stage 0 — interview + instrumentation on
The interview is the section above: one round of questions, then autonomous to
the end. Stage 0 then closes with two nearly-free things that pay for themselves
across the whole campaign.

**Start the power logger now and leave it running** — this is METHODOLOGY rule
24's instrumentation, opened at campaign start. A 500 ms CSV log costs one
process and a few MB a day, and it retroactively converts every later stage into
power data: the drafter sweep, the ceiling sweep, the depth ladder, the rule-21
suite and the effort arms all become energy arms *for free* if the log was
already running when they ran. Rerunning them later for watts is hours you do not
need to spend.

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
than an efficient one. One file per stage is fine — record each filename and its
start time in `campaign.md`, and restart the logger after any reboot.

**Take the cold idle baseline before anything loads**: board idle, no server,
n≥15 samples, dated, tier-labeled (reference 2026-08-22: **33.2 W**). Take it
**cold** — a board still cooling from earlier work reads high (one reference
log's first 10 samples averaged 58.0 W against the 33.2 W cold reading) — or
state which it was. The loaded-idle flavor is taken in Stage 1, the first time a
server is up and idle (reference: **30.7–31.1 W** — a resident model costs
almost nothing until asked). Both go in `campaign.md` with date and tier label;
every idle-subtracted figure downstream depends on them.

### Stage 1 — STRUCTURE (~1 h, cheap probes only)
Nothing in this stage may cost an hour of GPU on its own. Its products: runtime
and files on disk, the KV arithmetic, a verified `-ngl`, one floor number per
candidate quant, and a candidate roster that has already been pruned.

**Acquire** (network, parallel with nothing). `scripts/setup.ps1|sh` fetches a
llama.cpp build into `bin/` for this platform. Download the chosen quants +
mmproj into `models/` (curl, resumable, verify byte sizes against the HF
listing). Download nothing you won't measure.

**Foundation & sanity**
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
- Take the **loaded-idle** power baseline the first time the server is up and
  idle (Stage 0 holds the cold, no-server one).

**One floor probe per candidate quant.** Baseline, no speculation, temp 0, short
code probe → the **floor** (reference: `probe-config.ps1`, called with `-ngl 99`;
POSIX seed: `scripts/probe-config.sh`). Cross-check each floor against rule 10's
arithmetic (GB/s ÷ file GB × 0.7, re-deriving the efficiency constant per
format). One probe per file, not a sweep — the sweeps are Stage 3's, and they
only run on files that survive the gate below.

**The early pruning gate — the cheapest decision of the campaign.** Before any
file earns expensive treatment, screen the roster on three cheap numbers:
1. `llama-bench -p 0 -n 128` (tg128) per file — or the floor probe above, if the
   build ships no `llama-bench`;
2. file size on disk (rule 10: bytes per token IS the decode budget);
3. a **short PPL screen** — the same small fixed set of wikitext-2-raw chunks
   for every file (4 × 8,192 tokens is enough), identical chunks across files
   (adapt `ppl-compare.ps1` with a chunk cap; it is resumable).

**Drop, right here, any file that is both slower AND worse on the screen.** It
cannot win on an axis a reader cares about, and carrying it further buys one
word: the reference campaign took UD-Q4_K_XL through the full treatment to
conclude "pointless". Record the drop in `campaign.md` with both numbers and the
words "screened out at the Stage-1 gate"; the report says it was screened out
and how — never that it was untested. A file that is slower but better, or
faster but worse, is a real trade-off and survives to Stage 2. The screen ranks
nothing publishable: PPL over four chunks is a screen, and the publishable
ranking is Stage 6's full run under rule 6.

### Stage 2 — MEMORY MAP (~1.5 h)
Product: **every candidate window becomes known arithmetic.** After this stage
you can state, without launching another server, what any ⟨file + drafter +
projector + desktop⟩ configuration costs at any window — which is exactly what
Stage 5 needs to size recipes on paper.

- Budget table from the Stage-1 KV arithmetic (context × KV-type × largest
  fitting quant).
- **The drafter on/off VRAM pair, measured first** — it moves every ceiling
  underneath it (reference: 1,008 MiB fixed + 5,120 B per window token +
  898 MiB more at n-max 10 vs 4; the reference guide's "no VRAM cost" was a
  published error a blind run caught).
- **Ceiling sweep per surviving file, with deep-fill probes** (reference:
  `ctx-limit-sweep.ps1`, `iq4-ctx-sweep.ps1`): step `-c` upward with short
  probes + VRAM readings. Report BOTH ceilings: fully resident (dedicated VRAM
  fills) and shallow-safe (probes stay fast on overcommitted windows), plus the
  collapse point. Label per file, per mmproj-on/off, AND per drafter-on/off — a
  ceiling belongs to a configuration, not a file. **No window is labeled
  resident/safe without at least one deep-fill probe near its top** — a shallow
  probe on an overcommitted window reads fast right up until deep pages are
  touched (measured collapse: 8.0 t/s at 91k fill).
- **The projector pair**: the same window with mmproj loaded and not, so
  vision's memory bill is a measured constant instead of a surprise (reference
  model: projector ≈ 0.9 GiB ≈ 27k tokens of q8 window — recompute per model).
- **Desktop slack**, stated using this model's computed KV cost from Stage 1,
  not a remembered constant (reference model: each 32k of q8 window ≈ 1 GiB).
  Ship desktop-safe defaults; fence bare-desktop configs loudly (a browser UI
  once pushed the Windows compositor to 3.6 GiB and halved a "fitting" config).
- **The two-constant model — this stage's real deliverable.** From the pairs
  above, fit per configuration:
  `VRAM(window) ≈ fixed bytes + bytes-per-window-token × window tokens`
  (weights + drafter + projector + desktop overhead are the fixed term; KV is
  the per-token term). Two measured points give both constants, a third checks
  them, and from then on every candidate window is arithmetic rather than a
  launch. Verify the fit with one deep-fill probe at the top of each window a
  recipe will actually ship — arithmetic sizes the window, a probe confirms it.

### Stage 3 — SPEED SURFACES (~1 h)
Product: the speed surface every recipe will quote — floor, real-work band,
ceiling — each labeled with its token regime and its depth. Matched pairs only:
a drafter sweep transfers across quants (rule 11: same optimum, acceptance
within 1.6 pts), but it does NOT transfer across token regimes.

- **Sweep in BOTH token regimes.** Run the matched drafter/MTP sweep twice —
  thinking on and thinking off — and keep both surfaces. The reference campaign
  discovered the 1.69× regime split late, after speeds had been published
  without it; the split belongs here, before any recipe quotes a band.
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
- **Report mean draft length beside every acceptance rate** (rule 11): the p-min
  gate truncates the draft tree on uncertain tokens, so acceptance can sit
  identical while throughput differs 1.69× (reasoning stream: accept 0.895,
  draft len 2.99, 36.6 t/s; answer stream: accept 0.907, draft len 4.31,
  62.0 t/s — same server, same 91k prompt, same flags). Acceptance explains the
  mechanism; mean draft length predicts the throughput.
- Record floor / real-work band / ceiling per regime for the report's spec strip
  and for the Stage-5 recipe cards — every band labeled with the regime, depth
  and desktop state that produced it.

**The cooled depth ladder** (reference: `nuance-suite.ps1` part 1,
`deep-decode-probe.ps1`). Fixed probes at increasing prompt depths; report decode
and prefill vs depth with acceptance shown steady (or not). Use server timings,
never wall-clock-including-prefill. Declare the series' parity (drafter on/off,
projector on/off, token regime) — two series with mismatched parity are different
experiments, not one curve. **Run it cooled, to rule 12's clock-ramp protocol**:
a probe fired right after a long prefill reads up to 45% low because the board's
clocks are still ramping (prefill itself may only reach ~65% of settled clocks) —
discard the first post-prefill probe at every rung and time only settled probes,
or the ladder measures thermodynamics instead of depth. Run the ladder on the
windows Stage 2 proved safe; a rung above a proven ceiling measures spill.

### Stage 4 — APPETITE PROBES (~30 min, if the model has an effort/thinking knob)
Two cheap probes per effort level. Product: **the thinking-appetite distribution
per level** — the number Stage 5 sizes every window and every benchmark cap
against. This is the stage whose absence cost the reference campaign a 21-minute,
~120 Wh xhigh run that truncated to nothing (rule 25).

- **Cheap means cheap**: the shortest run that produces a thinking-token count.
  Use the reference task (`templates/effort-task-example.md`) or any prompt that
  reliably makes the model think, run at each level, at a cap and a window that
  cannot truncate — the largest window Stage 2 proved safe, with the cap set to
  the window minus prompt and a generous answer allowance. These probes are not
  quality arms: do not judge them, do not score them, do not publish them as
  effort quality. That is Stage 6's job, on locked recipes.
- **Record per level**: thinking tokens, answer tokens, wall, and whether the
  run finished. With n=2 you have a range, not a distribution — plan against the
  observed maximum plus margin, and say in `campaign.md` and the report that the
  tail is estimated from two samples (reference: xhigh 61–76k thinking tokens).
- **Spot-read the thinking traces for repetition loops before trusting the
  counts** (rule 20). Greedy decoding makes a loop deterministic, and a looping
  trace inflates appetite — which would then inflate every window in Stage 5.
- **A level that truncates even at the largest safe window** has its appetite
  recorded as "≥ window" and becomes a *not offered* candidate in Stage 5. It is
  never run as a measured-truncated arm.

### Stage 5 — RECIPE LOCK (no GPU time — the gate)
Stage 5 spends nothing and decides everything. Write the recipe cards into
`campaign.md` under a dated **RECIPE LOCK** heading. Each card carries:

**file · window (`-c`) · flags** (spec type / n-max / p-min / KV dtype /
`-ngl 99` / parallel / projector on-off) **· effort ceiling** (which levels this
recipe offers) **· expected speed band** (floor · real-work · ceiling from Stage
3, at this recipe's regime and depth) **· VRAM at the top of the window** (Stage
2's two-constant arithmetic, with the deep-fill probe that confirmed it) **·
desktop-safe or bare-desktop**.

- **The offer rule**: a recipe offers an effort level only if
  `window ≥ appetite upper tail + prompt tokens + answer allowance + margin`.
  Levels no recipe can hold are listed **"not offered"**, with their measured
  appetite beside them — never measured, never truncated, never quietly dropped.
- **Caps are set here, from the appetite distribution** — rule 7 applied BEFORE
  spending instead of after truncating. Every benchmark and effort arm in Stage 6
  inherits its cap from this line, and the serving `-c` must exceed the suite's
  longest prompt + that cap (rule 21). Truncation in Stage 6 is then impossible
  by construction; if an arm truncates anyway, the lock was wrong — fix the lock,
  raise the cap, rerun that arm only.
- **Name the consumer of every Stage-6 run** as you plan it (the
  over-measurement guard): the recipe decision or the reader-facing number that
  eats the result. Runs without a consumer are cut here, while cutting is free.

> **HARD RULE — the line no expensive run may cross.** No effort arm, benchmark
> suite, energy matrix, full PPL run beyond the Stage-1 screen, vision loop or
> agent matrix may start before the RECIPE LOCK is written. Stage 6 runs on
> locked recipes only. If a Stage-6 result invalidates a card (a window that
> will not hold, a band that does not reproduce), stop, fix the card, and note
> the correction in `campaign.md` — do not carry an unlocked configuration
> forward on the grounds that it is already running.

### Stage 6 — CHARACTERIZATION (~6–10 h, locked recipes only)
The only stage allowed to spend hours. Every arm below runs on a Stage-5 recipe,
at a Stage-5 cap, inside a Stage-5 window. Checkpoint-commit each sub-stage.

#### Stage 6a — quality: rank with perplexity, smoke-test with accuracy
- **Perplexity ranks quants — the survivors of the Stage-1 gate only**
  (METHODOLOGY rule 6 — the wikitext-2-raw test split, 294,912 token positions
  = 36 × 8,192-token chunks; reference: `ppl-compare.ps1`, resumable, one model
  per invocation if the platform kills long tasks). The report's ranking table
  lists the screened-out files too, marked "screened out at the Stage-1 gate"
  with their screen numbers, so no reader mistakes a pruned file for an untested
  one. Verify the KV-quant claim while here (fp16 vs q8_0 cache). **q4_0
  K-cache is not a free next step** — never recommend it without its own
  measured PPL check; absent the check, say "unverified here".
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

#### Stage 6b — effort (if the model has a thinking/effort knob)
Runs at each level's best-fit locked recipe, at the Stage-5 cap. A level Stage 5
listed "not offered" is not run here — it is reported as not offered, with its
measured appetite.

References: `sweep-efforts.ps1` (pass 1: one run per level, saves thinking +
answer), `sweep-pass2.ps1` (pass 2 at fresh sampling → the second independent
sample per level), `sweep-tune.ps1` (finds the largest fast context first, then
sweeps there — Stage 2's map now answers that question without the search),
`extract-html.ps1` (pulls the HTML answer out of each sweep output),
`effort-gsm8k.ps1` + `xhigh-16k.ps1` (accuracy per level, and the rerun that
removes a truncation artifact — the artifact Stage 5 exists to prevent).

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

#### Stage 6c — vision (if an mmproj exists)
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

#### Per-agent headless invocations (reference campaign, verbatim)
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

#### Stage 6d — agents end-to-end
Verify each coding agent confirmed in interview item 7 against the served model
with a one-shot request (matrix above, text-only) using exactly the configs the
report will print — served from a locked recipe, so what the reader copies is
what was tested. Fix and document, don't paper over (the reference campaign
found a missing `--alias` and a missing routing block this way).

#### Stage 6e — energy (the logger has been running since Stage 0)
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
Drop the first post-idle request from every arm and say so. Reference
integrator to adapt: `results/qwen38-27b-blind/work/power-integrate.py` —
**use the Python one**; the PowerShell version tripped over 5.1's
`TryParseExact` overload resolution.

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

### Stage 7 — PUBLISH + review gates
Build `results/<slug>/index.html` per `templates/REPORT-SPEC.md`, using
`templates/example-report.html` as the structural exemplar. The Stage-5 recipe
cards are the report's front matter, and REPORT-SPEC's two-voice writing law
governs every section. Then run THREE review passes with fresh subagents before
calling it done: numeric consistency (against the campaign log's canonical
numbers), structural (TOC/anchors/tags), and reader-experience (can a first-time
reader reach a confident config decision without contradictions?). Apply
must-fixes; commit; publish per the interview. Checkpoint commits have been
running since Stage 1; this is the last of them.

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
