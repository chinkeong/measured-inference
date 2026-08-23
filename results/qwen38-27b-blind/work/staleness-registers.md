# Staleness registers (2026-08-23 sweep) - INPUT TO THE GEN-2 REWRITE
Every item below is a claim invalidated by work that postdates its writing.
Apply during the Gen-2 pass; the front-matter item is already user-directed.

ummary": "Hunt claims invalidated by later campaign work in blind report and guide

---

ary": "Hunt claims invalidated by later campaign work in blind report and guide

---

mary": "Hunt claims invalidated by later campaign work in blind report and guide",
  "agentCount": 3,
  "logs": [],
  "result": {
    "neg": "# NEGATION REGISTER — `E:\AI\measured-inference\results\qwen38-27b-blind\index.html`

**Integration status confirmed by grep:** the file contains **zero** occurrences of `rule-21`, `82.1`, `MBPP`, `HumanEval`, `MATH-500`, `MeetingBank`, `composite`, `tokens/kWh`, `EDP`, `29.9 W`, `Q4_K_M` (except one rhetorical mention at L1857), `nvfp4`, or `parallel 2`. Events **2, 3, 4 and 5 are wholly unintegrated**; events 1 (projector/q4_0/repetition) and the DeepSWE skip line are integrated and are excluded below except where a *different* sentence still contradicts them.

---

## NOW-FALSE (17)

### N1 — L2352–2353, §14.03 negative-results register
> "**Benchmark accuracy.** No GSM8K, no MMLU, no coding benchmark, at any n. See §09 for why a small one would have been worse than none."

**NOW-FALSE.** Rule-21 live sweep ran GSM8K, MATH-500, HumanEval, MBPP and MeetingBank at n=25 × 3 efforts — 175 prompts/arm, 525 generations, 8.48 GPU-h. Per-benchmark at the 32k cap: GSM8K 100/100/100, MATH-500 92/100/92, HumanEval 100/96/84, MBPP 92/84/88, MeetingBank ROUGE-L 22.6/22.4/22.3.
**Fix:** "Benchmark accuracy per effort level — measured (rule-21, n=25 × 5 scored sets × 3 efforts). Still unmeasured: MMLU, any quant-vs-quant accuracy, and the two judge-gated sets."

### N2 — L1855, §09 section heading
> "Why this page publishes **no accuracy score at all**."

**NOW-FALSE.** The page now has scores; what it does not have is a *per-cell* ranking.
**Fix:** retitle "Why a 25-question cell is a smoke test, not a ranking" — the ±16-pt arithmetic below it survives intact and is exactly what licenses the composite-over-125-samples reading.

### N3 — L1148–1159, §04 callout (label + body)
> label: "**Accuracy per effort level: not measured**"
> body: "The methodology asks for a scored benchmark at each effort level, with a token cap high enough that no arm truncates and a truncation count reported beside every score. **That was not run** — see §09 for why a small-n substitute would have been worse than nothing."

**NOW-FALSE, and the most load-bearing miss on the page** — it names the exact protocol that then ran, cap discipline included (16,384 → 32,768 rerun, truncations 1/2/9 → 0/0/3).
**Fix:** replace with the result: 81.3/80.5/77.3 at the 16k cap reverses to **82.1/80.5/81.3** at 32k — within 1.6 pts, indistinguishable at n=25; effort buys wall clock (1.00/1.47/2.70 h), not measurable quality on this suite.

### N4 — L1888–1889, §09 callout "The right tool for the question"
> "…which is why §05 reports perplexity and **stays silent on benchmark accuracy**."

**NOW-FALSE.** **Fix:** "…which is why §05 ranks on perplexity; §04's n=25 suite is reported as a composite index over 5 scored sets, not as an accuracy."

### N5 — L1273 / L1277–1278 / L1305, §05 heading + body + subhead
> L1273: "**One quant was measured, so this section cannot rank quants.**"
> L1277–1278: "This campaign measured one, so **it publishes no ranking and no comparison — not even a hedged one.**"
> L1305: "Why this file, given **no ranking was possible**"

**NOW-FALSE on speed and energy.** M1 measured Q4_K_M head-to-head under byte-identical conditions (7 configs × 2 probes): no-spec 42.97 vs 39.99, peak 93.86 vs **81.71** t/s, acceptance within 1.6 pts at every config, +898 MiB draft step on both. Power matrix C1/C2/C3 measured three quants' energy: **8.198 / 8.853 / 9.293 J/decode-token** (Q4_K_M +7.8 %, NVFP4-HIGH +13.1 % vs IQ4_XS, outside the 2.9 % noise floor).
**Fix:** retitle "Three quants ranked on speed and energy; one on perplexity" — publish the speed/energy ranking, keep the accuracy-ranking refusal.

### N6 — L1313–1316, §05.01 closing
> "…the missing measurement is a perplexity run on a second file under these exact conditions, and it costs one evening."

**PARTIALLY-STALE → prints as false.** The quant ladder is in progress; rig gate 1 already reproduced the 6.5956 anchor **bit-identically**. The PPL arm is queued, not missing.
**Fix:** "…a perplexity run on a second file, now in flight: the ladder's rig gate reproduced this page's 6.5956 anchor bit-identically before the cross-quant rungs."

### N7 — L2350–2351, §14.03
> "**Other quantisations.** One file was measured. There is **no quant ranking** on this page and **there cannot be one**."

**NOW-FALSE** — "there cannot be one" is now contradicted by three measured quant arms. **Fix:** same as N5; scope the refusal to *accuracy* ranking only.

### N8 — L2473–2476, margin sidenote
> "**Why no benchmark score** / Twenty-five questions can detect a broken quant and nothing finer. Running a small benchmark and printing the percentage would have been the most quotable number on this page and the least true one."

**NOW-FALSE as a statement that no score exists.** **Fix:** retitle "Why a per-cell score is a smoke test"; the composite over ~125 scored samples/arm is the interpretable number and it *is* printed.

### N9 — L383–385, "Read this first" callout
> "**One quantisation was measured, so nothing here ranks quants.** No accuracy benchmark was run at all — not a small one, because a small one would be worse than none."

**BOTH CLAUSES NOW-FALSE.** ⚠️ *Verify against the already-caught front-matter item before editing* — this is a separate `<div class="callout warn">` at L381–394, **not** inside `<header class="hero">` (L317–335), so it is likely still live.
**Fix:** "Three quants were measured on speed and energy, one on perplexity. A smoke-tier accuracy suite (n=25 × 5 scored sets × 3 efforts) was run and is reported as a composite index, not an accuracy."

### N10 — L2140–2142, §12 opening
> "This page measured speed, memory, energy and image cost. **It ran no capability benchmark**, so the honest scope statement has to lean on the vendor's own claims and on structure."

**NOW-FALSE.** **Fix:** name the rule-21 suite and its composite, then keep the "not comparable to the vendor's harness" caveat, which still holds (4-bit, different harness, different sampling).

### N11 — L2144–2151, §12 "the one capability observation"
> "**The one capability observation it does have is §04's**… and it is n=2."

**NOW-FALSE.** 525 scored generations across 5 benchmarks now exist. **Fix:** demote this to "the one *generative-deliverable* observation"; lead with the suite.

### N12 — L2357, §14.03
> "**Coding agents. No agent was launched.** §13."

**NOW-FALSE — and self-contradicted on this same page** by §12 L2162–2167, which already documents the DeepSWE-via-Pier pipeline "built and validated end-to-end… one real sandboxed task, 22 LLM calls, 9 m 36 s wall."
**Fix:** "Coding agents. One agentic pipeline (DeepSWE via Pier) was launched and validated end-to-end; the 10-task × 3-effort sweep was skipped on the ~8.5 h cost gate, and the agent-attach **image** matrix was never run. §12, §13."

### N13 — L2210–2214, §13 refusal chapter
> "That phase was **cut for time before any agent was launched**, so this page publishes **no agent configuration, no verdicts, and no 'should work' snippets**. A config that was never run is a guess…"

**NOW-FALSE on two counts.** (a) An agent *was* launched — same contradiction as N12. (b) "no agent configuration" is now avoidable rather than principled: the validation run recorded a *working* config (`--ak model_class=null`, server on port 80 for squid Safe_ports, WSL host 192.168.128.1, `-c 131072` minimum — 65,536 overflowed after 22 calls).
**Fix:** "The **agent-attach image matrix** was cut before any agent was launched. A separate agentic pipeline did run (§12), but it tested plumbing and cost, not image attachment — so this page still publishes no attach verdicts. The one config it can publish is the DeepSWE harness's, and its four traps are in `campaign.md`."

### N14 — L2206, §13 h2
> "**Not measured — and unmeasured means unmeasured.**"

**PARTIALLY-STALE.** True of the attach matrix, false of "coding agents" as a category. **Fix:** "The attach matrix was not measured — and unmeasured means unmeasured."

### N15 — L2502–2503, footer
> "**Nothing else on this page was re-measured**, and the rows it did not touch stand as first published."

**NOW-FALSE.** Three later rounds moved this page's rows: the rule-21 live sweep (accuracy per effort, 8.48 GPU-h), the energy joins E0/E8a (re-integrated §04.03's Wh — reproduced within **0.05 %** — and added J/decode-token, tokens/kWh and EDP), and a 19-arm power matrix (idle, spec, quant, KV, regime, depth, parallel).
**Fix:** replace with a three-line list naming each round and the section it moves.

