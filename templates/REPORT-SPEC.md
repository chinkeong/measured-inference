# REPORT-SPEC — structure of a field-guide report

The output of a campaign is one self-contained HTML page,
`results/<slug>/index.html`. `example-report.html` in this directory is a
complete real instance; match its craft, not its model. (The example predates
this spec's ordering — it carries the same content with the recipes late. Follow
this spec's order, not the example's.)

**The example is a pinned snapshot.** `example-report.html` records its source
guide's date and commit in its footer. Any campaign that publishes a correction
to that source must re-cut the example or explicitly re-pin it, in the SAME
commit. A worked example may never teach a claim its own source has retracted —
and a correction that lives only in the source is a correction the next campaign
copies its way around.

## Non-negotiables
- Single file, no external assets except Google Fonts; light+dark via CSS
  tokens; wide tables in `overflow-x:auto` wrappers; sticky mono TOC.
- Every number: measured (dated, machine named), cited (inline link), or
  labeled derived. Conditions travel with numbers (METHODOLOGY rule 3).
- **Provenance chips, rendered at the number.** MEASURED / DERIVED / CITED is
  a visible per-number tag on the number or the cell — not a sentence covering
  a paragraph — with one page-level sentence stating that those three labels
  are the whole contract and nothing on the page is a fourth thing. `n=1`
  prints beside every single-sample figure.
- Where a published block, row, or cell differs in ANY field from the command
  or load actually measured (port, `-c`, effort level, build, drafter state),
  the difference is named per cell with the argument for its immateriality.
  Say it rather than let the block imply it was copy-pasted from the run.
- A header spec strip with FOUR bands, each with its condition in parentheses:
  **floor · short-context work · at-depth work (naming the depth that anchors
  it) · ceiling.** Three bands hide the number an agent user actually gets.
- **No load-bearing claim lives only in the marginalia.** Anything the report's
  frame depends on — the blinding declaration, a scope limit, a caveat — has a
  home in the main column, because the margin is hidden on narrow screens.
  Marginalia anchor in document flow, never by hard-coded pixel offsets.
- **"Publish and disclaim" is banned.** A number the report tells the reader
  not to use for its stated purpose is removed or replaced, not annotated: the
  disclaimed number is still the most quotable one on the page.
