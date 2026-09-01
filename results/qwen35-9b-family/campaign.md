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
