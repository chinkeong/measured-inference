# VOICE — the register of the published field guide

This file is the register of the published field guide written down as rules — how a sentence that carries a measurement is built, what may occupy its first clause, and which words may not appear in it — so that a writer who is not Claude Opus 4.6 can produce the page's voice, and so that any draft can be checked against it afterwards. It governs only what a reader can check against the sentence in front of them: `templates/REPORT-SPEC.md` says what the prose must BE — the two-voice law, what each section contains, which reader it addresses — and `methodology/WRITING.md` says how it gets written, briefed and verified; where this file seems to restate either of them, the other one governs. The first section is not style: on 2026-08-29 a voice pass in exactly this register rewrote 155 passages in fifty-one minutes and put eleven false statements into the published page while its gate confirmed that no number had been added, removed or altered — because a figure can keep every digit while the condition attached to it becomes false — and a writer who obeys the rest of this file without that section will reproduce the accident.

| What | File |
|---|---|
| What the prose must BE (two-voice law, section contents, reader) | `templates/REPORT-SPEC.md` |
| The 30 invariants | `methodology/METHODOLOGY.md` |
| How prose is written, briefed and verified | `methodology/WRITING.md` |

---

## 2. Where these rules do not apply

Every test below inherits these exemptions: (1) §15's corrections register (`id="corr-*"` entries), (2) the footer's revision list, (3) inline `<span class="hint">Correction: …</span>`, (4) launcher `::` / `rem` comments, (5) `aria-label` text, (6) any string a sentence is quoting.

---

## 3. Rules that keep the facts true while the sentence changes

On 2026-08-29 a voice pass in this register rewrote 155 passages in fifty-one minutes and put **eleven** false statements into the published page. Its gate confirmed no number had been added, removed or altered — because a figure can keep every digit while the condition attached to it becomes false. Four repair commits ran until 03:23. Every rule below exists to stop the next writer reproducing the accident.

**3.1. No invented conditions.** Attach only the conditions the source carries — window, date, flags, file, regime, baseline. If the source gives a number no condition, publish it bare; never infer one from a neighbouring sentence, never widen a scope to cover a second run or date.
*Why:* Eleven figures kept every digit while the condition beside them became false, and the gate cleared all eleven.
*Good:* `582&nbsp;MiB of slack at <code>-c 180224</code>; 847&nbsp;MiB measured at the same window days earlier`
*Bad:* `847&nbsp;MiB measured at <code>-c 32768</code>` — the pass supplied a window that is not this figure's.
*Test:* Set-diff the condition tokens (ISO dates, `-c` values, n-max/p-min, regime words, baselines) of before and after text. AFTER-minus-BEFORE must trace to the brief; unanswered means reject.

**3.2. Baseline named and rederived.** Every relative figure names both endpoints in the same sentence; recompute (new − old) ÷ old to the printed precision before shipping.
*Why:* −3.1% was reprinted against 93.9 t/s (true answer −21.3%).
*Good:* `<b>&minus;3.1%</b> against 76.32&nbsp;t/s at <code>-c 32768</code> in the same probe`
*Bad:* `<b>&minus;3.1%</b> against the matched sweep peak of 93.9 t/s at <code>-c 32768</code>`

**3.3. The referent is a fact.** A figure's referent — the noun it names — is a fact. Re-read the noun and check it against the artefact, not against the neighbouring sentence.
*Why:* 12,205 MiB is the *saving*; 13,480 MiB is what mmap *holds*. The pass swapped them; both values were already on the page in their correct roles — `1,275&nbsp;MiB working set against <code>mmap</code>&rsquo;s 13,480, a saving of` 12,205 — so every digit check passed. This defeats the page-wide number-set test where it matters most.

**3.4. Quantifiers and scope words are facts.** *no / none / any / every / all / only / never / always / each / both* are load-bearing; a rewrite may not introduce one, strengthen one, or replace a named condition with one. Write the positive scope you measured.
*Why:* One reader's case became `No 4-bit configuration on this page can hold all three`; a specific condition became `at any useful window`; a floor spanning four contents was narrowed to one.
*Test:* Diff quantifiers of each rewritten block. Any new universal or existential requires a source line carrying that scope.

