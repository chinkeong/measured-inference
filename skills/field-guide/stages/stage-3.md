---
name: stage-3
description: Load when executing Stage 3 (SPEED SURFACES, ~1 h) — the plan.json capability gate on the drafter work, the drafter/MTP sweep in both token regimes, the acceptance demonstration with mean draft length, and the cooled depth ladder run to the clock-ramp protocol.
---

# Stage 3 — SPEED SURFACES (~1 h)
Product: the speed surface every recipe will quote — floor, real-work band,
ceiling — each labeled with its token regime and its depth. Matched pairs only:
a drafter sweep transfers across quants (rule 11: same optimum, acceptance
within 1.6 pts), but it does NOT transfer across token regimes.

**Read `results/<slug>/plan.json` before launching anything — the drafter work
is capability-gated, and the gate is a file, not a judgement call.** Its
`stages[]` rows name `scripts/arms/spec-sweep.json` and
`scripts/arms/acceptance.json` RUNS or SKIPPED from the Stage-0 profile's
`drafter` field. **SKIPPED means they do not run: the sweep and the acceptance
demonstration are not attempted, and the report states that the model ships no
draft head and no companion draft model** — quoting plan.json's own line, which
says it in those words. It may never read as speculation measured and found
wanting; a silently missing axis is a measured negative to a reader who cannot
see the gate (rule 2). Measured 2026-08-29: `unsloth/Qwen3-1.7B-GGUF` profiles
as `drafter: null` and its plan marks both files SKIPPED, 8 arms not run; the
reference 27B profiles a sibling `MTP/mtp-Qwen3.8-27B-Q4_0.gguf` and runs both.
`depth-series.json` still RUNS on a drafter-less model, with `--spec-type`
dropped rather than swept — say so beside its numbers, because they then
describe a lighter configuration than the reference campaign's and are not
comparable to it (rule 30).

- **Sweep in BOTH token regimes.** Run the matched drafter/MTP sweep twice —
  thinking on and thinking off — and keep both surfaces. The reference campaign
  discovered the 1.69× regime split late, after speeds had been published
  without it; the split belongs here, before any recipe quotes a band.
- Discover drafting options (built-in MTP head? companion draft model?
  DFlash-style heads?). The profile's `drafter` block already answers the first
  two from the header — the sibling file, its bytes, its `arch`, whether it
  matches the target's, and any `others` it found — so start from that and add
  what it cannot see. **Name every mechanism available and mark each measured or
  unmeasured** — an omitted alternative reads as nonexistent.
  Sweep n-max × p-min on a realistic code probe (~10 configs; run: `python
  scripts/arms.py --arms scripts/arms/spec-sweep.json`; the Windows original is
  archived in scripts/reference-3090/). Expect high p-min to win at real
  acceptance rates.
- **Declare the token regime with every speed**: thinking tokens and answer
  tokens decode at different rates under speculation (blind reproduction:
  same file, same depth, 39 vs ~70 t/s across regimes; verbatim-copy answers
  hit 148.7). A t/s number without its regime is a different measurement in
  disguise.
- **The acceptance demonstration**: same flags, novel-code probe vs
  copy-this-text-verbatim probe (run: `python scripts/arms.py --arms
  scripts/arms/acceptance.json`; the Windows original is archived in
  scripts/reference-3090/). The spread IS the speed story; any published
  speedup without its acceptance rate is unfalsifiable.
- **Report mean draft length beside every acceptance rate** (rule 11): the p-min
  gate truncates the draft tree on uncertain tokens, so acceptance can sit
  identical while throughput differs 1.69× (reasoning stream: accept 0.895,
  draft len 2.99, 36.6 t/s; answer stream: accept 0.907, draft len 4.31,
  62.0 t/s — same server, same 91k prompt, same flags). Acceptance explains the
  mechanism; mean draft length predicts the throughput.
- Record four-band strip: floor / short-context work / at-depth (anchored) / ceiling per regime for the report's spec strip
  and for the Stage-5 recipe cards — every band labeled with the regime, depth
  and desktop state that produced it.

**The cooled depth ladder** (run: `python scripts/arms.py --arms
scripts/arms/depth-series.json`; the Windows originals are archived in
scripts/reference-3090/). Fixed probes at increasing prompt depths; report
decode and prefill vs depth with acceptance shown steady (or not). Use server
timings, never wall-clock-including-prefill. Declare the series' parity (drafter
on/off, projector on/off, token regime) — two series with mismatched parity are
different experiments, not one curve; depth-series.json holds two of them, the
ladder and the deep-decode probe, flagged in its own notes, and each arm's
`sweep` field names which, so no absolute t/s crosses between them. **Run it
cooled, to rule 12's clock-ramp protocol**: a probe fired right after a long
prefill reads up to 45% low because the board's clocks are still ramping
(prefill itself may only reach ~65% of settled clocks) — discard the first
post-prefill probe at every rung and time only settled probes, or the ladder
measures thermodynamics instead of depth. The runner enforces that discard
rather than the operator's memory: `discard_first` drops the first probe from
the summary and still writes it to the ledger marked discarded. The shipped arms
carry `discard_first false` because that is what produced the published numbers,
so a cooled run sets it true and is a NEW sweep, not a rung-by-rung comparison
against them. Run the ladder on the windows Stage 2 proved safe; a rung above a
proven ceiling measures spill.
