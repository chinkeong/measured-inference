I verified every BLOCKER against the file and the ledgers. I also found one thing all four gates missed: **`results.txt` was written at 12:34:27 on 08-24, eight minutes after the page was cut at 12:26:11** â€” the "still measuring" rung has landed.

---

# VERDICT

**SAFE TO PUBLISH ONCE THE BLOCKERS ARE FIXED: YES.**
**12 BLOCKERS.** No finding survives that undermines a measurement itself â€” every ladder figure, every judged score, every bootstrap interval re-derives exactly from the ledgers. All 12 blockers are either stale text the day's landings outran, or a within-page contradiction. Two derived numbers do not reproduce (B9 interval sign, B10 ratio column); both have exact corrections below.

**Fix S1 in the same pass as B10** â€” it is a false statement about the page's own printed error bars and I would not ship without it, though all four gates rated it SHOULD-FIX and I defer to that ranking.

---

# BLOCKERS

## B1 â€” Â§01.01 round-6 row doubles the campaign's strongest reproducibility claim
**Anchor:** `Two published anchors reproduced (one twice at 0.000&nbsp;% drift)` (line 578)
**Verified:** `results.txt` has three RIGGATE lines â€” two for `UD-IQ4_XS` (`expected=6.5956`, a real prior anchor) and one for `NVFP4-MTP-VERY-LOW` whose `expected=6.8774` was set to its own measured value. Â§08.03 line 2823 says in bold *"That is one anchor reproduced twice, not two anchors."* The summary table a reader meets first publishes exactly the claim Â§08.03 exists to kill.
**Replace with:** `One published anchor reproduced twice at 0.000&nbsp;% drift and one first measurement gated against its own value, which is arithmetic and not a reproduction (<a href="#s08-03">&sect;08.03</a>); one resolved same-size pair; one withdrawn instrument reading`

---

## B2 â€” The `UD-IQ2_S` rung has landed. The page says five times that it has not. *(missed by all four gates)*
**Verified:** `data/quant-ladder/results.txt`, last line, mtime 12:34:27 â€” after the page's 12:26:11 cut:
`RESULT UD-IQ2_S | role=pass2 | GiB=7.797 | bpw=2.4806 | PPL=7.5481 | err=0.05383 | bpb=0.6715 | ts=2026-08-24T12:34:27`
`detectors.txt`: `DETECT UD-IQ2_S | verdict=PASS | ... words=372 | uniq=0.5081 | tpsA=47.85`
`chain-ladder-pass2.out.log` then evaluated one further rung and declined it â€” `pass2 UD-IQ3_S: not enabled (ratio 0.84 < 1.5)` â€” and has been idle since 12:35:01. **The ladder is closed at nine files of this model.**

**B2a â€” ladder table.** Anchor: the `<tr class="hi">` for `UD-Q2_K_XL`. Insert immediately after it:
```html
<tr><td><code>UD-IQ2_S</code> <span class="small">the cliff begins</span></td><td class="num">7.797</td><td class="num">2.481</td><td class="num">7.5481 &plusmn; 0.054</td><td class="num">+14.44&nbsp;%</td><td class="num">0.6715</td><td>PASS</td></tr>
```
(+14.44 % = (7.5481âˆ’6.5956)/6.5956.)

**B2b** â€” Anchor: `<b>The ladder.</b> One model, eight files.` â†’ `<b>The ladder.</b> One model, nine files.`

**B2c** â€” Anchor: `Round 6 ran the same model at eight sizes, from 4.22 bits per weight down` â†’ `Round 6 ran the same model at nine sizes, from 4.40 bits per weight down`

**B2d** â€” Anchor: `<a href="#s08-04">&sect;08.04</a> ranks <b>eight</b> files of this model from` â€¦ `4.22 bits per weight to 1.83` â†’ `ranks <b>nine</b> files of this model from 4.40 bits per weight down to 1.83`
*(Both bpw ranges excluded `NVFP4-MTP-VERY-LOW` at bpw=4.4036 â€” a file inside the eight they claimed to bound.)*

**B2e â€” replace the whole "What is still measuring" paragraph.** Anchor: `<p><b>What is still measuring.</b> One rung, <code>UD-IQ2_S</code> at`
```html
<p><b>Where the cliff starts.</b> One rung, <code>UD-IQ2_S</code> at
7.797&nbsp;GiB, sits <em>inside</em> the cliff &mdash; between the knee at
9.154 and <code>IQ2_XXS</code> at 6.767. The ladder's own steepening rule
enabled it automatically, and it landed at 12:34 on 2026-08-24 at
<b>7.5481</b>. It answers the question it was enabled to ask. The two halves
of the cliff cost <b>5.82</b> and <b>5.91&nbsp;% per GiB</b> &mdash; near
enough the same &mdash; so the steep regime does not begin somewhere inside
the interval: it begins immediately below the knee, at 2.91 bits per weight.
Both halves are resolved far outside the error bars (7.7 and 5.9 standard
errors). The rule then evaluated one further rung, <code>UD-IQ3_S</code>, and
declined it &mdash; ratio 0.84 against a threshold of 1.5 &mdash; so the
ladder is closed.</p>
```

**B2f â€” Â§01.01 round-6 row.** Anchor: `Eight files of this model ranked on 294,912 scored positions each` â†’ `Nine files of this model ranked on 294,912 scored positions each`. Anchor: `One rung inside the cliff was still measuring at publication and is marked there.` â†’ delete. Anchor (window cell): `08-23 14:13 &ndash; 08-24` â†’ `08-23 14:13 &ndash; 08-24 12:35`. Anchor (caption): `The ladder was still running when this draft was cut.` â†’ `The ladder finished on 2026-08-24 at 12:35.`

