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

## Getting started

Four steps. The first is the only one that needs you rather than the agent.

### 1 — Give the machine a runtime

On an **NVIDIA box** the CUDA toolchain has to be installed first, and no agent can
`sudo` for you:

```bash
sudo apt-get install -y nvidia-cuda-toolkit cmake build-essential git \
                        python3-venv python-is-python3
./scripts/setup.sh --cuda        # builds llama.cpp with CUDA; ~4 min on an RTX 3090
```

Stock Ubuntu 24.04 ships neither of the last two. Without `python3-venv`,
`setup.sh` exits 6 at `python -m venv` and says so; without `python-is-python3`
there is no bare `python` on `PATH`, which the setup itself survives — it tries
`python3` first — and which breaks every `python …` line printed below.

Windows: `.\scripts\setup.ps1`. Apple Silicon and CPU-only: plain `./scripts/setup.sh`.

`setup.sh` **exits 3 rather than installing a Vulkan build on an NVIDIA box.** That is
deliberate: there is no official Linux CUDA binary, and a campaign measured on Vulkan is
not comparable to one measured on CUDA, so a silent fallback would quietly invalidate every
number. `MEASURED_INFERENCE_ALLOW_VULKAN=1` overrides it, and the backend then travels with
the results as one of their conditions.

### 2 — Check it is ready, before any GPU time

```bash
python scripts/lib/paths.py                   # what resolves, and what is missing
python scripts/verify/run-all.py              # every no-GPU check, cheapest first
python scripts/verify/probe-smoke-test.py     # just the one: every probe still starts
```

`paths.py` prints each candidate it tried and why it rejected it, so "not found" comes with
the fix attached. It never returns a default that merely happens to exist.

### 3 — Get the weights

There is **no downloader in this repo**. The agent fetches the quants you agree on during
the interview with resumable `curl` into `models/`. If the HuggingFace repo is **gated**,
say so in the interview and hand over a token *then* — a 401 discovered at download time
lands after the interview has closed, and rule 31 has by then made asking illegal.

### 4 — Tell the agent what you want

Start your coding agent in the repo (Claude Code, opencode, Pi) and paste a prompt from
**[PROMPTS.md](PROMPTS.md)** — 23 templates covering a single-model field guide, a quant
ladder, a multi-model shootout, benchmarks without sweeps, a hard stop on a rented machine,
a shift handover, and resuming after a crash.

The shortest path is [ask for the form pre-filled](PROMPTS.md#ask-for-the-form-pre-filled--the-shortest-path):
the agent resolves the model listing, detects the machine, derives the slug and finds your
installed coding agents, then hands you the Stage-0 answer sheet already filled in. You
correct three things it cannot know — what you will use the model for, how many hours it
gets, and quality-first or latency-first — paste it back, and the campaign runs to the end
without stopping to ask again (rule 31).

Every prompt in that file opens with `Read AGENTS.md, then skills/field-guide/SKILL.md.`
Keep that line: Claude Code loads `CLAUDE.md` on its own and opencode loads `AGENTS.md`, but
Pi loads neither.

### What it leaves behind

`results/<slug>/` — `index.html` (the field guide), `campaign.md` (the log, and the recovery
point after any crash), `campaign.json` and `machine.json` (what every later stage resolves
against), and `data/` (every measurement, including the per-probe ledger a sweep can resume
from).

Everything heavy is self-contained and gitignored: runtimes in `bin/`, weights in `models/`,
a repo-local `.venv/`. Nothing installs globally, because the machine may be borrowed.

## The pledge
Every number in a report is **measured on that machine, cited to a live source,
or explicitly labeled as derived** — and no reader should ever measure less than
the report promised. The rules that enforce this are in
[`methodology/METHODOLOGY.md`](methodology/METHODOLOGY.md).

## Status
- **Windows + NVIDIA** — the reference implementation, RTX 3090 proven end-to-end
  (the shipped worked example is a full campaign on one).
- **Linux + NVIDIA** — the runner, the resolver, the machine profile and the CUDA
  source build are proven on Ubuntu 24.04 against the same 3090. The perplexity
  ladder is **ported, not proven**: `scripts/quant-ladder/run-ladder.py` is a
  stdlib-only POSIX runner, so rule 6's quant ranking no longer needs a port,
  and no run of it on Linux is recorded anywhere in this repository — measured
  or cited. `run-ladder.ps1` remains the Windows path and the reference for
  behaviour, and the ranking the worked example publishes was measured on
  Windows.
- **Portable targets** — DGX Spark (GB10/Ubuntu-ARM), Intel Arc dGPU (Vulkan),
  Intel Core Ultra iGPU. OpenVINO support planned.

## Map
| Path | What |
|---|---|
| `AGENTS.md` | agent entrypoint — the tier-0 router (invariants + routing table) |
| `skills/field-guide/SKILL.md` | the campaign map and the one-round interview |
| `skills/field-guide/stages/` | `stage-0.md`…`stage-7.md` — one procedure per stage, loaded one at a time |
| `methodology/` | the measurement law (`METHODOLOGY.md`) and how to apply it (`REASONING.md`); `EXTERNAL-REVIEW.md` — what other people's published work does better; `NEXT-MODELS.md` — the models queued next and the benchmarks they share |
| `reference/` | `platform-notes.md`, `failure-library.md`, `ledger-notes.md` — grepped by symptom, never read whole |
| `templates/` | report spec + complete worked example |
| `PROMPTS.md` | the copy-paste prompt library, and the Stage-0 answer sheet |
| `methodology/VOICE.md` | the report's register as rules, so any writer can match it |
| `scripts/arms.py` + `scripts/arms/` | the sweep runner, and sweeps written as data — `results/ARM-PROVENANCE.md` says what each shipped arm may be quoted for |
| `scripts/ledger.py` | every campaign's measurements as one JSONL, plus the gate that refuses illegal comparisons |
| `scripts/lib/paths.py` | resolves the server, the weights and the card — never a bad default |
| `scripts/detect-machine.py` | writes `machine.json`; every field measured, derived, cited, or null with its reason |
| `scripts/bench/` | accuracy harness |
| `scripts/power/` | energy attribution toolkit |
| `scripts/verify/` | the no-GPU checks: smoke test, portability audit, instrument guard |
| `scripts/reference-3090/` | the original Windows probes, archived — read, never run |
| `results/<slug>/` | campaign logs, machine profile, measurements and the finished report |
| `docs/ARCHITECTURE.md` | how the whole thing works, for a newcomer reading rather than running it |
