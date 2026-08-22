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
   over ~330k token positions (the wikitext-2-raw test split the reference
   campaign scored) is how healthy quants are actually ranked.
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
*Every memory rule below is built on one arithmetic:*
**KV bytes/token = 2 × full-attention layers × n_kv_heads × head_dim ×
bytes-per-element (cache dtype)** — the 2 is K and V; count only
full-attention layers (linear/gated-delta/sliding-window layers cost less or
nothing); bytes-per-element is 2 for fp16, 1 for q8_0. Compute it per model
before any budget table; never carry another model's number forward.

13. **Two ceilings, not one**: fully-resident (VRAM fills; fast even when the
    window fills) vs shallow-safe (overcommitted but fast until deep pages are
    touched), plus the collapse point. Report both, per file, per
    projector-on/off.
14. **Slack is the anti-spill budget**: ~1 GiB slack does not survive a desktop.
    Ship desktop-safe defaults; fence bare-desktop configs loudly. The window
    and projector costs are model-specific — derive them from this model's
    measured KV bytes/token and mmproj file size (reference finding — recompute
    per model: each 32k of q8 window ≈ 1 GiB; the vision projector ≈ 0.9 GiB ≈
    27k tokens).
15. **The -ngl off-by-one**: output projection counts as layer n+1; always
    `-ngl 99`; the miss pins CPU threads and costs real decode speed
    (reference finding — recompute per model: ~35%).

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

## The standard benchmark protocol
21. **Every reasoning-effort sweep runs the standard suite** under fixed
    conditions: `SEED=42`, `N=25` per benchmark per effort level, greedy
    decoding, `max_tokens 16384` (rule 7 applies: report truncations; if any
    arm truncates, raise the cap and rerun that arm). Server `-c` must exceed
    the suite's longest prompt + 16,384 — MeetingBank transcripts are long.
    The suite (HuggingFace ids):
    - GSM8K (`gsm8k/gsm8k`) — exact-match accuracy
    - MATH-500 — exact-match accuracy
    - HumanEval (`openai/openai_humaneval`) — sandboxed execution pass@1
    - MBPP — sandboxed execution pass@1
    - ALPACA (`tatsu-lab/alpaca`) — judge-scored when an independent judge
      endpoint is configured; otherwise speed + transcripts only (a model
      judging its own outputs is not a score)
    - MeetingBank (`huuuyeah/meetingbank`) — ROUGE-L vs reference summaries
    - MT-Bench — judge-scored under the same judge rule as ALPACA
    - **Mean** — the composite index: each *scored* benchmark normalized to
      0–100 by its own scorer, then averaged; always labeled "composite
      index over ⟨list⟩", never presented as an accuracy.
    **Interpretation guardrails**: a single N=25 cell is a smoke test
    (±~16 pts) — never rank efforts by one cell. The cross-suite Mean
    aggregates ~175 samples per effort and carries near-n=200 power; it and
    categorical collapses are the interpretable results. Any suspicious cell
    escalates to n=200 on that benchmark before being claimed. Expect the
    full sweep to cost ~4–8 h per model at max effort on a 24 GB card.
22. **The agentic bucket (optional, DeepSWE via Pier)**: when sandboxing is
    available (Docker; Pier from datacurve-ai), sweep effort levels on the
    deterministic DeepSWE subset `--n-tasks 10 --sample-seed 0` with
    `mini-swe-agent` against the local server (one server per effort — the
    effort knob is server-side). **Search for published results first**: cite
    the official leaderboard score for the base model as the anchor, and
    present local scores as ⟨quant, machine, effort⟩ deltas against it — the
    unpublished part is exactly that delta. Interpretation: n=10 is
    categorical-only (±~30 pts) — collapses and large effort gaps are claims,
    small differences are not; escalate to more tasks before claiming a
    ranking. Agentic tasks are where per-step error compounding lives — this
    bucket is the empirical test of the scope-perspective section's
    predictions, and the place low effort is most expected to fail.
