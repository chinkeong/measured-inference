# Energy joins — E0 and E8a

Two zero-GPU analyses from the campaign's power gap map, computed **entirely
from logs already on disk**. No server was started, no logger was started, no
`nvidia-smi` was run. A power matrix was occupying the card throughout.

**Tooling.** Every joule below comes from `scripts/power/attribute-power.py`
(trapezoid on `power.draw`, edges linearly interpolated, `--max-gap 2.0 s`),
either through its CLI or by importing its `load_power` / `PowerSeries` /
`integrate` directly so no integrator was re-implemented. `--selftest` was run
first and **passed all 7 groups / 27 assertions** (2026-08-23).

---

## 0. Instrumentation tier — applies to every number in this file

> **In-band GPU board power (NVML, `nvidia-smi --query-gpu=power.draw`).**
> Inside the number: GPU die, VRAM, VRM losses, board fans.
> **Excluded and unmeasured on this machine:** PSU conversion loss, CPU, system
> RAM, drives, chassis fans, display, platform idle draw, datacentre PUE.
> Never call any figure here "system power" or "wall power", and never divide an
> electricity bill by it. A 3090 board drawing 344 W pulls meaningfully more than
> 344 W at the wall; nobody has measured how much more on this box.

**Token regime.** Both analyses are **mixed-regime**: reasoning/thinking tokens
and answer tokens are generated in one stream and both are inside every timed
window. `predicted_n` counts thinking + answer together. No number here is an
answer-token-only figure, and none may be quoted as one.

---

# E0 — per-request join for the rule-21 cap-32k effort sweep

## E0.0 Inputs and how the clocks were tied together

| input | file | notes |
|---|---|---|
| power | `data/power/rule21-power.csv` | 17,715 usable rows, 2026-08-23 **10:48:19.961 → 13:19:37.436** (9,077.5 s) |
| cadence | — | mean **0.512 s**, median 0.514, max **0.657 s**, **zero** gaps > 2 s → the 2 s gap cap never engaged, coverage 100.0 % everywhere the log runs |
| columns | — | `timestamp, power.draw, power.draw.instant, clocks.sm, clocks.mem, util.gpu, util.mem, mem.used, mem.reserved, temp, pstate` |
| requests | `data/rule21/arm-{xhigh,medium,low}-cap32k-llama-server.log` | 150 parent tasks (`is_child = 0`), each with `launch_slot_` (start), `prompt eval time = X ms / P tokens`, `eval time = Y ms / M tokens`, `release` |

**Anchoring.** `wall(event) = server_start + relative_stamp`, with
`server_start = log mtime − last relative stamp` (stamps are
`minutes.seconds.millis.micros`). Verified three independent ways:

| arm | recovered server start | arm log `started :` | Δ | power CSV's own transition | Δ |
|---|---|---|---|---|---|
| xhigh-cap32k | **09:55:45.260** | 09:55:44 | +1.26 s | `mem.used` 17000→1253 at 12:19:26.583 vs last release 12:19:26.182 | +0.40 s |
| medium-cap32k | **12:20:02.959** | 12:20:02 | +0.96 s | P8→P2 + clocks 210→1725 MHz at 12:20:03.464 | +0.51 s |
| low-cap32k | **12:52:17.090** | 12:52:16 | +1.09 s | P8→P2 at 12:52:17.495 | +0.41 s |

The xhigh anchor of **09:55:45.260** agrees with the independently recorded
llama-server PID start of 09:55:45.252 to **8 ms**. Every arm's *end* is
confirmed by the CSV's model-unload signature (`mem.used` collapse + pstate
drop) inside 0.4–0.7 s. Anchors are sound.

**Join verified downstream too.** Per-arm mean answer length and unweighted
decode t/s recomputed from the joined events reproduce the harness's own result
JSONs exactly (e.g. xhigh/MBPP mean 5084.2 tok, 41.25 vs 41.14 t/s;
medium/MBPP 1629.4 tok; low/MATH-500 2143.2 tok). Zero token mismatches across
all 150 requests between driver log and server log.

## E0.1 Conditions that travel with these numbers

Authoritative source: the arms' own result JSONs (`/settings`, `/backend`).

* Model `Qwen3.8-27B-UD-IQ4_XS.gguf`, llama.cpp build 10502 (`0adcc3bb5`), RTX 3090, driver 596.36.
* `-c 65536`, `-ctk q8_0 -ctv q8_0`, `--chat-template-kwargs {"reasoning_effort":"<level>"}`.
* **Speculative decoding OFF** (`"speculative": false`; the server log reports the
  `blk.64.nextn.*` MTP tensors as *"unused … ignoring"*). Decode lands at
  **38.4–40.2 t/s**, the drafter-off rate.
* Sampling **greedy**: temperature 0.0, top_p 1.0, top_k 1, presence_penalty 0.0, seed 42.
* `max_tokens` 32,768, `max_prompt_tokens` 8,192, n = 25 per dataset.
* Single slot (`n_slots = 1`), no batching, no prompt-cache reuse across datasets.
* Mixed regime (thinking + answer both timed and both counted).

## E0.2 Coverage map — which arms the power log actually reaches

| arm | wall window | vs power log | verdict |
|---|---|---|---|
| `arm-low` (16k cap, 7 datasets) | 04:40:43 → 05:40:30 (3,587.5 s) | ends 5 h 8 m before the log starts | **UNCOVERED — no power data exists** |
| `arm-medium` (16k cap, 7 datasets) | 05:44:51 → 07:13:01 (5,289.7 s) | ends 3 h 35 m before | **UNCOVERED — no power data exists** |
| `arm-xhigh` (16k cap, 7 datasets) | 07:13:22 → 09:55:20 (9,717.2 s) | ends 53 m before | **UNCOVERED — no power data exists** |
| `arm-xhigh-cap32k` | 09:55:45 → 12:19:26 (8,620.9 s) | log starts 3,154.7 s in | **PARTIAL — tail only, 63.4 % of the arm** |
| `arm-medium-cap32k` | 12:20:03 → 12:51:41 (1,897.9 s) | inside | **FULL** |
| `arm-low-cap32k` | 12:52:17 → 13:15:01 (1,364.1 s) | inside | **FULL** |
| trailing idle | 13:15:01 → 13:19:37 (276.2 s) | inside | **FULL** (see E0.8, contaminated) |

