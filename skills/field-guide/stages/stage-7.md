---
name: stage-7
description: Load when executing Stage 7 (PUBLISH + review gates) — build results/<slug>/index.html per REPORT-SPEC, then run the four fresh-subagent review passes (numeric, structural, reader-experience, internal consistency) before calling the campaign done.
---

# Stage 7 — PUBLISH + review gates
Build `results/<slug>/index.html` per `templates/REPORT-SPEC.md`, using
`templates/example-report.html` as the structural exemplar. The Stage-5 recipe
cards are the report's front matter, and REPORT-SPEC's two-voice writing law
governs every section. Then run FOUR review passes with fresh subagents before
calling it done — `templates/REPORT-SPEC.md`, "Review gates before done", is the
contract and Gate 4 is written out there in full:

1. **Numeric** — every figure against the campaign log's canonical numbers,
   including the ones inside embedded artefacts: launcher source, code comments,
   front-matter counts.
2. **Structural** — TOC, anchors, tags, encoding.
3. **Reader-experience** — can a first-time reader reach a confident config
   decision without contradictions? This pass runs the two-voice check
   explicitly: read only the first paragraph of every section, in order, and
   confirm that alone is a complete, correct guide that no Voice-2 table
   contradicts.
4. **Internal consistency** — the report against ITSELF, which the other three
   structurally cannot see: a report can be internally false while every number
   in it is faithfully transcribed. Re-derive every DERIVED number against every
   other measurement in the report that constrains the same quantity; re-derive
   every relation a caption asserts about its own table from that table's cells;
   check that a caveat established in one place travels to every REUSE site;
   check the abstention (a claim the report says it cannot make must not
   reappear later as guidance); check front-matter scope claims against the
   Sources trail; check `id` ↔ displayed number ↔ TOC label ↔ every `§NN` in
   prose.

Apply must-fixes; commit; publish per the interview. Checkpoint commits have
been running since Stage 1; this is the last of them.
