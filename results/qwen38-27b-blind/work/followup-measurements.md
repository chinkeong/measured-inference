# Qwen3.8-27B follow-up measurements — four queued loose ends

Measured 2026-08-23, 02:48–04:29 local, on the user's RTX 3090 (24 GiB, WDDM,
driver 596.36, CUDA 13.2), Windows 11 Pro 26200, llama.cpp binaries at
`E:\AI\llama.cpp` (built 2026-08-19). One GPU job at a time, strictly
sequential. GPU verified idle before the first job (918 MiB board, desktop
only, no `llama-server` process) and released at the end (950 MiB, no llama
processes).

Every speed number below comes from the llama-server response's own `timings`
object (`predicted_per_second`, `prompt_per_second`), never from wall-clock
that includes prefill.

Scripts (all in `E:\AI\measured-inference\results\qwen38-27b-blind\work\`):
`followup-m1.ps1`, `followup-m2.ps1`, `followup-m2b.ps1`, `followup-m2c.ps1`,
`followup-m2d.ps1`, `followup-m2e.ps1`, `followup-m2f.ps1`, `followup-m3.ps1`.
Raw logs: `E:\AI\measured-inference\results\qwen38-27b-blind\data\followup\`.

Model files:

| label | path | size |
|---|---|---|
| UD-IQ4_XS | `C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-IQ4_XS.gguf` | 13.27 GiB |
| Q4_K_M | `C:\Users\chink\.lmstudio\models\lmstudio-community\Qwen3.8-27B-GGUF\Qwen3.8-27B-Q4_K_M.gguf` | 15.66 GiB |
| mmproj | `C:\Users\chink\.lmstudio\models\lmstudio-community\Qwen3.8-27B-GGUF\mmproj-Qwen3.8-27B-BF16.gguf` | 0.87 GiB |

---

## 1. IQ4_XS-specific MTP flag re-sweep on a realistic novel-code probe

**Answer: no. IQ4_XS does not prefer different MTP flags from Q4_K_M. Both
quants rank the seven configurations the same way and both peak at
`--spec-draft-n-max 10 --spec-draft-p-min 0.5`. What the quant changes is not
the ranking but the size of the prize: IQ4_XS turns the drafter into 2.18x
where Q4_K_M gets 2.04x, and IQ4_XS is faster than Q4_K_M at every single
configuration.**

The shipped default in `serve-qwen.bat` (`n-max 4 / p-min 0.75`) is 11 % off
the peak on IQ4_XS and 15 % off on Q4_K_M for this probe.

### Conditions (identical for all 14 rows)

* `-c 32768 -ngl 99 --parallel 1 --load-mode mmap -ctk q8_0 -ctv q8_0 --jinja`
* `--chat-template-kwargs "{\"enable_thinking\":false}"` — thinking **off**, so
  the 700 timed tokens are the deliverable code, not reasoning (the phase3d
  correction). Section 2 below measures what thinking-on does to these numbers,
  and it is large.
* `temperature 0`, `top_k 1`, `max_tokens 700`, prompt 149 tokens
* fresh server per configuration (the spec flags are load-time), plus a
  discarded 16-token warm-up request
* **two identical probes per server**; probe 2 re-uses the cached prefix for
  prefill and decodes the same 700 greedy tokens again, giving a clean repeat
  of the decode rate on the same token stream
* port 1235

### Probe (novel, not a textbook algorithm)

> Write a single self-contained Python module named tenant_ratelimit.py
> implementing a sliding-window rate limiter keyed by (tenant_id, endpoint).
> Requirements: window size and quota configurable per endpoint with per-tenant
> overrides supplied as a dict at construction; monotonic-clock based so
> wall-clock changes cannot be exploited; thread-safe under concurrent callers;
> amortised O(1) memory per key by evicting expired timestamps lazily; a
> decorator @limited(endpoint) that raises RateLimitExceeded carrying
> retry_after_seconds; and a structured JSON audit record emitted on every
> denial. Include a \_\_main\_\_ block that exercises burst, steady-state and
> per-tenant override behaviour. Code only, no explanation.

This deliberately replaces the red-black-tree prompt the published sweep used.
That prompt is a textbook algorithm with thousands of near-identical public
implementations, which inflates draft acceptance.

### UD-IQ4_XS, `-c 32768`, thinking off, 700 tokens

| config | decode t/s (probe 1 / probe 2) | mean | vs no-spec | acceptance | draft n / accepted | server VRAM (ded) |
|---|---|---|---|---|---|---|
| `--spec-type none` | 43.05 / 42.88 | **42.97** | 1.00x | — | — | 14,480 MiB |
| n-max 2, p-min 0.75 | 73.52 / 73.30 | **73.41** | 1.71x | **96.46 %** | 452 / 436 | 15,378 MiB |
| n-max 3, p-min 0.75 | 79.76 / 79.38 | **79.57** | 1.85x | 93.31 % | 523 / 488 | 15,528 MiB |
| n-max 4, p-min 0.75 *(shipped)* | 83.67 / 83.32 | **83.50** | 1.94x | 89.74 % | 575 / 516 | 15,678 MiB |
| n-max 6, p-min 0.5 | 88.11 / 87.45 | **87.78** | 2.04x | 75.84 % | 745 / 565 | 15,976 MiB |
| **n-max 10, p-min 0.5** | 92.51 / 95.21 | **93.86** | **2.18x** | 61.43 % | 949 / 583 | 16,576 MiB |
| n-max 10, p-min 0.75 | 89.64 / 92.03 | **90.84** | 2.11x | 76.80 % | 737 / 566 | 16,576 MiB |

### Q4_K_M, same conditions, same probe

| config | decode t/s (probe 1 / probe 2) | mean | vs no-spec | acceptance | draft n / accepted | server VRAM (ded) |
|---|---|---|---|---|---|---|
| `--spec-type none` | 40.04 / 39.93 | **39.99** | 1.00x | — | — | 16,842 MiB |
| n-max 2, p-min 0.75 | 66.16 / 65.35 | **65.76** | 1.64x | **96.70 %** | 455 / 440 | 17,656 MiB |
| n-max 3, p-min 0.75 | 67.00 / 66.48 | **66.74** | 1.67x | 94.15 % | 513 / 483 | 17,806 MiB |
| n-max 4, p-min 0.75 *(shipped)* | 69.44 / 70.20 | **69.82** | 1.75x | 88.64 % | 581 / 515 | 17,956 MiB |
| n-max 6, p-min 0.5 | 66.56 / 66.20 | **66.38** | 1.66x | 72.11 % | 771 / 556 | 18,254 MiB |
| **n-max 10, p-min 0.5** | 80.49 / 82.93 | **81.71** | **2.04x** | 60.00 % | 965 / 579 | 18,854 MiB |
| n-max 10, p-min 0.75 | 78.25 / 78.04 | **78.15** | 1.95x | 75.37 % | 751 / 566 | 18,854 MiB |

### What the pair shows

1. **Same winner, same loser, same shape.** `n10/p0.5` is fastest on both files;
   `n2/p0.75` is the slowest speculating config on both.
2. **Acceptance is a property of the MTP head, not of the quant.** At every
   configuration the two files land within 1.6 points of each other
   (96.46/96.70, 93.31/94.15, 89.74/88.64, 75.84/72.11, 61.43/60.00,
   76.80/75.37). The quant does not change how well the draft head predicts; it
   changes how fast the target model verifies.
3. **IQ4_XS wins everywhere, and wins more with a bigger drafter.** +7.5 % with
   no drafter (42.97 vs 39.99), +19.6 % at `n4/p0.75`, +14.9 % at `n10/p0.5`,
   +32.2 % at `n6/p0.5`.
4. **The one real difference in shape** is in the mid-range: IQ4_XS climbs
   monotonically from n2 to n6 (73.4 → 79.6 → 83.5 → 87.8) while Q4_K_M
   flattens and dips (65.8 → 66.7 → 69.8 → **66.4** at n6/p0.5). Q4_K_M's
   verify step is expensive enough that a wider, lower-acceptance draft tree
   stops paying at n6; IQ4_XS's is cheap enough that it keeps paying. A
   difference of degree in the same curve, not a different optimum.
5. **Acceptance rate is not the objective.** `n2/p0.75` has the highest
   acceptance of any config on either file (96.5 % / 96.7 %) and is the slowest
   speculating config on both. See §2 for why acceptance is actively misleading
   here.

### Cost of the wider tree

`n-max 10` costs **898 MiB** more resident VRAM than `n-max 4` on IQ4_XS
(16,576 vs 15,678 MiB) — exactly the campaign's existing figure. The increments
are linear at ~150 MiB per draft slot on top of a ~600 MiB fixed drafter cost;
Q4_K_M shows the same 898 MiB step (18,854 vs 17,956).

### Caveat

At `temp 0 / top_k 1`, speculative decoding is supposed to be output-exact.
Answer lengths nevertheless varied slightly between configs (IQ4_XS 2,919–2,939
chars; Q4_K_M 2,919–2,968). All configs within a quant produced the same
opening 120 characters, so the streams agree and diverge late. This is the
usual CUDA batch-shape-dependent reduction-order non-determinism, not a
correctness problem — but "identical output regardless of spec flags" is not
literally true on this build.

Raw: `data\followup\m1-mtp-resweep.txt`.

---

## 2. Projector-at-depth paired probe

**Answer: the vision projector costs nothing at depth. Zero. It is a pure
memory cost of 1,138 MiB and does not touch decode throughput at a
90,862-token context fill — proven twice, with the drafter off and with it on,
n = 8–10 probes per arm, arms differing by 0.04 % and 0.09 %.**

**The 30.61 vs 35.81 loose end is not the projector. `phase5`'s 35.81
reproduces exactly (36.62 here under a controlled protocol); `phase4c`'s 30.61
is ~16 % low, which sits inside the post-prefill clock-state band measured
below (a fixed configuration reads anywhere from 18.27 to 26.60 t/s on that
probe).**

### The loose end being settled

phase4c read **30.61 t/s** at 90,885 tokens with `--mmproj` loaded; phase5 read
**35.81 t/s** at 92,679 tokens without it, on otherwise-identical flags. A
~15 % deep-decode cost for having the projector loaded would have been a real
finding, but it rested on one probe per arm from two different scripts at two
different depths.

### Attempt 1 (`followup-m2.ps1`) — the pair does not survive replication

Same prompt in both arms, `--spec-type none`, ABAB order, 2 decode samples per
load, **no cooldown**:

| arm | rep | depth | decode t/s (probe 1 / probe 2) |
|---|---|---|---|
| WITH-mmproj | 1 | 90,862 | 26.73 / 26.47 |
| NO-mmproj | 1 | 90,862 | 19.43 / 23.87 |
| WITH-mmproj | 2 | 90,862 | 18.97 / 24.88 |
| NO-mmproj | 2 | 90,862 | 18.52 / 24.51 |

Spread **inside** each arm (18.97–26.73 for WITH) dwarfs the effect being
tested, and the arm means would have said the projector makes decode *faster*.
The pattern was diagnostic: the probe fired immediately after the 105 s prefill
was always the slowest of its load.

### Attempt 2 (`followup-m2b.ps1`) — noise-controlled, drafter OFF

Changes: the post-prefill probe is **recorded but excluded**; a **45 s
cooldown** puts every measured probe in the same clock state; **5 measured
probes** per load; **ABBA** ordering; `nvidia-smi` sampled before each probe.

Conditions: UD-IQ4_XS, `-c 131072 -ngl 99 --parallel 1 --load-mode mmap
-ctk q8_0 -ctv q8_0 --spec-type none --jinja`, thinking off, `temp 0`,
`top_k 1`, `max_tokens 400`. Prompt: fixed nonce + 1,275 filler notes (seed 3,
the same generator phase4c and phase5 used) + the red-black-tree task —
**byte-identical text in both arms**, giving `depth_tok = 90,862` in all four
loads. The only difference between arms is
`--mmproj <path> --image-min-tokens 1024`.

| arm | rep | depth | median t/s | mean t/s | min | max | n | server VRAM (ded) | shared |
|---|---|---|---|---|---|---|---|---|---|
| WITH-mmproj | 3 | 90,862 | **26.95** | 26.99 | 26.88 | 27.18 | 5 | 19,376 MiB | 228 MiB |
| NO-mmproj | 3 | 90,862 | **26.95** | 26.99 | 26.85 | 27.19 | 5 | 18,238 MiB | 228 MiB |
| NO-mmproj | 4 | 90,862 | **26.88** | 26.96 | 26.85 | 27.19 | 5 | 18,238 MiB | 228 MiB |
| WITH-mmproj | 4 | 90,862 | **26.92** | 26.94 | 26.79 | 27.16 | 5 | 19,376 MiB | 228 MiB |

**Pooled: WITH-mmproj 26.965 t/s (n=10), NO-mmproj 26.975 t/s (n=10) —
difference 0.01 t/s = 0.04 %, against a within-arm spread of 0.4 %.**

Both arms fully resident: shared usage stays at 228 MiB (the desktop's own
share) in every load. Projector cost = **19,376 − 18,238 = 1,138 MiB**, matching
the campaign's figure exactly.

### Attempt 3 (`followup-m2c.ps1`) — same pair with the MTP drafter ON

Identical protocol, plus `--spec-type draft-mtp --spec-draft-n-max 4
--spec-draft-p-min 0.75` (the exact flags phase4c and phase5 used), 4 measured
probes per load:

| arm | rep | depth | median t/s | mean t/s | min | max | n | server VRAM (ded) |
|---|---|---|---|---|---|---|---|---|
| WITH-mmproj | 1 | 90,862 | **62.86** | 62.66 | 62.11 | 63.17 | 4 | 21,034 MiB |
| NO-mmproj | 1 | 90,862 | **62.77** | 62.58 | 61.93 | 63.10 | 4 | 19,896 MiB |
| NO-mmproj | 2 | 90,862 | **62.95** | 62.73 | 62.15 | 63.25 | 4 | 19,896 MiB |
| WITH-mmproj | 2 | 90,862 | **62.99** | 62.76 | 62.23 | 63.18 | 4 | 21,034 MiB |

**Pooled: WITH-mmproj 62.71 t/s (n=8), NO-mmproj 62.655 t/s (n=8) — difference
0.055 t/s = 0.09 %.** Draft acceptance matched probe-for-probe between arms
(0.8958, 0.8860, 0.9021, 0.8860 in both). Projector cost again exactly
**21,034 − 19,896 = 1,138 MiB**.

### What actually caused the spread

The excluded post-prefill probes are the evidence. On **identical**
configurations, the probe fired right after the ~105 s prefill read:

| load | arm | post-prefill decode t/s | GPU before prefill (°C / SM MHz / W) | GPU after |
|---|---|---|---|---|
| m2b rep3 | WITH-mmproj (no drafter) | **26.60** | 56 / 225 / 34 | 82 / 1455 / 331 |
| m2b rep3 | NO-mmproj (no drafter) | **18.82** | 66 / 435 / 131 | 78 / 990 / 271 |
| m2b rep4 | NO-mmproj (no drafter) | **19.21** | 66 / 375 / 136 | 77 / 900 / 254 |
| m2b rep4 | WITH-mmproj (no drafter) | **18.27** | 63 / 315 / 62 | 77 / 960 / 265 |

That is a **45 % swing (18.27 → 26.60) across four runs of one configuration**,
driven by what state the card was in when the job started. The first load of a
session begins on a genuinely idle card (56 °C, 225 MHz, 34 W) and the prefill
reaches a 1,455 MHz boost; every later load begins while the card is still
winding down from the previous server's teardown and model load (63–66 °C,
315–435 MHz, 62–136 W drawn at 1 % utilisation) and the prefill only reaches
900–990 MHz. With the drafter on the same effect is milder but present
(post-prefill 54.33–59.96 against a settled 62.7).

This is **not** steady-state thermal throttling. Once settled, decode is nearly
temperature-insensitive: within a cooled load the five probes run 57 °C → 82 °C
and decode moves only 27.18 → 26.90 (−1.0 %). The damage is confined to the
boost-clock ramp during and just after a long prefill.

### Cross-check: the depth ladder, re-measured (`followup-m2d.ps1`)

One server load, UD-IQ4_XS, `-c 131072`, n4/p0.75, no projector, thinking off,
cooled-probe protocol (post-prefill probe discarded, 30 s cooldown, 3 probes):

| depth (tok) | prefill t/s | median decode t/s | mean | min–max | acceptance | discarded post-prefill probe |
|---|---|---|---|---|---|---|
| 1,458 | 949.6 | **86.30** | 86.44 | 86.26–86.75 | 0.8925 | 86.23 |
| 28,388 | 1,115.5 | **80.20** | 80.32 | 80.11–80.65 | 0.9266 | 79.79 |
| 90,854 | 828.0 | **64.76** | 64.52 | 63.99–64.82 | 0.9242 | 59.61 |

Decode falls 86.3 → 64.8 t/s (−25 %) from 1.5k to 91k. The *shape* the campaign
published is confirmed; the *levels* are much higher than phase5's ladder
because phase5 timed thinking tokens — see next.

### The real lever, and the surprise (`followup-m2e.ps1`, `followup-m2f.ps1`)

phase5's ladder (thinking ON) sits a near-constant ~1.7x below the m2d ladder
(thinking OFF): 51.15/86.30 = 1.69, 47.07/80.20 = 1.70, 35.81/64.76 = 1.81.
That constant ratio is not clock noise. M2e isolates it — same server, same
90,854/90,894-token prompt, same n4/p0.75, cooled probes, the only change being
the chat template:

| arm | depth | median t/s | mean | min–max | acceptance | **mean draft len** |
|---|---|---|---|---|---|---|
| thinking **ON** (`--reasoning-preserve`) | 90,894 | **36.62** | 36.63 | 36.52–36.75 | 0.8951 | **2.99** |
| thinking **OFF** | 90,854 | **62.02** | 62.08 | 62.00–62.21 | 0.9073 | **4.31** |

**1.69x, from the token stream alone — and acceptance says nothing about it
(0.895 vs 0.907).** The mechanism is in the last column: with
`--spec-draft-p-min 0.75`, the confidence gate truncates the draft tree to a
mean of 2.99 tokens on the reasoning stream versus 4.31 on the answer stream.
Acceptance stays high *because* the gate is throwing away the uncertain part.
**Acceptance rate is therefore blind to the loss; mean draft length is the
metric that predicts throughput.** This also explains §1's result that the
highest-acceptance config (`n2/p0.75`, 96.5 %) is the slowest.

M2f then asks whether a wider tree with a lower gate recovers it, at the same
depth with thinking ON:

| config (thinking ON, 90,894 tok) | median t/s | mean | min–max | acceptance | mean draft len | vs no-spec |
|---|---|---|---|---|---|---|
| `--spec-type none` | **27.01** | 27.04 | 26.97–27.15 | — | — | 1.00x |
| n-max 4, p-min 0.75 *(shipped)* | **36.62** | 36.63 | 36.52–36.75 | 0.8951 | 2.99 | 1.36x |
| n-max 10, p-min 0.5 | **38.67** | 38.77 | 38.33–39.31 | 0.51–0.62 | 3.22 | 1.43x |

Only partly. `n10/p0.5` beats the shipped flags by 5.6 % on the thinking
stream — the same direction as §1 but a much smaller margin than the 12 % it
wins by on code.

Note the no-drafter floor: **27.01 t/s with thinking on vs 26.95 with thinking
off** — identical, confirming again that all content dependence is a
speculation effect.

### Practical consequence

At ~91k depth on UD-IQ4_XS with `-c 131072` and q8_0 KV, what a user actually
gets depends far more on whether the model is thinking than on any flag:

| what is being decoded | no drafter | n4/p0.75 | n10/p0.5 |
|---|---|---|---|
| answer / code tokens | 26.95 | **62.7** | ~70 (phase5b: 70.09) |
| reasoning tokens (the shipped xhigh default) | 27.01 | **36.6** | **38.7** |

Anyone running the shipped `xhigh` default over a 91k document should expect
**~37–39 t/s**, not the 62–70 the code-probe numbers advertise.

### Methodological consequence for the campaign

A single decode probe taken immediately after a multi-minute prefill on this
machine carries roughly ±25 % of clock-state noise. phase4c, phase5 and phase5b
are all built from such probes. Their *shape* is robust and independently
confirmed here; individual *levels* should not be compared across scripts to
better than about 25 %. phase5's 35.81 reproduces well (36.62); phase4c's 30.61
does not (16 % low) and should be treated as the noisy one. The fix is cheap
and is implemented in `followup-m2b.ps1`: discard the post-prefill probe, cool
45 s, take several probes from the cached prefix.

Raw: `data\followup\m2-projector-depth.txt`, `m2b-projector-depth.txt`,
`m2c-projector-depth-spec.txt`, `m2d-depth-ladder-cooled.txt`,
`m2e-thinking-on-at-depth.txt`, `m2f-thinking-spec-flags.txt`.

---

## 3. q4_0 K/V-cache perplexity check

**Answer: q4_0 KV costs +0.69 % perplexity against the fp16 baseline — about
2.2x the damage q8_0 does (+0.31 %), for halving the cache again. A real but
small cost, and still smaller than the gap between the model quants
themselves.**

### Conditions

Flags byte-identical to the campaign's phase6 KV series, so the number drops
straight into the existing table:

```
llama-perplexity.exe -m Qwen3.8-27B-UD-IQ4_XS.gguf \
    -f wikitext-2-raw-test.raw \
    -ngl 99 -c 8192 -fa on --load-mode mmap \
    -ctk q4_0 -ctv q4_0
```

* corpus `E:\AI\measured-inference\corpora\wikitext-2-raw-test.raw`,
  1,290,590 bytes, SHA256
  `173C87A53759E0201F33E0CCF978E510C2042D7F2CB78229D9A50D79B9E7DD08` —
  **verified byte-identical** to the `E:\AI\aider\qwen\wiki.test.raw` the fp16
  and q8_0 baselines used, so the three figures are directly comparable
* 36 chunks at `n_ctx=8192`, batch 2048, single sequence
* run detached via `Start-Process`, log polled to completion

### Result

| K/V cache | PPL | ± | vs fp16 | vs q8_0 | wall |
|---|---|---|---|---|---|
| `-ctk f16 -ctv f16` | **6.5956** | 0.04453 | — | — | ~295 s |
| `-ctk q8_0 -ctv q8_0` *(what the recipes ship)* | **6.6160** | 0.04483 | **+0.309 %** | — | 298.3 s |
| `-ctk q4_0 -ctv q4_0` *(this run)* | **6.6413** | 0.04507 | **+0.693 %** | **+0.383 %** | **266.3 s** |

Final chunk trace: `[34]6.4088, [35]6.6363, [36]6.6413`.

### Reading

* **Degradation is super-linear in bits.** fp16 → q8_0 (halving the cache)
  costs 0.31 %; q8_0 → q4_0 (halving it again) costs a further 0.38 % — slightly
  more than the first halving.
* **Both are small next to the model quantisation.** The Q4_K_M ↔ UD-IQ4_XS gap
  on this same corpus is 6.535 vs 6.596 = 0.93 %, larger than q4_0 KV's entire
  penalty. Anyone who accepted IQ4_XS over Q4_K_M on quality grounds has already
  accepted a bigger hit than moving to q4_0 KV would add.
* **The error bars overlap.** ±0.045 on each estimate means the fp16 → q4_0
  difference (0.0457) is right at one standard error. The direction is
  consistent with the q8_0 point and with theory, but a single 36-chunk run
  does not resolve it on its own.
* q4_0 KV was **not faster** in any way that matters — the 266 s vs 298 s wall
  difference is a bandwidth effect on a perplexity-shaped workload, not a decode
  result.
* **No reason to change the default.** q8_0 already buys the context ceilings
  the campaign published. q4_0 would extend them further at 0.69 %; whether that
  trade is worth taking depends on the window needed, and nothing here argues
  for it by itself.

Raw: `data\followup\m3-ppl-kv-q4_0.log`, `data\followup\m3-ppl-kv-q4_0.txt`.

---

## 4. Repetition spot-check on the long greedy transcripts (no GPU)

**Answer: 10 of 10 transcripts are clean. No degenerate repetition loops
anywhere — no immediate n-gram cycling, no repeated line blocks, no tail
spirals. One file is incomplete, but from a token-budget cut, not a loop.**

### Method

`data\followup\m4-repcheck.py` (kept with the results). Four independent
lexical tests plus manual adjudication of every flag:

1. **immediate loop** — the same k-word block (k = 3…60) repeated back-to-back
   3+ times; the classic greedy death spiral
2. **tail n-gram** — any 16-word block from the last 20 % of the file occurring
   4+ times with occurrences clustered in the tail
3. **global repeat** — any 16-word block occurring 3+ times anywhere
4. **line loop** — identical non-trivial lines repeated back-to-back
5. plus a duplicate-sentence scan over the `THINKING` section, to catch
   deliberation that re-treads rather than progresses

Raw output: `data\followup\m4-repetition-scan.txt`.

### Per-file verdict

| file | words | think / answer words | verdict |
|---|---|---|---|
| `E:\AI\aider\qwen\Qwen3.8-27B-Q4_K_M - low.txt` | 8,733 | 7,742 / 985 | **clean** |
| `E:\AI\aider\qwen\Qwen3.8-27B-Q4_K_M - low - pass2.txt` | 6,059 | 248 / 5,805 | **clean** |
| `E:\AI\aider\qwen\Qwen3.8-27B-Q4_K_M - medium.txt` | 7,796 | 1,577 / 6,213 | **clean** |
| `E:\AI\aider\qwen\Qwen3.8-27B-Q4_K_M - medium - pass2.txt` | 8,819 | 1,603 / 7,210 | **clean** |
| `E:\AI\aider\qwen\Qwen3.8-27B-Q4_K_M - xhigh.txt` | 26,429 | 18,219 / 8,204 | **clean** |
| `E:\AI\aider\qwen\Qwen3.8-27B-Q4_K_M - xhigh - pass2.txt` | 23,484 | 17,130 / 6,348 | **clean** (one flag, adjudicated false positive) |
| `...\qwen38-27b-blind\data\effort-low.txt` | 6,394 | 751 / 5,637 | **clean** |
| `...\qwen38-27b-blind\data\effort-medium.txt` | 9,494 | 2,943 / 6,545 | **clean** |
| `...\qwen38-27b-blind\data\effort-xhigh.txt` | 20,318 | 19,197 / 1,115 | **clean but TRUNCATED** |
| `...\qwen38-27b-blind\data\effort-xhigh-120k.txt` | 16,065 | 13,422 / 2,637 | **clean** |

Nine of the ten end correctly on `</html>`.

### The one detector flag, adjudicated

`Qwen3.8-27B-Q4_K_M - xhigh - pass2.txt`, three 16-word blocks at words 19,483 /
19,515 / 19,547 — exactly 32 words apart. Reading the region: it is the body of
`nearFish()`, three sequential `for` loops over three **different** arrays
(`S.trop`, `S.ang`, `S.clowns`) running the same nearest-neighbour test.
Deliberate hand-unrolled code, correct. **False positive; the file is clean.**

### The one incomplete file

`effort-xhigh.txt` ends mid-token — `if (c.x === 0){ c.x = A.an`. This is **not**
a repetition loop. Per `data\phase7.txt` the generation hit `finish=length` at
`predicted_n=65536` (the cap), with `think_chars=160919`, `answer_chars=8557`,
`html_ok=False`. Sampling its reasoning at 55 %, 80 % and 97 % of its length
shows monotonically productive work — lobster gait and blink animation, then
layout anchors and clamps, then jellyfish/turtle/bubble update functions — with
no re-tread between samples. The model ran out of budget while drafting an
unusually detailed page. The rerun at a larger window
(`effort-xhigh-120k.txt`, phase7b) finished with `finish=stop`, `html_ok=True`.

### Duplicate thinking sentences (all benign)

* `Qwen3.8-27B-Q4_K_M - low.txt`: 1 sentence twice — "OK, I'm going to write the
  complete code now.", later followed by "OK, now I'm really writing the final
  code." Deliberation restart, not a loop.
* `Qwen3.8-27B-Q4_K_M - xhigh - pass2.txt`: 7 sentences twice, all short JS
  snippets drafted, revised, then restated before committing (frame loop, `dt`
  handling, bubble spawn multiplier). Each appears exactly twice, far apart.
* All eight other files: zero duplicate thinking sentences.

**Greedy decoding at `temp 0 / top_k 1` showed no degeneracy in ~133,000 words
of generation across three reasoning efforts and two passes.**

---

## Summary of every number produced

| # | measurement | headline |
|---|---|---|
| 1 | MTP re-sweep, IQ4_XS vs Q4_K_M, novel code | both peak at `n10/p0.5`; IQ4_XS 93.86 t/s (2.18x), Q4_K_M 81.71 t/s (2.04x); shipped `n4/p0.75` is 11 % / 15 % off the peak |
| 2 | projector at 90,862-token depth | drafter off: WITH 26.965 vs NO 26.975 t/s (0.04 % apart, n=10 each). drafter on: WITH 62.71 vs NO 62.655 t/s (0.09 % apart, n=8 each). Projector = 1,138 MiB, 0 % decode |
| 2b | thinking on vs off at 91k depth | 36.62 vs 62.02 t/s — **1.69x** — at nearly identical acceptance (0.895 vs 0.907); mean draft length 2.99 vs 4.31 |
| 3 | q4_0 KV perplexity | 6.6413 ± 0.04507 = **+0.693 %** vs fp16 6.5956, **+0.383 %** vs q8_0 6.6160 |
| 4 | repetition spot-check | 10/10 clean; 1 truncated by token budget (`effort-xhigh.txt`) |

### Corrections to standing numbers

* The `+0.23 %` figure for q8_0 KV that circulates in the session notes is
  stale. Recomputed from `data\ppl-kv-f16.log` and `data\ppl-kv-q8.log`:
  (6.6160 − 6.5956) / 6.5956 = **+0.309 %**. `campaign.md` already says +0.31 %.
* The 30.61 vs 35.81 t/s projector "loose end" is resolved: not a projector
  cost. phase5's 35.81 reproduces (36.62 controlled); phase4c's 30.61 is the
  noisy one.
* Deep-decode figures quoted for a *coding* workload (62–70 t/s at 91k) do not
  apply to the shipped `xhigh` default, which decodes reasoning tokens at
  **36.6–38.7 t/s** at the same depth.

### Harness notes for whoever runs the next batch

* **Never name a variable `$base` in a script that dot-sources `lib.ps1`.**
  PowerShell variable names are case-insensitive, so `$base` silently
  overwrites `$script:BASE` (the server URL) and `Start-Srv`'s health poll then
  requests `-c 131072 ... /health` forever, in a `try {} catch {}` that hides
  it. Cost one wedged 10-minute run. `followup-m2e.ps1` carries the warning.
* Foreground-to-background handoff of a long `powershell.exe ... *> log` call
  loses output flushing. Launch long runs detached with `Start-Process` and
  `-RedirectStandardOutput`, and poll the script's own `Write-Row` file (which
  uses `Add-Content` and flushes) rather than the console log.
* `Get-Counter '\GPU Process Memory(*)\...'` is fine on this machine (1.2 s) and
  is the only way to get llama-server's dedicated/shared split, since Windows
  `nvidia-smi` is per-process blind.

### Housekeeping

No git commit made. No report or guide edited. `llama-server` and
`llama-perplexity` both confirmed stopped; GPU returned to 950 MiB idle with no
llama processes.
