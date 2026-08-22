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
   truncation count; decode speeds need content, TOKEN REGIME (thinking vs answer tokens - a blind reproduction measured the same file at 39 vs 70 t/s at equal depth across regimes), depth, and desktop state;
   offload/iGPU speeds need RAM type and channel count.
4. **Two independent cheap metrics agreeing beats one expensive one.**
5. **When a claim dies, keep it as a dated case study** — how a clean benchmark
   misled is worth more than the number ever was (see the example's drafter-sweep
   section: "measured history, and proof that any single-prompt sweep overfits").

## Statistics
6. **Sample-size law**: accuracy at n≤25 is a smoke test (detects ~20-pt
   collapses only). Detecting a gap of G points needs roughly (paired, 95%/80%):
   20 pts → ~25; 10 → ~100–150; 5 → ~300–500; 1–3 → thousands. Perplexity/KLD
   over 294,912 token positions (36 x 8,192-token chunks of the frozen wikitext-2-raw test corpus - the reference
   campaign scored) is how healthy quants are actually ranked.
7. **The budget rule**: thinking models must run with a cap the longest thought
   cannot hit - clearing the appetite DISTRIBUTION's upper tail, not its median (a generous-looking cap near the median is a truncation machine); report truncations; on truncation, raise the cap and rerun the
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
10. **Decode is bandwidth ÷ bytes-per-token**: floor ≈ GB/s ÷ file GB × 0.7
    (the 0.7 efficiency constant is format-dependent — K-quants ran ~0.70,
    IQ formats ~0.65 in the reference campaign; re-derive per file from one
    measured point). Smaller equal-quality files are faster; this is why
    quality and speed often point at the same file. **Roster mandate**: any
    report that scales its measured decode to other cards ("scaling that by
    each card's derived decode gives…") must cover the FULL minimum card
    roster in `templates/REPORT-SPEC.md` §7 — the NVIDIA 24–32/16/12 GB
    classes, **DGX Spark (GB10, 128 GB unified, 273 GB/s)**, Intel Arc Pro
    B70/B50, and the Arc B390-class iGPU with its RAM-channel caveat — each
    row marked measured or derived-by-bandwidth; cards the machine cannot
    represent stay as derived rows, never dropped.
11. **Acceptance IS the speculative speedup.** Content decides acceptance; flags
    only tune where you sit on one curve. Sweep drafting knobs on realistic
    content; expect optima to shrink (shorter drafts) as acceptance falls.
12. **Depth costs**: decode declines with loaded context even with acceptance
    steady (KV reads/token grow); measure a depth series with server timings,
    never wall-clock that includes prefill. A depth series must DECLARE its
    parity: drafter on/off, projector on/off, and token regime — two series
    with mismatched parity are different experiments, not one curve.
    When a model ships more than one drafting mechanism (built-in MTP,
    DFlash-style heads, external draft models), name every one available and
    mark each measured or unmeasured — an unmeasured alternative silently
    omitted reads as nonexistent.

## Memory
*Every memory rule below is built on one arithmetic:*
**KV bytes/token = 2 × full-attention layers × n_kv_heads × head_dim ×
bytes-per-element (cache dtype)** — the 2 is K and V; count only
full-attention layers (linear/gated-delta/sliding-window layers cost less or
nothing); bytes-per-element is 2 for fp16, 1 for q8_0. Compute it per model
before any budget table; never carry another model's number forward.
KV-cache quantization to q8_0 is recommended only when verified per model
(reference: +0.23%/+0.31% PPL); **q4_0 K-cache is NOT a free next step** —
it is known to disproportionately damage some architectures, so it may not
be recommended without a measured per-model PPL check, and absent that check
a report says "unverified here" rather than staying silent.

13. **Two ceilings, not one — and ceilings belong to configurations, not
    files**: fully-resident (VRAM fills; fast even when the window fills) vs
    shallow-safe (overcommitted but fast until deep pages are touched), plus
    the collapse point. A ceiling is scoped to ⟨file + drafter on/off +
    projector on/off + desktop state⟩ — a blind reproduction showed a window
    labeled "fully resident" collapsing to 8 t/s at deep fill once the
    drafter's VRAM bill was on board. Therefore: (a) measure the VRAM
    footprint as a drafter-on/off PAIR (the reference drafter cost 1,008 MiB
    fixed + 5,120 B per window token + 898 MiB more at n-max 10 vs 4 —
    "no VRAM cost" was a published error this rule exists to prevent);
    (b) no window is labeled resident/safe without at least one deep-fill
    probe near its top.
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
    that survives session restarts. **Greedy repetition check**: any long
    greedy generation whose tokens or timings feed a claim must be spot-read
    for degenerate repetition loops first — a looping transcript inflates
    t/s and token counts with garbage, and greedy decoding makes the loop
    deterministic, not rare.

## The standard benchmark protocol
21. **Every reasoning-effort sweep runs the standard suite** under fixed
    conditions: `SEED=42`, `N=25` per benchmark per effort level, greedy
    decoding, `max_tokens 16384` (rule 7 applies: report truncations; if any
    arm truncates, raise the cap and rerun that arm). Server `-c` must exceed
    the suite's longest prompt + 16,384 — MeetingBank transcripts are long.
    **Must-run — all seven, every effort sweep.** Cross-report comparability
    (other models; the same model on other machines) requires the identical
    suite: a missing benchmark breaks apples-to-apples and voids the Mean.
    - GSM8K (`gsm8k/gsm8k`) — exact-match accuracy
    - ALPACA (`tatsu-lab/alpaca`) — judge-scored when an independent judge
      endpoint is configured; otherwise speed + transcripts only (a model
      judging its own outputs is not a score — this is a scoring gate, the
      benchmark still RUNS and its transcripts are kept)
    - HumanEval (`openai/openai_humaneval`) — sandboxed execution pass@1
    - MeetingBank (`huuuyeah/meetingbank`) — ROUGE-L vs reference summaries
    - MATH-500 — exact-match accuracy
    - MBPP — sandboxed execution pass@1
    - MT-Bench — judge-scored under the same judge rule as ALPACA
    **Optional**: only the agentic bucket (rule 22), because it alone carries
    an hours-to-days cost gate.
    **Mean** — the composite index: each *scored* benchmark normalized to
    0–100 by its own scorer, then averaged; always labeled "composite index
    over ⟨list⟩", never presented as an accuracy. Two reports' Means are
    comparable only when their scored sets AND suite hashes match — a report
    without a judge endpoint states that its Mean excludes the judge-gated
    pair.
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
    **Cost gate**: before committing to the sweep, run ONE task and project the
    full subset sweep from its wall time. If the projection exceeds a few hours
    (~4 h), do not run it — the bucket is then satisfied by citing the best
    available published scores (the leaderboard anchor plus any community
    local-quant results a search surfaces) and one honest line in the report:
    "local effort-sweep available but skipped for cost (projected ~N h);
    published anchor: ⟨score, conditions⟩". A cited anchor with a stated gap
    beats a sweep that never finishes.
    **Validated plumbing (2026-08-23, reference machine; full log:
    `agentic/setup-log.md`)** — reuse, don't rediscover: pass
    `--ak model_class=null` or mini-swe-agent silently routes `openai/...`
    names to the Responses API llama.cpp lacks; Pier's squid sidecar only
    allows ports 80/443, so the llama-server must listen on **port 80**;
    from WSL2 (NAT) the host is the vEthernet gateway (reference:
    `192.168.128.1`) — never localhost; serve with `-c 131072` minimum
    (a validation run overflowed 65,536 after just 22 calls — mini-swe-agent
    never summarizes) and check the bigger KV still fits VRAM; DeepSWE wall
    time is prompt-processing-bound (measured 1.01M prompt vs 21.7k
    completion tokens per task), so judge cost by prefill speed; one server
    restart per effort level (the knob is server-side); ~5 GB Docker image
    per task, cached across efforts (~50 GB disk for the 10-task subset);
    measure with `-n 1` — shared slots make per-task wall unattributable.
    Reference gate outcome: single task 9m36s truncating at 65k → projected
    ~8.5 h for a completing 10×3 sweep → gate says skip; anchor cited.
23. **Frozen inputs, offline-first.** Apples-to-apples across machines requires
    identical inputs: the benchmark test cases live IN the repo
    (`scripts/bench/datasets-frozen/`, `corpora/`) and every scored run uses a
    committed **frozen suite manifest** (SHA-256-pinned prompts + settings via
    the harness's `--suite`); two reports are comparable iff their suite hashes
    match. Loading order everywhere: frozen file → local cache → network — the
    network is a fallback, never a dependency, so a dead website or an
    air-gapped machine cannot break a run. What cannot live in git (runtimes,
    weights, container images) is covered two ways: the sneakernet path (copy
    `bin/` and `models/` from another machine — both are location-independent)
    and `scripts/make-offline-bundle.ps1`, which pre-downloads every external
    dependency into one folder for USB transfer. A campaign that had to touch
    the network for anything beyond the model weights records what and why.
