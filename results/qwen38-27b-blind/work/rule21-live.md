# Rule-21 effort sweep — Qwen3.8-27B UD-IQ4_XS, RTX 3090 (first LIVE run)

Everything before this run was validated against a stub. This is the first run
against the real model, and it found **three scorer bugs that a stub cannot
expose**, because each one needs a real model's formatting habits to trigger.

- **Date**: 2026-08-23, GAMINGPC (RTX 3090 24 GB, driver 596.36, Windows 11)
- **Model**: `C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-IQ4_XS.gguf`
- **Engine**: `E:\AI\llama.cpp\llama-server.exe`, version 0.1.2-dev (build 10502, commit 0adcc3bb5)
- **Suite**: `scripts/bench/suites/rule21-n25.json`, hash **`1cdf54f8eb9d3f8f`**, 175 prompts
- **Protocol**: rule 21 — n=25/benchmark, greedy (temp 0 / top-k 1), seed 42,
  max_tokens 16384, all seven benchmarks, `-c 32768` auto-sized
- **Server args per arm**: `-ctk q8_0 -ctv q8_0 --chat-template-kwargs {"reasoning_effort":"<low|medium|xhigh>"}`
  plus bench.py's defaults (`-ngl 99 --parallel 1 --jinja`). No speculative
  decoding: MTP is a pure speed knob and this run wanted the scores clean, so
  the tok/s column below is the unaccelerated baseline (~42 t/s).
- **Judge**: none. ALPACA and MT-Bench ran **unscored with transcripts kept**,
  by design — a model must never judge its own outputs. The composite Mean is
  therefore over **5 scored sets**, and is labeled that way everywhere.

## Score table

Rendered: `data/rule21/rule21-effort-sweep.png` (via `render_table.py`).

| Benchmark | Scorer | low | medium | xhigh |
|---|---|---|---|---|
| GSM8K | exact match | 100% | 100% | 100% |
| MATH-500 | exact match | 92% (1 trunc) | 100% | 92% (2 trunc) |
| HumanEval | execution pass@1 | 100% | 96% (1 trunc) | 84% (4 trunc) |
| MBPP | execution pass@1 | 92% | 84% (1 trunc) | 88% (2 trunc) |
| ALPACA | judge 1-10 | **unscored — no independent judge** | unscored | unscored |
| MeetingBank | ROUGE-L F1 | 22.6 | 22.4 | 22.3 |
| MT-Bench | judge 1-10 | **unscored — no independent judge** | unscored | unscored |
| **Mean (composite index over the 5 scored sets)** | — | **81.3** | **80.5** | **77.3** |

| Per-arm | low | medium | xhigh |
|---|---|---|---|
| Wall time | **1.00 h** | **1.47 h** | **2.70 h** |
| Truncated at the 16,384 cap (scored sets) | 1 | 2 | 8 |
| Truncated including unscored sets | 1 | 2 | 9 (ALPACA +1) |
| Mean output tokens (all 7 sets) | 830 | 1228 | 2217 |
| Decode tok/s (mean) | 42.2 | 42.0 | 41.9 |

**Read this table together with the raised-cap re-run below — on its own it is
misleading.** The Mean falls as effort rises only because every truncated
generation scores 0 by rule 7 and xhigh truncates 8× more often than low. Once
the cap is raised the three arms are indistinguishable (82.1 / 80.5 / 81.3).

The honest one-line summary of the sweep: **on this suite, effort buys wall
clock, not measurable quality** — 1.00 h → 1.47 h → 2.70 h and 830 → 1228 →
2217 mean output tokens, for composite Means that sit inside each other's noise
at n=25.

### Interpretation guardrails

- A single N=25 cell is a **smoke test** (±~16 pts). MBPP 92 / 84 / 88 is two
  samples of movement — not a ranking.
- The Mean aggregates ~125 scored samples per arm and is the interpretable
  number, but it is **a composite index, not an accuracy**, and it excludes the
  two judge-gated sets. It is comparable only with other runs whose scored set
  *and* suite hash match.
- MeetingBank's ~22 is a property of the metric pairing, not a failure: the
  model writes the summary the prompt asks for (measured over all 75
  MeetingBank generations: 79–129 words, mean 105, against a requested 60–120),
  while the reference is a ~40-word resolution title, so ROUGE-L F1 is
  structurally capped. It is
  flat across arms (22.6 / 22.4 / 22.3), so it contributes no signal here.

