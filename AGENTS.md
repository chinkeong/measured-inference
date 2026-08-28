# measured-inference — TIER-0 ROUTER

You are a coding agent on a possibly-borrowed machine. This repo turns a new
local LLM into a published, fully-measured field guide, autonomously. The prime
directive, from the person you work for: **no reader may ever measure less than
the report promised them.** Read this file always; read anything else only when
the situation below triggers it.

## THE INVARIANTS

`methodology/METHODOLOGY.md`'s 30 rules, one line each, plus the interview rule
— enough to know WHEN a decision is governed. Open the rule before acting on it.

1. Measured, cited, or labeled-derived — there is no fourth category [1]
2. No reader measures less than promised; a best case ships labeled as one, with the condition that produced it [2]
3. A number without its conditions is unfalsifiable — regime, depth, cap, acceptance, desktop state and RAM channels travel with it [3]
4. Two independent cheap metrics agreeing beat one expensive metric [4]
5. When a claim dies, keep it as a dated case study — how it misled is worth more than the number was [5]
6. Accuracy at n≤25 is a smoke test (~20-pt collapses only); quants are ranked by perplexity over 294,912 token positions [6]
7. Cap above the appetite distribution's upper tail, not its median; report truncations; on truncation raise the cap and rerun that arm only — never filter to non-truncating questions [7]
8. Small-n judging (n=2): blind judges, spec checklists, ties allowed, variance beside means — categorical findings are real, point differences are not [8]
9. Overthinking is real: a lower score at higher effort on easy tasks is a statistical tie until proven otherwise [9]
10. Decode ≈ GB/s ÷ file GB × 0.7, the constant re-derived per format; any scaling to other cards covers REPORT-SPEC §7's full roster [10]
11. Acceptance IS the speculative speedup, but MEAN DRAFT LENGTH is the throughput predictor — publish both, always [11]
12. Depth costs; a depth series declares its parity; discard the first post-prefill probe — ramping clocks read up to 45% low [12]
13. Two ceilings (fully resident, shallow-safe) plus the collapse point, scoped to ⟨file+drafter+projector+desktop⟩; drafter VRAM is an on/off pair; no window is labeled without a deep-fill probe near its top [13]
14. Slack is the anti-spill budget — ~1 GiB does not survive a desktop; ship desktop-safe defaults and fence bare-desktop configs loudly [14]
15. The -ngl off-by-one: the output projection counts as layer n+1 — always `-ngl 99` [15]
16. The window sets the effort ceiling: a level whose appetite exceeds the window does not degrade, it truncates [16]
17. Effort buys completeness, not easy-task accuracy [17]
18. Image cost is resolution, not file size [18]
19. Agents drop images silently unless capability is declared; hallucinated "sight" is the worst outcome and is hunted explicitly [19]
20. Detach, resumable, parse-check, checkpoint-commit, one GPU job at a time, a campaign log that survives restarts; spot-read long greedy output for repetition loops before trusting its tokens or timings [20]
21. Every effort sweep runs the identical 7-benchmark suite (SEED=42, N=25, 16,384 cap, `-c` above longest prompt + cap); the Mean is a composite index, one cell is a smoke test [21]
22. The agentic bucket is optional and cost-gated: project the sweep from one task; past ~4 h, cite the published anchor and say so [22]
23. Frozen inputs, offline-first: frozen file → local cache → network; two reports compare only if their suite hashes match [23]
24. Every watt carries its instrumentation tier and every joule its phase; energy is measured or it is absent — TDP is not a measurement [24]
25. Cheap probes buy the map; the map locks the recipes; only locked recipes earn expensive hours — no expensive run before the written RECIPE LOCK [25]
26. Publish the noise floor ONCE, page-wide, with the class of claim that survives it; printed precision respects the band, and the report's one reproduction check carries a PASS BAND derived from it [26]
27. Questions to the user happen at Stage 0 ONLY; after the interview closes the campaign is autonomous to the end — mid-run uncertainty resolves interview-record → measured default → record-the-assumption-and-proceed, never by stopping to ask [interview rule]
28. The RUN is the scarce thing, not the sampling — widening a query already being issued costs nothing, and a field not written down during the run cannot be recovered at any price [28]
29. An ignore rule is a claim about re-creatability and it has to be true — ignore by EXTENSION or by a directory of pure bulk, never by a directory of mixed content [29]
30. Throughput on this rig has two levels ~13% apart and nothing recorded predicts which — compare arms INSIDE one sweep, alternate arm order, publish the level a reader usually gets, and never name a cause (seven candidates tested, all eliminated) [30]

