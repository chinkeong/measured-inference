# METHODOLOGY — the rules every campaign obeys

Distilled from the reference campaign (Qwen3.8-27B on RTX 3090, 2026-08-22;
published as templates/example-report.html). Each rule earned its place by a
measured failure.

**Rule numbers are stable and are never reused or renumbered**, because they
are cited by name from probe headers, campaign logs and published pages, and a
citation that silently changes meaning is worse than one that dangles. One
number was overloaded and is now split: **rule 27 is QUIET MACHINE**, and the
Stage-0 interview rule — cited throughout this repository as "rule 27" until
2026-08-30, while carrying no text here at all — **is rule 31**. A "rule 27"
citation written before that date means rule 31 where its sentence is about
asking the user a question, and rule 27 where it is about host load or machine
state, which is what it always meant here.

## Epistemics
1. **Measured, cited, or labeled-derived.** Nothing else ships.
   (a) A number labeled **measured** resolves to a NAMED RUN in the Sources
   trail; one that resolves to nothing is downgraded to an estimate (a
   published "the card draws a measured ~310 W" had no trail entry and was a
   guess). (b) **CITED carries a grade** — primary-document-linked /
   arithmetic-on-published-specs / carried-from-a-dated-prior-fact-check
   (name the fact-check and its date) — and a DERIVED number inherits its
   WEAKEST input's grade, with its derivation DEPTH counted: name every
   borrowed constant it passes through (reference: roster rows derived twice
   over — bandwidth formula, then this machine's 1.91× drafting speed-up —
   and the non-CUDA rows a third time, because they also assume a speculator
   on a backend nobody ran). Laundering someone else's homework through a
   tag that says DERIVED is the failure this grades against.
   (c) **An unrun configuration is never printed as an unlabeled copy-paste
   block.** Format is an epistemic claim: a guess in a monospace block reads
   exactly like a measurement. Verification status is the block's FIRST line
   (`UNVERIFIED — DERIVED CONFIG`), never a trailing comment — which is what
   legitimizes printing derived recipes instead of dropping them.
2. **No reader measures less than promised.** Publish the number a reader will
   actually get under their realistic conditions; best cases are labeled best
   cases, with the condition that produced them.
