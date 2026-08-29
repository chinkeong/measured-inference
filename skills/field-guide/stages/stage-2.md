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
  probes.** `scripts/arms/ctx-ceiling.json` runs UNEDITED and is not copied
  anywhere: since 2026-08-29 its two arms are rung TEMPLATES, and `arms.py`
  expands each into one arm per rung out of `results/<slug>/plan.json`, which
  `scripts/plan-campaign.py` derives from that file's own GGUF header
  (`context_length`, KV bytes/token, weights) and this machine's `machine.json`
  (board total, desktop reserve). Run the plan first, then the sweep:

  ```
  python scripts/plan-campaign.py --slug <slug>
  python scripts/arms.py --arms scripts/arms/ctx-ceiling.json --slug <slug> --dry-run
  python scripts/arms.py --arms scripts/arms/ctx-ceiling.json --slug <slug>
  ```

  **Do not hand-substitute the rungs into a copy of the file.** Writing the
  derived `-c` values in as literals produces the same servers and destroys the
  record of where they came from: every probe line would carry
  `ctx_source: "literal"` instead of `"plan"`, and lose the rung record, the
  plan's path, its slug, its generation time and its `rungs.step_rule` — the
  derivation, which is what makes the ceiling a labeled-derived number rather
  than a bare one (rules 1, 3 and 28). There is no fallback and that is
  deliberate: without a plan the file ABORTS and names the command that writes
  one, because a ladder sized for one 27B on one 24 GB card, run against
  something else, would be recorded as if it had been derived for it.

  Measured 2026-08-29 against the reference 3090's `machine.json`: the reference
  27B derives 12 rungs at step 8,192, 16,384 to 212,992; `unsloth/Qwen3-1.7B-GGUF`
  derives ONE, at its whole 40,960-token window, because the arithmetic holds
  198,618 tokens and there is no ceiling to find. A one-rung plan is not "no
  ceiling work" — it is a ceiling the arithmetic already found, and it still
  earns its deep-fill probe. `--dry-run` prints the derived ladder beside the
  reference campaign's own 18 rungs, as REPRODUCED or DIFFERENT; read it before
  committing the hours, because numbers measured on a different ladder are not
  arm-for-arm comparable with the published ones (rule 30).

  The file's `stop_rule` is the walk this stage performs and `arms.py` does not:
  run the rungs in file order (the plan emits them ascending), STOP at the first
  rung below 0.75 × the reference arm — the LOWEST rung of the sweep, not
  122,880 — then binary-refine between the last good and the first bad rung at
  4,096-token resolution, one arm at a time with `--only`, or by adding the
  refined rungs to the file as LITERAL arms beside the templates. A file may mix
  the two. Its flags are RECONSTRUCTED from `serve-menu-example.bat`, so check
  them before publishing a ceiling; the Windows originals are archived in
  `scripts/reference-3090/` and `results/ARM-PROVENANCE.md` grades every arm.
  Report BOTH ceilings:
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
