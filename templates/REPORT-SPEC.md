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
   answer, the window-sets-the-ceiling table, the guidance table.
5. **Which file** — quant table with the settled pick and evidence; scored
   smoke test framed as a smoke test; perplexity ranking table; the dark-horse
   callout if a challenger emerged.
6. **Speculative decoding** — the zoomed-out band table first; drafting
   mechanics; the tuning sweep as case study if it flipped; the acceptance
   demonstration; the one-curve callout.
7. **Hardware matrix** — wall-clock for the reference run per card class,
   derived rows condition-labeled (RAM channels!), measured rows marked.
8. **Recipes per card class** — copy-paste blocks with prominent titles; one
   recipe per class except where two measured winners split by use (then a
   choosing rule up front); vision flags printed, not hinted; a measured menu
   decision table + the launcher source in a collapsed details block.
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