3. **A number without its conditions is unfalsifiable.** Speculative speedups
   need their acceptance rate; benchmark scores need their max_tokens cap and
   truncation count; decode speeds need content, TOKEN REGIME (thinking vs answer tokens - a blind reproduction measured the same file at 39 vs 70 t/s at equal depth across regimes), depth, and desktop state;
   offload/iGPU speeds need RAM type and channel count; every speed needs its
   **SAMPLING SETTINGS**. Acceptance is a property of which token the drafter
   must guess, so sampling moves it directly: both reference reports published
   greedy speculative bands while shipping `temp 1.0` recipes. A speculative
   band is measured at the sampling its recipe ships, or it is labeled
   greedy-only and non-transferable. **Every table declares its comparability
   scope** — which other tables in the same report its numbers may NOT be
   compared against, and what differs (build, workload, run state).
   **THE CONDITION TRAVELS WITH THE NUMBER, AND THE BURDEN IS ON THE
   DESTINATION.** Stating the condition where a figure is measured is necessary
   and not sufficient: the failures happen where it is later QUOTED, and the
   origin is usually blameless. Four in one session, 2026-08-25/26, every one a
   correct number in the wrong place:
   **11,396 MiB** lost "board VRAM, contains this machine's desktop" three
   sections downstream and became a card verdict that told every 12 GB owner
   "No, use a smaller model" about a configuration needing 10,497 MiB;
   **2 of 75 empty answers** lost "at temperature 0" and became a
   recommendation floor no reader running the shipped sampler could ever meet
   (measured: 0 of 300 per file at the card's own settings);
   **`prompt_n` 13,771** lost "newly processed tokens, not depth" under
   `cache_prompt` and under-reported a retrieval depth by more than half;
   a **196,608-token recipe's prose** lost "at that window" and was pasted into
   a block running `-c 229376`. Rule 10 already says this for FLAGS - "tuned
   flags travel silently otherwise" - and it is the same disease with a
   different carrier. **A figure marked measured carries its condition in the
   same sentence, the same table cell, or one link away; a quoting section that
   cannot state the condition may not state the number.** These survive review:
   the 12 GB row passed four gates and a 137-agent audit, because every number
   in it was correct. Only re-deriving a figure from the raw measurement
   exposes it, which is why `scripts/verify/condition-check.py` runs before
   publication.
4. **Two independent cheap metrics agreeing beats one expensive one** — but
   only when at least ONE of the differences exceeds its own error bar. Two
   null results agreeing in sign is a tie, not corroboration (reference:
   PPL 6.535 vs 6.596 and GSM8K 94.0 vs 93.0, each already declared
   within noise, published as "two independent metrics agreeing" — two coin
   flips). A tie is broken on a named NON-QUALITY axis — file size, VRAM,
   load time — and the axis is named in the verdict.
5. **When a claim dies, keep it as a dated case study** — how a clean benchmark
   misled is worth more than the number ever was (see the example's drafter-sweep
   section: "measured history, and proof that any single-prompt sweep overfits").
   A superseded number carries its marker at EVERY occurrence — chart label,
   table row, figcaption, recipe comment — not only at the case study. A reader
   lands on one occurrence, not on the tour.

## Statistics
6. **Sample-size law**: accuracy at n≤25 is a smoke test (detects ~20-pt
   collapses only). Detecting a gap of G points needs roughly (paired, 95%/80%):
   20 pts → ~25; 10 → ~100–150; 5 → ~300–500; 1–3 → thousands. Perplexity/KLD
   over 294,912 token positions (36 x 8,192-token chunks of the frozen wikitext-2-raw test corpus - the reference
   campaign scored) is how healthy quants are actually ranked.
   **Cross-MODEL comparisons never use raw perplexity** — PPL is
   tokenizer-dependent (different vocabularies cut the same text into
   different token counts, so equal-text PPL across model families compares
   nothing). For a size-matched cross-model row ("does a 12B QAT at 4 bits
   beat a 27B crushed to 2?"), convert to **bits-per-byte**
   (total NLL ÷ corpus bytes: ln(PPL) × n_tokens ÷ (ln 2 × corpus_bytes),
   with each model's OWN token count) or judge by scored benchmarks
   (rule 21) — both tokenizer-independent. Within one model's quant ladder,
   raw PPL stays the ranking tool.
7. **The budget rule**: thinking models must run with a cap the longest thought
   cannot hit - clearing the appetite DISTRIBUTION's upper tail, not its median (a generous-looking cap near the median is a truncation machine); report truncations; on truncation, raise the cap and rerun the
   affected arm only (greedy determinism makes other arms byte-identical).
   **Never filter to non-truncating questions** — that selects the test set on
   one arm's behavior and drops exactly the hard items.
   **The raise is mandatory ONCE, and it is a diagnostic as much as a remedy.**
   A truncation has two possible causes and the rerun tells them apart: a
   budget shortfall (the raised cap completes the answer) or a
   **non-terminating generation** (the raised cap reproduces the truncation).
   If the raised-cap rerun reproduces it, **no further raise is licensed** —
   the item never terminates, the cap is merely what stops it, and escalating
   again only buys the same zero at more GPU hours. Say which of the two it
   was, keep the item in the denominator, retire the "provisional" mark the
   first raise earned, and stop. A campaign that keeps doubling caps against a
   non-terminating generation is measuring its own patience.
   **A reproduced truncation is a FINDING, not an inconvenience**: it says the
   model enters a state it does not leave, which no accuracy cell can show.
   Report it beside the score with whatever the mechanism probe found — and
   check the completion's content, because the worst shape is an unterminated
   thinking block that returns an EMPTY answer while consuming the whole
   budget (measured 2026-08-23/24 in two different model families: gemma-4-12B
   at 19 items, unchanged across a doubled cap; Qwen at xhigh, ALPACA item 21,
   empty at 16,384 and empty again at 32,768 while all 24 sibling answers
   reproduced byte-identically).
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
    represent stay as derived rows, never dropped. **Prefill is compute-bound
    — bandwidth ÷ file size does NOT scale it**, and a decode-ordered roster
    is the wrong buying advice for agentic work: any report recommending for
    agentic or long-context use publishes a PREFILL-SCALED row beside the
    decode row, and every wall-clock estimate states its prompt:completion
    ratio (reference: DeepSWE measured 1.01M prompt against 21.7k completion
    tokens per task — the wall clock is prompt-bound end to end). A recipe for
    a card the campaign did not run marks each flag **measured-here** or
    **carried-over-unverified**, and the block carries a derived banner: tuned
    flags travel silently otherwise, and a KV-quant verdict verified on CUDA
    is not verified on the backend it was pasted onto.
11. **Acceptance IS the speculative speedup — but MEAN DRAFT LENGTH is the
    throughput predictor.** Content decides acceptance; flags only tune where
    you sit on one curve. Refinement (measured 2026-08-23): the p-min gate
    truncates the draft tree on uncertain tokens, so acceptance can sit
    identical while throughput differs 1.69× (reasoning stream: accept 0.895,
    draft len 2.99, 36.6 t/s; answer stream: accept 0.907, draft len 4.31,
    62.0 t/s — same server, same 91k prompt, same flags). The
    highest-acceptance config can be the slowest. Report mean draft length
    beside acceptance, always — and report the **drafting PAIR**: drafted/pass
    AND accepted/pass, with the counter formula printed
    (`draft_n_accepted ÷ (predicted_n − draft_n_accepted)`), because
    throughput ≈ (1 + accepted/pass) per verify pass. Acceptance percentage
    alone is the wrong quantity: two rows reading 100% and 99% acceptance ran
    3.96 vs 10.54 accepted per target pass. Sweep drafting knobs on realistic
    content; acceptance is a property of the drafter head, not the quant (matched-pair
    sweep: same optimum, acceptance within 1.6 pts across quants).
12. **Depth costs**: decode declines with loaded context even with acceptance
    steady (KV reads/token grow); measure a depth series with server timings,
    never wall-clock that includes prefill. A depth series must DECLARE its
    parity: drafter on/off, projector on/off, and token regime — two series
    with mismatched parity are different experiments, not one curve.
    **The clock-ramp trap**: a probe fired right after a long prefill reads
    up to 45% low — the GPU's clocks are still ramping (prefill itself may
    only reach ~65% of settled clocks); steady-state temperature moves decode
    only ~1%. Discard the first post-prefill probe; time only settled probes.
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
**The arithmetic is a FLOOR, not the budget**: step `-c`, read the VRAM
delta, and budget from the measured slope — the reference model computed
34,816 B/token by arithmetic and measured 39,936 (drafter off) / 45,056
(drafter on), a 15% under-prediction that lands inside the slack fence.
KV-cache quantization to q8_0 is recommended only when verified per model
(reference: +0.23%/+0.31% PPL); **q4_0 K-cache is NOT a free next step** —
it is known to disproportionately damage some architectures, so it may not
be recommended without a measured per-model PPL check, and absent that check
a report says "unverified here" rather than staying silent (reference model
measured: +0.693% PPL vs f16 — superlinear, more than double q8_0's
+0.309%, with 1-SE error-bar overlap). **A cache-dtype verdict requires a
long-context RETRIEVAL check, not only a short-context perplexity delta**: a
perplexity pass at `-c 8192` structurally cannot see the retrieval failure at
200k that the verdict is justified by. Both reference reports refused q4_0 on
a retrieval argument and verified with an 8k PPL delta. A window shipped
beyond its retrieval-tested depth is labeled
**"speed-verified, quality-unverified at depth"**.

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
    27k tokens). **The desktop's own appetite is a dated RANGE, never a
    carried constant**: measure it across the campaign's own loads, from
    llama-server's dedicated counter against the board total (reference:
    133–1,181 MiB across 26 loads — nothing but what else was on screen).
    A recipe's slack must exceed (measured desktop MAXIMUM + the campaign's
    own load-to-load VRAM variance); a fence inside the noise is not a fence
    (reference: 1,260 MiB of slack against a 1,181 MiB desktop maximum, while
    two loads of the same config differed by 128 MiB — a 79 MiB margin).
15. **The -ngl off-by-one**: output projection counts as layer n+1; always
    `-ngl 99`; the miss pins CPU threads and costs real decode speed
    (reference finding — recompute per model: ~35%).