**B2g â€” Â§15.01 rounds ledger.** Anchor: `<span class="small">14:13 &rarr; running</span>` â†’ `<span class="small">08-23 14:13 &rarr; 08-24 12:35, ~6 h GPU</span>`. In the same row's raw-material cell, add `<code>decisive.txt</code>` (the equal-budget ledger Â§08.04 depends on) to the file list.

**B2h â€” Â§15.03 entry 18.** Anchor: `<h4>18. The quantisation ladder &mdash; <span style="color:var(--good)">landed 2026-08-24</span>, with one rung outstanding</h4>` â†’ drop `, with one rung outstanding`. Replace the two "outstanding" paragraphs (`<p><b>What is still outstanding, and it is the interesting one.</b>` through `both queued</p>`) with:
```html
<p><b>The rung that located the cliff.</b> <code>UD-IQ2_S</code> at
7.797&nbsp;GiB was enabled automatically by the steepening rule &mdash; bracket
gap 14.47&nbsp;% against a 1.11&nbsp;% reference, ratio 13.0 against a
threshold of 1.5 &mdash; and landed at 12:34 on 2026-08-24 at PPL 7.5481,
detectors PASS. The two halves of the cliff cost 5.82 and 5.91&nbsp;% per GiB,
so the cliff begins at the knee rather than somewhere inside the interval.
The rule then declined <code>UD-IQ3_S</code> (ratio 0.84) and the ladder
closed at nine files.</p>
<p><b>The Qwen equal-budget arm.</b> Its raised-cap re-run landed at 12:29 on
2026-08-24 with identical scores &mdash; mean 78.70, one MBPP truncation
surviving the doubled cap &mdash; so its status is now symmetric with the
comparator's and its provisional mark is gone.</p>
<p class="price">Price paid: ~6 h GPU. Nothing outstanding.</p>
```

---

## B3 â€” The Qwen equal-budget raised-cap re-run has landed; three places still call it queued
**Verified:** `decisive.txt`: `ARM qwen-iq2xxs-cap32k | cap=32768 | mean=78.70 | GSM8K=80.0 HumanEval=84.0 MBPP=72.0 | truncations=1 | ts=2026-08-24T12:29:01`. Identical scores; the rule-7 remedy did **not** clear the truncation.
**Fix:**
- Anchor: `<b>78.70</b> <span class="pv h">PROVISIONAL</span>` â†’ `<b>78.70</b>` (delete the chip).
- Anchor: `The Qwen arm's own single truncation triggered the same raise-the-cap rule, which is why its Mean is marked provisional here.` â†’ `The Qwen arm's own single truncation triggered the same raise-the-cap rule; that re-run has landed and returned identical scores with the one MBPP truncation still present at the 32,768 cap &mdash; the same outcome as the comparator's.`
- Entry 18 handled in B2h.

*(Gate 2 also asked for an ARM line to be appended to `decisive.txt`. It is already there. No ledger edit.)*

---

## B4 â€” Hero evidence tier describes an instrument the opposite of the one that ran
**Anchor:** `and the judgements about writing quality
    are one run each, by one judge who could see which setting produced
    what.` (lines 409-413)
**Verified:** `judge-scores.json` â€” 3 blind seats, `answers_rated 150 / answers_total 150`, `missing []`, `partial []`; key sealed in `key-SEALED.json`; per-seat shuffle seed. The unblinded single-judge caveat is true only of Â§09.04's n=1 authoring task.
**Replace the Smoke-tier sentence with:**
```
525 generations across three thinking levels, <b>all 525 now scored</b> &mdash;
five sets marked mechanically, and the two open-ended writing sets read on
2026-08-24 by a blind three-seat Claude Opus&nbsp;5 panel with the arm map
sealed in a key no seat opened (<a href="#s09-judge">&sect;09.09</a>), whose
stated limit is that judge and author are both Claude models. The one
remaining unblinded, single-judge quality reading is &sect;09.04's n=1
authoring comparison, and it is labelled there.
```
**Same pass, four more:**
- Line 436 hero stat: `<dt>Benchmark generations &mdash; 375 of them scored</dt><dd>525` â†’ `<dt>Benchmark generations &mdash; all 525 scored</dt><dd>525`
- Line 4280 Â§13.01: `Five scored benchmark sets ran at 25 questions each across three effort
  levels &mdash; <b>375 scored generations</b> out of the 525 the suite produced` â†’ `Seven scored benchmark sets ran at 25 questions each across three effort levels &mdash; <b>all 525 generations scored</b>, five mechanically and two by the blind judge panel of &sect;09.09`
- Lines 394-399 / 436: `across five completed
    rounds on 2026-08-23` â€¦ `<b>12&nbsp;h&nbsp;53&nbsp;m of GPU time</b>` â†’ `across six rounds, five on 2026-08-23 and the ladder finishing 2026-08-24, totalling about <b>18&nbsp;h&nbsp;55&nbsp;m of GPU time</b> (12&nbsp;h&nbsp;53&nbsp;m over rounds 1&ndash;5, about 6&nbsp;h for the ladder)`; stat tile `<dt>GPU time measured, five rounds, one machine</dt><dd>12:53` â†’ `<dt>GPU time measured, six rounds, one machine</dt><dd>18:55`