**3.5. No qualitative-to-quantitative.** A number standing where the source had a phrase is an invented number, even when the digits exist elsewhere on the page.
*Why:* "the largest window they could get" became "a window past 122,880" — 122,880 is real and appears elsewhere, so every digit check passed. §6.1 (you-not-we) *pushes the writer into this*: delete the reader and the scope must be restated impersonally; the nearest restatement is a threshold.

**3.6. Number set per clause, rescue the datum.** Diff the triple (figure, referent, conditions) per clause, not just the page-wide set. A figure leaves a passage only by relocation to the corrections register with a `<sup class="cref">` left at the cell. The page-wide count checks *deletion*; it does not check *correctness*.
*Why:* "1,583 distinct, unchanged" was true while two figures were wrong.
*Good:* `it needs <b>16,906&nbsp;MiB</b> at <code>-c 65536</code> &mdash; more than the whole card`
*Test:* (a) Triple per clause. (b) Literal set may not shrink. (c) `class="cref"` count must not fall (39 → 43). (d) `href="#corr-*"` minus `id="corr-*"` empty. (e) Spelled counts re-derived: the §15 heading reads `The thirty-seven places this page corrected itself` above 36 `<li>`.

**3.7. Tag sequence, not tag count.** Compare the ordered tag sequence per block; check every row's cell width against its header, counting `colspan`. A global tag-balance count is not a check: a dropped `<td>` and its `</td>` cancel exactly.
*Good:* `</td><td>the largest text-only window that stays resident`
*Test:* Per `<table>`, first row `<th>` widths set the count; every later row's `<td>` widths must match. Mismatches may not rise.

**3.8. No sentence twice.** Strip tags, collapse whitespace, scan for `(.{80,400}?) ?\1` — require zero. A sentence-splitting check misses duplicates that begin mid-sentence; all three that the pass introduced did.
*Good:* `(Those 17 are the fully-resident subset of 26 loads in total; the other nine were overcommitted configurations, which the model does not describe.)`
*Test:* `re.sub(r'<[^>]+>',' ',t)`, collapse whitespace, `re.findall(r'(.{80,400}?) ?\1', s)` → 0. Separately: any sentence ≥ 60 chars occurring more than once → reject.

---

## 4. The opening slot

Every rule here creates the pressure §3 exists to stop: promoting a result opens a conditions slot the writer fills by guessing.

**4.1. Result in the first clause.** Open every paragraph, cell, list item and figcaption with the finding. Provenance, method and editorial state follow; none may occupy the opening.
*Good:* `<b>Ship <code>--parallel 1</code>.</b>` · *Bad:* `<b>Settled 2026-08-25. This page had refused to use either figure until a decisive test could separate them` …
*Test:* Reject `^(Settled|Restored|Corrected|Added|Recorded)\b` before a date, `^Earlier editions`, `^This page (had|used|refused)` — 7 → 0.
*Exception:* `Measured <ISO>:` is permitted where the date *is* the finding — a re-measurement displacing a published figure. → §3.1

**4.2. Conditions in the same breath.** Conditions ride in the same sentence as the number — em-dash aside or parenthetical, never a preamble reaching forward, never the next sentence. §3.1 owns membership; this rule owns position.
*Good:* `<strong>A <code>q4_0</code> K/V cache costs +0.693% perplexity against fp16</strong> — 6.6413 against 6.5956 (2026-08-23, same corpus and flags as the <code>q8_0</code> run)`

**4.3. Governing figure leads.** Where a unit carries two values, the governing one comes first in the present tense; the superseded one follows in the past tense, dated.
*Test:* Governing figure's character offset is lower; retired figure's verbs are past tense ("costs" → "cost", digits untouched). → §3.6

**4.4. Typical figure leads.** The first clause carries the figure the reader will usually get. A best case follows with its frequency or distinguishing condition.
*Good:* `76–79 t/s — plan for this level; about one session in eight reaches 86–89 instead` → §3.1

**4.5. Labels state the finding.** Every heading, tag and figcaption states the finding, never the editorial episode. REPORT-SPEC says a heading names the content; this adds that it may never name the edit.
*Good:* `GPQA-Diamond: 79.8% on 198 graduate-level science questions`
*Bad:* `A knowledge benchmark, run twice because the first half was not a sample`
*Test:* `class="tag">Correction` → 0; tags opening `Settled 20`, `Recorded 20` → 0.