### N16 — L1744, §08.05 measured-menu table footer
> "Idle, **no server loaded**: **34.6 W** (n=15; 33.2 W measured 83 minutes earlier). Idle with the model loaded and **answering nothing**: **30.2–31.1 W** across all five configurations — **a loaded server costs essentially nothing** until you ask it something."

**NOW-FALSE, and inverted.** Power matrix, settled, quiet desktop: **A1 no-server 29.9 W**, **A2 loaded 34.1 W** — a resident model costs **+4.2 W**, the physically sane ordering. The published pair (loaded *below* no-server) was a cooling board.
**Fix:** "Settled idle, quiet desktop: no server **29.9 W** (A1); model resident and answering nothing **34.1 W** (A2) — **+4.2 W** for a resident model. The campaign-night 33.2/34.6 W readings were taken on a board still cooling."

### N17 — L886–887, §03 universal-flags table, `--parallel 1` row
> "**Not separately benchmarked in this campaign**; the arithmetic is in llama-server's own `n_ctx_slot` line…"

**NOW-FALSE.** Power matrix G1 vs G2, same prompt, drafter off: aggregate **39.16 → 62.77 t/s (+60.3 %)**, **8.585 → 5.189 J/decode-token (−39.6 %)**, EDP −62 %.
**Fix:** keep the window-division arithmetic; add G1/G2 with two caveats the campaign log flags — it was measured **drafter-OFF**, and it contradicts an earlier +11 % aggregate claim, so a matched spec-ON pair is still owed before this ships as general.

---

## STILL-TRUE (checked, no edit needed)

| Line | Claim | Why it survives |
|---|---|---|
| L897 | `--load-mode none` page-cache footprint "**was never measured here**… untested rather than recommended" | No event touches load mode |
| L2383–2385 | §14.03 "System RAM under either load mode… **was not measured**" | Same |
| L779 | "163,840 **was never itself probed at depth**" | Deepest depth arm is 91k (F3); ladder tops out at 90,854 |
| L1353–1359 | "Other drafters exist, and **none of them were tried**… Read their absence as untested, not as a verdict" | DFlash2 still untried |
| L2386–2387 | §14.03 "Any drafter but the built-in MTP head… **out of scope**" | Same |
| L2008–2011, L2354–2356, L2124–2132, L2070–2071 | Vision **critique loop** not measured; "An unmeasured loop is reported as unmeasured, **never as a pass**"; "the test this page tells you to run in §13 is exactly the one **it did not run here**" | No event runs a critique loop or an attach matrix |
| L2051–2053 | `--image-max-tokens 1024` detail cost "**was not measured**" | Untouched |
| L2358–2359 | "**Blind quality judging.** §04's quality note is one judge, not blind, at n=1" | Reinforced — rule-21 ran ALPACA and MT-Bench **unscored** for exactly this reason ("a model must never judge its own outputs") |
| L2360–2362 | "**Other machines.** Every measured row is this RTX 3090" | All events are GAMINGPC/3090 |
| L1574 | "whether `--spec-type draft-mtp` is even available on this backend **was not checked here**" | Untouched |
| L1614, L1644 | "a backend this campaign **never ran**"; drafting multiplier "**measured on exactly one card**" | Untouched |
| L2328 | "hardware this campaign **had no way to check**" | Untouched |
| L960–969, L2363–2368 | q4_0 KV — already integrated; residual "**What remains unmeasured** is… a perplexity pass at `-c 8192` cannot see a retrieval failure at 200k" and the `UNMEASURED HERE` badge | No long-context retrieval test exists |
| L2369–2382 | Repetition audit, "10 of 10 clean" — already integrated | Matches M4 exactly |
| L2175 | DeepSWE "**that delta is the unmeasured part**" | Local sweep still skipped |
| L1450 | "**Neither copy probe ever copied anything.**" | Untouched |
| L2404–2409 | Blinding sidenote, prior results "**never opened**" | Untouched |
| L376–379 | The three-label contract, "Where a phase was skipped for time, the page says the phase was skipped" | True in form — N1–N17 are precisely the holes it promises against |

---

## Adjacent staleness spotted en route (not negations — flagging so they are not lost)

- **L1189, L1760–1761, L2197 — "~344 W" as a constant.** E0.7 measured sustained drafter-off decode drifting **305.5 → 341.1 W (+11.7 %)** at constant throughput, constant 77–79 °C and constant memory clock. "344 W sustained" must become a range (306–341 W drafter-off; 338.6–345.0 drafter-on) or a run's own mean. L2197's flat "sustained **344 W**" in §12's closing proposition callout is the most quotable instance.
- **L882, L941, L1286 — "294,912 token positions" / "36 chunks × 8,192".** The corpus actually tokenizes to **297,193** tokens for Qwen (36 chunks); 294,912 is the nominal `36 × 8,192`, not the count.
- **§04.03 (L1162–1190) is now under-claimed.** E8a reproduces all four published Wh figures within **0.05 %** (they may be cited unhedged) and adds J/decode-token **4.26/5.18/6.60/6.13**, tokens/kWh **845k/695k/545k/587k**, EDP **1.57e7 → 5.52e8 J·s (35×)**, and the mechanism `J/token ≈ mean_W ÷ decode_t/s` with no residual — plus the drafter-off reference **7.884 ± 0.307 J/token (n=115)**, i.e. the drafter roughly **halves** J/token.
- **§04.05 Guidance (L1233–1258)** is built entirely on n=1. Rule-21 at n=175/arm says effort buys wall clock, not measurable quality — the two now sit in tension on the same page.
- **L2169 cites "rule 22"** as the operative gate; the law is now **26 rules + 4 review gates** plus a two-voice/recipes-first spec and a standardized-industry-metrics mandate.
- **§14.01's follow-up bullet (L2273–2284)** describes only the 02:48–04:29 round; it is the natural home for the three later rounds N15 needs.",
    "counts": "# COUNT / DATE / SCOPE REGISTER — `qwen38-27b-blind` index.html + campaign.md

