# DECISION DOCUMENT â€” Sub-Q4 quants as a daily driver under 24 GB

Prepared 2026-08-24T11:47. Ledgers read live at that time; the equal-budget arm was still generating (MBPP 12/25).

---

# PART 1 â€” THE HONEST ANSWER TO "IS IT IN PLAN"

**Plain answer: no. The thing you asked for is not in plan, and the thing that is in plan answers a different question.**

The quant ladder now running is chartered as *"how small can this model's file get and still work"*. It varies the file size and holds the machine fixed. Your question varies the machine and asks what file size that machine permits. Those two questions share exactly one axis â€” quality â€” and the ladder measures that axis at a context depth of 8,192 tokens, which is not a depth anybody's daily driver runs at. It measures no speed you would experience, no VRAM footprint, and no window. There is no card in the loop anywhere in it.

So: the quality half of your question is nearly answered and cost nothing more to publish. The usability half has no measurement in plan, no data on disk, and no scoped deliverable anywhere.

### (i) Already measured or running

| Thing | State | Where |
|---|---|---|
| Perplexity for 7 Qwen rungs, 4.22 â†’ 1.83 bits/weight | **DONE**, pass-1 complete 2026-08-24T01:24 | `data\quant-ladder\results.txt` |
| Rig gate: IQ4_XS reproduced 6.5956 bit-identically, twice | **DONE**, `delta_pct=0.000` | same |
| Functional detectors (repetition, JSON echo, fence discipline) on all 7 rungs + gemma | **DONE**; one FAIL (IQ1_S, `json=FAIL(empty)`) | `data\quant-ladder\detectors.txt` |
| Decode t/s per rung at prompt depth 218, no drafter, f16 KV, `-c 8192`, n=1 | **DONE** (incidental â€” never analysed) | `srv-det-<rung>.err.log` |
| Cross-model comparator, gemma-4-12B-QAT-Q4_0, 3 datasets Ã— n=25 | **DONE**, mean 73.30, but carries 19 unresolved truncations | `data\quant-ladder\decisive.txt` |
| Qwen IQ2_XXS scored arm, same 3 datasets | **IN FLIGHT at time of writing.** GSM8K 80.0, HumanEval 84.0, MBPP at 12/25. **Do not quote as final.** | `bench\arm-qwen-iq2xxs.console.log` |
| UD-IQ2_S infill rung (the cliff bracket) | **AUTO-ENABLED 01:12:13, BLOCKED.** `dl-iq2s.out.log` is 0 bytes; `chain-ladder-pass2` has been idling "no rung was runnable" every 60 s since 11:20 | `enable-UD-IQ2_S.flag` |
| gemma perplexity / bits-per-byte | **WITHDRAWN**, quarantined, forbidden from every table | `results.txt` WITHDRAWN line |

### (ii) Scoped as a deliverable â€” but for the blind report, not the guide

One sentence in the Gen-2 blind report is the entire scoped consumer of this data:

> `index-gen2-draft.html:2851` â€” *"this section gains a perplexity-against-size curve with its knee named, and detector verdicts beside it â€” perplexity ranks, detectors disqualify."*

That names a curve and verdicts. It names no speed, no VRAM, no window, no card class. The rewrite brief calls it a *"bounded second pass"* into **blind-report section 05** (`gen2-rewrite-brief.md:338-341`). The equal-budget arm is scoped the same way â€” `decisive-arm.ps1:6-9` frames ~6.5 GiB as a *model-family* matching budget, never as a VRAM recommendation.

### (iii) Genuinely NOT in plan

1. **No guide chapter.** The one guide-facing register entry (`staleness-registers.md:520-522`, item B12) says: *"The ladder is otherwise in progressâ€¦ nothing else from it ships yet. Fix: one clause on the Â§05 perplexity paragraph; hold the rest until pass-1 lands."* Pass-1 has now landed. That is a deferral placeholder, not a scope â€” it names no chapter, no reader question, no card class, no acceptance criterion.
2. **No speed measurement in any regime a reader would use.** Every ladder t/s is at prompt depth 218 with no drafter. MISSING at 4k/16k/32k depth, MISSING with the MTP drafter, MISSING with q8_0 KV.
3. **No VRAM footprint for any rung.** Not one log records model buffer, KV buffer, or compute buffer. The only VRAM figure in the whole campaign is an incidental `nvidia-smi` board total (`vram=9971MiB`) for one rung at one window with other processes resident.
4. **No context-window measurement.** Every rung ran at a fixed `-c 8192`. A per-rung ceiling cannot be derived from a run where context is a constant.
5. **No 8 GB anything.** The guide has no 8 GB card, recipe, or roster row; `REPORT-SPEC.md` Â§7's minimum roster has no 8 GB class either.

### What IS obligated right now, independent of your request

`REPORT-SPEC.md:60-68` â€” *"A report is stale the moment its campaign outlives itâ€¦ Every commit that adds results to a campaign re-runs the self-reference check on the published page."* Pass-1 landing makes this bite on the published guide **today**, whether or not a new chapter is ever written:

| Guide line | Now-false or now-weak claim | Correct state |
|---|---|---|
| 175 | *"a quantization ladderâ€¦ contributes two results here"* | 7 pass-1 rungs + 2 rig-gate reproductions + 1 withdrawal + 1 functional FAIL |
| 1461 | UD-Q3_K_XL: *"Unmeasured here"* | Measured: **PPL 6.7691 Â± 0.04667, +2.63% vs UD-IQ4_XS** |
| 1013 | *"even the smallest file (UD-IQ1_S, 5.8 GiB) misses once buffers are counted"* | Still true as arithmetic, but IQ1_S now has a measured PPL (8.9265) and a hard detector FAIL â€” the sentence must point at a register, not assert |
| 1014 | *"UD-IQ3_XXS (10.15 GiB) **fits** with real room to spare"* | Rule 13b: a residency label with no deep-fill probe. Must be downgraded or probed |
| 1443 | Arc B580: *"even 3-bit does not fit â€” heavy offload or 2-bit"* | 2-bit is now measurable and mostly disqualified; the dismissive clause needs a pointer |
| 1456 | *"If you have a 16 GB card, take UD-Q3_K_XL"* | **Now has evidence.** This is the cheapest, highest-value single edit available today: one line, zero GPU |