## Effort & windows
16. **The window sets an effort ceiling**: measure each effort level's thinking
    appetite; a level whose appetite exceeds the window doesn't degrade — it
    truncates. On small-VRAM cards, medium is not the budget option, it is the
    best quality the VRAM affords. Where reasoning is PRESERVED across turns,
    the ceiling is a **turns-per-window budget**, not a per-answer one —
    declare the preserve setting with the table (reference: xhigh = one turn
    in 131k) — and the **overflow event is measured, not assumed**: what the
    server actually does on turn N+1 past the window (error, context shift, or
    full re-prefill) and what that costs in wall clock. A level published as
    **not offered** names its BINDING CONSTRAINT — window or wall-clock —
    because the two have different fixes: a 12 GB card refusing xhigh at
    6–8 t/s is out of patience, not out of memory.
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
    **The liveness protocol — silence is not progress.** A detached pipeline
    must be watched in three tiers, because every tier can die and only the
    one above it notices: (a) every long runner WRITES a heartbeat
    (timestamp + progress counter, ≤2 min interval); (b) an independent
    WATCHDOG reads heartbeat freshness and GPU state, with its stale
    threshold set ABOVE the longest legitimate quiet stretch of the work it
    watches, and acts on staleness — restart the resumable runner, or
    escalate; (c) a SESSION-LEVEL fallback wake (~30 min) checks that the
    watchers themselves are alive. A heartbeat nobody reads is a diary.
    GPU idle while work is pending is itself an alarm condition, never a
    reassurance. Dated case study (2026-08-23 night): a ladder runner died
    the minute its inputs arrived, its agent's monitor died with it, and
    the GPU sat idle for two hours — invisible to the completion-based
    notification chain, caught only by a human asking for status. Both
    lower tiers existed; the third did not. **Greedy repetition check**: any long
    greedy generation whose tokens or timings feed a claim must be spot-read
    for degenerate repetition loops first — a looping transcript inflates
    t/s and token counts with garbage, and greedy decoding makes the loop
    deterministic, not rare.
    - **Every branch runs before publication.** Parse-checking covers the
      campaign's own scripts; code a REPORT ships is executed on every branch
      it advertises, and the advertised range is trimmed to what runs (the
      shipped launcher advertised `[1-8]` with only `pick_1`..`pick_4`
      defined — options 5–8 died on "cannot find the batch label").
    - **Artifact read-back.** A probe whose claim carries a content label
      ("copying", "prose", "code") must have its generated text SAVED and
      READ; discarded output cannot support a claim about what was generated.
      The signature is empty `content` with `finish_reason=length` — both
      reference copy probes had copied nothing and spent the whole budget
      thinking, and the read-back produced the campaign's largest correction.
      **The EMPTY-ANSWER RATE is its own metric, and the truncation counter
      cannot see it.** An empty completion has two shapes and only one of them
      trips a cap: `finish_reason=length` (the runaway rule 7 diagnoses) and
      **`finish_reason=stop` with zero characters** — the model spends its
      reasoning budget, terminates normally, and returns nothing. The second
      shape is invisible to every truncation count, so any scored arm reports
      empties and truncations as SEPARATE numbers. Measured 2026-08-24 on one
      model's quant ladder, same suite, same conditions: the 4.2-bpw and
      3.9-bpw rungs returned **0 empties of 75**; the 2.15-bpw rung returned
      **3 of 75, of which only 1 was a truncation** — the other two stopped
      by themselves after 3,939 and 7,296 tokens, and the identical three
      items scored 100 at the anchor. A report counting only truncations would
      have published "1" and missed two-thirds of the failure. Empty answers
      stay in the denominator (rule 7 forbids filtering) and their rate is
      published beside the score, because a rising empty rate is a
      degradation signal no accuracy cell explains.
    - **Knob-took-effect.** A server-side knob under test is proven to have
      reached the model by a cheap observable BEFORE its arms are believed
      (reference: `prompt_n` 1,689 vs 1,659 from an identical user message
      proves `--chat-template-kwargs` reached the template). A silently
      ignored kwarg produces three identical arms and a null result nobody
      can see.
    - **Instrument-first.** A surprising result runs a control isolating the
      MEASURING APPARATUS before it becomes a finding, and the report states
      which anomalies were traced to the instrument rather than the system
      (reference: a 30.61 t/s "collapse" was the meter; wall-clock read 9.2
      t/s where decode was 47.1).
    - **Resource-flag proof.** A flag whose stated purpose is a RESOURCE is
      measured on that resource, or it is not recommended. Two reference
      campaigns shipped opposite `--load-mode` defaults, each having measured
      only load time — one flag, two directions, zero system-RAM
      measurements. Closing it costs no GPU time.
    - **Schedule the budget-eater last.** A run whose only failure mode is
      consuming the time budget goes at the END of the campaign; then its
      failure ships as a finding instead of blocking the report.
      **And an escalation is a decision, not a reflex**: rule-7 cap-raises
      on SECONDARY arms are deliberate, priced choices — never automatic —
      because an unbounded secondary queued ahead of a deadline-bound
      primary is priority inversion (dated case, 2026-08-23: an automatic
      gemma cap-32k rerun consumed 4.1 GPU-hours while the quant ladder —
      the campaign primary — sat gate-blocked until its 8-hour wall
      expired cleanly and silently; every safety mechanism worked, the
      schedule was wrong). A deadline runner that exits with pending work
      says so loudly, and its watchdog treats pending>0 at exit as an
      alarm, not a completion.
    - **A blind reproduction declares three things**: its SEAL (the exact
      paths and globs never opened), its EXCEPTIONS (inputs, not results —
      a shared corpus is input data), and its INHERITANCE (which distilled
      artifacts of the sealed campaign — rules, templates, reference
      constants — it was permitted to use). An undeclared inheritance turns
      a front-matter "nothing is carried over" into a false scope claim.
    - **Name the measurement base once.** The campaign names the
      configuration every number was measured on, in one place, and marks
      every number measured on anything else — otherwise the whole report is
      silently about a config the reader is not running.
    - **The campaign log opens with a deviations register**: every departure
      from protocol, its justification, the AXIS on which that justification
      was verified, and the cheapest measurement that would close the rest.
      "Decode-neutrality was checked and held; the system-RAM half was never
      examined" is the shape — a justification is scoped to what it covers.

29. **An ignore rule is a claim about re-creatability, and it has to be true.**
    Every line in `.gitignore` asserts one thing about the files it matches:
    that anyone who loses them can make them again from what is left. That
    claim is true of downloaded weights, self-built runtimes, benchmark
    corpora and per-run transcripts. It is false of an instrument, and false
    of any primary record of an event that has already happened - a telemetry
    capture, a power trace, a scored arm. Because those two kinds of file get
    written into the same directories all day, ignore BY EXTENSION, or by a
    directory that holds nothing but bulk, and never by a directory of mixed
    content: the rule `results/**/work/`, written to exclude "campaign working
    data", excluded the harness that every measurement ran through, and nobody
    noticed for weeks, because git says nothing when it is obeying you. The
    test is one question asked about the file itself, not about the directory
    it happens to sit in: IF THIS FILE DISAPPEARED TONIGHT, WOULD REMAKING IT
    COST A COMMAND, OR AN EXPERIMENT? A command is bulk and may be ignored; an
    experiment is evidence and must be committed, whatever its size and
    whichever directory it landed in. A file that a tracked script reads, or
    that a committed record or a published page names, has already answered
    the question - it is evidence, so `git add -f` it now.
    `scripts/verify/instrument-guard.py` enforces this and exits non-zero;
    silencing it costs one written sentence in `instrument-guard-allow.txt`
    naming the command that remakes the file, and the difficulty of writing
    that sentence is the measurement.