Files audited: `E:\AI\measured-inference\results\qwen38-27b-blind\index.html` (2,533 lines), `E:\AI\measured-inference\results\qwen38-27b-blind\campaign.md` (1,072 lines).
Checked against: campaign.md addenda lines 991–1072, `work\rule21-live.md`, `work\energy-joins.md`, `data\power-matrix\report.txt`, `data\quant-ladder\results.txt`, `data\followup\`, `data\rule21\`.
Hero block (`<header class="hero">`, index.html:317–335) skipped per instruction. The "Read this first" callout (381–394) is a separate element and is included — drop item 8 if your hero catch already covered it.

---

## A. NOW FALSE — the claim is contradicted by a completed post-publication run

**A1. index.html:383** — "**One quantisation was measured, so nothing here ranks quants.**"
Ladder `results.txt` lines 2–8: UD-IQ4_XS PPL **6.5956**, NVFP4-MTP-VERY-LOW PPL **6.8774**, both 36 chunks × 8,192 = 294,912 positions, `RIGPAIR … gap_pct=4.273 | min=2.0 | RESOLVED`. Plus Q4_K_M measured for throughput (M1: 81.71 t/s) and for energy (matrix C2: 8.853 J/dec-tok vs C1 8.198).
**FALSE.** → *Fix:* "Three Qwen quants have now been measured; the resolved perplexity ranking (IQ4_XS 6.5956 < NVFP4 6.8774, +4.27 %) is in the quant-ladder addendum — this section predates it."

**A2. index.html:1273** (§05 `<h2>`) — "**One quant was measured, so this section cannot rank quants.**"
Same evidence. The heading is the load-bearing one; a reader who reads only headings gets the retired claim.
**FALSE.** → *Fix:* retitle "The ranking arrived after publication — §05 as first written, with the ladder result at the top."

**A3. index.html:1277–1278** — "**This campaign measured one, so it publishes no ranking and no comparison — not even a hedged one.**"
The ladder's gap is not hedged, it is `RESOLVED` against a 2.0 pt minimum at identical corpus, `n_ctx`, and `-fa` settings.
**FALSE.** → *Fix:* replace the sentence with the two-row IQ4_XS/NVFP4 table and keep the "as first published" framing for the rest of §05.

**A4. index.html:2350–2351** (§14.03) — "**Other quantisations.** One file was measured. There is no quant ranking on this page and there cannot be one."
"cannot be one" is now affirmatively wrong. Note §14.03 already contains the correct pattern in its q4_0 KV bullet ("measured in the follow-up round, no longer an omission") — this bullet was not given the same treatment.
**FALSE.** → *Fix:* convert to the same "measured after publication, no longer an omission" form, citing 6.5956 / 6.8774 / +4.27 %.

**A5. index.html:2352–2353** (§14.03) — "**Benchmark accuracy.** No GSM8K, no MMLU, no coding benchmark, **at any n.**"
Rule-21 live sweep ran GSM8K, MATH-500, HumanEval, MBPP, MeetingBank at n=25 per benchmark per effort arm (175 prompts, suite hash `1cdf54f8eb9d3f8f`). 32k-cap results: GSM8K 100/100/100, MATH-500 92/100/92, HumanEval 100/96/84, MBPP 92/84/88, MeetingBank 22.6/22.4/22.3.
**FALSE, and it is the page's single most load-bearing stale line.** → *Fix:* "Measured after publication at n=25/benchmark over five scored sets — composite Means 82.1 / 80.5 / 81.3 — still far short of the n §09 shows a quant ranking needs."

**A6. index.html:1150–1152** (§04, "Accuracy per effort level: not measured") — "The methodology asks for a scored benchmark at each effort level, with a token cap high enough that no arm truncates and a truncation count reported beside every score. **That was not run.**"
That is a precise description of what rule-21 then ran, truncation counts included (1/2/9 at 16k; 0/0/3 at 32k), with the rule-7 raised-cap rerun on affected arms only.
**FALSE.** → *Fix:* "That was run after publication — see the rule-21 addendum: all three efforts land within 1.6 points at n=25, i.e. effort bought wall clock, not measurable quality."

**A7. index.html:1855** (§09 `<h2>`) — "**Why this page publishes no accuracy score at all.**"
**FALSE as a present-tense claim.** → *Fix:* "Why the first publication carried no accuracy score — and what the n=25 sweep that followed can and cannot say."

**A8. index.html:2140–2142** (§12) — "This page measured speed, memory, energy and image cost. **It ran no capability benchmark**, so the honest scope statement has to lean on the vendor's own claims and on structure."
Five scored capability sets × 3 effort arms now exist.
**FALSE.** → *Fix:* lead with the measured composite Means and the effort-tie, and reserve the vendor-lean for the agentic axis only.

**A9. index.html:2211** (§13) — "That phase was **cut for time before any agent was launched**" / §14.03:2357 "**Coding agents.** No agent was launched."
campaign.md:991–1001: a DeepSWE-via-Pier pipeline was built and validated end-to-end, one real sandboxed task, 22 LLM calls, 9 m 36 s, 1,014,115 prompt / 21,736 completion tokens, F2P 0/96, P2P 561/561. §12:2162–2180 already says so; §13 and §14.03 were never propagated.
**FALSE (internally contradicted at 2162).** → *Fix:* "One harness was launched and validated on one task; the *sweep* was gated out on cost (~8.5 h vs a ~4 h gate). §12."

**A10. index.html:1760 + 2197 + 1188–1189** — "the multi-minute runs in §04.03 **sustained 344 W**" / "drawing a **sustained 344 W**" / "the board draws the **same ~344 W** whatever it is generating".
`work\energy-joins.md` anomaly (1): sustained board power drifted **305.5 → 341.1 W** at constant throughput, temperature and memory clock, tracking SM clock 1453 → 1606 MHz; the write-up states "'344 W sustained' must become a range (306–341 W drafter-off)". Matrix arm means run 302.4–338.9 W.
**FALSE as a point figure**, and 1188–1189 is the premise of the Wh/1k-token argument. → *Fix:* "306–341 W sustained (drafter off) — the board's own clock drifts at constant throughput, so a single wattage is a snapshot, not a constant."

**A11. index.html:1170 caption + 1744 + campaign.md:814, 953** — "Board idle with no server loaded measured **33.2 W** … and **34.6 W** (n=15) 83 minutes later — **call it 33–35 W**."
Power matrix A1 settled no-server idle = **29.9 W**, explicitly proving the published 33.2 W was a still-cooling board; energy-joins provisional settled idle 31.2 W; matrix report uses `idle W : 31.00`.
**FALSE.** → *Fix:* "Call it ~30 W settled (matrix A1: 29.9 W); the 33–35 W readings were taken before the board had finished cooling."

**A12. index.html:2489–2490** (footer) — "**Measurements ran 2026-08-23, 00:19 to 02:19 local**".
Measurement on this slug continued the same day: follow-up 02:48–04:29; rule-21 arms 04:40–13:19; power log 10:48–13:19; matrix 13:21:49–14:05:20; quant ladder 14:13 onward (`heartbeat.txt` stamped 15:31, still running). Total measurement wall is now well past 12 h, not 2 h.
**FALSE.** → *Fix:* "The first publication's measurements ran 00:19–02:19; measurement continued the same day to 15:30+ across five further rounds — see the dated addenda in `campaign.md`."

**A13. index.html:2495–2503** (footer) — "A follow-up round the same morning (02:48–04:29) closed three of the gaps … **Nothing else on this page was re-measured, and the rows it did not touch stand as first published.**"
Later rounds re-measured published rows: idle power (A11), sustained watts (A10), the MTP optimum (M1 re-swept both quants, n10/p0.5 wins both), the depth ladder (cooled 86.30 / 80.20 / 64.76), and the effort-quality question (rule-21).
**FALSE on both clauses.** → *Fix:* replace with a dated rounds ledger — follow-up, rule-21, energy joins, power matrix, quant ladder — and delete "nothing else was re-measured".

**A14. index.html:2487** (footer, *not* the hero) — "one model, one machine, **one night**".
"one night" fails per A12. "one model" fails too: the ladder's cross-model arm measured **gemma-4-12B-it-QAT-Q4_0** on this rig (PPL 1,159.72, flagged `ppl_comparable=NO-different-tokenizer`).
**FALSE.** → *Fix:* "one model on one machine at first publication; a second model and two further quants were added in later rounds."

**A15. campaign.md:7–8** (header) — "**Every number below was produced on this machine tonight**".
Four dated sections now sit below that line (991, 1003, 1025, 1051) and ran across 08-23 daytime.
**FALSE as written.** → *Fix:* "Every number in the campaign log proper (00:19–02:18) was produced that night; the dated sections after 'The canonical list' are later rounds with their own timestamps."

**A16. campaign.md:35–37** (Deviation 2) — "**Single quant** — no quant ranking is possible or published."
**FALSE.** → *Fix:* append "(superseded 2026-08-23 by the quant ladder — NVFP4 6.8774 vs IQ4_XS 6.5956, gap 4.273 %, RESOLVED)".

**A17. campaign.md:36–37** (Deviation 3) — "Phase 6 accuracy (n=200) skipped — time. … **no accuracy number is published at all** rather than a misleading small-n one."
**FALSE.** → *Fix:* append "(superseded by the rule-21 live sweep: five scored sets at n=25 each, published with truncation counts and the smoke-test caveat attached)".

---

## B. NOW UNDERCOUNTED / SCOPE-STALE — true of round one, wrong about the campaign

**B1. index.html:389–390** — "**It corrected itself four times while running**".
Post-publication corrections add at least seven: the 81.7 t/s "phantom" acquitted as a mislabeled token regime; the 30.61 outlier reattributed to clock ramp; the mechanism swap (mean draft length, not acceptance, predicts speculative throughput — identical acceptance 0.895/0.907, draft len 2.99 vs 4.31, 1.69×); the 16k "quality falls with effort" artifact reversed by the rule-7 rerun; two scorer bugs (MATH-500 low 60→92, GSM8K xhigh 92→100); idle 33.2 W → 29.9 W settled; 344 W → 306–341 W range.
**UNDERCOUNTED (4 → 11+).** → *Fix:* "four times while running, and seven more in the rounds that followed — the running count is in `campaign.md`."

**B2. index.html:721 + 734** — "reproduce **every fully-resident VRAM measurement in this campaign**: **17 server loads**" / "Validated against **every fully-resident load in the campaign** — 17 of them".
"every" is now scoped to round one only; the matrix (19 arms), ladder (4 servers) and follow-up (~20 servers) all loaded configurations that were never fed to the two-constant model.
**SCOPE-STALE superlative.** → *Fix:* "every fully-resident load in the campaign proper — 17 of them; later rounds' loads have not been checked against it."

**B3. index.html:897 + campaign.md:817** — "across **~30 restarts**".
Restart count across all rounds is now well over 60 (19 matrix arms + 6 rule-21 arms + ~20 follow-up servers + ladder servers).
**UNDERCOUNTED.** → *Fix:* "~30 restarts in the campaign proper".

**B4. index.html:2146–2151** (§12) — "this model produced **two** complete, dependency-free, ~1,270-line HTML files in one shot … and it is **n=2**".
The xhigh 120k re-run produced a third complete file (1,180 lines, 25 draw functions, judged best of three) — stated at §04:1130–1136, never propagated to §12.
**UNDERCOUNTED (already internally contradicted).** → *Fix:* "three complete files … n=3", or scope explicitly to "the two judged side by side".

**B5. index.html:1919–1921** — "This page measured 8.0 to 148.7 t/s for the same file on the same card **in one evening** — an 18× spread".
"one evening" fails per A12; and both endpoints are single post-prefill probes now known to carry ±25 % clock-state noise (the page says so at 827–829 but not here).
**SCOPE-STALE.** → *Fix:* "in one campaign", plus "(both endpoints are single probes — see §02's clock-noise band)".

**B6. index.html:1930** — "**Six failures**, each with the signature that identifies it."
Later rounds produced at least four more signature-bearing failures with no home: the partial-window energy join that yields an impossible 5.32 J/token; "server-down ≠ GPU-idle" (plot rendering spiked the idle tail to 121–124 W five times); the suite-file settings block that records sampling the `--greedy` runner overrides; and the 16k-cap truncation artifact that reads as quality falling with effort (11 of 12 truncations returned empty content).
**UNDERCOUNTED.** → *Fix:* add the four rows, or "Six failures, plus four found after publication (see `campaign.md` addenda)".

**B7. index.html:1858** (§09) — "more samples than **a four-hour window** can buy".
Still directionally true but now superseded by measurement: rule-21 spent ~5.2 h of arm wall and still landed three efforts inside 1.6 points at n=25. The measured version is stronger than the arithmetic version currently printed.
**STALE FRAMING.** → *Fix:* cite the live result beside the power arithmetic.

**B8. index.html:1876–1881** (§09 worked example) — "**Suppose** you run 25 GSM8K questions and one quant scores 22/25 (88 %)…"
The supposition has been run: GSM8K returned 100/100/100 — the saturation case the hypothetical does not cover (a ceilinged benchmark discriminates nothing at any n).
**STALE HYPOTHETICAL.** → *Fix:* replace the invented numbers with the measured row and add the saturation lesson.

**B9. index.html:2404–2409** (Blinding sidenote) — "This was run as a reproduction test with the answer key sealed … **every** summary and log from that run were **never opened**."
True of round one. But the ladder now gates against a published anchor as an *expectation* (`RIGGATE UD-IQ4_XS | expected=6.5956 | measured=6.5956 | PASS`), i.e. later rounds are post-blind by construction.
**SCOPE-STALE present tense.** → *Fix:* "The blind held for the campaign of 00:19–02:19; everything after is post-blind and labelled by round."

**B10. campaign.md:72–88** — "**Nine phases were ADDED** that the skill does not list … **Six of the nine** changed a published conclusion."
Later rounds added M1–M4, rule-21, energy joins E0/E8a, the 19-arm power matrix and the quant ladder — and at least four of those changed a published conclusion (A9, A10, A11, the MTP optimum).
**UNDERCOUNTED.** → *Fix:* "Nine in the campaign proper; the later rounds added five more, four of which changed a published conclusion."

**B11. campaign.md:706–708** — "**Three fresh-subagent passes** ran against the draft: structural, reader-experience and numeric."
Accurate for pre-publication; at least three post-publication integration passes have since run (08-23 follow-up integration, the projector/q4_0/repetition update, this one).
**SCOPE-STALE.** → *Fix:* label "three **pre-publication** passes" and open a post-publication pass log.

**B12. campaign.md:26** — "Time budget | SMOKE TIER, **hard cap ~4 h of measurement**" and **campaign.md:795** "**total GPU time** | 00:19 - 02:18 | **1 h 59 min**".
Both are correct records of round one; neither is labelled as such, and the total measurement on this slug now exceeds 12 h.
**SCOPE-STALE.** → *Fix:* label the row "campaign proper" and add a rounds ledger beneath it.

**B13. index.html:382 / 1357 / 2168** — "this is a **smoke-tier campaign**" / "out of scope for a **smoke tier**" / "exceeds the methodology's **~4-hour gate**".
The smoke-tier label still correctly describes round one's *quality* evidence, and the ~4 h gate correctly governed the agentic skip. But with 12 h+ of measurement, five rounds and a resolved quant pair on the board, an unqualified "this is a smoke-tier campaign" now understates the corpus.
**SCOPE-STALE, not false.** → *Fix:* "smoke-tier at first publication; the addenda have since raised the speed/energy/quant evidence above that tier, while the n=1 quality judgements remain smoke-tier."

---

## C. INTERNAL COUNT CONFLICTS (pre-existing, still unfixed)

**C1. campaign.md:762** — "Two constants per configuration reproduce **ten independent server loads**" vs **campaign.md:925** "reproduce **17** fully-resident loads" vs **index.html:721/734** "**17** server loads".
The "ten" is a stale earlier count left standing in the review-pass narrative. → *Fix:* campaign.md:762 → 17.

**C2. campaign.md:760** — "the desktop's own share, across the night | **223 - 1,179 MiB**" vs **campaign.md:934** "**133 - 1,181 MiB**", "26 loads", and index.html:701/855/1688/1744/2490 (all 133–1,181).
campaign.md:760 is the odd one out. → *Fix:* campaign.md:760 → "133 – 1,181 MiB across 26 loads".

**C3. index.html:701 vs 721** — "133 to 1,181 MiB **across 26 loads**" and "**17 server loads**" on the same screen, with no statement that these are different populations (26 total loads; 17 of them fully resident).
Reads as a contradiction to any careful reader. → *Fix:* one clause — "26 loads in total, of which the 17 fully-resident ones feed the budget model."

**C4. index.html:885 (canonical) vs 713** — projector "= **~26,500 tokens** of window" (canonical list, campaign.md:885) vs "**~25,900 tokens**" (campaign.md:271) vs "**~26,500 tokens**" (index 713). Same 1,138 MiB divided by the same 45,056 B/token; campaign.md:271 uses the older divisor.
**MINOR CONFLICT.** → *Fix:* campaign.md:271 → ~26,500.

---

## D. SOURCES / TRAIL COMPLETENESS (§14.01, index.html:2236–2285)

The trail has exactly one post-campaign entry — the follow-up round bullet at 2273–2284. **Four completed rounds and one in-progress round have no trail entry at all**, including the round that supplies the accuracy numbers §14.03 currently says do not exist.

| Round | Trail entry? | Artefacts that exist and are uncited |
|---|---|---|
| Follow-up M1–M4 (02:48–04:29) | **YES** (2273–2284) | — complete, correctly dated |
| **Rule-21 live effort sweep** (04:40–13:19) | **MISSING** | `work\rule21-live.md`; `data\rule21\` (per-arm JSON, `*_transcripts.json`, `arm-*-llama-server.log`, `arm-*-regraded.json`, `rule21-effort-sweep{,-cap32k}.{md,png}`); scripts `work\rule21-{arm,inspect,render,finalize,determinism,merge-cap}.py`; suite `rule21-n25.json` hash `1cdf54f8eb9d3f8f`, 175 prompts, n=25, greedy temp 0/top-k 1 seed 42, **MTP off**, `-c 32768`, `-ctk/-ctv q8_0`. **Highest priority — it is the evidence for A5, A6, A7, A8.** |
| **Energy joins E0 + E8a** (zero GPU) | **MISSING** | `work\energy-joins.md`; power log `data\power\rule21-power.csv` (500 ms logger, 10:48–13:19, 17,716 samples). Source of J/decode-token 7.884 ±0.307 (drafter off) vs 4.26/5.18/6.60/6.13 (on), tokens/kWh 845k/695k/545k/587k, EDP per level, prefill 26–43× cheaper per token, and the 344 W→range anomaly (A10). |
| **Power matrix, 19 arms** (13:21:49–14:05:20) | **MISSING** | `data\power-matrix\` (`report.txt`, `arms.csv`, `arms.json`, 17 per-arm JSONs, `console-*.log`, `events\`, `srv\`, `prompts\`); log `data\power\power-matrix-20260823-132140.csv` (5,098 usable rows); runner `work\power-matrix.ps1` + `work\power-matrix-README.md`. Source of A11 (settled idle 29.9 W) and of per-arm J/decode-token. |
| **Quant ladder** (14:13 → in progress) | **MISSING** | `data\quant-ladder\` (`results.txt` ledger, `ppl-*.log`, `det-*` detector transcripts, `run-ladder.log`, `heartbeat.txt`, `detectors.txt`). Source of A1–A4 and A14. Rig gate reproduced the anchor bit-identically (`expected=6.5956 | measured=6.5956 | delta_pct=0.000 | PASS`). |
| **Agentic bucket** | **PARTIAL** | Finding is in §12; **no §14 bullet and no path**. `agentic\setup-log.md` is named only in campaign.md:993. §14.01's "Raw material" bullet lists only `work/`, `data/`, `campaign.md` — `agentic/` is invisible from the report. |

Additional §14 gaps the new runs created:

- **§14.03 "What was not measured" is missing three now-declared omissions:** (a) **power-cap arms H1/H2 — SKIPPED, needs-admin, commands recorded** (matrix); (b) **ALPACA and MT-Bench — unscored, no independent judge**, transcripts kept, by design (rule-21) — the page nowhere states that two of the seven benchmark sets carry no score; (c) **PSU losses, rest-of-node and PUE — explicitly excluded and unmeasured** (matrix `report.txt` line 3), which bounds every Wh figure in §04.03 and §08.
- **No standardized-metrics row anywhere.** Grep confirms `J/token`, `tokens/kWh` and `EDP` appear **zero times** in index.html; §04.03 and §08 report only Wh/answer and Wh/1k-token. The law's standardized-industry-metrics mandate is unmet even though every input now exists in `energy-joins.md` and `power-matrix\report.txt`. → *Fix:* add J/decode-token, tokens/kWh and EDP columns to the §04.03 table and one line to §14.01 naming the integration method.
- **No ruleset version pin.** The page invokes "METHODOLOGY rule 7 / 8 / 16 / 21 / 22" (index 1104, 2168–2169; campaign.md 85, 618, 653, 991) without ever naming the version — now 26 rules + 4 review gates + two-voice/recipes-first spec + standardized-metrics mandate. The page pins the llama.cpp build to a commit hash but not the methodology it claims to follow. → *Fix:* one §14.01 bullet pinning the ruleset version the way `build 10502, commit 0adcc3bb5` is pinned.
- **Perplexity corpus description is now tokeniser-naive.** §05:1286 and §14.01:2263–2265 describe the corpus only as "36 chunks × 8,192 = 294,912 token positions". The ladder records **297,193 tokens (Qwen) vs 295,216 (Gemma)** for the identical corpus, both at 36 chunks — i.e. 294,912 is a scored-window count, not the corpus size, and it is tokeniser-dependent. → *Fix:* one clause distinguishing scored positions from corpus tokens, now that a second tokeniser has been run.

---

## E. CHECKED AND STILL TRUE (swept, no action)

- index.html:2360 "**Other machines.** Every measured row is this RTX 3090." — holds; all five rounds ran on the same 3090/driver 596.36.
- index.html:2354–2356 + 2124–2132 "**The vision critique loop** … not measured" — holds; no post-publication round attempted it.
- index.html:2386–2387 "**Any drafter but the built-in MTP head**" out of scope — holds; M1 swept MTP parameters only, no external speculator.
- index.html:2383–2385 + 897 "**System RAM under either load mode**… never measured" — holds; no round took a working-set reading.
- index.html:988–994 / 2358–2359 / 2463–2470 "**n=1, one non-blind judge**" for §04 — holds for §04; rule-21 is a separate n=25 mechanical-scorer round and does not retroactively fix §04's judging. (Rule-21's own two judge-gated sets are unscored for the same reason — see D.)
- index.html:2246–2249 "Measured on **port 1235**" — holds across rounds.
- index.html:1906–1908 "Presenting n=25 as a quant ranking … detects a 20-point collapse and nothing finer" — holds, and is now independently confirmed by rule-21's own guardrail ("a single N=25 cell is a smoke test, ±~16 pts"). Optional upgrade: cite the measurement instead of resting on the arithmetic.",
    "guide": "# STALE-CLAIM REGISTER — `E:\chinkeong.github.io\qwen-27b\index.html`

Audited against `E:\AI\measured-inference\results\qwen38-27b-blind\campaign.md`, `work\rule21-live.md`, `work\energy-joins.md`, `data\power-matrix\report.txt`. Line numbers are from the guide. Already-integrated items (follow-up probes M1–M4, 81.7 acquittal, projector/q4_0/repetition, blind-report hero block) excluded.

**Structural finding first:** the string `energ*` occurs in the guide only at line 438 (§04), 1534 and 1540 (sources/footer). §06 has zero energy content, §08 has zero energy content, and the strings `J/token`, `tokens/kWh`, `EDP` occur nowhere on the page. The strings `rule 21`, `HumanEval`, `MBPP`, `MeetingBank`, `MT-Bench`, `ALPACA` also occur nowhere — the entire 8.48-hour rule-21 campaign is absent.

---

## A · NOW-FALSE / NOW-CONTRADICTED

**A1 · §04 idle baselines — wrong numbers AND wrong ordering** (line 437)
> "Baselines: `33.2` W idle with no server, `30.7–31.1` W idle with the model loaded and answering nothing — **leaving the server up costs essentially nothing**."

**NOW-FALSE.** Power-matrix A1 = **29.9 W** settled no-server, A2 = **34.1 W** loaded (+4.2 W for a resident model). The campaign states explicitly that "the published 33.2-vs-30.7 was a cooling board" — the old no-server reading was taken while the board was still shedding heat, which is what produced the physically impossible ordering (loaded idle *below* no-server idle) the guide currently prints.
**Fix:** "29.9 W settled idle with no server, 34.1 W with the model resident (2026-08-23 power matrix, quiet desktop, first ≥60 s of every idle window discarded) — a resident model costs +4.2 W, still essentially nothing."

---

**A2 · §04 "flat ~344 W" — the mechanism sentence** (line 438)
> "…because the board pulls a **flat ~344 W** whatever it is generating while decode falls 81 → 51 t/s."

**NOW-FALSE.** Board power is not flat on either axis. Over time: it drifted **305.5 → 341.1 W (+11.7 %)** across 2.5 h at constant throughput, constant 77–79 °C and constant memory clock, tracking SM clock 1453 → 1606 MHz (E0.7 — the campaign's named headline anomaly). Across configurations: it **fell** as speculation got more aggressive — 325.2 → 308.4 → 302.4 W for B1/B2/B3.
**Fix:** "…because the board holds **306–341 W** whatever it is generating while decode falls 81 → 51 t/s" — and keep the mechanism, which is now proven with no residual (`J/token ≈ mean_W ÷ decode t/s` predicted 4.24/5.16/6.60/6.13 vs measured 4.26/5.18/6.60/6.13).

---

**A3 · §04 "344 W is the sustained figure to plan with"** (line 437)
> "Short 10-second windows read only 277–287 W because they catch the ramp from idle; **`344` W is the sustained figure to plan with.**"

**NOW-FALSE as a constant.** Energy-joins licences this only as a range: drafter-off sustained decode **306–341 W**, drafter-on **338.6–345.0 W**. "Quote a run's own mean, or the range. A single global constant is not supported."
**Fix:** "…plan with the band: **306–341 W drafter-off, 339–345 W drafter-on**, or with your own run's mean." (Keep the 277–287 ramp warning — E8a confirms it as a real 17–20 % short-probe artifact.)

---

**A4 · §03 `--parallel 1` — the recommendation is now unsafe as stated** (line 371)
> "Two concurrent requests at `--parallel 2` gained only **+11% aggregate throughput** (79.2 vs 71.3 t/s) while making each request ~40% slower… **For one user — even one driving multiple agents — queueing beats sharing.**"

**NOW-CONTRADICTED.** Matrix G1/G2 with the drafter **OFF**: `--parallel 2` = **+60.3 % aggregate t/s, −39.6 % J/token (5.19 vs 8.59), −62 % EDP**. The campaign's own reading: the +11 % was likely measured with the drafter ON, because drafting already amortizes the weight read batching would otherwise amortize. The campaign also gates this — "a matched spec-on pair is required before publishing either number as general."
**Fix:** scope both — "+11 % with the MTP drafter on; +60 % aggregate and −40 % J/token with it off (matrix G1/G2). Queueing beats sharing only while you are speculating" — or hold the bullet until the matched spec-ON pair runs.

---

**A5 · §04 effort cost multiplier** (line 413)
> "~**4×** medium's wall-clock, measured twice"

**NOW-SCOPED / OVERSTATED as a general figure.** That is one 1,700-token authoring task. On the 175-prompt rule-21 suite, same machine, greedy: **2.70 h vs 1.47 h = 1.84×**, and mean output 2,217 vs 1,228 tokens = 1.8×.
**Fix:** "~4× on one long authoring task, **1.8× across a 175-prompt benchmark suite** — the multiplier is task-shaped, not a constant."

---

**A6 · §04 cap-sufficiency footnote** (line 409)
> "rerun at a 16,384 cap: **zero truncations, 95.0%** — … and **16,384 proved sufficient for every xhigh thought on this benchmark**."

**LITERALLY TRUE, NOW DANGEROUS.** The scope clause "on this benchmark" is doing enormous work that no reader will honour. On the seven-benchmark rule-21 suite the same 16,384 cap truncated xhigh **8 times in the scored sets (9 including ALPACA)**, and **3 prompts still exceed 32,768**. Worse: **11 of the 12 truncations returned empty `content`** — the runaway lives *inside* the reasoning block, so `</think>` never arrives and the answer is not merely cut, it never exists.
**Fix:** append "…on GSM8K. On a seven-benchmark suite the same cap truncated xhigh 8×/175 and three prompts exceeded even 32,768 — size the cap against your hardest set, not against GSM8K."

---

**A7 · §04 "nobody has run that here"** (line 409)
> "Separating a real effort→defect effect from sampling noise needs n≥10 per level on a single task with blind judging; **nobody has run that here**."

**STILL TRUE, NOW MISLEADING.** No blind-judged single-task n≥10 exists — but the sentence reads as "no effort-vs-quality evidence beyond n=2 exists", and 2026-08-23 produced **~125 scored samples per arm across 5 scored benchmark sets**.
**Fix:** keep the sentence, add "— but the adjacent question now has an answer at n≈175 per arm: see the rule-21 sweep below."

---

**A8 · §04 quality-table row for `low` contradicts its own prose, and now contradicts the data** (line 415)
> "`low` / `none` … **measured shipping broken code on complex tasks, 2 of 2 runs**"

**NOW-FALSE as a flat claim.** The §04 prose already retracts the direction (the blind campaign's `low` page rendered correctly; its `medium` page shipped the init bug) — but the table row still states it unqualified, which REPORT-SPEC's "publish and disclaim is banned" rule targets directly. Rule-21 now makes it worse: at the 32k cap **`low` is the highest-scoring arm (82.1)**.
**Fix:** rewrite the cell to "one campaign saw 2/2 fatal defects at `low`, another saw the defect at `medium` — a fatal defect is a live risk at every level at n=1; on the 175-prompt suite `low` scores highest (82.1)."

---

**A9 · §05 scored smoke test — MATH-500 column now suspect on two independent grounds** (lines 488, 492–494)
> "MATH-500 … **75%** (5 trunc) / 65% (5 trunc) / 65% (5 trunc)" under a "**4096-token budget**; answers that ran out of budget mid-thinking count as wrong"

**NOW-SUSPECT.** (a) 5/20 = **25 % truncation** at 4,096, and rule-21 shows MATH-500 needing up to **18,273 tokens and still scoring correct** — §09's own "raise the budget, don't shrink the test" rule was applied to §04's GSM8K and never to this table. (b) The rule-21 live run found a MATH-500 scorer bug of exactly this shape — **presentation-vs-value normalization** (`145` vs `145^\circ`, `\dfrac` vs `\frac`, `55°` vs `55^\circ`, LaTeX thin spaces, `\\[6pt]` row spacing) — worth **32 points at n=25 (60.0 → 92.0)**.
**Fix:** mark the MATH-500 column "cap-taxed and normalization-unaudited" and re-grade the kept transcripts with the fixed normalizer before it is quoted again.

---

**A10 · §04 + §05 GSM8K n=200 columns — same bug class, same signature** (lines 404–406, 517, 1536)
> "GSM8K n=200 … 96.0% / 97.5% / **95.0%**" and "Q4_K_M **94.0%**, UD-Q4_K_XL 94.5%, UD-IQ4_XS 93.0%"

**NOW-SUSPECT, must-check.** Rule-21 bug #2: the GSM8K grader "compared the whole answer line instead of the number", surfacing **only at xhigh, which reasons in units** (`#### 156 kg` vs ref `156`) — and it was xhigh's *entire* GSM8K deficit: **92.0 → 100.0** once fixed. The guide's xhigh column is its lowest GSM8K score: the identical signature. (Different harness — `chinkeong/benchmark` vs `measured-inference/scripts/bench` — so this is a re-grade order, not a proven error.)
**Fix:** re-grade the kept n=200 transcripts with a `####`-number extractor before 95.0 or the 94.0/94.5/93.0 quant ordering is quoted again. Note the blast radius: §08 Choice A's "two independent metrics agreeing" argument rests on the 94.0 vs 93.0 gap.