- Lines 414-421, the round-6 paragraph: `A sixth round opened at 14:13 and was still running when this
    draft was written; its GPU time is not in the total above.` â€¦ `So far it has re-run this page's own quality
    score for the shipped file and got the same answer twice, settled one
    file-against-file comparison, and thrown out one reading as a broken
    instrument` â†’ `A sixth round opened at 14:13 on 2026-08-23 and finished at 12:35 the next day. It is a <em>size ladder</em>: the same model squeezed into smaller and smaller files, to find where quality breaks. It ranked nine files of this model from 4.40 down to 1.83 bits per weight, found that the point where quality turns (9.154&nbsp;GiB) and the point where the model stops working (below 6.267&nbsp;GiB) are different rungs, ran a cross-model arm at an equal weight budget, reproduced this page's own quality score for the shipped file twice, and threw out one reading as a broken instrument`
- Â§01.01 total row: `<b>Total GPU time, rounds 1&ndash;5: 12 h 53 m.</b>` â†’ `<b>Total GPU time: 12 h 53 m over rounds 1&ndash;5, about 6 h for round 6 &mdash; roughly 18 h 55 m.</b> Round 6's figure is the sum of the ledgers' own <code>wall_s</code> fields (2,990 s of perplexity plus 18,767 s of equal-budget arms = 6 h 03 m) and does not include the detector probes or the eleven-arm gemma isolation.`

---

## B5 â€” Â§09.02's lead paragraph denies the numbers in the table twelve lines below it
**Anchor:** `525 generations, of which <b>375 are scored</b>` â€¦ `<b>ALPACA and MT-Bench ran unscored with their transcripts kept</b>` â€¦ `<b>composite index over five scored sets</b>, not an accuracy.` (lines 3114-3122)
**Verified:** the table at 3134-3137 prints ALPACA 70.2 / 75.1 / 72.9, MT-Bench 80.7 / 85.3 / 79.7 and a seven-set Mean row. The table's own counting note even says *"unscored when this count was taken, judged since."*
**Replace the paragraph's second half with:**
```
That is 175 prompts per arm and 525 generations, <b>all 525 now scored</b>.
Five sets are marked mechanically. The other two need a judge model; there
was none on this machine when round 3 ran, so ALPACA and MT-Bench were kept
as transcripts and scored on 2026-08-24 by the blind three-seat panel of
<a href="#s09-judge">&sect;09.09</a> &mdash; a model must never judge its own
outputs, and these answers are Qwen's. Both composites are printed below: the
five-set index because every earlier comparison on this page is against it,
and the seven-set index because that is what the protocol specifies.
```

---

## B6 â€” Â§09's opening and its closing guidance both deny the finding Â§09.09 makes between them
**Verified:** Â§09.09 reports `medium` over `xhigh` on MT-Bench, +0.51, 95 % interval +0.21 to +0.80, 14Â·3Â·8, verdict DIFFERENT (`judge-paired.json`: `mean_diff_b_minus_a âˆ’0.507, ci95 [âˆ’0.8, âˆ’0.213]`), and calls it *"the first thing in this campaign that separates the effort levels at all."*

**B6a** â€” Anchor: `On this evidence,
effort buys time and electricity, not measurable quality.` â†’ `On the five mechanically scored sets, effort buys time and electricity and no measurable quality. On the two judged writing sets it does: <a href="#s09-judge">&sect;09.09</a> separates <code>medium</code> from <code>xhigh</code> on MT-Bench, and that is the campaign's only measured quality difference between effort levels.`

**B6b** â€” Anchor: `This page crowns none of the three.` â†’ `No level is crowned on the mechanically scored suite; &sect;09.09's task-specific split on writing is the one exception and is stated there.`

**B6c** â€” Anchor: `Pick by what you can afford in
  time and electricity, not by expected quality, because the quality difference
  between the three did not survive measurement at this sample size.` â†’ `Pick by what you can afford in time and electricity, because on the five mechanically scored sets the quality difference between the three did not survive measurement at this sample size. On the two judged writing sets it did: <a href="#s09-judge">&sect;09.09</a> puts <code>medium</code> ahead of <code>xhigh</code> on MT-Bench.`

**B6d** â€” Anchor: `<b>No level is crowned anywhere on this page</b>, and nothing below should be read as one.` â†’ `<b>No level is crowned on the mechanically scored suite</b>; &sect;09.09's judged split on writing is the one exception and is named in the cells below.`

**B6e** â€” In the guidance table's `Use it when` cells, add: `medium` â†’ `â€¦and it is the level to use for open-ended writing: the blind panel of &sect;09.09 put it ahead of <code>xhigh</code> on MT-Bench, measured and paired.`; `xhigh` â†’ append `Not for open-ended writing &mdash; &sect;09.09 measured it behind <code>medium</code> there.`

---

## B7 â€” Â§09.09's "twice out of two" is falsified twice on the same page
**Anchor:** `deliver the whole specification with no fatal defect, twice out of two.` (line 3626)
**Verified:** line 3248 â€” *"`xhigh` produced nothing at all on its first run."* Line 1282 â€” *"at that cap one of two samples truncated and returned no usable file after 21 minutes and 120 Wh."* Â§09.10's own xhigh row repeats it. This sentence is the sole justification offered for the new "xhigh for hard code" advice.
**Replace with:** `deliver the whole specification with no fatal defect &mdash; at n=2, and only on the run that had a cap it could reach. The other run hit the 65,536-token cap and returned nothing at all (&sect;09.04). That is a categorical finding at n=2 with a cap condition attached, and it stands only with both.`

---