31. **Questions to the user happen at Stage 0 ONLY; after the interview closes
    the campaign is autonomous to the end.** This rule is the product's shape
    rather than a post-mortem: a campaign that may stop and ask is a campaign
    that needs a human awake for the whole of it, and the whole of it is hours
    to days. Everything is asked in ONE round, up front, and auto-detected
    facts are handed back FILLED IN for correction rather than asked as open
    questions. After the round closes, mid-run uncertainty about what the user
    wants resolves in this order and no other: **the interview record in
    `campaign.md` → the measured default → record the assumption and
    proceed.** A campaign triggered on a Friday evening must hold finished
    results on Monday morning; a wrong-but-recorded assumption costs minutes
    to correct, and a GPU weekend spent blocked on a question nobody was awake
    to answer cannot be re-run.
    - **What can only be learned by asking is proved while asking is still
      legal.** A gated HuggingFace repo answers 401 at Stage-1 download time,
      by which point the round has closed — so access is proved INSIDE the
      round with a range request on one chosen file
      (`curl -sI -r 0-1023 <resolve-url>` → 206/200, not 401/403; the listing
      API succeeds on gated repos, so a listing is not proof), and a token is
      handed over and confirmed in the same round.
      `scripts/check-request.py` exists for this shape of question: it runs
      the network, arithmetic and architecture checks whose failure would
      otherwise need one, at the one moment a question is still allowed.
    - **Three answers cannot be defaulted away**, because no machine holds
      them: what the model will be used for, how many hours it gets, and
      quality-first or latency-first. Everything else on the sheet — the quant
      roster, the machine block, the slug, the installed-agent roster — is
      detected and printed already filled in, marked as assumed. A user who
      edits three fields and pastes the sheet back has closed the interview.
    - **Recording is the discipline the rule rests on.** An assumption never
      written into `campaign.md` is indistinguishable afterwards from a
      measurement, which is rule 1's failure reached by another road. The
      campaign log's deviations register is where it goes (rule 20).
    `skills/field-guide/SKILL.md` carries the seven questions and the answer
    sheet; `PROMPTS.md` carries the templates that close the round.

## Power
24. **Every watt carries its instrumentation tier; every joule carries its
    phase.** Energy is measured or it is absent — TDP is not a measurement,
    and a campaign that cannot read a counter says "unmeasured" rather than
    estimating.
    - **Tier label on every power figure.** Three tiers: **in-band** (the
      accelerator's own telemetry — NVML/`nvidia-smi` board power, RAPL,
      `powermetrics`), **node** (machine-level: IPMI/BMC, PSU telemetry), and
      **wall** (PDU or plug meter). Name the tier in the table header or the
      number is unfalsifiable (rule 3). A machine with NVML only — the
      reference 3090 — publishes "in-band GPU board power (NVML); PSU losses
      and datacenter PUE excluded", never calls that figure system power, and
      never inflates it by a guessed PSU efficiency. Total-system and
      cost-per-kWh claims need a wall meter or they do not ship.
    - **Phase-aware attribution is mandatory.** Prefill is compute-bound and
      spikes; decode is bandwidth-bound and flat (reference 2026-08-22:
      ~344 W sustained decode). One mean-watts figure over a whole run hides
      both. Log power **timestamped at ≤1 s interval** (the reference campaign
      logs at 500 ms) and **join the samples to the server's own per-request
      `timings`**: `prompt_n`/`prompt_ms` bound the prefill window,
      `predicted_n`/`predicted_ms` the decode window. Report the two
      separately. A watt-number over a wall-clock window that folds prefill
      into decode is rule 12's error with a meter attached.
    - **The standardized industry metrics — every report ships this table
      under that name**, each cell with its tier and phase: **J/token**
      (decode), **J per prompt-token** (prefill), **tokens/kWh**, **Wh per
      answer reported twice — gross and idle-subtracted**, **EDP =
      energy × latency (J·s)**, spelled out so no reader takes it for a
      power-delay product, and **E_comm (interconnect/communication
      energy)** — measured or split out on multi-accelerator serving, and on
      a single-GPU machine stated as "N/A — single GPU, no interconnect"
      rather than omitted. Idle is **measured on THIS machine and dated**, in
      both flavors (no-server and loaded-idle), with the first ≥60 s of every
      idle window discarded: the reference campaign's own idle numbers were
      contaminated — a board still cooling from the prior job read
      **33.2–34.6 W "idle"** against **30.7–31.1 W loaded-idle**, a
      physically backwards ordering; the settled tails read 30.3–31.0 W in
      both states. A remembered idle constant is not a baseline, and neither
      is a cooling board.
    - **The clock-ramp caveat is a power caveat too.** Rule 12's ramp applies
      to both ends of J/token: a prefill fired at a cold board reaches only
      ~900–990 MHz against 1,455 MHz settled, so it draws unrepresentative
      watts over an unrepresentative duration. Discard the first post-idle
      request as rule 12 discards the first post-prefill probe, and state
      which samples were dropped and why (clocks and pstate belong in the log
      for exactly this: they prove a low sample was a ramping board and not an
      efficient one).
    - **Every axis the report recommends on carries a J/token comparison or
      an explicit "not measured" line.** The set: quant (each candidate file),
      drafter (`--spec-type` off vs each tuned config — t/s rises at roughly
      constant W, so J/token should fall; quantify it), KV dtype (f16 vs
      q8_0), `--parallel` (1 vs 2, aggregate J/token — batching amortizes a
      fixed draw), depth (rule 12's series: t/s falls, so measure whether W
      falls with it and what J/token does), effort level, and token regime
      (thinking vs answer). A recommendation whose energy went unmeasured says
      so in its own row; silence is the omission rule 12 already bans, in
      energy.
    - **Power-limit capping is the direct efficiency knob — named either
      way.** `nvidia-smi -pl <W>` (reference 3090 default 350 W; Linux may
      need `-pm 1` first) trades t/s for J/token and belongs in the same
      J/token + EDP table as every other axis. It normally requires an
      elevated shell: a campaign that can elevate **measures** it; one that
      cannot prints the command, the stock cap, and "unmeasured on this
      machine (requires administrator)". An unmeasured knob is documented,
      never estimated.