---

**A11 · §04 energy table is missing its most useful row** (lines 431–436)
> low 344.1 W / 20.55 Wh · medium 344.3 / 35.96 · xhigh 338.6 / **120.21**

**INCOMPLETE.** 120.21 Wh is the **truncated** xhigh run that returned no file. The **completed** 120k-cap xhigh run exists and is absent: **104.84 Wh, 6.13 J/decode-token, 586,830 tokens/kWh, EDP 4.16e8**. All four published Wh figures were independently re-integrated to within **0.05 % (rectangle) / 0.15 % (trapezoid)** — they may now be cited without hedging.
**Fix:** add the xhigh-120k row and label 120.21 explicitly "truncated — no deliverable".

---

**A12 · Footer and Sources date-scope are a pass behind** (lines 1534, 1535, 1540)
> footer: "updated **2026-08-23 (second pass)** — follow-up measurements folded in…"
> sources: "…**~2 h of GPU time**… The two follow-ups it left pending … were measured the same day and are the bullet below"

**NOW-STALE.** Four further rounds landed after that update: the **rule-21 live effort sweep (8.48 h GPU)**, the **E0/E8a energy joins (zero-GPU)**, the **19-arm power matrix (43.7 min, 100 % coverage)**, and an **in-progress quant ladder**. "The two follow-ups it left pending" now reads as closure on a campaign that kept going.
**Fix:** bump to "(third pass)" and add three source bullets — rule-21 (suite hash `1cdf54f8eb9d3f8f`, n=25×7×3 arms, greedy seed 42, no MTP, ALPACA/MT-Bench unscored by design); energy joins (`scripts/power/attribute-power.py`, `--selftest` passed 7 groups / 27 assertions); power matrix (19 arms, in-band NVML, H1/H2 skipped needs-admin).