**4.6. Recommendation imperative, naming the artefact.** State the recommendation as an imperative naming the exact file, flag or value. A rounded figure may describe a measured result but never the identity of the thing to get.
*Good:* `<strong>Stop at UD-Q2_K_XL &mdash; 2.912 bits per weight, 9.154&nbsp;GiB.</strong>`
*Bad:* `The advice has not changed: stop at about 9&nbsp;GiB.` → §3.5

**4.7. Disqualification leads.** When the finding is that a number cannot be used, the disqualification occupies the first clause. Close on the state of the question, not the argument.
*Good:* `So the perplexity gap is unresolved, and the GSM8K result is unusable.`
*Bad:* `So the case rests on one unresolvable difference and one withdrawn instrument.`

---

## 5. The page has no memory

**5.1. No page autobiography.** Never narrate the page's editing history in body prose. Present-tense verbs about what the page contains are fine; past-tense verbs about what it said are not.
*Good:* `<strong>That constant is format-specific</strong>: on CUDA it measures about <strong>0.70 for K-quants</strong>`
*Bad:* `which earlier editions of this page flattened into a single ~0.7`
*Test:* `earlier edition`, `this page (had|refused|used to)`, `this revision` → 0. → §3.6

**5.2. No edit-relative words.** No "today", "no longer", "still", "finally", "already" in the time-relative sense. Print the absolute date. "Now" is licensed only for evidence status or the machine's present state.
*Test:* Replace the word with "as of the last edit"; if the sentence still works, it is a defect. → §3.3

**5.3. Dates date measurements.** Every date in body prose dates a measurement, written ISO. `Measured <ISO>:` is the permitted date-first form; `Added / Changed / Settled / Corrected / Recorded / New on` before a date are not. Promote an editing date only when something was measured on that date; the fact-safety rule (§3.1) governs the register rule.
*Good:* `<b>Measured 2026-08-25:</b> at <code>-c 131072</code>, deep-filled with prose`
*Bad:* `<b>New on 2026-08-25:</b> at <code>-c 131072</code>, deep-filled with prose`

**5.4. History becomes an instruction.** Convert history worth keeping: a chronology → a standing rule; an apology → a reading instruction; a gap → a present-tense fact with the quantity named. Status words: *measured, derived, unresolved, unusable*.
*Good:* `Board power with concurrent drafter-on slots remains unmeasured.`
*Good:* `It is not an independent confirmation; read it as a breakdown of the accuracy column's failures, not as a second witness.`

---

## 6. The sentence

**6.1. You, not we.** Address the reader as "you"; call the document "this page". Never "we", "our", "us" or "I". No contractions. The third-party ban is rhetorical: strike the third party, re-read the claim, and if its scope changed, restore it.
*Good:* `If your machine returns something inside the band` · *Bad:* `and he is right enough that it is worth showing why.`
*Test:* `\bwe\b|\bour\b|\bus\b` outside quotes → 0. → §3.5

**6.2. Sentence length holds.** Write long, clause-dense, parenthetical sentences and hold the length: a rewritten passage keeps its median within ±10%. Only the opening sentence runs short — about 17 words, at least 5 below the later median of 23. REPORT-SPEC's Voice-1 "short sentences" governs vocabulary, not word count.
*Good:* `the three levels scored 80.2, 80.3 and 79.7 out of 100, a spread of 0.6 points at a sample size where a single benchmark cell is worth about ±16 points, which is a tie — while the wall clock went from 1.0 to 1.5 to 2.7 hours and the average answer grew from 830 to 2,217 tokens.`

**6.3. No boosters, no hedges.** Delete *dramatically, substantially, remarkably, surprisingly, impressively, appears to, seems to, tends to*. A superlative requires a number in the same clause; "significantly" requires its test statistic. Approximators (*about, roughly*) qualify a measured band but never the identity of the thing to get. → §3.5

**6.4. Negatives as facts.** State a negative result as a present-tense fact about the machine with the quantity named. Never confess on behalf of the document.
*Good:* `So the perplexity gap is unresolved, and the GSM8K result is unusable.`
*Bad:* `So the case rests on one unresolvable difference and one withdrawn instrument.`

**6.5. Against, not vs.** A comparison in prose takes "against"; a movement takes "→". Reserve "vs" for labels.
*Good:* `joules per token equals watts divided by tokens per second, and it predicts these four numbers as 4.24 / 5.16 / 6.60 / 6.13 against the measured 4.26 / 5.18 / 6.60 / 6.13`
*Test:* `' vs '|versus|compared to` inside `<p>` → 0.

