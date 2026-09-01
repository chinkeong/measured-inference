# COMPARISON-SPEC — structure of a multi-model comparison

`REPORT-SPEC.md` governs a field guide: **one model, one machine**. This governs
the other deliverable this repo produces and had no contract for — a document
that ranks several models against each other, and that expects to grow as more
models arrive.

`PROMPTS.md` shape 3 already says how to RUN one ("ONE campaign, ONE slug, all
files as arms in ONE sweep group") and calls the failure "nearly universal in
practice". This says what the resulting document must contain, so Stage 7's
review gates have something to check.

---

## The one rule everything else follows from

**A comparison is not N field guides.** Three campaigns whose throughput numbers
share a table are not measuring the models; they are measuring three sweeps. On
the reference rig, **twenty-three runs of one identical configuration produced
two clusters roughly 13% apart** — twenty results between 75.71 and 78.65 t/s and
three at about 88, nothing in between, seven candidate causes tested and every
one eliminated (rule 30). A 13% unexplained gap is larger than most differences
anyone runs a comparison to find.

So: **absolutes are legal only inside one sweep.**

---

## THE ANCHOR — how a comparison stays open to new models

The obvious reading of rule 30 is that a comparison can never grow: add a model
next quarter and it lives in a different sweep, so nothing may be compared. That
would make every comparison a one-shot, which is not what anyone wants.

Rule 27 supplies the escape — *"arms that cannot share a load interleave the
reference arm"*:

> **Name ONE model the ANCHOR. Every sweep, forever, includes it. Publish every
> cross-sweep claim as a RATIO to the anchor measured in that same sweep.**

    sweep A (2026-09): anchor 118.4 t/s   ·  model X 131.3 t/s  ->  X = 1.109 x anchor
    sweep B (2026-12): anchor 104.7 t/s   ·  model Y 129.8 t/s  ->  Y = 1.240 x anchor

X and Y were never in a sweep together and **their absolutes may not be printed
side by side**. Their ratios to a common anchor may, because the two-level effect
moves the anchor and the arm together within one sweep.

Requirements on the anchor, all mandatory:

- It is a **model, pinned to a file**, not a configuration. Record its sha256.
- It runs in **every** sweep, at the same recipe, with `order: alternate` so its
  position in the sweep cannot be mistaken for a property of it (rule 30).
- **Its own absolute is published for every sweep.** A reader must be able to see
  the anchor move; that movement is the evidence that ratios were necessary.
- If the anchor file ever changes, the chain **breaks** and the document says so.
  A re-quantised anchor is a new anchor and every prior ratio is retired, not
  silently carried forward.
- Prefer the **base model** as anchor when the roster is a family: it is the one
  every derivative is defined against, and it is the least likely to be dropped.

---

## TIERS — what may be compared depends on what the models share

**Tier 1 — same architecture.** Config fields identical on every structural key
(layer count, head counts, head dim, hidden/intermediate size, attention
interval, vocab). Then:

- architecture, KV bytes/token, the fit table and the roofline are properties of
  the SHAPE and are measured **once**, not per model. The second model's job is
  to CONFIRM they match, and that confirmation is itself a published finding.
- the comparison is purely about **weights** — which is the cleanest comparison
  this repo can make, because everything else is held identical by construction.
- **Worked example, measured 2026-09-01**: `ornith-ai/Ornith-1.5-9B` against
  `Qwen/Qwen3.5-9B` — every structural field identical (32 layers,
  `full_attention_interval` 4, head_dim 256, hidden 4096, intermediate 12288,
  16/4 heads, `linear_num_key_heads` 16, `linear_num_value_heads` 32,
  `mtp_num_hidden_layers` 1, vocab 248320, 262144 context). The only diffs are
  `pad_token_id`, `use_cache`, `tie_word_embeddings` and `partial_rotary_factor`,
  none of them architectural. Ornith is Qwen3.5-9B's shape with different
  training, and the report says so in those words.

**Tier 2 — different architecture.** Each model carries its own architecture
block, its own KV arithmetic, its own fit. Nothing is measured once.

**The tokenizer gate, which is separate from the tier and is the one people
miss.** Raw perplexity and KL-divergence compare distributions over TOKENS. Two
models with different tokenizers cut the same text into different token counts,
so an equal-text PPL compares nothing (rule 6). Therefore:

| the models share a tokenizer | raw PPL / KLD across them | what to use instead |
|---|---|---|
| yes (identical `vocab_size` and vocab) | **legal, and say so explicitly** | — |
| no | **forbidden** | bits-per-byte (each model's own token count) or the rule-21 scored benchmarks — both tokenizer-independent |

A shared tokenizer is a fact to be checked and stated, never assumed from a
shared family name.

---

## The legality table — every cross-model claim names its warrant

Stage 7 checks this. A claim that cannot name its row does not ship.

| claim | legal when | published as |
|---|---|---|
| "A decodes faster than B" | both in ONE sweep | absolute t/s, both arms, sweep named |
| "A is x% faster than B" across sweeps | both measured beside the anchor | ratio to anchor, both anchors' absolutes shown |
| "A is more faithful than B" | shared tokenizer | KLD vs the unquantised base, positions stated |
| "A is more faithful than B", different tokenizers | never on KLD | bits-per-byte, or scored benchmarks |
| "A scores higher on GPQA" | same suite hash, same cap, truncations reported | score + n + truncation count |
| "A needs less VRAM" | same context, same projector/drafter state | the measured pair table |
| any architectural claim in tier 1 | configs verified identical | measured once, stated as shared |

---

## Section skeleton

The two-voice law from `REPORT-SPEC.md` applies unchanged: every section opens in
plain international English a non-expert can act on, engineering depth follows,
and the depth may never contradict the surface.

1. **What is being compared, and what is held constant** — the roster, the
   anchor, the tier, the tokenizer verdict. A reader must learn in the first
   screen whether these models share a shape.
2. **The recommendation** — which model, for which job, with the number that
   justifies it. A comparison whose reader still has to choose has failed.
3. **Held-constant block** — machine, backend, build tag, driver, desktop state,
   sampler, caps. One block for the whole document, because a comparison's whole
   value is that these did not move.
4. **Speed** — absolutes within the sweep, ratios to the anchor, the anchor's own
   absolute for every sweep in the document.
5. **Fidelity / quality** — the axis the tokenizer gate permits, never a second
   axis smuggled in beside it.
6. **Memory and fit** — measured once in tier 1, per model in tier 2.
7. **Where the models are the same** — in tier 1 this is most of the document and
   it belongs in it: "identical on every structural field" is a finding, and it
   tells a reader that a Qwen3.5-9B measurement transfers.
8. **Provenance and chain** — every sweep in the document, its date, its anchor
   absolute, and which arms ran in it. This is what lets the NEXT model join.
9. **What this comparison cannot say** — mandatory, never empty. Cross-sweep
   absolutes, axes the tokenizer forbade, models measured under different
   samplers or caps.

---

## Adding a model later — the procedure

1. New sweep, **including the anchor**, same recipe, `order: alternate`.
2. Publish the new sweep's anchor absolute beside the earlier ones. If the anchor
   has moved more than the rig's known spread, say so before any ratio is read.
3. Add the new model as ratios. **Do not restate earlier models' absolutes in the
   new sweep's table** — they were not measured in it.
4. Re-run the tokenizer gate and the tier test for the newcomer. A new model does
   not inherit the roster's tier.
5. Append to the provenance chain; never rewrite it.

---

## Review gates specific to a comparison

Beyond `REPORT-SPEC.md`'s four passes:

- **The anchor pass.** Every cross-sweep number traces to an anchor ratio. Any
  absolute spanning two sweeps is a defect, not a rounding choice.
- **The tokenizer pass.** Every PPL or KLD comparison names the shared tokenizer,
  or is not there.
- **The tier pass.** Every "measured once" claim in tier 1 names the config diff
  that justifies it.
- **The sameness pass.** A tier-1 comparison that reports only differences is
  incomplete: where two models are identical, the reader needs to know, because
  it is what makes one model's measurements transfer to the other.

---

## Slug and naming

A comparison has no single model, so the field-guide slug rule does not apply.
Use a family or cohort name and a date: `qwen35-9b-family`, `9b-class-2026-09`.
Record the anchor in `campaign.json` under `models` like any other arm, and name
it in `campaign.md`'s first line — the anchor is the document's spine and a
reader resuming after a crash needs it before anything else.