---

# PART 2 â€” WHAT THE MEASURED DATA CAN ALREADY SUPPORT

**Plain summary: the data licenses a strong statement about quality and a surprising statement about speed. It licenses nothing at all about fit.**

The surprise is worth putting first, because it is the most decision-relevant number in the whole dataset and nobody has looked at it yet: **making the file smaller barely makes it faster.** From 4.22 to 1.83 bits/weight the file shrinks **2.30Ã—** and decode speeds up **1.33Ã—**. Sub-Q4 buys VRAM. It does not buy speed.

## 2A. Claims the data licenses TODAY

**Conditions that travel with every perplexity number below** (rule 3): frozen `wikitext-2-raw-test.raw`, md5 `7c0137fc034ddbc56a296bce31b4f7fb`, 1,290,590 bytes; 36 Ã— 8,192 chunks = 294,912 scored positions; `-ngl 99 -c 8192 -fa on --load-mode mmap`; **f16 KV**; llama.cpp build 10502, commit `0adcc3bb5`, driver 596.36, RTX 3090. `ppl_comparable=yes` on all Qwen rungs. **Comparability scope: comparable only to each other and to the campaign's own 6.5956 / 6.8774 anchors. Not comparable to any other model (rule 6, different tokenizer), and not to Â§08's KV-quant table (different axis).**

| # | Claim | Number | Grade |
|---|---|---|---|
| Q1 | Quality degrades **gently** from 4 bits to ~2.9 bits | 6.5956 â†’ 6.7691 (+2.63%) â†’ 6.9187 (+4.90%) â†’ 6.9957 (+6.07%) | MEASURED |
| Q2 | There is a **cliff** between 2.91 and 2.15 bits/weight | +14.47% in one step (6.9957 â†’ 8.0079); 13.0Ã— the previous step's 1.11% | MEASURED |
| Q3 | Below the cliff, perplexity keeps degrading | 8.1418 (+23.4%), 8.9265 (+35.3%) | MEASURED |
| Q4 | The 3-bit file the guide already recommends for 16 GB costs **+2.63%** perplexity | 6.7691 Â± 0.04667 | MEASURED |
| Q5 | Every step in Q1 is outside the error bars | error â‰ˆ Â±0.048 on 6.99 = Â±0.69%; steps are 2.63 / 2.27 / 1.11 percentage points | MEASURED |
| Q6 | Perplexity **cannot** separate IQ2_XXS from IQ1_M | 8.0079 Â± 0.05695 vs 8.1418 Â± 0.05586 â€” a 1.67% gap inside overlapping bars | MEASURED (a negative result) |

**Functional integrity** â€” conditions: llama-server `-ngl 99 -c 8192 -fa on --parallel 1 --jinja --reasoning off`, greedy (`temperature=0, top_k=1`), f16 KV, probe A only, n=1 per rung.

| # | Claim | Evidence | Grade |
|---|---|---|---|
| F1 | Everything at or above 2.91 bits writes correct, complete, instruction-following code | Q3_K_XL / IQ3_XXS / Q2_K_XL all continue from the cut point, zero fences, `json=PASS(exact)` | MEASURED |
| F2 | **IQ2_XXS emits a complete program that cannot run.** `this.edges.get(from)` on a Map nothing ever `.set()`s â€” first `addEdge` throws `TypeError` | `det-UD-IQ2_XXS-probeA.txt` | MEASURED (by reading the artifact) |
| F3 | Instruction-following decays in three visible steps | 5 rungs continue from the cut; IQ2_XXS restarts the file; both IQ1 rungs open a markdown fence the prompt forbade and never close it | MEASURED |
| F4 | IQ1_M collapses into mechanical enumeration | `visitedMap2` â€¦ `visitedMap29`, EOS mid-identifier at `const un`; ~58 of 125 lines are the counter | MEASURED |
| F5 | IQ1_S is the hard failure | `json=FAIL(empty)` â€” one token, immediate EOS, total abstention on a trivial echo | MEASURED |
| F6 | **The detector suite is blind to counter-incrementing degeneration.** D1â€“D4 all returned PASS(0) on IQ1_M | Detectors need identical adjacent lines or a recurring 16-gram; an incrementing counter defeats both | MEASURED (an instrument gap this campaign discovered) |
| F7 | `uniq` is the only field that sees F4, and it does not feed the verdict | IQ1_M uniq **0.3582** against 0.4899â€“0.5154 for every healthy rung; `detectors.ps1:195-198` uses only rep/json/fence | MEASURED |
| F8 | `uniq` is not monotone in quality | IQ1_S uniq 0.4143 > IQ1_M 0.3582, on worse output â€” each `TotalTotalâ€¦` counts as a distinct word | MEASURED |

**Speed â€” the finding nobody has extracted.** Conditions: RTX 3090 (936 GB/s), no drafter, greedy, f16 KV, `-c 8192`, single stream, **prompt depth 218**, ~0.9â€“1.3k generated tokens, cold-started server, **n=1**.

Efficiency constant = measured t/s Ã· (936 GB/s Ã· file GB). This is rule 10's constant, re-derived per file from one measured point, exactly as the rule requires.

| File | GB (dec) | t/s (n=1) | Efficiency vs bandwidth law |
|---|---|---|---|
| UD-IQ4_XS | 14.25 | 40 | **0.61** |
| NVFP4-MTP-VERY-LOW | 14.86 | 39 | 0.63 |
| UD-Q3_K_XL | 13.15 | 43 | 0.60 |
| UD-IQ3_XXS | 10.93 | 44 | 0.51 |
| UD-Q2_K_XL | 9.83 | 46 | 0.48 |
| UD-IQ2_XXS | 7.27 | 49 | **0.38** |
| UD-IQ1_M | 6.73 | 51 | 0.37 |
| UD-IQ1_S | 6.19 | 53 | **0.35** |

