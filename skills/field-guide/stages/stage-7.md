---
name: stage-7
description: Load when executing Stage 7 (PUBLISH + review gates) — build results/<slug>/index.html per REPORT-SPEC, then run the three fresh-subagent review passes (numeric, structural, reader-experience) before calling the campaign done.
---

# Stage 7 — PUBLISH + review gates
Build `results/<slug>/index.html` per `templates/REPORT-SPEC.md`, using
`templates/example-report.html` as the structural exemplar. The Stage-5 recipe
cards are the report's front matter, and REPORT-SPEC's two-voice writing law
governs every section. Then run THREE review passes with fresh subagents before
calling it done: numeric consistency (against the campaign log's canonical
numbers), structural (TOC/anchors/tags), and reader-experience (can a first-time
reader reach a confident config decision without contradictions?). Apply
must-fixes; commit; publish per the interview. Checkpoint commits have been
running since Stage 1; this is the last of them.