Three failures no rule number catches:
- Separate "the effect is real" from "the explanation is right" — independent claims, judged separately (81.7 t/s was a real number with a wrong story; the "debunked" verdict was wrong too).
- Your framework is your biggest blind spot: blind-verify your highest-confidence claims (a framework-free rerun killed "no VRAM cost" in one night, after framework-holding review passes had missed it).
- Before publishing any report section, review verdict or user-facing conclusion, run `methodology/REASONING.md`'s pre-output self-check.

## ROUTING TABLE

| Situation | Read this — and only this |
|---|---|
| starting or resuming a campaign | `skills/field-guide/SKILL.md`, then ONLY your current stage file |
| executing Stage N | `skills/field-guide/stages/stage-N.md` — never load another stage |
| writing, reviewing or publishing report sections | `templates/REPORT-SPEC.md` + `methodology/REASONING.md` |
| actually writing the prose — who writes it, how it is briefed and checked | `methodology/WRITING.md` |
| adjudicating conflicts, criticizing prior work, blind judging | `methodology/REASONING.md` |
| a probe or a number looks wrong | grep `reference/failure-library.md` for the symptom |
| platform trouble (PowerShell 5.1, POSIX, WSL) | grep `reference/platform-notes.md` for the exact error |
| running the benchmark suite | `scripts/bench/README.md` + rule 21 |
| power / energy work | `scripts/power/README.md` + rule 24 |
| the agentic bucket | `agentic/setup-log.md` + rule 22 |
| the full text of any invariant above | `methodology/METHODOLOGY.md`, rule N |

A new skill registers ONE line here. Not a section.

## RESUMING A CRASHED CAMPAIGN

Sessions die; campaigns do not have to. **Before starting anything, list
`results/*/campaign.md`.** If one exists and its last entry is not "Stage 7
complete / published" (older logs: "Phase 11 complete / published"), you are
resuming, not starting — do NOT re-interview.

1. Read `results/<slug>/campaign.md` end-to-end: interview answers, every
   finding so far, and the stage it died in. A log written under the old
   Phase 0–11 numbering is still resumable — SKILL.md's "Old numbering →
   stages" table maps every phase onto the stage that owns that work now.
2. Compare against `git log --oneline`: each completed stage left a checkpoint
   commit, the highest one is ground truth, and anything `campaign.md` claims
   past it was in flight when the session died.
3. Re-run the current stage's script — every long script skips work whose log
   already shows a final result, so a re-run costs only the unfinished arms.
   Confirm the GPU is idle first (a detached llama-server may have outlived the
   session — kill it).
4. Append a dated "resumed after session loss" line to `campaign.md`, noting any
   old-phase → stage mapping you used, then continue from there.
5. **Resuming into expensive work? Check the RECIPE LOCK first.** No dated
   RECIPE LOCK section in `campaign.md` means Stage 5 never ran: go back and
   write it before spending hours (rule 25).

## LAYOUT

```
skills/field-guide/SKILL.md  campaign map + the Stage 0 interview (start here)
skills/field-guide/stages/   stage-0..7.md — load exactly one
methodology/                 METHODOLOGY.md (the law) · REASONING.md (how to think)
templates/                   REPORT-SPEC.md + example-report.html (worked example)
reference/                   platform-notes.md · failure-library.md — grep, never read whole
scripts/                     reference-3090/ (proven probes) · bench/ · power/ · setup.*
bin/ models/                 gitignored: runtimes and weights live here
results/<slug>/              campaign.md · work/ · data/ · the final index.html
```
`<slug>` = the model repo name, lowercased, as a **single path component** (no
slashes), `-GGUF`/`-gguf` dropped: `.../unsloth/SomeNew-32B-GGUF` →
`somenew-32b`. Pick it once in Stage 0, write it into `campaign.md`, and reuse
it verbatim after any restart.

## THE CONTEXT BUDGET RULE

- This file is capped at **120 lines**. To add a line, remove a line.
- Learnings go to `reference/`, keyed by the symptom an agent would grep for —
  never here.
- When spawning a subagent, **inject the specific rules and numbers it needs
  into its prompt**, plus pointers for the conditional rest. Subagents do not
  excavate the corpus.