28. **The RUN is the scarce thing, not the sampling — collect every field the
    instrument offers for free while the workload is in front of you.** A
    measurement run costs hours; widening an `nvidia-smi` query that is already
    being issued costs nothing. A field not written down during the run cannot
    be recovered afterwards at any price, so the default is to over-collect.
    - **A power number without a constraint reading is unattributable, and
      therefore not comparable.** Two cards, two quantisations, or one card at
      two caps can report the *same* J/token for opposite reasons — one starved
      of bandwidth, the other clipped by its power limit — and watts alone
      cannot separate them. Every energy sample therefore carries
      `utilization.memory` and `clocks_event_reasons.active` alongside
      `power.draw`. Audit of 2026-08-27: seven scripts shared a sampler
      collecting clock, temperature and power only, so **every J/token this
      campaign had published to that date was unattributable** — corrected at
      source rather than by re-running.
    - **Throttle masks are counted with idle samples REMOVED.** A mask of
      `GpuIdle` says the workload was not running; counting those dilutes every
      other reason. Reading a raw histogram produced the claim that thermal
      throttling "never" fired on the reference part; dropping idle samples put
      it at 3.0% of busy samples, with the fan already pinned at 100%.
    - **Fields that are genuinely unavailable are recorded as such**, so their
      absence is never read as an oversight. On the reference RTX 3090:
      `temperature.memory` (and dmon `mtemp`) return N/A, and `nvidia-smi pmon`
      reports `-` for every process under Windows WDDM, so per-process GPU
      attribution cannot be had on that platform at all.
    - **A server is instrumented before it is depended on.** `llama-server`
      needs `--metrics`, and its stdout must go somewhere real. A full agentic
      run was launched without either and produced a complete power trace and
      complete pass rates that **could not be divided into each other**. The
      standing recovery, which needs no flag and no restart, is to poll
      `/slots`: it carries prompt depth, tokens served from cache, and
      `n_decoded` per request. Prefer it to the log even when the log works.
    - **A poll-derived phase split is close, but only over a long window -
      and a short window can invert the error.** Measured 2026-08-27 by running
      both methods over the same run. Over the FULL arm (285 minutes, 16,931
      poll samples) 1 Hz `/slots` polling put decode at **78.9%** of busy time
      against the server's own cumulative counters at **80.4%** - a bias of
      **-1.5 points**, small enough that poll-derived splits already published
      stand. But an earlier measurement of the same quantity on a **4-minute**
      window early in the same run reported **+6.3 points**, wrong in
      magnitude AND in sign, because start-up transients dominated it. That
      preliminary figure was published here and is retracted.
      The lesson is the general one, not the number: a bias estimated on a
      short window is not a small version of the bias on a long one, and may
      not even point the same way. Any instrument-versus-instrument comparison
      is measured over the full run or not reported.
    - **An agentic J/token carries its prompt:completion ratio.** Measured
      across one run's exercises, energy per completion token spans **3.0×**
      (4.512 to 13.617 J) because prompt-heavy exercises decode few tokens to
      divide their energy by; the residual correlates with the
      prompt-to-completion ratio at 0.78. A single agentic J/token without that
      ratio is not a characterisation of the machine, and rule 3's transport
      clause applies to it in full.
    - **Energy attribution is only as good as its window, and a plausible
      window is not a correct one.** The first version of that measurement
      reported a **30×** spread. It was an artefact: the harness records a
      duration that covers only model calls, while the file whose timestamp
      anchors the window is written after the unit tests and the build
      cleanup, so the window had the right LENGTH in the wrong PLACE and
      billed test-time idle to the model. The cheapest exercise was published
      at 0.417 J/token against a true 5.830. Attribute each unit of work to the
      interval since the previous one finished, integrate only the busy
      samples, and state the busy fraction — 96.3% here — so a reader can see
      how much of the window was real.
    - **A cross-check must run over a window both sources cover.** Comparing
      client-side and server-side token counts across a span where one
      collector started late measures the missing prefix, not any disagreement:
      it produced a −19.5% "gap" that was pure window mismatch. Restricted to
      the overlap, the real disagreement is **+9.7%**, and it is a finding in
      its own right — the benchmark passes no separate small model, so
      chat-history summarisation is served by the same server through a path
      that does no token accounting, spending energy that reaches the numerator
      with nothing in the denominator.
    - **While power is pinned at the cap, J/token is a restatement of
      throughput.** Measured mean 335 W at 12.2% coefficient of variation with
      the part busy 93% of the trace: J/token is then `power ÷ tokens per
      second`, and it separates two designs only where they also differ in
      speed, or where the cap stops binding. An energy column that adds nothing
      to the speed column says so.