## B8 â€” Â§15.01's instrument register denies a whole class of number the page publishes
**Anchor:** `ALPACA and MT-Bench need a judge model and are unscored.` (line 4452)
**Verified:** six judged scores, a seven-set Mean and six bootstrap intervals now ship; entry 11 declares the gap closed. The caption promises *"Every class of number on this page and the instrument behind it"* and there is no judge row at all â€” no rubric, no seat count, no normalisation, no `scripts/bench/judge-panel.py`, no correlated-instrument note, and no rounds-ledger row for `data/judge/`.
**Fix, three parts:**
1. Delete that sentence; end the Benchmark-scores row's note at `the generations are untouched.`
2. Add a register row directly beneath it:
```html
<tr><td><b>Judged writing scores</b></td><td><code>rule21-judge-panel-v1</code> &mdash; three blind Claude Opus&nbsp;5 seats, standard 1&ndash;10 single-answer rubric, normalised <code>(r&minus;1)&divide;9&times;100</code>, opaque salted ids with the map sealed in <code>data/judge/key-SEALED.json</code>, a separate shuffle seed per seat; <code>scripts/bench/judge-panel.py</code></td><td>ALPACA and MT-Bench turn 1, 150 answers, 450 ratings, none missing, scored 2026-08-24. <b>Known quirk:</b> the judge and this report's author are both Claude models &mdash; a <em>correlated</em> instrument, disclosed with every number. A seat sees several answers to the same question inside one shuffled batch. Paired comparisons are a 20,000-resample bootstrap, seed 42, in <code>data/judge/judge-paired.json</code>.</td></tr>
```
3. Add a rounds-ledger row after round 6:
```html
<tr><td><b>Judge pass</b><br><span class="small">2026-08-24, zero GPU</span></td><td><a href="#s09-judge">&sect;09.09</a></td><td><code>data/judge/</code> &mdash; <code>packets/</code>, <code>ratings/</code>, <code>key-SEALED.json</code>, <code>judge-scores.json</code>, <code>judge-paired.json</code>. Builder, scorer and paired test: <code>scripts/bench/judge-panel.py</code>.</td></tr>
```
Also Â§01.01: `Six rounds ran on one machine on 2026-08-23` â†’ `Six measurement rounds ran on one machine across 2026-08-23 and 08-24, one job on the card at a time, plus a seventh zero-GPU pass on 08-24 &mdash; the judge panel.` Add the matching seventh row to Â§01.01's table, `zero-GPU` in the GPU column, exactly as round 4 is handled.

---

## B9 â€” Register entry 11 asserts a positive lead bounded by a wholly negative interval
**Anchor:** `MT-Bench by 0.51 rating points (95% interval &minus;0.80 to &minus;0.21),` (line 4727)
**Verified:** `judge-paired.json` stores this as `a=medium, b=xhigh, mean_diff_b_minus_a âˆ’0.507, ci95 [âˆ’0.8, âˆ’0.213]`. The point estimate was flipped into medium's frame; the interval was not. Â§09.09's table at line 3614 correctly prints `+0.51 / +0.21 to +0.80` for the identical comparison, so the page gives two different intervals for one number.
**Replace with:** `MT-Bench by 0.51 rating points (95&nbsp;% interval +0.21 to +0.80),`
**Same entry, second defect.** Anchor: `Every other pairing is a tie, and` â†’ `Four of the remaining five pairings are ties; the fifth,` and change `<code>medium</code>'s 0.44-point ALPACA lead over <code>low</code> clears zero by 0.013 and is reported as marginal` â†’ `<code>medium</code>'s 0.44-point ALPACA lead over <code>low</code>, clears zero by only 0.013 and is reported as marginal`. (`judge-paired.json` verdict for that pair is `DIFFERENT (marginal)`, not TIE â€” the sentence currently calls it a tie and then calls it marginal.)

---

## B10 â€” The marginal-cost table's median is wrong and its ratio column reproduces from no single divisor
**Verified from `results.txt`:** the caption says *"Every segment of the ladder"* and *"the median of the three segments above the cliff"*, but only two above-cliff segments are printed; the missing `IQ4_XSâ†’Q3_K_XL` is 1.030 GiB for +2.631 % = **2.55 %/GiB**. The median is 1.0805 â†’ **1.08**, not 1.07, on every reading. And the ratio column: 5.7Ã— needs a divisor â‰¤1.073 while 17.8Ã— needs â‰ˆ1.081 â€” disjoint ranges. Rows 1, 3 and 4 reproduce exactly from 1.0805; the cliff cell alone was carried from `campaign.md`'s 1.07.
**Apply B2 first.** Replace the caption and the whole `<tbody>`:

Caption â†’ `<b>The marginal cost of shrinking.</b> Every segment of the ladder, priced. The median of the three segments above the cliff is <b>1.08&nbsp;%</b> perplexity per GiB, and the right-hand column is against that figure.`

| Step down | GiB saved | % perplexity added | % per GiB | vs the median above |
|---|---|---|---|---|
| `IQ4_XS` â†’ `Q3_K_XL` | 1.03 | +2.63 | 2.55 | 2.4Ã— |
| `Q3_K_XL` â†’ `IQ3_XXS` | 2.06 | +2.21 | 1.07 | 1.0Ã— |
| `IQ3_XXS` â†’ `Q2_K_XL` | 1.03 | +1.11 | 1.08 | â€” *median* |
| **`Q2_K_XL` â†’ `IQ2_S`** *the cliff begins* | 1.36 | +7.90 | **5.82** | **5.4Ã—** |
| **`IQ2_S` â†’ `IQ2_XXS`** | 1.03 | +6.09 | **5.91** | **5.5Ã—** |
| `IQ2_XXS` â†’ `IQ1_M` | 0.50 | +1.67 | 3.34 | 3.1Ã— |
| `IQ1_M` â†’ `IQ1_S` | 0.50 | +9.64 | 19.28 | 17.8Ã— |