Printed to 2 significant figures per rule 26 â€” a single-probe level cannot hold 4.

| # | Claim | Grade |
|---|---|---|
| S1 | **The efficiency constant is not a format constant. It falls monotonically with file size, 0.61 â†’ 0.35.** | MEASURED, this regime only |
| S2 | **Halving the file buys about 24% more speed, not 96%.** IQ4_XS â†’ IQ2_XXS is 1.96Ã— smaller and 1.24Ã— faster | MEASURED |
| S3 | **Applying the guide's published flat constant (0.70 K-quant / 0.65 IQ-quant) to a sub-Q4 file over-predicts its speed, by more the smaller the file.** At IQ2_XXS: 0.65 against a measured 0.38 = a **1.7Ã— over-promise** | MEASURED â€” and this is a rule-2 violation waiting to be published |
| S4 | The guide's own 16 GB row is high. Its ~25â€“50 t/s band for UD-Q3_K_XL uses 0.70; the ladder measured **0.60** for that exact file â†’ the honest band is **~17% lower** | DERIVED from a measured constant, **pending the regime-collision check in Part 6/R6** |

## 2B. Claims the data does NOT license, and why

| Claim | Why not | Rule |
|---|---|---|
| "Rung X runs at N t/s for daily work" | Every t/s is at prompt depth 218 with no drafter, no q8_0 KV, on a cold server, n=1. A daily driver runs at depth, with a drafter, with a desktop up | Rule 3 (depth, token regime, desktop state, sampling must travel); rule 2 (publish what the reader actually gets) |
| Any t/s printed to 4 significant figures | The within-session band (Â±0.5â€“1.5%) explicitly excludes reload, page-cache state, clock ramp and thermal drift â€” the sources that actually move t/s. It is a **lower bound**, not the band | Rule 26 â€” *"four significant figures on a Â±25% probe is a lie of precision"* |
| "Rung X fits in 16/12/8 GB" | **No VRAM footprint was measured for any rung.** File GiB is not VRAM | Rule 13a |
| "Window W is resident/safe on rung X" | No deep-fill probe exists near the top of any window on any rung. Arithmetic sizes a footprint; it cannot license a residency label | Rule 13b â€” *"no window is labeled resident/safe without at least one deep-fill probe near its top"* |
| "A 12 GB card gets N t/s on rung X" | Derivable only, and now only with the per-rung constant from S1 â€” never with a flat 0.65 | Rule 1b (derivation depth), rule 10 |
| "The 27B at 2 bits beats a native 4-bit 12B" | The primary arm has not finished. `decisive.txt` currently records only `ARM qwen-iq2xxs \| FAILED - no result json` | Rule 1a (a "measured" number that resolves to nothing is downgraded) |
| Anything comparing gemma's perplexity to a Qwen rung | gemma's PPL and bits-per-byte are WITHDRAWN and quarantined | Rule 6, and the ledger's own WITHDRAWN line |
| "IQ1_M passes" | It is logged `verdict=PASS \| rep=CLEAN` on output that never finishes the task. F6/F7 say the verdict is the instrument's blind spot, not a property of the model | Rule 4 (two cheap metrics disagreeing) |
| "Rung X is worth it for coding" | Scored benchmarks exist for **exactly one** rung and it hasn't finished. There is no quant-vs-accuracy curve at all | Rule 6 designates the scored arm as the deciding instrument; it has one incomplete point |
| Carrying the other campaign's MTP peak (81.7 t/s) to any rung | Zero speculative decoding was used anywhere in this ladder. `bench-arm.py:24` â€” *"NO MTP drafter"* | Rule 3 comparability scope |
| Anything about wall clock for a 100k-token run | Requires t/s at depth, which does not exist | Rule 10 (prompt:completion ratio on every wall-clock estimate); user memory *wall-clock over throughput* |

---

# PART 3 â€” THE GAP, AS MEASUREMENTS

**Plain summary: four arms are worth running, three of them cheap. Two more that look attractive should be cut because no reader-facing number consumes them.**

The rig has **one 24 GB card**. That fixes what is obtainable:

- **MEASURED on this card:** perplexity, functional integrity, VRAM footprint, window residency *within an emulated VRAM budget*, decode and prefill at depth, drafter acceptance.
- **DERIVED arithmetic:** every number for a card that is not this 3090 â€” decode via `card GB/s Ã· file GB Ã— the per-file constant re-derived in Part 2A`, and window via the two-constant model below.
- **NOT OBTAINABLE, ever, without hardware:** a real 12/16/8 GB card's bandwidth behaviour, its driver's spill behaviour, its own desktop share, and therefore any residency *verdict* for that card. Rule 13b closes this permanently. It goes to the negative register with the price of a card loan.

### The two derivation formulas, with their borrowed constants named (rule 1b)

**Decode floor (depth 1, one borrowed constant):**
```
t/s â‰ˆ (card GB/s Ã· file GB) Ã— eff(file)
eff(file) = the per-rung constant measured in Part 2A â€” 0.61 at 4.2 bpw falling to 0.35 at 1.8 bpw.
NOT 0.70/0.65 flat. Borrowed: this machine's 936 GB/s and one n=1 probe at depth 218.
```

**VRAM base (depth 2, two borrowed constants, neither checked below 4 bits):**
```
base_MiB(rung) â‰ˆ 13,232 + (file_GiB âˆ’ 13.274) Ã— 1024
Borrowed 1: 13,232 MiB â€” measured base for UD-IQ4_XS, text-only, no drafter, from a 17-load fit
            reproducing all 17 within 127 MiB (guide Â§05-budget).
Borrowed 2: the 1:1 file-sizeâ†’base slope, itself derived from exactly two points ABOVE 4 bits
            (Q4_K_M +2.13 GiB file â†’ +2.1 GiB base; UD-Q4_K_XL +3.12 â†’ +3.1). Never checked below Q4.
```

