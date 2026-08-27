# The models queued after Qwen3.8-27B, and what the harness must run

Planning note, 2026-08-27. Five models are now in scope: the one measured, and
four the campaign expects to measure next. This file exists to pick the
benchmark set ONCE, from what those models' own cards report, rather than
discovering per model that nothing is comparable.

## Do they fit a 24 GB card?

| model | shape | smallest useful GGUF | fits 24 GB? |
|---|---|---|---|
| **Qwen3.8-27B** | dense 27B | UD-Q2_K_XL 9.8 GB · UD-IQ4_XS 14.25 GB | **yes** — measured |
| **Muse-Glimmer-30B** | dense 29.6B + 1.8B ViT | vendor ships a **K-Quant-17GB** | **yes** |
| **Gemma-4-31B-it** | dense 30.7B + 550M vision | ~17–18 GB at 4-bit | **yes** |
| **Nemotron-3.5-Lightning-30B-A3B** | MoE 30B total / 3B active, Mamba-2 + attention hybrid | ~17 GB at 4-bit; 92 quantised variants exist | **probably** — see risk |
| **Qwen3.8-Flash-Next** | MoE 125B total / 6B active, +51B n-gram embed | UD-IQ1_S ≈ 40 GB · UD-Q2_K_XL ≈ 64 GB | **no**, not comfortably |

**The three 30B-class models are the natural next cohort.** They sit where
Qwen3.8-27B sits, so every rig-level finding — the power cap binding, the
roofline shift under speculation, the quantisation ladder — transfers directly.

**Two architecture risks, which are about llama.cpp support and not about memory.**
Nemotron is a **Mamba-2 / attention hybrid MoE**; support for that combination is
newer than for a plain transformer and must be verified before planning a run.
Flash-Next uses **Gated DeltaNet** and **Qwen Sparse Attention**, both novel — for
that model, architecture support is a harder gate than the 40 GB file.

## What their own cards report — and where they overlap

This is the whole point. A benchmark is only worth adopting if several of these
models publish a figure for it, because that published figure is what validates
the harness.

| benchmark | Qwen 27B | Flash-Next | Muse-Glimmer | Gemma-4-31B | Nemotron-3.5 | coverage |
|---|---|---|---|---|---|---|
| **GPQA Diamond** | 89.2 | 91.7 | 83.5 | 84.3 | 75.44 | **5 of 5** |
| **IFBench** | 79.5 | 81.3 | 77.0 | — | 71.88 | **4 of 5** |
| **Terminal-Bench 2.1** | 73.0 | — | 51.7 | — | 24.58 | **3 of 5** |
| SWE-bench Pro | 61.7 | 62.5 | 51.2 | — | — | 3 of 5 |
| LiveCodeBench v6 | 90.3 | 91.9 | — | 80.0 | — | 3 of 5 |
| SWE-bench Verified | — | — | 76.0 | — | 51.56 | 2 of 5 |
| SciCode | — | — | 43.6 | — | 32.60 | 2 of 5 |
| HLE | 30.8 | 35.9 | — | — | 11.72 | 3 of 5 |
| AIME 2026 | — | — | 94.7 | 89.2 | — | 2 of 5 |
| MMLU Pro | — | — | — | 85.2 | 81.94 | 2 of 5 |
| **aider polyglot** | — | — | — | — | — | **0 of 5** |

**Aider polyglot appears on none of the five cards.** That is the clearest
argument yet for migrating: the benchmark this campaign currently runs is one
that none of the models it wants to measure reports.

## What this implies for the harness

**GPQA Diamond is the cheapest harness validation available, and it is universal.**
Every one of the five publishes it. It is 198 multiple-choice questions,
single-turn — no agent loop, no containers, no test execution, no retries — so it
is a fraction of the cost of an agentic arm. Running it on Qwen3.8-27B and
comparing against the published **89.2** would, for the first time, tell this
campaign whether its harness reproduces a known number. That gap has been open
since the campaign began.

It validates the *serving stack and settings*, not agentic coding ability. That
is exactly what needs validating: the suspicion is never that Exercism problems
are wrong, it is that the local serving configuration differs from the one that
produced published figures.

**Terminal-Bench 2.1 is the agentic candidate.** Three of five report it, a
figure exists for the current model (73.0), and the Quesma quantisation study
already used it — so there is an independent quantisation comparison to check
against. Its risk is statistical: **89 tasks against aider polyglot's 225**.
At the discordance rate measured here that widens the paired confidence interval
from ±6.7 to ±10.7 points. Terminal-Bench buys external comparability and costs
resolution, and that trade must be stated rather than discovered.

**A forward-looking note on the campaign's own headline finding.** Speculative
decoding is the largest lever measured anywhere in this work (2.2×), and it
turns out the vendors agree: Muse-Glimmer ships a **DFlash** drafter claiming
3.1× on an RTX 5090, and Nemotron ships **DSpark, DFlash and MTP** drafters.
Three of the next four models ship a draft head. That makes drafter quality a
cross-vendor axis worth measuring directly, and it means the roofline result —
that speculation moves the workload off the bandwidth roof and onto the power
limit — should be re-tested per model rather than assumed to transfer.

## Settings, so the condition line is right per model

| model | temperature | top_p | top_k | thinking |
|---|---|---|---|---|
| Qwen3.8-27B | 0.7 (instruct) / 1.0 (thinking) | 0.80 / 0.95 | 20 | on by default, xhigh |
| Muse-Glimmer-30B | 1.0 | 0.95 | 64 | not a thinking model; effort via system prompt |
| Gemma-4-31B-it | 1.0 | 0.95 | 64 | configurable via a `<|think|>` token |
| Nemotron-3.5 | 1.0 | 0.95 | — | `enable_thinking=True/False`, on by default |
| Flash-Next | 0.7 / 1.0 | 0.80 / 0.95 | 20 | on by default, xhigh |

Every one of these differs from the greedy `temperature 0` this campaign uses
for its speed work. Greedy is right for a *speed* band — it has a 0.77%
run-to-run coefficient of variation against the recommended sampler's 5.68% —
but a *quality* number taken at greedy is not comparable to a published one
taken at the vendor's settings. The two purposes need two configurations, and
each result must say which it used.