Per-benchmark coverage, and this is the answer to "where covered":

| dataset | in suite | covered by power log |
|---|---|---|
| MATH-500 | yes | **low-cap32k only** (xhigh-cap32k's MATH-500 ran 09:55:52 → 10:28:05, entirely before the log started at 10:48:19.961) |
| HumanEval | yes | xhigh-cap32k **15 of 25** (prompts 11–25; its HumanEval block ran 10:28:05 → 11:24:40 and the log opens mid-prompt-10), medium-cap32k all 25 |
| MBPP | yes | xhigh-cap32k all 25, medium-cap32k all 25 |
| GSM8K | yes | **none** — only ever ran in the uncovered 16k arms |
| ALPACA | yes | **none** — same |
| MeetingBank | yes | **none** — same |
| MT-Bench | yes | **none** — same |

The cap-32k reruns were narrowed by `--datasets` to the cells that had
truncated at 16k, so GSM8K / ALPACA / MeetingBank / MT-Bench have **zero**
energy data at any cap. Nothing may be published about their energy.

**Partial-coverage discipline.** Only requests whose *entire*
`[t_launch, t_launch+prompt_ms+predicted_ms]` window lies inside the log are
counted (115 of 150). Mixing a full token count with a partial energy window is
the single easiest way to fabricate an efficiency win here — done naively it
reported xhigh/HumanEval at 5.32 J/token and 59.8 decode t/s, both physically
impossible for a drafter-off 3090. The corrected figures are below.

## E0.3 Per-request phase attribution, aggregated per (arm, benchmark)

Fully-covered requests only. `prefill = [t_launch, +prompt_ms]`,
`decode = [+prompt_ms, +predicted_ms]`, from the server's own timings — so
there is **no client-side `t_start` bias to correct** (`--lead-ms` is not
needed; the join point is the server's `launch_slot_`, not an HTTP stamp).

| arm | benchmark | n / N | decode tok | prompt tok | J_decode | J_prefill | **J/decode-tok** | J/prompt-tok | decode t/s | mean W (decode) | tokens/kWh | EDP (J·s) | Wh (suite) | Wh/answer |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| xhigh-cap32k | MATH-500 | 0 / 25 | — | — | — | — | — | — | — | — | — | — | — | — |
| xhigh-cap32k | HumanEval | 15 / 25 | 83,458 | 2,640 | 685,550 | 1,334 | **8.214** | 0.5052 | 38.67 | 317.6 | 438,260 | 2.77e7 | 190.80 | 12.72 |
| xhigh-cap32k | MBPP | 25 / 25 | 127,106 | 2,065 | 1,006,835 | 1,629 | **7.921** | 0.7887 | 38.81 | 307.4 | 454,475 | 1.97e7 | 280.13 | 11.21 |
| medium-cap32k | HumanEval | 25 / 25 | 34,519 | 4,017 | 267,094 | 1,629 | **7.738** | 0.4055 | 40.23 | 311.3 | 465,261 | 2.46e6 | 74.65 | 2.99 |
| medium-cap32k | MBPP | 25 / 25 | 40,734 | 2,065 | 323,721 | 1,325 | **7.947** | 0.6415 | 40.11 | 318.8 | 452,989 | 2.66e6 | 90.29 | 3.61 |
| low-cap32k | MATH-500 | 25 / 25 | 53,579 | 2,652 | 449,234 | 2,099 | **8.385** | 0.7917 | 39.95 | 335.0 | 429,363 | 6.26e6 | 125.37 | 5.02 |

*Wh (suite)* = prefill + decode energy of the covered requests only.
*EDP* = mean over requests of `J_decode × decode_seconds`.
Prefill windows are 0.14–0.45 s — **shorter than the 0.512 s sample period**, so
`J_prefill` (and therefore J/prompt-token) is **interpolated, not sampled**.
Treat J/prompt-token as order-of-magnitude only; it is reported because it
proves the asymmetry (prefill 0.4–0.8 J/token vs decode ~8), not because a
4th significant figure is real.

## E0.4 J/decode-token distribution across requests

| arm | benchmark | n | min | p10 | p25 | median | p75 | p90 | max | mean ± sd |
|---|---|---|---|---|---|---|---|---|---|---|
| xhigh-cap32k | HumanEval | 15 | 7.521 | 7.664 | 7.836 | 7.912 | 8.106 | 8.285 | 8.432 | 7.971 ± 0.244 |
| xhigh-cap32k | MBPP | 25 | 7.140 | 7.420 | 7.505 | 7.803 | 7.967 | 8.070 | 8.238 | 7.743 ± 0.280 |
| medium-cap32k | HumanEval | 25 | 7.448 | 7.501 | 7.543 | 7.616 | 7.754 | 8.097 | 8.144 | 7.686 ± 0.207 |
| medium-cap32k | MBPP | 25 | 7.148 | 7.575 | 7.631 | 7.844 | 8.099 | 8.215 | 8.324 | 7.868 ± 0.289 |
| low-cap32k | MATH-500 | 25 | 7.807 | 7.962 | 8.082 | 8.170 | 8.323 | 8.399 | 8.632 | 8.186 ± 0.193 |
| **xhigh-cap32k** | pooled | 40 | 7.140 | 7.485 | 7.656 | 7.864 | 8.036 | 8.140 | 8.432 | **7.829 ± 0.289** |
| **medium-cap32k** | pooled | 50 | 7.148 | 7.531 | 7.574 | 7.705 | 8.057 | 8.148 | 8.324 | **7.777 ± 0.267** |
| **low-cap32k** | pooled | 25 | 7.807 | 7.962 | 8.082 | 8.170 | 8.323 | 8.399 | 8.632 | **8.186 ± 0.193** |
| **all arms** | pooled | **115** | 7.140 | 7.518 | 7.632 | **7.908** | 8.112 | 8.292 | 8.632 | **7.884 ± 0.307** |

The whole distribution spans **7.14 → 8.63 J/token**, a ±9 % band, with no
tail. Answer length barely matters: answers < 1,000 tokens average 7.849 J/tok,
answers ≥ 1,000 tokens 7.947 J/tok (n = 74 / 41) — deeper KV costs ~1 %.

**Effort level does not change J/token.** The cleanest comparison is the same
benchmark at two efforts: MBPP at xhigh = 7.921 J/tok, MBPP at medium = 7.947
J/tok — 0.3 % apart while the answers differ 3.1× in length (5,084 vs 1,629
mean tokens). Effort changes **J per answer** (11.21 vs 3.61 Wh), not J per
token. The residual arm-to-arm spread (7.69–8.19) is board clock drift, not
effort — see E0.7.

**Clock-ramp check.** J/token of each arm's first *covered* request against the
rest of that arm: low **−5.0 %** (7.968 vs 8.388), medium **−1.0 %** (7.772 vs
7.852), xhigh **+2.1 %** — and xhigh's row is not a true first request (the log
opens mid-arm), so only low and medium speak to the ramp. Both are negative,
i.e. request 1 reads *better* than it should, exactly as the README predicts.
The ramp penalty is small here because ~10 s of model loading at 125–155 W
warms the board before request 1. `--drop-first` changes nothing material;
the pooled figure is quoted **without** it and that is stated.

## E0.5 Arm-level energy (whole arm, including inter-request time)

| arm | integrated window | wall s | cov % | mean W | peak W | **Wh gross** | Wh net (−31 W) | status |
|---|---|---|---|---|---|---|---|---|
| xhigh-cap32k | 10:48:19.961 → 12:19:26.182 | 5,466.2 | 100.0 | 311.6 | 350.4 | **473.09** | 426.02 | **PARTIAL** — 3,154.7 s (36.6 %) ran before the logger |
| medium-cap32k | 12:20:02.959 → 12:51:40.847 | 1,897.9 | 100.0 | 314.6 | 350.3 | **165.87** | 149.52 | FULL |
| low-cap32k | 12:52:17.090 → 13:15:01.202 | 1,364.1 | 100.0 | 333.1 | 351.4 | **126.22** | 114.47 | FULL |

Whole log span: 9,077.5 s, mean 305.1 W, **769.40 Wh** total board energy
across the covered window. Budget: 765.17 Wh under load (99.45 %), 1.21 Wh in
the two between-arm gaps (0.16 %), 3.02 Wh trailing idle (0.39 %).

**xhigh-cap32k full-arm figure is an ESTIMATE, not a measurement.** Crediting
the uncovered 3,154.7 s head at the arm-tail mean (311.6 W) through the first
covered 10-minute mean (331.7 W) brackets it at **746–764 Wh** for the full
2 h 24 m arm. Publish it only with that bracket and the word *estimated*.

## E0.6 Inter-request power (scoring / code execution)

Between `release` of one request and `launch_slot_` of the next, within an arm:

| arm | benchmark | n gaps | total s | mean s | mean W | J total |
|---|---|---|---|---|---|---|
| xhigh-cap32k | HumanEval | 15 | 3.3 | 0.22 | 320.5 | 1,060 |
| xhigh-cap32k | MBPP | 25 | 5.9 | 0.24 | 312.5 | 1,850 |
| medium-cap32k | HumanEval | 24 | 3.5 | 0.15 | 317.2 | 1,112 |
| medium-cap32k | MBPP | 25 | 4.6 | 0.18 | 316.2 | 1,455 |
| low-cap32k | MATH-500 | 24 | 5.8 | 0.24 | 335.8 | 1,947 |

Two findings. (1) **Scoring is energetically free**: 5.8–9.2 s per arm,
0.04–0.14 % of arm energy, even though HumanEval and MBPP *execute generated
code* between prompts. Grading is CPU-side and sub-second. (2) The board does
**not** drop clocks in a 0.2 s gap — it still reads 312–336 W, i.e. full load
power. Any "idle between requests" saving at this cadence is zero.

Between *arms* (server teardown + next server's model load + report render):

| gap | span | s | mean W | Wh |
|---|---|---|---|---|
| xhigh → medium | 12:19:26 → 12:20:03 | 36.8 | 49.0 | 0.500 |
| medium → low | 12:51:41 → 12:52:17 | 36.2 | 70.5 | 0.709 |

## E0.7 ANOMALY — sustained board power drifts ±6 % at constant throughput

10-minute means over loaded samples (`util.gpu ≥ 50`):

| window | arm | mean W | SM MHz | util % | util.mem % | temp °C |
|---|---|---|---|---|---|---|
| 10:48 | xhigh | 331.7 | 1570 | 96.8 | 79.1 | 78.7 |
| 10:58 | xhigh | 315.1 | 1500 | 96.8 | 78.6 | 77.9 |
| 11:08 | xhigh | 312.6 | 1475 | 97.1 | 75.6 | 77.8 |
| 11:18 | xhigh | 307.4 | 1463 | 96.9 | 77.6 | 77.5 |
| 11:28 | xhigh | 306.6 | 1459 | 96.9 | 78.0 | 77.4 |
| 11:38 | xhigh | **305.5** | **1453** | 96.9 | 78.1 | 77.4 |
| 11:48 | xhigh | 308.8 | 1457 | 97.0 | 75.3 | 78.0 |
| 12:08 | xhigh | 308.7 | 1467 | 96.9 | 78.4 | 78.2 |
| 12:20 | medium | 310.1 | 1475 | 97.0 | 78.0 | 78.0 |
| 12:40 | medium | 318.4 | 1529 | 96.3 | 78.4 | 77.7 |
| 12:52 | low | 335.9 | 1610 | 95.0 | 79.8 | 78.8 |
| 13:12 | low | **341.1** | **1604** | 96.9 | 79.9 | 79.0 |

Per-arm loaded means: xhigh tail **311.6 W / 1478 MHz**, medium **315.4 W /
1509 MHz**, low **334.9 W / 1595 MHz**.

The board's sustained draw swung **305.5 → 341.1 W (+11.7 %)** across 2.5 h
while:

* logged GPU temperature stayed pinned at **77–79 °C** the whole time;
* memory clock stayed at 9,501 MHz;
* `util.gpu` stayed at 95–97 %;
* **decode throughput stayed at 38.4–40.2 t/s** — the low arm ran at 1,595 MHz
  and delivered the same ~40 t/s as the medium arm at 1,509 MHz.

Power tracked SM clock almost exactly (low vs medium: +5.7 % clock, +6.2 %
power, +0 % throughput). Decode at batch 1 is memory-bandwidth-bound at a
fixed memory clock, so **the extra SM clock bought no tokens and cost ~6 % more
energy per token** — that is the entire 7.69 → 8.19 J/token gap between the
medium and low arms. The cause is not in the CSV (no memory-junction
temperature, no throttle-reason column); it is *not* logged core temperature.

Consequences, and these matter for the guide:

1. **"~344 W sustained decode" is the top of a range, not a constant.** On this
   box, drafter-off sustained decode occupies **306–341 W**. Quote the range
   or quote a run's own mean, never a single global constant.
2. **A ±6 % J/token band is instrumental, not workload.** Do not attribute a
   6 % J/token difference between two arms measured hours apart to the variable
   under test.
3. **This is the strongest available argument for the unmeasured power-cap
   sweep.** The board demonstrably spends 6–12 % more power at clocks that buy
   zero throughput. `nvidia-smi -pl` requires an elevated shell and remains
   **unmeasured on this machine (requires administrator)** — do not estimate it.

## E0.8 Provisional idle baseline — PROVISIONAL, pending the matrix's A1/A2

Trailing segment after the last load at 13:15:01.202, first 60 s discarded
(board cooling: it takes ~8 s to fall through P0→P3→P5→P8 and the temperature
keeps falling for minutes after).

| skip | window | s | mean W | median W | min | max | sd |
|---|---|---|---|---|---|---|---|
| 0 s | 13:15:01 → 13:19:37 | 276.2 | 39.33 | 31.44 | 28.76 | 312.28 | 26.99 |
| 30 s | 13:15:31 → 13:19:37 | 246.2 | 37.05 | 31.26 | 28.76 | 123.58 | 20.65 |
| **60 s** | **13:16:01 → 13:19:37** | **216.2** | **37.77** | **31.12** | 28.76 | 123.58 | 21.95 |
| 120 s | 13:17:01 → 13:19:37 | 156.2 | 35.85 | 30.92 | 28.76 | 123.58 | 18.90 |

**The settled tail is contaminated.** The mean (37.8 W) is 22 % above the
median (31.1 W) because five short excursions to ~121–124 W punch through it —
13:16:19, 13:16:30, 13:17:30, 13:18:32, 13:19:00, each 3–5 s, each a P0 spike
with SM 300→1725 MHz at 0–14 % utilisation and 1.57–1.73 GB resident. That is
**non-inference desktop/render GPU work** (the sweep was writing its PNG plots
and merged JSONs at 13:15–13:16), not the model — llama-server was already
gone (`mem.used` had collapsed to ~1.58 GB).

Splitting the settled tail by pstate:

| pstate | n | share | mean W | median W | SM MHz | mem MHz | util % | temp °C |
|---|---|---|---|---|---|---|---|---|
| **P8** | 380 | 90.0 % | **31.16** | **30.95** | 212 | 405 | 7.4 | 55.6 |
| P5 | 12 | 2.8 % | 82.12 | 75.55 | 349 | 810 | 4.4 | 56.8 |
| P0 | 30 | 7.1 % | 103.87 | 120.92 | 1674 | 9439 | 1.8 | 58.6 |

> **PROVISIONAL IDLE BASELINE (E0): 31.2 W**
> (P8-only settled tail, n = 380, mean 31.16 W, median 30.95, p05 29.28,
> p95 33.95, min 28.76, max 42.03; no model resident, ~1.58 GB board use,
> 55.6 °C, 212 MHz SM.)
> **Marked provisional.** It is a 216 s window with the desktop live and a
> plotting job running, taken while the board was still 20 °C above its cold
> resting point. It is superseded the moment the power matrix's **A1/A2** idle
> arms land. Use it only for sensitivity checks, never as the published idle.

Corroborating cross-checks from the same log: the xhigh→medium between-arm gap
with the server fully down reads **32.07 W** (n = 44, median 32.07, min 31.07,
max 33.30, 1,250 MB resident, P8) — 0.9 W above the tail figure and consistent
with a warmer board. The medium→low gap reads a useless 65.67 W mean (max
155.9 W) because a PNG render overlapped it: an object lesson that "the server
is down" is not the same as "the GPU is idle."

Existing campaign figures for comparison: cold board, no server **33.2 W**;
Phase 10b no-server idle **34.6 W** (n = 15, peak 70.1 — also contaminated);
loaded idle with model resident **30.7–31.1 W**. The E0 provisional 31.2 W sits
inside that band and does not move any conclusion.

---

# E8a — re-integration of the original effort-arm logs

## E8a.0 Inputs, boundaries, and anchoring

| input | file | notes |
|---|---|---|
| power (Phase 7) | `data/power.csv` | **1 Hz**, headerless, unit-suffixed (`98.71 W`), 4 columns `ts, W, util %, mem MiB`. 1,947 rows, 00:54:46.429 → 01:27:33.604. Cadence mean 1.011 s, max 1.106 s, **0** gaps > 2 s |
| power (Phase 7b) | `data/power-xhigh120k.csv` | **1 Hz**, 2 columns `ts, W` only. 1,120 rows, 01:55:26.588 → 02:14:16.792. Cadence mean 1.010 s, max 1.031 s, **0** gaps > 2 s |
| boundaries | `data/phase7.txt`, `data/phase7b.txt` | `RESULT` lines carry `t0=[...] t1=[...]`, `wall_s`, `prompt_n`, `predicted_n`, `decode_tps`, `accept`, `finish` |
| timings | `data/srv-effort-{low,medium,xhigh,xhigh-120k}.err.log` | each carries the full `prompt eval time` / `eval time` / `total time` block — so a **true phase split is available**, which Phase 10 did not use |

Neither CSV has `clocks.sm`, `pstate`, or `temperature`. There is no way to
prove from these files whether a low sample was a ramping board or an efficient
one; that is a permanent limitation of these two logs.

**Anchor check** (`server_start = mtime − last relative stamp`, then
`t_start = server_start + launch_slot_ stamp`):

| arm | recovered server start | recovered request t_start | `phase7*.txt` t0 | Δ |
|---|---|---|---|---|
| low | 00:55:01.510 | **00:55:14.604** | 00:55:14 | +0.604 s |
| medium | 00:59:03.714 | **00:59:16.759** | 00:59:16 | +0.759 s |
| xhigh-64k | 01:05:46.546 | **01:05:59.603** | 01:05:59 | +0.603 s |
| xhigh-120k | 01:55:29.642 | **01:55:46.891** | 01:55:46 | +0.892 s |

All four land inside the 1-second truncation of the recorded `t0`. The
boundaries are correct.

## E8a.1 Conditions — these travel with every number below

* **1 Hz sampling** (half the rate of the rule-21 log), no clocks / pstate /
  temperature columns.
* **MTP speculative decoding ON, n4 / p0.75**, acceptance 83.6–91.0 %.
* **temperature 1.0**, top_p 0.95, top_k 20 (the model card's thinking sampling)
  — *not* greedy. n = 1 per level. `-c 131072`, `-ngl 99`, q8_0 KV, **no
  projector**, `--reasoning-preserve`.
* Task: the aquarium HTML brief (`templates/effort-task-example.md`).
* **Mixed regime** — thinking and answer in one stream. xhigh-64k spent 160,919
  characters thinking and returned **no usable file** (`finish_reason=length`).
* Idle **not** subtracted in the gross columns.

## E8a.2 Reproduction of the published Phase-10 numbers — it reproduces

Old method exactly as `work/power-integrate.py` implemented it: arithmetic mean
of samples falling inside `[t0, t1]`, multiplied by `wall_s` (a rectangle rule,
no edge interpolation).

| arm | n samples | wall s | mean W | peak W | **Wh reproduced** | Wh published | Δ |
|---|---|---|---|---|---|---|---|
| low | 212 | 215 | 344.1 | 349.8 | **20.55** | 20.55 | +0.01 % |
| medium | 372 | 376 | 344.3 | 349.6 | **35.96** | 35.96 | +0.01 % |
| xhigh-64k | 1,264 | 1,278 | 338.6 | 349.4 | **120.21** | 120.21 | +0.00 % |
| xhigh-120k | 1,094 | 1,105 | 341.6 | 349.9 | **104.85** | 104.9 | −0.05 % |

**All four published figures reproduce.** No investigation needed.

## E8a.3 Trapezoid re-integration (the numbers to publish going forward)

`attribute-power.py` `PowerSeries`, window = the server's own
`[t_launch, t_launch + prompt_ms + predicted_ms]`, edges interpolated,
max-gap 2 s.

| arm | wall s | cov % | mean W | peak W | J gross | **Wh gross** | vs published | **J/token** | Wh/1k tok | **tokens/kWh** | **EDP (J·s)** |
|---|---|---|---|---|---|---|---|---|---|---|---|
| low | 215.0 | 100.0 | 344.6 | 349.8 | 74,093 | **20.581** | +0.15 % | **4.278** | 1.188 | **841,585** | 1.593e7 |
| medium | 375.7 | 100.0 | 345.0 | 349.6 | 129,619 | **36.005** | +0.13 % | **5.190** | 1.442 | **693,592** | 4.870e7 |
| xhigh-64k | 1,278.3 | 100.0 | 338.7 | 349.4 | 432,916 | **120.254** | +0.04 % | **6.606** | 1.835 | **544,978** | 5.534e8 |
| xhigh-120k | 1,104.4 | 100.0 | 341.8 | 349.9 | 377,436 | **104.843** | −0.05 % | **6.140** | 1.705 | **586,361** | 4.168e8 |

Trapezoid vs rectangle differs by ≤ 0.15 %. The published numbers were never
wrong; they are now defensible as well as correct. `EDP = J × wall_s`, per
answer (n = 1, so no averaging).

## E8a.4 Phase split — new, and not available to Phase 10

| arm | prefill s | J_prefill | J/prompt-tok | decode s | J_decode | **J/decode-tok** | decode t/s | tokens/kWh | EDP (J·s) |
|---|---|---|---|---|---|---|---|---|---|
| low | 1.72 | 280 | 0.1658 | 213.3 | 73,813 | **4.2615** | 81.22 | 844,778 | 1.574e7 |
| medium | 1.60 | 199 | 0.1202 | 374.1 | 129,420 | **5.1824** | 66.75 | 694,661 | 4.842e7 |
| xhigh-64k | 1.75 | 276 | 0.1622 | 1,276.5 | 432,640 | **6.6016** | 51.34 | 545,326 | 5.523e8 |
| xhigh-120k | 1.87 | 302 | 0.1775 | 1,102.5 | 377,134 | **6.1347** | 55.76 | 586,830 | 4.158e8 |

Prefill is **0.12–0.18 J per prompt token** against **4.3–6.6 J per decode
token** — a 26–43× asymmetry, and it accounts for **0.06–0.38 %** of each
answer's energy. Note these prefill windows (1.6–1.9 s) are longer than the 1 s sample
period, so unlike E0's, these J/prompt-token values are genuinely sampled.

The whole J/token spread is explained by throughput: `J/token ≈ mean_W ÷
decode_t/s` gives 4.24 / 5.16 / 6.60 / 6.13 against the measured 4.26 / 5.18 /
6.60 / 6.13. At a flat ~344 W board, **slower tokens are more expensive tokens,
proportionally and with no residual**.

## E8a.5 First-60 s excluded — the ramp contributes almost nothing here

| arm | mean W, first 60 s | mean W, after 60 s | Δ W | Wh full | Wh if all at settled rate | ramp cost | ramp % |
|---|---|---|---|---|---|---|---|
| low | 339.0 | 346.8 | −7.8 | 20.581 | 20.712 | **−0.131** | −0.63 % |
| medium | 337.6 | 346.4 | −8.8 | 36.005 | 36.152 | **−0.147** | −0.41 % |
| xhigh-64k | 337.8 | 338.7 | −0.9 | 120.254 | 120.269 | **−0.015** | −0.01 % |
| xhigh-120k | 323.5 | 342.8 | −19.3 | 104.843 | 105.165 | **−0.321** | −0.31 % |

The ramp makes every arm look **0.01–0.63 % better** than its settled rate —
the right sign (the README's warning is real) but a negligible magnitude,
because the board was already hot from the preceding phase and because these
are multi-minute runs. **The published Phase-10 Wh figures need no ramp
correction.** Contrast the README's short-probe case, where 10 s probes read
277–287 W against a 344 W sustained rate — a 17–20 % artifact. The lesson
stands for short runs; it does not bite here.

xhigh-120k's larger −19.3 W first-minute deficit is a genuine cold start and is
visible sample by sample: the board sits at **41.9 W** at 01:55:44.767 (model
resident, answering nothing — a clean loaded-idle reading), reaches 338 W only
by 01:55:48.8, then holds ~331 W for the rest of the first minute against a
342.8 W settled rate. Exactly the artifact the README describes — and it still
moves the published answer by only **0.32 Wh out of 104.84** (0.31 %).

## E8a.6 Idle subtraction — two baselines, and why the choice is irrelevant

| arm | Wh gross | Wh net (30.7 W, old contaminated) | Wh net (31.16 W, E0 provisional) | **spread** | J/tok gross | J/tok @30.7 | J/tok @31.16 | tokens/kWh @31.16 |
|---|---|---|---|---|---|---|---|---|
| low | 20.581 | 18.748 | 18.721 | **0.133 %** | 4.278 | 3.897 | 3.891 | 925,239 |
| medium | 36.005 | 32.801 | 32.753 | **0.133 %** | 5.190 | 4.729 | 4.722 | 762,457 |
| xhigh-64k | 120.254 | 109.354 | 109.190 | **0.136 %** | 6.606 | 6.007 | 5.998 | 600,201 |
| xhigh-120k | 104.843 | 95.425 | 95.284 | **0.135 %** | 6.140 | 5.588 | 5.580 | 645,186 |

Decode-only, idle-subtracted (the row directly comparable with E0):

| arm | decode t/s | J/decode-tok gross | @30.7 W | @31.16 W | tokens/kWh net |
|---|---|---|---|---|---|
| low | 81.22 | 4.2615 | 3.8835 | 3.8778 | 928,360 |
| medium | 66.75 | 5.1824 | 4.7225 | 4.7156 | 763,425 |
| xhigh-64k | 51.34 | 6.6016 | 6.0036 | 5.9946 | 600,539 |
| xhigh-120k | 55.76 | 6.1347 | 5.5841 | 5.5758 | 645,645 |

**A 0.46 W disagreement about idle moves the answer by 0.13 %.** At 344 W the
idle baseline is 9 % of the total and any plausible refinement of it is under a
seventh of a percent. Idle subtraction removes ~9 % (18.7 vs 20.6 Wh); *which*
idle figure you use is noise. Argue about the baseline only for near-idle work,
never for sustained decode. The E0 provisional idle therefore does **not**
change a single published effort number.

## E8a.7 Cross-analysis: what the drafter is worth, E8a vs E0

Different tasks and different sampling, so this is a **reference comparison,
not a controlled A/B** — but the two analyses bracket the drafter cleanly.

| | E0 (rule-21 cap 32k) | E8a (Phase 7 / 7b) |
|---|---|---|
| speculative decoding | **OFF** | **ON** — MTP n4 / p0.75 |
| decode t/s | 38.4 – 40.2 | 51.3 – 81.2 |
| mean board W under load | 306 – 341 (arm means 311.6 / 315.4 / 334.9) | 338.6 – 345.0 |
| **J/decode-token** | **7.88 ± 0.31** (n = 115 requests, 7.14 – 8.63) | **4.26 – 6.60** (n = 4 runs) |
| sampling | greedy | temp 1.0 / top_p 0.95 / top_k 20 |
| task | MATH-500 / HumanEval / MBPP, n = 25 | one aquarium HTML brief, n = 1 |
| regime | mixed | mixed |

The drafter costs roughly **+8 % board power** (arm means ≈317 W → ≈342 W: it
keeps the SMs busy drafting and verifying) and buys **+28 % to +103 %
throughput**. Net: **16 % less energy per token at xhigh, 46 % at low**
(6.60 and 4.26 J/tok against the 7.88 drafter-off pooled figure). Caveat: the
±6 % drift documented in E0.7 sits inside that +8 % power gap, so the power
side of this comparison is soft; the throughput side is not.
The mechanism is entirely `J/token = W ÷ t/s` — no separate efficiency effect
is needed or observed.

---

# Anomalies found

1. **Partial-coverage inflation (caught, corrected).** Charging a full token
   count against a partially covered energy window reported xhigh/HumanEval at
   5.32 J/token and 59.8 decode t/s — impossible for a drafter-off 3090. Fixed
   by counting only requests whose entire window is inside the log (115 of
   150). *Any* per-arm join across a log boundary needs this filter.
2. **Sustained board power drifted 305.5 → 341.1 W (+11.7 %) at constant
   throughput, constant 77–79 °C, constant memory clock**, tracking SM clock
   1453 → 1606 MHz. Costs ~6 % J/token for zero tokens. Cause not present in
   the logged columns. Full detail in E0.7 — this is the headline anomaly.
3. **The "settled idle" tail is contaminated by non-inference GPU work.** Five
   P0 spikes to 121–124 W in 216 s drag the mean to 37.8 W against a 31.1 W
   median. Server-down ≠ GPU-idle. The A1/A2 matrix arms must run with the
   desktop quiet or they will inherit this.
4. **The suite file's `settings` block does not describe what ran.**
   `work/rule21-n25-cap32768.json` records `temperature 1.0, top_p 0.95,
   top_k 20, presence_penalty 1.5`; every arm's result JSON records what the
   runner actually used — `temperature 0.0, top_p 1.0, top_k 1,
   presence_penalty 0.0`. The result JSONs are authoritative (and the arm logs'
   "greedy" banner agrees with them). The stale suite block is a live trap for
   anyone quoting conditions from the suite file.
5. **Harness `tok_s` is an unweighted mean over requests; the server's is
   token-weighted.** 41.0–41.7 t/s (harness) vs 38.4–40.2 t/s (server timings)
   for the same arms — the harness average is dominated by short, shallow-KV
   answers. Not an error, but the two must never be mixed in one table. All
   E0 throughput figures here are token-weighted from server timings.
6. **`arm-xhigh-cap32k`'s MATH-500 block has zero power coverage**, and GSM8K,
   ALPACA, MeetingBank and MT-Bench have zero coverage at any cap. Four of the
   suite's seven datasets have no energy data at all.

---

# What this licenses the guide to say

Claims now supported by measurement. Every one carries the tier line
*"in-band GPU board power (NVML); PSU, CPU and node excluded — unmeasured"*
and the regime line *"mixed regime: reasoning + answer tokens both counted"*.

### Licensed — the standardized metrics table (from E8a, drafter ON, n=1/level)

| level | Wh/answer | J/decode-token | tokens/kWh | EDP (J·s) | decode t/s |
|---|---|---|---|---|---|
| low | 20.58 | 4.26 | 844,778 | 1.57e7 | 81.22 |
| medium | 36.01 | 5.18 | 694,661 | 4.84e7 | 66.75 |
| xhigh (64k cap, truncated) | 120.25 | 6.60 | 545,326 | 5.52e8 | 51.34 |
| xhigh (120k cap, complete) | 104.84 | 6.13 | 586,830 | 4.16e8 | 55.76 |

Conditions to print with it: RTX 3090, IQ4_XS, `-c 131072`, q8_0 KV, MTP
n4/p0.75 ON, temp 1.0 / top_p 0.95 / top_k 20, no projector, **n = 1 per
level**, one HTML-authoring task, mixed regime, 1 Hz log with no clock or
pstate columns, idle not subtracted.

1. **The published 20.55 / 35.96 / 120.21 / 104.9 Wh figures are confirmed** by
   independent re-integration to within 0.05 % (rectangle) and 0.15 %
   (trapezoid). They may be cited without hedging.
2. **tokens/kWh and EDP per effort level** may now be published (table above) —
   they were never computed before.
3. **EDP spans 1.57e7 → 5.52e8 J·s, a 35× range across three effort levels.**
   Energy-delay product punishes xhigh far harder than energy alone (5.8×).
4. **Prefill costs 0.12–0.18 J/prompt-token against 4.3–6.6 J/decode-token** —
   a 26–43× asymmetry, and under 0.4 % of an answer's energy. Prefill is free;
   generation is the bill.
5. **`J/token ≈ mean_W ÷ decode_t/s` with no residual** (predicted 4.24/5.16/
   6.60/6.13 vs measured 4.26/5.18/6.60/6.13). The guide may state that at
   batch 1 on a fixed board, *throughput is efficiency* — anything that raises
   t/s at constant W lowers J/token proportionally.
6. **Wh/1k tokens rises with effort (1.19 → 1.44 → 1.84)** — confirmed, and now
   with the mechanism proven rather than asserted: the board holds ~344 W while
   decode falls 81 → 51 t/s.
7. **The ramp correction is not needed for these runs** (0.01–0.63 %). The
   guide may publish the gross Wh unqualified, while keeping the short-probe
   warning (10 s probes read 277–287 W vs 344 W sustained — a 17–20 % artifact).
8. **Idle subtraction is a 9 % effect and the choice of baseline is a 0.13 %
   effect** at 344 W. The guide may say the idle-baseline argument is
   irrelevant at sustained-decode scale and show the 30.7 W vs 31.16 W columns
   as proof.

### Licensed — the drafter-off reference (from E0, n = 115 requests)

9. **Drafter-off decode on this 3090 costs 7.88 ± 0.31 J/token**
   (median 7.91, p10–p90 7.52–8.29, full range 7.14–8.63, n = 115 requests
   across 3 arms and 3 benchmarks) at 38.4–40.2 t/s. This is the **~8 J/token
   drafter-off reference** to set against the drafter-on **6.1–6.6 J/token**
   at xhigh (and 4.3–5.2 at low/medium). It is a real distribution from 115
   requests, not a single run.
10. **The drafter costs ~+8 % board power and returns 16–46 % less energy per
    token** (16 % at xhigh's 51 t/s, 46 % at low's 81 t/s) — labelled a
    reference comparison, not a controlled A/B (different task, different
    sampling; E0 is greedy benchmark work, E8a is one temp-1.0 authoring task),
    and with the note that E0.7's ±6 % drift sits inside the power half of it.
11. **Reasoning effort does not change J/token; it changes J/answer.** MBPP at
    xhigh = 7.921 J/tok vs MBPP at medium = 7.947 J/tok (0.3 % apart) while mean
    answer length differs 3.1× (5,084 vs 1,629 tokens) and Wh/answer differs
    3.1× (11.21 vs 3.61 Wh). Same-benchmark, same-hardware, n = 25 each.
12. **Per-benchmark energy at n = 25** (in-band, covered requests only): MATH-500
    at low **125.4 Wh / 5.02 Wh per answer**; HumanEval at medium **74.6 Wh /
    2.99**; MBPP at medium **90.3 Wh / 3.61**; MBPP at xhigh **280.1 Wh /
    11.21**; HumanEval at xhigh **190.8 Wh / 12.72** (15 of 25 requests).
13. **Scoring and code execution are energetically free**: 0.15–0.24 s per
    inter-request gap, 5.8–9.2 s per 25-prompt arm, 0.04–0.14 % of arm energy —
    and the board does not drop clocks in gaps that short (312–336 W throughout).
14. **A full benchmark arm's board energy**: medium-cap32k (50 prompts,
    31.6 min) = **165.87 Wh**; low-cap32k (25 prompts, 22.7 min) = **126.22 Wh**.
    Both fully covered, 100 % sample coverage.
15. **Answer length is nearly irrelevant to J/token**: < 1,000 tokens 7.85,
    ≥ 1,000 tokens 7.95 (n = 74 / 41) — deeper KV costs ~1 % per token.

### Licensed with the anomaly attached

16. **"Sustained decode ≈ 344 W" must become a range.** Drafter-off sustained
    decode measured **306–341 W** across 2.5 h at constant throughput and
    constant logged temperature; drafter-on measured 338.6–345.0 W. Quote a
    run's own mean, or the range. A single global constant is not supported.
17. **A ±6 % J/token difference between arms measured hours apart is within
    instrumental drift** and may not be attributed to the variable under test.
18. **The power-cap lever is the strongest untested hypothesis on this box** —
    the board spent 6–12 % more power at SM clocks that produced zero extra
    tokens. State it as a hypothesis and keep the cap marked
    *"unmeasured on this machine (requires administrator)"*. Do not estimate it.

### Explicitly NOT licensed

* **No idle-baseline claim beyond "provisional 31.2 W".** The E0 tail is 216 s
  with the desktop live and a plot renderer firing; the campaign's own 33.2 /
  34.6 / 30.7–31.1 W figures are equally contaminated. Wait for A1/A2.
* **No energy figure for GSM8K, ALPACA, MeetingBank or MT-Bench** at any cap,
  and none for the three 16k-cap arms (04:40–09:55) — no power log exists for
  any of them.
* **No full-arm energy for `arm-xhigh-cap32k`** as a measurement. Covered
  portion = 473.09 Wh over 5,466 s; the full 2 h 24 m arm is **estimated
  746–764 Wh** and must carry that word and that bracket.
* **No MATH-500 energy at xhigh** — that block ran entirely before the logger.
* **No answer-token-only J/token anywhere.** Everything here is mixed regime.
* **No wall-power, system-power, cost-per-answer, or CO₂ figure.** In-band GPU
  board power only; PSU losses and the rest of the node are unmeasured.
* **No per-effort statistical claim from E8a**: n = 1 per level. The n = 25
  statistics belong to E0 (drafter-off) only.

---

## Provenance

| artefact | path |
|---|---|
| integrator | `scripts/power/attribute-power.py` (`--selftest` passed, 2026-08-23) |
| E0 power log | `results/qwen38-27b-blind/data/power/rule21-power.csv` |
| E0 request logs | `results/qwen38-27b-blind/data/rule21/arm-{xhigh,medium,low}-cap32k-llama-server.log` |
| E0 arm/driver logs | `results/qwen38-27b-blind/data/rule21/arm-*-cap32k.log`, `arm-*-cap32k-wall.json`, `arm-*-cap32k-*.json` |
| E8a power logs | `results/qwen38-27b-blind/data/power.csv`, `data/power-xhigh120k.csv` |
| E8a boundaries | `results/qwen38-27b-blind/data/phase7.txt`, `data/phase7b.txt` |
| E8a timings | `results/qwen38-27b-blind/data/srv-effort-{low,medium,xhigh,xhigh-120k}.err.log` |
| original method | `results/qwen38-27b-blind/work/power-integrate.py` → `data/phase10.txt` |
| campaign entries | `results/qwen38-27b-blind/campaign.md` — Phase 7 (line 538), Phase 7b (line 651), metrics (line 947) |

Analysis scripts (scratchpad, not committed): `parse_rule21.py` (log → event
JSONL + anchors), `e0.py` (per-request join), `e0b.py` (drift + idle
characterisation), `e8a.py` (effort-arm re-integration).
