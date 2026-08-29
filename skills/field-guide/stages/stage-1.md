---
name: stage-1
description: Load when executing Stage 1 (STRUCTURE, ~1 h, cheap probes only) — acquire runtime and weights, take KV bytes/token from the Stage-0 model profile and cross-check it, verify -ngl 99, one floor probe per quant, and the early pruning gate that drops files before they earn expensive treatment.
---

# Stage 1 — STRUCTURE (~1 h, cheap probes only)
Nothing in this stage may cost an hour of GPU on its own. Its products: runtime
and files on disk, the KV arithmetic, a verified `-ngl`, one floor number per
candidate quant, and a candidate roster that has already been pruned.

**Acquire** (network, parallel with nothing). `scripts/setup.ps1|sh` fetches a
llama.cpp build into `bin/` for this platform, creates `.venv` from
`requirements-min.txt`, and records what it installed in
`bin/llama.cpp/INSTALL.json` — `flavor` (cuda/vulkan/metal/cpu), tag, driver.
Copy that flavor and tag into `campaign.md` now; it is a condition of every
number that follows (rule 3). **On Linux + NVIDIA there is no official CUDA
binary, so `setup.sh` refuses to install a Vulkan one and exits 3: run
`./scripts/setup.sh --cuda` (needs `nvidia-cuda-toolkit cmake build-essential
git`, 10–25 min) — a Vulkan campaign is not comparable to a CUDA one.** Download
the chosen quants + mmproj into `models/` (curl, resumable, verify byte sizes
against the HF listing). Download nothing you won't measure.

**Foundation & sanity**
- **KV bytes/token comes from `results/<slug>/model-<LABEL>.json`**, the
  Stage-0 profile — the budget-table backbone, read out of the header of the
  very file this campaign loads. `kv_bytes_per_token` gives f16, q8_0 and q4_0;
  `kv_arithmetic.lines` prints the derivation to copy into `campaign.md`:

  **KV bytes/token = 2 × full-attention layers × n_kv_heads × head_dim ×
  bytes-per-element** — 2 = K and V; bytes-per-element = 2 for fp16 cache, 1
  for `q8_0`. For a plain transformer, full-attention layers = all layers. For
  hybrids (the reference model is Gated-DeltaNet + full attention every 4th
  layer) count only the full-attention ones; linear/gated-delta layers carry a
  fixed-size state, and sliding-window layers cap at their window — note both
  as separate constants rather than folding them into the per-token figure.

  **Cross-check the header against the base repo's `config.json` and against
  the server's reported KV size at a known `-c`** — two independent cheap
  readings agreeing beat one (rule 4), and on the reference 27B they agree.
  The header derives 16 full-attention layers × 4 kv-heads × (key_length 256 +
  value_length 256) = 32,768 values = **65,536 B/token** at f16; `python
  scripts/check-request.py unsloth/Qwen3.8-27B-GGUF --quant UD-IQ4_XS --c-min
  65536`, reading the base repo's `config.json`, prints `KV bytes/token = 2 x 16
  full-attn x 4 kv-heads x 256 head-dim x 2 B = 65,536`. Keep `config.json` as
  the cross-check and never promote it back to the source: it 404s on
  quant-only repos (verified 2026-08-29 — `ibm-granite/granite-4.0-h-tiny-GGUF`
  answers 404, the reference repo answers 200), and its transformers-era
  `layer_types` vocabulary does not always name the layers that hold a cache, so
  a hybrid can read out at 0 B/token, which is a green light for every context
  rather than a conservative answer. If the two disagree, trust the server, then
  the header, and record which and why in `campaign.md`. llama-server's own
  startup dump (`n_layer`, `n_head_kv`, `n_embd_head_k` / `n_embd_head_v`) is
  the third reading when they do.
- **The -ngl trap**: llama.cpp counts the output layer as layer n+1. Always use
  `-ngl 99`; verify with a baseline probe that decode ≈ bandwidth ÷ file-size ×
  0.7 (reference: `probe-config.ps1` — note its header warning: it defaults to
  `-ngl 64` and relies on callers passing `-ngl 99`; POSIX seed:
  `scripts/probe-config.sh`, which defaults correctly). If it lands far low with
  high CPU and ~60% GPU util, an output layer is on the CPU.
- Spill prevention: document "Prefer No Sysmem Fallback" (NVIDIA) or platform
  equivalent; record the machine's idle VRAM (desktop overhead).
- Discover the effort/thinking knob (`--chat-template-kwargs`) and the sampling
  the model card recommends.
- Take the **loaded-idle** power baseline the first time the server is up and
  idle (Stage 0 holds the cold, no-server one).

**One floor probe per candidate quant.** Baseline, no speculation, temp 0, short
code probe → the **floor** (reference: `probe-config.ps1`, called with `-ngl 99`;
POSIX seed: `scripts/probe-config.sh`). Cross-check each floor against rule 10's
arithmetic (GB/s ÷ file GB × 0.7, re-deriving the efficiency constant per
format). One probe per file, not a sweep — the sweeps are Stage 3's, and they
only run on files that survive the gate below.

**The early pruning gate — the cheapest decision of the campaign.** Before any
file earns expensive treatment, screen the roster on three cheap numbers:
1. `llama-bench -p 0 -n 128` (tg128) per file — or the floor probe above, if the
   build ships no `llama-bench`;
2. file size on disk (rule 10: bytes per token IS the decode budget);
3. a **short PPL screen** — the same small fixed set of wikitext-2-raw chunks
   for every file (4 × 8,192 tokens is enough), identical chunks across files
   (adapt `ppl-compare.ps1` with a chunk cap; it is resumable).

**Drop, right here, any file that is both slower AND worse on the screen.** It
cannot win on an axis a reader cares about, and carrying it further buys one
word: the reference campaign took UD-Q4_K_XL through the full treatment to
conclude "pointless". Record the drop in `campaign.md` with both numbers and the
words "screened out at the Stage-1 gate"; the report says it was screened out
and how — never that it was untested. A file that is slower but better, or
faster but worse, is a real trade-off and survives to Stage 2. The screen ranks
nothing publishable: PPL over four chunks is a screen, and the publishable
ranking is Stage 6's full run under rule 6.