- **The title states directly what the document is.** The H1 and the browser
  `<title>` name the model, the hardware, and what the reader gets — e.g. the
  shape "⟨Model⟩ on a 24 GB RTX 3090: the measured settings" — never a
  slogan, a metaphor, or a pledge. A pledge or tagline may follow as a
  sub-line under the title, never as the title. The same rule governs every
  section heading and TOC label: a heading tells the reader in plain words
  what the section contains or the question it answers ("Which file should I
  download?"), and Voice 1 applies to headings first of all — a reader
  scanning only the TOC must already know what the document covers.
- The front matter declares the **evidence tier before the first number** —
  hours measured, arms run, what is smoke and what is solid, and the count of
  the report's own self-corrections.
- Every vendor-quoted file size states its **GB↔GiB conversion**: download
  pages are decimal, budgets are binary, and the ~7% gap lands inside the slack
  fence (reference: a 17.6 GB file is 16.39 GiB resident).
- **The two-voice writing law below governs every section.**
- **Recipes first**: a reader who wants a working configuration reaches one
  before any evidence chapter; the evidence follows, in causal order.
- A Sources / fact-check trail section listing own-run methodology and every
  external citation.
- **A report is stale the moment its campaign outlives it.** Every commit
  that adds results to a campaign re-runs the self-reference check on the
  published page: negations ("no X was run"), counts, dates, and scope
  claims are re-verified against the log before the push. A standing "not
  measured" claim lives ONLY in the negative-results register — the one
  place that is maintained; prose elsewhere points at the register instead
  of asserting a negation that later work will silently falsify (reference:
  one post-publication day produced 17 now-false negations on the blind
  report, including a callout that named the exact protocol that then ran).

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

## Figures, charts and configuration tables

- **Every figure carries an `aria-label` that states the FINDING in sentences,
  with its numbers** — a readable data table in prose, not a description of the
  chart's shape — plus a `figcaption` naming the measurement's date and
  conditions. A chart whose alt text describes a shape does not ship.
- **The measured/derived distinction is encoded VISUALLY in every chart**, not
  only in the table beside it: measured points are marked, interpolated or
  cross-run spans are dashed, derived bars are visually distinct from measured
  ones. A polyline drawn through three sampled points reads as a continuous
  measurement unless the points are marked.
- **Any table whose rows are configurations makes each row's exact command
  reachable from the row itself** — a `title`, a details block, an anchor —
  never only from the recipes chapter.

## Section skeleton (adapt names, keep the arc)

**Front matter — what this is, the words, and the recipes.**

1. **What this page is** — five sentences or fewer, Voice 1 only: which model,
   which machine, which dates, what was measured, and who the page is for. Say
   plainly what it is not (one machine, one model family, measured — not a
   review). The evidence-tier declaration comes before the first number, and
   the four-band header spec strip (floor · short-context work · at-depth work,
   with its anchoring depth · ceiling) sits here.
2. **Plain words** — a boxed glossary, defined once for the whole page, one or
   two plain sentences each, with this campaign's own number attached wherever a
   number makes the term concrete. The unavoidable eleven:
   **token · context window · VRAM · quantization · KV cache · drafter
   (speculative decoding) · perplexity · effort · prefill and decode · spill ·
   percentage point vs percent** — the last defined as an absolute unit against
   the relative "percent better", with THIS report's per-question point value
   at its own n ("at n=25 each question is worth 4 points").
   Add a term only if the page cannot be read without it; every later section
   links back to this box instead of re-defining anything. Concept diagrams for
   non-experts earn their place here.
3. **The recipes** — the page's product, at the front. Copy-paste blocks with
   prominent titles; one recipe per card class, except where two measured
   winners split by use (then a plain choosing rule up front, before the
   blocks). Vision flags are printed, not hinted. Each recipe states, in plain
   words above its block: **the file · the context window · the flags · the
   effort levels it offers, and the levels it does not, with their measured
   appetite and the binding constraint that excludes each (window or
   wall-clock — the two have different fixes) · the expected speed band with
   its conditions · the VRAM it uses at the top of its window · whether it is
   safe with a desktop running or needs a bare machine.** A measured menu
   decision table plus the launcher source go in a collapsed details block.
   Also required, per recipe:
   - **The choosing rule is repeated INSIDE each copy-paste block**, and it
     points both ways ("choose A when …; choose B below for more context").
     Copy-paste blocks travel out of the page and leave the surrounding prose
     behind.
   - **The flags deliberately omitted, each with the measurement that would
     justify adding it** ("no drafter flags here on purpose: speculation is
     unmeasured on the CPU-offload path"), so an absence reads as a decision
     rather than an oversight.
   - **A recipe's quoted speed is measured with the recipe's OWN flags**,
     including the effort level the recipe sets. A figure taken at other flags
     is labeled a cross-reference, not the recipe's speed.
   - **The invalidation trigger**: what change — llama.cpp build, driver, a new
     quant, a firmware update — obliges re-measuring this recommendation.
   - **The launcher is unattended-safe**: a timed default or a positional
     selector, so a restart script never blocks on a human; and every
     configuration in it carries its justifying measurement as a comment,
     because the launcher travels to other machines without the report.
   - **The menu decision table keeps its losers**, each with a one-line reason
     ("measured worse than plain Q4_K_M, PPL +1.8% — skip"), so an option the
     reader has already heard of is answered rather than absent.
   - **Client configs printed beside a multi-option menu are parameterized on
     the chosen row**, or they print the arithmetic that derives every number
     from `-c`. A hardcoded `122880` beside a menu offering three windows is
     wrong for two of them.
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
   tokens vs answer tokens). **Where a common wrong measurement produces a
   plausible number, publish it beside the correct one as a recognition aid** —
   a `naive tok÷wall` column next to decode speed, so a reader who computed
   9.2 t/s where decode is 47.1 recognizes their own arithmetic instead of
   their hardware. And **a column headed "the measurement" contains only
   measurements**: structural flags ("not separately benchmarked", "structural,
   not benchmarked") go in a separate table or an explicitly marked column, or
   the column head is a promise three of its rows break.
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
   chapter in Voice 1. **The generative probe set must include at least one
   read-then-edit or repair task against existing code**: greenfield
   single-file tasks (the aquarium, HumanEval, MBPP) do not represent the
   agentic use both this spec and rule 21 recommend the model for, and a
   quality verdict drawn only from them is scoped to work nobody does.
10. **Vision** (if applicable) — the proven loop with numbers, resolution/token
    budgets, serving+capture commands, harness rules. An unmeasured loop is
    reported as unmeasured, never as a pass. **An image-token budget knob
    ships with a measured quality consequence** — the same image at two
    budgets, asked a question whose answer depends on the detail — or it ships
    labeled as an unverified default; "min for grounding, max for detail" is a
    mechanism, not a measurement. **A perception or critique-loop claim
    requires a withheld-image control** (does the model answer as well without
    seeing it?); a report lacking that control names it as the missing control
    and does not call the result a critique loop.
11. **Agents, measured** — the agent-attach matrix with its PASS / FAIL-honest /
    FAIL-hallucinated verdicts (hallucinated "sight" flagged loudly), and the
    end-to-end verdict per agent against the served recipe.
12. **Benchmark sample size** — the statistics teaching section (CI worked
    example, gap-vs-n table, right-tool split, the token-budget lesson). The
    gap-vs-n table carries a **price column on THIS machine** — wall-clock and
    Wh per row — so escalating from a smoke test to n=200 is a budget decision
    a reader can make, not an aspiration the section leaves hanging.
13. **Troubleshooting** — each failure mode with its measured signature, a
    distinguishing table, and the platform-specific diagnostic commands that
    actually work. **Each signature publishes the HEALTHY-state reading of the
    same signal** ("50–70% CPU during perfectly healthy all-GPU decode is
    normal"), plus any log line that LOOKS like the failure and is not
    ("`failed to fit params to free device memory` only means an explicit
    `-ngl` overrode the automatic fit — any value triggers it, `-ngl 99`
    included"). **Client-contract failures are their own class** — one shared
    token pool, client-side cut-offs, no seamless resume, timeouts,
    `max_tokens` sizing — stated together and up front, because the reader's
    fix for every one of them is in a different file from the server command.
14. **Scope perspective** — what this size class is for vs the frontier,
    literature-cited (see example §12 for the citation set and the honest
    kind-vs-degree framing).
15. **Coding agent setups** — verified setups per agent, popularity-ordered,
    exact configs including every capability declaration the tests proved
    necessary.
16. **Sources** — the trail, in three parts. **Per-instrument register**:
    which counter, field, or tool produced each class of number (server
    `timings`, NVML board power, `nvidia-smi` dedicated VRAM, the scorer),
    because a reader who distrusts one number needs to know what read it.
    **Graded external citations** (METHODOLOGY rule 1b: primary-document-linked
    / arithmetic-on-published-specs / carried-from-a-dated-prior-fact-check).
    And a **negative-results register** — "what was not measured", stated
    plainly so nobody mistakes an omission for a result — carrying, per gap:
    why it is missing, the exact measurement that closes it, and its price in
    machine time ("a perplexity run on a second file under these conditions:
    one evening"). Closed items stay in the list, marked closed.

## Review gates before "done"
Four fresh-subagent passes: numeric (against the campaign log), structural
(TOC/anchors/tags/encoding), reader-experience (config decision reachable
without contradictions), and internal consistency (the report against itself).
The reader-experience pass runs the two-voice check explicitly: read only the
first paragraph of every section, in order, and confirm that alone is a
complete, correct guide which no Voice-2 table contradicts. Apply must-fixes,
then ship.

**Gate 4 — internal consistency.** The other three check the report against the
log, the markup, and the reader. This one checks the report against itself,
because a report can be internally false while every number in it is faithfully
transcribed:
- Every DERIVED number is checked against every other measurement in the report
  that constrains the same quantity (a multi-image token count that
  arithmetically falsifies the vision table fifteen lines above it must be
  caught here, not a day later).
- Every relation a caption asserts ABOUT its own table — a constant, a ratio, a
  span — is re-derived from that table's cells ("a constant 1,162 MiB across
  all nine rows" was true for five of them).
- **Caveats propagate to every reuse site.** A number caveated where it was
  established carries a pointer to that caveat everywhere it is reused; this
  pass reads reuse sites, not first appearances.
- **The abstention check**: a claim the report declares itself unable to make
  ("no level is crowned") must not reappear later as guidance, a superlative,
  or a recommendation.
- **Front-matter scope claims are checked against the Sources trail** ("nothing
  is carried over from another run" against a table of carried figures), and a
  blinding declaration lists its inheritances beside its exclusions.
- **Embedded artifacts are inside the numeric pass**: launcher source, code
  comments, front-matter counts — not only prose and tables.
- **Anchor id equals displayed section number**, and the gate checks
  id ↔ displayed number ↔ TOC label ↔ every `§NN` in prose. Cross-references
  address sections by number or anchor only; a nickname ("the dark-horse
  callout") never becomes a link target, because it cannot be renamed without
  breaking every reference to it.
