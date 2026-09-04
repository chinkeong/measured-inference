# Brief — section 8 of the Ornith-1.5-9B field guide, one added revision block

Write ONE `<div class="v2">` block containing TWO `<p>` paragraphs, to be
appended to the existing `.v2` block region at the end of section 8
("Benchmarks, and how much to trust them"). Print ONLY the HTML fragment to
stdout. No preamble, no explanation, no markdown fence.

## What the page already says, and must not be contradicted

- 198-question GPQA Diamond, scored 71.7 out of 100, published vendor figure 86.4.
- 43 of 198 answers ran past the length limit and were scored zero.
- Among the 155 that finished, 142 correct = 91.6 %. Both true, neither alone.
- Format tax 0.0 pp; zero unreadable answers of the 155 finished.
- Cap 30,000 tokens, seed 42, sampler temperature 1.0 / top_p 0.95 / top_k 20 /
  presence_penalty 0.0 — the model card's general preset.
- Section 9 carries a DIFFERENT phenomenon and you must not blur into it: under
  GREEDY decoding this model degenerates into repetition, and one prompt
  truncated at both 16,384 and 32,768. That row is about greedy. Everything in
  this brief is about the card sampler. Do not imply the cap advice repairs the
  greedy repetition, and do not imply the greedy row explains these 43.

## The facts you are writing up. Every figure here is measured or derived as marked.

Instrument: `work/appetite-censored.py`, run against the saved generations. Zero
additional GPU cost. The 43 truncated rows are right-censored observations, not
missing data.

MEASURED, non-parametric (Kaplan-Meier), exact up to the cap and undefined above it:
- 25 % of questions finish by 1,183 tokens; 50 % by 3,533; 75 % by 24,102.
- Survival at 30,000 = 0.217. Above 30,000 the data say nothing at all.

DERIVED, maximum likelihood with right-censoring:
- Every single-distribution fit is rejected against the finished answers. The
  best of them by AIC is lognormal and it still fails a Kolmogorov-Smirnov test
  at D = 0.1726, p = 0.0002.
- A two-component lognormal mixture is NOT rejected: D = 0.0440, p = 0.9119,
  and it beats the best single family by 59.8 AIC.
- Short mode: weight 0.474, median 1,230 tokens.
- Long mode: weight 0.526, median 23,077 tokens.
- The 30,000 cap therefore sat just past the LONG MODE'S OWN MEDIAN. It did not
  fall slightly short of the distribution; it cut through the middle of one of
  its two halves.
- The observed mean of 11,297 tokens per question falls in the sparse middle
  where almost no question lives: 84 finished answers under 2,500 tokens, 15
  over 20,000, and only 56 between.
- Cap needed for 10 % truncation: 66,935 tokens. For 5 %: 113,143. For 1 %:
  285,955. At a 0.1 % target the candidate families disagree by 68 times.
- A 66,935-token cap would cost about 11.7 GPU hours against the 7.9 hours the
  run actually took, because expected cost per question is dominated by the
  short mode.

MEASURED, accuracy of the 155 finished answers by generation length:
- under 2,500 tokens: 81 of 84 correct, 96.4 %
- 2,500 to 10,000: 32 of 34, 94.1 %
- 10,000 to 20,000: 18 of 22, 81.8 %
- 20,000 to 30,000: 11 of 15, 73.3 %
- All 43 truncated answers ran longer than every one of those.

DERIVED projection: scoring the 43 at the 73.3 % rate of the longest finished
bucket puts a re-run at 173.5 of 198, which is 87.6 %, with a 95 % floor of
81.5 % and a ceiling of 91.7 %. The vendor publishes 86.4.

## What must be said, and must not be overclaimed

1. The mechanism: the cap was set inside the long mode. That is why 21.7 %
   truncated, and it is why two earlier cap estimates derived from a mean both
   failed — a distribution with two modes has no useful mean.
2. The actionable number for a reader who will run this model on this benchmark:
   start at 66,935 tokens and expect about 10 % truncation.
3. The projection, and that it is statistically indistinguishable from the
   published 86.4 — which SUPPORTS the page's existing claim that 71.7 and 86.4
   are the same model measured with and without a cap.
4. MANDATORY CAVEAT ONE: the tail is an extrapolation. It rests on one measured
   constraint, survival 0.217 at 30,000, plus an assumed shape. The mixture is
   not rejected by the data, but no fit can see past the cap.
5. MANDATORY CAVEAT TWO: the accuracy gradient is CONFOUNDED, not causal. Hard
   questions produce both longer generations and wrong answers. Do not write
   that long thinking causes errors. The consequence that IS supported: the cap
   does not remove a random 21.7 % of questions, it preferentially removes ones
   the model was going to get wrong, which is why the projected recovery lands
   near the vendor's figure rather than above it.

## Register

Write against `methodology/VOICE.md`. Specifically:
- No `we`, `our`, `us`. No `dramatically`, `substantially`, `remarkably`,
  `seems to`. No `vs`, `versus`, `compared to` inside a paragraph.
- British forms.
- `&nbsp;` between a figure and its unit or symbol (`21.7&nbsp;%`, `66,935` is
  bare, `11.7&nbsp;GPU hours` — use it for symbol-unit pairs).
- Em dashes tight, no spaced hyphens, no comma inside a `-c <digits>` value.
- No edit-relative language: not `added`, not `this revision`, not
  `Recorded 2026-…`, not `earlier edition`. The reader has never seen a prior
  version of this page.
- Each paragraph opens with a short bold lead-in in `<strong>` tags, matching
  the two paragraphs already in this block ("A finding about the instrument,
  not the model." and "Sample size.").
- The two-voice law: a reader who reads only the bold lead-ins must come away
  with a correct shallow guide; the prose under them carries the evidence.
