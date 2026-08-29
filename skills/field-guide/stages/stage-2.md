---
name: stage-2
description: Load when executing Stage 2 (MEMORY MAP, ~1.5 h) — the budget table, the drafter on/off VRAM pair, the per-file ceiling sweep on plan.json's derived rungs with deep-fill probes, the projector pair, desktop slack, and the two-constant VRAM(window) model.
---

# Stage 2 — MEMORY MAP (~1.5 h)
Product: **every candidate window becomes known arithmetic.** After this stage
you can state, without launching another server, what any ⟨file + drafter +
projector + desktop⟩ configuration costs at any window — which is exactly what
Stage 5 needs to size recipes on paper.

- Budget table from the Stage-1 KV arithmetic (context × KV-type × largest
  fitting quant).
- **The drafter on/off VRAM pair, measured first** — it moves every ceiling
  underneath it (reference: 1,008 MiB fixed + 5,120 B per window token +
  898 MiB more at n-max 10 vs 4; the reference guide's "no VRAM cost" was a
  published error a blind run caught).
- **Ceiling sweep per surviving file, on `plan.json`'s rungs, with deep-fill
  probes.** Do not run the shipped ladder as it stands:
  `scripts/arms/ctx-ceiling.json` is 25 arms holding 18 distinct `-c` values
  from 122,880 to 262,144, every one of them sized for ONE 27B on ONE 24 GB
  card. A different model needs the derived ladder —
  `plan.json`'s `rungs.per_file[].rungs[].c`, DERIVED per file from the fit
  table and the model's own `context_length`, with `rungs.step_rule` stating the
  rule that produced it. Measured 2026-08-29 against the reference 3090's
  `machine.json`: the reference 27B derives 12 rungs at step 8,192, 16,384 to
  212,992; `unsloth/Qwen3-1.7B-GGUF` derives ONE, at its whole 40,960-token
  window, because the arithmetic holds 198,618 tokens and there is no ceiling to
  find. A one-rung plan is not "no ceiling work" — it is a ceiling the
  arithmetic already found, and it still earns its deep-fill probe.

  Copy `scripts/arms/ctx-ceiling.json` to `results/<slug>/work/ctx-ceiling.json`,
  put the derived rungs in place of its `-c` values, keep its `stop_rule` (walk
  in file order, stop at the first rung below 0.75 × the reference arm, then
  binary-refine between the last good and the first bad rung at 4,096-token
  resolution), and run `python scripts/arms.py --arms
  results/<slug>/work/ctx-ceiling.json`. Its flags are RECONSTRUCTED from
  `serve-menu-example.bat`, so check them before publishing a ceiling; the
  Windows originals are archived in scripts/reference-3090/. Nothing else in
  this bullet changes with the swap: step `-c` upward with short probes + VRAM
  readings. Report BOTH ceilings:
  fully resident (dedicated VRAM fills) and shallow-safe (probes stay fast on
  overcommitted windows), plus the collapse point. Label per file, per
  mmproj-on/off, AND per drafter-on/off — a ceiling belongs to a configuration,
  not a file. **No window is labeled resident/safe without at least one
  deep-fill probe near its top** — a shallow probe on an overcommitted window
  reads fast right up until deep pages are touched (measured collapse: 8.0 t/s
  at 91k fill). Each derived rung carries its own `deep_fill_tokens` — 90% of
  that rung — so the fill depth is DERIVED as well, not picked.
- **The projector pair**: the same window with mmproj loaded and not, so
  vision's memory bill is a measured constant instead of a surprise (reference
  model: projector ≈ 0.9 GiB ≈ 27k tokens of q8 window — recompute per model).
- **Desktop slack**, stated using this model's computed KV cost from Stage 1
  against this machine's measured board total and desktop reserve in
  `results/<slug>/machine.json`, not remembered constants (reference model:
  each 32k of q8 window ≈ 1 GiB).
  Ship desktop-safe defaults; fence bare-desktop configs loudly (a browser UI
  once pushed the Windows compositor to 3.6 GiB and halved a "fitting" config).
- **The two-constant model — this stage's real deliverable.** From the pairs
  above, fit per configuration:
  `VRAM(window) ≈ fixed bytes + bytes-per-window-token × window tokens`
  (weights + drafter + projector + desktop overhead are the fixed term; KV is
  the per-token term). Two measured points give both constants, a third checks
  them, and from then on every candidate window is arithmetic rather than a
  launch. Verify the fit with one deep-fill probe at the top of each window a
  recipe will actually ship — arithmetic sizes the window, a probe confirms it.
