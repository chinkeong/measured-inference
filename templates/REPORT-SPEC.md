# REPORT-SPEC — structure of a field-guide report

The output of a campaign is one self-contained HTML page,
`results/<slug>/index.html`. `example-report.html` in this directory is a
complete real instance; match its craft, not its model. (The example predates
this spec's ordering — it carries the same content with the recipes late. Follow
this spec's order, not the example's.)

## Non-negotiables
- Single file, no external assets except Google Fonts; light+dark via CSS
  tokens; wide tables in `overflow-x:auto` wrappers; sticky mono TOC.
- Every number: measured (dated, machine named), cited (inline link), or
  labeled derived. Conditions travel with numbers (METHODOLOGY rule 3).
- A header spec strip with the speed band: floor · real-work band · ceiling.
- **The two-voice writing law below governs every section.**
- **Recipes first**: a reader who wants a working configuration reaches one
  before any evidence chapter; the evidence follows, in causal order.
- A Sources / fact-check trail section listing own-run methodology and every
  external citation.

## The two-voice writing law (non-negotiable)

Every section is written in two voices, in this order, without exception.

**Voice 1 — the surface. It comes first, always.** Every section opens with
plain international English paragraphs: short sentences, common vocabulary, no
metaphor, no idiom, no jargon beyond the terms the "Plain words" box has already
defined. They are written for two readers at once — a non-expert setting up a
machine at home or in a small lab, and a reader whose first language is not
English. These opening paragraphs state the recommendation and justify it in
plain terms: what to do, and why, with the number that decides it. **A reader who
reads only the first paragraph of every section must come away with a complete,
correct, shallow guide** — not a teaser, and not a summary that defers to the
depth below, but a guide they can act on.

**Voice 2 — the depth. It comes below, never above.** The technical material
follows, written for the people who design AI silicon, firmware and serving
software, and for cloud engineers who run models for a living: the arithmetic,
the conditions, the parity declarations, the failure modes, the citations, the
tables. Voice 2 may add precision that Voice 1 left out. **Voice 2 may never
contradict Voice 1.** If the depth changes the answer, the surface was wrong —
rewrite the surface. Never publish a plain paragraph that a later table
undercuts, and never resolve such a conflict with a footnote.

Checkable consequences of the law:
- Plain prose opens every section. No section begins with a table, a chart, a
  command block, or a caveat.
- Terms are defined once, in the "Plain words" box, and used plainly thereafter.
  A term that box does not define does not appear in a Voice-1 paragraph.
- No idioms, no cultural references, no wordplay that assumes English is the
  reader's first language. "Free lunch", "dark horse", "sweet spot", "rule of
  thumb", "punches above its weight" are Voice-2 phrasings at best; in Voice 1,
  write what you mean.