## Sequencing
25. **Cheap probes buy the map; the map locks the recipes; only locked recipes
    earn expensive hours.** Measurement has an order, and the order is not
    negotiable: information that would change what you run is bought FIRST, at
    the lowest price it can be bought at, and it is written down as a decision
    before any hour-scale run begins.
    - **The recipe lock is a gate, not a summary.** Before any expensive arm —
      effort arms, the rule-21 benchmark suite, the energy matrix, full
      perplexity beyond the cheap screen, the vision loop, the agent matrix —
      the campaign writes explicit recipe cards (file · window · flags · effort
      ceiling · expected speed band) into the campaign log. Nothing expensive
      starts above the line where those cards are written. A configuration that
      is not on a card does not get measured; a card a later measurement
      falsifies is corrected on the card first and re-run second.
    - **Appetite before effort arms.** Every effort level's thinking-token
      appetite is measured by cheap probes before ANY expensive arm runs at that
      level, and a level is offered on a recipe only where
      `window ≥ appetite upper tail + prompt + answer margin`. A level no recipe
      can hold is published as **not offered**, with its measured appetite
      beside it — it is never run to truncation and reported as a score.
    - **Caps cleared before benchmark arms.** Rule 7 is applied BEFORE spending
      rather than after truncating: every benchmark and effort cap is derived
      from the measured appetite distribution, and the serving `-c` is sized
      above longest-prompt + cap, so truncation is impossible by construction.
      Truncation discovered afterwards is a sequencing failure, not a data
      point.
    - **Sweep at the SHIPPED RECIPE, not at a clean-room default.** Once
      Stage 5 has locked the recipes, every comparison arm runs with the flags
      the recipes actually ship — drafter and its tuned n-max/p-min, KV dtype,
      effort level, projector — because a ranking measured under a
      configuration no reader runs is a ranking of something nobody will
      experience. Where an arm MUST deviate (greedy scoring wants determinism;
      a scored suite wants the drafter's speed out of the timing), the
      deviation is NAMED, its axis is stated, and its immateriality is
      MEASURED ONCE rather than assumed — the campaign's own energy table
      already does this correctly with its "named difference" paragraph.
      **Dated case study, 2026-08-24/25 — this rule cost four GPU hours and
      inverted a verdict.** A quant ladder scored eight rungs drafter-OFF for
      clean determinism, and on those numbers UD-Q2_K_XL (9.154 GiB) tied the
      4-bit UD-IQ4_XS (13.274 GiB) on accuracy while running FASTER
      (45.66 vs 42.34 t/s) — an obvious daily-driver upgrade freeing 4.12 GiB.
      A follow-up probe at the shipped drafter setting reversed it: with
      `--spec-type draft-mtp` on, the 4-bit file runs **86.91 t/s against the
      2.9-bit file's 77.01** — 12.9% FASTER despite being 45% larger, because
      the draft head degrades with bit-width (acceptance 0.611 → 0.551, mean
      draft length 5.70 → 5.08, speculation worth 2.05× → 1.69×). **The
      ranking INVERTS when the drafter is switched on.** Had the sweep shipped
      the recipe's flags from the first arm, the right answer would have been
      in hand at no extra cost; instead it needed a separate probe, and the
      wrong answer was briefly the obvious one.
    - **Appetite is a property of the QUANT, not only of the effort level.**
      Rule 25 already requires appetite probes before effort arms; the same
      applies per rung of a quant ladder. Generation length grows as bit-width
      falls — at the bottom a model stops terminating at all — so a cap chosen
      once for the top of the ladder is a truncation machine at the bottom.
      Probe two or three prompts per rung and read the token counts before
      committing the arm: it costs minutes and it either raises that rung's
      cap up front or screens the rung out. Dated case study, 2026-08-24:
      UD-IQ1_S at 1.835 bpw truncated **20 of 75** items at a 16,384 cap
      inherited from the 4-bit rung, answering in 7k–16k tokens where the
      anchor used a few hundred, and its arm ran 2.5 h — five times any other.
    - **Prune before you treat.** A candidate file earns expensive treatment
      only after surviving a cheap screen (throughput probe + file size + a
      short perplexity screen over identical chunks). A file that is both slower
      AND worse is dropped there, with both screen numbers recorded and
      published as screened-out — never carried through hours of treatment to
      earn a one-word verdict.
    - **Dated case study (2026-08-22, reference campaign — rule 5).** The xhigh
      effort arm ran 21 minutes and ~120 Wh inside a 65,536-token window. The
      campaign then measured xhigh's thinking appetite: **61–76k tokens**. The
      arm had truncated, the deliverable was zero, and it had to be re-run at a
      raised cap. The cheap probes that would have predicted this cost minutes;
      they would have moved the run into a window that fits, or listed xhigh as
      not offered on that recipe — honestly, and for free. The same campaign
      carried UD-Q4_K_XL through the full treatment to conclude "pointless":
      hours spent to publish one word. Both failures have one shape — an
      expensive run started before the cheap information that governed it
      existed.
    - **The who-consumes-this-number test.** Every planned run names, before it
      starts, the recipe decision or the reader-facing number that will consume
      its result. A run nothing consumes is cut: completeness is not a consumer,
      and neither is curiosity. The same test bounds replication — establish the
      noise floor by replicating ONE configuration across arms, never every arm.
      Over-measurement is not the safe error: it spends the hours the runs a
      reader actually needs were going to use.
    - **The added-phase register** is the retrospective half of that test:
      every unplanned probe is logged with the QUESTION that forced it and
      whether the answer changed a published conclusion (reference: nine
      phases added, six of the nine changed one). A plan that never deviates
      was not measuring anything.
    - **The cost ledger.** The campaign log carries GPU-hours and Wh per
      phase against what each phase bought, so the who-consumes test can one
      day be tuned by data instead of by anecdote.

## Noise
26. **The noise floor is published once, page-wide, and it bounds what may be
    claimed.** Every campaign derives its probe repeatability from the ONE
    configuration rule 25 had it replicate, and publishes the resulting band
    as a reading instruction for the whole report, naming the class of claim
    that survives it — levels, ratios, or categorical (reference: "read every
    single-probe level on this page as carrying about ±25% of clock-state
    noise; the shapes and the ratios are what survive it", derived from
    18.27 / 18.82 / 19.21 / 26.60 t/s on one config). **Printed precision
    respects the band**: four significant figures on a ±25% probe is a lie of
    precision, and a header strip naming `79.26` is claiming a level it
    cannot hold.
    **A SPEED BAND NAMES ITS SAMPLER.** Measured 2026-08-25, 25 alternating
    pairs in one load on a host-gated quiet machine: greedy (temperature 0,
    top_k 1) gives **CV 0.77%, spread 3.8%**; the model card's recommended
    sampler (temperature 1.0 / top_p 0.95 / top_k 20) with the drafter on
    gives **CV 5.68%, spread 25.5%** — seven times wider, and **replicated
    three times**: greedy 0.99 / 0.76 / 0.77%, sampler 5.76 / 5.61 / 5.68%,
    with the excess attributable to sampling alone at **5.62%** and decode
    tracking mean draft length at **r = 0.923** within the run
    (`scripts/bench/sampler-band.py`). **The published figures are the ones
    whose artifact is on disk** — the first two runs completed their GPU work
    and then died in the paragraph that explains the numbers, losing both, which
    is why that script now writes its artifact before it interprets anything. This is rule 11 at
    the scale a reader meets it: sampling changes the text, different text
    drafts differently, and mean draft length decides speculative throughput.
    A campaign measures greedy so the machine is the only variable — that
    is correct — but it must then ALSO publish the band for what the reader
    will actually run, and say plainly that **a single generation is not
    evidence about a setup**. A reproduction check is exempt only if it PINS
    the sampler in the request body it tells the reader to send.
    **One noise band per phenomenon**, stated once, with the
    arithmetic connecting any second figure to it — a page carrying both
    "a 45% swing" and "±25%" with nothing joining them has two noise floors
    and therefore none. A baseline used as a DIAGNOSTIC THRESHOLD is
    replicated across the conditions it claims invariance to and shipped as a
    band, not a point (reference: the decode floor established across four
    contents and both token streams, published as a 3% band). And every
    report ends with ONE reproduction check: the exact command, the value it
    should return, and a **PASS BAND derived from this campaign's own noise
    floor**. Without the band a reader cannot tell a broken setup from probe
    noise, which is the only thing the check was for.

27. **A speed measurement requires a QUIET MACHINE, and every probe records the
    machine state it ran under.** Measured 2026-08-25 on the reference rig:
    with the GPU at full boost, loading the HOST with 18 busy processes cost
    **−5.4%** of decode on average and **−24.0%** on the worst pair,
    **12 of 12 pairs negative**, while SM clock *rose* **+0.9%** and
    temperature and acceptance were unchanged
    (`scripts/bench/cpu-contention.py`). It also made the reading erratic:
    **CV 0.97% quiet against 6.09% loaded**. llama.cpp's decode loop is not
    purely a GPU affair — sampling, draft acceptance and token bookkeeping
    run on the CPU, and speculative decoding does more of it per token —
    so a starved host slows decode *invisibly to any clock or temperature log*.
    **A report that cannot say the machine was quiet cannot defend its
    levels.** Every probe therefore records SM clock, board power and
    temperature; a reading without them is not admissible, because it can
    never be diagnosed afterwards.
    **CONFIRMED IN THE WILD, not only under synthetic load.** Forty-five
    repeats of one greedy probe in one server load, on a machine nobody was
    deliberately loading, with a CPU-availability index sampled before each
    probe: **r = −0.924** between that index and decode throughput, which is
    **85% of the variance** (`scripts/bench/host-correlate.py`). Six of the
    forty-five probes fell into an excursion, and it carries a
    **three-part signature that identifies it on sight**: those six probes
    against the other thirty-nine read **65.58 against 73.78 t/s** on decode,
    **1736 against 1698 MHz** on SM clock, and **327.3 against 341.8 W** on
    board power — that is
    **throughput DOWN 11.1%, clock UP 2.2%, power DOWN 4.2%, all at once.**
    A starved process leaves gaps in the GPU's work, so the card draws less
    power, and with that headroom it boosts *higher* while delivering *less*. Any
    speed reading showing that combination is contaminated, whatever its clock
    log says. `refarm.quiet_report()` gates a run on the same index; it read
    2.07× idle under load and 1.01× quiet.
    **What this instrument actually resolves**, all measured on one rig on
    2026-08-25 and all far narrower than had been feared:
    within one server load, greedy, n=100 — **0.32% CV**, no drift
    (`resolution-floor.py`); across **16 separate loads** of one fixed arm
    — **1.1% range**, of which only **0.26%** is genuinely between-load
    (`refarm.py --calibrate 16`); probe length 80 / 200 / 700 / 885 tokens on
    a shared window — **0.58 / 0.32 / 0.32 / 0.40% CV**, so length barely
    matters (`probe-length-floor.py`); prompt wording, two prompts alternating
    in one load — **1.4%**, in the direction rule 11 predicts
    (`prompt-ab.py`). **The busy host dominates every one of these, and it is
    the only one that is not a property of the measurement at all.**
    **The REFERENCE ARM.** Comparisons that cannot share a load — a quant
    ladder must reload to change the file, a context series to change `-c`
    — interleave ONE fixed configuration, loaded and probed beside the
    arms. Its calibrated tolerance on this rig is **1.0%** (3 sd of 16 loads).
    If the reference moves further than that between the arms, the comparison
    is **VOID** and re-run: the arms are not comparable, and no care taken
    inside them repairs it. The standard must never be tuned — change its
    model, prompt, flags or probe count and every earlier reading becomes
    incomparable, so a new standard is calibrated from scratch and the old
    readings retired rather than converted.
    **CASE STUDY, 2026-08-25.** `sampling-bridge.py` reported **64.32 t/s**
    for an arm that reads **74.36** over sixteen loads and **75.53** on that
    script's own prompt. Five explanations were proposed and each was killed by
    measurement in turn — a between-load lottery, the prompt, probe length,
    clock state, temperature. The cause was the host, and it cost a day to find
    because that script was the only one in `scripts/bench` that logged no
    clock, no power and no temperature. **The reading nobody can explain is
    reliably the one taken by the instrument that recorded least.**

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
    - ALPACA (`tatsu-lab/alpaca`) — judge-scored when a conforming judge
      endpoint is configured (see the pinned judge protocol below); otherwise
      speed + transcripts only (a model judging its own outputs is not a score
      — this is a scoring gate, the benchmark still RUNS and its transcripts
      are kept). "Unscored **by design**" is the wrong label for a missing
      judge: an absent instrument is a GAP, and calling it a design choice
      dresses a hole up as a decision. Say "unscored — no judge configured",
      and keep the transcripts so the gap can be closed later without
      re-running the GPU. The reference endpoint is
      `scripts/bench/judge-panel.py`.
    - HumanEval (`openai/openai_humaneval`) — execution pass@1 (isolated
      subprocess: `python -I -E`, temp cwd, timeout — isolation, not a true
      container sandbox; run untrusted-model code with `--no-exec` where that
      matters)
    - MeetingBank (`huuuyeah/meetingbank`) — ROUGE-L F1 vs reference
      summaries (8,192-token prompt guard, head-truncation marked in-prompt)
    - MATH-500 — exact-match accuracy
    - MBPP — execution pass@1 (same isolation note; scored against the FULL
      test list)
    - MT-Bench — judge-scored under the same judge rule as ALPACA, **turn 1
      only** (pinned — comparability requires every report to agree);
      judge ratings normalize (r−1)/9 → 0–100
    The harness is `scripts/bench/` (`--rule21` preset; explicit flags beat
    the preset — `--rule21 --samples 200` is the escalation run); the
    committed reference manifest is `scripts/bench/suites/rule21-n25.json`
    (hash `1cdf54f8eb9d3f8f`, 175 prompts, `-c 32768`).
    **Optional**: only the agentic bucket (rule 22), because it alone carries
    an hours-to-days cost gate.
    **Mean** — the composite index: each *scored* benchmark normalized to
    0–100 by its own scorer, then averaged; always labeled "composite index
    over ⟨list⟩", never presented as an accuracy. Two reports' Means are
    comparable only when their scored sets AND suite hashes match — a report
    without a judge endpoint states that its Mean excludes the judge-gated
    pair. **When a judge is configured, publish BOTH Means** — the five-set
    one, because every earlier comparison in that campaign is against it, and
    the seven-set one, because that is what this rule specifies. Dropping
    either silently breaks one comparison or the other.
    **The judge protocol is pinned** (same reason turn-1 is pinned —
    comparability requires every report to agree). A judge endpoint is
    conforming only if it is: (a) a model family *different from the model
    under test* — the scoring gate is about self-grading, so a same-family
    judge is not a judge; (b) **blind** — opaque per-answer identifiers, the
    identifier→arm map sealed in a file no judge reads, and a per-seat shuffle
    seed so ordering effects do not correlate across seats; (c) a **panel of
    ≥3 seats**, every seat rating every answer, with the seat spread published
    beside every mean — a single seat is an anecdote; (d) scored on the
    standard 1–10 single-answer rubric, normalized (r−1)/9 → 0–100; (e) run
    over **every** answer including empty, truncated and degenerate ones —
    rule 7's no-filtering clause binds the judge exactly as it binds the
    scorer, and an empty answer is a 1, not an exclusion.
    **Arm-against-arm claims from judged sets are PAIRED or they are not
    made.** The same prompts went to every arm, so compare per-prompt
    differences with a bootstrap interval, not mean against mean; report the
    win/loss/tie counts beside the interval; and when several comparisons run,
    say how many, and call an interval that barely clears zero *marginal*, not
    a finding (rule 8: point differences are not real at small n).
    **A correlated judge is disclosed, never presented as independence.** If
    the judge and the report's author share a vendor or model family, the
    scoring gate is satisfied but independence is not: say so wherever the
    numbers appear, and carry the stronger judge — another vendor, or humans —
    as an open negative-register entry with its price. Keep the blinded
    packets, the sealed key and every rating, so a different judge can be run
    over the identical answers and compared.
    **What a judge is FOR is not only the score.** Judged sets are the only
    instrument in this suite that can see confident invention, degeneration
    that stops short of any cap, and instruction-following failures. Report
    those findings beside the score — and when a degeneration shape gets past
    the campaign's own detectors, that is a measured instrument gap and is
    published as one (2026-08-24: a story prompt that became an endless
    spelled-out number count at 1,682 tokens tripped no truncation counter and
    no repetition detector; three seats rated it 1).
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

30. **On this rig throughput has two levels and nothing recorded predicts
    which one you get, so ratios travel and absolute numbers do not.**
    Twenty-three sessions of one identical configuration on 2026-08-28 -
    UD-IQ4_XS, n-max 10 / p-min 0.5, `-c 32768`, `-ctk/-ctv q8_0`, `-ngl 99`,
    `--parallel 1`, `-fa on`, reasoning off, greedy, 700 predicted tokens,
    fresh server each, one warmup discarded - produced twenty results between
    75.71 and 78.65 t/s and three at 88.76, 88.18 and 88.21. Two levels about
    13% apart, with nothing in between.

    Seven candidates were tested and every one was eliminated: the workload
    (greedy output is bit-identical, probe for probe), the drafter (acceptance
    and mean draft length bit-identical across sessions), the llama.cpp build
    (every compute library unchanged since 2026-08-19), the core clock (a HIGH
    session ran 49 MHz SLOWER than a low one), board temperature (75-83 C
    throughout), the memory clock (pinned at 9501 MHz in every probe ever
    recorded), and prior sustained load, which was tested by four alternating
    pairs and refuted at -0.43% with overlapping ranges. **The cause is
    unmeasured. Do not name one.** Three mechanisms were named and withdrawn
    in a single day before this rule was written.

    THE OPERATING CONSEQUENCES, which cost nothing to follow:

    - **Compare arms inside ONE sweep. Never compare a number from one sweep
      against a number from another.** Re-running the five-arm drafter sweep
      last-to-first kept every relationship's sign and rough size (f16 KV
      -8.9% then -8.2%; `-c 180224` -3.1% then -4.7%; n4/p0.00 +8.4% then
      +13.2%) while the baseline arm itself moved 76.32 to 67.41, -11.7%.
      Ratios are robust; levels are not.
    - **A multi-arm sweep alternates or reverses its arm order**, because a
      sweep that starts a fresh server per arm and runs them back to back
      confounds arm POSITION with arm SETTING. `energy-four-sets.py` already
      does this; the drafter sweeps did not until 2026-08-28.
    - **A single-figure throughput claim is a point drawn from a band.**
      Publish the level a reader will usually see, not the best one observed:
      the figure this campaign advertised for these flags, 86.91 t/s, was
      reached in 3 of 23 attempts, and rule 2 says no reader may measure less
      than the report promised.
    - **Record what the card was doing before the probe started**, alongside
      the build, the driver and the cap. `scripts/bench/provenance.py` records
      the rest; prior state is the field this rule adds to the list of things
      an artefact must carry.

