# qwen35-9b-family — a comparison, not a field guide

Governed by `templates/COMPARISON-SPEC.md`, not `REPORT-SPEC.md`.

**ANCHOR: `Qwen/Qwen3.5-9B`**, the base every arm in this roster is defined
against. COMPARISON-SPEC: *"Prefer the base model as anchor when the roster is a
family."* Every sweep in this document, forever, includes it, and every
cross-sweep claim is published as a RATIO to the anchor measured in that same
sweep.

## 2026-09-02 — why this campaign exists

`results/ornith-1.5-9b-mtp/` measured Ornith-1.5-9B exhaustively over two days.
Every comparison it makes against Qwen3.5-9B is **cited, not measured** — the
vendor's published MMMU 78.4, Terminal-Bench 18.9, SWE-bench 53.2 — and that
campaign itself recorded that those baselines were produced *by Ornith*, the
vendor whose model they are the baseline for.

Rule 1 allows a cited number. Rule 30 does not allow a comparison built from
one: **arms compare only INSIDE one sweep.** So no legal Ornith-vs-Qwen3.5
claim existed anywhere in this repo, and this campaign is the sweep that makes
one possible.

## Roster and the file choice, which was the first trap

| arm | file | source | block_count | size |
|---|---|---|---|---|
| **Qwen3.5-9B** (anchor) | `Qwen3.5-9B-Q8_0.gguf` | `unsloth/Qwen3.5-9B-MTP-GGUF` | **33** | 9.11 GiB |
| Ornith-1.5-9B | `Ornith-1.5-9B-MTP-Q8_0.gguf` | `protoLabsAI` (MTP) | **33** | 9.11 GiB |

The Ornith campaign's Stage 0 found that third-party conversions silently drop
the multi-token-prediction layer — 243,290,624 parameters — leaving a 32-block
model, and that the file size gives it away. That finding reproduced exactly
here, across a different model, before anything was downloaded:

    Q8_0 with the MTP layer     9.79 GB   unsloth/...-MTP-GGUF, bartowski
    Q8_0 without it             9.53 GB   lmstudio-community

Those are the same two sizes the Ornith table records for its own lineages.
Taking `lmstudio-community`'s 9.53 GB file would have put a **32-block model
against a 33-block one** and published the difference as a model comparison.

## Tier and the gates

**TIER 1, verified at the GGUF header** rather than only at the HF config:
`arch qwen35`, `block_count 33`, `context_length 262144`, `embedding_length
4096`, `head_count 16`, `head_count_kv 4`, `head_dim 256`, and an identical
`kv_bytes_per_token` table. So architecture, KV arithmetic, the fit table and
the roofline are properties of the SHAPE and are measured ONCE.

**Two differences, both of which matter and neither of which is architectural:**

- **The chat templates differ** (different sha256). This is not cosmetic here:
  Ornith's own published benchmark footnotes say they *"adjust the Qwen chat
  template to ensure consistency between training and inference"* — and their
  Qwen3.5-9B baseline row never says it received the same fix. A template
  difference is a condition that travels with every scored number (rule 3), and
  each arm runs with its OWN template, which is the only defensible choice.
- **Qwen3.5-9B ships NO draft head** (`drafter: null`); Ornith ships one. The
  speculative-decoding arms of the Ornith campaign therefore have no counterpart
  here and no ratio may be formed for them. Published as an asymmetry, not
  quietly dropped.

## What is being measured for the anchor, and what is deliberately not

Ornith-1.5-9B is the subject; Qwen3.5-9B is the **anchor**, and an anchor needs
only what a legal comparison requires — not a second full field guide.

| | why |
|---|---|
| **A — paired anchor sweep** | both arms in ONE sweep, fully crossed over 2 samplers, 4 reps with the first discarded (rule 12), alternating order (rule 30). This is what makes any Ornith-vs-Qwen speed claim legal, and it publishes the anchor's own absolute so a later sweep can form ratios against it. |
| **B — rule-21 suite on Qwen3.5-9B** | the same frozen suite hash `1cdf54f8eb9d3f8f` the Ornith arm and `qwen38-27b-blind` ran, so the composite Means are comparable by construction (rule 23). |
| ~~GPQA Diamond~~ | **NOT queued, deliberately.** It cost 7 h 55 m on Ornith and its value there was validating the harness against a published figure. Re-spending a day on the anchor buys a number this comparison does not need. Recorded as an omission rather than left to look like an oversight. |
| ~~KLD across models~~ | **not a legal instrument here.** KL divergence asks how far a quant is from ITS OWN unquantised weights; pointed at two different models it compares distributions that were never meant to agree. A shared tokenizer is a necessary condition for that comparison, not a sufficient one. |
| ~~speculative arms~~ | **impossible, not skipped.** Qwen3.5-9B ships no draft head, so there is no counterpart to Ornith's MTP arms and no ratio can be formed. |

`work/run-to-publish.py` runs A then B unattended: resumable through
`data/chain-state.json`, a heartbeat before and after every step, each child
taking the GPU lock itself so rule 20 holds without the chain knowing anything
about the card, and a checkpoint commit after each step.

## Stage 7 publish target — mirrored, never auto-pushed

The finished report is `results/qwen35-9b-family/index.html`, and it is mirrored
to **`~/Workspace/chinkeong.github.io/qwen-9b/index.html`** —
`github.com/chinkeong/chinkeong.github.io`, branch `master`. The precedent is
`results/qwen38-27b-blind` → `qwen-27b/`, which carries `index.html`,
`figures/`, `quant-ladder.png` and the standalone agentic reports.

`scripts/report/mirror-to-pages.sh <slug> <page-dir>` does the copy. **It does
not commit and it does not push, deliberately.** Everything else in this tree
pushes automatically because measured data on one disk is at risk (rule 28) and
that remote is the author's own working repo. This target is a **public
website**: a wrong number on a public page is read, cached and cited before it
can be corrected, so the last step stays a human decision. The script stages the
bytes, refuses outright while `index.html` is absent or still contains
TODO/PLACEHOLDER/FIXME, and prints the two commands that would publish.