## Rule 7 — truncation at the cap, and the raised-cap re-run

Counts at the 16,384 cap are in the table above. The exact inventory:

| Arm | Truncated prompts (index within the dataset) |
|---|---|
| low | MATH-500 [20] |
| medium | HumanEval [6], MBPP [18] |
| xhigh | MATH-500 [3] [20], HumanEval [5] [14] [21] [24], MBPP [8] [12], ALPACA [21] |

**11 of the 12 came back with empty `content`** — the run away happens *inside*
the reasoning block, so the model never emits `</think>` and never reaches an
answer at all. (The exception is medium MBPP [18], which finished thinking and
was cut off mid-answer.) MATH-500 [20] is the one prompt that truncates at both
low and xhigh.

Re-run of **only the affected arm/datasets**, at `--max-tokens 32768` with
`-c 65536` (auto-sized; ≥ the required 49,152). Measured VRAM at `-c 65536`:
**16.7 GB of 24 GB** — text-only IQ4_XS has ample room.

Scoping note: the re-run covers the datasets that actually truncated, not all
seven. Greedy decoding makes the untouched datasets byte-identical, and the
re-run verifies exactly that on the datasets it does cover (see the
determinism check below), so a full-arm re-run would have burned hours to
reproduce identical numbers.

After the re-run, **low and medium have zero truncations left**; xhigh still has
three — HumanEval [5], HumanEval [21] and MBPP [8] — which exceed 32,768 as
well and are true non-terminating reasoning loops rather than long-but-finite
solves.

### Raised-cap results (`--max-tokens 32768`, `-c 65536`)

Rendered: `data/rule21/rule21-effort-sweep-cap32k.png`.

| Arm | Dataset | at 16,384 | at 32,768 |
|---|---|---|---|
| low | MATH-500 | 92% (1 trunc) | **96%** (0 trunc) |
| medium | HumanEval | 96% (1 trunc) | 96% (0 trunc) |
| medium | MBPP | 84% (1 trunc) | 84% (0 trunc) |
| xhigh | MATH-500 | 92% (2 trunc) | **100%** (0 trunc) |
| xhigh | HumanEval | 84% (4 trunc) | **92%** (2 trunc) |
| xhigh | MBPP | 88% (2 trunc) | **92%** (1 trunc) |

| Composite Mean (5 scored sets) | low | medium | xhigh |
|---|---|---|---|
| at the 16,384 cap | 81.3 | 80.5 | **77.3** |
| at the 32,768 cap | **82.1** | **80.5** | **81.3** |
| truncations remaining | 0 | 0 | 3 |
| re-run wall time | 0.38 h | 0.53 h | 2.40 h |

**This overturns the headline.** At the 16,384 cap the sweep looks like quality
*falling* with effort (81.3 → 80.5 → 77.3). With the cap raised, all three arms
land within 1.6 points (82.1 / 80.5 / 81.3) — indistinguishable at n=25, where a
single cell carries ±~16 pts. The apparent xhigh penalty was the token cap, not
the model.

Individual prompts make it concrete: MATH-500 [3] at xhigh needed **18,273
tokens and was correct**; HumanEval [24] needed **17,025 tokens and was
correct**. Both scored 0 at the 16,384 cap. Not every case is a long solve,
though — **3 prompts at xhigh still run past 32,768** (2 HumanEval, 1 MBPP),
which is a genuine runaway inside the reasoning block, not a length shortfall.

### Determinism check (what licenses the dataset-scoped re-run)

Every prompt that did **not** hit the old cap was compared byte-for-byte between
the 16,384 run and the 32,768 re-run (`work/rule21-determinism.py`):

| Arm | Non-truncated prompts reproduced identically |
|---|---|
| low | 24/24 |
| medium | 48/48 |
| xhigh | 67/67 |
| **total** | **139/139, zero drift** |

Raising `--max-tokens` and doubling `-c` changed nothing about any generation
that had room to finish. That is the evidence that re-running only the
truncating datasets loses no information relative to a full-arm re-run.

## Harness bugs found and fixed

