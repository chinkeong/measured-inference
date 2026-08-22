# METHODOLOGY — the rules every campaign obeys

Distilled from the reference campaign (Qwen3.8-27B on RTX 3090, 2026-08-22;
published as templates/example-report.html). Each rule earned its place by a
measured failure.

## Epistemics
1. **Measured, cited, or labeled-derived.** Nothing else ships.
2. **No reader measures less than promised.** Publish the number a reader will
   actually get under their realistic conditions; best cases are labeled best
   cases, with the condition that produced them.
3. **A number without its conditions is unfalsifiable.** Speculative speedups
   need their acceptance rate; benchmark scores need their max_tokens cap and
   truncation count; decode speeds need content, depth, and desktop state;
   offload/iGPU speeds need RAM type and channel count.
4. **Two independent cheap metrics agreeing beats one expensive one.**
5. **When a claim dies, keep it as a dated case study** — how a clean benchmark
   misled is worth more than the number ever was (see the example's drafter-sweep
   section: "measured history, and proof that any single-prompt sweep overfits").

## Statistics
6. **Sample-size law**: accuracy at n≤25 is a smoke test (detects ~20-pt
   collapses only). Detecting a gap of G points needs roughly (paired, 95%/80%):
   20 pts → ~25; 10 → ~100–150; 5 → ~300–500; 1–3 → thousands. Perplexity/KLD
   over ~300k token positions is how healthy quants are actually ranked.
7. **The budget rule**: thinking models must run with a cap the longest thought
   cannot hit; report truncations; on truncation, raise the cap and rerun the
   affected arm only (greedy determinism makes other arms byte-identical).
   **Never filter to non-truncating questions** — that selects the test set on
   one arm's behavior and drops exactly the hard items.
8. **Small-n quality judging** (n=2 per setting): blind judges, spec checklists,
   ties allowed; report variance beside means; categorical findings (works vs
   crashes) are real at n=2, point differences are not.
9. **Overthinking is real**: a lower score at higher effort on easy tasks is a
   statistical tie until proven otherwise, and the literature's overthinking
   effect is the mechanism to name if the lean persists.

## Speed
10. **Decode is bandwidth ÷ bytes-per-token**: floor ≈ GB/s ÷ file GB × 0.7.
    Smaller equal-quality files are faster; this is why quality and speed often
    point at the same file.
11. **Acceptance IS the speculative speedup.** Content decides acceptance; flags
    only tune where you sit on one curve. Sweep drafting knobs on realistic
    content; expect optima to shrink (shorter drafts) as acceptance falls.
12. **Depth costs**: decode declines with loaded context even with acceptance
    steady (KV reads/token grow); measure a depth series with server timings,
    never wall-clock that includes prefill.

## Memory
13. **Two ceilings, not one**: fully-resident (VRAM fills; fast even when the
    window fills) vs shallow-safe (overcommitted but fast until deep pages are
    touched), plus the collapse point. Report both, per file, per
    projector-on/off.
14. **Slack is the anti-spill budget**: ~1 GiB slack does not survive a desktop;
    each 32k of q8 window ≈ 1 GiB. Ship desktop-safe defaults; fence
    bare-desktop configs loudly. The vision projector ≈ 0.9 GiB ≈ 27k tokens.
15. **The -ngl off-by-one**: output projection counts as layer n+1; always
    `-ngl 99`; the miss costs ~35% decode and pins CPU threads.

## Effort & windows
16. **The window sets an effort ceiling**: measure each effort level's thinking
    appetite; a level whose appetite exceeds the window doesn't degrade — it
    truncates. On small-VRAM cards, medium is not the budget option, it is the
    best quality the VRAM affords.
17. **Effort buys completeness, not easy-task accuracy** (reference finding —
    re-verify per model): lowest effort shipped crashing code on hard generative
    work while matching everyone on easy math.

## Vision
18. Image cost is resolution, not file size (smart-resize → visual tokens;
    min-tokens floor for grounding, max-tokens for detail).
19. **Agents drop images silently** unless capability is declared — test every
    agent with a question only answerable by seeing the image; hallucinated
    "sight" is the worst outcome and must be hunted explicitly.

## Operations
20. Detach long jobs; make scripts resumable; parse-check before detaching;
    checkpoint-commit each phase; one GPU job at a time; keep a campaign log
    that survives session restarts.
