# What other people's work does better than ours

A campaign that only reads its own output drifts. This file records other
published measurements of the same model, what they do BETTER than this
campaign, and what was changed as a result. It is not a list of their mistakes;
the point is the opposite direction.

---

## Quesma, "Qwen3.8-27B quantizations benchmarked" (August 2026)

<https://quesma.com/blog/qwen38-27b-quantizations-benchmarked/>

Tested BF16, Q8_0, Q4_K_M, UD-Q2_K_XL, UD-IQ1_M and UD-IQ1_S on GPQA Diamond,
IFBench and Terminal-Bench 2.1, across L40S / H100 / H200, with Wilson 95%
intervals and three reasoning-effort levels.

### 1. They have a true full-precision reference. We do not.

Their ladder is measured against **BF16**, so they can state absolute quality
loss: BF16 ~94% on GPQA Diamond, Q4_K_M ~93%, UD-Q2_K_XL ~91%. This campaign's
KL ladder is referenced to **UD-IQ4_XS**, which is itself a lossy 4-bit file,
because 55 GB of BF16 does not fit a 24 GB card. Every divergence number this
campaign publishes is therefore *relative to a quantised baseline*, and it
cannot say how much was already lost before the ladder starts.

**This is the single biggest methodological weakness in the campaign**, and it
was under-stated: the limitation appears in the fine print rather than beside
the numbers.

**What was first proposed here, and why it was withdrawn.** An earlier version
of this file queued a Q8_0 re-anchor: fetch the 29 GB file and re-base the
ladder on it, since Q8_0 is near-lossless against BF16. On measuring the
machine rather than estimating it, that is **not doable here and is dropped**.
BF16 at 55 GB is plainly impossible. Q8_0 at 29 GB does not fit 24 GB of VRAM
either: it would run with roughly 7 GB of weights resident in system RAM and
computed on the CPU, on a machine with **31.8 GB of RAM in total**, of which
8.8 GB was free with one benchmark running. A full 200-chunk KL pass under that
split is hours of a loaded, noisy machine — which this campaign's own
quiet-machine rule forbids while any other measurement is in flight, and which
would perturb whatever else is running. Recorded as **out of scope for this
hardware** rather than attempted and reported badly.

**What was done instead, for free.** `scripts/quant-ladder/anchor-crosscheck.py`
uses THEIR expensive BF16 measurement to bound ours. One file appears in both
studies under the same metric — UD-IQ1_S, top-1 token agreement. Checking that
the metrics really match came first: our column is llama-perplexity's "Same top
p" output line, whose name collides with nucleus sampling and is unrelated to
it, and which reports how often the quantised model's most likely next token
matches the reference's. That is top-1 agreement, the same thing Quesma plots.

    UD-IQ1_S vs our UD-IQ4_XS anchor    73.07%   (measured here, 200 chunks)
    UD-IQ1_S vs BF16                    ~72%     (Quesma, read from a chart)

    triangle inequality on token disagreement:
    => our anchor differs from BF16 on AT LEAST 1.1% of tokens

That is a **lower** bound, and the script says so plainly: it converts
"unknown" into "at least this much", and it does **not** prove the anchor is
close to full precision. Their figure is chart-read and approximate, so the
bound inherits that imprecision.

The same script reports the ladder's shape, also free: the cost per bit removed
rises from **0.058 KLD/bpw** at the top of the ladder to **0.737** at the
bottom, a factor of **12.7**. The curve is convex, so the flattest region is
the one just above the anchor — consistent with the anchor sitting near the
converged end, but an extrapolation past the last measured point and not
evidence of its absolute quality.

Until a full-precision anchor is affordable, **every divergence figure must
name its base in the same breath**, and this campaign's KLD table must not be
compared against a BF16-anchored one.

### 2. Token overhead: the best single metric in their study.

They report that UD-Q2_K_XL needs **~1.25x the output tokens of BF16 on the
tasks both solved**. That one number connects quality to cost better than
anything this campaign had. It matters especially here because of this
campaign's own rule that wall-clock beats throughput: **a smaller file that
decodes faster per token but needs 25% more tokens to reach the same answer is
not faster**, and no tokens-per-second table will ever say so.

**Action taken.** Implemented in `scripts/report/compare-arms.py`, in a
stronger form than the source: **paired** over the exercises both arms solved,
reported as a median with an interquartile range rather than a ratio of sums.
Pairing matters because an arm that solves fewer, easier tasks would otherwise
look efficient. Extended to the derived costs that follow once tokens and
energy are both known per exercise - **joules per solved exercise**, **seconds
per solved exercise**, **tokens per solved exercise** - none of which is a
throughput number, and all of which are what a user actually pays.

### 3. They validate their harness against published reference results.