---

## PROPOSED — drafted 2026-09-01, not yet law

Two amendments this campaign earned. They are written in the numbered style so
they can be adopted verbatim, and kept separate from the ratified rules above
because **rule numbers are stable and are never reused or renumbered**, so a
number must not be spent on a draft. Adopting rule 32 also costs one line of
`AGENTS.md`, which sits at its 120-line cap; the line to remove is the adopter's
call, not the drafter's.

32. **Speculation is not a free axis — prove the tokens are identical, or
    publish that they are not.** Lossless rejection sampling is a property of an
    implementation, not a guarantee of every implementation, and this repository
    has now measured a build where it does not hold. Measured 2026-09-01
    (Ornith-1.5-9B, llama.cpp b10717, `--spec-type draft-mtp` against a sibling
    MTP head, temperature 0 / top_k 1, fresh server per run): speculation ON and
    OFF produce **different text**, at Q4_K_M (16,407 chars against 4,100) and at
    **BF16** (9,478 against 8,950). The innocent explanation was ruled out first
    — every configuration was run twice and hashed, and all four are
    bit-reproducible, so this is not numerical nondeterminism. A sweep may
    therefore never report "1.238× faster" alone: it reports 1.238× faster **at
    the same answer, or at a different one**, and which it is comes from hashing
    the response bodies with the axis on and off. `scripts/arms.py` already
    saves them (`--save-responses`) and nothing compares them, which is why a
    campaign caught this by luck rather than by process. The corollary for rule
    11: acceptance and mean draft length describe how fast the axis is, and say
    nothing about whether it changed the output.