---

## B11 â€” Three flat refusals and the front-matter scope line are falsified by Â§08.04's own cross-model arm
**Verified:** Â§08.04 compares `Qwen3.8-27B UD-IQ2_XXS` against `gemma-4-12B-it-QAT Q4_0` on the same frozen suite `1cdf54f8eb9d3f8f`, 25 prompts per benchmark, greedy, seed 42 â€” a file-against-file benchmark comparison. The intended claim is narrower and Â§08's own lead already states it correctly.
**Fix all four:**
- Line 513-517 (in the "Read this first" callout): `and no file
  was compared with another on benchmark accuracy` â†’ `and no two quantisations of <em>this</em> model were compared with each other on benchmark accuracy &mdash; the one benchmark comparison between files, in &sect;08.04, is across model families at an equal weight budget`
- Line 518: `What this page is not: a review, a comparison of models,` â†’ `What this page is not: a review, a general comparison of models &mdash; &sect;08.04's single equal-weight-budget arm is scoped and captioned as the exception &mdash;`
- Line 3003-3005 (Â§08.05): `<b>No two files were compared on
  benchmark answers, and this page publishes no accuracy ranking of
  quantisation files.</b>` â†’ `<b>No two quantisations of this model were compared on benchmark answers, and this page publishes no accuracy ranking of quantisation files.</b> The one benchmark comparison between files is &sect;08.04's equal-weight-budget arm, and it reaches across model families rather than within this one.`
- Line 4679 (Â§15.03 entry 8): same substitution, plus the entry-8 rewrite in S9.

---

## B12 â€” The page describes itself as an unreviewed draft, and dates itself before its own newest content
**Verified:** every clause becomes false on publication; and the cut date `2026-08-23` predates the ladder rungs (`ts=2026-08-24T00:52` through `12:34`), the equal-budget Qwen arm (`12:29`) and the judge panel (08-24).
**Fix:**
- Line 374: `generation 2 &mdash; DRAFT` â†’ `generation 2`
- Lines 5052-5056: replace the whole `<b>DRAFT &mdash; generation 2.</b>` paragraph with a published-state block â€” publication date, which gates ran and when, that it replaces `index.html`, and where generation 1's report can still be found.
- Line 5103: `Draft &middot; source commit 5dc41ec &middot; cut 2026-08-23` â†’ `Published &middot; source commit âŸ¨shipping commitâŸ© &middot; cut 2026-08-24`
- Lines 5059-5060: `finished on 2026-08-24 for roughly six hours more` â†’ `ran roughly six hours more, finishing at 12:35 on 2026-08-24`
- Masthead line 375, hero eyebrow line 391, meta description line 7: `measured 2026-08-23` â†’ `measured 2026-08-23 to 08-24`

---

# SHOULD-FIX

**S1 â€” near-blocking. Â§08.04's two error-bar claims are each the inverse of what the table prints.** Fix in the same pass as B10.
- Anchor: `Down to about 2.9 bits per weight the model gives up roughly one percent of
  perplexity per gigabyte saved, three steps running, and every one of those
  steps is far outside the error bars &mdash; this is a real slope, not noise.
  Then it stops being a slope. <b>The knee is <code>UD-Q2_K_XL</code> at
  9.154&nbsp;GiB</b>: the step below it costs 6.06&nbsp;% per GiB, <b>5.7&times;
  the median of every step above</b>. That single step buys 2.39&nbsp;GiB for
  more perplexity than the previous three steps cost put together.`
  **Verified:** `IQ3_XXSâ†’Q2_K_XL` is 0.0770 against a combined 1-SE of 0.0677 = **1.14Ïƒ**, with the bars overlapping by 0.019 (6.9665 vs 6.9478). The other two are 2.69Ïƒ and 2.24Ïƒ. And the top step costs 2.55 %/GiB, not "roughly one percent".
  **Replace with:** `From the anchor down to about 2.9 bits per weight the model gives up between one and two and a half percent of perplexity per gigabyte saved &mdash; 2.55, then 1.07, then 1.08&nbsp;% per GiB. Two of those three steps clear their error bars comfortably, at 2.7 and 2.2 standard errors of the difference; the third, <code>IQ3_XXS</code>&nbsp;&rarr;&nbsp;<code>Q2_K_XL</code>, is 1.1 standard errors with its bars overlapping, so the slope in this region is read from the three steps together and not from any one of them. Then it stops being a slope. <b>The knee is <code>UD-Q2_K_XL</code> at 9.154&nbsp;GiB</b>: the step below it costs 5.82&nbsp;% per GiB at 7.7 standard errors, <b>5.4&times; the median of every step above</b>. That one step buys 1.36&nbsp;GiB for more perplexity than all three steps above it cost put together.`
- Anchor: `<code>IQ2_XXS</code> and <code>IQ1_M</code> are 1.67&nbsp;% apart with
    overlapping error bars, so perplexity <b>cannot separate them</b>`
  **Verified:** the bars do **not** overlap â€” 8.0079+0.05695 = 8.0649 against 8.1418âˆ’0.05586 = 8.0859, a 0.021 gap. The separation is 1.68Ïƒ. Â§08.01 uses the overlap test correctly for the `q4_0` row, so a reader applying the same test here finds the opposite.
  **Replace with:** `<code>IQ2_XXS</code> and <code>IQ1_M</code> are 1.67&nbsp;% apart at <b>1.7 standard errors</b> of the difference &mdash; their bars clear each other by 0.02, but the gap does not reach 95&nbsp;% significance, so perplexity <b>still cannot rank them with confidence</b>`

