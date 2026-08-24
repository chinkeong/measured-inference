VERDICT: the report is safe to publish after four framing/staleness fixes. The GUIDE is NOT safe to publish as it stands â€” it carries two arithmetically wrong reader-facing numbers.

WHAT PASSED (both documents). Every ladder figure â€” GiB, bpw, perplexity, Mean, per-benchmark, empty/silent, truncations, median tokens â€” matches the dataset exactly. I re-derived independently and all reproduce: perplexity deltas vs 6.5956 (+2.63/+4.90/+6.07/+14.44/+21.41/+23.44/+35.34%); drafter multipliers 2.05x and 1.69x; +7.8% off / +12.9% on / 45% larger; -9.8% acceptance, -10.9% draft length, -11.4% throughput; batching +22.0% / -35.4% and the ~55% wait (12.63 s vs 8.16 s); 34% at depth, +18.8% drafter, 962 MiB, fence 1,181+127=1,308, clears by 409, short by 553; 218,233/262,144 = 83%; 424 s at 514.7 t/s; VRAM under-prediction +1,214/+1,212 -> 1,213; +605 MiB on the report's own 262,144 cell; the report's marginal-cost table (2.55/1.07/1.08/5.82/5.91/3.34/19.28 % per GiB, median 1.08, 5.4x/5.5x/2.4x/3.1x/17.8x) and its standard-error figures (2.7/2.2/1.1/7.7/5.9/1.7, bars clearing by 0.02); 2.30x shrink vs 1.33x speed; gemma 5.3 points and 18-of-18 / 22-of-22 / 15-of-16 against 19 truncations. All nine McNemar rows are exact in both. Both state the boundary as the 2.48-2.15 bpw INTERVAL and never a point. IQ3_XXS vs Q2_K_XL carries an explicit "no ordering claim exists" in both. IQ2_XXS vs IQ1_M is written as noise with b=5 c=10 printed, never as a reversal, in both. Every 16 GB and 12 GB claim is chipped DERIVED/unmeasured in both, and both say outright that speed and fit on such a card are not measured. Both include their own accuracy ladder in the n=25 warning class. Empties and truncations are separate columns everywhere both appear. The guide's section 08 callout no longer asserts the old per-gigabyte reason for stopping at 9 GiB â€” it names it as retired and wrong. The section 06.06 quarantine is lifted with the corrected figures in both.

=== DEFECTS REMAINING ===

GUIDE â€” E:\chinkeong.github.io\qwen-27b\index.html
(Note: this file was edited at 02:38, mid-review; all findings below are against the current on-disk version.)

G1. WRONG NUMBER, twice. Line 1527 (section 08 "How far down can you go?" callout) and line 1631 (section 08-ladder table, UD-IQ1_S verdict cell) both read "...one arm took two and a half hours where every other took under thirty minutes." FALSE. Ground truth, data/quant-ladder/bench/arm-qwen-iq2s-wall.json: UD-IQ2_S ran wall_s 2,166.0 = 36 minutes. (Full ledger: 1,141.1 / 1,378.4 / 1,182.0 / 1,172.1 / 2,166.0 / 1,705.0 / 1,765.9 / 8,965.3 s.) The report's own table prints 36 m for that arm, so the guide also contradicts its companion document.
FIX: replace "where every other took under thirty minutes" with "where the next longest took thirty-six minutes" in both places.

G2. WRONG RATIO. Line 2192 (section 15-runs, accuracy-ladder entry): "the bottom rung took 8,965.8 s â€” two and a half hours, five times any other arm". 8,965.8 / 2,166.0 = 4.14x, not 5x. (The "five times" is inherited from campaign.md line 1383, which is itself loose.) The same entry's earlier clause, "most took under thirty minutes each", is correct and should stay.
FIX: "...two and a half hours, more than four times the next-longest arm".

G3. WRONG NUMBER â€” batching latency, direction and magnitude. Line 1110 (section 06 flag list, --parallel bullet): "the whole cost is that each user waits about 35% longer for their own tokens." A per-slot fall of 35.4% is a wait 1/0.646 = 1.55x, i.e. ~55% longer. The report explicitly corrected this same campaign-log wording; the guide still carries the wrong version.
FIX: "...each user waits about 55% longer for their own tokens â€” 12.6 s against 8.2 s for a 700-token answer."

G4. WRONG NUMBER â€” same error, inverted. Line 861 (section 03-axes, --parallel 1 vs 2 row): "Every recipe still ships --parallel 1, now because one user gets their tokens 35% faster that way." Going from --parallel 2 to --parallel 1 is 85.79 / 55.41 = +54.8%, not +35%. 35.4% is the loss in the other direction only.
FIX: "...now because one user gets their tokens about 55% faster that way (85.79 against 55.41 t/s per slot)."

