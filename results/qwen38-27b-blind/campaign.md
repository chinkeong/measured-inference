# Campaign log — qwen38-27b-blind

> **Canonical numbers** live at the end of this file, under
> "The canonical list". Anything in the report must match a line there.


**Blind reproduction test** of the measured-inference methodology. Every number
below was produced on this machine tonight; no prior campaign's results were
consulted (blinding protocol: `chinkeong.github.io/**`,
`templates/example-report.html`, and all `.txt/.json/.log/*summary*` under
`E:\AI\aider\qwen\` were never opened; the one exception is `wiki.test.raw`,
which is input data, not a result).

## Phase 0 — interview (pre-answered, no questions asked)

| Item | Answer |
|---|---|
| Slug | `qwen38-27b-blind` |
| Model | `Qwen3.8-27B`, single quant: `unsloth/Qwen3.8-27B-GGUF` → `Qwen3.8-27B-UD-IQ4_XS.gguf` (13.27 GiB) |
| Projector | `lmstudio-community/Qwen3.8-27B-GGUF` → `mmproj-Qwen3.8-27B-BF16.gguf` (0.867 GiB) |
| Machine | RTX 3090 24 GiB, Windows 11 Pro 26200, driver 596.36 |
| Runtime | pre-existing `E:\AI\llama.cpp\llama-server.exe` (**deviation**: `scripts/setup.ps1` skipped to save wall time) |
| Port | 1234, one GPU job at a time |
| Use cases | text coding + vision |
| Philosophy | quality-first |
| Time budget | SMOKE TIER, hard cap ~4 h of measurement |
| Skipped by instruction | Phase 1 (files present), Phase 6 n=200 accuracy, Phase 8 agent-attach matrix + critique loop, Phase 9 agents |
| Vision scope | resolution→token cost of ONE 1440p Chrome-headless screenshot, direct API |

## Deviations from the SKILL (declared up front)

1. **Phase 1 skipped** — model + projector already on disk; `setup.ps1` not run,
   the machine's existing llama.cpp build is used instead of a repo-local `bin/`.
2. **Single quant** — no quant ranking is possible or published. Perplexity is
   reported as a single absolute number, not a ranking.
3. **Phase 6 accuracy (n=200) skipped** — time. The report says so; no accuracy
   number is published at all rather than a misleading small-n one.
4. **Phase 7 at n=1 per level** (skill asks 2). Judged statically by one judge
   (me), not blind subagents — labelled as such, and no winner is crowned.
5. **Phase 8 reduced** to the resolution→token map only. Critique loop and
   agent-attach matrix explicitly unmeasured.
6. **Phase 9 skipped**.

7. **Port 1234 was already bound** by a running LM Studio instance. Rather than
   kill the user's application, everything was measured on **port 1235**. Port
   has no effect on any measured quantity; the published recipes use 1234.
8. **`--load-mode mmap` instead of the reference's `--load-mode none`.** The
   sweeps restart the server ~25 times; mmap lets the OS page cache hold the
   weights so a reload costs ~6-10 s instead of ~60-90 s. With `-ngl 99` every
   weight ends up in VRAM either way, so load mode cannot affect decode speed
   (and phase 2 vs phase 3 repeat probes agree to 0.7 %). Recipes therefore
   publish `--load-mode mmap`.

   **What that verification does and does not cover.** Decode-neutrality was
   checked and held. The *other* half of the `--load-mode none` argument — the
   system-RAM footprint, roughly 15 GB of page cache held by the mapped weight
   file, which is the reason the flag exists at all — **was never examined in
   this campaign**. No system-RAM measurement was taken under either mode, so
   nothing here says what mmap costs a RAM-tight machine, and the deviation is
   only justified on the axis that was measured. A reader with 16 GB of system
   RAM should treat the published `--load-mode mmap` as untested for their
   case. Closing it is cheap: one `\Process(llama-server)\Working Set` and
   system-wide available-MB reading per mode, no GPU time.

9. **Two measurement steps were moved from PowerShell to Python** after
   PowerShell 5.1 failed at them: the vision request (`Invoke-RestMethod`
   cannot post the ~261 KB body a 1440p PNG data-URI produces - the request
   never reaches the server and throws no useful error), and the power
   integration (`[datetime]::TryParseExact` overload resolution). Both are
   recorded in the report; the vision failure is published as a troubleshooting
   entry because it is the kind of thing that looks like a model problem.
10. **Nine phases were ADDED that the skill does not list**, each because a
    measurement raised a question the plan did not anticipate:
    - **3b** content sweep - is the drafting winner prompt-specific? (yes)
    - **3c** acceptance verification with the text saved - were the probes
      even producing answers? (no)
    - **3d** answer-token control with thinking disabled - the real
      acceptance demonstration
    - **4b** MTP memory isolation - what does the drafter cost per token?
    - **4c** the collapse point - is the "shallow-safe" ceiling real? (no)
    - **4d** promoted-recipe verification - does the shipped drafter change
      the ceiling? (yes, by 898 MiB)
    - **5b** depth for the shipped recipe on answer tokens - the table a
      reader actually needs, found missing by the reader-experience review
    - **7b** the xhigh re-run at a raised cap (METHODOLOGY rule 7)
    - **8b** the vision retry in Python
    - **10b** per-recipe power and VRAM
    Six of the nine changed a published conclusion.

---

## Timeline

### 00:19 - Phase 0/2 start
Machine detected: RTX 3090 24 GiB (driver 596.36), i5-13600KF 14C/20T,
**31.8 GiB RAM as 2 x 16 GiB DDR4-3200 (dual channel)**, Windows 11 Pro 26200.
Idle board VRAM with desktop up: **1179 MiB**.

**config.json (fetched live from `Qwen/Qwen3.8-27B`, saved to `data/config.json`)**
- 64 layers, `full_attention_interval: 4`, `layer_types` lists **16
  `full_attention` layers** (indices 3, 7, ... 63) and **48 `linear_attention`
  (Gated-DeltaNet) layers**.
- `num_key_value_heads: 4`, `head_dim: 256`, `hidden_size: 5120`,
  `num_attention_heads: 24`, `vocab_size: 248320`, `max_position_embeddings:
  262144`, `partial_rotary_factor: 0.25`, `rope_theta: 1e7`.
- Linear layers: `linear_num_key_heads 16`, `linear_key_head_dim 128`,
  `linear_num_value_heads 48`, `linear_value_head_dim 128`,
  `linear_conv_kernel_dim 4`, `mamba_ssm_dtype float32`.
- `mtp_num_hidden_layers: 1` -> the GGUF carries a built-in MTP head
  (`blk.64.nextn.*`), so `--spec-type draft-mtp` needs no companion drafter.
- Vision tower: patch 16, `spatial_merge_size 2` -> one visual token per
  32 x 32 px block.
- Chat template exposes `reasoning_effort` in `low | medium | xhigh`
  (default **xhigh**; `high` is silently aliased to `xhigh`; anything else
  raises). Only `low` and `xhigh` inject a reasoning-instruction system line;
  `medium` injects none.

**KV arithmetic (derived)**
`KV bytes/token = 2 x full-attn layers x n_kv_heads x head_dim x bytes/elem`
- fp16: `2 x 16 x 4 x 256 x 2` = **65,536 B/token = 64 KiB/token**
- q8_0 nominal: **32,768 B/token = 32 KiB/token**; with q8_0's fp16 block scale
  (34 B per 32 values) the real cost is **34,816 B/token = 34 KiB/token**.
- So **1 GiB of q8_0 KV buys ~30.8k tokens**; a 32k q8 window costs ~1.06 GiB.
- The 48 Gated-DeltaNet layers carry a **fixed** state, not a per-token one:
  conv `4 x (2x16x128 + 48x128) = 40,960` fp32 elems + recurrent
  `48 x 128 x 128 = 786,432` fp32 elems = 3.16 MiB/layer x 48 =
  **~151 MiB per sequence, independent of context length**. Three quarters of
  this model's layers cost nothing extra as the window grows - that is why a
  27B model can hold a 262k window on a 24 GiB card at all.

**Phase 2 probes** (IQ4_XS, `-c 32768`, `--spec-type none`, temp 0/top_k 1,
83-token code prompt, 700 predicted tokens, desktop idle):

| arm | decode t/s | board VRAM | llama-server dedicated | shared |
|---|---|---|---|---|
| `-ngl 99`, q8_0 KV | **42.31** | 15,661 MiB | 14,480 MiB | 132 MiB |
| `-ngl 99`, f16 KV | **43.19** | 16,428 MiB | 15,354 MiB | 132 MiB |
| `-ngl 64`, q8_0 KV | **29.84** | 15,256 MiB | 14,182 MiB | 142 MiB |

- **The -ngl off-by-one is real on this model**: `-ngl 64` (= n_layer) leaves
  the output projection on the CPU and costs **29.5 % of decode** (42.31 ->
  29.84 t/s; `-ngl 99` is **1.42x** faster). Load succeeded and VRAM looked
  almost identical - the only signature is the speed.
- f16-vs-q8 KV dedicated delta = 874 MiB over 32,768 tokens = 27.3 KiB/token
  measured, against 30 KiB/token predicted (9 % low). Perf-counter granularity;
  the phase-4 slope over a 230k-token span is the better check.
- Bandwidth sanity: 936 GB/s / 14.25 GB file = 65.7 t/s theoretical, x0.7 =
  46.0 t/s expected floor; **measured 42.3 t/s = 0.64 of raw bandwidth**. In
  the expected band -> full offload confirmed, no silent spill.
- With `--spec-type none` the server logs `model has unused tensor blk.64.*
  -- ignoring`: the MTP head is simply not loaded. Speculation is free to
  turn off and costs ~300 MiB of VRAM to turn on.

**Phase 2 elapsed: 00:19 -> 00:23 (4 min, incl. one false start on the bound port).**

### 00:24 - Phase 3: speed, speculation, acceptance

MTP sweep. Conditions on every row: IQ4_XS, `-c 32768`, `-ngl 99`, q8_0 KV,
`--parallel 1`, temp 0 / top_k 1, 83-token novel-JS-code prompt, 700 predicted
tokens, desktop idle, port 1235. Fresh server per config. Acceptance =
`timings.draft_n_accepted / timings.draft_n` reported by the server.

| config | decode t/s | vs no-spec | drafted | accepted | acceptance |
|---|---|---|---|---|---|
| `--spec-type none` | 42.61 | 1.00x | - | - | - |
| mtp n-max 3, p-min 0 | 81.97 | 1.92x | 580 | 505 | 87.1 % |
| mtp n-max 4, p-min 0.75 | 80.99 | 1.90x | 565 | 508 | **89.9 %** |
| mtp n-max 6, p-min 0.5 | 80.18 | 1.88x | 794 | 548 | 69.0 % |
| mtp n-max 10, p-min 0 | 87.31 | 2.05x | 1229 | 575 | 46.8 % |
| **mtp n-max 10, p-min 0.5** | **87.39** | **2.05x** | 969 | 574 | 59.2 % |
| mtp n-max 10, p-min 0.75 | 80.32 | 1.88x | 744 | 538 | 72.3 % |
| mtp n-max 16, p-min 0.5 | 80.32 | 1.88x | 1233 | 581 | 47.1 % |

**Finding that contradicts the prior expectation**: on this model the
*highest-acceptance* config is not the fastest. n4/p0.75 accepts 89.9 % but
runs 80.99 t/s; n10/p0.5 accepts only 59.2 % and runs 87.39 t/s. The MTP head
is cheap enough that speculating deeper and being wrong more often still wins.
Acceptance alone does not rank configs; **accepted-tokens-per-target-pass**
does. The spread across all eight configs is only 80-87 t/s, so the choice is
worth ~8 %, while turning MTP on at all is worth ~105 %.

**Acceptance demonstration (same server, same flags n10/p0.5):**
- novel code generation: 89.06 t/s, acceptance 59.2 %
- verbatim copying of a supplied JS snippet: 59.26 t/s, acceptance 54.7 %

At n10/p0.5 this reads as the **opposite** of the expected result, and my
first two explanations were both wrong. **Correction, after Phase 3c saved the
generated text:** neither of those probes ever copied anything - both spent all
700 tokens *thinking about* the copy task and returned an empty `content`
field. Speculative decoding is lossless at greedy sampling, so the n4/p0.75 and
n10/p0.5 runs of that prompt emitted the **identical** token sequence; the
96.3 % vs 54.9 % acceptance gap is about predicting *that reasoning stream* 4
tokens ahead vs 10, not about copying. See the Phase 3c entry below.

**Phase 3b - anti-overfit control.** With `--spec-type none` decode is flat
across content: code-js 42.81, code-py 42.77, prose 42.66, verbatim 42.47 t/s
(spread 0.8 %). So content type does nothing without speculation; every
content-dependent number in this report is a speculation effect.

Same four contents, two tuned MTP configs (fresh server each, four probes per
server, 700 predicted tokens, temp 0):

| content | n10/p0.5 t/s | acceptance | n4/p0.75 t/s | acceptance | no-spec t/s |
|---|---|---|---|---|---|
| novel JS (red-black tree) | **88.77** | 59.2 % | 78.71 | 89.9 % | 42.81 |
| novel Python (LRU+TTL+tests) | **63.09** | 56.5 % | 56.36 | 87.4 % | 42.77 |
| English prose (500 w explainer) | 48.42 | 43.2 % | **51.68** | 79.9 % | 42.66 |
| verbatim copying (JS snippet) | 56.44 | 54.9 % | - | - | 42.47 |

**The single-prompt sweep overfits, demonstrated.** n10/p0.5 beats n4/p0.75 by
13 % on the prompt the sweep was tuned on, ties on Python, and *loses* by 6 % on
prose. Published as a case study, not as a universal winner. The report ships
n10/p0.5 for a coding workload and says exactly that.

**Derived: accepted tokens per target pass.** Acceptance rate alone does not
rank configs. Target passes = `predicted_n - draft_n_accepted` (each pass emits
one target token plus every accepted draft), so accepted-per-pass =
`draft_n_accepted / (predicted_n - draft_n_accepted)`:

| config | acceptance | accepted / target pass | drafted / pass | t/s |
|---|---|---|---|---|
| n3/p0 | 87.1 % | 2.59 | 2.97 | 81.97 |
| n4/p0.75 | 89.9 % | 2.65 | 2.94 | 80.99 |
| n6/p0.5 | 69.0 % | 3.61 | 5.22 | 80.18 |
| n10/p0 | 46.8 % | 4.60 | 9.83 | 87.31 |
| n10/p0.5 | 59.2 % | 4.56 | 7.69 | 87.39 |
| n10/p0.75 | 72.3 % | 3.32 | 4.59 | 80.32 |
| n16/p0.5 | 47.1 % | 4.88 | 10.36 | 80.32 |

n16 accepts the most per pass and is still slow: the draft itself costs. The
optimum is a ridge, not a monotone.

**Phase 3 + 3b elapsed: 00:24 -> 00:31 (7 min).**

### 00:31 - Phase 4: memory, the two ceilings

Context ceiling sweep. Conditions: IQ4_XS + **mmproj loaded**, `-ngl 99`,
q8_0 KV, `--parallel 1`, MTP n4/p0.75, `--image-min-tokens 1024`, fresh server
per step, 20-token probe / 200 predicted tokens (deliberately SHALLOW), desktop
idle at 1179 MiB. `ded`/`shr` are llama-server's own GPU Process Memory perf
counters; `board` is nvidia-smi total.

| `-c` | board MiB | server dedicated | server shared | shallow decode t/s |
|---|---|---|---|---|
| 32,768 | 17,978 | 16,816 | 190 | 63.63 |
| 65,536 | 19,356 | 18,194 | 254 | 64.06 |
| 98,304 | 20,764 | 19,602 | 318 | 63.80 |
| 131,072 | 22,172 | 21,010 | 382 | 63.84 |
| **163,840** | **23,580** | **22,418** | 446 | 63.74 |
| 196,608 | 24,132 | 23,637 | **700** | 59.72 |
| 229,376 | 24,145 | 23,716 | **2,096** | 60.44 |
| 262,144 (native max) | 24,162 | 23,784 | **3,502** | 59.06 |
| 262,144, mmproj OFF | 24,162 | 23,782 | 2,364 | 58.85 |

- Dedicated VRAM grows **exactly 1,408 MiB per 32,768 tokens** across the four
  linear steps (16,816 / 18,194 / 19,602 / 21,010 / 22,418) = **45,056 B per
  token** of window. That is 10,240 B/token MORE than the q8_0 arithmetic
  predicts (34,816). Phase 4b isolates why.
- **Fully-resident ceiling (desktop-safe): 163,840 tokens.** At 163,840 the
  board sits at 23,580 of 24,576 MiB with the desktop's 1,179 MiB already
  inside that figure - 996 MiB of slack, and slack is the anti-spill budget.
  Extrapolating the slope, the arithmetic wall is ~187k tokens on a bare
  desktop; nothing between 163,840 and 196,608 was tested, so 163,840 is what
  this report ships.
- **Shallow-safe ceiling: 262,144 tokens = the native maximum.** The server
  loads and answers a short prompt at 59.1 t/s with **3.5 GiB living in system
  RAM**. This looks like a free lunch and is not one - see Phase 4c.
- **The projector costs 1,138 MiB** (3,502 - 2,364 MiB of shared spill at the
  same window, mmproj on vs off): ~1.11 GiB = **~25,900 tokens of q8_0 window**
  at this model's measured 45,056 B/token. Turning vision off buys you about
  26k tokens of context.
- Allocating a huge but resident window is free in speed: 63.6-64.1 t/s across
  32k..163k (spread 0.7 %). Only overcommitment costs (59-60 t/s, -6 %).

**Phase 4b - what MTP costs in memory.** Same sweep endpoints with
`--spec-type none` (mmproj still on): `-c 32768` -> 15,618 MiB dedicated,
`-c 163840` -> 20,610 MiB. Slope = 4,992 MiB / 131,072 tokens =
**39,936 B/token** for the cache alone.

| configuration | B per window token | delta |
|---|---|---|
| config.json arithmetic, q8_0 + block scales | 34,816 | (floor) |
| measured, MTP off | **39,936** | +5,120 vs arithmetic |
| measured, MTP on | **45,056** | **+5,120 for the draft path** |

So **speculation costs 11.4 % of the window** on top of ~1.2 GiB of fixed
allocation (16,816 - 15,618 MiB at `-c 32768`). The +5,120 B/token gap between
the arithmetic floor and the measured MTP-off slope is unexplained by
config.json alone (alignment/padding is the likely cause); the report publishes
the measured slope and says the arithmetic is a floor.

Cross-check that landed: the projector's cost measured **1,138 MiB** two
independent ways - (a) shared-memory difference at `-c 262144` mmproj on vs off
(3,502 - 2,364), and (b) dedicated difference at `-c 32768` between the Phase-2
no-projector load (14,480) and the Phase-4b projector load (15,618). Two cheap
metrics agreeing.

**Phase 4 + 4b elapsed: 00:31 -> 00:40 (9 min).**

### 00:34 - Phase 5: depth

One server, `-c 131072`, IQ4_XS, `-ngl 99`, q8_0 KV, MTP n4/p0.75, no
projector, temp 0 / top_k 1, 300 predicted tokens per point. Each prompt is
prefixed with a fresh GUID so llama.cpp's prefix cache cannot be reused and
`prompt_n` / `prompt_ms` describe the whole prefill. Server `timings` only.

| depth (tokens) | prefill t/s | prefill wall | decode t/s | acceptance | naive tok/wall |
|---|---|---|---|---|---|
| 1,533 | 1,082 | 1.4 s | 51.15 | 79.6 % | 41.3 |
| 10,658 | 1,198 | 8.9 s | 50.32 | 88.7 % | 20.0 |
| 28,423 | 1,097 | 25.9 s | 47.07 | 92.3 % | 9.2 |
| 56,840 | 951 | 59.8 s | 41.07 | 91.1 % | 4.4 |
| 92,679 | 816 | 113.6 s | 35.81 | 85.9 % | 2.4 |

- **Decode falls 30 % (51.15 -> 35.81) while acceptance RISES** (79.6 % ->
  92.3 % peak). The decline is KV read cost per token, not a drafting failure.
  This is the cleanest possible demonstration that acceptance and depth are
  independent axes.
- Prefill decays only 25 % over a 60x longer prompt. ~1,000 tokens/s is the
  planning figure.
- The naive column is what tokens-divided-by-wall-clock reports. At 28k depth
  it says 9.2 t/s where decode is 47.1. Publish that number and every reader
  measures less than promised.

**Phase 5 elapsed: 00:34 -> 00:39 (5 min).**

### 00:40 - Phase 4c: the collapse point (added, not in the original plan)

The shallow sweep says 262,144 "works". That is a trap and it needed proving.
Same prompts, same flags (mmproj on, MTP n4/p0.75), only `-c` differs:

| depth | `-c 131072` resident | `-c 262144` (3.5 GiB in RAM) | penalty |
|---|---|---|---|
| 1,531 tok | 53.48 t/s | 42.92 t/s | 1.25x |
| 29,837 tok | 47.30 t/s | **18.64 t/s** | **2.54x** |
| 90,886 tok | 30.61 t/s | **8.02 t/s** | **3.82x** |

Prefill collapses with it: 818.9 -> 182.9 t/s at 90.9k, and 1,084.8 -> 408.2 at
29.8k. Draft acceptance is *unchanged* (0.849 vs 0.907 at 90.9k; 0.903 vs 0.895
at 29.8k), which rules out any drafting explanation - this is purely the KV
cache being read across PCIe.

**The shallow-safe ceiling is a measurement artefact of shallow probes.** A
reader who trusted it would get 26 % of the promised speed the first time they
loaded a 90k-token document - 8 t/s on a card that does 50. Reported as the
collapse point, and the recipes ship 163,840.

Cross-check: Phase 4c's `-c 131072` + projector row at ~90.9k depth reads 30.61
t/s where Phase 5's projector-less `-c 131072` at 92.7k read 35.81 t/s. Both
fully resident; the ~14 % difference is the projector's runtime cost at depth
and is reported as a separate conditioned row rather than averaged away.

### 00:37 - Hardware matrix citations (no GPU time)

A subagent verified every bandwidth figure against primary vendor documents.
Two findings changed the report:

1. **The RTX 3090 is 936 GB/s, not 936.2.** 936 is NVIDIA's own figure in the
   GA102 whitepaper (384-bit x 19.5 Gbps). 936.2 is a third-party derivation
   from the unrounded 1219 MHz memory clock - not wrong, but false precision
   with no primary source. The report cites 936.
2. **The RTX 4060 Ti's widely-quoted 554 GB/s is not bandwidth.** It is
   NVIDIA's own *effective*-bandwidth argument about the card's 32 MB L2.
   Peak is 288 GB/s and that is the only correct entry in a bandwidth column.

Also noted: Apple's M4 Max is 410 or 546 GB/s depending on the bin, so "up to
546" is a silicon ceiling and not a machine's figure. TechPowerUp and AnandTech
were both unreachable behind bot challenges and were not cited; a naive scrape
of TechPowerUp returns a valid-looking page with zero spec content.

Derived-decode formula used in the report:
`t/s = bandwidth GB/s / 14.25 GB x 0.649`, where 0.649 is THIS machine's
measured achieved-to-raw ratio (42.61 / 65.7). Every non-3090 row is labelled
derived, and the non-CUDA rows are additionally flagged as softer because the
efficiency constant is a CUDA-backend measurement.

### 01:40 - Phase 4d: verifying the promoted recipes (this changed them)

The ceiling sweep ran at MTP n4/p0.75. The coding recipe ships n10/p0.5. That
turned out to matter:

| config | -c | board MiB | dedicated | shared | slack | decode t/s |
|---|---|---|---|---|---|---|
| **shipped R1**: mmproj + n10/p0.5 | 163,840 | **24,039** | 23,189 | 574 | **537** | 74.61 |
| (same window at n4/p0.75, Phase 4) | 163,840 | 23,580 | 22,418 | 446 | 996 | 63.74 |
| text-only + n10/p0.5 | 180,224 | 23,729 | 22,882 | 478 | **847** | 56.58 |
| text-only + n10/p0.5 | 196,608 | 24,161 | 23,459 | 638 | 415 | 51.88 |
| text-only + n10/p0.5 | 212,992 | 24,296 | 24,163 | 744 | 280 | 49.20 |

- **A deeper draft costs ~771 MiB of dedicated VRAM** (23,189 vs 22,418 at the
  same context). The fully-resident ceiling is a property of the WHOLE
  configuration, not of `-c` alone.
- **Recipe 1 at 163,840 has only 537 MiB of slack**, not the 996 the sweep
  implied. Fenced as a bare-desktop configuration; the desktop-safe default is
  demoted to `-c 131072`.
- **Text-only ceiling with the coding drafter: 180,224** (847 MiB slack), not
  the 196,608 the projector arithmetic suggested. 196,608 leaves 415 MiB and
  212,992 leaves 280 - and decode already sags across those three (56.58 ->
  51.88 -> 49.20) on a *short* probe, which is the overcommitment penalty
  starting to show. Recipe 3 was changed from 196,608 to 180,224 before the
  power pass measured it.

This is exactly what the "verify your promoted defaults" step is for: two of
the four shipped recipes were wrong before it ran.

### 01:42 - Phase 10b: per-recipe power and the promoted-config check

Fresh server per recipe, 1 Hz power log around one identical 700-token novel-JS
probe (temp 0 / top_k 1), integrated over the generation window only.

| recipe | -c | vision | drafter | board | slack | decode t/s | mean W | peak W | Wh/answer |
|---|---|---|---|---|---|---|---|---|---|
| R1 bare-desktop | 163,840 | yes | n10/p0.5 | 23,565 | 1,011 | 79.26 | 277.0 | 340.0 | 0.730 |
| **R2 default** | 131,072 | yes | n10/p0.5 | 22,150 | **2,426** | 77.05 | 278.0 | 338.1 | 0.746 |
| R3 text-only | 196,608* | no | n10/p0.5 | 23,813 | 763 | 80.02 | 283.0 | 336.2 | 0.733 |
| R4 prose | 131,072 | yes | n4/p0.75 | 21,241 | **3,335** | 72.44 | 279.0 | 336.5 | 0.799 |
| R1b reference | 163,840 | yes | n4/p0.75 | 22,641 | 1,935 | 70.46 | 286.7 | 335.7 | 0.845 |

*R3's power arm ran at 196,608; the shipped window is 180,224 (Phase 4d:
board 23,729, 847 MiB slack). Power is flat across configurations so the
substitution is immaterial.

- **Idle, no server: 34.6 W** (n=15). **Idle with the model loaded: 30.7-31.1 W**
  across all five. A loaded server costs essentially nothing until asked.
- **The 10-second windows understate sustained load.** Mean 277-287 W here
  because the first samples catch the ramp from 31 W; the multi-minute effort
  runs sustained 344 W. The report says so and points planning at the Phase 10
  Wh/1k-token figures instead.
- **Reproducibility check that passed:** R1b's dedicated VRAM at `-c 163840`
  with n4/p0.75 read **22,418 MiB**, identical to the Phase 4 sweep's reading
  of the same configuration 70 minutes earlier.
- **Desktop variance is real and large.** The same Recipe 1 configuration read
  board 23,565 MiB here and 24,039 MiB in Phase 4d - a 474 MiB spread caused by
  nothing but what else was on screen. That is 10,900 tokens of window, and it
  is why the default recipe was demoted to `-c 131072`.

### 01:36 - Phase 3d: the acceptance demonstration, third attempt

Thinking disabled (`chat_template_kwargs {"enable_thinking": false}`) so every
timed token is a token a reader keeps. Same four contents, three configs,
fresh server each, `-c 32768`, temp 0 / top_k 1, up to 700 predicted tokens.

| content generated | no spec | n10/p0.5 | acc | n4/p0.75 | acc | best vs floor |
|---|---|---|---|---|---|---|
| copy a supplied JS snippet | 41.46 | **148.66** | 99.0 % | 97.04 | 100.0 % | **3.59x** |
| novel JavaScript class | 42.17 | **95.35** | 67.4 % | 84.47 | 92.3 % | 2.26x |
| novel Python module + tests | 41.84 | **79.13** | 59.3 % | 75.12 | 91.9 % | 1.89x |
| English prose explainer | 41.55 | 43.80 | 43.5 % | **48.35** | 79.9 % | 1.16x |

**This is the campaign's headline speed result.** Same card, same file, same
flags; a **3.4x spread** in decode produced purely by what is being written.

- **New ceiling: 148.66 t/s** (copying, 99.0 % acceptance).
- **New floor: 41.46-42.17 t/s.** Across four contents AND both token streams
  the no-spec numbers span 3 % (41.46 to 42.81). Content is not a variable
  without speculation.
- **Answer tokens are FASTER than reasoning tokens** for code (95.35 vs 88.77
  on JS; 79.13 vs 63.09 on Python) - code is more predictable than free-form
  reasoning prose.
- **On prose, speculation is nearly worthless**: 43.80 vs a 41.55 floor =
  1.16x. The drafter's 1.2 GiB is hard to justify on a pure writing workload.
- **Acceptance rate still does not rank configs.** On the copying row
  n4/p0.75 accepts a *perfect* 100.0 % (424/424) and runs 97.0 t/s, while
  n10/p0.5 accepts 99.0 % and runs 148.7. Accepted per target pass: 3.96 vs
  **10.54**. A perfect acceptance rate on a shallow draft is a rate limit.
- **Both shipped recipes survive re-measurement**: n10/p0.5 wins every code row
  (+5 to +53 %), n4/p0.75 wins prose (+10 %). Chosen on reasoning tokens,
  confirmed on answer tokens.

### 01:29 - Phase 8 (reduced): vision, after one failed attempt

**First attempt failed, and the failure is worth recording.** The PowerShell
harness posted the image request and got nothing back; the *server log showed
no task at all*, so the request never left the client. Cause: Windows
PowerShell 5.1's `Invoke-RestMethod` cannot post the ~261 KB body a 1440p PNG
data-URI produces. The identical request from Python succeeds in 3.8 s. The
vision phase was rewritten as `work/phase8b.py`.

Conditions: IQ4_XS + BF16 projector, `-c 65536`, `-ngl 99`, q8_0 KV, MTP
n4/p0.75, temp 0 / top_k 1, thinking left at the model default. Image cost =
`prompt_tokens(text+image) - prompt_tokens(text)`; the text-only baseline
measured 75 tokens. Screenshots are Chrome headless captures of
`data/effort-low.html` - the model's own generated page.

| arm | image | image tokens | predicted by arithmetic | prefill t/s | prefill s |
|---|---|---|---|---|---|
| default | 1280x720 | **922** | 920 | 573.8 | 1.66 |
| default | 2560x1440 | **3,602** | 3,600 | 613.2 | 5.93 |

**The 32 x 32-pixel arithmetic is confirmed to within 2 tokens.** patch 16 x
`spatial_merge_size` 2 = one token per 32 x 32 px block; 2560/32 x 1440/32 =
3,600, measured 3,602 (the extra pair is the vision start/end sentinels).
No smart-resize happened at these resolutions with default flags.

A separate direct check against a server started with `--image-max-tokens
1024` returned 1,045 prompt tokens for the same 1440p image against a 35-token
baseline = **1,010 image tokens**, so the cap knob works and costs ~3.6x fewer
tokens.

**Unplanned bonus - the model demonstrably sees the pixels.** Asked to name
three distinct things, it returned "a green sea turtle, a cluster of purple
jellyfish, and a purple starfish resting on the rocks" (720p) and "purple
jellyfish, a green sea turtle, and tall green stalks of seaweed rising from the
sand" (1440p). Every one of those is actually in the rendered frame. That is
not the full critique loop (which asks for a judgement, not a description) and
the report does not claim it is - but it does establish that the transport and
the perception work on this machine.

### 00:54 - Phase 3c: the acceptance demonstration falsified my own framing

Phase 3c re-ran the acceptance cases at n10/p0.5 **and saved the generated
text**. Two of the four returned an EMPTY `content` field with 700 completion
tokens and `finish_reason=length`:

| case | t/s | acceptance | answer text |
|---|---|---|---|
| novel code (JS red-black tree) | 88.79 | 59.2 % | **empty - 700 tokens of thinking** |
| verbatim copy of a JS snippet | 59.29 | 54.7 % | **empty - 700 tokens of thinking** |
| verbatim copy of an English paragraph | **102.55** | 77.1 % | present, copied correctly |
| count 1 to 200 | **133.78** | 85.5 % | present, correct |

**Every speed probe in Phases 2-5 ran at the model's DEFAULT reasoning effort
(`xhigh`) with a 700-token cap, so the tokens being timed were reasoning
tokens, not deliverables.** The content labels described the *task*, not the
token stream. That does not invalidate the decode measurements - the tokens are
real and the server timed them correctly - but it does change what they mean,
and it explains the "verbatim copying is slower" anomaly completely: the model
was *thinking about* the copy task, not copying.

It also moves the ceiling. Answer tokens on genuinely predictable content run
**133.78 t/s** (counting) and **102.55 t/s** (copying prose) - well above the
89.1 t/s that reasoning-token probes reported as the maximum.

Added **Phase 3d** as the control: same four contents, same two drafting
configs plus no-spec, with `--chat-template-kwargs {"enable_thinking":false}`
so the timed tokens are the actual output. Queued ahead of Phase 6.

### 00:54 - Phase 7 (reduced) + Phase 10: effort cost and power

Conditions, identical for all three levels: IQ4_XS, `-c 131072`, `-ngl 99`,
q8_0 KV, MTP n4/p0.75, **no projector**, `--reasoning-preserve`,
`--chat-template-kwargs {"reasoning_effort":"<level>"}` at load time, the
aquarium task from `templates/effort-task-example.md`, the model card's
recommended thinking sampling (temp 1.0 / top_p 0.95 / top_k 20), 65,536-token
cap so no level could truncate. **n=1 per level.** A 1 Hz `power.draw` log ran
across the whole phase with per-run start/end timestamps recorded.

| level | prompt_n | completion_n | decode t/s | acceptance | wall | finish | answer bytes |
|---|---|---|---|---|---|---|---|
| low | 1,689 | 17,321 | 81.21 | 91.0 % | 3 m 35 s | stop | 36,680 |
| medium | 1,659 | 24,973 | 66.75 | 88.2 % | 6 m 16 s | stop | 40,838 |
| **xhigh** | 1,701 | **65,536 = the cap** | 51.34 | 83.6 % | 21 m 18 s | **length** | 8,557 (incomplete) |

**xhigh TRUNCATED.** 160,919 characters of thinking (~40k tokens), then it
started the file and hit the 65,536-token cap 8,557 characters in;
`finish_reason=length` and no extractable `<html>` document. This is
METHODOLOGY rule 16 measured directly: a level whose appetite exceeds the
budget does not degrade, it truncates. Rule 7 says raise the cap and re-run
that arm only - queued as **Phase 7b** at a 120,000-token cap (the largest that
fits inside `-c 131072` alongside the 1,701-token prompt), scheduled as the
LAST GPU job so nothing else is at risk if it overruns.

`prompt_n` across the three levels is 1,689 / 1,659 / 1,701 - `low` and `xhigh`
inject a reasoning-instruction system line, `medium` injects none, exactly as
the chat template says. The knob is real.

**Phase 10 - energy per effort level** (1 Hz `power.draw`, integrated over each
generation window only; gross draw, idle NOT subtracted):

| level | samples | mean W | peak W | Wh per answer | Wh per 1k tokens |
|---|---|---|---|---|---|
| low | 212 | 344.1 | 349.8 | **20.55** | 1.19 |
| medium | 372 | 344.3 | 349.6 | **35.96** | 1.44 |
| xhigh | 1,264 | 338.6 | 349.4 | **120.21** | 1.83 |

- **xhigh burned 120 Wh and returned no usable file** - 5.8x low's energy for
  zero deliverable.
- Wh per 1k tokens *rises* with effort (1.19 -> 1.44 -> 1.83) because the board
  draws a flat ~344 W whatever it generates while decode falls 81 -> 51 t/s.
  Slower tokens are more expensive tokens.
- Baseline: board idle with no server loaded measured **33.2 W** at campaign
  start. The first 10 samples of this phase's log average 58.0 W because the
  GPU was still cooling from Phase 3c - so the campaign uses the 33.2 W cold
  reading as the idle figure and says the load numbers are gross.

Decode falls with effort (81.21 -> 66.75 t/s) because the token *mix* changes:
low spent 4,827 characters thinking and the rest emitting HTML (highly
predictable, 91.0 % acceptance); medium spent 20,906 characters thinking
(less predictable, 88.2 % acceptance overall).

**Judging (static + rendered, n=1, NOT blind - I could see the labels).**
Each answer was checked mechanically against the task's numbered requirements
(`work/judge.py`), then rendered headless in Chrome at 1280x720 and looked at.

- **low** - 20 CONFIG keys, all 7 mandated ones present, and *all 20 are
  actually referenced in the code*. 17 draw functions. No external references.
  rAF + delta time + resize listener; no `devicePixelRatio` handling.
  **Renders correctly and the scene is well distributed.**
- **medium** - 13 CONFIG keys (all 7 mandated present, better commented), 21
  draw functions including creative extras (treasure chest, clownfish,
  caustics, motes), `devicePixelRatio` handled, static scenery stored in
  *normalised* coordinates so it survives a resize - architecturally the
  better file. **But it ships a real bug.**

**The medium bug, confirmed in code and in the render.** `let W = 0, H = 0,
FLOOR = 0;` sits at line 42; `resize()` is not called until line 1270, after
every creature array has been built. So every mobile creature is spawned with
`rand(W * 0.1, W * 0.9)` = `rand(0, 0)` = **0**. All fish, jellyfish, crabs,
lobster, starfish, seahorse and the turtle spawn stacked in the top-left
corner, and the right 90 % of the tank holds only static scenery (which is
fine, because scenery uses normalised coordinates). This directly violates the
task's "Creatures should not cluster in one area. Distribute them across the
tank."

`low` does not have the bug: it calls `resize()` at line 48, *before* the first
spawn at line 79.

Per METHODOLOGY rule 8, a categorical difference (works vs. broken) is real at
n=1 in a way a point score is not - so the report states the bug and does
**not** crown a winner.

Notes as they land:
- **low did not truncate and did not fail.** 17.3k tokens, of which only ~4.8k
  characters were thinking; the rest is the deliverable. `finish_reason=stop`.
- Decode 81.21 t/s on **answer tokens** with 91.0 % acceptance - HTML/JS is
  highly predictable content, and this is the most realistic "real work" speed
  number in the campaign.
- The rendered page works (screenshotted headless): tropical fish, angelfish,
  a school, jellyfish, seahorse, turtle, crabs, lobster, starfish, seaweed,
  rocks, coral, shells, caustic rays, sandy floor, motes.

### 01:45 - Phase 6 (reduced): perplexity

`llama-perplexity -m <IQ4_XS> -f wiki.test.raw -ngl 99 -c 8192 -fa on
--load-mode mmap`, wikitext-2-raw **test** split, **36 chunks x 8,192 =
294,912 token positions**, 8.96 s per pass, 298.3 s wall for the q8_0 arm.

| KV cache | perplexity | vs fp16 | wall |
|---|---|---|---|
| fp16 | **6.5956 +/- 0.04453** | - | ~295 s |
| q8_0 (what the recipes ship) | **6.6160 +/- 0.04483** | **+0.31 %** | 298.3 s |

**The KV-quant claim is verified.** Halving the cache costs 0.31 % perplexity
over 294,912 scored token positions - that is the entire quality price of
nearly doubling the context window, and it is why every recipe ships q8_0.

Single-quant campaign: the absolute value is a health check, not a ranking.
The fp16-vs-q8_0 comparison IS a ranking, but of cache dtypes on one file, not
of quants.

### 01:55 - Phase 7b: the xhigh re-run at a raised cap (last GPU job)

METHODOLOGY rule 7 in action. `-c 131072`, cap raised 65,536 -> **120,000**
(the largest that fits alongside the 1,701-token prompt), everything else
identical to the Phase 7 xhigh arm. Scheduled last on purpose so an overrun
could not cost the campaign anything already measured.

**It completed, and it changed the finding.**

| xhigh run | cap | tokens used | decode t/s | wall | finish | Wh | deliverable |
|---|---|---|---|---|---|---|---|
| first | 65,536 | 65,536 | 51.34 | 21 m 18 s | **length** | 120.2 | none |
| re-run | 120,000 | **61,476** | 55.76 | 18 m 24 s | **stop** | 104.9 | complete, best of the three |

The second sample wanted **fewer** tokens than the cap the first sample hit -
61,476 against 65,536. Thinking was 114,081 characters this time versus
160,919. At temperature 1.0 **xhigh's appetite straddles 65,536**: the effort
ceiling is a distribution, not a number, and a cap near the median truncates a
good fraction of runs while looking generous.

Judged: 25 draw functions, 18 CONFIG constants, `devicePixelRatio` capped, no
external references, 1,180 lines. Rendered headless it distributes creatures
across the full width, adds a clownfish in the anemone, a treasure chest and a
title card, and has none of medium's initialisation bug. **Best of the three -
at n=1, by a judge who could see the label.**

### 02:15 - Phase 5b: depth for the configuration that actually ships

The reader-experience review found that no table crossed depth x shipped
drafter x answer tokens - the only one a Recipe 2 user needs. Measured:
`-c 131072`, projector loaded, MTP n10/p0.5, `enable_thinking:false`, temp 0,
400 predicted tokens per row.

| depth | prefill t/s | prefill wall | decode t/s | acceptance |
|---|---|---|---|---|
| 1,488 | 964 | 1.5 s | **94.49** | 60.0 % |
| 29,841 | 1,084 | 27.5 s | **80.96** | 60.9 % |
| 90,887 | 814 | 111.7 s | **70.09** | 64.7 % |

**Decode at 91k depth is 70.09 t/s, not the 30.61 the reasoning-token probe
suggested.** Same 26 % decline shape, roughly twice the level. Acceptance rises
with depth again (60.0 -> 64.7 %) - a second independent confirmation that
depth and acceptance are unrelated axes. The spec strip now carries 70.1.

**Operator error, recorded.** At 02:13 I started a second llama-server (CPU-only,
`-ngl 0`) to try to reproduce the port-1234 bind failure for the log. LM Studio
had released the port by then, so it bound and ran for 54 s. The xhigh re-run
had already finished at 02:14:11 so nothing was contaminated - but at 02:14:47 I
then killed what I believed was my stray process and it was **Phase 5b's
server**, which had started 20 s earlier. Phase 5b was re-run clean from its
resume point. Two rules broken in one command: one GPU job at a time, and never
kill by assumption. The bind-failure row in the report is now labelled an
observation rather than a saved artefact, because it could not be reproduced.


### 01:58 - Review passes and the corrections they forced

Three fresh-subagent passes ran against the draft: structural, reader-experience
and numeric.

**Structural: clean on all six checks** (anchors/TOC, tag balance, encoding,
self-containment, duplicate ids, table column counts). Its one nit - captions
placed after `</tbody>` rather than as the table's first child - was fixed.

**Reader-experience: eleven must-fixes, all real.** The pattern was one thing:
the campaign revised itself three times (reasoning-vs-answer tokens, drafting
flags, VRAM after the drafter change) and the revisions were written up where
they were discovered and never propagated backwards. Specifically fixed:

1. Three places still said "no level truncated" on the same screen as the table
   showing xhigh at `finish_reason=length`.
2. The 24,039 MiB re-reading had two mutually exclusive explanations 800 lines
   apart (deeper drafter / busier desktop). **Both were true and they are
   separable** - see the reconciliation below.
3. The section-02 budget table used constants from the n4/p0.75 sweep while
   every recipe ships n10/p0.5, and under-predicted slack in the dangerous
   direction. Rebuilt.
4. Section 12 still quoted the pre-revision "50-89 t/s" reasoning-token band.
5. `2.05x` for the drafter appeared in a hero math grid with no conditions at
   all, and is a reasoning-token figure; answer tokens give 2.26x on code and
   1.16x on prose.
6. Recipe 4's justification in the HTML and one comment in the shipped `.bat`
   still quoted the retracted reasoning-token pair, while another comment twelve
   lines away quoted the corrected one.
7. Two dead cross-references to a "section 06.5" that does not exist.
8. The drafter's memory cost was stated as 800 MiB, 1.2 GiB and 1,838 MiB in
   three places.
9. **No llama.cpp build ID anywhere** - every finding here is build-specific.
   Now recorded: **version 0.1.2-dev, build 10502, commit 0adcc3bb5**, Clang
   20.1.8, Windows x86_64, binary dated 2026-08-19.
10. Over-claims trimmed: "there is no card on which `-ngl 99` is wrong"
    (contradicted by this report's own 12 GB row); the hero's "nothing here is
    quoted from a vendor slide" (section 07's bandwidths are, and are cited);
    "the perception is real rather than hallucinated" in section 11 (the model
    was shown a page *it wrote*, and no control run withheld the image - it
    fails this report's own stated test).

**The VRAM reconciliation, which turned out to be the campaign's cleanest
result.** Separating llama-server's own dedicated usage from the desktop's share
of the board resolves every apparent contradiction:

| quantity | measured |
|---|---|
| per window token, drafter on | 45,056 B |
| per window token, drafter off | 39,936 B |
| weights + buffers, text-only, no drafter | 13,232 MiB |
| the vision projector | **1,138 MiB** |
| turning the drafter on | **1,008 MiB** fixed |
| n-max 10 instead of n-max 4 | **898 MiB** |
| the desktop's own share, across the night | **223 - 1,179 MiB** |

Two constants per configuration reproduce **ten independent server loads**:
eight to the megabyte, worst miss 30 MiB. The 22,641 / 23,565 / 23,580 / 24,039
board spread for "the same" configuration is 898 MiB of drafter plus ~950 MiB of
desktop, and llama-server's own figure moved by at most 127 MiB. The report now
budgets on the server figure and states the desktop range separately.

**Numeric pass:** run concurrently; findings folded in above.

**One gap the review found that could still be measured** - no table crossed
depth x shipped drafter x answer tokens, which is the one a Recipe 2 user
actually needs. Queued as Phase 5b behind the xhigh re-run.

## How long each phase took

| phase | window | wall |
|---|---|---|
| 0 + 2 foundation, KV arithmetic, -ngl trap | 00:19 - 00:23 | 4 min (incl. one false start on the bound port) |
| 3 MTP sweep + acceptance demo | 00:24 - 00:28 | 4 min |
| 3b content sweep (anti-overfit) | 00:28 - 00:31 | 3 min |
| 4 context ceiling sweep | 00:31 - 00:34 | 3 min |
| 5 depth series | 00:34 - 00:39 | 5 min |
| 4b MTP memory isolation | 00:39 - 00:40 | 1 min |
| 4c collapse point (added) | 00:40 - 00:54 | 14 min |
| 3c acceptance verification (added) | 00:54 - 00:55 | 1 min |
| 7 + 10 effort x3 with power | 00:55 - 01:27 | 32 min |
| 8 vision, first attempt (failed) | 01:27 - 01:35 | 8 min, wasted |
| 8b vision, Python rewrite | 01:35 - 01:36 | 1 min |
| 3d answer-token control (added) | 01:36 - 01:40 | 4 min |
| 4d promoted-recipe verification (added) | 01:40 - 01:42 | 2 min |
| 10b per-recipe power | 01:42 - 01:45 | 3 min |
| 6 perplexity x2 | 01:45 - 01:55 | 10 min |
| 7b xhigh re-run at 120k cap | 01:55 - 02:14 | 19 min |
| 5b depth for the shipped recipe | 02:15 - 02:18 | 3 min (after one self-inflicted restart) |
| **total GPU time** | **00:19 - 02:18** | **1 h 59 min** |

Report writing and the three review passes ran concurrently with the GPU work
from ~00:45 onward.

---

## The canonical list

Every number the report may use. Conditions are attached; anything not on this
list is not measured.

### Machine and files
| item | value |
|---|---|
| GPU | RTX 3090, 24,576 MiB, driver 596.36 |
| CPU / RAM | i5-13600KF 14C/20T; 31.8 GiB as 2 x 16 GiB DDR4-3200, dual channel |
| OS | Windows 11 Pro 26200 |
| idle board VRAM (desktop up, no server) | **1,179 MiB** |
| idle GPU power (no server) | **33.2 W** |
| model file | Qwen3.8-27B-UD-IQ4_XS.gguf, **14,252,845,984 B** (13.27 GiB) |
| projector | mmproj-Qwen3.8-27B-BF16.gguf, **931,145,856 B** (0.867 GiB) |
| server load time, mmap, warm page cache | 6.0 - 10.6 s (~30 restarts) |

### Architecture (from config.json, fetched live)
| item | value |
|---|---|
| layers | 64 total; **16 full attention**, 48 Gated-DeltaNet |
| KV heads / head dim | 4 / 256 |
| KV bytes/token, fp16 (arithmetic) | 65,536 |
| KV bytes/token, q8_0 nominal (arithmetic) | 32,768; **34,816** with block scales |
| linear-layer fixed state (arithmetic) | **~151 MiB**, context-independent |
| MTP head weight bytes (from server log) | **350,988,288 B = 334.7 MiB** |
| native context | 262,144 |
| effort levels | low / medium / xhigh (default **xhigh**) |
| vision token granularity | 1 token per 32 x 32 px (patch 16, merge 2) |

### Speed - the floor and the -ngl trap (`-c 32768`, spec off, temp 0, 700 tok)
| arm | decode t/s | board MiB | srv dedicated | srv shared |
|---|---|---|---|---|
| `-ngl 99`, q8_0 KV | **42.31** | 15,661 | 14,480 | 132 |
| `-ngl 99`, f16 KV | **43.19** | 16,428 | 15,354 | 132 |
| `-ngl 64`, q8_0 KV | **29.84** | 15,256 | 14,182 | 142 |
| off-by-one cost | **-29.5 %** (1.42x) | | | |
| bandwidth check | 936 GB/s / 14.25 GB = 65.7 t/s; measured **0.649** of raw | | | |

### Speed - MTP sweep (`-c 32768`, temp 0, 700 tok, novel-JS task, reasoning tokens)
| config | t/s | acceptance | accepted/pass | drafted/pass |
|---|---|---|---|---|
| none | 42.61 | - | - | - |
| n3/p0 | 81.97 | 87.1 % | 2.59 | 2.97 |
| n4/p0.75 | 80.99 | 89.9 % | 2.65 | 2.94 |
| n6/p0.5 | 80.18 | 69.0 % | 3.61 | 5.22 |
| n10/p0 | 87.31 | 46.8 % | 4.60 | 9.83 |
| **n10/p0.5** | **87.39** | 59.2 % | 4.56 | 7.69 |
| n10/p0.75 | 80.32 | 72.3 % | 3.32 | 4.59 |
| n16/p0.5 | 80.32 | 47.1 % | 4.88 | 10.36 |

### Speed - content sweep (`-c 32768`, temp 0, 700 tok)
| content | none | n10/p0.5 | acc | n4/p0.75 | acc |
|---|---|---|---|---|---|
| novel JS task | 42.81 | 88.77 | 59.2 % | 78.71 | 89.9 % |
| novel Python task | 42.77 | 63.09 | 56.5 % | 56.36 | 87.4 % |
| prose task | 42.66 | 48.42 | 43.2 % | 51.68 | 79.9 % |
| verbatim copy task | 42.47 | 56.44 | 54.9 % | 79.64 | 96.3 % |

### Speed - answer tokens vs reasoning tokens (Phase 3c, n10/p0.5)
| probe | t/s | acceptance | content field |
|---|---|---|---|
| novel JS | 88.79 | 59.2 % | **empty (all reasoning)** |
| copy JS snippet | 59.29 | 54.7 % | **empty (all reasoning)** |
| copy English paragraph | **102.55** | 77.1 % | present |
| count 1-200 | **133.78** | 85.5 % | present |

### Memory - ceiling sweep (mmproj ON, MTP n4/p0.75, q8_0 KV, shallow probe)
| -c | board MiB | dedicated | shared | decode t/s |
|---|---|---|---|---|
| 32,768 | 17,978 | 16,816 | 190 | 63.63 |
| 65,536 | 19,356 | 18,194 | 254 | 64.06 |
| 98,304 | 20,764 | 19,602 | 318 | 63.80 |
| 131,072 | 22,172 | 21,010 | 382 | 63.84 |
| **163,840** | 23,580 | 22,418 | 446 | 63.74 |
| 196,608 | 24,132 | 23,637 | 700 | 59.72 |
| 229,376 | 24,145 | 23,716 | 2,096 | 60.44 |
| 262,144 | 24,162 | 23,784 | 3,502 | 59.06 |
| 262,144 no mmproj | 24,162 | 23,782 | 2,364 | 58.85 |

- per-token window cost, MTP on: **45,056 B** (1,408 MiB per 32,768 tokens)
- per-token window cost, MTP off: **39,936 B** (Phase 4b: 15,618 -> 20,610 MiB)
- MTP per-token cost: **5,120 B/token** (+11.4 %); MTP fixed cost ~1,198 MiB at 32k
- projector cost: **1,138 MiB** = ~26,500 tokens of window (measured twice)
- **fully-resident ceiling: 163,840** (996 MiB slack) - **shallow-safe: 262,144**

### Memory - the collapse (Phase 4c, identical prompts, projector on)
| depth | -c 131072 | -c 262144 | penalty | prefill 131072 | prefill 262144 |
|---|---|---|---|---|---|
| 1,530 | 53.48 | 42.92 | 1.25x | 914 | 755 |
| 29,837 | 47.30 | 18.64 | 2.54x | 1,085 | 408 |
| 90,885 | 30.61 | **8.02** | **3.82x** | 819 | **183** |

### Depth (Phase 5, `-c 131072`, no projector, n4/p0.75, 300 tok)
| depth | prefill t/s | prefill s | decode t/s | acceptance | naive tok/wall |
|---|---|---|---|---|---|
| 1,533 | 1,082 | 1.4 | 51.15 | 79.6 % | 41.3 |
| 10,658 | 1,198 | 8.9 | 50.32 | 88.7 % | 20.0 |
| 28,423 | 1,097 | 25.9 | 47.07 | 92.3 % | 9.2 |
| 56,840 | 951 | 59.8 | 41.07 | 91.1 % | 4.4 |
| 92,679 | 816 | 113.6 | 35.81 | 85.9 % | 2.4 |

### Perplexity (Phase 6, wikitext-2-raw test split, 294,912 token positions, -c 8192, -fa on)
| KV cache | PPL | vs fp16 |
|---|---|---|
| fp16 | **6.5956 +/- 0.04453** | - |
| q8_0 | **6.6160 +/- 0.04483** | +0.31 % |

### Effort (Phase 7, n=1 per level, `-c 131072`, no projector, n4/p0.75, temp 1.0/top_p 0.95/top_k 20, 65,536 cap)
| level | prompt_n | completion_n | decode t/s | acceptance | wall s | finish |
|---|---|---|---|---|---|---|
| low | 1,689 | 17,321 | 81.21 | 91.0 % | 215.0 | stop |
| medium | 1,659 | 24,973 | 66.75 | 88.2 % | 375.7 | stop |
| xhigh | 1,701 | 65,536 (cap) | 51.34 | 83.6 % | 1,278.3 | **length** |
| xhigh, 120k cap (Phase 7b) | 1,701 | **61,476** | 55.76 | 87.6 % | 1,104.5 | **stop** |

### Depth, shipped recipe, ANSWER tokens (Phase 5b, -c 131072, projector on, n10/p0.5)
| depth | prefill t/s | decode t/s | acceptance |
|---|---|---|---|
| 1,488 | 964 | **94.49** | 60.0 % |
| 29,841 | 1,084 | **80.96** | 60.9 % |
| 90,887 | 814 | **70.09** | 64.7 % |

### VRAM model constants (reproduce 17 fully-resident loads, worst residual 127 MiB)
| quantity | value |
|---|---|
| per window token, drafter on | 45,056 B |
| per window token, drafter off | 39,936 B |
| weights + buffers, text-only, no drafter | 13,232 MiB |
| the vision projector | 1,138 MiB |
| turning the drafter on | 1,008 MiB fixed |
| n-max 10 instead of n-max 4 | 898 MiB |
| desktop's own share of the board, 26 loads | 133 - 1,181 MiB |

### GPU bandwidths used in the section 07 derivations (all CITED, section 14)
| card | GB/s | | card | GB/s |
|---|---|---|---|---|
| RTX 3090 | 936 | | RTX A6000 | 768 |
| RTX 4090 | 1008 | | Apple M4 Max (16C/40C) | 546 |
| RTX 5090 | 1792 | | Apple M4 Pro | 273 |
| RTX 6000 Ada | 960 | | DDR5-6000 dual channel | 96.0 |
| RTX 4060 Ti 16 GB | 288 | | DDR4-3200 dual channel | 51.2 |
| RTX 3060 12 GB | 360 | | (derived decode = GB/s / 14.25 x 0.649) | |

### Energy (Phase 10, gross draw, idle NOT subtracted)
| level | mean W | peak W | Wh/answer | Wh/1k tok |
|---|---|---|---|---|
| low | 344.1 | 349.8 | 20.55 | 1.187 |
| medium | 344.3 | 349.6 | 35.96 | 1.440 |
| xhigh | 338.6 | 349.4 | 120.21 | 1.834 |

Idle, no server: **33.2 W** at campaign start, **34.6 W** (n=15) in Phase 10b.
Idle with model loaded, answering nothing: **30.7-31.1 W**.

### Speed - ANSWER tokens (Phase 3d, thinking disabled, `-c 32768`, temp 0)
| content | none | n10/p0.5 | acc | n4/p0.75 | acc |
|---|---|---|---|---|---|
| copy a supplied JS snippet | 41.46 | **148.66** | 99.0 % | 97.04 | 100.0 % |
| novel JavaScript class | 42.17 | **95.35** | 67.4 % | 84.47 | 92.3 % |
| novel Python module + tests | 41.84 | **79.13** | 59.3 % | 75.12 | 91.9 % |
| English prose explainer | 41.55 | 43.80 | 43.5 % | **48.35** | 79.9 % |

### Vision (Phase 8b, text-only baseline 75 tokens)
| arm | image | image tokens | arithmetic | prefill t/s | prefill s |
|---|---|---|---|---|---|
| default | 1280x720 | 922 | 920 | 573.8 | 1.66 |
| default | 2560x1440 | **3,602** | 3,600 | 613.2 | 5.93 |
| `--image-min-tokens 1024` | 1280x720 | 1,077 | - | 681.3 | 1.63 |
| `--image-min-tokens 1024` | 2560x1440 | 3,602 | 3,600 | 615.9 | 5.90 |
| `--image-max-tokens 1024` | 2560x1440 | 1,010 | - | 566.4 | 1.85 |

### Recipes verified (Phase 10b + 4d)
| recipe | -c | vision | drafter | board MiB | slack | decode t/s | peak W | Wh/answer |
|---|---|---|---|---|---|---|---|---|
| R1 bare-desktop | 163,840 | yes | n10/p0.5 | 23,565 | 1,011 | 79.26 | 340.0 | 0.730 |
| **R2 default** | 131,072 | yes | n10/p0.5 | 22,150 | 2,426 | 77.05 | 338.1 | 0.746 |
| R3 text-only | 180,224 | no | n10/p0.5 | 23,729 | 847 | 80.02* | 336.2* | 0.733* |
| R4 prose | 131,072 | yes | n4/p0.75 | 21,241 | 3,335 | 72.44 | 336.5 | 0.799 |
| R1b reference | 163,840 | yes | n4/p0.75 | 22,641 | 1,935 | 70.46 | 335.7 | 0.845 |

*measured at 196,608 before the window was lowered to 180,224.

### Text-only ceiling with the coding drafter (Phase 4d)
| -c | board MiB | dedicated | shared | slack | decode t/s |
|---|---|---|---|---|---|
| **180,224** | 23,729 | 22,882 | 478 | **847** | 56.58 |
| 196,608 | 24,161 | 23,459 | 638 | 415 | 51.88 |
| 212,992 | 24,296 | 24,163 | 744 | 280 | 49.20 |

## 2026-08-23 - Agentic bucket (rule 22): gate ran, sweep skipped, anchor cited
Pier/DeepSWE pipeline built and validated end-to-end on this machine (WSL2
Ubuntu-24.04, docker 29.7.2; full log agentic/setup-log.md). One real task:
9m36s wall, 22 LLM calls, 1,014,115 prompt / 21,736 completion tokens, F2P
0/96, P2P 561/561 - plumbing PASS, task fail. Traps recorded in rule 22:
--ak model_class=null, server on port 80 (squid Safe_ports), WSL host
192.168.128.1, -c 131072 minimum (65,536 overflowed after 22 calls).
Projection for 10 tasks x 3 efforts, runs completing naturally, -n 1: ~8.5 h
> ~4 h gate -> SKIPPED. Published anchor cited in report section 12: 42.2 on
the DeepSWE 1.1 leaderboard (base model, full precision). Key measured fact:
agentic wall time is prompt-processing-bound on this harness.

## 2026-08-23 - Follow-up probes (cooled protocol; full log work/followup-measurements.md)
M1 MTP matched-pair re-sweep (-c 32768, thinking off, temp 0, code probe):
n10/p0.5 wins BOTH quants - IQ4_XS 93.86 t/s (2.18x, accept 61.4%), Q4_K_M
81.71 (2.04x, 60.0%); shipped n4/p0.75 = 83.50/69.82 (11-15% off peak).
Acceptance within 1.6 pts on six of seven configs across quants (one
pair, n6/p0.5, differs by 3.7) -> property of the MTP head, not the
quant. (CORRECTED from "at every config" 2026-08-23.) The campaign-era 81.7 reproduces exactly: mislabeled
token regime, not a phantom.
M2 Projector at depth (90,862 tok, ABBA, byte-identical prompts): decode
delta 0.04% (drafter off) / 0.09% (on) -> projector is decode-free; cost is
1,138 MiB VRAM only. The 30.61 outlier = clock-ramp artifact: probe fired
right after a ~105 s prefill reads 18.3-26.6 t/s (45% swing, clocks at
900-990 MHz vs 1,455 settled); steady-state temp 57->82 C moves decode 1%.
M3 q4_0 KV PPL 6.6413 +/-0.045 = +0.693% vs f16 (q8_0 +0.309%) -
superlinear in bits; 1-SE overlap -> direction consistent, not resolved.
M4 Repetition audit: 10/10 long greedy transcripts clean.
NEW MECHANISM: mean draft length, not acceptance, predicts speculative
throughput - identical acceptance (0.895/0.907), draft len 2.99 vs 4.31 ->
36.62 vs 62.02 t/s (thinking on vs off, same server, same 91k prompt,
1.69x). Corrected depth ladder (answer regime, n4/p0.75): 86.30 @ 1,458 ->
80.20 @ 28,388 -> 64.76 @ 90,854. xhigh real speed at 91k depth: ~37-39
t/s; n10/p0.5 recovers only 5.6% there vs 12% on shallow code.

## 2026-08-23 - Rule-21 live effort sweep (suite 1cdf54f8eb9d3f8f, n=25, greedy, seed 42, no MTP)
Composite Mean over 5 scored sets (ALPACA/MT-Bench unscored - no independent
judge; transcripts kept):
| cap | low | medium | xhigh | truncations |
|---|---|---|---|---|
| 16,384 | 81.3 | 80.5 | 77.3 | 1 / 2 / 9 |
| 32,768 (rule-7 rerun, affected arms only) | 82.1 | 80.5 | 81.3 | 0 / 0 / 3 |
At 16k the sweep reads as quality FALLING with effort - a truncation
artifact (11 of 12 truncations returned empty content: the runaway lives
inside the reasoning block). With room to finish, all three efforts land
within 1.6 points: indistinguishable at n=25. EFFORT BUYS WALL CLOCK, NOT
MEASURABLE QUALITY ON THIS SUITE (walls 1.00 / 1.47 / 2.70 h; mean output
830 / 1,228 / 2,217 tokens; ~42 t/s decode). Three xhigh prompts exceed
32,768 - genuine non-terminating loops, reported as such. MATH-500[3]
needed 18,273 tokens and was CORRECT - the budget rule's poster child.
Determinism: 139/139 non-truncated prompts byte-identical across cap
raise - empirically licenses rule 7's rerun-only-affected-arms.
Per-benchmark at the 16k cap: GSM8K 100/100/100, MATH-500 92/100/92,
HumanEval 100/96/84, MBPP 92/84/88, MeetingBank ROUGE-L 22.6/22.4/22.3.
At the 32k rerun the affected cells become: low MATH-500 96, xhigh
MATH-500 100 / HumanEval 92 / MBPP 92 - reconciling exactly to the
82.1/80.5/81.3 composites. (CORRECTION 2026-08-23 evening: this entry
originally labeled the 16k rows as 32k; caught by the Gen-2 draft
numeric audit.)
Scorer bugs found by the live run and fixed symmetrically (selftest
78/78): MATH-500 presentation-vs-value normalization (low arm 60->92),
GSM8K unit-suffix compare (xhigh 92->100), newline squeeze; all arms
re-graded offline from kept transcripts. Full log: work/rule21-live.md.
Power: 500ms logger covered 10:48-13:19 (xhigh-cap32k tail + all rerun
arms + trailing idle), 17,716 samples -> data/power/rule21-power.csv.

## 2026-08-23 - Energy joins (E0 + E8a, zero GPU; full tables work/energy-joins.md)
E0 (rule-21 arms, drafter OFF, mixed regime, in-band board power): pooled
J/decode-token 7.884 +/- 0.307 (n=115 requests wholly inside the logged
window); tokens/kWh 429k-465k; prefill 0.41-0.79 J/prompt-token. Coverage:
medium/low cap-32k arms full, xhigh-cap32k tail-only (63.4%; full arm
estimated 746-764 Wh); the 16k arms and GSM8K/ALPACA/MeetingBank/MT-Bench
have no power data. Provisional settled idle 31.2 W (pending matrix A1/A2).
E8a (effort arms, MTP n4/p0.75 ON, temp 1.0, n=1/level): reproduces
published Wh within 0.05%. J/decode-token 4.26 / 5.18 / 6.60(trunc) /
6.13(120k); tokens/kWh 845k / 695k / 545k / 587k; EDP 1.57e7 / 4.84e7 /
5.52e8 / 4.16e8 J.s; prefill 0.12-0.18 J/prompt-token = 26-43x cheaper
per token than decode; J/token == mean_W / decode_t/s with no residual.
HEADLINE: the drafter roughly halves J/token (4.3-6.1 on vs ~7.9 off).
ANOMALIES: (1) sustained board power drifted 305.5 -> 341.1 W at constant
throughput/temp/mem-clock, tracking SM clock 1453 -> 1606 MHz - decode is
bandwidth-bound so the extra clock bought nothing; "344 W sustained" must
become a range (306-341 W drafter-off); +/-6% J/token between arms hours
apart is instrumental. (2) partial-window joins must count only requests
wholly inside the log (caught: impossible 5.32 J/tok). (3) server-down !=
GPU-idle: plot rendering spiked the "idle" tail to 121-124 W five times.
(4) suite-file settings block records sampling the --greedy runner
overrides - result JSONs are authoritative for conditions.

## 2026-08-23 - Power matrix complete: 19 arms, 43.7 min, 100% coverage
Full tables: data/power-matrix/report.txt + arms.csv. In-band NVML board
power; PSU/CPU/node excluded. Idle baselines (settled, quiet desktop):
A1 no-server 29.9 W, A2 loaded 34.1 W (+4.2 W for a resident model -
the physically sane ordering; the published 33.2-vs-30.7 was a cooling
board). NOTE: the runner net columns used -IdleW 31.0 (hardcoded), not
A2 34.1 - uniform ~1% shift, no ranking changes; re-attribution is
zero-GPU when wanted.
HEADLINES:
- Speculation is an ENERGY feature: n10/p0.5 = 3.210 J/dec-token vs
  8.104 no-spec (2.52x less energy, 2.50x t/s, 6.3x better EDP).
  (CORRECTION 2026-08-23 evening, from the guide refactor consistency
  pass: the earlier "board W FELL 325->308->302, the win compounds"
  claim was a WHOLE-WINDOW artifact - those means fold each request
  prefill segment in, and prefill is a larger share of a shorter run.
  Decode-phase watts are FLAT: 344.6 -> 341.7 -> 341.0 W. The 2.52x
  energy saving IS the 2.50x throughput gain, exactly. J/token = W /
  t/s closes only against decode watts.)
- Batching (spec OFF): --parallel 2 = +60.3% aggregate t/s, -39.6%
  J/token (5.19 vs 8.59), -62% EDP. CONTRADICTS the earlier campaign
  +11% aggregate claim - likely because that was measured with the
  drafter ON (drafting already amortizes weight reads). A matched
  spec-on pair is required before publishing either number as general.
- Depth in energy: at 91k fill, 90.7% of the arm joules are PREFILL;
  J/prompt-token 0.164->0.306->0.421 (quadratic attention as joules);
  same 700-token answer costs 0.83 Wh at 1.5k vs 11.71 Wh at 91k (14x).
- Quant energy: Q4_K_M +8.0%, NVFP4-HIGH +13.4% J/token vs IQ4_XS
  (real, outside floor; CORRECTION - earlier line printed +7.8/+13.1,
  which reproduce from no pair of report.txt cells). KV f16 vs q8_0:
  0.7% = clean null.
- Regime: think-on 6.07 vs think-off 3.74 J/token (1.63x decode-rate
  penalty - independently cross-validates the 1.69x draft-length
  mechanism).
- NOISE FLOOR (B1/C1/D2 triplicate): 2.9% on J/token, 5.6% on EDP,
  monotonic with board heat - config-dependent (fast MTP arms agree to
  0.03%). Do not believe slow-arm gaps under ~3%.
- H power-cap arms SKIPPED needs-admin (probe: exit 4 Insufficient
  Permissions; commands recorded; cap never changed, left at 350 W).
OPEN ITEMS from this run: (1) matched spec-ON parallel pair before the
batching number ships; (2) F3 depth arm 10.4% below the cooled-ladder
reference (machine state suspect - recheck before publishing ladder);
(3) B3 t/s 13% above the matched re-sweep (ranking intact, level
unexplained); (4) E1 Wh/answer is per-700-tokens (ceiling hit), not per
complete answer; (5) SPILL heuristic fires on shr>0 - wants a
threshold (132-426 MiB WDDM shared mapping is benign; no arm spilled).

## 2026-08-23 evening - gemma PPL withdrawn (documented upstream defect); ladder logistics
Gemma-4-12B-QAT PPL 1,159.7 WITHDRAWN as a model result: gemma-4-instruct
family measures broken on llama-perplexity ecosystem-wide (published E4B
52.7 / E2B 144.5 / 26B-A4B 6,617; gemma-3-it and gemma-4 base sane). Rig
exonerated by two controls: Qwen anchor chunk1 exact, and our E2B control
133.7 vs published 144.5 (8%, different hardware/precision). bpb row for
gemma carries "not measurable on this stack - documented upstream defect";
the scored-benchmark decisive arm is the cross-model judge (in flight:
GSM8K 20/25 all correct so far, ~83 t/s). Agent self-corrections logged:
SWA hypothesis unsupported; llama-perplexity default -c is 512.
Ladder logistics: the other session downloader died 14:18 (five
.incomplete frozen); this session resumed all six rungs 18:33 (etag
resume preserved ~28 GiB); ladder polling continues, file-stability gate
unchanged.

## 2026-08-24 11:17 - ladder pass-1 complete; chain restart for the three remaining GPU jobs

The run-ladder3 runner exited CLEANLY at its 05:47 deadline (rule-20 pattern: deadline exit, not a crash) with one item pending: pass-2 infill UD-IQ2_S, whose file never appeared - the downloading session is dead (no .incomplete files, nothing new since the pass-1 six). Heartbeat was continuous to 05:46; the runner polled the file gate every 60 s from 01:24 to the wall.

Pass-1 stands COMPLETE (ledger data/quant-ladder/results.txt):
- Full PPL curve, 36 chunks / 294,912 positions each, all under the frozen phase-6 flags with the rig gate PASSing twice at 0.000% drift: IQ4_XS 6.5956 (anchor) / Q3_K_XL 6.7691 / IQ3_XXS 6.9187 / Q2_K_XL 6.9957 / IQ2_XXS 8.0079 / IQ1_M 8.1418 / IQ1_S 8.9265.
- Pass-2 enablement math: UD-IQ2_S ENABLED (bracket gap 14.47% vs reference 1.11%, ratio 13.0 >= 1.5); UD-IQ3_S NOT enabled (ratio 0.84 < 1.5) - the curve is flat above 9 GiB and steepens hard below it.
- Detectors: PASS at every rung down to IQ1_M. Two degradation signatures BEFORE the break: IQ1_M lexical diversity uniq=0.358 vs ~0.50 band elsewhere. First hard functional FAIL: UD-IQ1_S (1.83 bpw) returns an EMPTY JSON echo while its prose and fences still pass - the ladder found its "clearly no" rung.

11:17 restart (work/chain-0824.ps1, detached, own log chain-0824.log):
1. gemma-trunc-probe (running at launch check: server healthy, GPU 93%)
2. decisive-arm qwen-iq2xxs - the equal-budget primary arm. Rule-25 DECISION line recorded in decisive.txt BEFORE launch: the rule-7 cap raise on truncation is pre-authorized for this arm (primary, comparator already carries cap-32k).
3. run-ladder pass-2 for UD-IQ2_S once the file lands and holds 20 stable passes.

DEVIATION (second occurrence, same justification as 2026-08-23): the manifest says the runner never downloads - it still does not. The SESSION took over the UD-IQ2_S download (hf download, etag-resumable, detached) because the downloading session is dead. Runner and download never touch the same file until the byte-stability gate says so.

## 2026-08-24 11:35 - trunc-probe verdict in 2 minutes; qwen decisive arm crashed a scorer defect and was relaunched fixed

GEMMA NON-TERMINATION: MECHANISM ANSWERED (data/quant-ladder/gemma-trunc/trunc-probe.txt). With --reasoning-format none (thoughts left raw in content), both previously-truncated prompts run to the 4,096 probe cap, finish=length, with ZERO think-close tags and ZERO end-of-turn markers in 9,771 / 12,511 chars of output. With --reasoning off, the SAME prompts terminate cleanly at 355 / 331 tokens, finish=stop. The runaway lives entirely in gemma-4-12B-it-QAT default thinking mode: it opens a reasoning block it never closes. Not a cap problem, not a scorer problem, and thinking-off is a clean workaround. Loop-vs-rambling classification deferred to the probe transcripts (probe-raw-*.txt) at synthesis.

SCORER DEFECT (new, exposed by the 2.15-bpw quant): UD-IQ2_XXS's GSM8K prompt 5 response ends in a bare "####" with nothing after it; datasets_io.py grade() did .splitlines()[0] on the empty tail and crashed the whole arm (IndexError, wall 39 s). No previous model on this rig ever produced that shape - the ladder's low rungs are exactly where new failure shapes appear. Fixed: empty tail now grades WRONG instead of raising (verified: bare-#### False, empty False, normal True). The fix cannot alter any recorded score: any earlier run reaching this path would have crashed, and none did. The bare-#### response itself is a degradation observation for the IQ2_XXS rung, recorded here.

Also: bench-arm.py's finally block wrote wall.json even on crash, which would have made the resumable rerun skip the arm as done - crashed artifacts archived as crashed1-arm-qwen-iq2xxs.* and the arm relaunched (11:35) under the fixed scorer. UD-IQ2_S download healthy in parallel (hf names the in-flight blob by hash in .cache; 2.8 of 8.4 GB at 11:24).

## 2026-08-24 11:54 - the equal-budget verdict: a 27B crushed to 2.15 bits beats a 12B at Q4_0

Both arms of the decisive comparison are now measured on the identical frozen suite (hash 1cdf54f8eb9d3f8f, SEED=42, n=25 greedy, GSM8K/HumanEval/MBPP - tokenizer-independent, which is why this and not perplexity carries the cross-family comparison per rule 6).

| arm | file | bpw | Mean | GSM8K | HumanEval | MBPP | truncs | wall |
|---|---|---|---|---|---|---|---|---|
| Qwen3.8-27B UD-IQ2_XXS | 6.767 GiB | 2.15 | **78.70** | 80.0 | 84.0 | 72.0 | 1 | 1,705 s |
| gemma-4-12B-it-QAT-Q4_0 | 6.497 GiB | 4.65 | 73.30 | 72.0 | 88.0 | 60.0 | 19 | 9,551 s |

At the same weight budget the crushed 27B wins the composite by 5.4 points and wins two benchmarks of three; gemma keeps HumanEval (88 vs 84). The wall-clock gap is real but is NOT a clean speed comparison - most of gemma's 2.65 h is its 19 never-terminating generations burning the full cap, not slower decoding (its decode is FASTER: 82-84 t/s vs 49).

CONDITIONS ASYMMETRY, unchanged and still disclosed: qwen ran at reasoning_effort=low with q8_0 KV; gemma ran at its own defaults (no effort knob). This is a deliberate difference, not a fair-fight claim.

RULE 7 fired as pre-authorized: the qwen arm truncated once (MBPP) at cap 16,384, so the cap-32k rerun of THIS ARM ONLY started at 11:53. The Mean above is PROVISIONAL until it lands.

## 2026-08-24 11:45 - the judge-gated pair gets its judge (rule 21's scoring gate, opened)

Rule 21 has always said ALPACA and MT-Bench are "judge-scored when an independent judge endpoint is configured; otherwise speed + transcripts only". No endpoint existed, so the published Mean has been a FIVE-of-seven composite, labelled as such. An endpoint now exists: scripts/bench/judge-panel.py, a blind three-seat panel of Claude Opus 5 subagents.

Protocol pinned: canonical MT-Bench single-answer rubric, 1-10; rule 21's (r-1)/9 x 100 normalization; MT-Bench turn 1 only; every answer rated by all three seats; each seat gets its own shuffle seed so ordering effects do not correlate; arm identity lives only in key-SEALED.json, which no seat reads.

Scoring gate satisfied, and its limit stated: the answers were written by Qwen, so no model grades its own output. It is NOT independence in the strong sense - the judge and this report's author are both Claude models. That is a correlated instrument, disclosed with every number the panel produces, and the reason the panel publishes inter-rater spread beside every mean.

KNOWN CONDITION, not hidden: a seat sees several answers to the same question inside one shuffled batch. This is not a clean-room single-answer protocol and travels with the numbers.

RULE 7 IN THE PAIR: of 150 kept answers exactly one hit its cap - xhigh ALPACA[21], 16,384 tokens, content EMPTY (the never-closed-thinking-block signature again, this time in Qwen at xhigh). Rerun queued (work/chain-0824b-rule7-alpaca.ps1, GPU-gated behind the ladder chain), decided in advance per rule 25. low ALPACA tops out at 2,033 tokens and medium at 1,714, so under greedy decoding their answers are byte-identical at any higher cap - raising xhigh's cap alone changes nothing else.

## 2026-08-24 12:30 - the judge panel returned: the effort levels separate for the first time

150 answers, 3 blind Claude Opus 5 seats, 450 ratings, none missing or partial. Seat spread 0.28-0.92 rating points out of ten.

| set | low | medium | xhigh |
|---|---|---|---|
| ALPACA (0-100) | 70.2 | **75.1** | 72.9 PROVISIONAL |
| MT-Bench turn 1 (0-100) | 80.7 | **85.3** | 79.7 |
| **7-set composite** | 80.2 | **80.4** | 79.8 |
| 5-set composite (unchanged) | 82.1 | 80.5 | 81.3 |

THE FINDING. Paired bootstrap over the same 25 prompts (20,000 resamples, seed 42): on MT-Bench **medium beats xhigh by 0.51 rating points, 95% CI +0.21 to +0.80, winning 14 prompts to 3 with 8 tied**. That is the FIRST instrument in this entire campaign that distinguishes the effort levels at all - five mechanically scored benchmarks could not, and the 7-set composite (0.6 spread) still cannot. ALPACA medium-over-low is +0.44 with CI +0.013 to +0.91: it clears zero by 0.013, six comparisons were run, and it is recorded as MARGINAL, not a finding. Every other pairing is a tie.

This SHARPENS rather than reverses the xhigh guidance. xhigh's case was always completeness on complex code (categorical, n=2, still stands). The judged pair adds the other half: on open-ended writing more thinking made answers measurably worse. Guidance is now: xhigh for hard code you need finished, medium for writing.

WHAT THE JUDGES CAUGHT THAT NO MECHANICAL SCORER CAN:
- Confident invention inside fluent prose: a "Hawaiian $2 bill", the first surfers ever riding a wave at Sunset Beach, a misdated battle, a nonexistent hula centre, mistranslated Hawaiian words; invented Metra line names and expressways matched to wrong interstate numbers; a 1-for-4 bonus issue on 1,000 shares turned into 1,500.
- **A degeneration our own detectors are blind to**: low MT-Bench[2], asked for a short story, began spelling out numbers ("one hundred and one, one hundred and two...") and never returned to the story - at **1,682 tokens**, nowhere near any cap, so no truncation counter saw it and none of D1-D4 would trip. All three seats rated it 1. Recorded as a measured INSTRUMENT GAP, not a footnote. Also: xhigh ALPACA[16] expanded to 100 near-duplicate list entries; low ALPACA[23] repeated two words three times each to pad a list.
- A failure that is the model's, not the dial's: low and medium independently returned the same bare noun phrase on an ALPACA prompt demanding a sentence, both rated 3 by every seat.

RULE 7: xhigh ALPACA[21] was empty at the 16,384 cap (all three seats rated it 1) - the same never-closed-thinking-block signature as the gemma runaway, here in Qwen at its highest effort. Its score is PROVISIONAL and the cap-32k rerun is queued GPU-gated (work/chain-0824b-rule7-alpaca.ps1). The other five cells are final.

INSTRUMENT LIMIT, published with the numbers everywhere they appear: Qwen wrote the answers and Claude read them, so the self-grading gate is satisfied - but judge and report author are both Claude models, a CORRELATED instrument. Mitigations (3 seats, sealed-key blinding, per-seat shuffle seeds, published spread, paired tests) are partial. "A second-vendor or human judge" is now an open negative-register entry; the packets, key and all 450 ratings are kept so another judge can be run over identical answers.

LAW AMENDED. Rule 21 gains: publish BOTH Means when a judge exists; a pinned judge protocol (different family, blind with sealed key, >=3 seats all rating everything, 1-10 rubric, (r-1)/9, and rule 7's no-filtering clause binds the judge - an empty answer is a 1, not an exclusion); paired-or-not-made for arm claims; correlated-judge disclosure; and the ruling that "unscored BY DESIGN" is the wrong label for a missing instrument - an absent judge is a GAP, and calling it a design choice dresses a hole up as a decision.

ARTIFACTS UPDATED: published guide (chinkeong.github.io commit 20721af, correction 26, new section 09-judge, footer fourth pass), templates/example-report.html re-cut and re-pinned to 20721af in this commit, index-gen2-draft.html (new 09.09, guidance renumbered to 09.10, register entry 11 closed), scripts/bench/README.md, METHODOLOGY rule 21.

## 2026-08-24 12:25 - DECISION: sub-Q4 daily-driver chapter PARKED; close Gen-2 first

User decision, asked and answered before any GPU was committed. The scoping document work/subq4-daily-driver-plan.md stands as written and is NOT cancelled - it is parked with its arms costed (A1 map ~2 h, A2/A3 depth ~1.5-3 h, A4 scored ~3-5.5 h, A5 IQ2_S, plus the zero-GPU A6/A7 and the republication sweep) and its kill criteria R1-R5 pre-registered. Nothing in it is started.

Priority is now: finish the running chain -> section 08 second pass -> swap the draft to index.html -> re-cut example-report.html -> close gates 3+4 -> fire the launch reminder for the fresh law-test campaign on a new model.

CARRIED FORWARD, unstarted, so the next campaign inherits it rather than rediscovering it:
- The republication sweep on the published guide is OVERDUE by the spec's own republication rule (six lines: 175, 1013, 1014, 1443, 1456, 1461 - pass-1 landed and those lines still describe a ladder in progress). This is zero GPU and should be the first thing done after the swap, not deferred to the next campaign.
- A7 (a counter-degeneration detector) is now DOUBLY earned: the judge panel independently proved D1-D4 blind to a degeneration shape at 1,682 tokens. That is an instrument gap with two witnesses.

## 2026-08-24 12:25 - ladder synthesis (pass-1 complete, scripts/quant-ladder/summarize.py)

**KNEE: UD-Q2_K_XL, 9.154 GiB, 2.912 bits/weight, PPL 6.9957 (+6.07% vs the IQ4_XS anchor).** It is the last rung before the curve turns up.

Marginal cost of shrinking, %PPL added per GiB saved: Q3_K_XL 1.07, Q2_K_XL 1.08 - then the cliff, Q2_K_XL -> IQ2_XXS at **6.06, which is 5.7x the median of every segment above it** (2.39 GiB bought for +14.47% PPL). Below that IQ1_M 3.34 and IQ1_S 19.28.

Functional floor is LOWER than the quality knee and they are different questions: the smallest rung that passes every detector is **UD-IQ1_M at 6.267 GiB** (+23.44%); **UD-IQ1_S at 5.767 GiB / 1.835 bpw FAILS** - it still writes clean prose and well-formed fences but returns an empty JSON echo. That is the ladder's designed right anchor doing its job: a rung where the answer is clearly no.

(CORRECTION 2026-08-25, from A6 - the execute probe. **This paragraph's "functional floor" is WRONG BY TWO RUNGS, in the direction that hurts a reader**, and the word "functional" is what was wrong: D1-D4 never ran the code. Under `node`, UD-IQ1_M does NOT function - `SyntaxError: Missing initializer in const declaration` - and neither does UD-IQ2_XXS - `TypeError: Cannot read properties of undefined (reading 'push')`. The **executed** functional floor is **UD-IQ2_S at 2.481 bpw**, the smallest rung whose program actually parses, runs and prints its answer. Kept here undeleted per rule 5: a detector that reads output cannot license the word "functional", and this is what that error looks like when it reaches print.)

Speed across the whole ladder (detector probe A, depth 218, no drafter, -c 8192, n=1 each): 40.02 -> 53.25 t/s. **The file shrinks 2.30x and decode speeds up 1.33x.** Sub-Q4 buys VRAM, not speed - the single most decision-relevant number in the ladder and the one that most needs a depth-and-drafter arm before it is published as guidance.

Rig gates: the IQ4_XS anchor reproduced 6.5956 twice at delta 0.000%, and the IQ4_XS-vs-NVFP4 pair resolved a 4.27% same-size quality gap against +/-0.045 error bars - the rig both reproduces and still discriminates.

Still open in the ladder: UD-IQ2_S (7.79 GiB, sits INSIDE the cliff - it is the one rung that decides where the cliff starts) is downloaded and queued behind the GPU; the qwen-iq2xxs cap-32k rule-7 rerun is running.

## 2026-08-24 12:29-12:35 - the last two ladder measurements landed

**UD-IQ2_S, the rung that located the cliff.** GiB 7.797, bpw 2.4806, **PPL 7.5481 +/- 0.05383**, bpb 0.6715, detectors PASS (uniq 0.5081, 993 tokens, 47.85 t/s), ts 12:34:27. It was enabled automatically by the steepening rule (bracket gap 14.47% vs 1.11% reference, ratio 13.0 against a 1.5 threshold).

What it answers: the two halves of the cliff cost **5.82 and 5.91 %PPL per GiB** - near enough identical. So the steep regime does NOT begin somewhere inside the 2.91-to-2.15 bpw interval; **it begins immediately below the knee**, at 2.91 bpw. Both halves clear their error bars by a wide margin (7.7 and 5.9 standard errors). The rule then evaluated UD-IQ3_S and DECLINED it (ratio 0.84 < 1.5). **The ladder is closed at nine files of this model.**

Corrected median: the marginal cost of the three segments above the cliff is **1.08 %PPL/GiB** (2.55, 1.07, 1.08), not the 1.07 recorded earlier - the earlier figure omitted the anchor-to-Q3_K_XL segment, which is 2.55. Ratio column now reads 5.4x and 5.5x for the two cliff halves against that median.

**qwen-iq2xxs cap-32k (rule-7 rerun), ts 12:29:01.** mean=78.70, GSM8K 80.0, HumanEval 84.0, MBPP 72.0 - **identical to the 16,384-cap arm**, and the single MBPP truncation SURVIVED the doubled cap. So the raise-the-cap remedy did not clear it; that prompt does not terminate at 32,768 either. The arm's status is now symmetric with the comparator's and its provisional mark is retired. True composite margin over gemma is 5.3 points, not 5.4 (the ledger's one-decimal rounding inflated it).

## 2026-08-24 15:46 - LIVENESS FAILURE, mine: three GPU hours lost to a stale .pid file

At 12:49 the session observed the ladder poller idling with nothing runnable and moved to stop it so the chain gate would open for the queued rule-7 ALPACA rerun. It killed the PID in `runner.pid` = 9984, confirmed `runner alive: 0`, and ended the turn believing the chain was released.

**runner.pid was written at 00:46:53 by the PREVIOUS ladder run.** The live poller was PID 32148, started 11:20:35 - exactly matching the chain log's `step start: chain-ladder-pass2`. The verification passed because nothing with PID 9984 was running: the check could not distinguish "I killed it" from "it was never there". The GPU then sat idle from 12:35 to 15:46 with a rule-7 rerun queued behind a gate that could not open. Killing a stale PID is also worse than a no-op, because the OS reuses PIDs and the kill may land on an unrelated live process.

Caught by the scheduled watchdog, not by the self-check. Fixed at 15:46:28 by resolving the process via `Get-CimInstance Win32_Process` COMMAND LINE and CreationDate, killing 32148, and confirming the EFFECT - `CHAIN DONE` appeared and the waiter opened its gate at 15:47:28.

Filed as a failure-library entry ("A .pid file names a process that is no longer that process"). The rule it earns: **resolve a runner by command line, never by .pid alone; and verify a kill by the effect you wanted - the chain advancing, the gate opening - never by the absence of a PID. Absence of a PID is absence of evidence.**

This is the third liveness failure of this campaign and the second where every safety mechanism worked and the schedule or the verification was wrong. The watchdog earned its keep again.

## 2026-08-24 16:08 - the rule-7 remedy has a limit, and this is the third case that proves it

The xhigh ALPACA rerun at cap 32,768 finished in 1,236 s. Result:

- **ALPACA[21] hit the 32,768 cap and is STILL EMPTY** (tokens=32768, chars=0). Doubling the budget bought nothing.
- **All 24 other answers reproduced BYTE-IDENTICALLY** (0 of 25 changed). Greedy determinism confirmed a third time on this rig, and it means the raise touched nothing it should not have.

Two consequences, and the second is the important one.

**(1) No re-judging is needed and the score does not move.** The judged content of item 21 is unchanged - still empty - so the panel's three ratings of 1 stand, xhigh ALPACA stays **72.9**, and the seven-set xhigh composite stays **79.8**. What changes is the LABEL: the cell is no longer PROVISIONAL-pending-a-rerun. The rerun happened. The number is final, carrying a disclosed non-terminating item.

**(2) THREE independent cases in this campaign now show the same thing: raising the cap does not cure a runaway.**
- gemma-4-12B-QAT default thinking: 19 of 75 items truncated at 16,384; at 32,768 the scores, the per-benchmark cells and the truncation count were all identical, at 1.78x the wall clock.
- Qwen UD-IQ2_XXS, MBPP: 1 truncation at 16,384, still 1 at 32,768.
- Qwen UD-IQ4_XS at xhigh, ALPACA[21]: empty at 16,384, empty at 32,768.

These are not budget shortfalls. They are **non-terminating generations** - the model enters a state it never leaves, and the cap is only the thing that eventually stops it. The gemma probe established the mechanism directly: with thinking left visible the runaway emits no end-of-thinking marker at all, and the same prompts with thinking disabled finish in a few hundred tokens.

RULE 7 AMENDED accordingly. The raise-the-cap remedy is mandatory once, and it is DIAGNOSTIC as much as remedial: if the raised-cap rerun reproduces the truncation, the item is a non-terminating generation and no further raise is licensed. Escalating a cap indefinitely against a non-terminating generation burns GPU hours to reproduce the same zero - the gemma pair cost 2.65 h to reproduce a number already in hand. Report the item, keep it in the denominator, and stop.

## 2026-08-24 17:05 - the re-judge: one finding survives, one dies, and the judge gets a noise floor

I was wrong earlier today. When the ALPACA rerun reproduced its truncation I argued no re-judging was needed, because the judged content was byte-identical and so the ratings could not move. That is REASONING WHERE A MEASUREMENT WAS AVAILABLE - the review gate caught it, and the measurement disagreed with the argument.

All three ALPACA arms were re-judged together (three fresh blind seats, v2 salted ids, 225 ratings) because one arm's generations had been replaced and mixing a pass-1 arm with a pass-2 arm inside one dataset would compare two judging sessions rather than two effort levels. MT-Bench never truncated and keeps its first-pass numbers.

FINAL: ALPACA 70.2 / 74.1 / 72.1 (was 70.2 / 75.1 / 72.9). Seven-set composite 80.2 / 80.3 / 79.7 (was 80.2 / 80.4 / 79.8). Five-set unchanged at 82.1 / 80.5 / 81.3.

**(1) THE MARGINAL RESULT DIED.** Pass 1 called ALPACA medium-over-low DIFFERENT (marginal) at +0.44, CI +0.013 to +0.907 - it cleared zero by thirteen thousandths and six comparisons had been run. Pass 2: **+0.35, CI -0.04 to +0.73, TIE.** It was noise. Labelling it marginal in advance is the only reason it never became a claim, and this is now the campaign's worked example of a pre-registered caution doing its job. **MT-Bench medium-over-xhigh is untouched** (-0.507, CI -0.800 to -0.213, 14 prompts to 3) and is now the ONLY surviving separation between effort levels - one of six comparisons.

**(2) THE JUDGE HAS A MEASURED NOISE FLOOR.** 74 of 75 answers were byte-identical between passes, so any rating change on them is the instrument, not the model: **mean absolute change 0.333 rating points, max 1.333, 25 unchanged exactly.** Averaged over 25 items an arm score moves at most ~1.0 point on the 0-100 scale. That band is exactly why a 0.51-point paired gap is a result and a 0.44-point one was not - the campaign can now SAY that with a number instead of asserting it. Measured on ALPACA only; MT-Bench was not re-judged, so applying the band there is an assumption and is labelled as one.

Cross-pass qualitative agreement is its own check: the second panel, with no knowledge of the first, independently flagged the same three degeneracies (the empty answer, the 100 near-duplicate season sets, the ripple/crash padding) and the same instruction failure (the noun phrase where a sentence was demanded).

ARTIFACTS: judge-panel.py gains rebuild/rescore/finalize; judge-scores-final.json is now the publishable record and rule21-merge-judge.py reads it; the guide is updated and pushed (cf62823); example-report.html re-cut and pinned to cf62823; the draft update is in flight.

## 2026-08-24 17:00 - GATE 3 CLOSED (the marriage audit) and GATE 4 CLOSED (internal consistency)

**GATE 3 - the marriage audit.** The user asked for neither new-replaces-old nor old-replaces-new but "old married new = superb newer generation". Closed by comparing templates/example-report.html against the blind report and carrying the better parent forward in each case: the old report's question-answering section names and its recipes-first shape; the new report's measurements, provenance chips and negative register. What the audit itself produced became law: rule 26 (one page-wide noise floor, precision respecting the band), review gate 4, the provenance grades on CITED and DERIVED, the republication rule, and the title law - a title states directly what the document is. All are in METHODOLOGY.md and REPORT-SPEC.md and were applied to both the guide and this report.

**GATE 4 - internal consistency.** Ran three times, because the document kept outrunning its own reviews:
1. The four-gate pass (numeric, provenance, reader, consistency) with an adjudicator that VERIFIED each blocker against the ledgers before passing it through - it dropped two of the gates' own blockers as reviewer error, which is the behaviour the gate exists to have. 12 blockers, 20 should-fixes, 5 notes. All applied.
2. A verify pass after those fixes: 10 defects remained, one blocking. It caught that the UD-IQ2_S rung had landed EIGHT MINUTES after the page was cut, that the qwen cap-32k arm had landed, and that class="tablebox" was undefined in this document's CSS so five new tables would have shipped clipped instead of scrollable.
3. A final verify pass after the re-judge: 3 defects, none of them a wrong number. A pointer still sent readers to the superseded pass-1 bootstrap; the re-judge's six replaced numbers had no self-correction entry, violating the page's own stated contract; and the page-wide noise floor named two instruments when there are now three.

Every number in the published report was independently re-derived from the ledgers by a verifier that recomputed rather than compared - all 28 marginal-cost cells, all six judged scores, all three composites, all twelve paired-interval bounds including their signs, and every count claim ("nine files", "sixteen self-corrections", "seven scored sets", "twenty-one words").

**PUBLISHED: results/qwen38-27b-blind/index.html at commit 83e11d2**, cut from source commit bf756c1, 428 KB. The draft file was deleted rather than left beside it - two copies of one document is how contradictions start. Generation 1 remains in git history.

The four gates the campaign owed are now all closed:
- Gate 1, the power matrix and its energy joins - closed 2026-08-23.
- Gate 2, the audit amendments - closed 2026-08-23 (rules 24-26, gate 4, the title law).
- Gate 3, the marriage - closed here.
- Gate 4, internal consistency - closed here.

## 2026-08-24 18:10 - the republication sweep, closed (zero GPU, ran alongside the accuracy ladder)

The spec's republication rule had been in debt since the ladder finished at 12:35: five places on the published guide still described a round that was running, contributing two results, or shipping nothing. Closed. Each site gained the evidence rather than merely losing the stale clause:

- **The 3-bit row for 16 GB cards** said "Unmeasured here" - for the file the guide actually recommends at that size. It is now the best-evidenced row in the table: PPL 6.7691 +/- 0.047, +2.63% vs the 4-bit default, the cheapest quality step on the whole ladder at 1.03 GiB saved, detectors clean. And what is STILL unmeasured for it - speed and fit on a real 16 GB card - is now stated rather than implied, because this rig owns one 24 GB card (rule 1, rule 13b).
- The Arc B580 row dismissed 2-bit in passing; 2-bit now carries its price.
- The 262,144 fp16 row called UD-IQ1_S merely too big; it is also the one rung that FAILS a functional check.
- Evidence tier and run log: the ladder is complete, and the log names what ships here and what does not.

Added the one honest summary section 08 owed, in Voice 1: quality falls ~1%/GiB down to 2.91 bpw and ~5x that below it, so the advice is **stop at about 9 GiB**, not "go as small as you can" - and the rung where the model stops WORKING is not the rung where quality turns. It closes by naming what is missing (speed at depth, window on a smaller board, the accuracy ladder in flight) and states that none of it is yet a recommendation to run a sub-4-bit file. Guide 6924755, pushed; example-report.html re-cut and re-pinned to it.

**A rule-6 constraint recorded BEFORE the accuracy ladder reports, so it cannot be rationalised afterwards.** Rule 6: accuracy at n<=25 is a smoke test detecting ~20-point collapses only; quants are ranked by PERPLEXITY. The running ladder is n=25 per cell. It therefore **may not rank the rungs** - that stays perplexity's job - and may only answer the collapse question: WHERE does the model break, not WHICH rung is better than which. The composite over three benchmarks pools 75 samples per arm, which is more power than one cell but still not a fine-grained ranking instrument. Rule 21's guardrail says the same from the other side.

**A rule-25 decision, also recorded in advance.** UD-IQ1_S already failed the detector screen, and rule 25's own dated case study is UD-Q4_K_XL carried through full treatment to publish one word. IQ1_S is LAST in the arm queue: if the curve has already collapsed at IQ1_M, **cut the IQ1_S arm** and publish its screen numbers instead of spending 30 minutes proving a screened-out file is bad.

**A REASONING self-check, recorded against myself.** "The accuracy cliff sits somewhere other than the perplexity cliff" is a TIDY story and I pitched it before any number existed - which is exactly the expertise-blindness trap (the tidier the story, the more it needs the extra probe; the acceptance-predicts-throughput story was tidy for a full day). The reversal check passes: if perplexity turns out to predict accuracy well, the two curves simply track and that is equally publishable. Writing it up either way, not hunting the divergence.

## 2026-08-24 18:35 - the rule-20 repetition audit found something the scorer could not

Ran the mandatory greedy-repetition check (work/ladder-repcheck.py, zero GPU) over the arms that had landed, BEFORE trusting their numbers. It reused the campaign's own detectors and added the unique-word ratio, because the judge panel proved this morning that those detectors are blind to a degeneration that merely counts upward.

**The detectors found no repetition loops anywhere.** What they found instead is better.

**EMPTY ANSWERS THAT ARE NOT TRUNCATIONS.** UD-IQ2_XXS returned **3 empty answers of 75**, and only ONE of them was a truncation. The other two - HumanEval[9] at 3,939 tokens and MBPP[18] at 7,296 - **terminated normally against a 16,384 cap** and emitted zero characters. The model spent its reasoning budget, stopped by itself, and returned nothing. No cap was hit, so no truncation counter moved: the arm reported `truncations=1` while the real failure count was three.

Control, and it is decisive: **the same three items at the 4.2-bpw anchor all scored 100.0**, using 701 / 4,152 / 1,829 tokens of real content. So this is the RUNG, not the prompts. And both the anchor and UD-Q3_K_XL returned **zero empties of 75**.

This is the OTHER shape of the failure rule 7 was amended for this morning. That amendment covered `finish_reason=length` - the runaway that a raised cap reproduces. This is `finish_reason=stop` with an empty body, which no cap governs and no truncation count sees.

LAW AMENDED (rule 20, artifact read-back): **the empty-answer rate is its own metric and is published separately from truncations**, because the truncation counter is structurally blind to half the failure. Empty answers stay in the denominator - rule 7 forbids filtering - and a rising empty rate is a degradation signal no accuracy cell explains. Failure-library entry added, keyed to the symptom an agent would actually grep: an arm scoring badly while the truncation count says nothing is wrong.

A LOWUNIQ note, recorded so it is not mistaken for a finding later: GSM8K[16] and HumanEval[19] flag low unique-word ratio at EVERY rung including the 4.2-bpw anchor (0.264 and 0.255 there). Same items, same flag, best possible quality - so that flag is a property of those prompts (repetitive code and table structure), not of any quant. This is exactly the control that separates an instrument artifact from a model result, and it is why the audit compares against the anchor rather than reading absolute thresholds.

ARMS SO FAR (frozen 3-benchmark suite, identical conditions):
| rung | bpw | Mean | GSM8K | HumanEval | MBPP | truncs | empties |
|---|---|---|---|---|---|---|---|
| UD-IQ4_XS (anchor) | 4.22 | **97.30** | 100.0 | 100.0 | 92.0 | 0 | 0 |
| UD-Q3_K_XL | 3.90 | **96.00** | 96.0 | 100.0 | 92.0 | 0 | 0 |
| UD-IQ2_XXS | 2.15 | **78.70** | 80.0 | 84.0 | 72.0 | 1 | 3 |

The 3-bit rung is 1.3 points off the anchor - far inside the +/-16-point smoke-test band, i.e. a tie, which is the strongest thing n=25 is licensed to say and it supports the guide's 16 GB recommendation. The 2.15-bpw rung is 18.6 points down, which clears the band and is a genuine collapse.

## 2026-08-24 21:05 - RULE 25 DECISION (pre-registered) and the paired ladder

**UD-IQ1_M landed at 85.30** (GSM8K 96.0, HumanEval 88.0, MBPP 72.0, **0 truncations, 0 empties**, 1,766 s).

**RULE 25 DECISION: LET UD-IQ1_S RUN.** The rule was pre-registered before any of these numbers existed: cut the bottom arm only if the curve had collapsed hard at IQ1_M (roughly below 70). It did not - 85.30 is in the 80s, and IQ1_M is a TIE with UD-IQ3_XXS and with UD-IQ2_S. With the curve still alive at 1.99 bpw, the 1.83-bpw anchor is genuinely informative about where the floor is rather than a screened-out file being carried through treatment to earn one word. Twenty minutes is also not the *hours* rule 25's case study is about. Decision made on the data, as written.

**THE NON-MONOTONICITY, tested rather than narrated.** IQ1_M (1.994 bpw, 6.267 GiB) scored 85.30 against UD-IQ2_XXS (2.153 bpw, 6.767 GiB) at 78.70 - a SMALLER, lower-bit file apparently beating a larger one by 6.6 points. Paired McNemar says **b=5, c=10, p=0.302: a TIE.** It is not a reversal and must never be written as one. What IS notable is the churn: those two disagree on **15 of 75 items** while roughly cancelling - more discordance than any adjacent pair above them, which is what two files failing in different places looks like.

**And they fail differently at the same score.** UD-IQ2_XXS carries **3 empty answers and 1 truncation**; UD-IQ1_M carries **zero of both** and loses its items to plainly wrong answers instead. Same statistical performance, different failure shape - which is precisely why rule 20 now requires empties and truncations as separate columns. A reader who only sees the Mean cannot tell "gets things wrong" from "sometimes returns nothing at all", and those need different mitigations.

**THE PAIRED LADDER, final form for the rungs measured so far** (McNemar, exact two-sided, on the identical 75 items; b = left correct & right wrong):

- Indistinguishable from the 4-bit anchor: **UD-Q3_K_XL** (p=1.00), **UD-Q2_K_XL** (p=1.00), **UD-IQ3_XXS** (p=0.25), **UD-IQ2_S** (p=0.0625, the weakest tie and right at the edge).
- Measurably worse than the anchor: **UD-IQ2_XXS** (b=14 c=0, p=0.0001) and **UD-IQ1_M** (b=9 c=0, p=0.0039).
- So **the boundary lies between 2.48 and 2.15 bits per weight**, and n=25 cannot place it more finely. Say the interval, never a point.

Losses are near-perfectly one-directional (c=0 in most rows): the smaller file almost never wins an item the larger one lost. Quality IS degrading monotonically all the way down - it is simply unresolvable by this instrument until the cliff. That is the honest reconciliation of a monotone perplexity curve with a flat accuracy curve, and it is the sentence the chapter should carry.

## 2026-08-25 01:05 - the accuracy ladder is COMPLETE, and two failures of mine to record

**UD-IQ1_S, the right anchor, landed at 34.70** (GSM8K 36.0, HumanEval 32.0, MBPP 36.0) with **20 truncations of 75** and a wall clock of **8,965.8 s - 2.5 hours**, more than four times the next-longest arm (8,965.8 s against UD-IQ2_S at 2,166.0 s = 4.14x). The rung the ladder was designed to prove "clearly no" proved it emphatically, and the MECHANISM is the interesting part: at 1.835 bpw this model loses the ability to STOP. Its own console log shows routine answers of 7,154 / 8,556 / 9,756 / 16,384 tokens where the 4-bit anchor answered the same prompts in a few hundred. It is not that the answers are wrong; it is that they never end. That is a qualitatively different failure from anything above it on the ladder, and neither the perplexity number (8.9265) nor the single detector probe revealed it.

This VINDICATES the rule-25 decision to let the arm run rather than cut it. The pre-registered rule said cut only if the curve had collapsed at IQ1_M; it had not, so IQ1_S ran, and it produced the most informative failure at the bottom of the ladder. A cut would have saved time and lost the finding.

### FAILURE 1 (mine): an automatic rule-7 escalation on a screened-out file ate the GPU

IQ1_S's 20 truncations triggered decisive-arm.ps1's AUTOMATIC cap-32k rerun at 23:28. That is **exactly the priority inversion rule 25 forbids** - "rule-7 cap-raises on SECONDARY arms are deliberate, priced choices, never automatic" - and it is the same shape as the dated gemma case study that earned the clause. It ran 1.6 h of a projected 4-5 h before I killed it at 01:05.

I pre-authorised that raise **thinking only of primary arms** and then launched a runner that escalates automatically. The rule existed, I had amended rule 7 myself twelve hours earlier, and I still walked into it. What the rerun would have bought: **nothing.** Rule 7 as amended makes the raise a DIAGNOSTIC distinguishing a budget shortfall from a non-terminating generation - and that answer was already in hand from 20 truncations at 16k on a file whose detector screen had already failed. No reader-facing number consumes an IQ1_S cap-32k Mean. The 16,384-cap arm stands as published, truncations reported.

### FAILURE 2 (mine): the drafter probe was starved and I let the watchdog lapse

work/drafter-at-2bit.ps1 - the probe that answers the user's live question about replacing the 4-bit daily driver - waited politely behind the runaway rerun and hit its own 120-minute deadline at **22:24 without running a single load**. It failed SAFELY and said so in its log, which is the design working; but the campaign lost four hours because a screened-out file's automatic escalation outranked the one measurement a reader was actually waiting for.

Compounding it: I did not reschedule the session watchdog on my last turn, so nothing was watching between ~21:30 and 01:04. Relaunched at 01:05 on a free card; first load healthy in 11.7 s.

### THE LESSON, and it is a script change not just a note

`decisive-arm.ps1` escalates on truncation with no gate. It should require the raise to be explicitly enabled per arm, so that "escalation is a decision" is enforced by the harness rather than by my memory. Recorded as the change to make before this script is used again.

## 2026-08-25 01:10 - THE DRAFTER PROBE INVERTS THE VERDICT (and proves the user right)

Four matched loads, three settled probes each, first post-prefill probe discarded (rule 12), 700-token novel-code generations at -c 32768, q8_0 KV, thinking off, temperature 0:

| file | GiB | drafter | decode t/s | acceptance | mean draft len |
|---|---|---|---|---|---|
| UD-IQ4_XS | 13.274 | off | 42.34 | - | - |
| UD-IQ4_XS | 13.274 | **on** | **86.91** | 0.611 | 5.70 |
| UD-Q2_K_XL | 9.154 | off | 45.66 | - | - |
| UD-Q2_K_XL | 9.154 | **on** | **77.01** | 0.551 | 5.08 |

**THE RANKING INVERTS WITH THE DRAFTER.** Drafter OFF, the smaller 2.9-bpw file is FASTER (45.66 vs 42.34, +7.8%) - which is what the whole accuracy ladder was measured under, and it says "swap your daily driver". Drafter ON, which is how every recipe on the published page actually ships, the 4-bit file is **12.9% faster** (86.91 vs 77.01) **despite being 45% larger**.

MECHANISM, and rule 11 predicts it almost exactly: the draft head degrades with bit-width. Acceptance falls 0.611 -> 0.551 (-9.8%) and **mean draft length falls 5.70 -> 5.08 (-10.9%)**, against a throughput fall of -11.4%. Draft length is again the throughput predictor, to within half a point. Speculation is worth **2.05x** on the 4-bit file and only **1.69x** on the 2.9-bpw one, and that difference is larger than the entire size advantage.

**ANSWER TO THE READER'S QUESTION: do NOT swap the daily driver.** UD-Q2_K_XL ties the anchor on accuracy (paired p=1.00, one discordant item of 75) and frees 4.12 GiB, but in the configuration the recipes ship it is materially slower. It remains the right pick where VRAM is the binding constraint - a 16 GB card - and the wrong pick on 24 GB where the 4-bit file fits with the drafter.

**THE LAW THIS EARNS, and the user identified it before the number came back:** *sweep at the shipped recipe, not at a clean-room default.* The ladder scored eight rungs drafter-off for clean determinism and produced the WRONG ORDERING for the configuration anyone runs. Had the sweep carried the recipe's flags from its first arm, the correct answer would have been in hand at no extra cost; instead it needed a separate probe, four hours were lost to the escalation that starved that probe, and the wrong answer was briefly the obvious one. Rule 25 now carries it, with this as its dated case study, plus the companion clause: **appetite is a property of the quant, not only of the effort level** - probe two or three prompts per rung before committing the arm, because a cap chosen for the top of the ladder is a truncation machine at the bottom (UD-IQ1_S: 20 truncations of 75, 2.5 h).

`decisive-arm.ps1` is fixed: the rule-7 raise is now opt-in per arm via `-EscalateArms`, so "escalation is a decision" is enforced by the harness instead of by my memory. Truncations are still always reported; only the rerun is gated.

INSTRUMENT NOTE: the probe script's acceptance regex did not match this build's log format and wrote `n/a`; the numbers above were recovered from the server logs directly (`draft acceptance = 0.61283 ( 573 accepted / 935 generated), mean len = 5.78`). Draft length parsed correctly throughout. The script's parser should be fixed before reuse.

## 2026-08-25 01:30 - CORRECTION to my own entry, and the empty-answer rate turns out to be the best instrument on the ladder

**I PUBLISHED A FALSE STATEMENT TODAY.** In the 21:05 entry and in commit 4c6c95e I wrote that "UD-IQ2_XXS carries 3 empty answers and 1 truncation; **UD-IQ1_M carries zero of both**" and built an argument on it about the two rungs failing differently. **UD-IQ1_M carries FIVE empty answers.** I read `truncations=0` off the ARM ledger line and inferred zero empties from it - which is exactly the inference rule 20's amendment forbids, written by me twelve hours earlier, in the same session. The truncation counter cannot see a silent empty; that was the whole point of the amendment, and I still trusted the counter instead of the artifacts.

Corrected, from the full audit over every arm (work/ladder-repcheck.py):

| file | bpw | empty | at cap | **silent** | median tokens |
|---|---|---|---|---|---|
| UD-IQ4_XS | 4.223 | 0 | 0 | 0 | 424 |
| UD-Q3_K_XL | 3.895 | 0 | 0 | 0 | 488 |
| UD-IQ3_XXS | 3.240 | 0 | 0 | 0 | 454 |
| UD-Q2_K_XL | 2.912 | 0 | 0 | 0 | 416 |
| UD-IQ2_S | 2.481 | 2 | 1 | **1** | 475 |
| UD-IQ2_XXS | 2.153 | 3 | 1 | **2** | 472 |
| UD-IQ1_M | 1.994 | **5** | **0** | **5** | 502 |
| UD-IQ1_S | 1.835 | 28 | 18 | **10** | 932 |

So UD-IQ1_M has MORE empties than UD-IQ2_XXS, not fewer, and **all five of its empties are silent** - it reported zero truncations while failing to answer five questions. The "they fail differently" argument is withdrawn: they fail the SAME way, and IQ1_M does it more.

**WHAT THE CORRECTED TABLE SHOWS, and it is better than what I thought I had.** The empty-answer rate is **exactly zero for every rung down to and including the perplexity knee at 2.912 bpw**, then rises monotonically: 2, 3, 5, 28. It is a cleaner signal than the accuracy Mean, which is flat-then-cliff with noise in between and could not separate adjacent rungs at all.

**It is also MORE SENSITIVE than the accuracy test.** It registers degradation at **2.481 bpw** - a full rung above where the paired accuracy test can resolve anything (UD-IQ2_S is a tie with the anchor at p=0.0625). A reader would meet this failure before any benchmark could measure it.

So the ladder now has three instruments with three different sensitivities, and they should be published together because each sees something the others cannot:
- **Perplexity** - monotone from the very top, the most sensitive to small quality loss, but says nothing about whether the model still works.
- **Empty-answer rate** - zero through the knee, then monotone; catches "returns nothing at all" a rung before accuracy notices, and costs no GPU to compute from artifacts already on disk.
- **Accuracy Mean** - flat until the cliff at 2.153; the only one that speaks in the reader's units, and the least sensitive of the three.

And the runaway signature is quantified: median answer length holds at 416-502 tokens for every rung from 4.223 down to 1.994, then **jumps to 932 at 1.835 bpw** - the rung that stops terminating.

## 2026-08-25 01:26 - NEGATIVE-REGISTER ENTRY 9 CLOSED: batching is worth +22%, not +60%

Matched pair on UD-IQ4_XS, drafter ON at the shipped n10/p0.5, three reps each, first post-prefill probe discarded:

| --parallel | aggregate t/s | per-slot t/s | acceptance | mean draft len |
|---|---|---|---|---|
| 1 | 82.98 | 85.79 | 0.618 | 5.70 |
| 2 | **101.25** | **55.41** | 0.620 | 5.61 |

**+22.0% aggregate, -35.4% per slot.** The quarantined §06.06 figure was +60.3% aggregate / -39.6% J-per-token measured with the drafter OFF; the prior campaign's drafter-ON figure was about +11%. The truth is between them and much nearer the prior campaign: **once the drafter is already amortising the weight read, batching has far less left to amortise.** That was the stated hypothesis for the quarantine and it is now measured rather than assumed. Acceptance is unchanged (0.618 -> 0.620) so the drafter is not being disturbed by the second slot; the cost is purely that each user waits ~35% longer for their own tokens.

**This is the SECOND time in twelve hours that a drafter-off measurement gave the wrong answer for the shipped configuration** - the first being the whole quant ladder. The user identified the pattern before either measurement came back, and rule 25 now carries it.

## 2026-08-25 01:30 - a gap the user's own question opened, and it is worth closing

Asked whether the 2.9-bpw file is worth taking on a 24 GB card for near-full context. The arithmetic says something better than "maybe", using this campaign's own measured KV slopes (39,936 B/token drafter-off, 45,056 with the drafter, plus 1,008 MiB fixed):

| window | UD-Q2_K_XL drafter off | UD-Q2_K_XL drafter on | UD-IQ4_XS drafter off |
|---|---|---|---|
| 131,072 | 14.03 GiB | 15.64 GiB | - |
| 180,224 | 15.86 GiB | 17.70 GiB | - |
| **262,144 (full native)** | **18.90 GiB** | **21.14 GiB** | **23.02 GiB** |

Board is 24.00 GiB and the rule-14 fence is 1.28 GiB (measured desktop max 1,181 MiB + 127 MiB load-to-load variance). So UD-IQ4_XS at the full native window leaves 24.00 - 23.02 - 1.28 = **negative**, which is exactly why the guide says full native is headless-only and requires --spec-type none. UD-Q2_K_XL at the same window leaves **3.8 GiB spare drafter-off and about 1.6 GiB drafter-on**.

If that holds, the smaller file buys something the 4-bit file cannot have at any speed: **the entire 262,144-token window, with speculation, on a machine you are also using.** That reframes the whole sub-Q4 recommendation for 24 GB owners - not a speed play (the drafter probe killed that) but a CONTEXT play.

**RULE 13b FORBIDS SHIPPING THAT AS A WINDOW LABEL.** It is arithmetic, and a blind reproduction in this same campaign already caught a window labelled "fully resident" collapsing to 8 t/s at depth once the drafter's VRAM was aboard. So work/q2kxl-fullcontext.ps1 is running: three arms at -c 262144 (Q2_K_XL drafter-on, Q2_K_XL drafter-off, IQ4_XS drafter-off as the control that should struggle), each loaded, VRAM read as a drafter on/off pair (rule 13a), then filled to ~236,000 real tokens and probed with the first post-prefill probe discarded (rules 12/13b).

**ANSWER TO "ARE WE FINISHED COLLECTING": NO, and this is why.** The question a reader asks changes which measurement matters. The ladder answered "how good is it"; it did not answer "what does it let me do that the bigger file cannot", and that is the actually useful question for a 24 GB owner. Outstanding after this: negative-register entries 17 (two cross-checks, ~15 min) and 6 (image budget + withheld-image control, ~15 min). The write-up waits until all of it is in, per the user's instruction.

## 2026-08-25 01:58 - THE FULL NATIVE WINDOW FITS ON THE 2.9-BPW FILE, measured

Two of three arms in. Deep fill of **218,233 real tokens** - 83% of the 262,144 window, which satisfies rule 13b's "probe near the top" - then the first post-prefill probe discarded and two settled probes timed.

| arm | board at load | board at depth | slack | decode at depth | mean draft len |
|---|---|---|---|---|---|
| UD-Q2_K_XL @262,144, drafter ON (n4/p0.75) | 22,714 MiB | 22,859 MiB | **1,717 MiB** | **21.33 t/s** | 2.43 |
| UD-Q2_K_XL @262,144, drafter OFF | 20,431 MiB | 20,567 MiB | **4,009 MiB** | 17.96 t/s | - |

**IT FITS, AND IT FITS WITH SPECULATION.** Drafter-off leaves 4,009 MiB of slack; drafter-on leaves 1,717 MiB, which clears the rule-14 fence (1,181 MiB measured desktop maximum + 127 MiB load variance = 1,308 MiB) by 409 MiB. Tight, and it must be published as tight - but it clears, and the whole native window is resident.

**The drafter still earns its keep at 218k depth**: 21.33 against 17.96 t/s, +18.8%, even though mean draft length has collapsed from 5.70 shallow to **2.43** at depth - exactly the depth behaviour rules 11 and 12 describe, and another instance of draft length predicting throughput rather than acceptance.

**The honest cost, which belongs beside the recommendation**: filling that window takes **424 seconds at 514.7 t/s prefill** - seven minutes before the first token of the answer. This is a long-document configuration, not an interactive one.

### The two-constant VRAM model under-predicts by ~1.2 GiB at this window

Predicted from the campaign's own measured slopes: 19,353 MiB drafter-off, 21,647 MiB drafter-on. Measured: 20,567 and 22,859. **A consistent +1,214 / +1,212 MiB offset** - compute buffers the two-constant model does not carry. Rule 13 already says the arithmetic is a FLOOR rather than the budget (the reference model under-predicted 15% at 32k); this measures the absolute size of that floor-to-reality gap at the full native window, and it is large enough to matter: a reader budgeting from the formula alone would have thought drafter-on left 2.9 GiB when it leaves 1.7.

### INSTRUMENT NOTE - my own probe column is misleading

`fullcontext.txt` records `prompt_n=4` for both arms. That is not a failed fill: probes 2 and 3 hit llama-server's PROMPT CACHE, so the server reports only the 4-token delta, and my script averaged prompt_n over the settled probes rather than reading the first one. The real fill is in the server log - `prompt eval time = 424001.08 ms / 218233 tokens`. The decode numbers are correct and ARE at depth; only the depth column is wrong. Fix the script to read the first probe's prompt_n before reuse. Filed here rather than silently corrected, per rule 20's verify-your-own-probes clause - a metric that looks wrong is checked before the run is believed, and this one looked wrong.

The third arm, UD-IQ4_XS drafter-off at the same window, is running as the control that should struggle: it took the board to 23,819 MiB, leaving 757 MiB - INSIDE the fence.

## 2026-08-25 02:05 - the control lands, and the 24 GB recommendation flips for one use case

All three arms, deep-filled to 218,233 real tokens (83% of the 262,144 window), first post-prefill probe discarded:

| arm | board at depth | slack | decode at depth |
|---|---|---|---|
| UD-Q2_K_XL, drafter ON | 22,859 MiB | **1,717 MiB** | **21.33 t/s** |
| UD-Q2_K_XL, drafter OFF | 20,567 MiB | 4,009 MiB | 17.96 t/s |
| UD-IQ4_XS, drafter OFF | 23,821 MiB | **755 MiB** | 15.96 t/s |

**At the full native window the 2.9-bpw file beats the 4-bit file on every axis at once.** It is **34% faster** at depth (21.33 vs 15.96), it leaves **962 MiB more slack**, and it can run the drafter *at all* - UD-IQ4_XS at this window is already at 23,821 MiB with speculation OFF, so there is no room to turn it on. And 755 MiB of slack is INSIDE the rule-14 fence (1,308 MiB), which measures what the guide previously asserted from arithmetic: full native on the 4-bit file is headless-only, and now the number says so.

**So the 24 GB recommendation splits by use case, and both halves are measured:**
- **Normal use, windows up to ~180k**: stay on **UD-IQ4_XS**. The drafter makes it 12.9% faster than UD-Q2_K_XL (86.91 vs 77.01 t/s shallow), and that beats the size advantage.
- **The full 262,144-token window**: switch to **UD-Q2_K_XL**. It is 34% faster there, keeps speculation, clears the desktop fence, and ties the 4-bit file on accuracy (paired McNemar p=1.00, one discordant item of 75). The 4-bit file cannot hold this window with a desktop running at any speed.

That is the complete answer to the reader's question, and it is a better answer than either "swap" or "do not swap": **which file is right depends on the window, and the crossover is measured.**

Honest costs that ship with it: filling 218k tokens takes 424 s at 514.7 t/s prefill - seven minutes before the first answer token - and mean draft length collapses from 5.70 shallow to 2.43 at depth, so the drafter is worth +18.8% there rather than the ~2x it gives shallow.

DATA COLLECTION FOR THE SUB-Q4 STORY IS NOW COMPLETE: the 8-rung accuracy ladder, the empty-answer audit, paired McNemar across all rungs, the drafter on/off pair on both candidate files, the matched drafter-ON parallel pair (entry 9 closed at +22%), and this full-native-window trial. Remaining register work (entries 17 and 6) is unrelated to sub-Q4 and does not gate the write-up.

# ==========================================================================
# PLAN OF RECORD - autonomous run, 2026-08-25 02:50 to ~10:50 (8 hours)
# Written BEFORE any of it is spent (rule 25: the plan is a gate, not a summary)
# ==========================================================================

## PHASE A - 02:50-03:20, NO GPU. Close the guide.
Apply the six numeric defects the publish verifier found and refused to certify:
  G1 "every other took under thirty minutes" (L1527, L1631) - FALSE, UD-IQ2_S ran 36 m -> "the next longest took thirty-six minutes"
  G2 "five times any other arm" (L2192) - 8,965.8/2,166.0 = 4.14x -> "more than four times the next-longest arm"
  G3 "each user waits about 35% longer" (L1110) - a 35.4% per-slot FALL is a 55% longer WAIT -> "about 55% longer - 12.6 s against 8.2 s for a 700-token answer"
  G4 "one user gets their tokens 35% faster" (L861) - inverted; 85.79/55.41 = +54.8% -> "about 55% faster"
  G5 glossary "section 08 measures nine of them" (L281) - the ladder table has eight rows -> "eight"
  G6 "roughly 2.8 GB" (L1687) - that is a GiB figure wearing a GB label -> GiB
Then collect the plain-words audit result, apply it, validate, commit+push the guide, re-cut templates/example-report.html with a matching pin in the SAME commit, and update memory qwen-3090-ground-truth.md.
CONSUMER: G3 and G4 are wrong numbers in advice a reader acts on. Nothing ships until they are right.

## PHASE B - 03:20-04:00, GPU ~40 min. The drawer.
Negative-register entry 17 (two cross-checks, ~15 min) and entry 6 (image budget + withheld-image control, ~15 min).
CONSUMER: two open register entries closed. WHY NOW: both are Qwen-rig-specific and expire the moment the machine is re-tooled for a different model.

## PHASE C - 04:00-06:00, GPU ~2 h. The 16 GB and 12 GB budget emulation.
The user asked for corrected recommendations for 16 GB and lower. EVERY claim this campaign makes about those cards is currently DERIVED, because the rig owns one 24 GiB card. A ballast process holds VRAM so that only 16,384 / 12,288 MiB remains free, then the candidate files load against that budget and are deep-filled.
Arms: UD-Q3_K_XL and UD-Q2_K_XL x {16,384, 12,288 MiB free} x {drafter on, off}, each with a deep-fill probe near the top of whatever window fits (rule 13b).
WHAT IT LICENSES, precisely: "fits in 16 GB" moves from DERIVED to MEASURED-UNDER-AN-EMULATED-BUDGET-ON-A-3090. It is NOT a 16 GB card measurement - it emulates capacity only, not that board's bandwidth, driver or desktop - and it must be chipped as its own evidence class, never as measured-on-a-16GB-card.
CONSUMER: the 16 GB and 12 GB rows of the card table in both documents, which today carry derived chips and an explicit "not measured here".

## PHASE D - 06:00-09:00, GPU ~3 h. The depth curve at the shipped recipe.
UD-IQ4_XS and UD-Q2_K_XL at ~4k / 16k / 32k / 64k depth, DRAFTER ON at the shipped flags (rule 25's new sweep-at-the-shipped-recipe clause - this campaign already got the ranking wrong once by measuring drafter-off), logging acceptance and mean draft length at every depth, first post-prefill probe discarded (rule 12), n=3 settled probes.
CONSUMER: the "expected speed" line of every recipe card, and the sub-Q4 story's missing middle - today it has shallow speed and ONE deep point at 218k and nothing between.

## PHASE E - 09:00-10:50, NO GPU. Fold in and draw.
Write C and D into both documents; build the three-instrument overlay chart the user asked for (perplexity, empty-answer rate, accuracy Mean on one bits-per-weight axis, each normalised against the anchor - the picture that shows three instruments breaking at three different points); final verify; commit+push; re-cut the example.
A figure never carries a number alone (REPORT-SPEC): charts go BESIDE the tables, never instead of them.

## DISCIPLINE, carried from tonight's failures - every one of these cost real hours
- NO automatic rule-7 escalation. decisive-arm.ps1 now gates it behind -EscalateArms; any raise is a decision made and priced before launch.
- Appetite probe before committing any arm with a new file or config: generation length grows as bit-width falls, and a cap chosen for the top of a ladder is a truncation machine at the bottom.
- Anything speed-related runs at the SHIPPED recipe, drafter ON. Measured drafter-off, this campaign got the quant ranking backwards and the batching figure wrong by 38 points.
- Resolve every runner by COMMAND LINE (Get-CimInstance Win32_Process), never by .pid - a stale .pid cost three GPU hours - and verify every kill by the EFFECT, not by the absence of a process.
- The watchdog reschedules EVERY tick. It lapsed once tonight and four hours went missing.
- Every arm names the reader-facing number that consumes it before it starts. No run earns its hours on completeness or curiosity.
- Empties and truncations are counted separately from artifacts, never inferred from a counter.

## 2026-08-25 02:55 - DEVIATION from the plan of record, phase C, with its reason

The plan called for a BALLAST process holding VRAM so only 16,384 / 12,288 MiB stayed free, to move "fits in 16 GB" from DERIVED to MEASURED-UNDER-AN-EMULATED-BUDGET. Not run as written. Two reasons, the second the real one:

1. `torch` on this machine is **CPU-only** (2.6.0+cpu, `cuda.is_available()` False), so there is no clean CUDA allocation to build a precise ballast from. Soaking VRAM with a second llama-server is imprecise and puts two jobs on the card, against rule 20's one-job rule.
2. **It answers less than it appears to.** A card's CAPACITY requirement is a property of the model, the window and the flags - not of the board - so it can be measured directly here and read off by the owner of any card. What genuinely does not transfer is SPEED, which is bandwidth-bound, and no amount of ballast on a 3090 fixes that. The ballast would have proved one extra thing - that the driver behaves the same when the card is nearly full - which is second-order against the cost.

REPLACED BY work/window-ceiling-subq4.ps1, launched 02:55: UD-Q3_K_XL and UD-Q2_K_XL x {32,768, 65,536, 131,072} x {drafter on n4/p0.75, drafter off} = 12 arms. Each loads, reads VRAM at load, deep-fills to ~90% of its window (rule 13b), discards the first post-prefill probe (rule 12), then times two settled probes and records the real fill length from the server log rather than from the cached probes - the instrument trap that bit the full-context run four hours ago.

WHAT IT LICENSES, and the wording matters: a REQUIREMENT table, in MiB, that a reader subtracts their own desktop from to pick their `-c`. Capacity transfers across cards; the decode column does NOT and stays labelled as this 3090's. That is a better deliverable than a ballast emulation would have produced, and it is honest in the same place the ballast would have been tempting to overclaim.

## 2026-08-25 03:13 - PHASE C COMPLETE: the requirement table, measured

Twelve arms. Each loaded, VRAM read, deep-filled to ~90% of its window, first post-prefill probe discarded (rule 12), two settled probes. Fill lengths read from the server log, not the cached probes.

**VRAM required at depth, MiB, and decode at that depth:**

| file | -c 32,768 | -c 65,536 | -c 131,072 |
|---|---|---|---|
| **UD-Q3_K_XL** (12.244 GiB) drafter ON | 15,530 / 39.59 t/s | 16,906 / 42.98 | 19,724 / 41.68 |
| UD-Q3_K_XL drafter OFF | 14,322 / 36.44 | 15,568 / 31.28 | 18,064 / 23.91 |
| **UD-Q2_K_XL** (9.154 GiB) drafter ON | 12,606 / 43.19 | 13,982 / 40.30 | 16,800 / 28.76 |
| UD-Q2_K_XL drafter OFF | 11,396 / 33.48 | 12,644 / 32.18 | 15,140 / 24.54 |

The drafter costs a consistent **1,198-1,660 MiB** across every file and window.

### THE 16 GB ANSWER, and it is decisive

Usable budget on a 16,384 MiB card after the 1,308 MiB desktop reserve: **15,076 MiB**.

- **UD-Q2_K_XL at -c 65,536 WITH the drafter: 13,982 MiB - fits with 1,094 MiB to spare, and runs 40.30 t/s.**
- UD-Q3_K_XL fits ONLY at -c 32,768 with the drafter OFF: 14,322 MiB, 754 MiB to spare, 36.44 t/s. With the drafter on it needs 15,530 and does not fit.

So on a 16 GB card the 2.9-bpw file gives you **more speed (40.30 vs 36.44), twice the context (65,536 vs 32,768), speculation you can actually keep, and 2,924 MiB less memory** than the 3.9-bpw file. And it ties the 4-bit reference on accuracy (paired McNemar p=1.00). **UD-Q2_K_XL is the 16 GB recommendation, and it is not close.**

### THE 12 GB ANSWER IS NO, and that is worth saying plainly

Usable budget after the reserve: 10,980 MiB. The smallest configuration measured - UD-Q2_K_XL at -c 32,768 with the drafter off - needs **11,396 MiB**, which is **416 MiB over**. Nothing in this ladder fits a 12 GB card with a desktop running. The honest advice for 12 GB is a smaller model, not a smaller quantisation of this one.

### A finding neither file predicted: the drafter's value at depth moves in OPPOSITE directions

UD-Q3_K_XL, drafter-on over drafter-off: **1.09x at 32k, 1.37x at 65k, 1.74x at 131k** - speculation matters MORE the deeper you go.
UD-Q2_K_XL: **1.29x at 32k, 1.25x at 65k, 1.17x at 131k** - it matters LESS.
Mean draft length tells the same story from the other side: Q2_K_XL starts higher (4.67 at 32k) and falls to 3.20 at 131k, while Q3_K_XL holds 2.91 -> 3.00 -> 3.30. The 2.9-bpw file drafts well shallow and degrades with depth; the 3.9-bpw file is the reverse. This is rule 11 again - draft length, not acceptance, carrying the throughput - and it is a second, independent reason the 24 GB long-context recommendation should not be read as a general one.

## 2026-08-25 03:32 - PHASE D reshaped, and why

The plan had phase D as a 4k/16k/32k/64k depth curve, ~3 h. Phase C already measured decode at depth for three windows on both sub-Q4 files, so the depth curve's marginal value collapsed - what is MISSING is the 4-bit reference at the SAME windows, without which the requirement table cannot be compared. Phase D is therefore the identical sweep on UD-IQ4_XS: six arms, ~45 min instead of three hours. Launched 03:32 (work/window-ceiling-iq4xs.ps1). The saved time goes to phase B's drawer entries and to the write-up.

## 2026-08-25 03:42 - PHASE D COMPLETE, and a result I am NOT publishing yet

The 4-bit reference at the same three windows completes the requirement table:

| file | -c 32,768 | -c 65,536 | -c 131,072 |
|---|---|---|---|
| **UD-IQ4_XS** (13.274 GiB) drafter ON | 16,586 MiB / 41.35 t/s | 17,962 / 42.69 | 20,848 / 34.35 |
| UD-IQ4_XS drafter OFF | 15,376 / 35.92 | 16,678 / 30.73 | 19,188 / 24.77 |

Set against phase C, the drafter-ON rows at matched windows read:
- **32,768**: Q2_K_XL 43.19 · IQ4_XS 41.35 · Q3_K_XL 39.59
- **65,536**: Q3_K_XL 42.98 · IQ4_XS 42.69 · Q2_K_XL 40.30
- **131,072**: **Q3_K_XL 41.68 · IQ4_XS 34.35 · Q2_K_XL 28.76**

### The 131k row is suspicious and is being replicated before anything is written from it

Read naively it says the 3.9-bpw file is **21% faster than the 4-bit file at depth**. Two reasons not to believe it yet:

1. **Bandwidth alone predicts about 8%** (13.274 / 12.244), not 21%.
2. **It contradicts the mechanism that produced every other result in this campaign.** UD-IQ4_XS has the LONGER mean draft length at that window - 3.43 against Q3_K_XL's 3.30 - and is nonetheless the slower. Rule 11 says draft length is the throughput predictor, and it has held everywhere else, including in the drafter inversion and in phase C's opposite-direction finding. When a proposed effect contradicts the mechanism behind all the neighbouring results, suspect the measurement, not the mechanism.

n=2 settled probes cannot separate 21% from clock state or a warm-up artefact, and rule 26 puts this campaign's own floor at ~3% on slow arms and up to +/-25% on single probes. So work/depth131k-replicate.ps1 is running: the same three configurations at n=**5** settled probes, first post-prefill probe discarded, and a 30-second settle after the fill so clocks are steady (rule 12's ramp trap reads up to 45% low). It reports mean, min, max, standard deviation and the full probe list.

**If the ordering survives at n=5 it is real and gets published. If it collapses, the 131k row gets a BAND and no ranking** - which is what rule 26 requires of a level nobody replicated. Either way the write-up waits for it, because the sentence at stake is "which file is fastest at long context on a 24 GB card", and that is exactly the kind of tidy story REASONING's expertise-blindness check says to probe once more before believing.

## 2026-08-25 04:04 - THE 131k RESULT SURVIVED REPLICATION. I was wrong to doubt it, and the mechanism is now the open question.

n=5 settled probes per arm, first post-prefill probe discarded, 30 s settle after the fill:

| file | n=2 sweep | n=5 replication | sd | spread | acceptance | mean draft len |
|---|---|---|---|---|---|---|
| UD-IQ4_XS | 34.35 | **34.66** | 0.22 | 1.7% | 0.944 | 3.43 |
| UD-Q3_K_XL | 41.68 | **41.44** | 1.51 | 9.4% | 0.885 | 3.30 |
| UD-Q2_K_XL | 28.76 | **29.46** | 1.32 | 11.7% | 0.917 | 3.20 |

**UD-Q3_K_XL leads UD-IQ4_XS by 6.78 t/s = 19.6%, at 4.4 sigma on the combined spread.** The ordering is real. My pre-registered doubt was recorded and is now retired: the design could return "the claim survived" and it did, which is the only reason the doubt was worth writing down.

### The effect is real. The EXPLANATION I would have reached for is wrong.

Rule 11's model - throughput proportional to (1 + accepted per verify pass) divided by the cost of a verify pass, which scales with file size - predicts these three files should land at:

| file | accepted/pass | verify cost | predicted index | MEASURED |
|---|---|---|---|---|
| UD-IQ4_XS | 3.24 | 13.274 GiB | 0.3194 | 34.66 |
| UD-Q3_K_XL | 2.92 | 12.244 GiB | 0.3201 | 41.44 |
| UD-Q2_K_XL | 2.93 | 9.154 GiB | **0.4297** | **29.46** |

It fails in **both** directions. It puts IQ4_XS and Q3_K_XL within 0.2% of each other when they differ by 20%, and it makes UD-Q2_K_XL comfortably the fastest when it is comfortably the slowest. Bandwidth alone predicts 8.4% for the Q3_K_XL/IQ4_XS pair, not 19.6%.

**So: the effect is published, the mechanism is not.** AGENTS.md's standing warning applies exactly - "separate the effect is real from the explanation is right; 81.7 t/s was a real number with a wrong story". Recorded as an OPEN MECHANISM QUESTION rather than dressed in a plausible one. Candidate hypotheses, none tested, none to be published as though it were: memory pressure or allocator behaviour near 20.8 GiB of a 24.0 GiB board; a K-quant versus IQ-format kernel difference at depth (Q3_K_XL is the only K-quant of the three at this window); or the `mean len` counter measuring the verify batch rather than the accepted run, which this campaign has already flagged as an instrument quirk, making the draft-length column unfit for this comparison.

### What it changes for a 24 GB reader, and it adds a THIRD file to the picture

At -c 131,072 with the drafter on, **UD-Q3_K_XL is the fastest file measured** - 41.44 t/s against the 4-bit default's 34.66 and the 2.9-bpw file's 29.46 - and it needs 19,724 MiB, leaving 4,852 MiB free, far above the 1,308 MiB reserve. The window-dependent picture is now:

- **up to ~65k**: all three within a few percent; stay on the shipped UD-IQ4_XS.
- **~131k**: UD-Q3_K_XL, by 20%, replicated.
- **the full 262,144**: UD-Q2_K_XL, because it is the only one that still fits WITH speculation (21.33 t/s against the 4-bit file's 15.96 with the drafter forced off).

Three different files win at three different windows. That is a more useful answer than any single recommendation, and every leg of it is measured.

Launched work/depth98k-crossover.ps1 at -c 98,304, same protocol, to locate where UD-Q3_K_XL overtakes - at 32k the 4-bit file leads (41.35 vs 39.59), at 65k they are level (42.69 vs 42.98), at 131k Q3_K_XL leads by 20%.

## 2026-08-25 04:30 - RETRACTION: the 131k ranking I published 25 minutes ago is withdrawn

The 98,304 point contradicts it, and the contradiction is decisive. Decode at depth, drafter ON, across four windows:

| file | 32,768 | 65,536 | 98,304 | 131,072 | pattern |
|---|---|---|---|---|---|
| UD-IQ4_XS | 41.35 | 42.69 | 36.09 | 34.66 | rises then declines - plausible |
| **UD-Q3_K_XL** | 39.59 | 42.98 | **32.86** | **41.44** | **NON-MONOTONE, 26% jump 98k -> 131k** |
| UD-Q2_K_XL | 43.19 | 40.30 | 34.08 | 29.46 | clean monotone decline |

**A decode rate cannot RISE from 98k to 131k.** Deeper context means more KV to read per token; the curve must fall. UD-Q3_K_XL swings 30.8% across four windows in a non-monotone pattern while the other two files behave. So the 41.44 at 131k is not a property of that file being fast at depth - something about that configuration is unstable on this rig, and my 19.6%-at-4.4-sigma claim measured the instability, not a speed.

**WITHDRAWN, at every occurrence (rule 5):** "at -c 131,072 UD-Q3_K_XL is the fastest file measured, by 20%", and the 24 GB recommendation built on it ("at ~131k take UD-Q3_K_XL"). The corrected 24 GB answer reverts to two files: **UD-IQ4_XS up to ~131k, UD-Q2_K_XL for the full 262,144** because it is the only one that still fits with speculation. UD-Q3_K_XL has no window where it can be recommended on measured speed.

### The methodological lesson, and it is a new one

**Replicating within a condition cannot test whether the condition itself is anomalous.** I replicated 131k at n=5 and got sd 1.51, spread 9.4%, and a 4.4-sigma gap - every internal check passed, and the number was stable, reproducible and wrong. What exposed it was a NEIGHBOURING WINDOW, not more probes at the same one. n=5 at one point bought precision about a number that should never have been trusted in isolation.

Two signals were visible before the 98k point and I did not weight them enough:
- UD-Q3_K_XL carried the LARGEST spread at both replicated windows (8.4% and 9.4%) against UD-IQ4_XS's 0.5% and 1.7% - an order of magnitude noisier, in the file making the surprising claim.
- Its acceptance at 98k reads **1.00000**, which this campaign has already flagged as a degenerate reading ("two rows reading 100% and 99% acceptance ran 3.96 vs 10.54 accepted per target pass").
- Each n=5 run contains exactly one low outlier (98k: 30.73 among four ~33.4; 131k: 38.43 among four ~42.2), which is a state artefact signature rather than sampling noise.

Running work/q3kxl-instability.ps1 now: UD-Q3_K_XL alone at -c 98,304, independent reload, n=5. If it returns ~41 rather than ~33, the file's depth numbers are load-dependent and the whole UD-Q3_K_XL depth row must ship as a BAND with an instability note. If it returns ~33 again, the non-monotonicity is reproducible and stranger still, and it becomes a documented open anomaly.

**What survives untouched:** the 16 GB answer (UD-Q2_K_XL at -c 65,536 with the drafter, 13,982 MiB, 1,094 spare, 40.30 t/s), the 12 GB "no", the whole accuracy ladder, the empty-answer table, the paired McNemar results, the drafter inversion at shallow depth, and the full-262k finding - none of which depend on UD-Q3_K_XL's depth series.

## 2026-08-25 04:52 - the re-run REPRODUCED, and my retraction was half wrong. Correcting the correction.

UD-Q3_K_XL at -c 98,304, two independent loads:

| run | mean | sd | acceptance | mean draft len | probes |
|---|---|---|---|---|---|
| first | 32.86 | 1.07 | 1.00000 | 2.89 | 33.42 30.73 33.43 33.49 33.23 |
| reload | **32.95** | 1.25 | 1.00000 | 2.89 | 33.57 30.44 33.52 33.58 33.63 |

**Reproducible to 0.3%**, with identical acceptance, identical draft length, and the same one-low-outlier shape. So 98k is not noise and not load-dependent. It is a solid ~32.9.

### What I got wrong in the retraction, and it matters

I wrote: *"a decode rate cannot RISE from 98k to 131k... deeper context means more KV to read per token; the curve must fall."* **That argument is wrong for a SPECULATIVE decoder**, and this campaign's own rule 11 says why. With speculation the observed rate is not raw decode - it is decode divided by how many tokens each verify pass delivers, and that depends on MEAN DRAFT LENGTH, which is gated by `--spec-draft-p-min` on the drafter's confidence. Confidence depends on the content at that depth. So the effective rate CAN move non-monotonically with depth even though raw decode falls monotonically underneath it.

The counters say exactly that, and they say it cleanly:

| file | 98,304 | 131,072 |
|---|---|---|
| UD-Q3_K_XL | acceptance **1.000**, draft len **2.89** -> 32.9 t/s | acceptance 0.885, draft len **3.30** -> **41.4** |

Acceptance FALLS and the file gets FASTER, because the draft got LONGER. That is rule 11's headline claim - *acceptance is the speedup but mean draft length is the throughput predictor* - reproducing in a place I did not expect it. And an acceptance of exactly **1.00000** paired with a SHORT draft is the degenerate signature this campaign already documented: the p-min gate is cutting the draft early, so everything guessed is accepted because almost nothing is guessed.

### What still stands from the retraction

The **ranking** stays withdrawn, for a different and narrower reason than I gave. 98k now has two independent loads; **131k still has only one**. Before any sentence says which file is fastest at 131k, the 131k point needs the same treatment 98k just got. work/q3kxl-131k-reload.ps1 is running now - UD-Q3_K_XL alone at -c 131,072, independent reload, n=5, same protocol.

So the honest state of this thread, in three parts kept separate on purpose:
- **EFFECT**: UD-Q3_K_XL is ~32.9 t/s at 98k (reproduced twice) and measured 41.4 at 131k (once).
- **MECHANISM**: rule 11's draft-length story fits it, and fits it better than my "not physical" objection did.
- **CLAIM**: no ranking between files at 131k until that window is reproduced across loads.

That is the second time in two hours this thread has moved, and both moves came from one more probe rather than from more thinking about the probes I had.

## 2026-08-25 05:15 - RESOLVED: the non-monotonicity is real, and rule 11 explains it

UD-Q3_K_XL, both windows, two independent loads each:

| window | load 1 | load 2 | acceptance | mean draft len |
|---|---|---|---|---|
| 98,304 | 32.86 (sd 1.07) | **32.95** (sd 1.25) | 1.00000 | 2.89 |
| 131,072 | 41.44 (sd 1.51) | **42.04** (sd 0.36) | 0.88462 | 3.30 |

**Reproducible at both windows across independent server loads.** The 131k reload came back tighter than the original (sd 0.36, 2.2% spread), which retires the instability hypothesis entirely. This file really does run ~33 t/s at 98k and ~42 at 131k.

**The mechanism is rule 11, and it is unusually clean here.** Acceptance FALLS from 1.000 to 0.885 while mean draft length RISES from 2.89 to 3.30, and throughput follows the DRAFT LENGTH, not the acceptance. An acceptance of exactly 1.00000 beside a 2.89 draft is the p-min gate cutting the draft early on low-confidence content: everything guessed is accepted because almost nothing is guessed, and the file crawls. At 131k the content is such that the drafter keeps guessing, accepts a bit less of what it guesses, and delivers 28% more throughput. This campaign wrote rule 11 from a 1.69x reasoning-vs-answer contrast; it now has a second, independent instance of the same mechanism from a completely different axis.

### The full arc of this thread, kept because it is worth more than the number

1. Measured 41.68 at 131k with n=2 and **doubted it** - bandwidth predicted 8%, not 20%, and the draft-length column seemed to contradict it.
2. Replicated at n=5: **survived**, 4.4 sigma. Published it.
3. Measured the neighbouring 98k window: **contradicted it**. Retracted the ranking, and reasoned that decode "cannot rise with depth".
4. That reasoning was **wrong for a speculative decoder** - the observed rate is decode divided by tokens per verify pass, and p-min gates draft length on content confidence. Corrected the correction.
5. Reloaded both windows independently: **both reproduce**. The effect is real, the mechanism is rule 11, and the original number was right for a reason I had not understood when I published it OR when I retracted it.

**Two lessons, both new to this campaign:**
- **Replicating within a condition cannot test whether the condition is anomalous** - n=5 at one window passed every internal check twice over; only a neighbouring window could interrogate it. That stands, and it is why step 3 was correct even though its stated reason was not.
- **A retraction needs the same evidentiary standard as the claim.** I withdrew a replicated 4.4-sigma result on a physical argument I had not checked against this campaign's own rule 11. Retracting on a bad argument is not safer than publishing on one - it just fails in the other direction, and it nearly buried a real finding.

### Claim status
UD-Q3_K_XL's depth series is now publishable WITH its mechanism. The between-file RANKING at 131k still waits on one thing: UD-IQ4_XS and UD-Q2_K_XL each have only ONE load at that window. work/depth131k-crossload.ps1 is running both now. If they reproduce, the 131k ordering ships; if not, that row ships as bands.

## 2026-08-25 05:42 - ALL THREE FILES REPRODUCE AT 131k. The ranking ships, with its condition.

| file | load 1 | load 2 | sd (load 2) | acceptance | mean draft len |
|---|---|---|---|---|---|
| UD-Q3_K_XL | 41.44 | **42.04** | 0.36 | 0.885 | 3.30 |
| UD-IQ4_XS | 34.66 | **34.70** | 0.16 | 0.944 | 3.43 |
| UD-Q2_K_XL | 29.46 | **29.41** | 1.07 | 0.917 | 3.20 |

Every file within 1.4% of its first load. **The 131k ordering is real: UD-Q3_K_XL ~41.7, UD-IQ4_XS ~34.7, UD-Q2_K_XL ~29.4.** The retraction is fully reversed and the ranking is publishable - with the mechanism, and with the condition below.

### The complete depth picture, drafter ON (means across loads where measured twice)

| file | 32,768 | 65,536 | 98,304 | 131,072 |
|---|---|---|---|---|
| UD-IQ4_XS | 41.35 | 42.69 | **36.09** | 34.68 |
| UD-Q3_K_XL | 39.59 | 42.98 | 32.90 | **41.74** |
| UD-Q2_K_XL | **43.19** | 40.30 | 34.08 | 29.44 |

A different file is fastest at three of the four windows. That is not noise - every one of those numbers is reproduced or carries a tight spread - and it is the most useful thing this sweep produced.

### THE CONDITION THAT MUST TRAVEL WITH IT, or the recommendation is dishonest

The mechanism is `--spec-draft-p-min` gating draft length on the drafter's CONFIDENCE, and confidence is a property of **the content at that depth**. Every one of these numbers was measured on the same filler: wikitext-2-raw prose. A reader's actual content - code, a codebase, a chat transcript - may put the p-min gate somewhere else entirely and move the ordering with it. So this ships as **"measured on prose fill; worth ten minutes of testing on your own content"**, never as a universal law of these files. UD-Q3_K_XL's own 98k-vs-131k reversal is the proof that the ordering is content-sensitive rather than fixed.

### The 24 GB answer, final, every leg reproduced

- **up to ~65k**: all three within a few percent - stay on the shipped **UD-IQ4_XS**, no reason to move.
- **~98k**: **UD-IQ4_XS** (36.09 against 34.08 and 32.90).
- **~131k**: **UD-Q3_K_XL**, 20% faster than the 4-bit default, 19,724 MiB with 4,852 free, and it ties the reference on accuracy (paired McNemar p=1.00).
- **the full 262,144**: **UD-Q2_K_XL** - 21.33 t/s against the 4-bit file's 15.96, and the only one that still fits WITH speculation.

Unchanged: 16 GB is UD-Q2_K_XL at -c 65,536 with the drafter (13,982 MiB, 1,094 spare, 40.30 t/s). 12 GB is no.

DATA COLLECTION FOR THIS CAMPAIGN IS COMPLETE. Everything remaining is writing.

## 2026-08-25 10:30 - AN INDEPENDENT CROSS-CHECK, and it exposes a real scope limit in what we just published

Source: YouTube video **"Qwen 3.8 27B Quantizations Q1 - Q8 compared"** (title CONFIRMED by fetch, 2026-08-25), channel reported as Luke's Dev Lab. Channel, dates and per-task detail come from a **user-supplied breakdown**; the video itself was NOT watched from here. Graded accordingly: independent single-run CATEGORICAL observations, not a controlled study, and its point differences are not rankings (rule 8 - categorical findings are real at n=1-2, point differences are not).

Their setup differs from ours in three ways that matter: **reasoning effort HIGH** (ours: low for the accuracy ladder), the same unsloth XL variants but reaching up to Q8, and - the decisive difference - **long multi-turn AGENTIC tasks with tool calls** (a Kanban web app, Blender MCP 3D asset generation, a Godot 4 game) where ours were **single-turn benchmark prompts capped at 16,384 tokens**.

### Where they confirm us, independently

1. **IQ1_M is unusable, and it fails by LOOPING.** They report unrecoverable infinite loops in planning, endless tool-call loops, and call it unusable across all three tasks. We measured that same failure from single-turn prompts and zero GPU: IQ1_M carries **5 empty answers of 75, all SILENT** - terminating normally, returning nothing - while every rung above 2.481 bpw carries zero. And at 1.835 bpw the model stops terminating outright (20 truncations, median answer 932 tokens against 424).
   **This is independent validation of the empty-answer instrument.** A zero-GPU audit of saved transcripts predicted, from short prompts, the failure that only surfaces expensively in multi-turn agentic work. Our own accuracy Mean did NOT predict it - IQ1_M scored 85.30, which looks survivable. The instrument that caught it is the one this campaign only added yesterday.
2. **Q2_K_XL is surprisingly viable, and fits 16 GB.** They one-shotted a full Kanban app with it, zero intervention, and recommend it for 16 GB cards. That is our headline 16 GB recommendation, reached from perplexity, paired accuracy and a VRAM requirement table, on a different rig with different tasks at a different effort setting.
3. **Q4 is the sweet spot.** Their overall pick; our shipped default.

### Where they find something WE CANNOT SEE, and it limits our advice

**Q2_K_XL FAILED their Godot task** - trapped in infinite tool-execution loops immediately - and **Q3_K_XL failed it too**, generating crashing scripts until the project was corrupted. Both of those files carry **zero empty answers** in our data and tie the 4-bit reference on paired accuracy.

That is not a contradiction; it is a SCOPE LIMIT, and it is ours, not theirs. **Every number in this campaign comes from single-turn prompts of at most 16,384 tokens.** Nothing here tested a long multi-turn agentic loop with tool calls, where errors compound across steps and a model must keep terminating cleanly dozens of times in a row. Rule 22 says exactly this about the agentic bucket - it is where per-step error compounding lives - and this campaign SKIPPED that bucket on a cost gate.

**So our 16 GB recommendation needs a condition it does not currently carry.** We tell a 16 GB owner to run UD-Q2_K_XL. On this evidence that is right for chat, single-file coding and web work, and **may be wrong for agentic tool-calling work**, which is a common use for a coding model. Publishing that recommendation without the caveat would let a reader measure less than the report promised them - rule 2, the prime directive.

### What goes into both documents

- The scope limit, stated plainly wherever a sub-4-bit file is recommended: measured on single-turn prompts up to 16,384 tokens; agentic multi-turn behaviour NOT measured here; an independent tester reports Q2_K_XL and Q3_K_XL failing a multi-turn game-engine task at high effort.
- The IQ1_M convergence as corroboration for the empty-answer instrument, cited to them, with the grading stated.
- Their Q5/Q6/Q8 observations recorded as a region this campaign never measured at all (we stopped at 4.4 bpw).

### What this does NOT change
No number moves. The perplexity ladder, the paired accuracy results, the empty-answer table, the VRAM requirement table and the depth series are all unaffected - they measure what they measure. What changes is the SCOPE the recommendations claim.

## 2026-08-25 11:10 - D5, the loop detector: BUILT, VALIDATED, and it does NOT do what I expected

`scripts/bench/loop-detect.py`. Four orthogonal signals: N1 immediate repeats after normalising digits AND number-words; N2 the share of prose lines collapsing to one structural skeleton; N3 zlib compression ratio; N4 the worst sliding-window type-token ratio. Zero GPU - it reads transcripts already on disk.

### Validation, and it corrected me twice mid-build

**First run:** all three known degenerations scored merely "hint". Each fired exactly ONE signal but fired it hard - the counting story at N4=0.1167 against a reference minimum of 1.0000; the 100-set answer at N2=0.7645 against a reference maximum of 0.2222. My "two agreeing signals" rule was wrong: corroboration is right when signals are weak and wrong when one is unambiguous.
**Also caught:** N1 normalised DIGITS only, and this campaign's worst known loop counts in WORDS ("one hundred and one, one hundred and two"). The single signal built to catch counters was blind to the actual counter. Fixed - and the fix immediately caused its own failure.
**Second run:** false positives on the 4-bit reference went 1 -> 4. All four were legitimate CODE: a dict literal mapping number words to digits, a doctest block, two worked-example lists. Number-word normalisation turns `'one': 1, 'two': 2` into `'#': #, '#': #` - **manufacturing the exact pattern it was built to detect.** Fixed by running the two structural signals on prose only, with fenced code stripped.
**Final:** the two severe degenerations fire LOOP; the mild one fires hint; all four control items clean; **1 false positive in 75 reference answers**. And the severity ordering matches the judges independently - the answers rated 1 and 3 fire LOOP, the one rated 4-5 fires only a hint.

### The scan, and the honest negative

| file | bpw | n non-empty | LOOP | novel LOOP (not also on the reference) |
|---|---|---|---|---|
| UD-IQ4_XS | 4.223 | 75 | 1 | - |
| UD-Q3_K_XL | 3.895 | 75 | 4 | 3 |
| UD-IQ3_XXS | 3.240 | 75 | 3 | 2 |
| UD-Q2_K_XL | 2.912 | 75 | 1 | 0 |
| UD-IQ2_S | 2.481 | 73 | 3 | 2 |
| UD-IQ2_XXS | 2.153 | 72 | 2 | 2 |
| UD-IQ1_M | 1.994 | 70 | 1 | 0 |
| UD-IQ1_S | 1.835 | 47 | 4 | 4 |

**This is not a degradation signal.** UD-Q3_K_XL - a file that ties the 4-bit reference on accuracy - carries 3 novel flags, while UD-Q2_K_XL and UD-IQ1_M carry none. There is no monotone trend and none should be claimed. One item, MBPP[20], fires on FIVE different files including the reference: that is the prompt, not any model, and it is why the scan reports flags net of the reference at all.

**Why it fails here, and it is the same reason the video mattered.** These are single-turn answers with a median length of 416-502 tokens. A loop needs room to develop, and at that length it mostly cannot. The failure this detector exists to name is the one that appears in long multi-turn agentic runs - exactly the regime this campaign never measured. **So D5 is an instrument built for the next campaign, not a result about this one.**

**And the comparison worth publishing:** on THIS corpus the empty-answer rate gives a clean monotone signal (0/0/0/0/2/3/5/28) and the loop detector gives none. Two instruments aimed at the same family of failure, and on short single-turn answers only one of them works. That is a finding about the instruments, and it belongs beside them.

## 2026-08-25 - A6, the execute probe: the cheapest instrument in the campaign, and it moved a published number

**scripts/bench/execute-probe.py. Zero GPU. It runs `node` over code already on disk.**

Probe A is a CONTINUATION task, which matters for reading its artifacts. The prompt supplies the file header and `class MinHeap` down to `push(node, pri) {`, then asks for the rest and says "Output raw code only - no prose, no markdown fences, no commentary." **An output beginning `this.a.push({ node, pri });` is therefore CORRECT, not truncated.** I read those five files as clipped and was wrong; the prefix was recovered from `detectors.ps1` and prepended, per rung, by the shape each output actually took. Recording the misread because it nearly became a retraction of good data.

Sampler, confirmed from artifacts and not from source: probes ran through `Invoke-Probe`, **greedy by construction, temperature 0, top_k 1, no penalty field**; the accuracy arms record `temperature 0.0, top_k 1, presence_penalty 0.0, seed 42` in all 29 run manifests. These results are deterministic and carry no sampler confound.

| file | bpw | followed the prompt | executed under node v24.15.0 |
|---|---|---|---|
| UD-IQ4_XS | 4.223 | continued | **runs** - Total cost: 15 |
| UD-Q3_K_XL | 3.895 | continued | **runs** - Total cost: 10 |
| UD-IQ3_XXS | 3.240 | continued | **runs** - Total cost: 12 |
| UD-Q2_K_XL | 2.912 | continued | **runs** - Total cost: 8 |
| UD-IQ2_S | 2.481 | continued, but fenced | **runs** - Total cost: 15 |
| UD-IQ2_XXS | 2.153 | restarted the file | **TypeError** - Cannot read properties of undefined (reading 'push') |
| UD-IQ1_M | 1.994 | restarted, fenced | **SyntaxError** - Missing initializer in const declaration |
| UD-IQ1_S | 1.835 | restarted, fenced | **SyntaxError** - Identifier 'shortestPathCostsTotalTotalTotal...' |
| NVFP4-MTP-VERY-LOW | 4.404 | continued | **runs** - Total cost: 11 |
| gemma-4-12B-QAT-Q4_0 | 4.651 | continued | **SyntaxError** - Unexpected token '{' |

**All ten were published `verdict=PASS`. Six run.**

**1. The published "functional floor" was wrong by two rungs.** The 08-24 synthesis named UD-IQ1_M the smallest functional rung because it passed D1-D4. It does not function. The executed floor is **UD-IQ2_S, 2.481 bpw**. Corrected in place at that entry per rule 5. This is the failure mode the campaign exists to catch and it reached print: a detector that READS output was allowed to license the word "functional".

**2. D1-D4 are blind to whole-program syntax, and this is the THIRD witness.** The judge panel was the first, the 1,682-token degeneration the second. A missing brace contains no repeated n-grams, so no lexical detector can see it - and no amount of tuning their thresholds would help. **A parser is not a better detector of the same kind; it is a different kind.** A7 stands earned three times over.

**3. Instruction-following collapse predicts execution failure perfectly on this corpus.** Every rung that RESTARTED the file - ignoring "continue this file" - failed to execute. Every rung that CONTINUED as asked ran, with one exception (gemma). Three rungs also emitted the markdown fences the prompt explicitly forbade, and all three are at the bottom: IQ2_S, IQ1_M, IQ1_S. The boundary-token and instruction-adherence failures arrive together, and they arrive at the bottom of the ladder. n=1 per rung, so this is a signal to test at n, not a rate.

**4. A measured counter-example to "smaller model, more bits".** The common advice is that a smaller model at 4-5 bpw beats a larger one at 2-3 bpw for code and agentic work. Here **gemma-4-12B-QAT-Q4_0 at 4.651 bpw produced unrunnable code** - it opened `const insert = (node, pri) => { ... };` inside `push(node, pri) {`, never closed `push`, then wrote `siftUp(i) {` as if back at class-body level - **while Qwen3.8-27B at 2.912 bpw produced a working Dijkstra.** Verified as the model's error, not the harness's: the prefix leaves exactly one brace open and any fair concatenation reproduces it. **n=1, one task, one language.** It dents "almost always"; it does not refute the tendency, and it must not be published as if it did.

**HARDENED (2).** `bench.py` carries `SAMPLING = dict(..., presence_penalty=1.5)` as its non-greedy default. Every published run used `--greedy`, which zeroes it, so nothing measured is affected - but a penalty on code and JSON penalises braces, keys and indentation, which are legal repeats. Added a warning that fires when HumanEval or MBPP run with a nonzero penalty. Found by an external cross-check, not by us.

## 2026-08-25 - post-publication audit: the correction I made yesterday was incomplete, and the audit found it

**Four read-only lenses over both published documents, every finding sent to an independent agent instructed to REFUTE it by default. 37 raised, 19 refuted, 18 confirmed.** The refutation rate is the point: a lens that reports everything is worthless, and a third of what was raised did not survive contact with the file.

**THE FINDING THAT MATTERS, and it is about me.** Yesterday I corrected the "functional floor" and wrote in the commit message that it was "marked SUPERSEDED at every occurrence per rule 5." **It was not.** I corrected the callout that stated the claim and the ladder table beside it, and missed the two places a reader is most likely to meet it:

  - **section 08.04's "answer first" lead paragraph** - written expressly so a reader can stop there - still said the model works down to 6.3 GiB
  - **the page's opening Evidence-tier lede** still said it stops working below 6.267 GiB

I searched for the phrase I had used ("functional floor") and fixed what matched. Both misses state the same claim **without using that phrase**. **Rule 5 says every occurrence of the claim, and I swept for every occurrence of the wording.** That is the failure mode, it is subtle, and it is now in the failure library: *when retracting, search for the CLAIM - the numbers, the thresholds, the paraphrase - never only for the sentence you remember writing.*

**Reader-harmful, found in the guide, nothing to do with A6.** Both 16 GB recipes shipped `UD-Q3_K_XL` at `-c 49152` priced at "~15.3 GiB" from a **derived** bandwidth estimate. Measured, that file with the drafter needs 15,530 MiB at 32k and 16,906 at 65k, so `-c 49152` interpolates to **16,218 MiB - 1,142 MiB over the 15,076 MiB budget the same page publishes.** It does not fit. Both now ship `UD-Q2_K_XL` at `-c 65536` (13,982 MiB measured, 1,094 spare, twice the window, ties the reference on accuracy).

**And the worse half of that:** the Intel Arc Pro B50 recipe had **copied** the NVIDIA budget verbatim, and when the NVIDIA one got its correction note the copy did not. It carried no warning at all for a day. **A copied recommendation outlives the measurement it was copied from**, and nothing in the process was looking for copies.

**Self-inflicted, all four caught by the audit, all from the last hour's work:** the new section's heading said "third instrument" while its own body said fourth; the new figure was chipped MEASURED when all three of its curves are ratios against the reference; appending self-correction 19 falsified the sentence introducing the list ("the last two are a pair"); and the recipe change I made needed propagating to two card-table rows and the effort-ceiling table, which it did not have until I looked. **Editing a document breaks the sentences that describe it**, and a change is not finished at the place you made it.

**Also confirmed and fixed:** "the one file on the ladder that fails a functional detector" (four do); "a bigger file is a slower file" published without its drafter-off condition, next to a sentence stating a rule the page's own recommendations no longer follow; the drafter cost printed "1,198-1,660 MiB" where the table's own rows subtract to 1,208 (in BOTH documents); and "a 5080 and a 4060 Ti offload at nearly the same 8-12 t/s" inheriting a MEASURED framing for two cards this machine has never contained.

**What this says about the campaign's instruments.** The published-document audit is now the third instrument to find something the campaign's own process missed, after the judge panel and the execute probe. All three share one property: **they examine the artifact rather than the intention.** The pledge is that no reader may ever measure less than the report promised them; three separate times now, the only thing that caught the gap was something that went and looked.

## 2026-08-25 - REGISTER ENTRY 17(a) CLOSED, and the hypothesis lost

**`scripts/reference-3090/entry17-clockramp-test.ps1`. ~9 min GPU.**

**The claim under test.** The deepest round-5 energy arm reads 58.05 t/s where the cooled reference at the same depth and flags reads 64.76 - 10.4% low. This page explained that as a post-prefill clock state (rule 12), on the strength of the reference's own DISCARDED post-prefill probe reading 59.61, within 2.6% of the arm. That is a hypothesis, it was published as a reason, and its obvious test had never been run.

**A better test than the register proposed.** The register said "re-run that arm with prompt caching on". Done that way it compares a fresh run against a number measured on another day, so driver, clocks, ambient temperature and fill content all confound it. Instead both conditions ran **inside one server load**: UD-IQ4_XS, `-c 131072`, n4/p0.75, `q8_0` KV, filled to **92,487 tokens**. Probe 1 pays a **112.7-second prefill** and decodes immediately after it - the arm's condition. Probes 2-4 reuse the cached prefix, so no prefill precedes them - the cooled condition. Everything else is held identical, which no cross-day comparison can do.

| condition | decode |
|---|---|
| immediately after a 112.7 s prefill | **35.99 t/s** |
| prefix cached, no prefill (36.09 / 36.27 / 36.22) | **36.19 t/s** |
| difference | **+0.56%** - inside the 2.9% noise floor |

**REFUTED.** The mechanism this page invoked to explain a 10.4% deficit produces half a percent when isolated. **The outcome that costs something is the one that happened**, which is exactly why the three possible outcomes were written into the script's header before it ran.

**What changes.** §09.07's caveat keeps its ADVICE and loses its REASON: the deepest row's decode half should still be read as approximate, because a single probe carries a ±25% band - but the 10.4% gap is now **unexplained**, and the page says so rather than leaving a wrong reason attached. Run-to-run variation and a difference in fill content are both still open and neither was tested.

**What this run cannot claim, stated because it would be easy to overclaim.** Its absolute level (~36 t/s) is nowhere near either published figure, so it tests the MECHANISM, not that arm's LEVEL. The two numbers compared are each other, not 58.05 or 64.76. Separately and unplanned: 36.09 is where §08's independently-run depth series puts this file near this depth. That is consistent, but the windows differ (`-c 131072` here against the series' own), so it is an observation and **not** a matched replication.

**17(b) remains open** - the 13% drafting-level gap was not touched.

**A note on the instrument.** A within-run contrast is stronger than a cross-day re-run for any question of the form "does X depress Y", and this campaign has now been bitten twice by cross-day comparisons (the batching figure, the 131k ordering). Where a hypothesis can be tested by holding one server load and varying one thing inside it, that is the design to reach for first.

## 2026-08-25 - REGISTER ENTRY 6 CLOSED: what --image-max-tokens 1024 actually costs

**`scripts/vision/make-detail-target.py` + `entry6-image-budget.py`. ~6 min GPU. Both in PYTHON, deliberately - the harness is moving to Linux and new instruments should not add to the PowerShell debt.**

**The instrument, and two choices that make it stronger than the register asked for.** The register proposed "the same image at two budgets, asked a question whose answer depends on fine detail, scored blind, plus one control run with the image withheld". A blind judge is the right tool when the answer is prose. Here it is not needed: the target is GENERATED, so every answer is known exactly and scoring is string equality - no judge, no noise floor, no cost. And the target carries its own POSITIVE CONTROL: two questions about type rendered at 96 px and 54 px, which survives any plausible downsampling, beside five about type at 12-15 px, which should not. That separates a resolution result from a plumbing result, and the distinction earned its place immediately (see the harness failure below).

| arm | coarse | fine | all | image tokens |
|---|---|---|---|---|
| FULL `--image-max-tokens 10580` | 2/2 | 5/5 | **7/7** | 3,635 |
| REDUCED `--image-max-tokens 1024` | 2/2 | 3/5 | **5/7** | 1,043 |
| BLIND, no image (control) | 0/2 | 0/5 | **0/7** | 33 |

**The control is what makes the other two rows mean anything, and it behaved.** 0/7, with five of seven honest refusals ("I don't see a screenshot") and two guesses that were both wrong. Every correct answer above is therefore perception and not prior. Without this arm the FULL row is just a plausible transcript.

**The cap does what it claims.** 3,635 image tokens to 1,043 - a **3.49x cut**, against the register's estimate of 3.6x. Note the FULL arm never reaches 10,580: this image only needs 3,635, so at the shipped budget the flag is not binding at all.

**THE FINDING, and it is not "the model goes blind".** At 1,043 tokens the model still reads the layout, the headline, the banner, a 4-digit queue value and a 4-digit calibration offset. What it loses is the finest type - and **it does not know it has lost it**:

- `SHARD-07` latency: **207 -> 287**. One digit, silently wrong.
- unit serial: **QUB-85731-3D3B -> QLN-15731-3053**. Right shape, wrong content.

It does not refuse, and it does not hedge. It returns a confident, well-formed, wrong value. **That is a worse failure than blindness**, because a screenshot-reading agent propagates it without a signal. n=1 per question, 5 fine questions, 2 failures - a threshold, not a rate.

**HARNESS FAILURE, first run, and it is this campaign's own self-correction #1 repeated verbatim.** The first run scored 1/21 with twenty BLANK answers, which reads exactly like a perception collapse. It was `max_tokens=64` on a thinking model: the reasoning consumed the whole budget and `content` came back empty. The campaign's very first documented error was "a 700-token cap never reaches the answer at the default effort", and I re-made it in a new script. **The positive control is what exposed it** - a coarse question rendered at 96 px cannot be a resolution failure, so a blank there had to be plumbing. The script now forces `reasoning_effort: low`, caps at 800, records reasoning length on every row, and prints a warning that a blank is a harness result and must never be scored as a wrong answer.

**Also closed by the same run:** 12.02's perception observation had no withheld-image control, which made it a transport check rather than a perception result. It has one now.

## 2026-08-25 - the drafter pair REPLICATED, after two failed attempts that were my own error

**A reader challenged the published claim that UD-Q2_K_XL is slower with the drafter on, arguing from memory bandwidth that a 31%-smaller file must be faster. The premise that Q2_K_XL speed was "not measured on the page" was wrong - it is measured in three places - but the challenge was worth answering with a fresh measurement rather than a citation, and this machine becomes Ubuntu shortly, so it was also the last chance on this stack.**

**RESULT: the published table replicates, in a second implementation, in a different language, on a different day.** `scripts/bench/q2-vs-q4-headtohead.py` against `work/drafter-at-2bit.ps1`:

| arm | published | replicated | delta | acceptance pub -> repl |
|---|---|---|---|---|
| UD-IQ4_XS drafter off | 42.34 | 42.91 | +1.3% | - |
| UD-IQ4_XS drafter ON | 86.91 | **86.58** | **-0.4%** | 0.611 -> **0.611** |
| UD-Q2_K_XL drafter off | 45.66 | 45.58 | -0.2% | - |
| UD-Q2_K_XL drafter ON | 77.01 | **76.97** | **-0.1%** | 0.551 -> **0.551** |

Three of four throughput arms inside 0.4%, all four inside 1.3%, and **both acceptance figures exact to three decimals**. Drafter off, Q2_K_XL is faster by 6.2%; drafter on it is slower by 11.1%. **The inversion is real** and the reader's bandwidth reasoning, while correct about bytes per token, is outweighed by what speculation returns to the less-damaged file.

**TWO FAILED ATTEMPTS FIRST, AND THE FAILURE IS MINE.** I wrote a script called a replication and ran it twice WITHOUT OPENING the script that produced the numbers I was checking. Four conditions silently differed: **`-fa on` was missing**, **`--reasoning off` was replaced** by a `reasoning_effort` request field, `--load-mode none` was added, and the prompt was a different program. IQ4_XS drafter-on read **73.71** instead of 86.9.

Then I compounded it. Three of four arms matched, so I read the fourth as a failure to reproduce and inferred a mechanism from it - "the inversion is a property of the drafter setting" - ran a second mismatched arm to test that, and inferred a second mechanism - "the 2-bit draft head cannot use extra draft depth." **Both were artifacts of my own missing flags, and both were stated to the reader before being checked.** Retracted.

**THE TELL I MISREAD.** Three of four arms agreeing to ~1% is not "one bad number". It is **"the conditions are close but not identical"**. Near-agreement across most arms should raise the conditions question, not close it. Into the failure library.

**THE FINDING THAT SURVIVES, and it is about this campaign's reproducibility rather than about the models.** `-fa on` together with `--reasoning off` is worth **~17% on the IQ4_XS drafter-on arm** - 73.71 without them, 86.58 with. Neither is recoverable from a server log after the fact: llama-server prints no parameter dump in these artifacts. **The full flag set has to live in the artifact, not in the prose.** This is the second time today the same gap surfaced - the workflow verifier flagged the prefill anchor's unstated `-fa` state this morning, and I walked into the identical trap hours later.

**ONE COLUMN THAT DID NOT REPLICATE, AND IT IS MY FORMULA, NOT THE MEASUREMENT.** My derived mean draft length reads 7.22 / 6.83 against the published 5.70 / 5.08. llama-server does not expose a draft-call count, so I derived `draft_n / (predicted_n - accepted)`; the original used something else. **The ratio behaves the same way** - the 2-bit file drafts shorter in both - but the absolute numbers are not comparable and this replication does not confirm that column. Stated rather than quietly dropped.

**One noise note:** the Q2_K_XL drafter-on arm spread 7.0% across its three settled probes (80.19 / 74.78 / 75.95) where the other three arms spread under 0.5%. The mean still lands within 0.1% of published, but that arm is the noisiest in the pair and a single probe of it would not be trustworthy.

**LAW, unchanged but re-earned:** rule 3 says state the conditions. The corollary this adds is **read them before replicating**. A replication that has not opened the original is not a replication, and its disagreements are uninterpretable.

## 2026-08-25 - the drafter question a reader asked, and the gate that answered it

**A reader asked whether `--spec-draft-n-max 4` is the right card recommendation for someone chasing maximum speed who would accept a smaller window, and separately whether Q4_K_M should be dropped so readers stop struggling with a false choice. Both were good questions and both had answers the page had never measured.**

### Q4_K_M: kept, but it stops being a "Choice"

**Not deleted.** That section is titled "losers included" and exists so an option a reader has already heard of is ANSWERED rather than absent; Q4_K_M is the best-known 4-bit GGUF there is, and deleting it removes the answer, not the decision.

**The labels were the actual defect.** "Choice A" and "Choice B" manufacture a decision the measurement does not support, and were confusingly ordered - B appeared first on the page, A second. Now **THE DEFAULT** and **THE ONE YOU HAVE HEARD OF**.

**And the quality claim was overclaimed.** "Maximum measured quality" is retracted. The perplexity gap is **0.061** (6.535 vs 6.596) against this page's own **±0.063** combined comparison error - and the passage that sets that yardstick *names this very pair*. **Inside the bar.** The corroborating 200-question GSM8K comparison used a grader later found to carry three bugs and was never re-scored. One unresolvable difference plus one withdrawn instrument is not a quality advantage.

### The drafter: the card was right, for a reason it stated badly

Three measurements, each answering the previous one's weakness.

**Shallow, vision loaded, -c 122880:** n10/p0.5 reads **+33.2%** over n4/p0.75 with 2,023 MiB free. Shrinking `-c` to 98,304 to "afford" it buys nothing - 87.04 against 87.49 t/s, inside noise, for 24,576 fewer tokens. **So the reader's proposed trade is strictly worse than simply switching the flag.**

**Deep-filled to 112,735 real tokens:** the advantage halves to **+17.1%** (62.47 against 53.33) and slack holds at **1,776 MiB** - clear of the 1,308 MiB reserve. Slack collapse from load to depth was only 89 MiB, nothing like the 2.6 GiB that burned this page at 196,608. On that evidence the recommendation looked wrong.

**The gate that changed the answer:** a real 1440p image in flight on top of 105,397 tokens, board VRAM sampled every 0.5 s across the request rather than read at two end points. **Peak 23,450 MiB, leaving 1,126 MiB** against a 1,308 MiB reserve.

**Short by 182 MiB - and the same configuration varied 397 MiB between two loads on the same day.** So the verdict is not "fails", it is **"marginal"**, and marginal against a safety reserve is a no: the failure mode is not an error but a silent spill that costs half the speed and logs nothing.

**DECISION: the conservative drafter stays on the vision pick. The card was right.** What changes is the reason - it was argued against a *reasoning* stream at 5.6% when the reader was writing code, and is now measured on the workload it is actually recommended for.

### Three findings that outlive the question

1. **A shallow probe overstates speculation by about double** - +33.2% on an empty window against +17.1% at real depth. Every drafter comparison taken at an empty context is suspect by that factor.
2. **Vision is not degraded by context pressure, only memory is.** At 105,397 tokens the model correctly read a 15 px table cell - a fine-detail question with a known answer. Memory is what runs out at depth, not sight.
3. **An end-point VRAM pair cannot see a transient peak.** Load-and-depth readings missed 342 MiB that 0.5 s sampling caught. Any residency verdict taken from two readings is a floor, not a peak.

**NOT USED, stated so nobody mines it from the artifact:** that run's decode figure of 20.01 t/s. `max_tokens` was 200 and the correct answer is "207", so `predicted_n` is a handful of tokens and the rate is dominated by startup. It is not a speed result.

## 2026-08-25 - a 2.9-bit model sees as well as a 4-bit one

**Asked whether UD-Q2_K_XL should join the card so a 24 GB reader can have the full native 262,144 window WITH vision. That has two gates, and the memory one is the second. The first is whether a 2.9-bit model can still READ an image - the projector is separate from the weights, but the model interpreting those image tokens is the quantised one, and nobody had tested it.**

Same instrument as register entry 6: a generated 1440p target whose every answer is known exactly, scored by string equality.

| arm | UD-IQ4_XS | **UD-Q2_K_XL** |
|---|---|---|
| full budget `--image-max-tokens 10580` | 7/7 | **7/7** |
| reduced `--image-max-tokens 1024` | 5/7 | 4/7 |
| image withheld (control) | 0/7 | **0/7** |

**At the shipped image budget the 2.9-bit file is indistinguishable from the 4-bit one** - it read a 12 px serial (`QUB-85731-3D3B`) and a 15 px table cell exactly. Both controls score zero, so both columns are perception rather than prior.

**Where it does show, and it is where the flag is already wrong.** At the crippled 1024 budget Q2_K_XL drops to 4/7 against IQ4_XS's 5/7 - one extra miss - and the misses have the same signature as the 4-bit file's: **confident wrong values, never refusals.** 207 came back 287 on both files; the serial mangled on both. Q2_K_XL additionally missed the queue value (9155 -> 3155). So quantisation costs a little acuity only at a budget this campaign already recommends against, and costs **nothing measurable** at the one the recipes ship.

**This closes the first gate. It does not license the recommendation** - a window that holds tokens is not a window that can find them, and register entry 2 says every window this page ships is speed-verified and quality-unverified at depth. The needle probe is the second gate and it is running.

**Worth noting for its own sake:** this is the first evidence on this page that heavy quantisation leaves vision intact. Perplexity at 2.912 bpw is +6.07 %, task accuracy ties the reference, and now image reading ties it too. The 2-bit file keeps being better than its bits suggest.

## 2026-08-25 - REGISTER ENTRY 2, partly closed: the 262,144 window is real

**Entry 2 has been open the whole campaign and says the worst thing a measurement page can say about itself: "every shipped window beyond 8k is speed-verified and quality-unverified at depth. No retrieval or needle probe was run at any depth." A reader asked whether the full native window does work half of it cannot. That question could not be answered, so it got measured.**

**THE INSTRUMENT, and why it cost 20 minutes instead of the 12 hours entry 2 prices.** The register's plan is a needle grid, and prefill dominates its cost. This plants FIVE needles at 10/30/50/70/90% of one fill, prefills ONCE, then asks for each needle in its own small request - every question after the first hits the server's prefix cache. Five deep probes become one deep prefill plus five cheap questions.

Two design choices that decide whether the result means anything:
- **The needles wear the same sentence frame as the filler**, differing only in carrying a calibration key. A needle that reads differently gets found by SHAPE rather than by attention, and would flatter the model.
- **A control sector is never planted.** A model that invents a plausible key gets caught instead of scored.

| window | prefill | 10% | 30% | 50% | 70% | 90% | control |
|---|---|---|---|---|---|---|---|
| `-c 131072`, 120,281 tokens | 164 s | OK | OK | OK | OK | OK | NONE, correct |
| `-c 262144`, **241,655 tokens** | 498 s | OK | OK | OK | OK | OK | NONE, correct |

**5 of 5 at both windows, at every depth, with no confabulation.** The model retrieves a key buried 217,000 tokens deep as reliably as one at 24,000. On UD-Q2_K_XL - the 2.9-bit file - which makes it more surprising, not less.

**SO THE ANSWER TO THE READER IS YES: the full window is real, not a number.** 262,144 genuinely holds and yields twice the material 131,072 does.

**WHAT THIS DOES NOT ESTABLISH, and the distinction is the whole finding.** This is LITERAL retrieval - find the note that names GAMMA-17. The evidence this page already cites says accuracy collapses when retrieval requires INFERENCE rather than matching, and that mid-context material is used worse than material at the edges. **The window holds and yields; whether the model can reason ACROSS 240k is untested and stays in the register.** Entry 2 is partly closed, not closed.

**Also n=1 per depth, one filler shape, one file.** A smoke test that can say "clearly works" or "clearly broken", not a grid.

**The cost that belongs beside the capability:** 498 seconds of prefill - **8.3 minutes before the first token** - against 164 s at half the window. Prefill is compute-bound and does not scale with the window's convenience. This is a long-document configuration, not an interactive one, and the card must say so wherever it offers the window.
