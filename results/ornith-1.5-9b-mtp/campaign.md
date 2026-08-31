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

---

## Stage 1 — STRUCTURE  ·  2026-08-31  ·  measurements in

Roster acquired: 22.78 GB, five files, sizes matched against the HF listing and
GGUF magic verified on each. Backend condition, copied from
`bin/llama.cpp/INSTALL.json` as rule 3 requires: **flavor `cuda`, tag `b10717`,
commit `a32af33de2b5`, built from source, `CMAKE_CUDA_ARCHITECTURES=native`
(sm_86), driver 580.173.02.**

### CORRECTION to the Stage-0 record: the in-file MTP layer is INERT in b10717

Stage 0 chose this lineage because the vendor and protoLabsAI files carry
`block_count 33 / nextn_predict_layers 1` where every third-party conversion
carries `32 / None`, and concluded that mixing repos would compare two
architectures. **The file facts are right and the conclusion was overstated.**
The server log says, on every load:

```
W model has unused tensor blk.32.attn_q.weight       -- ignoring
W model has unused tensor blk.32.nextn.eh_proj.weight -- ignoring
... 15 tensors, the whole of block 32
```

llama.cpp b10717 loads block 32 and throws it away. At runtime the vendor file
and mradermacher's are the same model; the 0.15–0.49 GB difference is tensors
this build ignores. Keeping one lineage is still correct — the files differ in
bytes-on-disk, which IS the decode budget (rule 10) — but not for the reason
Stage 0 gave. Recorded rather than quietly amended: separating "the effect is
real" from "the explanation is right" is one of the three failures AGENTS.md
says no rule number catches, and this campaign walked into it in its first hour.

### The drafter is real, and it is the separate head — not the in-file layer

`--spec-draft-model models/mtp-Ornith-1.5-9B-head-Q8_0.gguf`, Q8_0 target,
`--spec-draft-n-max 10 --spec-draft-p-min 0.5`, c=8192, temp 0:

| Q8_0 | decode | acceptance | mean draft length |
|---|---|---|---|
| no speculation | 78.30 t/s | — | — |
| + MTP draft head | **115.89 t/s** | **0.698** (125/179) | **3.12** |

**1.48x on the largest file in the roster.** Rule 11 wants both numbers and both
are here. protoLabsAI is the only source shipping that head, so the roster choice
survives its own correction.

### Floors — one probe per quant, temp 0, no speculation, c=32,768, `-ngl 99`

| arm | size | floor (server `timings`) | llama-bench tg128 | pp512 | rule-10 constant |
|---|---|---|---|---|---|
| Q8_0 | 9.79 GB | 78.30 t/s | 86.20 ± 0.06 | 4264.84 | 0.82 |
| Q4_K_M | 5.78 GB | 118.38 t/s | 123.29 ± 0.03 | 4088.54 | 0.73 |
| IQ2_M | 3.87 GB | 131.30 t/s | 138.64 ± 0.10 | 3670.75 | 0.54 |

Conditions on every row: short code task, temp 0, c=32,768, no speculation,
**desktop live** (GNOME + Steam + browser). Decode is the server's own
`predicted_per_second`, never tokens/wall.

**Rule 10's efficiency constant is not one constant here.** Back-solved against
the 3090's published 936 GB/s it reads 0.82 / 0.73 / 0.54 across the three
formats. IQ2_M lands 22% under what pure bandwidth predicts: at 2 bits the file
stops being bandwidth-bound and starts being unpack-bound, so **the 2-bit file
buys far less speed than its size suggests** — 1.11x the decode of Q4_K_M for
0.67x the bytes. Carried to Stage 5 as a recipe input; it is the first thing that
would mislead a reader sizing by file alone.

### The idle baselines — and why the Stage-0 number was 34% wrong