- Numbers in Voice 1 carry their unit and their plain meaning ("about 60 tokens
  per second, which is faster than most people read").
- Every Voice-1 recommendation names the measurement that justifies it in one
  clause. The justification is never deferred to Voice 2.
- The reader-experience review pass reads ONLY the Voice-1 paragraphs, in order,
  and must reach every configuration decision without reading a Voice-2 line.

## Section skeleton (adapt names, keep the arc)

**Front matter — what this is, the words, and the recipes.**

1. **What this page is** — five sentences or fewer, Voice 1 only: which model,
   which machine, which dates, what was measured, and who the page is for. Say
   plainly what it is not (one machine, one model family, measured — not a
   review). The header spec strip (floor · real-work band · ceiling) sits here.
2. **Plain words** — a boxed glossary, defined once for the whole page, one or
   two plain sentences each, with this campaign's own number attached wherever a
   number makes the term concrete. The unavoidable ten:
   **token · context window · VRAM · quantization · KV cache · drafter
   (speculative decoding) · perplexity · effort · prefill and decode · spill.**
   Add a term only if the page cannot be read without it; every later section
   links back to this box instead of re-defining anything. Concept diagrams for
   non-experts earn their place here.
3. **The recipes** — the page's product, at the front. Copy-paste blocks with
   prominent titles; one recipe per card class, except where two measured
   winners split by use (then a plain choosing rule up front, before the
   blocks). Vision flags are printed, not hinted. Each recipe states, in plain
   words above its block: **the file · the context window · the flags · the
   effort levels it offers, and the levels it does not, with their measured
   appetite · the expected speed band with its conditions · the VRAM it uses at
   the top of its window · whether it is safe with a desktop running or needs a
   bare machine.** A measured menu decision table plus the launcher source go in
   a collapsed details block.
   **Energy lives with the recipes unconditionally, to METHODOLOGY rule 24**
   (which defines the metrics — do not restate it): a table explicitly titled
   **"Standardized industry metrics"** carrying, per recipe, the instrumentation
   tier label, mean load W, **J/token (decode) with J/prompt-token (prefill)
   beside it**, tokens/kWh, **EDP (J·s)**, **Wh/answer both gross and
   idle-subtracted** against this machine's dated idle, and an **E_comm** row
   ("N/A — single GPU, no interconnect" on single-accelerator machines,
   measured/split on multi-GPU). If power could not be measured, the columns say
   so rather than being dropped.

**Evidence chapters — in causal order. Each one opens by naming the recipe line
it justifies.**

4. **The facts that decide every setting** — the architecture facts that drive
   the configuration, with per-token KV cost derived on this model's numbers,
   plus the bandwidth arithmetic that predicts decode speed (METHODOLOGY rule
   10). Voice 1 explains, without arithmetic, why a bigger file is a slower file.
5. **The memory map** — the VRAM budget table; the two-ceilings paragraph (fully
   resident vs shallow-safe, plus the collapse point, each scoped to ⟨file +
   drafter on/off + projector on/off + desktop state⟩, rule 13); the drafter's
   and the projector's measured VRAM bills; the desktop-slack rule on this
   model's numbers; the speed-vs-context cliff chart with its measured points;
   and the two-constant arithmetic (fixed bytes + bytes per window token) that
   lets a reader size a window this page never measured.
6. **Speed** — the universal flags that hold on every card, each with its
   measured justification (all-layers `-ngl 99`, load mode, KV quant verified,
   parallel verdict); the zoomed-out band table first; drafting mechanics; the
   tuning sweep as a case study if it flipped a conclusion; the acceptance
   demonstration with **mean draft length beside every acceptance rate** (rule
   11); the one-curve callout; the depth series with its parity declared and its
   clock-ramp discards stated. Every speed carries its token regime (thinking
   tokens vs answer tokens).
7. **Other hardware** — wall-clock for the reference run per card class,
   derived rows condition-labeled (RAM channels!), measured rows marked.
   **Minimum card roster** (RULE — any report that scales measured decode to
   other hardware must cover ALL of these, marking each row measured or
   derived-by-bandwidth):
   - NVIDIA: 24–32 GB class (3090 / 4090 / 5090), 16 GB class
     (5080 / 4080 / 4070 Ti S / 5060 Ti), 12 GB class (3060 / 5070)
   - DGX Spark (GB10, 128 GB unified, 273 GB/s)
   - Intel Arc Pro B70 (32 GB, 608 GB/s) and Arc Pro B50 (16 GB, 224 GB/s)
   - Intel Arc B390-class iGPU (Core Ultra): shared memory ≤96 GB,
     153.6 GB/s — stated as "(LPDDR5X-9600, 2ch)" with the single-channel /
     slower-RAM halving caveat attached
   Verify each roster card's bandwidth/VRAM against current online sources at
   campaign time (specs drift; the figures above are the reference campaign's
   fact-checked values). Cards the machine cannot represent stay derived rows —
   never dropped.
8. **Which file** — the quant table with the settled pick and its evidence; the
   perplexity ranking table; scored accuracy framed as the smoke test it is;
   files screened out before full treatment listed as **screened out**, with the
   two numbers that screened them, so no reader mistakes a pruned file for an
   untested one; the challenger callout if a cheaper file won (Voice 1 says "the
   smaller file scored better"; the "dark horse" framing is Voice 2 at best).
   **When the campaign measures a size ladder** (how small can this model's
   file get and still work): the PPL-vs-GiB curve with its knee named; a
   right-hand anchor where the answer is clearly "no"; detector verdicts
   beside the curve (perplexity ranks, detectors disqualify — repetition,
   format collapse, template sanity); and, where an equal-budget competitor
   model exists at a rung's size, the fixed-size comparison row — judged by
   bits-per-byte and scored benchmarks, never raw cross-model PPL
   (METHODOLOGY rule 6).
9. **Effort and energy** (if the model has an effort knob) — cost table
   (tokens/wall per level, 2 runs); blind-judged quality, with ties reported as
   ties and the within-level spread beside each mean; accuracy per level with
   cap annotations; **the window-sets-the-ceiling table** — measured thinking
   appetite per level against each recipe's window, with levels no recipe can
   hold listed **"not offered"** beside their measured appetite, never as a
   truncated score; **energy per effort level**, carrying the same METHODOLOGY
   rule-24 metrics as the recipes table (tier label, Wh/answer gross AND
   idle-subtracted, J/token, tokens/kWh); and the **per-axis J/token table**
   (quant, drafter, KV dtype, parallel, depth, effort, regime, power cap), every
   row measured or marked "not measured", linked from the recipes chapter. The
   guidance table — which level to use for which kind of work — closes the
   chapter in Voice 1.
10. **Vision** (if applicable) — the proven loop with numbers, resolution/token
    budgets, serving+capture commands, harness rules. An unmeasured loop is
    reported as unmeasured, never as a pass.
11. **Agents, measured** — the agent-attach matrix with its PASS / FAIL-honest /
    FAIL-hallucinated verdicts (hallucinated "sight" flagged loudly), and the
    end-to-end verdict per agent against the served recipe.
12. **Benchmark sample size** — the statistics teaching section (CI worked
    example, gap-vs-n table, right-tool split, the token-budget lesson).
13. **Troubleshooting** — each failure mode with its measured signature, a
    distinguishing table, and the platform-specific diagnostic commands that
    actually work.
14. **Scope perspective** — what this size class is for vs the frontier,
    literature-cited (see example §12 for the citation set and the honest
    kind-vs-degree framing).
15. **Coding agent setups** — verified setups per agent, popularity-ordered,
    exact configs including every capability declaration the tests proved
    necessary.
16. **Sources** — the trail.

## Review gates before "done"
Three fresh-subagent passes: numeric (against the campaign log), structural
(TOC/anchors/tags/encoding), reader-experience (config decision reachable
without contradictions). The reader-experience pass runs the two-voice check
explicitly: read only the first paragraph of every section, in order, and
confirm that alone is a complete, correct guide which no Voice-2 table
contradicts. Apply must-fixes, then ship.
