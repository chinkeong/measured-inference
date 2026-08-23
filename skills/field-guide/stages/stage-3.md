---
name: stage-3
description: Load when executing Stage 3 (SPEED SURFACES, ~1 h) — the drafter/MTP sweep in both token regimes, the acceptance demonstration with mean draft length, and the cooled depth ladder run to the clock-ramp protocol.
---

# Stage 3 — SPEED SURFACES (~1 h)
Product: the speed surface every recipe will quote — floor, real-work band,
ceiling — each labeled with its token regime and its depth. Matched pairs only:
a drafter sweep transfers across quants (rule 11: same optimum, acceptance
within 1.6 pts), but it does NOT transfer across token regimes.

- **Sweep in BOTH token regimes.** Run the matched drafter/MTP sweep twice —
  thinking on and thinking off — and keep both surfaces. The reference campaign
  discovered the 1.69× regime split late, after speeds had been published
  without it; the split belongs here, before any recipe quotes a band.
- Discover drafting options (built-in MTP head? companion draft model?
  DFlash-style heads?). **Name every mechanism available and mark each
  measured or unmeasured** — an omitted alternative reads as nonexistent.
  Sweep n-max × p-min on a realistic code probe (~10 configs; reference:
  `spec-sweep.ps1`). Expect high p-min to win at real acceptance rates.
- **Declare the token regime with every speed**: thinking tokens and answer
  tokens decode at different rates under speculation (blind reproduction:
  same file, same depth, 39 vs ~70 t/s across regimes; verbatim-copy answers
  hit 148.7). A t/s number without its regime is a different measurement in
  disguise.
- **The acceptance demonstration**: same flags, novel-code probe vs
  copy-this-text-verbatim probe (reference: `accept-demo.ps1`). The spread IS the
  speed story; any published speedup without its acceptance rate is unfalsifiable.
- **Report mean draft length beside every acceptance rate** (rule 11): the p-min
  gate truncates the draft tree on uncertain tokens, so acceptance can sit
  identical while throughput differs 1.69× (reasoning stream: accept 0.895,
  draft len 2.99, 36.6 t/s; answer stream: accept 0.907, draft len 4.31,
  62.0 t/s — same server, same 91k prompt, same flags). Acceptance explains the
  mechanism; mean draft length predicts the throughput.
- Record floor / real-work band / ceiling per regime for the report's spec strip
  and for the Stage-5 recipe cards — every band labeled with the regime, depth
  and desktop state that produced it.

**The cooled depth ladder** (reference: `nuance-suite.ps1` part 1,
`deep-decode-probe.ps1`). Fixed probes at increasing prompt depths; report decode
and prefill vs depth with acceptance shown steady (or not). Use server timings,
never wall-clock-including-prefill. Declare the series' parity (drafter on/off,
projector on/off, token regime) — two series with mismatched parity are different
experiments, not one curve. **Run it cooled, to rule 12's clock-ramp protocol**:
a probe fired right after a long prefill reads up to 45% low because the board's
clocks are still ramping (prefill itself may only reach ~65% of settled clocks) —
discard the first post-prefill probe at every rung and time only settled probes,
or the ladder measures thermodynamics instead of depth. Run the ladder on the
windows Stage 2 proved safe; a rung above a proven ceiling measures spill.