Stage 0 recorded a cold idle of **37.71 W** (n=47, sd 0.10, taken immediately
after starting the logger, exactly as stage-0.md prescribes). It is wrong, and
the continuous log proves it. Empty board, P8 throughout, 0.5 s per sample:

| window | n | power |
|---|---|---|
| samples 0–47 — *the Stage-0 baseline window* | 47 | **37.71 W** |
| samples 47–120 | 73 | 37.91 W |
| samples 120–300 | 180 | 38.21 W |
| samples 300–900 | 600 | **25.66 W** |
| samples 900–end | 3733 | 28.17 W |

The board sits ~38 W for its first ~150 seconds **in P8 the whole time**, then
settles. It is not a pstate change and not the sampler: it is a settling tail,
and Stage 0's "n≥15 samples, before anything loads" puts the entire window
inside it. stage-0.md already warns that "a board still cooling from earlier work
reads high" and cites the reference campaign's 58.0 W against a 33.2 W cold
reading — the warning exists and the prescription does not operationalise it,
so a campaign that follows the letter still gets a wrong number. **Rule 24 makes
every idle-subtracted joule downstream depend on this figure.**

**The corrected pair, both from the persistent 500 ms logger, P8 only:**

| baseline | n | power | mem clock |
|---|---|---|---|
| cold idle — empty board, desktop live | 4,554 | **28.09 W** | 405 MHz |
| loaded idle — Q8_0 resident, nothing decoding | 458 | **31.12 W** | 405 MHz |

**A resident 9.79 GB model costs +3.03 W at idle**, which reproduces the
reference campaign's finding that a resident model costs almost nothing until
asked (theirs: 33.2 → 30.7–31.1 W). Tier on both: in-band GPU board power
(NVML); PSU losses and PUE excluded.

Also measured and worth keeping: **a board 5 s after a model load reads 133.14 W
at SM 1821 MHz** while decoding nothing. Any energy arm that starts sampling
immediately after a load bills that to the arm.

### Two harness defects this stage surfaced (campaign goal 2)

1. **`scripts/probe-config.sh` violates rule 20.** stage-1.md names it the POSIX
   seed for the floor probe. It launches `llama-server` with a bare `&` and stops
   it with `pkill -f "llama-server.*--port <port>"`, and never touches
   `scripts/bench/gpu_lock.py`. AGENTS.md states rule 20 as *enforced* — every
   server through `gpu_lock.serve()`, never a bare Popen — because four
   concurrent servers hung the reference machine on 2026-08-29. The pkill is
   worse than merely unguarded: it matches by port and would kill a server
   another job legitimately holds under the lock. A bash script cannot hold the
   lock (it is a Python API with no `run` verb), so the fix is a Python probe.
   This campaign uses `work/stage1-structure.py`, which takes the lock once for
   the whole stage and launches every server through `gpu_lock.serve()`.
2. **b10717 logs no KV-size and no offload line**, so stage-1.md's prescribed
   rule-4 cross-check — "the server's reported KV size at a known `-c`" — has no
   source in this build. Recorded as UNAVAILABLE rather than claimed as
   agreement. `-ngl 99` residency is DERIVED instead, from `memory.used` 10,002
   MiB against 9,333 MiB of weights plus a 454 MiB desktop, and from tg128
   sitting at 0.82 of the bandwidth bound — a partially-offloaded model cannot
   reach that. The header's 32,768 B/token stands unchallenged by a second
   reading on this build.

One thing that worked exactly as designed and is worth recording as a pass:
`gpu_lock.serve()`'s "the child cannot outlive this process" guarantee held when
a 120 s harness timeout SIGTERM'd the parent mid-probe — `gpu_lock.py status`
came back `free / servers: none` with no orphan holding VRAM.

**Pruning gate: nothing is dropped.** The gate drops a file that is both slower
AND worse; on speed alone all three are separated and monotonic in the right
direction, so no file can be screened out before the short PPL screen. That screen
is the next step, and it is what decides whether IQ2_M survives to Stage 2.
