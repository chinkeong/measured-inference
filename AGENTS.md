# measured-inference — agent entrypoint

You are a coding agent on a possibly-borrowed machine. This repo turns a new
local LLM into a published, fully-measured field guide, autonomously.

## What to do
1. The user will name a model (usually a HuggingFace GGUF URL) and ask for a
   report/field guide. Load `skills/field-guide/SKILL.md` and follow it exactly:
   one interview round, then autonomous execution through all phases.
2. The law is `methodology/METHODOLOGY.md`. The output contract is
   `templates/REPORT-SPEC.md` with `templates/example-report.html` as the
   complete worked example.
3. Proven script implementations live in `scripts/reference-3090/` (PowerShell,
   Windows/NVIDIA reference machine). Adapt copies into your campaign's
   `results/<slug>/work/`; never edit the references. The accuracy harness is
   `scripts/bench/` (Python; see its README).
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

## Layout
```
skills/field-guide/   the campaign skill (start here)
methodology/          the rules
templates/            report spec + the worked example report
scripts/reference-3090/  proven probes & sweeps from the reference campaign
scripts/bench/        accuracy harness (bench.py)
scripts/setup.*       self-contained llama.cpp bootstrap
bin/ models/          gitignored: runtimes and weights live here
results/<slug>/       campaign log, work dir, data, and the final index.html
```