They plot official Qwen figures alongside their own to show the harness
reproduces a known number before trusting it on new ones. This campaign runs
aider's official benchmark unmodified in aider's own container, which is good,
but has **never demonstrated that it reproduces any published score**. A harness
can be faithful and still be misconfigured.

**Action.** Open. Adopt the practice: score one model with a published aider
polyglot figure, and report the delta as a harness-validation line before any
new result. Until then, absolute pass rates from this campaign should be read as
internally comparable but not cross-comparable with published leaderboards.

### 4. Reasoning effort interacts with quantisation, and they measured it.

They ran low / medium / xhigh and found the **gap between quantisations widens
at higher effort**. This campaign runs with reasoning **off** throughout, so it
is measuring one corner of that surface and reporting it as the surface. A
quantisation that looks harmless with reasoning off may not be.

**Action, scoped to this hardware.** A full effort sweep is **not doable**:
each level is another complete 225-exercise arm at three to four hours, and a
useful comparison needs at least two levels on at least two quantisations —
four arms, north of fourteen hours of exclusive machine time, on a rig that
runs exactly one measurement at a time. Dropped as beyond capability rather
than run at a sample size that could not resolve the effect anyway.

What is free, and is therefore required instead: every published pass rate from
this campaign **states that reasoning was off**, and states that the
quantisation gap is known *from other people's work* to widen at higher effort
— so a reader knows this is one corner of the surface, and which way the rest
of it moves.

### 5. Breadth: benchmarks, hardware, context.

Three benchmarks against our one; three GPUs against our one; 98k context on
their agentic benchmark against our 32k. Breadth is expensive and some of it is
simply unavailable here, but the honest consequence is that this campaign's
findings are **one-machine, one-runtime, one-context** results and must keep
saying so.

---

## Where this campaign is stronger, recorded so it is not traded away

These are not criticisms of the above - they are the axes this campaign should
keep, especially while adopting the items above.

- **Reproducibility.** They publish no code, no seeds, no configuration and no
  raw numbers, and note that the Unsloth v2 files they tested were replaced on
  19 August 2026, so most of their work is **not reproducible even by them**.
  This campaign commits its scripts, pins inputs by hash, and keeps raw
  telemetry.
- **Sampler discipline.** They disclose no temperature, top-p or seed anywhere.
  This campaign measured what that costs: the recommended sampler's run-to-run
  variation is **5.68%** against greedy's **0.77%**, a spread of 25.5% between
  repeats of an identical configuration. An undisclosed sampler makes a
  reported difference of a few points uninterpretable.
- **A measured noise floor.** They call Wilson intervals "very conservative for
  run-to-run noise" but never measured run-to-run noise. This campaign
  publishes a measured floor per phenomenon and refuses to report differences
  inside it.
- **Pairing.** They compare independent proportions. Both arms here run the
  identical suite in the identical order, so comparisons use **paired McNemar**
  on discordant exercises - strictly more sensitive on the same data, which
  matters when the effect is a few points on a couple of hundred items.
- **Interpolation.** They skipped Q8_0 on Terminal-Bench and interpolated the
  point rather than leaving it absent. This campaign's rule is that an
  unmeasured value is documented, never estimated.
- **Instrumentation.** Power, clocks, throttle reasons, memory traffic, host
  coupling and per-request server state are absent from their study entirely.
- **Per-task breakdown.** They state they have none. This campaign reports per
  language and per exercise, which is where the 3.0x energy spread was found.

---

## Scope decision, recorded once

Adopted, because each costs nothing beyond analysis of data already collected:

- **Token overhead**, paired over jointly-solved exercises, plus joules,
  seconds and tokens per SOLVED exercise (`compare-arms.py`).
- **Anchor cross-check** against their published BF16 point, reported as the
  lower bound it is (`anchor-crosscheck.py`).
- **Ladder convexity**, from the 200-chunk ladder already measured.
- **Plain statement of conditions** on every figure: one machine, one runtime,
  32k context, reasoning off, anchor is UD-IQ4_XS and not full precision.

Not attempted, because this hardware cannot do it honestly:

| item | why not |
|---|---|
| BF16 anchor | 55 GB against 24 GB VRAM + 31.8 GB system RAM |
| Q8_0 anchor | 29 GB; ~7 GB would sit on the CPU, hours on a loaded machine |
| reasoning-effort sweep | four full arms, 14+ hours of exclusive machine time |
| second/third benchmark | GPQA, IFBench, Terminal-Bench are each a fresh harness |
| multi-GPU comparison | one card exists here |
| 98k-context agentic | KV at that depth does not fit alongside these weights |

The rule this follows is the campaign's own: **an unmeasured value is
documented, never estimated.** A limitation stated plainly is worth more than a
number produced by a method the hardware cannot support.