**S2 â€” The equal-budget composite is arithmetically the truncation column, and the completed-item arithmetic is missing.**
Anchor: `At the same weight budget the crushed 27B takes the composite by
  5.4&nbsp;points and wins two benchmarks of three; the 12B keeps HumanEval.`
**Verified from `decisive.txt`:** gemma GSM8K 72.0 with 7 truncations = 18 correct of 18 completed; HumanEval 88.0 with 3 = 22/22; MBPP 60.0 with 9 = 15/16. On items it finished, the 12B is 55/56 and beats the Qwen arm (20/25, 21/25, 18/25) on every set. Also: (80+84+72)/3 = 78.67 and (72+88+60)/3 = 73.33, a true margin of **5.33 â†’ 5.3**, not 5.4 â€” the ledger's own one-decimal rounding inflates it.
**Replace with:** `At the same weight budget, at each model's own settings &mdash; not a matched-conditions comparison &mdash; the heavily quantised 27B takes the composite by <b>5.3&nbsp;points</b>. <b>Read the truncation column before the score column, because the gap is the truncation column.</b> On the items it actually finished the 12B is near-perfect &mdash; 18 of 18, 22 of 22 and 15 of 16 &mdash; and beats the Qwen arm's 20, 21 and 18 of 25 on every set. What the composite measures is that the 12B in its default thinking mode fails to terminate on 19 of 75 items while the 27B terminates on 74 of 75. That is a categorical finding about termination, not a resolvable quality ranking: at n=25 per cell &sect;10's guardrail is about &plusmn;16 points, so "wins two benchmarks of three" is not something this arm can support.` Also print the means as `78.7` and `73.3`.

**S3 â€” Ladder t/s figures are cold first-request probes, printed as settled ones.**
Anchor: `<span class="pv h">n=1 per rung</span> at depth 218 with
  <code>-c 8192</code>`
**Verified:** `srv-det-UD-IQ4_XS.err.log` shows the 218-token prompt as `task 0`, the first request after a 6.0 s load; the server's own `tg_3s` falls 43.27 â†’ 37.84 within that one probe (12 %), and the published 40.02 is the mean over 1,202 generated tokens, i.e. depths 218â†’1,420. Â§08.02's energy arm discards a warm-up, so the page applies two standards.
**Replace with:** `<span class="pv h">n=1 per rung</span> &mdash; each a cold <em>first</em> request on a freshly loaded server, greedy (temperature 0 / top_k 1), on a 218-token prompt with <code>-c 8192</code>, averaging decode over roughly 1,200 generated tokens rather than sitting at one depth. Within the anchor's single probe the server's own three-second rate falls from 43.3 to 37.8&nbsp;t/s. No replicated band on this page covers this probe class: the <em>ratio</em> is the durable part; the absolute speeds are not.` Print the speeds as `40.0` and `53.3`. Carry `n=1` and one condition clause onto the `1.33&times;` where it repeats in the Â§08 lead.

**S4 â€” Â§09.02's judged cells lack the PROVISIONAL chip, the seat spread and the correlated-judge note; the seven-set Mean mixes two caps.**
**Verified:** `judge-scores.json` flags xhigh ALPACA `provisional: true, at_cap_items [21]`; Â§09.09 chips it, Â§09.02 prints only `1 empty`. I checked disk: `arm-xhigh-cap32k-*_transcripts.json` contains only MATH-500, HumanEval and MBPP â€” **ALPACA was genuinely never re-run at the raised cap, so the chip is legitimate and must stay.** Separately, the judged cells sit in the column headed `32,768 &mdash; what to read` while Â§09.09's caption says the generations are the 16,384-cap arms.
**Fix:** add `<span class="pv h">PROVISIONAL</span>` to the `72.9` cell and to the xhigh seven-set `79.8`; mark the two xhigh-ALPACA rows of Â§09.09's paired table as resting on a provisional arm; append to the table caption: `The two judged sets were generated at the 16,384 cap; the five mechanical sets at 32,768. The seven-set composite therefore mixes the two caps until the xhigh ALPACA re-run lands. Seat spreads are published beside every judged mean in <a href="#s09-judge">&sect;09.09</a>, whose judge is a correlated instrument &mdash; judge and author are both Claude models.`

**S5 â€” "three independent Claude Opus 5 seats" is withdrawn a hundred lines later.**
Anchor: `a panel of <b>three independent Claude Opus&nbsp;5 seats</b>` â†’ `a panel of <b>three blind Claude Opus&nbsp;5 seats</b> &mdash; three separate rating sessions of the same model, kept apart from each other and not independent of one another`. (`judge-scores.json` itself says only `"3 blind seats"`.) Reserve "independent" for what the correlated-judge callout says is still open.

**S6 â€” Two composite indexes rank the levels oppositely and neither is named where it is printed.**
**Verified:** five-set 82.1 / 80.5 / 81.3 (medium lowest); seven-set 80.2 / 80.4 / 79.8 (medium highest), and Â§09.02 labels the seven-set one *"what the protocol actually specifies"*. Both recompute exactly.
**Fix:** Â§09.10 column head `Composite<br>index` â†’ `Composite index<br><span class="small">five mechanically scored sets</span>`, and add a footnote: `On the seven-set index that includes the judged sets the order reverses &mdash; 80.2 / 80.4 / 79.8 &mdash; which is itself the point: a 1.6-point spread and a 0.6-point spread are both ties.` In Â§09's lead, anchor `On the raised-cap suite it scored
  <b>lowest</b> of the three, 80.5 against <code>xhigh</code>'s 81.3 and
  <code>low</code>'s 82.1` â†’ `On the five-set index it scored <b>lowest</b> of the three, 80.5 against <code>xhigh</code>'s 81.3 and <code>low</code>'s 82.1; on the seven-set index that the protocol specifies it scores <b>highest</b>, 80.4 against 80.2 and 79.8. Two indexes disagreeing on the order is itself the argument that a spread this size is not a ranking.`

