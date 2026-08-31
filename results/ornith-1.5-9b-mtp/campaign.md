# Campaign log — ornith-1.5-9b-mtp

Ornith-1.5-9B (MTP GGUF lineage) on an RTX 3090, bare-metal Ubuntu 26.04.
This file is the canonical log and the recovery point after any crash. Append
decisions, findings and timestamps; never rewrite history in it.

---

## Stage 0 — interview + instrumentation  ·  2026-08-31  ·  CLOSED

### The interview record (rule 31: questions happen here and nowhere else)

| # | Question | Answer | Who decided |
|---|---|---|---|
| Q1 | Model | `protoLabsAI/Ornith-1.5-9B-MTP-GGUF` — Q8_0, Q4_K_M, IQ2_M, plus mmproj and the MTP head | operator named the model; agent resolved the lineage |
| Q2 | Machine | RTX 3090 24,576 MiB, driver 580.173.02, CUDA b10717 built from source; 20 cores, 30.7 GB RAM, 2 RAM channels | auto-detected, operator confirmed |
| Q3 | Use cases | "How good is Ornith-1.5-9B", plus **how well this harness supports a new model** — the campaign is a harness test as well as a model test | operator |
| Q4 | Time budget | **MULTI-DAY** — every surviving quant gets the full treatment: n=200 accuracy per arm, full perplexity on all three files, the Stage-2 ceiling sweep per file, accuracy per effort level | operator |
| Q5 | Philosophy | **QUALITY-FIRST** — ship maximum effort wherever the window allows | operator |
| Q6 | Publish | `results/ornith-1.5-9b-mtp/index.html` | agent derived the slug, operator accepted |
| Q7 | Coding agents | detected on PATH: `opencode`, `claude`. No aider/qwen/pi/dsh; installing them was not authorised, so Stage 6d tests what is here | auto-detected |
| — | Desktop state | **Recorded as-is.** Live GNOME session: gnome-shell + Xwayland + Steam + browser, monitors on, 454 MiB resident | operator, explicitly |

**The desktop decision is a condition of every throughput number in this
campaign and must travel with them (rule 3).** Rule 27 measured that a busy host
costs decode invisibly to any clock log — −5.4% mean, −24.0% worst, r = −0.924.
The operator chose to measure the desktop they actually use rather than a quiet
box. Every speed figure this campaign publishes is therefore a *desktop-live*
figure and the report says so; it is not comparable to the reference 3090
campaign's quiet-box numbers without that caveat.

### Why this repo and not the vendor's — the finding that set the roster

The operator's first instinct was the vendor repo. It cannot produce the ladder
they asked for, and the third-party repos that can are **not the same model**.

Read out of the GGUF headers with `scripts/inspect-model.py`, 2026-08-31:

| repo | BF16 | Q8_0 | Q4_K_M | 2-bit | `block_count` | `nextn_predict_layers` | params |
|---|---|---|---|---|---|---|---|
| `ornith-ai` (vendor) | 18.41 | 9.79 | 5.78 | **none shipped** | 33 | 1 | 9,197,093,888 |
| `protoLabsAI` (MTP) | 18.41 | 9.79 | 5.78 | IQ2_M 3.87 | 33 | 1 | 9,197,093,888 |
| `mradermacher` | 17.92 | 9.53 | 5.63 | Q2_K 3.83 | **32** | **None** | 8,953,803,264 |
| `AtomicChat` | 17.92 | 9.53 | — | AD-IQ2 3.38 | **32** | **None** | 8,953,803,264 |
| `prithivMLmods` | 17.92 | 9.53 | 5.63 | — | **32** | **None** | 8,953,803,264 |

All three third-party conversions **drop the multi-token-prediction layer**. The
gap is 243,290,624 params, and the arithmetic closes:

```
predicted BF16 file-size gap = 243,290,624 x 2 B = 0.487 GB
observed  BF16 file-size gap = 18.41 - 17.92     = 0.490 GB
```

A stock `convert_hf_to_gguf` run drops that layer and says nothing. Taking Q8
from the vendor and Q2 from mradermacher would have put a **different
architecture at the two ends of the quant ladder** and published it as a
quantisation finding (rule 3; rule 30 — compare arms inside one sweep). All
three arms therefore come from one lineage.

`protoLabsAI` is also the only source shipping a separate MTP head
(`mtp-head/mtp-Ornith-1.5-9B-head-Q8_0.gguf`, 2.43 GB), which is what puts
`drafter` in the capability list. **Ornith-1.0-9B had no draft head anywhere**,
so speculative decoding is an axis this campaign can run and a 1.0 campaign
could not.

CAVEAT, carried forward: `protoLabsAI` is a third party (19,770 downloads at
selection time). Its Q8_0/Q4_K_M are byte-different from the vendor's despite
identical nominal sizes — a different quantisation run, not a re-host. Whether
its IQ2_M used an imatrix is undocumented; Stage 1's pruning gate will show it.

### What the model IS (`model-*.json`, header reads over ranged GETs)

- `qwen35`, **supported by this build** (b10717) — loadable
- 9.197 B params, 33 blocks (32 + 1 MTP), context_length **262,144**
- **Hybrid attention**: 8 of 32 layers are full attention
  (`full_attention_interval` 4); the other 24 are recurrent/linear gated-delta
  holding a **fixed 51 MiB state, context-independent**
