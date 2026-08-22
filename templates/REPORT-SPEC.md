# REPORT-SPEC — structure of a field-guide report

The output of a campaign is one self-contained HTML page,
`results/<slug>/index.html`. `example-report.html` in this directory is a
complete real instance; match its craft, not its model.

## Non-negotiables
- Single file, no external assets except Google Fonts; light+dark via CSS
  tokens; wide tables in `overflow-x:auto` wrappers; sticky mono TOC.
- Every number: measured (dated, machine named), cited (inline link), or
  labeled derived. Conditions travel with numbers (METHODOLOGY rule 3).
- A header spec strip with the speed band: floor · real-work band · ceiling.
- A Sources / fact-check trail section listing own-run methodology and every
  external citation.

## Section skeleton (adapt names, keep the arc)
1. **The model, in N facts that drive every setting** — architecture facts with
   per-token KV cost derived; concept diagrams for non-experts where they earn
   their place.
2. **The physics** — bandwidth formula; the speed-vs-context cliff chart with
   measured points; the VRAM budget table; the two-ceilings paragraph.
3. **Universal rules** — the flags true on every card, each with its measured
   justification (all-layers, load-mode, KV quant verified, parallel verdict).
4. **Effort** (if applicable) — cost table (tokens/wall per level, 2 runs),
   blind-judged quality, accuracy per level with cap annotations, energy per
   answer *resolved per effort level* (the §8 energy column, split by level),
   the window-sets-the-ceiling table, the guidance table.
5. **Which file** — quant table with the settled pick and evidence; scored
   smoke test framed as a smoke test; perplexity ranking table; the dark-horse
   callout if a challenger emerged.
6. **Speculative decoding** — the zoomed-out band table first; drafting
   mechanics; the tuning sweep as case study if it flipped; the acceptance
   demonstration; the one-curve callout.
7. **Hardware matrix** — wall-clock for the reference run per card class,
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
8. **Recipes per card class** — copy-paste blocks with prominent titles; one
   recipe per class except where two measured winners split by use (then a
   choosing rule up front); vision flags printed, not hinted; a measured menu
   decision table + the launcher source in a collapsed details block. **Energy
   lives here unconditionally**: the decision table carries a measured
   watts-under-load and kWh-per-answer column per recipe, labeled gross or
   idle-subtracted (Phase 10). If a model has an effort knob, §4 repeats it
   split by level; if power could not be measured, the column says so rather
   than being dropped.
9. **Benchmark sample size** — the statistics teaching section (CI worked
   example, gap-vs-n table, right-tool split, the token-budget lesson).
10. **Troubleshooting** — each failure mode with its measured signature, a
    distinguishing table, and the platform-specific diagnostic commands that
    actually work.
11. **Vision** (if applicable) — the proven loop with numbers, resolution/token
    budgets, serving+capture commands, the agent-attach matrix, harness rules.
12. **Scope perspective** — what this size class is for vs the frontier,
    literature-cited (see example §12 for the citation set and the honest
    kind-vs-degree framing).
13. **Coding agents** — verified setups per agent, popularity-ordered, exact
    configs including every capability declaration the tests proved necessary.
14. **Sources** — the trail.

## Review gates before "done"
Three fresh-subagent passes: numeric (against the campaign log), structural
(TOC/anchors/tags/encoding), reader-experience (config decision reachable
without contradictions). Apply must-fixes, then ship.
