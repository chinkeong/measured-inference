# reference-3090 — the proven scripts, as they actually ran

These are the verbatim implementations from the reference campaign
(Qwen3.8-27B on an RTX 3090, Windows/NVIDIA, 2026-08-22) that produced
`templates/example-report.html`. They are **historical artifacts, not a
library**: every path is an author-machine path and every model is the
reference model.

**Never edit these.** Copy the one you need into `results/<slug>/work/`, adapt
paths and models there, and run the copy. That is what keeps the example
report's numbers reproducible.

## Two path substitutions you will make in every script

- **`serve-qwen.bat`** — referenced by `ctx-limit-sweep.ps1`,
  `sweep-efforts.ps1`, `sweep-tune.ps1`, `sweep-pass2.ps1`, `probe-diag.ps1`
  and others, but **shipped here as `serve-menu-example.bat`** (its own header
  comment still reads `rem serve-qwen.bat`). It is the reference campaign's
  measured-menu launcher; treat it as the template for your campaign's own
  launcher, not as a file to restore under the old name.
- **`E:\AI\llama.cpp\llama-server.exe`** and `E:\AI\aider\qwen\…` — author
  machine paths. **The repo's runtime lives at `bin/llama.cpp/`** after
  `scripts/setup.ps1` / `scripts/setup.sh` runs; working files belong in
  `results/<slug>/work/` and logs in `results/<slug>/data/`.

Model paths point into an LMStudio cache
(`C:\Users\<user>\.lmstudio\models\…`); this repo downloads into `models/`
instead.

One more verbatim quirk: `ppl-compare.ps1`'s header estimates "~300k token
positions". The campaign actually scored **~330k** on the wikitext-2-raw test
split — that is the figure METHODOLOGY rule 6 and the SKILL carry. The header
is left as written.

## Script → phase map

Phase numbers here are the reference campaign's original numbering. The campaign
skill now runs Stages 0–7; its "Old numbering → stages" table
(`skills/field-guide/SKILL.md`) maps every phase below onto the stage that owns
that work today. The **Stage** column below is that mapping applied — open
`skills/field-guide/stages/stage-N.md` for the procedure a script serves.

| Phase | Stage today | Scripts | What they do |
|---|---|---|---|
| **2–3** (foundation, sanity, the -ngl trap) | **Stage 1** | `probe-config.ps1`, `probe-diag.ps1`, `probe-diag2.ps1` | `probe-config.ps1` is the canonical parameterized probe every sweep calls (fresh server + temp-0 probe + t/s); the two diag scripts surface the server's own layer-offload / speculation / timing log lines (`probe-diag2` adds `-ngld 99` for the draft context). **`probe-config.ps1` defaults to `-ngl 64`** — see the warning in its header. |
| **3** (speed, speculation, acceptance) | **Stage 3** | `spec-sweep.ps1`, `spec-sweep2.ps1`, `accept-demo.ps1`, `confirm-benchmarks.ps1`, `dflash-real-code.ps1` | MTP n-max × p-min sweep then refinement around the winner; the novel-vs-verbatim acceptance demonstration; the re-confirmation pass that re-ran every cited number with `-ngl 99`; the external-drafter (DFlash2) apples-to-apples comparison. |
| **4** (memory, context ceilings) | **Stage 2** | `ctx-limit-sweep.ps1`, `iq4-ctx-sweep.ps1`, `verify-recommend.ps1` | Step `-c` upward to the spill tipping point and binary-refine (Q4_K_M, then IQ4_XS); then verify the promoted defaults under real desktop VRAM load with a short probe, a deep prompt, and VRAM sampling. |
| **5** (depth) | **Stage 3** | `deep-decode-probe.ps1`, `nuance-suite.ps1` (part 1) | The server-timings prefill/decode split at ~27k depth; the nuance suite's depth/prefill series. `nuance-suite.ps1` also carries part 2 (q8 KV quality PPL → Phase 6), part 3 (`--parallel 2`), and part 4 (multi-image vision → Phase 8). |
| **6** (quality: perplexity) | **Stage 1** screen, **Stage 6a** ranking | `ppl-compare.ps1` | Perplexity over wikitext-2-raw across the local quants; downloads and caches the corpus; resumable, one model per invocation. |
| **6–7** (quality: accuracy) | **Stage 6a/6b** | `quant-accuracy.ps1`, `iq4-accuracy.ps1`, `effort-gsm8k.ps1`, `xhigh-16k.ps1` | n=200 greedy scored GSM8K: paired across quants, the final gate for the promoted quant, per effort level, and the 16k-cap rerun that removed the truncation artifact from the xhigh arm. All drive `scripts/bench/bench.py`. |
| **7** (effort) | **Stage 4** appetite, **Stage 6b** arms | `sweep-efforts.ps1`, `sweep-pass2.ps1`, `sweep-tune.ps1`, `extract-html.ps1` | Pass 1 and pass 2 of the effort sweep (two independent samples per level for blind judging); `sweep-tune.ps1` first finds the largest context that still decodes fast, then sweeps there; `extract-html.ps1` pulls the HTML answer out of each output file. The prompt these read (`prompt.md`) ships as `templates/effort-task-example.md`. |
| **serving** | **Stage 5 / 7** | `serve-menu-example.bat` | The measured-menu launcher: numbered configs, each with the measurement that justifies it. The pattern REPORT-SPEC §3 (the recipes chapter) asks every report to produce. |

## Adapting on POSIX

Every script here is PowerShell — the reference machine was Windows.
`scripts/probe-config.sh` is a bash port of `probe-config.ps1`, provided as the
adaptation seed for Linux/macOS campaigns. The POSIX equivalents for
detaching, parse-checking and VRAM diagnostics live in
`reference/platform-notes.md` — grep it by symptom.
