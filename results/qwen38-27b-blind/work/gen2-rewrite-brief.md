# Gen-2 rewrite brief — Qwen3.8-27B field guide

Execution brief for the second-generation report. Two parents: the pinned
worked example (`templates/example-report.html`) and the blind reproduction
(`results/qwen38-27b-blind/index.html`). This file is the work order, not the
report. Three parts: what to finish, what to inherit, what to declare open.

Numbers below are quoted from `campaign.md` and `work/` unless marked
otherwise; every one of them must resolve to a named run before it is printed
(rule 1a).

---

## Part 1 — the finishing pass (14 items, priority order)

Items 1–5 need **zero GPU time**: the measurements already exist in
`campaign.md` and `work/energy-joins.md`. Item 8 is the only structural one and
runs LAST, after all content has landed, so the anchor check runs once.

**1. The accuracy chapter — highest priority. The report contradicts its own
log.** Front matter says *"No accuracy benchmark was run at all"*; §09 is
titled *"Why this page publishes no accuracy score at all"*; §14.03 says
*"No GSM8K, no MMLU, no coding benchmark, at any n."* `campaign.md` holds a
complete rule-21 sweep. **Write §09 up per rule 21 and delete all three
claims.** The material: suite `1cdf54f8eb9d3f8f`, 175 prompts, n=25, seed 42,
greedy, no MTP, `-c 32768`. Composite Mean over the five scored sets —
16,384 cap: **81.3 / 80.5 / 77.3** (low/medium/xhigh), truncations 1 / 2 / 9;
32,768 rule-7 rerun of the affected arms only: **82.1 / 80.5 / 81.3**,
truncations 0 / 0 / 3. Per-benchmark at 32k: GSM8K 100/100/100, MATH-500
92/100/92, HumanEval 100/96/84, MBPP 92/84/88, MeetingBank ROUGE-L
22.6/22.4/22.3. Mandatory framing: the Mean is labeled *"composite index over
⟨GSM8K, MATH-500, HumanEval, MBPP, MeetingBank⟩"* and states that it EXCLUDES
the judge-gated pair (ALPACA, MT-Bench — no independent judge endpoint;
transcripts kept). The finding is **effort buys wall clock, not measurable
quality on this suite** (walls 1.00 / 1.47 / 2.70 h; mean output 830 / 1,228 /
2,217 tokens): all three land within 1.6 points, indistinguishable at n=25.
The 16k table is kept as the truncation artifact it is — quality appears to
FALL with effort because 11 of 12 truncations returned empty content, the
runaway living inside the reasoning block. Publish the determinism result
(**139/139 non-truncated prompts byte-identical across the cap raise**), which
is what empirically licenses rule 7's rerun-only-affected-arms. Publish
MATH-500[3]: 18,273 tokens, and CORRECT — the budget rule's poster child.
Three xhigh prompts exceed 32,768 as genuine non-terminating loops and are
reported as such, not filtered.

**2. The "Standardized industry metrics" table, under that exact title**
(rule 24, REPORT-SPEC §3). Data is already joined in `work/energy-joins.md`.
Tier label: *in-band GPU board power (NVML); PSU losses and datacenter PUE
excluded*. E0 (rule-21 arms, drafter OFF, mixed regime): **J/decode-token
7.884 ± 0.307** (n=115 requests wholly inside the logged window),
**tokens/kWh 429k–465k**, **prefill 0.41–0.79 J/prompt-token**. E8a (effort
arms, MTP n4/p0.75 on, temp 1.0, n=1/level): J/decode-token
**4.26 / 5.18 / 6.60 (truncated) / 6.13 (120k)**, tokens/kWh
845k / 695k / 545k / 587k, **EDP 1.57e7 / 4.84e7 / 5.52e8 / 4.16e8 J·s**
spelled out as energy × latency, prefill 0.12–0.18 J/prompt-token =
26–43× cheaper per token than decode. Headline: **the drafter roughly halves
J/token** (4.3–6.1 on vs ~7.9 off). Add an **E_comm** row reading
*"N/A — single GPU, no interconnect"*. Coverage gaps are printed, not dropped:
the medium/low cap-32k arms are fully covered, xhigh-cap32k is tail-only
(63.4%; full arm estimated 746–764 Wh), and the 16k arms plus
GSM8K/ALPACA/MeetingBank/MT-Bench have no power data at all.

**3. "344 W sustained" becomes a range.** Sustained board power drifted
**305.5 → 341.1 W at constant throughput, temperature and memory clock**,
tracking SM clock 1453 → 1606 MHz — decode is bandwidth-bound, so the extra
clock bought nothing. Print **306–341 W (drafter off)** everywhere the report
currently prints 344 W as a headline (§04.03 and §12). The ±6% J/token spread
between arms hours apart is instrumental and says so.