All three scorer bugs share a shape: **the scorer compared presentation, not
value.** A stub emits canonical strings, so none of them could surface before a
real model formatted its own answers. Every fix is symmetric — it is applied to
the prediction *and* the reference — so it can only make one value written two
ways compare equal; it can never make two different values match. All were
verified with explicit must-match / must-stay-wrong case lists, and
`selftest.py` stayed at **78 passed, 0 failed** after each.

### 1. `_norm_answer` rejected correct MATH-500 answers (datasets_io.py)

The big one: **MATH-500 at low effort scored 60.0 when the model had actually
earned 92.0.** 8 of the 25 answers were correct and marked wrong:

| Model wrote | Reference | Why it failed |
|---|---|---|
| `145`, `120`, `75` | `145^\circ`, `120^\circ`, `75^\circ` | degree unit only on the reference |
| `55°` | `55^\circ` | Unicode degree vs LaTeX |
| `\dfrac{16}{27}`, `\dfrac{7}{4}` | `\frac{16}{27}`, `\frac{7}{4}` | `\dfrac` vs `\frac` |
| `(6,\ 31,\ -1)` | `(6,31,-1)` | LaTeX thin space `\ ` |
| `\begin{pmatrix}\dfrac{16}{49}\\[6pt]…` | `\begin{pmatrix}16/49\\…` | `\\[6pt]` row spacing + `a/b` vs `\frac{a}{b}` |

Fix: normalize `\dfrac`/`\tfrac`→`\frac`, strip degree/percent/currency marks
and LaTeX spacing macros, collapse `\\[6pt]`-style row spacing, and canonicalize
integer `a/b` to `\frac{a}{b}` — on both sides.

### 2. GSM8K compared the whole answer line instead of the number (datasets_io.py)

Surfaced **only at xhigh**, which reasons in units: `#### 156 kg` (ref `156`)
and `#### 5 hours` (ref `5`) were both marked wrong. That alone was xhigh's
entire GSM8K deficit — **92.0 → 100.0** once fixed. `grade()` now takes the
number out of the `####` line, as the canonical GSM8K scorer does.

### 3. `_norm_answer` squeezed spaces but not newlines (datasets_io.py)

Surfaced **only at xhigh**, which lays its boxed matrix out over several lines.
`\boxed{\n\begin{pmatrix}\n\frac{16}{49}\\[2mm]\n…}` could not match a
single-line reference. Fix: collapse all whitespace, not just `" "`.

A self-inflicted variant of the same bug turned up while fixing #1: stripping
`"\ "` (thin space) blindly also eats the second backslash of a `\\ ` matrix
row break. The thin-space strip now skips row breaks (`(?<!\\)\\ `).

### 4. `--datasets` was silently ignored on `--suite` runs (bench.py)

Not a scoring bug, but it blocked the rule-7 re-run: a suite run always used
every dataset in the file, so there was no way to re-run just the datasets that
truncated. An explicit `--datasets` now narrows a suite run (the flag is
ignored, as before, when a preset filled it in, so `--rule21 --suite` is
unchanged). The suite file and its hash are untouched — the run JSON still
records the parent hash `1cdf54f8eb9d3f8f` and lists only the datasets that ran.

### Not bugs — checked and left alone

- **MBPP `volume_cone`**: the model's `(1/3)*math.pi*r**2*h` differs from the
  dataset's expected `314.15926535897927` in the last ULP. MBPP asserts exact
  float equality; that is the benchmark's own artifact and "runs the dataset's
  own `test_list`" is the documented scorer. Not touched.
- **MBPP `last_occurence_char`**: the model returned `s.rfind(char)` and even
  argued in its answer that the dataset's expected `10` is a typo for `9`. It
  still fails the unshown asserts (`None` vs `-1`). A genuine pass@1 failure.
- **`grade()` not calling `strip_think`**: harmless here — with `--jinja` and no
  `--reasoning-preserve`, llama-server puts reasoning in `reasoning_content` and
  `content` holds only the final answer. Verified across all 525 generations: no
  `<think>` tag ever appeared in `content`.

## Extraction verdict

**Extraction was never the problem — normalization was.**

- **Code (HumanEval + MBPP, 150 answers)**: every non-truncated answer came back
  in a single ```python fence and extracted cleanly. Zero unfenced fallbacks,
  zero "no code-like block" warnings except on truncated (empty) responses.
  HumanEval scored 100% at low with 25/25 programs assembling and executing.
- **GSM8K (75 answers)**: `####` present in every non-truncated answer; the only
  extraction complaints were the two unit-suffixed answers now handled by fix #2.