**S7 â€” "125 scored samples per arm" is the pre-judge figure in three places.** Lines 761, 3043, 3694, 4671. Carry Â§10.03's qualifier everywhere: `125 mechanically scored samples per arm, or 175 including the two judged sets`. In Â§09.10's `low` cell, name which composite `scored highest` rests on.

**S8 â€” "five scored sets" in three places is now seven.** Line 4783 (entry 15): `the five scored
    sets are mathematics, code and summarisation` â†’ `the seven scored sets are mathematics, code, summarisation and open-ended writing`. Line 4881: append `&mdash; the remaining two were closed by the judge panel on 2026-08-24 (entry 11)`. Line 5073 (footer): `with five scored sets` â†’ `with five mechanically scored sets, and the 2026-08-24 judge panel closed the remaining two`.

**S9 â€” Â§15.03 entry 8 prices work already delivered nine times.** Anchor: `Three files are ranked on speed and energy, and one has a perplexity
    number.` and `either a perplexity run on a second file under identical
    conditions &mdash; which is one evening and gives a per-token ranking &mdash;
    or`. Round 6 ran perplexity on nine files of this model under one identical condition set. **Rewrite:** state that nine files are now ranked on perplexity (round 6, Â§08.04), scope the surviving negation to *no two quantisations of this model compared on benchmark answers under matched conditions*, and reprice the remaining branch to the scored comparison only.

**S10 â€” Â§08's headline is contradicted by its own section, in two directions.** Anchor: `<h2>Three files ranked on speed and energy; two have a quality number, and not the same two.</h2>` **Verified:** nine files of this model now carry perplexity, and Â§08.05 says *"Exactly one of those three also has a perplexity number."* **Replace with:** `<h2>Three files ranked on speed and energy; nine ranked on quality &mdash; and only one file is on both lists.</h2>`

**S11 â€” Â§15.03 entry 12 republishes an inference the ledger formally withdrew.** Anchor: `consistent with attention or positional
    handling failing beyond the sliding window`. **Verified:** `results.txt` carries a `CORRECTION gemma-withdrawal` line retracting exactly this: *"the published blowups occur at -c 768 with sliding_window=1024, where the window never bindsâ€¦ so neither SWA nor the global-layer path is stressed."* **Replace the sentence with** the ledger's correction: the monotonic rise can no longer be read as evidence of a windowing fault, because independently published blowups occur at contexts where the window never binds.

**S12 â€” Â§10.03's summarising phrase does not match its own intervals.** Anchor: `against intervals four to six points wide` â†’ `against intervals seven to nine points wide`. **Verified:** the three Wilson intervals printed directly above are 7.5, 9.0 and 8.2 points wide (I re-derived all three; they are correct as printed). Only the phrase is wrong.

**S13 â€” Â§09.09 generalises "open-ended writing" from one of two writing sets.** Anchor: `<b>on open-ended writing, more thinking made the answers
    measurably worse.</b>` **Verified:** MT-Bench medium-over-xhigh is DIFFERENT (+0.21 to +0.80); ALPACA medium-over-xhigh is a TIE (âˆ’1.03 to +0.63). **Replace with:** `<b>on MT-Bench turn 1, more thinking made the answers measurably worse</b> &mdash; while on ALPACA the same pairing is a tie. One of six comparisons survived a 95&nbsp;% test, so this is a set-specific result and the overthinking effect is a candidate mechanism, not an established one.`

**S14 â€” "xhigh for hard code" is not actionable in any recipe.** Anchor: `So: <code>xhigh</code> for hard code you need finished, <code>medium</code>
    for writing.` **Verified:** all four recipes hardcode `reasoning_effort medium`, and Â§03.05 line 1282 says *"Not offered anywhere on this page: `xhigh` with a cap near 65,536â€¦ Raise it to 120,000 or drop the level."* **Append:** ` The recipes ship <code>medium</code>; using <code>xhigh</code> means overriding it per request <em>and</em> setting <code>max_tokens</code> to 120,000, which fits one turn per 131,072-token window (&sect;03.05).`

**S15 â€” `UD-IQ1_M` is published as the functional floor with a contrary signal in the same ledger line.** **Verified from `detectors.txt`:** IQ1_M `uniq=0.3582` on 564 words, against 0.4899â€“0.5154 for every other rung â€” including the failing IQ1_S at 0.4143 and the new IQ2_S at 0.5081. That is a 29 % drop in lexical uniqueness on a longer output, which is the shape Â§09.09 says these four detectors are blind to. **Fix:** print the unique-word ratio beside the IQ1_M detector verdict and add one clause noting that Â§09.09 establishes these detectors cannot see that failure shape.

**S16 â€” "About 6.5 GiB" describes only the losing arm.** Anchor: `At about 6.5&nbsp;GiB of
  weights:` â†’ `At 6.77 against 6.50&nbsp;GiB of weights &mdash; a 4&nbsp;% budget advantage to the Qwen arm:`

