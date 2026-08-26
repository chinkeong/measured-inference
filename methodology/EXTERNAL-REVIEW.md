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

**Action taken.** BF16 is genuinely out of reach here (55 GB against 24 GB VRAM
plus 31.8 GB system RAM, with no headroom for KV or activations). **Q8_0 at
29 GB is reachable** with partial offload, and is near-lossless against BF16 by
every published account - Quesma's own ladder shows Q8_0 and BF16 indistinct
wherever both were run. Queued: fetch Q8_0, re-base the KL ladder on it, and
report both the Q8_0-referenced numbers and the IQ4_XS-referenced ones so the
older figures remain comparable. Until that lands, every divergence figure must
name its base in the same breath.

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

**Action.** Open. Reasoning effort should become an axis, not a fixed setting.
At minimum, every published pass rate must state that reasoning was off - which
is a condition, and this campaign's rule 3 already requires it to travel.

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