G5. COUNT INCONSISTENCY. Line 281 (section 02 glossary, "rung, and the ladder"): "Â§08 measures nine of them", hyperlinked to #s08-ladder â€” whose heading is "The quantization ladder: eight files of one model" and whose table has eight rows. The ninth file (NVFP4-MTP-VERY-LOW, 4.404 bpw) appears nowhere in the guide's ladder.
FIX: "Â§08 measures eight of them" (or re-point the "nine" at the perplexity ladder described in the header).

G6. MINOR, unit consistency. Line 1687 (section 08-cards, 12 GB row): "9.154 GiB of weights on a 12 GB board leaves roughly 2.8 GB". 12 GiB âˆ’ 9.154 GiB = 2.85 GiB = 3.06 GB; 12 decimal GB âˆ’ 9.83 GB = 2.17 GB. The "2.8" is a GiB figure wearing a GB label. The value is supplied verbatim by the dataset so I did not treat it as an error, but the guide's own "Units, because they bite" paragraph (line 1542) makes the mislabel conspicuous.
FIX (optional): "...leaves roughly 2.8 GiB".

REPORT â€” E:\AI\measured-inference\results\qwen38-27b-blind\index.html

R1. WRONG RATIO, contradicted by the document's own table. Line 3181 (section 08.04, accuracy-table footer row): "That is why its wall clock is five times any other arm's". The table immediately above prints 2 h 29 m against a 36 m UD-IQ2_S arm â€” 4.1x. Against the next-longest arm after that (29 m) it would be 5.1x, but the claim as written is falsified by the adjacent cell.
FIX: "...why its wall clock is more than four times the next-longest arm's".

R2. STALE ROUND COUNT â€” four places, now contradicted by the document's own round-8 row, section 15.01 ledger row and register entries 8 and 9.
  - Line 554, section 01 h2: "One model, one card, six rounds of measurement." -> "eight rounds".
  - Lines 593-595, section 01.01 lead: "Six measurement rounds ran on one machine across 2026-08-23 and 08-24 ... plus a seventh zero-GPU pass on 08-24" -> eight rounds, 2026-08-23 to 08-25, with the two zero-GPU passes named.
  - Line 396, hero lede: "across six rounds" -> "across eight rounds".
  - Lines 5835-5839, footer "About this page": "Measurement ran across six rounds on one machine ... A seventh piece of work used no GPU at all" â€” omits round 8 (the accuracy ladder, the drafter pair, the batching pair and the full-window trial) entirely. Add a round-8 sentence.

R3. STALE DATE RANGE â€” the 2026-08-25 work is absent from all four page-level date stamps, while the hero lede itself says "A follow-up pass on 2026-08-24 and 2026-08-25".
  - Line 7, meta description: "measured 2026-08-23 to 08-24" -> "to 08-25".
  - Line 375, top tag: "measured 2026-08-23 to 08-24" -> "to 08-25".
  - Line 391, hero eyebrow: "Measured on one machine Â· 2026-08-23 to 08-24" -> "to 08-25".
  - Line 5882, footer-bottom: "cut 2026-08-24" -> the 08-25 cut date.

R4. INTERNAL ARITHMETIC CONFLICT on the campaign GPU total. Line 399 (hero lede): "totalling about 19 h 16 m of GPU time (12 h 53 m over rounds 1-5, about 6 h for the ladder)". The rounds table (line 611) gives rounds 1-5 as 13 h 14 m and round 6 as 6 h 03 m; 12 h 53 m + 6 h 03 m = 18 h 56 m, not the 19 h 16 m stated in the same sentence. The 12 h 53 m figure omits round 3's 21-minute 08-24 raised-cap re-run, which the table counts. (Same 20-minute gap makes line 611's own components â€” 13 h 14 m + about 6 h + 5 h 39 m â€” land at 24 h 53-56 m against its stated "roughly 24 h 55 m"; that one is inside its hedge.) The hero stat itself, 19:16 relabelled "rounds 1-6" with "(round 8 adds 5:39 of scored arms)", is correct.
FIX: change the parenthetical to "(13 h 14 m over rounds 1-5, 6 h 03 m for the ladder)".

PUBLICATION CALL. The report's defects are framing and staleness plus one ratio (R1) â€” none of them touches a measured value, a tie, a boundary or a provenance chip; fix R1-R4 and it is safe. The guide must not ship as-is: G3 and G4 are wrong numbers in the advice a reader acts on, and G1/G2 are claims its own companion document's table disproves.