- **MATH-500 (75 answers)**: `\boxed{}` present in every non-truncated answer.
  Every remaining miss is a truncation (empty content) or a genuine wrong value.
- **Every remaining extraction warning across all three arms corresponds 1:1 to
  a truncated sample.**

Offline re-scoring from transcripts reproduces the run-time scores exactly on
every arm and every dataset (`re-score mismatches: none`), except where a fix
was applied — which is the audit trail for the fixes themselves.

## Consistency of the reported numbers

The MATH-500 fix landed after the `low` arm had already run, so **all three arms
were re-graded offline from their kept transcripts with the final scorer**
(`work/rule21-finalize.py`). Greedy decoding means the generations are
untouched; only the grading was redone, and it cost no GPU time. Changes:

- `low`: MATH-500 60.0 → 92.0
- `medium`: none (it ran with the fix already in)
- `xhigh`: GSM8K 92.0 → 100.0, MATH-500 88.0 → 92.0

The re-graded, effort-labeled JSONs (`arm-<effort>-regraded.json`) are what the
table and PNG are rendered from. The raw run JSONs bench.py wrote are kept
beside them, unmodified.

## Reporting caveat in render_table.py (not fixed)

`render_table.py` keys comparison columns on `model_label`, and all three arms
are the same GGUF — without intervention the table renders three identically
named columns. The finalizer relabels each arm's JSON copy by effort, which is
why the columns read LOW / MEDIUM / XHIGH. Related: the PNG caption is built
from `runs[0]` only, so it prints `"reasoning_effort":"low"` for the whole
table. The column headers carry the real effort; the caption's server-args
fragment applies to the first column only. Left alone as a cosmetic issue in a
frozen harness.

## Files

All under `E:\AI\measured-inference\results\qwen38-27b-blind\`:

- `data/rule21/rule21-effort-sweep.png` / `.md` — the rule-21 (16,384 cap) table
- `data/rule21/rule21-effort-sweep-cap32k.png` / `.md` — the raised-cap table
- `data/rule21/arm-<effort>-regraded.json` — re-graded, effort-labeled results
- `data/rule21/arm-<effort>-cap32k-merged.json` — the raised-cap arm
  (re-run datasets merged in, `max_tokens_by_dataset` records which cap
  produced each cell)
- `data/rule21/arm-<effort>-Qwen3_8-27B-UD-IQ4_XS_*.json` — bench.py's raw run JSONs
- `data/rule21/arm-<effort>-*_transcripts.json` — all 175 generations per arm,
  including the unscored ALPACA / MT-Bench answers for later blind judging
- `data/rule21/arm-<effort>-cap32k-*` — the rule-7 re-run's own JSON,
  transcripts, PNG, logs and wall time
- `data/rule21/arm-<effort>-inspect.txt` — per-arm extraction audit + offline re-score
- `data/rule21/arm-*.log` / `.err` — console logs
- `data/rule21/arm-*-llama-server.log` — the server log for that arm
- `data/rule21/arm-*-wall.json` — wall time per arm
- `work/rule21-arm.py` — arm launcher (builds argv in Python so the
  `--chat-template-kwargs` JSON never meets a PowerShell quoting rule)
- `work/rule21-inspect.py` — extraction audit + offline re-score
- `work/rule21-finalize.py` — re-grade an arm from transcripts, relabel by effort
- `work/rule21-determinism.py` — byte-comparison of base vs raised-cap re-run
- `work/rule21-merge-cap.py` — merge a rule-7 re-run into its arm
- `work/rule21-render.py` — comparison PNG + markdown table
- `work/rule21-n25-cap32768.json` — rule-7 raised-cap suite copy (same prompt hash)

**Total GPU time: 8.48 h** — arms 1.00 + 1.47 + 2.70 h, rule-7 re-runs
0.38 + 0.53 + 2.40 h. One job on the card at a time throughout; the server was
stopped after every run and the GPU returned to idle (~1 GB).

Harness files changed (in `E:\AI\measured-inference\scripts\bench\`):
`datasets_io.py` (fixes 1–3), `bench.py` (fix 4). Nothing else was touched; no
prompts were modified; no commits were made.
