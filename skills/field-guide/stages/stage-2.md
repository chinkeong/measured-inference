---
name: stage-2
description: Load when executing Stage 2 (MEMORY MAP, ~1.5 h) — the budget table, the drafter on/off VRAM pair, the per-file ceiling sweep with deep-fill probes, the projector pair, desktop slack, and the two-constant VRAM(window) model.
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
- **Ceiling sweep per surviving file, with deep-fill probes** (reference:
  `ctx-limit-sweep.ps1`, `iq4-ctx-sweep.ps1`): step `-c` upward with short
  probes + VRAM readings. Report BOTH ceilings: fully resident (dedicated VRAM
  fills) and shallow-safe (probes stay fast on overcommitted windows), plus the
  collapse point. Label per file, per mmproj-on/off, AND per drafter-on/off — a
  ceiling belongs to a configuration, not a file. **No window is labeled
  resident/safe without at least one deep-fill probe near its top** — a shallow
  probe on an overcommitted window reads fast right up until deep pages are
  touched (measured collapse: 8.0 t/s at 91k fill).
- **The projector pair**: the same window with mmproj loaded and not, so
  vision's memory bill is a measured constant instead of a surprise (reference
  model: projector ≈ 0.9 GiB ≈ 27k tokens of q8 window — recompute per model).
- **Desktop slack**, stated using this model's computed KV cost from Stage 1,
  not a remembered constant (reference model: each 32k of q8 window ≈ 1 GiB).
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
