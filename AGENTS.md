# measured-inference — agent entrypoint

You are a coding agent on a possibly-borrowed machine. This repo turns a new
local LLM into a published, fully-measured field guide, autonomously.

## What to do
0. **First, check `results/` for an in-flight campaign** (see "Resuming a
   crashed campaign" below). Only start a fresh Phase 0 interview if there
   isn't one.
1. The user will name a model (usually a HuggingFace GGUF URL) and ask for a
   report/field guide. Load `skills/field-guide/SKILL.md` and follow it exactly:
   one interview round, then autonomous execution through all phases.
2. The law is `methodology/METHODOLOGY.md`. The output contract is
   `templates/REPORT-SPEC.md` with `templates/example-report.html` as the
   complete worked example.
3. Proven script implementations live in `scripts/reference-3090/` (PowerShell,
   Windows/NVIDIA reference machine). Adapt copies into your campaign's
   `results/<slug>/work/`; never edit the references. The accuracy harness is
   `scripts/bench/` (Python; see its README — install its two dependencies into
   a repo-local `.venv`, never globally). On POSIX, start from
   `scripts/probe-config.sh` (the bash adaptation seed) rather than translating
   PowerShell from scratch.
4. `scripts/setup.ps1` / `scripts/setup.sh` bootstrap a self-contained
   llama.cpp into `bin/` — nothing is installed globally; models download into
   `models/`. Both directories are gitignored: this repo clones in seconds.

## House rules
- Long jobs: detach + log + resumable; the GPU is single-file; checkpoint-commit
  every phase; keep `results/<slug>/campaign.md` current — it is the recovery
  point if your session dies.
- Never ask the user anything after the Phase-0 interview.
- Windows PowerShell 5.1 has traps (function output pollution, quoting,
  stderr-wrapping) — the skill lists them; parse-check scripts before detaching.

## Resuming a crashed campaign
Sessions die; campaigns do not have to. **Before starting anything, list
`results/*/campaign.md`.** If one exists and its last entry is not "Phase 11
complete / published", you are resuming, not starting — do NOT re-interview.

1. Read `results/<slug>/campaign.md` end-to-end: it holds the interview answers
   (model, machine, use cases, time budget, philosophy, publish target, agent
   roster), every finding so far, and the phase it died in.
2. Compare its record against `git log --oneline` — each completed phase left a
   checkpoint commit. The highest checkpointed phase is ground truth; anything
   `campaign.md` claims past that was in flight when the session died.
3. Re-run the current phase's script. Every long script is resumable: it skips
   work whose output log in `results/<slug>/data/` already shows a final result,
   so a re-run costs only the unfinished arms. Confirm the GPU is idle first
   (a detached llama-server may have outlived the session — kill it).
4. Append a dated "resumed after session loss" line to `campaign.md`, then
   continue the phase list from there.

## Layout
```
skills/field-guide/   the campaign skill (start here)
methodology/          the rules
templates/            report spec + the worked example report
scripts/reference-3090/  proven probes & sweeps from the reference campaign
scripts/bench/        accuracy harness (bench.py)
scripts/setup.*       self-contained llama.cpp bootstrap
scripts/probe-config.sh  POSIX/bash port of the canonical probe (adaptation seed)
bin/ models/          gitignored: runtimes and weights live here
results/<slug>/       campaign log, work dir, data, and the final index.html
```
`<slug>` = the model repo name, lowercased, as a **single path component** (no
slashes): `https://huggingface.co/unsloth/SomeNew-32B-GGUF` → `somenew-32b`.
Drop the `-GGUF`/`-gguf` suffix. Pick it once in Phase 0, write it into
`campaign.md`, and reuse it verbatim after any restart.