33. **Perplexity ranks confidence, not fidelity — a quant ladder is cross-checked
    against KL-divergence or it is not a ranking.** Rule 6 ranks quants by
    perplexity over 294,912 token positions. Measured 2026-09-01 on
    Ornith-1.5-9B, that ranking came out in exactly reverse order of fidelity:

        arm      mean KLD vs BF16   same top-1    PPL      PPL rank
        Q8_0            0.009766      97.998%   9.0519         3rd
        Q4_K_M          0.130086      87.112%   7.9544         1st
        IQ2_M           0.363336      76.740%   8.6629         2nd

    KLD is monotonic in bit-width; perplexity is inverted. Q4_K_M diverges 13.3×
    further from the unquantised weights than Q8_0 while scoring 1.10 PPL
    *better*, and disagrees with BF16's argmax on one position in eight.
    Perplexity asks only what probability the model gave the token that actually
    came next, so a quant whose distribution is differently shaped can score
    better on predictable text while being further from the model it was made
    from — and the same divergence shows up as greedy degeneration, which this
    campaign measured at Q4_K_M and did not measure at BF16. A campaign that
    followed rule 6 to the letter would have crowned the least faithful file in
    its roster and screened out the most faithful one at the Stage-1 gate. The
    tooling already exists (`scripts/quant-ladder/kld-ladder.py`,
    `kld-blocks.py`); what is missing is the requirement. Cheapest sufficient
    form: KLD against the unquantised weights over the same frozen chunks, with
    the highest-bit quant as a control whose KLD must come out near zero.