**Window (depth 1 plus an untested invariance):**
```
window_MiB(n) = n Ã— 39,936 / 1,048,576         (drafter off, q8_0 KV)
              = n Ã— 45,056 / 1,048,576 + 1,008 (drafter on, MTP n-max 4)
Both slopes measured on UD-IQ4_XS. KV size is an architecture property, not a weight-quant property,
so the slope SHOULD transfer across rungs â€” but that is an inference, not a measurement. Arm A1 tests it.
Rule-14 fence: desktop measured max 1,181 MiB + load-to-load variance 127 MiB = 1,308 MiB reserved.
```

**What that arithmetic predicts** â€” DERIVED, depth 3, published only if A1 does not retract it:

| Rung | Derived base | 16,384 MiB budget | 12,288 MiB budget | 8,192 MiB budget |
|---|---|---|---|---|
| UD-Q3_K_XL | ~12,177 MiB | ~76k tok drafter-off / ~44k drafter-on | **does not fit** | does not fit |
| UD-IQ3_XXS | ~10,068 MiB | comfortable | ~24k tok drafter-off | does not fit |
| UD-Q2_K_XL | ~9,013 MiB | comfortable | ~52k tok drafter-off | does not fit |
| UD-IQ2_XXS | ~6,569 MiB | comfortable | comfortable | ~8k tok drafter-off |
| UD-IQ1_M | ~6,057 MiB | comfortable | comfortable | ~22k tok drafter-off |

Sanity note: this reproduces the guide's own derived 15.3 GiB for its 16 GB recipe within 0.4 GiB. That is two derivations agreeing, not evidence.

---

## The arms

### A1 â€” Residency and window map (**the biggest gap, and the cheapest fix**)

**Measures.** For each candidate rung: llama-server's own dedicated-VRAM counter at load, as a **drafter-on/off pair** (rule 13a), at 3â€“4 window sizes each; then **one deep-fill probe near the top of every window that gets a label** (rule 13b) â€” fill to ~95% of `-c`, discard the first post-prefill probe (rule 12), time only settled probes.

Then repeat each configuration under a **VRAM-budget ballast**: a separate process holding a CUDA allocation that leaves 16,384 / 12,288 / 8,192 MiB free.

**Exact conditions.** `-m <rung>.gguf -ngl 99 -c <sweep> --parallel 1 --load-mode none -ctk q8_0 -ctv q8_0 --jinja --host 127.0.0.1 --port 1236`; drafter arm adds `--spec-type draft-mtp --spec-draft-n-max 4 --spec-draft-p-min 0.75`; no `mmproj`; **desktop up** (rule 2). Candidates: Q3_K_XL, IQ3_XXS, Q2_K_XL, IQ2_XXS. 4 rungs Ã— 3 windows Ã— 2 drafter states Ã— 3 budgets, minus the combinations the arithmetic already excludes â†’ ~40 loads.

**What it licenses, precisely.** The ballast converts *"fits in 16 GB"* from DERIVED to **MEASURED-under-an-emulated-VRAM-budget-on-a-3090**. It is not a 5080 measurement: it emulates capacity only, not bandwidth, not that board's driver, not that machine's desktop share. It must be chipped as its own evidence class and never as `meas` on a 16 GB card.

**Wall clock.** Loads are 4â€“8 s (`load_s` in `detectors.txt`); the deep fills dominate â€” filling 49k at the measured ~1,000 t/s prefill is ~50 s. **â‰ˆ 1.5â€“2 h.**

**Who consumes it.** The new section's fit table ("largest window that fits at 16,384 / 12,288 / 8,192 MiB"), the `-c` value of any recipe card the section ships, and the **possible retraction of the guide's currently-published 16 GB `-c 49152`**. Also closes guide line 1014's unprobed "fits".

---

### A2/A3 â€” Depth, drafter, and prefill (one arm, two rows)