---

## B · MISSING EVIDENCE — strongest additions

**B1 · §06 carries no energy result at all. This is the single biggest gap on the page.**
The matrix ran a controlled same-server, same-prompt speculation ladder:

| arm | J/decode-token | decode t/s | EDP (J·s) | mean board W |
|---|---|---|---|---|
| B1 `--spec-type none` | **8.104** | 42.53 | 93,380 | 325.2 |
| B2 n4/p0.75 | 3.743 | 91.29 | 20,091 | 308.4 |
| B3 **n10/p0.5** | **3.210** | 106.22 | **14,811** | **302.4** |

**n10/p0.5 uses 2.52× less energy per token, delivers 2.50× the throughput, and 6.3× better EDP than no speculation — and board watts *fell* as speculation got more aggressive.** The guide's own "flat W" assumption predicted no power change; the win compounds instead.
**Fix:** add a "Speculation is an energy feature" block to §06 and change the section's framing from "free speed, priced in acceptance" to "free speed *and* 2.5× cheaper tokens, priced in acceptance". This also strengthens §06's "So what should you set?" callout, which currently justifies n10/p0.5 on speed alone.

**B2 · §06's mean-draft-length mechanism gets an independent energy cross-validation.**
Matrix E1/E2, think-on vs think-off on one server: **6.066 vs 3.744 J/decode-token = 1.62×**, against the **1.69×** throughput ratio the draft-length measurement produced (2.99 vs 4.31 mean draft length). Same mechanism, completely different instrument.
**Fix:** one sentence after §06's mean-draft-length table.