- KV = 2 × 8 full-attn × 4 kv-heads × 256 head-dim × 2 B = **32,768 B/token** (f16)
- Vision: `mmproj-Ornith-1.5-9B-BF16.gguf`, 879 MiB, projector `qwen3vl_merger`
- Drafter: present (see above)
- Effort knob: `enable_thinking`, **BOOLEAN** — an effort sweep here is **two
  arms, not four graded levels**
- capabilities: `text, vision, drafter, effort`

### The fit (`check-request.py`, against measured `machine.json`)

Budget = 24,576 MiB board − 454 MiB desktop reserve = **24,122 MiB**.
At the **full 262,144-token window with the projector resident**:

| arm | weights | +KV | +proj | +state | total | spare |
|---|---|---|---|---|---|---|
| Q8_0 | 9,333 | 8,192 | 879 | 51 | 18,455 | 5,666 |
| Q4_K_M | 5,512 | 8,192 | 879 | 51 | 14,634 | 9,487 |
| IQ2_M | 3,687 | 8,192 | 879 | 51 | 12,809 | 11,312 |

Adding the 2,318 MiB draft head still leaves Q8_0 at 20,773 MiB, ~3.3 GB spare.
**Everything fits at maximum context with vision and speculation both on.**
NOT counted: llama.cpp's compute/output buffers (hundreds of MiB, unknown until
Stage 1 reads the server's own figure). Treat these margins as UNPROVEN until
then (rule 13).

### The plan (`plan.json`, `plan-campaign.py` exit 0)

**14 of 14 stage units RUN — nothing is skipped.** This model has vision, a
drafter and an effort knob, so every axis in the harness is live. For the
operator's second goal that is the point: this campaign exercises the whole
instrument, not a subset.

DERIVED estimate: **11.6–15.6 GPU hours**. One deviation the planner flagged:
Stage 2's ceiling sweep collapses to one rung per file, because the whole window
fits and there is no ceiling to find. Everything else in Stage 2 still runs.

### The harness-validation anchor (the operator's second goal, made falsifiable)

The vendor publishes **GPQA Diamond 86.4** for Ornith-1.5-9B (model card, read
2026-08-31), alongside SWE-bench Verified 70.6, Terminal-Bench 2.1 46.2/47,
SWE-bench Pro 47.5, NL2Repo 32.4 and HLE 20.2 / 30.5 with tools.

This repo ships GPQA Diamond frozen at all **198** questions
(`scripts/bench/datasets-frozen/gpqa_diamond.jsonl`).
`methodology/NEXT-MODELS.md` names GPQA Diamond the cheapest and most universal
harness validation available and records that the gap — never once having
checked this harness against a published number — has been open since the
campaign began. **This campaign closes it**: Stage 6a runs GPQA Diamond against
the published 86.4, and the distance between the two is the measurement of the
harness, not of the model. Recorded here so the comparison is a stated intent
and not a result fished for afterwards.

### Instrumentation on

- Power logger started 2026-08-31, 500 ms, detached:
  `results/ornith-1.5-9b-mtp/data/power/campaign-power.csv` (pid 362231,
  mode redirect, 12 columns incl. `clocks_event_reasons.active`).
  Enforced power limit at start: **350.00 W**. euid 0, elevated true.
- **COLD IDLE BASELINE — 2026-08-31, n=47 @ 500 ms, nothing loaded:**
  **37.71 W** mean (min 37.53, max 37.92, sd 0.10). SM clock pinned 210 MHz,
  memory.used 454 MiB (the desktop).
  Tier: **in-band GPU board power (NVML); PSU losses and PUE excluded.**
  The reference 3090 read 33.2 W cold on Windows; the ~4.5 W difference is the
  live GNOME desktop and is a condition, not a discrepancy.
  The *loaded* idle flavour is taken in Stage 1, the first time a server is up
  and idle. Every idle-subtracted figure downstream depends on both.

### Elevation — recorded, and what it forfeits

This campaign runs from a **root shell** (`elevated: true`, `privilege_path:
direct`). That buys the power-cap arms (350/300/250 W) without a human step.
It costs exactly one field: `pl_writable_without_elevation` stays `null`,
because a power-limit set that succeeds under root says nothing about an
ordinary user. Rule 28 makes that permanent for this campaign — the operator
was offered an unelevated `detect-machine.py` run to capture it and the campaign
opened without one.

### Stage 0 close criteria

`campaign.json` ✓ · `machine.json` ✓ · `model-Q8_0.json` `model-Q4_K_M.json`
`model-IQ2_M.json` ✓ · `plan.json` ✓ · power logger running ✓ · cold idle
baseline dated ✓ — **Stage 0 CLOSED. The campaign is autonomous from here
(rule 31).** Mid-run uncertainty resolves: this interview record → the measured
default → record the assumption and proceed. Never stop to ask.

**Next: Stage 1 — STRUCTURE.** Download 22.79 GB (Q8_0 9.79 + Q4_K_M 5.78 +
IQ2_M 3.87 + mmproj 0.92 + MTP head 2.43) into `models/`, verify `-ngl 99`,
read the server's own KV figure to replace the UNPROVEN margins above, take the
loaded-idle power baseline, and run one floor probe per quant. The early pruning
gate drops anything slower AND worse, and records it as screened out.