**Measures.** Decode t/s at depths ~2k / 16k / 32k / 64k (as each rung's A1-confirmed window allows), **drafter off and on**, logging draft acceptance rate; and the prefill t/s of each fill, which is the **prefill-scaled row rule 10 mandates for any agentic recommendation** and comes free because the fill has to happen anyway.

**Exact conditions.** As A1's flags, plus: q8_0 KV, `--parallel 1`, desktop up, prompts prefixed with a unique identifier so the prefix cache cannot be reused, **n=3 settled probes per point with the first post-prefill probe discarded** (rules 12 and 26). Sampling recorded: `--temp 1.0 --top-p 0.95 --top-k 20 --min-p 0.0` â€” the guide's own recipe sampling, not the ladder's greedy, because that is what a reader runs.

**Wall clock.** ~2 min per point + settling. Scoped to the rungs A1 leaves alive: 3 rungs Ã— 4 depths Ã— 2 drafter states Ã— 3 probes â‰ˆ **2.5â€“3 h**. If A1 kills 12 GB outright, ~1.5 h.

**Who consumes it.** The speed column of the new section's verdict table; the **100k-token wall-clock column** (which cannot be computed honestly without it â€” user memory: wall clock over throughput); the "Expected speed" line of any recipe card; and the correction to the guide's 16 GB and 12 GB roster rows.

**Also settles the single biggest unknown in the whole question: does the MTP draft head still work at 2 bits?** If it does not, the sub-Q4 rungs lose the 1.9Ã— the Q4 recipes get, and the effective ordering can invert.

---

### A4 â€” Scored-benchmark ladder

**Measures.** GSM8K / HumanEval / MBPP, n=25 each, execution-scored, on the **IQ4_XS anchor plus each surviving rung**. The anchor is mandatory: `bench-arm.py:18-21` states this is *"NOT a rule-21 run"*, so its scores are not comparable to the guide's existing 7-benchmark results and need their own in-suite reference point.

**Exact conditions.** `--greedy --score --seed 42 --samples 25 --max-tokens 16384`, suite hash `1cdf54f8eb9d3f8f`, `-c 32768`, `-ctk q8_0 -ctv q8_0`, `reasoning_effort=low`, no drafter. Rule-7 cap raise pre-authorised in the log **before** launch (it already is, for the qwen arm).

**Wall clock.** The in-flight arm is running 62 items in 21 min (~20 s/item) at 49 t/s; larger files run slower. **â‰ˆ 35â€“45 min per rung.** 4 further rungs + anchor â‰ˆ **3â€“3.75 h**, budget **4.5â€“5.5 h** with truncation contingency (gemma's cap raise cost 5,365 s â†’ 9,552 s for an identical score).

**Who consumes it.** The verdict column â€” the "is it worth it" answer, on the instrument rule 6 designates for decisions. Without it the section would rank quants on perplexity alone, which Q6 already proves cannot separate IQ2_XXS from IQ1_M.

---

### A5 â€” UD-IQ2_S infill rung (already in plan, blocked)

**Measures.** The one point inside the 14.47% cliff. Currently a **2.39 GiB / 0.76 bpw hole** between 2.9123 and 2.1529 bpw, and the entire quality cliff is inside it. **Where the cliff starts is unknown.**

**Blocker.** `dl-iq2s.out.log` is 0 bytes â€” the download has produced nothing since 11:17. Diagnose before anything else; the pass-2 loop has been idling on it for 27 minutes.

**Wall clock.** Download (MISSING â€” depends on link) + ~4.7 min perplexity + ~2 min detectors = **~7 min GPU.**

**Who consumes it.** The single most decision-relevant point in the section: whether 2.5-bit-class is above or below the cliff decides whether a 12 GB card has any sub-Q4 option worth naming at all.

---

### A6 â€” Execute probe A (zero GPU)

**Measures.** Run each rung's emitted JavaScript under `node`. F2 proves a rung can pass every detector and emit code that throws on first call.

**Wall clock.** **0 GPU-hours**, ~30 min authoring. Runs now, in parallel with the in-flight arm.

**Who consumes it.** The "Runs?" column of the functional-integrity table. Without it, IQ2_XXS's `verdict=PASS` is published as a quality signal it does not carry â€” a rule-4 violation.

---

### A7 â€” D5: a counter-degeneration detector (zero GPU)

**Measures.** Normalise trailing digits and repeated morphemes, then re-run the run-length checks; or promote `uniq` into the verdict with a threshold. F6 showed D1â€“D4 are blind to `visitedMap21` â‰  `visitedMap22`.

**Wall clock.** **0 GPU-hours.** Re-scores existing `det-*-probeA.txt` files.

**Who consumes it.** Every `verdict=PASS` the section prints at a low rung. Until D5 exists, a PASS below the cliff means less than it appears to, and the section would be publishing a verdict it knows is compromised.

---

## CUT â€” nothing consumes these (rule 25, the who-consumes-this-number test)

| Cut | Cost avoided | Why cut |
|---|---|---|
| q4_0-KV Ã— every rung cross product | ~35 min GPU | The guide already has a measured q4_0 KV price (+0.693%) and already endorses it for 16 GB. No recipe decision changes per rung. **Conditionally reinstate as ONE run** if A1 shows q4_0 is the only way the chosen 12 GB rung reaches a usable window |
| Full rule-21 seven-benchmark suite per rung | ~60 h GPU | The 3-dataset n=25 arm is the screen. Rule 25: *"Prune before you treatâ€¦ never carried through hours of treatment to earn a one-word verdict"* |
| Energy J/token per sub-Q4 rung | ~43.5 min per configuration | No recipe decision in the proposed section turns on it. Goes to the negative register with its price |
| Vision projector on sub-Q4 | ~30 min | The BF16 `mmproj` costs a measured 1,138 MiB regardless of weight quant. On a 12 GB board that is arithmetic, not an arm. Keep one sentence |
| Anything further on UD-IQ1_S | â€” | It FAILED the screen. Rule 25: screened-out files publish both screen numbers and stop |
| A drafter sweep per rung | ~4 h | A2's on/off pair at the guide's shipped n-max 4 / p-min 0.75 is enough to decide *whether* the drafter survives. Only if it does, and only for the recommended rung, does a sweep earn its hours |

---

# PART 4 â€” THE GUIDE SECTION

**Plain summary: one new chapter, placed second-to-last, with five subsections and five tables. It ships at most one new recipe card and may shrink an existing one. Its 8 GB answer is most likely a fence, not a recipe.**

### Heading

> **Below 4 bits: what you lose, and what a smaller card gains**

Two clauses, question-answering, plain â€” matching *"What fits in 24 GB, and where speed collapses"* and *"When 27B is enough, and when it is not"*. No slogan.

### Placement

Insert as **new `#s15`, immediately after `#s14` (Coding agent setups)**, and renumber the existing Sources chapter `s15 â†’ s16`. Sources must stay last; appending as s16 after it would break the document's shape.

**Renumber cost, priced exactly:** section id + `<p class="fno">15</p>` â†’ 16, five h3 ids (`s15-instruments`, `s15-external`, `s15-runs`, `s15-corrections`, `s15-negative`, `s15-repro`), four TOC lines, and **13 cross-references** (`#s15` Ã—3, `#s15-corrections` Ã—3, `#s15-negative` Ã—3, `#s15-repro` Ã—3, `#s15-instruments` Ã—1). ~25 mechanical edits. Bounded.

The alternative â€” folding it into Â§08 as h3 subsections â€” costs zero renumbering but is wrong: the chapter spans quality *and* speed *and* VRAM *and* card class, and Â§08 is already 98 lines.

### Subsections

| id | h3 | Carries |
|---|---|---|
| `s15-ladder` | The quality ladder, measured | Table 1 |
| `s15-integrity` | Where the model stops writing working code | Table 2 |
| `s15-speed` | Smaller files are barely faster | Table 3 |
| `s15-fit` | What fits in 16, 12 and 8 GB | Table 4 |
| `s15-verdict` | The verdict, per card | Table 5 |

### Table 1 â€” the ladder (`s15-ladder`)

Columns: **File Â· Weights (GB Â· GiB) Â· bits/weight Â· Perplexity Â± err Â· vs UD-IQ4_XS Â· bits-per-byte Â· Evidence chip**

Rows: UD-IQ4_XS (anchor, `hl`), UD-Q3_K_XL, UD-IQ3_XXS, **UD-IQ2_S â€” MISSING (A5)**, UD-Q2_K_XL, UD-IQ2_XXS (`hl`, the cliff), UD-IQ1_M, UD-IQ1_S (FAIL).

Footnotes: Q4_K_M 6.5348 is a **prior-campaign anchor, `cited`, not re-run in this ladder**. Comparability scope stated on the table per C7. `n=1` on every row except IQ4_XS (n=2, `delta_pct=0.000`).

### Table 2 â€” functional integrity (`s15-integrity`)

Columns: **File Â· Detector verdict Â· JSON echo Â· Fence discipline Â· Unique-word ratio Â· Does the emitted code run? Â· What its output actually looks like**

The "Does it run?" column is **MISSING until A6**. The last column is where the two-voice law earns its keep â€” one plain sentence per rung ("restarts the file instead of continuing it"; "counts to 29 and stops mid-word"), because that is what the reader can actually act on.

Carries a callout: **the detectors said PASS on output that cannot run, and PASS on output that never finishes the task.** Publishing that instrument gap is not optional â€” F6 is a finding, not an embarrassment.

### Table 3 â€” speed (`s15-speed`)

Columns: **File Â· Decode t/s at depth 218, no drafter (meas, n=1) Â· Decode t/s at 16k depth with drafter (MISSING â†’ A2) Â· Efficiency vs the bandwidth law Â· Speed gained vs UD-IQ4_XS Â· Prefill t/s at that depth (MISSING â†’ A3) Â· 100k-token run, wall clock (MISSING â†’ A2/A3)**

Headline sentence, already licensed today: **2.30Ã— smaller, 1.33Ã— faster.** The ratio is what survives the noise band; the levels are not.

The prefill row is mandatory (rule 10) because this section makes a recommendation for agentic and long-context use, and every wall-clock cell states its prompt:completion ratio.

### Table 4 â€” the fit map (`s15-fit`)

Columns: **File Â· Base VRAM measured on this card (MISSING â†’ A1) Â· Largest fenced window at 16,384 MiB Â· at 12,288 MiB Â· at 8,192 MiB Â· Drafter on/off Â· Deep-fill verdict**

Every budget column chipped as **budget-emulated on a 3090**, never as measured on a 16 GB card. The rule-14 fence (1,181 desktop max + 127 load variance = 1,308 MiB) is stated in the conditions line, not buried.

### Table 5 â€” the verdict (`s15-verdict`)

Columns: **Card class Â· VRAM Â· Best file this page can recommend Â· Window Â· Realistic decode (derived; formula and depth named) Â· Verdict**

**All seven rule-10 roster members appear** (C11 â€” cards the machine cannot represent stay as derived rows, never dropped): NVIDIA 24â€“32 GB, NVIDIA 16 GB, NVIDIA 12 GB, DGX Spark GB10 (128 GB unified, 273 GB/s), Arc Pro B70, Arc Pro B50, Arc B390-class iGPU (LPDDR5X-9600, 2ch, with the single-channel halving caveat). **Plus a new 8 GB class row**, since you asked about it â€” the roster in `REPORT-SPEC.md` Â§7 is a *minimum*, so adding a class is permitted, but the addition must be recorded as a spec amendment.

### Recipe cards

At most **one added**, and only after the recipe lock (rule 25 â€” the cards are written into the campaign log *before* A2 and A4 spend GPU hours):

- **"12 GB class Â· the sub-Q4 alternative"** â€” ships only if A1+A2+A4 show a rung that beats the guide's existing Q4_K_M `-ngl 28` offload path (currently ~6â€“8 t/s derived, `-c 112640`). First line of the `<pre>` is `:: UNVERIFIED â€” DERIVED CONFIG` (C4). Every flag marked `measured-here` or `carried-over-unverified` (C14).
- **"8 GB class"** â€” most likely **no card at all**. If the numbers say no, the section prints the fence and the reason, not a card with a disclaimer. C29: *"publish and disclaim is banned."*
- **The existing 16 GB card at line 619 is EDITED, not duplicated** â€” its `-c 49152` may shrink and its "25â€“50 t/s" band may drop ~17% (S4).

### Verdicts, as shapes

**16 GB card.**
> Stays with **UD-Q3_K_XL** if A1 confirms its base plus a rule-14-fenced window fits inside 16,384 MiB *with the drafter on*, and A4 shows its scored drop against the IQ4_XS anchor sits inside the n=25 noise. Drops to **UD-IQ3_XXS** if the window turns out to be the binding constraint and the scored gap between the two is smaller than the context gained. **And the currently-published `-c 49152` shrinks** if the drafter's 1,008 MiB fixed plus 45,056 B/token push the total past the fence â€” the arithmetic in Part 3 says it lands near 44k, about 5,100 tokens short of what is published today.
>
> *The quality half of this verdict already leans yes:* +2.63% perplexity, every detector clean, complete and correct code. That is measured. The fit half is not.

**12 GB card.**
> Sub-Q4 replaces the guide's current Q4_K_M `-ngl 28` offload recipe **only if** a rung's derived decode at 12 GB-class bandwidth beats the offload path's 6â€“8 t/s **and** its fenced window is usable at that speed. If A1 shows the only rungs that fit are at or below the 14.47% cliff, the verdict is the guide's existing one â€” restated with a measured reason for the first time: **a smaller model, not a smaller quant.**
>
> The arithmetic currently predicts Q3_K_XL does not fit 12,288 MiB at all, and that the rungs which do fit sit at or under the cliff. A5 decides whether anything lives in between.

**8 GB card.**
> **Most likely no, and the section should say so plainly.** Shape: the only rungs whose derived base fits an 8,192 MiB board with a rule-14 desktop fence are at or below UD-IQ2_XXS â€” and UD-IQ2_XXS is the rung that writes a complete, well-structured program which throws `TypeError` on its first call while every detector reports PASS. If A1 confirms that fence and A4 confirms the scored drop, the section publishes the arithmetic, the failure mode, and a negative-register entry â€” **not a recipe.** The answer becomes: at 8 GB the right move is a smaller model at 4 bits, not a 27B at 2.
>
> It flips to yes only if A5's IQ2_S lands **above** the cliff *and* its base plus a fenced window fits 8,192 MiB *and* it executes clean. Three conditions, all currently MISSING.

---

# PART 5 â€” SEQUENCING

**Plain summary: do the free work now, buy the fit map for two hours, lock the recipes, and only then spend the expensive hours. Total GPU is 5â€“11 hours depending on how hard the map prunes â€” one overnight either way.**

The law: *cheap probes buy the map, the map locks the recipes, only locked recipes earn expensive hours.* The map here is A1. Nothing about which rungs deserve scored arms is knowable until A1 says which rungs can hold a window on a real card class.

| Phase | Work | GPU h | Human h | Blocking? |
|---|---|---|---|---|
| **0 â€” now** | Let the in-flight qwen arm finish (~10 min left). In parallel, zero-GPU: **A6** execute probe A, **A7** build D5, **diagnose the 0-byte IQ2_S download**, and run the **republication sweep** on guide lines 175 / 1013 / 1014 / 1443 / 1456 / 1461 | 0 | ~2 | No â€” runs alongside |
| **0.5** | Finish the equal-budget arm; write its ARM line into `decisive.txt`; decide whether gemma's 19 unresolved truncations disqualify the comparison | ~0.2 | 0.5 | Gates the cross-model claim only |
| **1 â€” the map** | **A1** residency + ballast, 4 rungs Ã— budgets Ã— drafter pair, with deep-fill probes | **1.5â€“2** | 0.5 | **Gates everything expensive** |
| **1.5** | **A5** IQ2_S rung, whenever the download lands. Slots anywhere GPU is free | 0.12 | 0 | Gates the 12/8 GB verdict shape |
| **2 â€” the lock** | Write the candidate recipe cards (file Â· window Â· flags Â· effort ceiling Â· expected band) into the campaign log. **Rule 25: nothing expensive starts above the line where those cards are written.** Also pre-register the kill criteria from Part 6 | 0 | 1 | **Hard gate** |
| **3 â€” depth** | **A2/A3**, scoped to the rungs Phase 1 left alive | **1.5â€“3** | 0.5 | Gates every speed and wall-clock cell |
| **4 â€” scored** | **A4**, IQ4_XS anchor + surviving rungs only | **3â€“5.5** | 0.5 | Gates the verdict column |
| **5 â€” synthesis** | Ladder synthesis â†’ **blind-report Â§08 second pass** (the only scoped consumer) â†’ then the new guide Â§15 â†’ renumber Sources to Â§16 â†’ **re-cut `example-report.html` in the SAME commit** | 0 | 3â€“4 | â€” |
| **6** | Gates 3 + 4 close â†’ launch reminder fires | 0 | 0.2 | â€” |

**Total GPU: 6.3â€“10.8 h.** Overnight-shaped. If A1 kills 12 GB outright, Phases 3+4 collapse to ~4.5 h and the total is ~6.5 h.

### Three sequencing constraints that are not negotiable

1. **Blind report before guide.** `REPORT-SPEC.md`'s republication rule and the example pin both run *source â†’ derivative*. `example-report.html:2087` pins to the live guide at commit `092ee66`; any correction to the guide obliges re-cutting or re-pinning that file **in the same commit**. So: blind report Â§08 â†’ guide Â§15 â†’ example re-cut, and the last two share a commit.
2. **The republication sweep does not wait for the chapter.** Pass-1 landed 2026-08-24; the sweep is already overdue. Ship it in Phase 0 as its own commit. Do not let a new chapter be the reason a now-false negation stays on a public page.
3. **The recipe lock is a gate, not a summary.** If Phase 2 is skipped, Phase 4's 3â€“5.5 hours are being spent on rungs nothing has committed to recommending â€” which is exactly the failure rule 25 exists to prevent.

---

# PART 6 â€” RISKS, AND WHAT WOULD MAKE THE ANSWER "NO"

**Plain summary: the strongest signal in the data today already points at "no", and it should be pre-registered as a kill criterion before any expensive hour is spent. A campaign that can only conclude yes is not measuring.**

## Kill criteria â€” write these into the log at Phase 2, before A2 and A4 run

**R1 Â· Speed never arrives. (Already 70% confirmed.)**
The efficiency constant collapses 0.61 â†’ 0.35. IQ4_XS â†’ IQ2_XXS is 1.96Ã— smaller and only 1.24Ã— faster. If A2 confirms this shape at 16k/32k depth, then sub-Q4 buys VRAM and nothing else â€” and on any card that can already hold Q3_K_XL there is no speed argument for going lower.
*Evidence that decides it:* A2's t/s-vs-file-size at depth being flat or sub-linear. *Kill if:* the derived decode for the recommended 12/16 GB rung fails to beat the guide's existing offload path by more than the noise band.

**R2 Â· The drafter dies at low bit-width. (Completely MISSING.)**
Every Q4 recipe in the guide ships `--spec-type draft-mtp` and banks roughly 1.9Ã—. Nothing in this ladder ran a drafter at all. If a 2-bit model's draft head has poor acceptance, the ordering inverts: **Q4 with a working drafter beats IQ2 without one**, and the whole sub-Q4 case evaporates.
*Evidence:* A2's drafter-on/off pair per rung with acceptance rate logged. *Kill if:* acceptance at the recommended rung falls far enough that drafter-on t/s is inside noise of drafter-off â€” the rung loses the 1.9Ã— while still paying 1,008 MiB + 5,120 B/token for it.

**R3 Â· Functional integrity fails on real work, not on probes. (Already visible.)**
IQ2_XXS writes a complete, well-structured, correct-heap program that throws `TypeError` on its first `addEdge`. Every detector said PASS. Perplexity moved 1.67% between IQ2_XXS and IQ1_M and could not separate a rung that writes a whole program from one that counts to 29 and stops mid-word.
*Evidence:* A6's execution check and A4's execution-scored HumanEval/MBPP. *Kill if:* execution pass@1 steps down at or above the cliff by more than the perplexity curve predicts â€” which would mean perplexity is systematically flattering sub-Q4 files, and the section's ranking instrument is the wrong one.

**R4 Â· The window never materialises.**
If A1 shows that on 12,288 MiB the only fitting rungs leave under ~32k of fenced context, the reader's real daily-driver window is *worse* than the Q4_K_M `-ngl 28` path the guide already ships at `-c 112640`.
*Evidence:* A1's fit map. *Kill if:* fenced window at 12 GB < the offload recipe's, at comparable speed.

**R5 Â· The 12B wins at equal bytes.**
gemma-4-12B-QAT-Q4_0 scored mean **73.30**. The qwen IQ2_XXS partials (GSM8K 80.0, HumanEval 84.0) are ahead â€” but the arms are **not condition-matched by the ledger's own admission** (`bench-arm.py:23-29`: qwen gets q8_0 KV and `reasoning_effort=low`; gemma gets defaults â€” *"a deliberate conditions difference, not a fair-fight claim"*), and gemma's arm carries **19 unresolved truncations that doubling the cap did not change** (identical mean, identical scores, identical 19, wall time 5,365 s â†’ 9,552 s).
*Kill if:* the finished qwen mean lands below 73.30. Then the 8/12 GB answer is "buy a 12B", and the sub-Q4 chapter becomes a redirect rather than a recommendation.

**R6 Â· A regime collision the section would inherit.**
The guide's measured 3090 row is **40 t/s** for Q4_K_M at `-c 122880`, depth-averaged over a 100k run, no drafter. The ladder measured **40.02 t/s** for UD-IQ4_XS at depth 218, `-c 8192`, no drafter. Two different files, two different regimes, the same number. Those cannot both be published beside each other without the arithmetic joining them â€” rule 26: *"a page carrying both 'a 45% swing' and 'Â±25%' with nothing joining them has two noise floors and therefore none."*
*Resolve before publishing:* one A2 point at Q4_K_M, `-c 122880`, matching the guide's regime. Until then, S4's "the 16 GB band is ~17% high" is a strong suspicion, not a correction.

**R7 Â· The section retracts a live recipe instead of adding one.**
The derived arithmetic puts the guide's 16 GB `-c 49152` at roughly 5,100 tokens over a rule-14 fence once the drafter's fixed and per-token costs are booked. If A1 confirms it, the correct outcome of this whole effort is **shrinking a published recipe**, not adding a chapter that praises sub-Q4. That is a legitimate and valuable result. It must not be softened into a footnote.

## Standing publication limits â€” true regardless of what the arms find

- **No residency verdict is obtainable for any card the rig does not own.** Rule 13b closes this permanently. The 12/16/8 GB columns can never be stronger than a derived expectation plus a budget-emulated fit test. The honest closing move is a negative-register entry naming the card loan or purchase that would close it, with its price in machine time (`REPORT-SPEC` Â§16, C30).
- **The realistic number must headline.** Rule 2. Not the depth-218, no-drafter, cold-server, bare-desktop, n=1 best case. Best cases get labeled as best cases with the condition that produced them, and the header strip carries **four** bands â€” floor Â· short-context Â· at-depth (naming the depth) Â· ceiling â€” not three (C28).
- **Publish-and-disclaim is banned** (C29). If sub-Q4 turns out not to be worth it, the section says so in its first paragraph. It does not print an attractive t/s and annotate it away, because the disclaimed number is still the most quotable one on the page.
- **The instrument gaps get published, not hidden.** F6 (detectors blind to counter-incrementing degeneration) and F2 (a PASS on code that cannot run) are findings this ladder produced. They belong in the section, because they bound how much any low-rung `PASS` is worth.

## The meta-risk

Every remaining arm in this plan is capable of producing a "no". A1 can say nothing fits. A2 can say nothing is faster and the drafter is dead. A4 can say the scores fall off a cliff the perplexity curve hid. A5 can say the cliff starts higher than hoped. R5 can say buy a different model. **Pre-register R1â€“R5 in the campaign log at Phase 2, with their thresholds, before a single expensive hour is spent** â€” that is the only structural guard against a campaign that can only conclude yes.

---

## Key paths

- Guide: `E:\chinkeong.github.io\qwen-27b\index.html` â€” Â§05-budget at 993â€“1033 (the two-constant model), Â§07 roster at 1383â€“1451, Â§08 at 1453â€“1550, insertion point at 1961/1963, Sources Â§15 at 1963â€“2085, TOC at 128â€“168
- Ladder ledgers: `E:\AI\measured-inference\results\qwen38-27b-blind\data\quant-ladder\{results.txt,detectors.txt,decisive.txt,heartbeat.txt}`
- In-flight arm: `...\data\quant-ladder\bench\arm-qwen-iq2xxs.console.log`
- Blocked download: `...\data\quant-ladder\dl-iq2s.out.log` (0 bytes), `enable-UD-IQ2_S.flag`, idling loop in `chain-ladder-pass2.out.log`
- Raw probe artifacts (the F2/F4/F5 reads): `...\data\quant-ladder\det-<rung>-probeA.txt`
- Server logs carrying the t/s in Part 2A: `...\data\quant-ladder\srv-det-<rung>.err.log`
- Scripts: `E:\AI\measured-inference\scripts\quant-ladder\{ladder-manifest.json,run-ladder.ps1,detectors.ps1,ladder-lib.ps1,bench-arm.py,decisive-arm.ps1}`
- Law: `E:\AI\measured-inference\methodology\METHODOLOGY.md`, `E:\AI\measured-inference\templates\REPORT-SPEC.md` (rules 1, 2, 3, 6, 10, 12, 13, 14, 16, 25, 26; Â§7 roster; Â§16 register)
- The pin that forces the same-commit re-cut: `E:\AI\measured-inference\templates\example-report.html:2087`
- Registers: `...\work\staleness-registers.md` (B12 at 520â€“522), `...\work\gen2-rewrite-brief.md` (318â€“327, 338â€“341)