**B3 · §09 is missing the best truncation case study the campaign produced.**
Rule-21, 175 prompts × 3 arms, composite Mean over 5 scored sets:

| cap | low | medium | xhigh | truncations |
|---|---|---|---|---|
| 16,384 | 81.3 | 80.5 | **77.3** | 1 / 2 / 9 |
| 32,768 | **82.1** | 80.5 | **81.3** | 0 / 0 / 3 |

At 16k the sweep reads as **quality falling with effort**; raise the cap and all three land within **1.6 points**. The entire xhigh penalty was the cap. `MATH-500[3]` needed **18,273 tokens and was correct**; `HumanEval[24]` needed **17,025 and was correct** — both scored 0 at 16,384.
**Fix:** promote this above §09's current 5-of-200 GSM8K example. The existing example costs ~1 point; this one **overturns a headline**.

**B4 · §09's determinism licence is asserted; it is now measured 139/139.**
> line 1253: "because greedy decoding is deterministic, arms that never truncated produce byte-identical output under any larger cap — only the truncated arm needs rerunning."

Rule-21 byte-compared every non-truncated prompt across the cap raise (`work/rule21-determinism.py`): **low 24/24, medium 48/48, xhigh 67/67 = 139/139, zero drift** — with `-c` doubled as well as `--max-tokens`.
**Fix:** attach 139/139. It converts the guide's licensing argument for dataset-scoped reruns from a principle into evidence, and it is the cheapest credibility upgrade on the page.

