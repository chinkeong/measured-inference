---
name: field-guide
description: >
  Run a full measurement campaign against a new local LLM and produce a published
  field-guide HTML report. Trigger when the user gives a HuggingFace model/GGUF URL
  and asks for "a report", "a field guide", "measure this model", or "sweep the
  hardware for best settings". Interviews once, then runs autonomously for hours
  to days: hardware sweep, speed/quality/context/effort/vision/agent measurements,
  every number condition-labeled, output like templates/example-report.html.
  This file is the campaign MAP: read it once, then load only stages/stage-N.md.
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

This file is the map, not the manual. It holds the interview (which runs exactly
once) and the stage table (which tells you which single file to open next). The
procedures live in `stages/` and are loaded one at a time.

## Stage 0 — the interview (the ONLY time you may ask questions)

Ask everything up front, in ONE round. After this, run autonomously to the end;
never block on the user. Confirm auto-detected facts rather than asking open
questions.

**Detect first, then hand back a filled sheet.** Do not ask the seven questions
one at a time and do not ask what you can find out. Resolve the HF listing, run
`python scripts/detect-machine.py --slug <slug> --json`, and probe `PATH` for
the coding agents; then print `PROMPTS.md`'s answer sheet with everything you
found ALREADY FILLED IN, and ask the user only to correct it. Four of the seven
are yours to fill: **Q1** the roster and whether an mmproj exists and whether the
repo is gated (prove that with the range request now, not at download time),
**Q2** the whole machine block, **Q6** the slug, which the naming rule derives
mechanically from the repo name, and **Q7** the detected agent roster. Three are
genuinely the user's and cannot be defaulted away: **Q3** what they will use the
model for, **Q4** the time budget, and **Q5** quality-first or latency-first.
Mark every line you filled so they can see what you assumed, and say plainly
that anything they leave takes the printed default. A user who edits three
fields and pastes it back has closed the interview.

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

**After this round closes, the campaign is autonomous to the end.** Mid-run
uncertainty about what the user wants resolves in this order: the interview
record in `campaign.md` → the measured default → **record the assumption and
proceed**. Never stop to ask. A campaign triggered on a Friday evening must hold
finished results on Monday morning; a wrong-but-recorded assumption costs
minutes to correct, a stalled GPU weekend cannot be re-run.

## Standing rules (campaign-wide — memorize before Stage 1)

- **Measured, cited, or labeled**: every number in the report is measured on this
  machine, cited to a source URL found via live search, or explicitly marked as
  derived arithmetic. No fourth category.
- **Conditions travel with numbers**: a decode t/s means nothing without content
  type, token regime, context depth, sampling temp, and desktop state.
- **Long jobs run detached, resumable, and checkpoint-committed**: detach because
  harness background tasks may be killed near 10 minutes; make every long script
  skip work whose output log already shows a final result; commit after every
  completed stage because the machine may be shared or crash.
- **The GPU is single-file**: one measurement job at a time; serialize via
  completion markers.
- **Verify your own probes**: a metric that divides tokens by wall time including
  prefill will lie to you at depth. Prefer the server's own `timings` fields
  (prompt_per_second / predicted_per_second / draft acceptance).

**Platform traps are not here.** PowerShell 5.1's quoting, function-output and
stderr behaviour, the POSIX equivalents for detaching / parse-checking / VRAM
diagnostics, WSL2 addressing, and the per-accelerator notes all live in
`reference/platform-notes.md` — grep it by symptom when the platform bites.
A probe or a number that looks wrong is `reference/failure-library.md`.

## The stage map

Run in order. Each stage ends with: results appended to `campaign.md`, raw logs
in `results/<slug>/data/`, and a checkpoint commit. Scripts in
`scripts/reference-3090/` are the proven implementations from the reference
campaign — **adapt paths/models into `results/<slug>/work/`, do not edit the
references**.

| Stage | Goal | Cost | Gate / output | Procedure |
|---|---|---|---|---|
| **0** | interview + instrumentation on | ~free | slug, roster and budget agreed; power logger running; cold idle baseline dated | interview above, then `stages/stage-0.md` |
| **1** | STRUCTURE — runtime, files, KV arithmetic, verified `-ngl`, one floor per quant | ~1 h | **the early pruning gate**: slower AND worse is dropped, recorded, published as screened out | `stages/stage-1.md` |
| **2** | MEMORY MAP — budget table, drafter pair, ceiling sweep, projector pair, desktop slack | ~1.5 h | **the two-constant model**: every candidate window becomes arithmetic, confirmed by a deep-fill probe | `stages/stage-2.md` |
| **3** | SPEED SURFACES — drafter sweep in both token regimes, acceptance demo, cooled depth ladder | ~1 h | floor · real-work band · ceiling, each labeled with regime, depth and desktop state | `stages/stage-3.md` |
| **4** | APPETITE PROBES — two cheap probes per effort level | ~30 min | the thinking-appetite distribution per level (skip only if there is no effort knob) | `stages/stage-4.md` |
| **5** | **RECIPE LOCK** — turn the map into recipe cards | **no GPU** | **the hard gate**: no expensive run may start above the dated RECIPE LOCK line | `stages/stage-5.md` |
| **6** | CHARACTERIZATION — 6a quality · 6b effort · 6c vision · 6d agents · 6e energy | ~6–10 h | every arm on a locked recipe, at a locked cap, inside a locked window | `stages/stage-6.md` |
| **7** | PUBLISH + review gates | ~1 h | four fresh-subagent passes (numeric, structural, reader-experience) applied, then ship | `stages/stage-7.md` |

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

## Old numbering → stages

A `campaign.md` written under the old phase numbers is still resumable: find the
phase its last entry names, read the stage that owns that work now, continue
there, and append a line recording the renumbering.

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

---

**Executing a stage? Load `stages/stage-N.md` and nothing else.**