**6.6. British forms.** Use *behaviour, favour, centre, analyse, labelled, judgement, grey, licence* (noun). Do not normalise -ise/-ize — the page is split and neither is a defect.
*Good:* `Two knobs control drafting behaviour` · *Bad:* `behavior verified identical across all eight picks`

---

## 7. Typography that carries meaning

**7.1. Spaced em dash, en-dash range, minus sign.** ` — ` (spaced), never word—word, never `--`. Range: en dash (`6–8`). Negative figure: `&minus;`, never hyphen. No exclamation marks.
*Test:* `\w[—]\w` → 0; `--` in prose → 0; hyphen-minus before digit outside `<code>` → 0.

**7.2. `&nbsp;` binds symbol units.** `22,014&nbsp;MiB`, `350&nbsp;W`, `73.94&nbsp;t/s` — plain space before spelled-out nouns (`2,217 tokens`, `0.6 points`). Inside `<pre>` and launcher comments, plain spaces throughout.
*Test:* For MiB, W, MHz, Wh: `&nbsp;` share > 0.7. `\d&nbsp;(tokens|points|hours|questions)` → 0.

**7.3. Code literal vs prose number.** Inside `<code>`: never comma-grouped (`<code>-c 122880</code>`). In prose: always separated (a 122,880-token window).
*Test:* `-c [0-9]{1,3},[0-9]{3}` → 0; no `\d,\d{3}` inside any `<code>` span.

**7.4. Bold emphasis.** `<b>` wraps the figure or short lead-in (median 3 words); `<strong>` wraps the liftable claim (median 6 words). Bare-numeral bolds stay under 15% inside `<p>` (page: 9%).
*Good:* `<b>The band is set between sessions, not within one; twenty probes in one sitting cannot measure it.</b>`

---

## 8. Run these before you commit

Collected mechanical tests in the order a script would run them. Strip the §2 scope zones before running.

| # | Check | Target | Rule |
|---|---|---|---|
| 1 | Condition-token set-diff per block | AFTER-minus-BEFORE empty or sourced | §3.1 |
| 2 | (new − old) ÷ old on every %, ×, comparative | reproduces printed figure | §3.2 |
| 3 | Referent stated and grepped per figure | pairing in artefact | §3.3 |
| 4 | Quantifier diff per block | no unsourced universals | §3.4 |
| 5 | New figures traced to source as figures | no phrase-to-number | §3.5 |
| 6 | (figure, referent, conditions) triple per clause | matches source | §3.6 |
| 7 | Distinct numeric literals page-wide | set may not shrink | §3.6 |
| 8 | Spelled counts re-derived by counting | count matches | §3.6 |
| 9 | `class="cref"` count | must not fall | §3.6 |
| 10 | `set(href) − set(id)` | empty | §3.6 |
| 11 | Per-table `<td>` vs `<th>` widths | mismatches must not rise | §3.7 |
| 12 | `(.{80,400}?) ?\1` on tag-stripped text | 0 | §3.8 |
| 13 | Sentence ≥ 60 chars occurring > once | 0 | §3.8 |
| 14 | Opener regex on first 8 words | 0 | §4.1 |
| 15 | `earlier edition\|this page (had\|refused)\|this revision` | 0 | §5.1 |
| 16 | Edit-relative words → substitution test | no time-relative survivors | §5.2 |
| 17 | `(Added\|Changed\|Settled\|Corrected\|Recorded\|New on) 20\d{2}` | 0 | §5.3 |
| 18 | `dramatically\|substantially\|remarkably\|…\|seems to` | 0 | §6.3 |
| 19 | `\bwe\b\|\bour\b\|\bus\b` outside quotes | 0 | §6.1 |
| 20 | `' vs '\|versus\|compared to` inside `<p>` | 0 | §6.5 |
| 21 | British-form pairs: American form | 0 (except quantisation/quantization) | §6.6 |
| 22 | Tight em dash; `--`; hyphen-minus before digit | 0 | §7.1 |
| 23 | Symbol-unit `&nbsp;` share | > 0.7 | §7.2 |
| 24 | Comma inside `-c <digits>` | 0 | §7.3 |
| 25 | Bold median word count; bare-numeral share | ≥ 4; < 15% | §7.4 |