**B5 · §04 has no standardized-metrics columns; §08 has no metrics table at all.**
METHODOLOGY rule 24 / REPORT-SPEC require, under the literal title **"Standardized industry metrics"**: instrumentation tier, mean load W, **J/token (decode) with J/prompt-token (prefill) beside it**, **tokens/kWh**, **EDP (J·s)**, **Wh/answer gross *and* idle-subtracted**, and an **E_comm** row. Every number now exists:

| level | J/dec-tok | tokens/kWh | EDP (J·s) | Wh gross | Wh net |
|---|---|---|---|---|---|
| low | 4.26 | 844,778 | 1.57e7 | 20.58 | 18.72 |
| medium | 5.18 | 694,661 | 4.84e7 | 36.01 | 32.75 |
| xhigh 64k (truncated) | 6.60 | 545,326 | 5.52e8 | 120.25 | 109.19 |
| xhigh 120k (complete) | 6.13 | 586,830 | 4.16e8 | 104.84 | 95.28 |

Plus prefill **0.12–0.18 J/prompt-token**, `E_comm` = "N/A — single GPU, no interconnect", and the tier line: *in-band GPU board power (NVML); PSU, CPU and node excluded and unmeasured — never call this wall power or divide a bill by it.*
Two quotable results ride along: **EDP spans 1.57e7 → 5.52e8, a 35× range across three effort levels** (energy-delay punishes xhigh 6× harder than energy alone, which is 5.8×); and **idle subtraction is a 9 % effect while the *choice* of idle baseline is a 0.13 % effect** (30.7 vs 31.16 W) — the idle-baseline argument is irrelevant at sustained-decode scale.
**Fix:** replace §04's four-column table with the mandated one, and add a per-recipe metrics table to §08.

