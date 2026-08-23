---
name: stage-5
description: Load when executing Stage 5 (RECIPE LOCK) — the no-GPU gate. Write the dated recipe cards, apply the offer rule, set every Stage-6 cap, and name each planned run's consumer. No expensive run may start before this file's output exists.
---

# Stage 5 — RECIPE LOCK (no GPU time — the gate)
Stage 5 spends nothing and decides everything. Write the recipe cards into
`campaign.md` under a dated **RECIPE LOCK** heading. Each card carries:

**file · window (`-c`) · flags** (spec type / n-max / p-min / KV dtype /
`-ngl 99` / parallel / projector on-off) **· effort ceiling** (which levels this
recipe offers) **· expected speed band** (floor · real-work · ceiling from Stage
3, at this recipe's regime and depth) **· VRAM at the top of the window** (Stage
2's two-constant arithmetic, with the deep-fill probe that confirmed it) **·
desktop-safe or bare-desktop**.

- **The offer rule**: a recipe offers an effort level only if
  `window ≥ appetite upper tail + prompt tokens + answer allowance + margin`.
  Levels no recipe can hold are listed **"not offered"**, with their measured
  appetite beside them — never measured, never truncated, never quietly dropped.
- **Caps are set here, from the appetite distribution** — rule 7 applied BEFORE
  spending instead of after truncating. Every benchmark and effort arm in Stage 6
  inherits its cap from this line, and the serving `-c` must exceed the suite's
  longest prompt + that cap (rule 21). Truncation in Stage 6 is then impossible
  by construction; if an arm truncates anyway, the lock was wrong — fix the lock,
  raise the cap, rerun that arm only.
- **Name the consumer of every Stage-6 run** as you plan it (the
  over-measurement guard): the recipe decision or the reader-facing number that
  eats the result. Runs without a consumer are cut here, while cutting is free.

> **HARD RULE — the line no expensive run may cross.** No effort arm, benchmark
> suite, energy matrix, full PPL run beyond the Stage-1 screen, vision loop or
> agent matrix may start before the RECIPE LOCK is written. Stage 6 runs on
> locked recipes only. If a Stage-6 result invalidates a card (a window that
> will not hold, a band that does not reproduce), stop, fix the card, and note
> the correction in `campaign.md` — do not carry an unlocked configuration
> forward on the grounds that it is already running.