**4. Idle republished per rule 24.** The current *"33.2 W / 34.6 W"* no-server
against *"30.2–31.1 W"* loaded is the physically backwards ordering rule 24
cites as contaminated — a board still cooling from the prior job. Republish
both flavors, dated, with the first ≥60 s of every idle window discarded;
`campaign.md` carries **provisional settled idle 31.2 W** (mark it provisional,
pending matrix A1/A2, or run A1/A2 first). Then print **Wh/answer twice —
gross and idle-subtracted — everywhere Wh appears.** Note in the trail that
server-down ≠ GPU-idle: plot rendering spiked an "idle" tail to 121–124 W five
times.

**5. The per-axis J/token table** (rule 24's final bullet, REPORT-SPEC §9).
Eight axes: quant · drafter · KV dtype · `--parallel` · depth · effort ·
token regime · power cap. The drafter row is measured (4.3–6.1 on vs ~7.9
off); the rest are honest *"not measured"* lines. The power-cap row needs no
GPU time at all: print the command (`nvidia-smi -pl <W>`), the stock 350 W
cap, and *"unmeasured on this machine (requires administrator)"*.

**6. Mean draft length beside EVERY acceptance rate** (rule 11 says *always*).
It currently appears only in §06.02's sweep — absent from §02's two depth
series, §04's effort table, §06.03 and §06.05. `draft_n` and
`draft_n_accepted` were captured, so this is recomputation, not measurement.
Fold in the follow-up's 1.69× demonstration, which is a stronger version of
the report's own one-curve callout: **accept 0.895 vs 0.907, draft length
2.99 vs 4.31, 36.62 vs 62.02 t/s** — same server, same 91k prompt, same flags.
While here, add the drafting pair the amended rule 11 now requires:
drafted/pass AND accepted/pass, with the counter formula printed.

**7. The "Plain words" glossary box** (REPORT-SPEC §2). Currently absent
entirely. It is cheap, and it is the precondition for the two-voice law's
"terms defined once" clause — no Voice-1 paragraph is compliant until the box
exists. Eleven terms now, the eleventh being percentage point vs percent with
this report's own per-question value (**at n=25, one question is 4 points** —
which is also the honest frame for item 1's 1.6-point spread).

**8. Recipes-first reorder.** Recipes are §08 of 14. Mechanical section move,
TOC renumber, and ~20 forward `§08` references to fix. Largest of these items,
still hours and not GPU-hours. **Run it LAST**, after every content item has
landed, then run gate 4's anchor check once: id ↔ displayed number ↔ TOC ↔
every `§NN` in prose.

**9. Voice-1 openings** for the sections that currently open with a table
(§03 Universal flags, §10 Troubleshooting) and for the recipe cards that open
with a `MEASURED` stamp. No section begins with a table, a chart, a command
block, or a caveat.

**10. Effort levels offered / not-offered per recipe, with measured appetite
and the binding constraint** (REPORT-SPEC §3, rules 16 and 25). No recipe card
states which levels it can hold, and the shipped `serve-qwen38.bat` offers
`xhigh` on all four configurations with no cap guidance — while §04 measured
xhigh returning **nothing** at a 65,536 cap. Add the appetite fence
(`window ≥ appetite upper tail + prompt + answer margin`), a recommended
`max_tokens` per recipe, and for each excluded level the constraint that
excludes it (window or wall-clock).

**11. The Q4_K_M screen row.** A second file now exists on the speed axis:
follow-up M1 measured **Q4_K_M 81.71 t/s (2.04×)** beside **IQ4_XS 93.86**.
§05's *"One quantisation was measured"* gains a rule-25 *prune before you
treat* screen row — throughput probe plus file size — while still publishing
**no quality ranking**, because no second perplexity run exists (see Part 3).

**12. The cooled depth ladder.** The follow-up's corrected answer-regime
ladder (cooled protocol, n4/p0.75) is absent: **86.30 @ 1,458 → 80.20 @ 28,388
→ 64.76 @ 90,854 t/s**, with xhigh's real speed at 91k depth ~37–39 t/s, and
n10/p0.5 recovering only 5.6% there against 12% on shallow code. Publish it
beside §02's single-probe 5b table with parity declared on both — the report's
captions already declare parity correctly, so this is paste-and-label.

**13. Suite hash and frozen-input record** (rule 23). Once item 1 lands:
publish `1cdf54f8eb9d3f8f`, 175 prompts, `-c 32768`, and the note that
`config.json` and the wikitext corpus were network-fetched and saved to
`data/`. Two reports compare only if their suite hashes match; the hash is the
comparability contract.

**14. The scorer-bug case study** (rules 5 and 3). The live run found scorer
bugs that moved arms materially and were fixed symmetrically (selftest 78/78):
**MATH-500 presentation-vs-value normalization (low arm 60 → 92)**, **GSM8K
unit-suffix compare (xhigh 92 → 100)**, and a newline squeeze; all arms were
re-graded offline from kept transcripts. Under rule 5 this is a keepable dated
case study. Under rule 3 the offline re-grade is a **condition on every score
published in item 1** and travels with the table, not only with the case study.

---

## Part 2 — heritable genes

Both parents contribute practices no third campaign should have to reinvent.
Gen-2 carries all ten.

**From the blind reproduction:**

1. **Provenance chips.** MEASURED / DERIVED / CITED rendered AT the number and
   the cell, never as a sentence covering a paragraph, with one page-level
   contract line: those three labels are the whole contract, nothing here is a
   fourth thing. `n=1` prints beside every single-sample figure.
2. **The deviations register.** The campaign log opens with every departure
   from protocol, its justification, **the axis on which that justification was
   verified**, and the cheapest measurement that would close the rest. The
   shape to keep: *"decode-neutrality was checked and held; the system-RAM half
   was never examined."*
3. **The refusal chapter.** A section that was not measured keeps its number
   and its heading and is filled with the negative: what was cut, what is
   nonetheless established, and the test the reader should run. *"A config that
   was never run is a guess, and a guess in a monospace block reads exactly
   like a measurement."*
4. **The page-wide noise band.** Stated once as a reading instruction, with the
   replication arithmetic that produced it and the class of claim that survives
   it. Gen-2 must go one step further than its parent and make printed
   precision respect the band — no four-significant-figure levels on a ±25%
   probe — and must end with one reproduction check carrying a **pass band**
   derived from that floor (rule 26).
5. **Per-instrument Sources.** Which counter, field or tool produced each class
   of number — server `timings`, NVML board power, `nvidia-smi` dedicated VRAM,
   the scorer — plus graded external citations and the negative-results
   register in Part 3.

**From the worked example:**

6. **Figure aria-labels that state the finding.** The alt text is a readable
   data table in sentences with its numbers, not a description of the chart's
   shape; a figcaption carries the date and conditions.
7. **Per-row reproducing commands.** Every configuration table row makes its
   exact `llama-server` command reachable from the row itself — hover title
   plus a details block printing all of them, with a per-flag glossary.
8. **The four-band spec strip.** floor · short-context work · at-depth work,
   naming the depth that anchors it · ceiling, each with its condition. Three
   bands hide the number an agent user actually gets.
9. **Menu losers kept with their reasons.** The decision table carries the
   rejected configurations, one line each (*"measured worse than plain Q4_K_M,
   PPL +1.8% — skip"*), so an option the reader has already heard of is
   answered rather than absent.
10. **Concept diagrams for non-experts**, earning their place in the Plain
    words box (item 7 of Part 1 is where they land).

---

## Part 3 — the negative-results register (known-open, both parents blind)

These six are shared blind spots: neither parent measured them, so Gen-2 may
cite them as open rather than hide them. Each is a register entry per
REPORT-SPEC §16 — why it is missing, the measurement that closes it, its price
in machine time. **Prices are derived from this campaign's own phase ledger
(total GPU time 1 h 59 min across 17 phases) and are estimates, labeled as
such — they are not measurements.**

**1. The sampling-regime bridge.** *Why missing:* every speed number on both
pages was taken at `temp 0 / top_k 1`, while every recipe ships or assumes the
model card's `temp 1.0 / top_p 0.95 / top_k 20`. Acceptance is a property of
which token the drafter must guess, so sampling moves it directly — the
example asserts this and never measures it; the blind never raises it. Both
therefore publish speculative bands at a setting nobody should use for real
work. *Closed by:* the phase-3 drafting sweep plus one depth point re-run at
the shipped sampling, n≥3 per arm because temp 1.0 is not deterministic,
reported against the greedy band as a transfer factor. *Price:* ~30 min GPU
(estimate — phase 3 took 4 min greedy; triplication and one 91k depth probe
dominate). Until then, every speculative band is labeled **greedy-only and
non-transferable** (rule 3).

**2. Retrieval quality at depth.** *Why missing:* both parents ship 131k–262k
windows verified only for speed and residency. Neither ran a single retrieval
or needle probe at depth. Worse, both refuse `q4_0` KV on a long-context
retrieval argument and verify KV quantization with a perplexity pass at
`-c 8192` — which structurally cannot see the failure the argument is about.
*Closed by:* a needle-in-haystack grid at 8k / 90k / 180k × {f16, q8_0} KV,
n=5 per cell, scored on exact retrieval. *Price:* ~1–2 h GPU (estimate —
prefill-bound; the 180k cells dominate). Until then every shipped window
beyond 8k is labeled **"speed-verified, quality-unverified at depth"**
(Memory preamble).

**3. The prefill-scaled roster.** *Why missing:* both rosters derive every
non-measured card from `bandwidth ÷ file size` — the DECODE law — and are then
used as buying advice for agentic work, which is prompt-bound. The blind
measured that DeepSWE wall time is prefill-bound (**1.01M prompt against
21.7k completion tokens per task**) and still shipped a decode-ordered roster.
*Closed by:* a prefill-scaled row beside each decode row, anchored on this
machine's measured prefill throughput and scaled on each card's published
compute rather than its bandwidth, with every borrowed spec graded per rule 1b.
*Price:* **zero GPU time** — one afternoon of arithmetic plus roster spec
fact-checking. Every wall-clock estimate states its prompt:completion ratio
regardless (rule 10).

**4. The overflow event.** *Why missing:* the blind publishes a turns-per-window
budget (xhigh = one turn in 131k) and stops; the example's closest line is that
a cut generation cannot seamlessly resume. Neither measured what the server
actually does when a conversation overflows the window — error, context shift,
or full re-prefill — nor its wall cost, despite both recommending the model for
multi-turn coding agents. *Closed by:* one server with `--reasoning-preserve`
on at a deliberately small `-c`, driven past the window, recording the turn
N+1 behavior and its wall clock. *Price:* ~20–30 min GPU (estimate — one
server, no restarts).

**5. `--load-mode` system RAM.** *Why missing:* two campaigns shipped opposite
defaults for one flag — the example ships `none` claiming ~15 GB freed, the
blind ships `mmap` — and both measured only load time and decode neutrality.
Zero system-RAM measurements exist for a flag whose entire stated purpose is
system RAM. *Closed by:* `\Process(llama-server)\Working Set` sampled across
one load per `--load-mode` value. *Price:* **no GPU time**, ~10 minutes wall.
Until then the flag is documented as untested rather than recommended (rule 20,
resource-flag proof).

**6. Image-token budget quality.** *Why missing:* the example ships
`--image-max-tokens 10580` for "4K-class detail"; the blind measured that
`--image-max-tokens 1024` cuts a 1440p image 3.6× and states plainly that the
detail cost was not measured. Rule 18's *min for grounding, max for detail* is
a mechanism, not a measurement. *Closed by:* the same image at two budgets,
asked a question whose answer depends on the fine detail, blind-scored.
*Price:* ~15 min GPU (estimate — the phase-8b vision runs took ~1 min each).
Related and also open: the blind's perception claim lacks a **withheld-image
control**, and Gen-2 names that as the missing control rather than calling the
result a critique loop.

**Closed items stay in this register, marked closed.** Item 11 of Part 1 moves
"only one quantization was measured on the speed axis" to closed; the quality
axis stays open, and its price is one evening for a second perplexity run
under identical conditions.

---

## USER-DIRECTED (2026-08-23): rewrite the front-matter title block

The current hero must be replaced. Each clause is now false or non-compliant:

> "One model, one card, one night / ... nothing is carried over from another
> model or another run. The three things here that are not measurements -
> the arithmetic in 02, the other cards in 07, the vendor claims in 12 -
> say so where they stand."

- "one night" - the campaign now spans 2026-08-22 through 08-23+ (follow-up
  probes, rule-21 sweep, power matrix, energy joins, quant ladder).
- "One model" - the quant ladder adds a cross-model decisive arm
  (gemma-4-12B-QAT) and NVFP4/Q4_K_M rig controls.
- "nothing is carried over from another model or another run" - audit
  defect 2.12: the Sources trail itself says DGX Spark / Arc figures are
  carried from the template fact-check set; rule-21 suite + scorer are
  shared artifacts. The claim contradicts the report own trail.
- "The three things here that are not measurements" - the count is no
  longer three, and enumerating non-measurement classes in the hero is
  fragile; the per-number provenance chips + the evidence-tier declaration
  (new REPORT-SPEC non-negotiables) replace this device.

Replacement requirements: the new front matter satisfies the evidence-tier
non-negotiable (hours measured, arms run, smoke vs solid, self-correction
count, BEFORE the first number), states the true date span and scope, and
passes review gate 4 front-matter-vs-trail check. Keep the second line
("Every setting, with the number that justifies it") - it is true, it is
the pledge, and it survives the rewrite.

---

## PART 4 (2026-08-23 staleness sweep): apply work/staleness-registers.md

Three registers, all input to this rewrite: 17 NOW-FALSE negations in the
blind report (N1-N17: the no-benchmark family, the one-quant family, the
no-agent family - each with its quoted line and one-line fix), the
count/date/scope register, and the published-guide register (missing
rule-21 effort tie, energy metrics, 306-341 W range, 29.9/34.1 W idle
pair, drafter-halves-J/token, the 16k-cap reversal as section 09 teaching
material). The REPORT-SPEC republication rule now makes this check a
standing obligation on every result-adding commit.