**B6 · §04's quality story still rests on n=2 blind judging; the n≈175 tie is absent.**
Rule-21 gives per-benchmark at 32k: GSM8K **100/100/100**, MATH-500 92/100/92, HumanEval 100/96/92, MBPP 92/84/92, MeetingBank ROUGE-L 22.6/22.4/22.3; walls 1.00/1.47/2.70 h; mean output 830/1,228/2,217 tokens; ~42 t/s. ALPACA and MT-Bench deliberately **unscored** — a model must never judge its own outputs — so the Mean is labelled a composite index over 5 scored sets, not an accuracy.
This is §04's own headline ("moves hours, not percent") upgraded from n=2 to ~125 scored samples per arm, and it preserves the guide's "low sitting between them breaks any effort-accuracy ladder" observation — low is now highest.
**Fix:** add a rule-21 block to §04; restate the xhigh ship-default as **completeness insurance only**, explicitly, now that the score argument is gone.

**B7 · §04 omits the drafter, its own largest energy lever.**
E8a (drafter ON) 4.26–6.60 J/decode-token vs E0 (drafter OFF, **n=115 requests**, 3 arms, 3 benchmarks) **7.884 ± 0.307** → the drafter **roughly halves J/token**: −16 % at xhigh's 51 t/s, −46 % at low's 81 t/s, for ~+8 % board power. The matrix's controlled B-arms put it at 2.52×. Label the E0/E8a pair a **reference comparison, not a controlled A/B** (different task, greedy vs temp 1.0); the B-arms are the controlled version.
**Fix:** "the drafter is the cheapest energy setting on this page" in §04, cross-linked to §06.

**B8 · Energy at depth inverts the prefill story — nothing on the page says this.**
Matrix F1/F2/F3: at a 91k fill, **90.7 % of the arm's joules are prefill**, and the same 700-token answer costs **0.83 Wh at 1.5k depth vs 11.71 Wh at 91k — 14×**. Against E8a's short-prompt case where prefill is 0.06–0.38 % of an answer's energy.
**Fix:** one line in §02 or §04 — "prefill is free when the prompt is short and the answer long; **at agent depth prefill *is* the bill**."

**B9 · Quant choice is now an energy choice** (§05 table, §08 A-vs-B rule).
Matrix C1/C2/C3, same prompt, same server: IQ4_XS **8.198**, Q4_K_M **8.853**, NVFP4-HIGH **9.293** J/decode-token (+8.0 % and +13.4 % on the report's own columns; the campaign summary rounds these to +7.8 % / +13.1 %) — outside the 2.9 % noise floor. D1/D2 KV f16 vs q8_0 differ **0.7 %** — a clean null, which independently backs §03's "half the KV VRAM for statistically nothing".
**Fix:** add a J/token column to §05's file table; add "Choice A's quality edge costs ~8 % more energy per token" to §08's choosing rule.

**B10 · The page-wide noise floor is unpublished** (METHODOLOGY rule 26).
Measured B1/C1/D2 triplicate: **2.9 % on J/token, 5.6 % on EDP**, monotonic with board heat, config-dependent (fast MTP arms agree to 0.03 %). Plus E0.7's separate rule: **a ±6 % J/token difference between arms measured hours apart is instrumental drift**, not the variable under test.
**Fix:** one page-level sentence — "do not believe a slow-arm energy gap under ~3 %."

**B11 · One genuinely *new* "unmeasured" claim the guide should gain.**
E0.7 shows the board spending **6–12 % more power at SM clocks that bought zero extra tokens** (batch-1 decode is memory-bandwidth-bound at a fixed memory clock), which makes `nvidia-smi -pl` the strongest untested hypothesis on this box. Matrix **H1/H2 were SKIPPED**: the probe returned *exit 4 Insufficient Permissions*, the cap was never changed and remains 350 W, and the commands are recorded.
**Fix:** add to §04 or §10 — "power capping: **unmeasured on this machine (requires an elevated shell)**; commands recorded, not estimated." This is the only place on the page where a negation should be *added* rather than retired.

**B12 · §05 perplexity anchor gains an independent bit-identical reproduction, plus one usable caveat.**
The quant-ladder rig gate re-ran the fp16 anchor and reproduced **6.5956 bit-identically**. The ladder is otherwise **in progress** (cross-model Gemma arm and pass-1 rungs pending) — nothing else from it ships yet. One caveat is already usable: the same corpus tokenizes to **297,193 positions under Qwen's tokenizer and 295,216 under Gemma's** (both 36 chunks), so §05's "294,912 token positions" framing is tokenizer-bound and **perplexity is never comparable across model families**.
**Fix:** one clause on the §05 perplexity paragraph; hold the rest until pass-1 lands.

---

## C · HEADER SPEC STRIP vs THE FOUR-BAND MANDATE (line 155)

> "**Reference** RTX 3090 · 39.7–43.8 t/s floor (short-context, no spec) · 49–70 short-context work · 62–70 t/s at 91k depth (answer tokens; the shipped xhigh default's reasoning tokens 37–39 there) · 148.7 ceiling (verbatim copy, thinking off)"

**Verdict: structurally COMPLIANT — four bands are present and the at-depth band names its anchoring depth (91k), which is the part `templates/REPORT-SPEC.md:30` says three-band strips hide.** Two defects remain:

1. **Band 2 is the only one without its condition in parentheses.** "49–70 short-context work" states no file, no drafter flags, no token regime — and the spec requires *each* band to carry its condition. **Fix:** "49–70 (UD-IQ4_XS · n4/p0.75 · answer tokens)".
2. **The at-depth band is anchored on the noisiest column §06 publishes.** "62–70 t/s at 91k" takes its upper bound from the vision / n10-p0.5 **single-probe** column that §06 itself flags as carrying ±25 % clock-state noise, while §06's authoritative **cooled ladder** reads **64.8 t/s** at 91k. **Fix:** re-anchor to "64.8 at 91k (cooled ladder, answer tokens, n4/p0.75); 37–39 on the shipped xhigh reasoning stream".

Also worth noting: the strip is speed-only. Rule 24 makes energy a first-class metric and REPORT-SPEC puts energy **with the recipes unconditionally** — §08 currently has none, which is the same gap as B5.

---

## D · SOURCE PATHS

- Guide audited: `E:\chinkeong.github.io\qwen-27b\index.html`
- `E:\AI\measured-inference\results\qwen38-27b-blind\campaign.md` (rule-21 entry ~L1029; energy joins ~L1052; power matrix ~L1074)
- `E:\AI\measured-inference\results\qwen38-27b-blind\work\rule21-live.md`
- `E:\AI\measured-inference\results\qwen38-27b-blind\work\energy-joins.md`
- `E:\AI\measured-inference\results\qwen38-27b-blind\data\power-matrix\report.txt` (+ `arms.csv`)
- Mandates: `E:\AI\measured-inference\templates\REPORT-SPEC.md` (L30 four-band, L166 standardized metrics), `E:\AI\measured-inference\methodology\METHODOLOGY.md` (rule 24 L267, rule 26 L392)

**One caveat if matrix net-Wh figures are republished:** the matrix runner hardcoded `-IdleW 31.0` rather than the A2 loaded idle of 34.1 W — a uniform ~1 % shift with no ranking changes, and re-attribution is zero-GPU 