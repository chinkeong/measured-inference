---
name: stage-4
description: Load when executing Stage 4 (APPETITE PROBES, ~30 min) — two cheap probes per effort level to measure the thinking-appetite distribution that Stage 5 sizes every window and cap against. Skip only if the model has no effort/thinking knob.
---

# Stage 4 — APPETITE PROBES (~30 min, if the model has an effort/thinking knob)
Two cheap probes per effort level. Product: **the thinking-appetite distribution
per level** — the number Stage 5 sizes every window and every benchmark cap
against. This is the stage whose absence cost the reference campaign a 21-minute,
~120 Wh xhigh run that truncated to nothing (rule 25).

- **Cheap means cheap**: the shortest run that produces a thinking-token count.
  Use the reference task (`templates/effort-task-example.md`) or any prompt that
  reliably makes the model think, run at each level, at a cap and a window that
  cannot truncate — the largest window Stage 2 proved safe, with the cap set to
  the window minus prompt and a generous answer allowance. These probes are not
  quality arms: do not judge them, do not score them, do not publish them as
  effort quality. That is Stage 6's job, on locked recipes.
- **Record per level**: thinking tokens, answer tokens, wall, and whether the
  run finished. With n=2 you have a range, not a distribution — plan against the
  observed maximum plus margin, and say in `campaign.md` and the report that the
  tail is estimated from two samples (reference: xhigh 61–76k thinking tokens).
- **Spot-read the thinking traces for repetition loops before trusting the
  counts** (rule 20). Greedy decoding makes a loop deterministic, and a looping
  trace inflates appetite — which would then inflate every window in Stage 5.
- **A level that truncates even at the largest safe window** has its appetite
  recorded as "≥ window" and becomes a *not offered* candidate in Stage 5. It is
  never run as a measured-truncated arm.