**S17 â€” Equal-budget caption omits the cap the section's argument turns on.** Anchor: `25 prompts per benchmark,
    greedy, seed 42.` **Verified from the arm JSONs:** both arms ran `max_tokens 16384` at `-c 32768`, both re-run at `32768 / -c 65536`; gemma on 2026-08-23, Qwen on 2026-08-24. **Add:** cap (16,384, re-run at 32,768), `-c`, both dates, the machine, and `a three-benchmark subset of suite 1cdf54f8eb9d3f8f`. Relabel the bare `Mean` column head `Mean &mdash; composite index over âŸ¨GSM8K, HumanEval, MBPPâŸ©`.

**S18 â€” Two chip types appear under a contract that says there are three.** Anchor: `Those three labels are the whole contract. Nothing on this page is a fourth
thing.` **Verified:** `<span class="pv j">JUDGED</span>` and `<span class="pv h">PROVISIONAL</span>` render in the same chip style, with their own CSS classes at lines 216-217. **Fix:** add both to the `tagrow` legend and define them in the contract paragraph the way SUPERSEDED and WITHDRAWN already are â€” `JUDGED &mdash; scored by the blind panel of &sect;09.09, not by a mechanical scorer` and `PROVISIONAL &mdash; an arm whose unremedied truncation still owes a raised-cap re-run; the cell will be replaced` â€” and amend the sentence to cover the five-label set.

**S19 â€” Both new sections bury their conclusion behind two tables.** Â§08.04's opening gives the method, not the two numbers a reader came for; Â§09.09's second paragraph puts a normalisation formula in Voice-1 position. Put the answers first: Â§08.04 â†’ *quality turns at about 9.2 GiB, the model still works down to about 6.3 GiB and breaks at 5.8, this page still ships the 13.3 GiB file, and no rung is recommended for a smaller card because no depth-and-drafter arm was run*. Â§09.09 â†’ *a blind panel read the two writing sets and found the middle setting beat the highest one on MT-Bench, so use `medium` for writing* â€” then the protocol paragraph.

**S20 â€” Vocabulary used in Voice-1 positions without definition.** `rung`, `ladder`, `the cliff`, `bits per weight`, `seat` (24 uses, never defined), `crushed`, `20,000-resample bootstrap`. `rung` and `the cliff` first appear in Â§01.01, hundreds of lines before Â§08.04 gives them meaning; the Plain-words box says *"about 4.2 bits per number"* and never bridges to "per weight". **Fix:** add `bits per weight`, `rung / ladder`, `the cliff` and `seat` to the Plain-words box, and replace `crushed` (used as a technical term, twice) with `heavily quantised` â€” the section already uses `squeezed` plainly in its own first sentence.

---

# NOTE

**N1** â€” `<h3 id="s09-judge">` is the only nickname id on the page; every other subsection is `sNN-NN`. Â§10.03 links `href="#s09-judge"` while displaying `Â§09.09`. Rename to `id="s09-09"` and update the three references at lines 3563, 3778, 5063.

**N2** â€” Anchor: `measured each one twice over` â†’ `measured each one in two ways`; `a battery of functional detectors` â†’ `a set of functional detectors`. "Twice over" sits one subsection below Â§08.03, which is entirely about a file genuinely being measured twice.

**N3** â€” Anchor: `the ratio is the durable part, the levels are not` â†’ `the ratio is the durable part; the absolute speeds are not`. "Level" means an effort level everywhere else on this page.

**N4** â€” Â§09.01 narrates a fifteenth self-correction (`this page previously printed the predicted column under the accepted definition's formula; that is now corrected in both places`) that is not among Â§15.04's fourteen items. I counted Â§15.04: exactly 14 `<li>`, so the count is internally consistent. Either add it as item 15 and update "fourteen" in the hero, the stat tile and the Â§15.04 heading, or say in Â§09.01 that it is folded into item 1.

**N5** â€” Â§15.03's closed entry `Two are resolved on perplexity (round 6)` understates by seven; â†’ `nine are ranked on perplexity (round 6, &sect;08.04), two of them as a resolved same-size pair`.

---

# DROPPED, AND WHY

1. **Gate 2: "append the missing ARM line to `data/quant-ladder/decisive.txt`."** Wrong â€” `decisive.txt` already carries `ARM qwen-iq2xxs-cap32k | cap=32768 | mean=78.70 | â€¦ | ts=2026-08-24T12:29:01`. No ledger edit is needed; only the page edit in B3.

2. **Gate 2's BLOCKER: "demote the equal-budget verdict to a categorical one / drop the numeric composite."** Downgraded to S2. Gate 2 says the composite is "dressed as a quality ranking", but the page already prints the truncation column, tells the reader in bold to read it first, captions the arm *"A deliberate conditions difference, not a fair fight"*, and explains the runaway-thinking mechanism. The genuine defects â€” the missing completed-item arithmetic, the 5.4-vs-5.3 rounding, and "wins two benchmarks of three" ranking on 25-item cells â€” survive as S2. The related front-matter contradiction is promoted to B11 instead.

3. **Gate 1's fix text for the missing marginal-cost row: "Add the anchorâ†’Q3_K_XL row (2.06â†’ read 1.03 GiBâ€¦)."** The "2.06" is gate 1's own slip; the segment is 1.030 GiB. Superseded by the full table in B10.

4. **Any reading that xhigh ALPACA's PROVISIONAL chip is stale.** I checked disk: the raised-cap re-runs (`arm-{low,medium,xhigh}-cap32k-*_transcripts.json`) contain only MATH-500, HumanEval and MBPP. ALPACA was never re-generated at 32,768. The chip is correct and must stay â€” the fix in S4 is to *propagate* it, not remove it.