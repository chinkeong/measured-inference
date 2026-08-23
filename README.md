# measured-inference

**A field-guide generator for local LLMs.** Clone this repo on any machine, point
a coding agent at a new model, and hours-to-days later you have a published,
single-page field guide in which every recommended setting carries the
measurement that justifies it.

Born from a real campaign: [Qwen3.8-27B on an RTX 3090](templates/example-report.html)
— a night of sweeps that found an offload bug worth 35% of decode speed, debunked
a headline benchmark, crowned an unexpected quant, measured context ceilings,
reasoning-effort economics, vision loops, and coding-agent compatibility. This
repo packages that methodology so it can be replayed against any model on any
machine.

## Use
```
git clone https://github.com/chinkeong/measured-inference.git
cd measured-inference
# start your coding agent (Claude Code, etc.), then:
#   "I need a report for https://huggingface.co/<repo>/<model>.gguf"
# the field-guide skill interviews you once, then runs autonomously.
```

Everything heavy is self-contained and gitignored: `scripts/setup.*` downloads a
llama.cpp build into `bin/`, models download into `models/`, and the accuracy
harness's two Python dependencies go into a repo-local `.venv/` — nothing
installs globally, because the machine may be borrowed.

## The pledge
Every number in a report is **measured on that machine, cited to a live source,
or explicitly labeled as derived** — and no reader should ever measure less than
the report promised. The rules that enforce this are in
[`methodology/METHODOLOGY.md`](methodology/METHODOLOGY.md).

## Status
- v1: NVIDIA/Windows reference implementation (RTX 3090 proven end-to-end).
- Portable targets: DGX Spark (GB10/Ubuntu-ARM), Intel Arc dGPU (Vulkan),
  Intel Core Ultra iGPU. OpenVINO support planned.

## Map
| Path | What |
|---|---|
| `AGENTS.md` | agent entrypoint — the tier-0 router (invariants + routing table) |
| `skills/field-guide/SKILL.md` | the campaign map and the one-round interview |
| `skills/field-guide/stages/` | `stage-0.md`…`stage-7.md` — one procedure per stage, loaded one at a time |
| `methodology/` | the measurement law (`METHODOLOGY.md`) and how to apply it (`REASONING.md`) |
| `reference/` | `platform-notes.md`, `failure-library.md` — grepped by symptom, never read whole |
| `templates/` | report spec + complete worked example |
| `scripts/reference-3090/` | proven probe/sweep scripts |
| `scripts/bench/` | accuracy harness |
| `scripts/power/` | energy attribution toolkit |
| `results/<model>/` | campaign logs and finished reports |
