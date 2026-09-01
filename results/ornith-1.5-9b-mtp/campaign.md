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

### The pruning gate, and the finding that stopped it — 2026-09-01

The gate's third input is a short PPL screen, "4 x 8,192 tokens is enough,
identical chunks across files". It came back with the ordering inverted, so
rather than act on 32,768 positions the screen itself calls unpublishable, the
**full rule-6 ladder** was run instead — 36 chunks x 8,192 = **294,912 token
positions exactly**, the same chunks of the same frozen corpus for every arm.
It cost 6.3 GPU-minutes for all three files.

| arm | GB | screen (32,768 pos) | **rule 6 (294,912 pos)** | floor t/s |
|---|---|---|---|---|
| Q8_0 | 9.79 | 8.0341 ± 0.1743 | **9.0519 ± 0.0692** | 78.30 |
| Q4_K_M | 5.78 | 7.5848 ± 0.1548 | **7.9544 ± 0.0553** | 118.38 |
| IQ2_M | 3.87 | 7.9439 ± 0.1552 | **8.6629 ± 0.0586** | 131.30 |

**The inversion is not noise and it got stronger with more positions:**

```
Q8_0 vs Q4_K_M : +1.0975 PPL   12.4 sigma
Q8_0 vs IQ2_M  : +0.3890 PPL    4.3 sigma
IQ2_M vs Q4_K_M: +0.7085 PPL    8.8 sigma

expected ordering for correct quants : Q8_0 < Q4_K_M < IQ2_M   (lower is better)
observed ordering                    : Q4_K_M < IQ2_M < Q8_0
```

A Q8_0 is meant to be near-lossless. This one is **worse than the 5.78 GB
Q4_K_M and worse than the 3.87 GB 2-bit file**, on the same corpus, the same
chunks, the same build, in the same hour. That is not a quantisation result; it
is a defect somewhere.

The running estimates say where it starts. `[n]` is cumulative, so an agreeing
prefix followed by a jump locates the chunk that broke:

```
        Q8_0        Q4_K_M
[1]     9.1371      9.1050     agree to 0.35%
[2]     6.4624      6.4655     agree to 0.05%
[3]     7.8824      7.2756     <- diverges, 8.3%
[4]     8.0341      7.5848
[8]     8.2987      7.6318     and stays ~7% apart
```

**Hypothesis, UNTESTED and labelled as such:** this is a hybrid — 24 of its 32
layers are recurrent gated-delta carrying a fixed state — and a quantisation
defect in those layers would degrade with sequence position rather than
uniformly, which is the shape above. It is a hypothesis and nothing here tests
it. This campaign already got burned once today asserting a mechanism it had not
separated from its effect; the effect is what is recorded.

**THE GATE WAS RIGHT AND I WAS WRONG ABOUT IT.** On the screen alone the
Stage-1 rule — drop what is both slower AND worse — pointed at Q8_0, and the
first reading of that here was "the gate would drop the quality anchor, so the
gate needs a guard". It did not need a guard. It had detected a real defect in a
file, which is exactly its job; the error was mine, in assuming the anchor could
not be the broken thing. Recorded because the near-miss is worth more than the
number: a reader who trusts a Q8 by its name would have shipped it.

**No file is dropped yet.** A cross-check is running first (rule 4 — two
independent cheap readings beat one): the SAME 294,912-position ladder against
the **vendor's own** `ornith-ai/Ornith-1.5-9B-GGUF` Q8_0, a different
quantisation lineage of the same weights.

- If the vendor's Q8_0 lands near 7.9, protoLabsAI's Q8_0 is defective, the
  roster changes, and the campaign's Q8 arm moves lineage — accepting that the
  ladder then spans two lineages, which must be stated on every comparison.
- If the vendor's Q8_0 also lands near 9.05, the file is not the problem and
  something about this architecture, this build, or this corpus is — a larger
  finding than the one being chased.

Either way rule 5 applies: the dead claim is kept as a dated case study, because
how it misled is worth more than the number was.

### The cross-check: the file is NOT defective, and the finding is bigger — 2026-09-01

The same 294,912-position ladder, same corpus, same chunks, same build, against
the **vendor's own** Q8_0 from `ornith-ai/Ornith-1.5-9B-GGUF` — an independent
quantisation lineage of the same weights:

| arm | lineage | PPL | ± |
|---|---|---|---|
| Q8_0 | protoLabsAI MTP | 9.0519 | 0.0692 |
| **Q8_0** | **ornith-ai (first-party)** | **9.0460** | 0.0691 |
| Q4_K_M | protoLabsAI MTP | **7.9544** | 0.0553 |
| IQ2_M | protoLabsAI MTP | 8.6629 | 0.0586 |

**The two Q8_0 lineages agree to 0.06 sigma.** The "protoLabsAI's file is
defective" hypothesis is dead — the second hypothesis this campaign has had to
kill in a day, and it died the same way the first did: cheaply, because it was
tested instead of assumed.

What survives is a stronger and stranger claim: **on this model, Q8_0 is ~1.10
PPL worse than its own Q4_K_M and 0.39 worse than the 2-bit file, reproducibly,
across independent quantisation runs by different people.** An 8-bit quant is
the least aggressive thing on the roster and is meant to be near-lossless.

**BF16 is the arbiter and it was not finished.** Only the unquantised reference
says which end of the ladder is the anomaly:
- BF16 ≈ 7.95 → Q8_0 is the outlier: 8-bit quantisation of this hybrid loses
  something real, and everyone running the vendor's own Q8_0 is getting worse
  output than the 5.78 GB file.
- BF16 ≈ 9.05 → Q4_K_M is the outlier, scoring better than the original
  weights, which points at the corpus or at how this hybrid is evaluated.

Until BF16 lands, **no quant recommendation may be published from this ladder**
(rule 2: no reader measures less than the report promised) and the Stage-1
pruning gate stays open with nothing dropped.

### INTERRUPTED — 2026-09-01, mid-Stage-2

Three background jobs were killed together: the BF16 download, the Stage-2
memory map, and a stale waiter. State on inspection, all verified rather than
assumed:

- `gpu_lock.py status` → **lock free, servers: none**; VRAM back to 454 MiB and
  38.91 W, i.e. the desktop alone. `gpu_lock.serve()`'s "the child cannot
  outlive this process" guarantee held under an abrupt kill for the **second**
  time today. Nothing orphaned, nothing holding the card.
- `models/vendor-Ornith-1.5-9B-BF16.gguf` — partial, 1,157,517,312 of
  ~18.41 GB. `curl -C -` resumes it; nothing else reads it, so a partial file
  cannot be mistaken for a complete one by any later stage.
- `data/stage2-memory-map.json` — header only, no arm completed. The script
  skips any pair already recorded, so re-running costs only what was not done.

**Nothing measured has been lost.** Everything through the vendor cross-check is
committed; the ladder, the floors, the speculation result and both idle
baselines are on disk and in git.

## Stage 2 — MEMORY MAP  ·  2026-09-01

### The pair table (rule 13's scope: file + drafter + projector + desktop)

Eight loads, VRAM read settled (20 s after health, median of 9 samples), c=32,768:

| arm | total MiB | server-only MiB |
|---|---|---|
| Q8_0 bare | 10,002 | 9,548 |
| Q8_0 + projector | 11,132 | 10,678 |
| Q8_0 + drafter | 12,268 | 11,814 |
| Q8_0 + both | 13,398 | 12,944 |
| Q4_K_M bare | 6,770 | 6,316 |
| Q4_K_M + both | 10,064 | 9,610 |
| IQ2_M bare | 4,970 | 4,516 |
| IQ2_M + both | 8,366 | 7,912 |

**The two constants, and they ADD exactly:**

| constant | measured | the file says | delta |
|---|---|---|---|
| projector | **1,130 MiB** | 879 MiB | +251 MiB of buffers |
| drafter | **2,266 MiB** | 2,318 MiB | −52 MiB |
| both together | **3,396 MiB** | 1,130 + 2,266 = 3,396 | **0 — additive** |

Projector and drafter are independent: the pair table may be summed, which is
what makes a budget table legal here. And `check-request.py`'s warning that it
does not count compute buffers is confirmed rather than assumed — the projector
costs 251 MiB more resident than its file.

### The rule-4 KV cross-check, obtained by SLOPE

stage-1.md wants the header's KV arithmetic checked against "the server's
reported KV size at a known `-c`". b10717 prints no such line (recorded in
Stage 1 as UNAVAILABLE). **This closes that gap by a different route**: load one
file at four context sizes and take the slope of settled VRAM. Everything that
does not scale with context — weights, compute buffers, the 24 recurrent layers'
fixed state — cancels in the difference.

| c | VRAM at load | after a real request |
|---|---|---|
| 8,192 | 5,978 MiB | 5,982 |
| 32,768 | 6,770 | 6,774 |
| 65,536 | 7,826 | 7,830 |
| 131,072 | 9,938 | 9,942 |

```
measured KV = (9,938 - 5,978) MiB / (131,072 - 8,192) tokens = 33,792 B/token
header      = 2 x 8 full-attn x 4 kv-heads x 256 head-dim x 2 B = 32,768 B/token
agreement   = 1.031   (+3.1%)
```

**The header's KV arithmetic is confirmed** — two independent readings agreeing
(rule 4), and a third from `config.json` (`num_hidden_layers` 32,
`full_attention_interval` 4 → 8 full-attention layers; `num_key_value_heads` 4;
`head_dim` 256), which reproduces the same 32,768 B/token from the base repo
rather than from the GGUF. Load and after-request differ by 4 MiB, so **the
cache is allocated eagerly, not lazily** — a load-only reading is trustworthy
here.

### The fit, now on measured constants rather than arithmetic

```
Q8_0 bare at c=32,768                   9,548 MiB   measured
+ KV for 229,376 more tokens            7,392 MiB   measured slope
+ projector                             1,130 MiB   measured pair
+ drafter                               2,266 MiB   measured pair
= 20,336 MiB of a 24,122 MiB budget  ->  3,786 MiB spare
```

**Q8_0 holds the full 262,144-token window with vision AND speculation resident,
with 3.8 GB to spare, measured rather than derived.** plan.json's call that the
ceiling sweep collapses to one rung per file is upheld: there is no ceiling to
find on this card.

### One open item, recorded rather than explained

Weights-plus-KV does not close against measured VRAM in the same direction for
every arm: overhead above file size is +215 MiB (Q8_0), +804 (Q4_K_M), +829
(IQ2_M) at c=32,768, where KV alone should be ~1,056 MiB for all three. Two
known contributors are unquantified here — llama.cpp ignores this file's
`blk.32` entirely (Stage 1), which is ~247 MiB of Q8_0 that never becomes
resident, and a large `token_embd` may not be offloaded the way the rest is.
**The slope is unaffected** (both cancel in a difference), so the KV figure
stands; the absolute decomposition does not, and no number in this campaign
depends on it. Left as an open item rather than given a mechanism it has not
earned.

## Stage 3 — SPEED SURFACES  ·  2026-09-01

### The speculation sweep, and why its baseline is unusable

Six arms, fresh server each, one temp-0 probe, `arms.py` alternating arm order
(rule 30). The first pass hit `finish_reason=length` on **all six** at the
reference campaign's 700-token cap; rule 7 forbids interpreting or filtering a
truncated probe, so the cap went to 3,000 and every arm re-ran.

| arm | t/s | vs none | acceptance | draft_n | predicted_n | finish |
|---|---|---|---|---|---|---|
| spec-none | 119.56 | 1.000x | — | — | **3000** | **length** |
| spec-mtp-n4-p0.75 | **148.03** | **1.238x** | 0.902 | 795 | 1135 | stop |
| spec-mtp-n6-p0.5 | 138.50 | 1.158x | 0.680 | 1494 | 1427 | stop |
| spec-mtp-n10-p0 | 115.64 | **0.967x** | 0.298 | 2540 | 1012 | stop |
| spec-mtp-n10-p0.5 | 134.21 | 1.123x | 0.630 | 1483 | 1311 | stop |
| spec-mtp-n16-p0.5 | 130.90 | 1.095x | 0.627 | 1491 | 1311 | stop |

**Speculation can LOSE.** `n10/p0` — ten drafted tokens with no probability
floor — runs at **0.967x**, slower than no speculation at all, on acceptance
0.298: two thirds of every draft is thrown away and the verification pass is not
free. The best arm is the most conservative one, `n4/p0.75`, at acceptance 0.902.
A reader tuning by "more drafting is more speed" would land on the one setting
that costs them throughput.

**The baseline still truncated, and that is the real story.** `spec-none` ran to
its 3,000 cap while every speculative arm terminated normally at 1,012–1,427
tokens, on the SAME prompt with the SAME greedy sampler. Reading the tail
(rule 20: spot-read long greedy output for repetition loops before trusting its
tokens) shows why — it is in a **degeneration loop**, cycling near-identical
`if (sibling.color === RedBlackTree.BLACK && ...)` branches with permuted
conditions until the cap stops it.

### Speculation is NOT output-preserving here — and the alternative was tested

Six arms produced six different texts at temperature 0. The tempting reading is
"speculation changes the output", which would make the 1.238x speedup not free.
That reading is not earned until the cheaper explanation is ruled out: at a
degeneration loop's near-tied logits, any perturbation of the execution path can
flip a tie, so the divergence might simply be numerical nondeterminism.

Two configurations, two repeats each, fresh server every time, n_predict 4,096:

| config | rep 1 | rep 2 | reproducible |
|---|---|---|---|
| spec-none | 16,407 chars, n=4096, **length** | 16,407 chars, n=4096 | **YES** — sha `26feb103aaf7` both |
| spec-n4-p0.75 | 4,100 chars, n=1135, **stop** | 4,100 chars, n=1135 | **YES** — sha `363a2a0005b4` both |

**Greedy decoding on this box is bit-reproducible.** Nondeterminism is ruled
out, so the divergence is real: `--spec-type draft-mtp` on this model and this
build **changes the generated text**. Lossless rejection sampling would forbid
that; whatever this path is doing, it is not that.

Two consequences, and they are not the same claim:
1. **The speedup and the output are entangled.** "1.238x faster, same answer" is
   not available here and must never be published. What is measurable is
   "1.238x faster, different answer".
2. **On this prompt the speculative answer is the better one** — it terminates
   with a complete class in 1,135 tokens where the non-speculative path
   degenerates and runs past 4,096. That is one prompt and is not a quality
   claim; Stage 6 decides quality.

### What this costs the campaign, stated plainly

`spec-none` is measuring a repetition loop on this prompt, so it is not a
throughput baseline and the `vs none` column above is provisional. Worse, the
**Stage-1 floors used the same temp-0 / top_k-1 sampler**, which is this repo's
standard speed-probe setting; they ran only 300 tokens and show no loop, but the
sampler that degenerated here is the sampler that took them. Before any locked
recipe quotes a floor, the floors need a loop check — `scripts/bench/loop-detect.py`
exists for exactly this and has not yet been run over them.

### THE ARBITER — BF16, and the ladder was being read from the wrong end

| arm | PPL | ± | vs BF16 |
|---|---|---|---|
| **BF16 (unquantized)** | **9.0355** | 0.0690 | — |
| Q8_0 vendor | 9.0460 | 0.0691 | +0.011 (**0.1σ**) |
| Q8_0 protoLabsAI | 9.0519 | 0.0692 | +0.016 (**0.2σ**) |
| IQ2_M | 8.6629 | 0.0586 | −0.373 (4.1σ) |
| Q4_K_M | 7.9544 | 0.0553 | **−1.081 (12.2σ)** |

All five tokenized identically (36 chunks, n_ctx 8192), so the comparison is sound.

**CORRECTION, and it reverses this campaign's own earlier framing.** This log
previously recorded "Q8_0 is worse than the 2-bit file" and hunted a defect in
Q8_0. That was reading the ladder from the wrong end. **Q8_0 is near-perfect** —
0.1–0.2 σ from the unquantised weights, which is exactly what a Q8_0 is for.
**Q4_K_M is the anomaly**, scoring 1.08 PPL *better than the weights it was made
from*, at 12.2 σ. A quantisation cannot genuinely beat its own source. Here a
LOW perplexity is the suspicious reading, not the good one.

### Two hypotheses, one run, at BF16

The campaign was handed a third-party analysis claiming that MTP degrades output
on quantised models because speculation forces GEMM instead of GEMV, and
floating-point under low-bit quantisation is not associative — with the explicit
claim that *"MTP does not impact output quality only holds true under
unquantised BF16 precision."* That is a mechanism, and it is testable with a
file this campaign already has.

Same script as the Q4_K_M determinism test, target swapped to BF16, two repeats
each, fresh server every time, temp 0 / top_k 1, n_predict 4,096:

| target | config | rep 1 | rep 2 | reproducible |
|---|---|---|---|---|
| Q4_K_M | spec-none | 16,407 ch, n=4096, **length** | identical | yes |
| Q4_K_M | spec-n4-p0.75 | 4,100 ch, n=1135, stop | identical | yes |
| **BF16** | spec-none | 9,478 ch, n=2563, **stop** | identical | yes |
| **BF16** | spec-n4-p0.75 | 8,950 ch, n=2547, **stop** | identical | yes |

**Hypothesis A — the quantisation mechanism: NOT SUPPORTED.** MTP changes the
generated text at **BF16 too** (`3dbaf65806f6` vs `c4075dada3b6`, both
bit-reproducible across repeats). If non-associative low-bit arithmetic were the
cause, BF16 would converge. It does not. **CAVEAT, and it makes this a partial
test:** the draft head is `mtp-…-head-Q8_0.gguf` and stays quantised even when
the target is BF16, so this refutes "the TARGET's quantisation causes it" and
does not touch "the DRAFTER's quantisation causes it". A BF16 draft head would
close that, and none is published.

**Hypothesis B — Q4_K_M's low PPL is tied to degeneration: SUPPORTED.** At BF16
the non-speculative greedy run **terminates cleanly** at 2,563 tokens. At
Q4_K_M, the identical prompt and sampler **loops to the 4,096 cap**. The
quantisation induces a degeneration the unquantised weights do not have.

Two measured facts, and the link between them labelled as what it is:
- BF16 does not loop on this prompt; Q4_K_M does. *Measured*, two bit-identical
  repeats each.
- Q4_K_M scores 1.08 PPL below BF16. *Measured*, 294,912 positions.
- **Repetitive text is low-entropy, and low-entropy text scores low perplexity**,
  so a model biased toward repetition scores *better* on the rule-6 instrument
  while being *worse* to use. That is a HYPOTHESIS linking the two, it is
  mechanically plausible, and nothing here tests it directly. Testing it means
  measuring the repetition rate of the corpus continuations, not the code prompt.

**If it holds, it is a warning about the instrument itself**: rule 6 ranks quants
by perplexity, and perplexity rewards the failure mode that hurts a reader most.

### THE HARNESS GAP THIS EXPOSES (campaign goal 2)

Checked, not assumed:
- **No arm file in this repo scores quality with speculation on versus off.**
  All six of `scripts/arms/spec-sweep.json`'s arms, and `acceptance.json`,
  measure throughput and acceptance only; none carries `bench_arms`.
- **METHODOLOGY contains no rule requiring speculation to preserve output.**
  The only "preserve" hits are `reasoning-preserve` across turns, unrelated.
- **Rule 11 frames speculation purely as a throughput axis**: "Acceptance IS the
  speculative speedup, but MEAN DRAFT LENGTH is the throughput predictor —
  publish both, always."

So the harness would have published "1.238x at acceptance 0.902" and a reader
would reasonably have concluded speculation was free. **This campaign only caught
it because the response bodies were hashed** — luck, not process. `arms.py` saves
the generated text (`--save-responses`) and nothing ever compares it.

### KLD settles it: perplexity ranked the quants in EXACTLY reverse fidelity order

The hypothesis was that Q4_K_M's low perplexity is not fidelity. KL-divergence
against the unquantised BF16 logits answers what perplexity cannot — perplexity
asks only "what probability did you give the token that actually came next",
while KLD compares the whole distribution. 32,768 positions, same frozen corpus,
Q8_0 as the control (0.1 σ from BF16 on PPL, so its KLD must be ~0 or the
instrument is broken).

| arm | mean KLD | median KLD | same top-1 | PPL | PPL rank |
|---|---|---|---|---|---|
| Q8_0 | **0.009766** | 0.000750 | **97.998%** | 9.0519 | **3rd** |
| Q4_K_M | 0.130086 | 0.035664 | 87.112% | 7.9544 | **1st** |
| IQ2_M | 0.363336 | 0.148640 | 76.740% | 8.6629 | 2nd |

```
fidelity order (KLD, closest to BF16 first):  Q8_0  <  Q4_K_M  <  IQ2_M
perplexity order (best PPL first)          :  Q4_K_M  <  IQ2_M  <  Q8_0
```

**KLD is perfectly monotonic in bit-width. Perplexity is exactly inverted.**
Q4_K_M diverges **13.3×** further from BF16 than Q8_0 does while scoring 1.10
PPL *better*, and disagrees with BF16's top token on **12.9% of positions — one
in eight**. The control behaved: Q8_0's KLD is 0.0098 and it keeps BF16's
argmax 98.0% of the time.

So the low perplexity was never fidelity. It is a different distribution that
happens to score better on the one question perplexity asks, over text where
most next-tokens are easy. And 12.9% argmax disagreement is more than enough to
explain both the greedy divergence and the degeneration loop measured earlier at
Q4_K_M and absent at BF16.

**This is a finding about rule 6's instrument, not just about this model.**
Rule 6 says quants are RANKED by perplexity over 294,912 token positions. On
this model that ranking is precisely backwards, and a campaign that followed the
rule to the letter would have crowned the least faithful file in the roster and
screened out the most faithful one at the Stage-1 gate. The repo already ships
KLD tooling (`scripts/quant-ladder/kld-ladder.py`, `kld-blocks.py`) — it is not
a missing capability, it is a missing *requirement*.

### A1 — loop scan over every transcript kept (2026-09-01)

Stage 1 saved only 400 characters per floor probe, so the floors could not be
loop-checked from what was written down — rule 28 the hard way, and the reason
this task re-takes them with the full text kept. Detector:
`scripts/bench/loop-detect.py`'s D5 signals, the repo's own.

| floor | predicted_n | finish | verdict |
|---|---|---|---|
| Q8_0 | 700 | length | ('clean', []) |
| Q4_K_M | 700 | length | ('clean', []) |
| IQ2_M | 700 | length | ('clean', []) |

Spec-sweep transcripts: spec-mtp-n10-p0.5__rep1__00-rbtree-code.txt=('LOOP', ['N3-compresses!', 'N4-vocab-collapse!']), spec-mtp-n10-p0__rep1__00-rbtree-code.txt=('LOOP', ['N3-compresses!', 'N4-vocab-collapse!']), spec-mtp-n16-p0.5__rep1__00-rbtree-code.txt=('LOOP', ['N3-compresses!', 'N4-vocab-collapse!']), spec-mtp-n4-p0.75__rep1__00-rbtree-code.txt=('LOOP', ['N3-compresses!', 'N4-vocab-collapse!']), spec-mtp-n6-p0.5__rep1__00-rbtree-code.txt=('LOOP', ['N3-compresses!', 'N4-vocab-collapse!']), spec-none__rep1__00-rbtree-code.txt=('LOOP', ['N3-compresses!', 'N4-vocab-collapse!'])

**Floors showing a loop: none**

### A2 — the speculation speedup on a baseline that does not loop

| arm | t/s | predicted_n | finish | loop verdict | sha |
|---|---|---|---|---|---|
| prose/spec-none | 118.68 | 2511 | stop | ('clean', []) | `d420d0c9a4332bd0` |
| prose/spec-n4-p0.75 | 128.87 | 3000 | length | ('clean', []) | `b0a3b7c051b29b18` |
| code/spec-none | 118.24 | 3000 | length | ('clean', []) | `e3b0c44298fc1c14` |
| code/spec-n4-p0.75 | 132.32 | 3000 | length | ('clean', []) | `e3b0c44298fc1c14` |

### A3 — acceptance is a property of the CONTENT (rule 11)

Same server, same flags (draft-mtp n4/p0.75), two regimes:

| regime | t/s | acceptance | predicted_n |
|---|---|---|---|
| novel-code | 140.63 | 0.8885 | 1500 |
| verbatim-prose | 127.98 | 0.9171 | 1206 |

## Stage 4 — APPETITE  ·  2026-09-01

The effort knob on this model is `enable_thinking`, BOOLEAN, so the sweep is two
arms and not four levels. Six reasoning prompts per arm, cap 16,384, temp 0.

| arm | probes | min | median | max | truncated |
|---|---|---|---|---|---|
| thinking-on | 6 | 736 | 2099 | 3605 | 0 |
| thinking-off | 6 | 414 | 837 | 1671 | 0 |

**Derived caps (rule 7 — above the upper tail, never the median): {"thinking-on": 5407, "thinking-off": 2506}**

This is the gate on Stage 6. A benchmark run at a cap below the upper tail does
not degrade gracefully: it truncates, and a truncated answer scores 0.0, which
the report would publish as model quality.

### E1 — the KLD ladder at rule 6's own position count (294,912)

| arm | mean KLD vs BF16 | median KLD | same top-1 |
|---|---|---|---|
| Q8_0 | 0.016143 | 0.000821 | 97.633% |
| Q4_K_M | 0.209331 | 0.0421 | 85.868% |
| IQ2_M | 0.441164 | 0.1571 | 75.994% |

### E4 — the roofline claim, tested against hardware counters (2026-09-01)

Stage 1 back-solved rule 10's efficiency constant per format — 0.82 / 0.73 /
0.54 — and this campaign has been leaning on IQ2_M's 22% shortfall to claim that
at 2 bits the workload stops being memory-bound and becomes unpack-bound. That
was a RATIO against a CITED peak. Nsight reads the hardware.

Aggregate over the sampled kernels (means include small kernels, so absolute
percentages are diluted — the per-kernel view below is the one that answers it):

| arm | SM %peak | DRAM %peak | achieved GB/s | % of 936 | kernels |
|---|---|---|---|---|---|
| Q8_0 | 11.88 | 19.40 | 176.3 | 18.8% | 22 |
| Q4_K_M | 14.46 | 19.51 | 176.9 | 18.9% | 23 |
| IQ2_M | 13.60 | 11.40 | **103.5** | **11.1%** | 24 |

**The dominant matrix-vector kernels, which is where the answer is:**

| arm | kernel | SM %peak | DRAM %peak |
|---|---|---|---|
| Q8_0 | `mul_mat_vec_q<type 8>` | 45.3 | **89.7** |
| Q8_0 | `mul_mat_vec_q<type 8>` | 29.6 | 52.4 |
| Q8_0 | `gated_delta_net_cuda<128>` | 36.0 | 48.1 |
| IQ2_M | `mul_mat_vec_q<type 12>` | 52.2 | 60.1 |
| IQ2_M | `mul_mat_vec_q<type 22>` | **63.2** | 48.9 |
| IQ2_M | `mul_mat_vec_q<type 21>` | **56.9** | 40.0 |

**CONFIRMED, and now with a mechanism.** Q8_0's busiest kernel runs at **89.7%
of DRAM peak** against 45.3% SM — textbook memory-bound. IQ2_M's busiest kernels
invert it: SM throughput MEETS OR EXCEEDS DRAM throughput on all three. The
balance has flipped to compute.

The aggregate bandwidth says the same thing from the other side: Q8_0 and
Q4_K_M both move ~176 GB/s while **IQ2_M moves only 103.5 GB/s — 41% less, from
the smallest file on the roster.** A bandwidth-bound kernel reading fewer bytes
per weight should move data at least as fast. It moves less, because the time
goes into unpacking.

So rule 10's constant falling 0.82 → 0.73 → 0.54 is not an artefact of the
citation: it tracks a real shift along the roofline, and the 2-bit file is on
the compute side of it.

**What this is worth to a silicon reader.** Low-bit inference on this
architecture does not want more HBM — Q8_0 is already at 90% of DRAM peak on its
hot kernel and IQ2_M cannot even reach half of it. It wants faster dequant: the
`mul_mat_vec_q` variants for the IQ formats are SM-limited, so the lever is
unpack throughput and LUT bandwidth, not memory. `gated_delta_net_cuda` showing
up in the top three is the hybrid's recurrent path, and it sits mid-roofline
(SM 36.0 / DRAM 48.1) rather than at either wall.

**Conditions and limits, stated.** 22–24 kernels sampled per arm past a
200-launch warm-up — a bounded steady-state sample, not the whole run. The
936 GB/s peak is CITED (machine.json carries null) and must be re-checked
against NVIDIA's page before publication. Profiling requires admin
(`RmProfilingAdminOnly: 1`), so this table is impossible in an unelevated
campaign — the other side of the trade Stage 0 recorded.

**`nsys` is unusable on this box** and the task dropped it: apt
nsight-systems 2023.4.4 writes a `.qdstrm` and then reports "The importer binary
and its dependencies were not found", so no readable report is ever produced.
Its raw captures are ~500 MB each and are now ignored by extension (rule 29:
ignore by extension or by a directory of pure bulk — a profiler intermediate
whose every published number lands in data/*.json is exactly that).

### The enable_thinking anomaly — RESOLVED, and it was the extractor

Stage 4 recorded `think_chars: 0` on all twelve appetite probes and flagged that
thinking might never have been enabled — which would have made the effort axis
unpublishable (rule 2). It was enabled. The template gates it like this:

```jinja
{%- if enable_thinking is defined and enable_thinking is false %}
    {{- '<think>\n\n</think>\n\n' }}     ← OFF: a pre-closed empty block
{%- else %}
    {{- '<think>\n' }}                    ← ON: an OPEN tag, emitted in the PROMPT
{%- endif %}
```

and llama.cpp with `--jinja` then **parses the reasoning out of the completion
into a separate `reasoning_content` field**. Measured 2026-09-01, same question,
temp 0, reproducing B1's q5 token counts exactly (1460 on / 1671 off):

| `enable_thinking` | message keys | content | reasoning_content |
|---|---|---|---|
| **true** | content, **reasoning_content**, role | 1,599 ch | **2,175 ch** |
| false | content, role | 4,157 ch | — |

The probe searched `content` for `<think>…</think>` tags the server had already
removed. **B1's appetite distribution stands** — `predicted_n` counts reasoning
and answer together — and the derived cap is unaffected.

A behavioural finding falls out of the same run: with thinking ON the model
reasons privately for 2,175 characters and then answers in 1,599; with it OFF it
writes a 4,157-character worked answer inline. Same question, same sampler. The
knob does not simply add tokens — it moves them from the answer into the
reasoning, and shortens what the reader is shown.

---

## Stage 5 — RECIPE LOCK  ·  2026-09-01  ·  DATED AND CLOSED

Rule 25: no expensive run may start above this line. Everything below is locked
against measurements already in this log; nothing here is projected.

### THE RANKING DECISION: fidelity (KLD), not perplexity

This campaign's two instruments disagree, and the lock has to choose:

| arm | mean KLD vs BF16 (294,912 pos) | same top-1 | PPL | PPL rank |
|---|---|---|---|---|
| Q8_0 | **0.016143** | 97.6% | 9.0519 | 3rd |
| Q4_K_M | 0.209331 | 85.9% | 7.9544 | 1st |
| IQ2_M | 0.441164 | 76.0% | 8.6629 | 2nd |

**Ranking by KLD.** Perplexity ranked these in exactly reverse fidelity order,
and BF16 settled which end was wrong: Q8_0 sits 0.1 σ from the unquantised
weights while Q4_K_M scores 1.08 PPL *better than the weights it was made from*.
A quantisation cannot beat its own source; low perplexity here is a differently
shaped distribution, not a better model. Rule 6's letter would have crowned
Q4_K_M and screened out Q8_0 at the Stage-1 gate. Proposed rule 33 carries the
argument; this lock acts on it.

### LOCKED RECIPES

**R1 — QUALITY (the default recommendation).** `Q8_0`, `-ngl 99`, `-c 262144`,
mmproj resident, `--spec-type none`.
- KLD 0.016 from BF16, keeps its argmax 97.6% of the time — the only arm on the
  roster that is faithful to the model the vendor published.
- Measured fit: 20,336 MiB of a 24,122 MiB budget **with vision AND the draft
  head resident** — the full 262,144-token window, 3,786 MiB spare.
- Floor 78.30 t/s (Stage 1) / 83.59 t/s (A1 re-take, loop-clean). The 6.8 %
  spread between takes is unexplained and is rule 30 territory; **quote the
  lower**.
- Speculation is OFF in this recipe deliberately — see R2.

**R2 — SPEED, with a condition that must travel with it.** `Q4_K_M`,
`--spec-type draft-mtp -md <mtp head> --spec-draft-n-max 4 --spec-draft-p-min 0.75`.
- 148.03 t/s against a 119.56 t/s in-sweep baseline = **1.238×**, acceptance
  0.902, the best of six arms. `n10/p0` is **slower than no speculation at all**
  (0.967×, acceptance 0.298) — more drafting is not more speed.
- **The output is NOT preserved.** Speculation on and off produce different text
  at Q4_K_M *and* at BF16, with nondeterminism ruled out by bit-identical
  repeats. This recipe is "1.238× faster at a DIFFERENT answer", never "the same
  answer faster" (proposed rule 32).
- Q4_K_M is 13× further from BF16 than Q8_0 and disagrees with its argmax on one
  token in eight. R2 is a latency recipe, not a quality one, and the report must
  not let a reader mistake it for one.

**NOT RECOMMENDED — IQ2_M.** KLD 0.441, keeps BF16's argmax only **76.0%** of the
time: one token in four differs from the published model. And it barely pays:
131.30 t/s against Q4_K_M's 118.38 is **1.11× for 0.67× the bytes**, because at
2 bits the kernels are compute-bound, not bandwidth-bound (E4: SM throughput
meets or exceeds DRAM on all three of its hot kernels, and it moves 103.5 GB/s
against Q4_K_M's 176.9). It is published as measured and screened out, never as
untested.

### LOCKED CAPS AND CONDITIONS FOR STAGE 6

- **n_predict cap: 5,407** for thinking-on arms (rule 7: B1 measured max 3,605
  with ZERO truncations at 16,384, so this is a true upper tail × 1.5, not a
  lower bound). Thinking-off arms: 2,506.
- **Effort axis is two arms**, not four: `enable_thinking` is boolean.
- **Desktop is LIVE** on every number (GNOME + Steam + browser, 454 MiB). Rule 27
  says that costs decode invisibly; it is a condition of the sweep, equal across
  arms.
- **Idle baselines**: cold 28.09 W, loaded 31.12 W, both P8-settled from the
  continuous logger — NOT the 37.71 W Stage 0 recorded inside the settling tail.
- **Backend**: cuda, llama.cpp b10717, commit a32af33de2b5, sm_86, driver
  580.173.02.

### WHAT STAGE 6 MAY NOW SPEND HOURS ON

1. **GPQA Diamond, all 198, on R1, thinking ON, cap 5,407** — against the
   vendor's published **86.4**. This is the harness-validation anchor, and the
   distance is a measurement OF THE HARNESS, not of the model.
2. The rule-21 seven-benchmark suite at n=25 on R1.
3. Vision (mmproj resident) with the rule-19 hallucinated-sight hunt.
4. Energy attribution over the arms already run — the 500 ms logger has been
   up since Stage 0, so they are already attributable.

**RECIPE LOCK CLOSED 2026-09-01.** Expensive work may now begin.

### AMENDMENT to the RECIPE LOCK — the GPQA cap was wrong, caught at question 2

The lock set `n_predict 5,407` for thinking-on arms, derived from Stage 4's
measured appetite (max 3,605 across six reasoning prompts × 1.5). A two-question
pilot of the real benchmark truncated immediately:

```
prompt 1/2: 1577 tok, CORRECT
prompt 2/2: 5407 tok, wrong (TRUNCATED)
```

**Appetite is content-specific and Stage 4 sampled the wrong content.** Six
general reasoning prompts do not bound what GPQA Diamond asks for; bench.py
scores a truncated answer 0.0, so that question would have been published as
model quality — the exact failure rule 16 names and the lock exists to prevent.
The lock did not fail as a mechanism: it caught this at **question 2 of 198**,
before hours were spent, which is what the gate is for.

The repo already held the answer and this campaign did not read it forward:
`scripts/bench/run-gpqa-anchor.ps1` records that "GPQA at xhigh spends 4,247 to
over 16,384 output tokens per question on this rig, and a first pilot at a
16,384 cap truncated 3 of 9", and it uses **30,000 of a 32,768 window**.

**AMENDED CAP: 30,000, at `-c 32768`.** Following the measured precedent rather
than a second guess. The run validates its own cap: rule 7 is satisfied only if
the truncation count comes back ZERO, and the count is published either way.
Stage 4's 5,407 remains correct for what it measured — general reasoning — and
is not a benchmark cap.

**Cost, stated before it is spent:** at ~83 t/s a 30,000-token question is
6 minutes. 198 questions at the reference's observed mean (~6,000 tokens) is
~4 h; a pathological tail is longer. The run is resumable per question, so a
crash costs one question.

### The orphan guarantee did not exist on Linux — and two of my own claims were wrong

`gpu_lock.py`'s header lists three holes it was written to close after the
2026-08-29 host hang. Hole 2 is **"ORPHANS OUTLIVE THEIR PARENT"**, and its
stated fix is "the child is put in a Windows Job Object with
KILL_ON_JOB_CLOSE, so it cannot outlive the process that started it, even on
SIGKILL of the parent." `serve()`'s own docstring repeats it: "child gets a
commit cap and CANNOT outlive this process."

`_cap_child()` opens with `if not _WINDOWS or not cap: return False`. Nothing
set `PR_SET_PDEATHSIG`. **On Linux the guarantee did not exist at all** — and the
"could not job-cap" warning is gated on `if _WINDOWS`, so Linux got silence where
Windows got a loud line.

Measured here 2026-09-01: `kill <bench.py pid>` left `llama-server(396565)`
alive holding 10 GB of the card. The campaign watchdog's ORPHAN alarm is what
surfaced it — the same alarm that had produced two false positives an hour
earlier, which is why the debounce mattered rather than deleting the check.

**Two claims I made in this log today were wrong and are corrected here.** I
twice recorded that "gpu_lock.serve()'s child-cannot-outlive-parent guarantee
held under an abrupt kill". It did not. Every script in this campaign carries a
`finally: proc.terminate()`, so *my own cleanup* killed those servers and I read
the result as the guard working. The one time a process died without that
cleanup — `bench.py` under SIGTERM — the server survived, which is the case that
tells the truth.

**FIXED**: `serve()` now attaches `prctl(PR_SET_PDEATHSIG, SIGKILL)` via
`preexec_fn` on every POSIX launch, with or without an RLIMIT — the orphan guard
must not depend on a cap that `_posix_rlimit_wanted()` correctly refuses to set
for CUDA. Verified by SIGKILLing a parent with no cleanup path at all:

```
child pid 397614  alive before: True
parent SIGKILLed -> child alive: False
VERDICT: orphan guard HOLDS on Linux
```

Rule 20's third guard is now real on this platform instead of documented.

### CAVEAT on the Stage-3 speculation sweep: every arm is n=1

The sweep ran `repeat: 1` — one probe per arm, six arms. The ranking it produced
(n4/p0.75 best at 1.238x, n10/p0 *slower* than no speculation at 0.967x) is
therefore six single measurements, and rule 30's two-level effect alone spans
~13% on this class of rig. The **categorical** finding survives that — a 0.967x
arm and a 1.238x arm are 28% apart and the acceptance figures (0.298 against
0.902) move in the same direction, which is two independent cheap metrics
agreeing (rule 4). The **ordering of the middle arms** does not: n6/p0.5 at
1.158x and n10/p0.5 at 1.123x are 3% apart on one probe each and should be read
as a tie.

Drafting-knob sweeps are known to be noisy without a clean monotonic trend, so
single-run results from one are exactly the kind that need repeats before they
are trusted. Recorded rather than quietly re-run: the arm file says `repeat: 1`,
and any recipe quoting a middle arm needs `repeat: 3` first.

### CORRECTIONS from the architecture fact-check — 2026-09-01

An adversarial fact-check of this campaign's own ground-truth block found six
statements this log had asserted and could not support. They are corrected here
rather than edited away.

**1. "The in-file MTP layer is INERT in b10717" — WRONG, and it reverses a
retraction.** Nine loads, no exceptions:

| load | `--spec-type` | `unused tensor` warnings |
|---|---|---|
| stage1-Q8_0-server, stage2-{Q8_0,Q4_K_M,IQ2_M}-bare, stage2-Q8_0-proj | none | **15** |
| stage2-Q8_0-draft, -proj-draft; stage2-Q4_K_M-proj-draft; stage2-IQ2_M-proj-draft | draft-mtp | **0** |

`blk.32` is skipped **only when speculation is off**. Commit 86b4aef recorded it
as inert full stop, and concluded that third-party conversions dropping it are
runtime-identical. That holds only for a campaign that never enables
speculation — which is not a caveat this log attached, and Stage 0's original
rationale was closer to right than the retraction that replaced it.

**The mechanism is NOT yet established.** Every draft-mtp load above also passed
`-md <separate head>`, so these logs cannot distinguish "blk.32 becomes the draft
source" from "naming draft-mtp changes which tensors count as used". The
decisive test is `--spec-type draft-mtp` with NO `-md`; it needs the card and is
queued. Effect confirmed, explanation open.

**2. llama.cpp DECLINES to load blk.32; it does not load and ignore it.**
`src/llama-model-loader.cpp` logs the warning then executes
`size_data -= nbytes; return nullptr` — no tensor is created and the bytes leave
the allocation total. The 15 warnings carry byte sizes summing to 258,557,952 B,
so ~246.6 MiB of Q8_0 never becomes resident. This log's wording ("loads it and
throws it away") overstated what happens.

**3. The recurrent state is 50.25 MiB, not 51 MiB, and the 51 was
unverified.** 52,690,944 B from this build's own state-shape formula.
`model-Q8_0.json` ships the figure self-flagged `"verified": false` and this log
quoted it as measured.

**4. head_dim 256 is the ATTENTION head dimension.** The 24 recurrent layers run
at `ssm.state_size` 128. Substituting 256 into a recurrent state-size formula
overstates it fourfold — a trap this campaign came close to.

**5. Full attention sits at blocks 3, 7, 11, 15, 19, 23, 27, 31** — the LAST of
each group of four. Blocks 0, 1 and 2 are recurrent. Derived from this build's
`is_recr_impl[i] = (i < n_layer()) && ((i + 1) % full_attn_interval != 0)`
because the GGUF carries no `recurrent_layers` key. Any layer diagram that draws
attention first is wrong, and any partial-offload reasoning must know the
cache-holding layers are not the early ones.

**6. "Built on Qwen3.5 and Gemma4" attaches to Ornith-1.0, not 1.5.** The
vendor's own sentence is "It extends Ornith-1.0, which was developed on top of
Qwen3.5 and Gemma 4". Gemma-4-31B otherwise appears only as a baseline being
beaten, and no Gemma-4 trace exists in the 9B's config or tensor index. This log
repeated the misattribution in two commits.

**7. On the sampler deviation — this log overstated it.** The card carries TWO
presets: general (temp 1.0, presence_penalty 1.5) and precise coding (temp 0.6,
presence_penalty **0.0**), and both of the card's own Python examples use 0.6.
The GPQA run's `presence_penalty 0.0` therefore matches the card's coding preset
rather than departing from the card outright. Which preset a graduate science
benchmark should take is a judgement, not a deviation — and the open question
is still whether 1.5 would suppress the 28% truncation.

Also settled: there has never been a dense Qwen at 9B, so "the old Qwen 9B" names
a model that does not exist. The models people actually run at this size are
Qwen3-8B and Qwen2.5-7B-Instruct.

### 2026-09-01 — the GPQA anchor's score splits two ways, and the safety net was dropping the half that mattered

Checking whether this campaign could report GPQA-Diamond as *knowledge* and
*format* separately — rather than as one number mixing them — turned up a defect
in `bench.py` that had been live for the whole 10-hour anchor run.

`_grade_choice`'s docstring already promised the diagnostic: "run with
transcripts kept, and the unparsed rate can be recovered by re-running this
extractor over them." This run *is* keeping transcripts (`--transcripts`). But
the per-question crash-protection file — the thing that exists so a ten-hour run
is recoverable from disk rather than from scrollback — appended `rec` **after**
the response text had been popped out of it. Transcripts are serialised only by
`checkpoint_cb`, which fires once per dataset: for a single-dataset anchor run,
once, at the very end.

So at question 185 of 198 the on-disk state was 185 rows of tokens/score/
truncated and **zero generations**. Had the run died there, the score would have
survived and every text-dependent diagnostic would not have — rule 28 in the
exact shape the rule describes, and for a field that costs one short write per
question to keep.

Fixed the same day: the partial row now carries `response` whenever the run is
keeping transcripts. **The fix does not reach the run in flight** — Python read
`bench.py` at launch — so this anchor stays exposed until it completes. It did
complete, so nothing was lost; that is the only reason this is a fixed defect
and not a dead claim kept as a case study (rule 5).

`scripts/bench/rescore-choices.py` is the diagnostic the docstring promised.
Measured: truncated / empty-bodied / unparsed / bare-letter counts. Derived and
labelled as such: strict accuracy, lenient accuracy, format tax. The lenient
figure ships as a **ceiling** — a prose-tolerant extractor scores ~25% of lost
answers right by luck on four options — so the pair is published as a bracket
with every recovery attributed to the tier that made it. The strict pass imports
`datasets_io`'s regexes and cross-checks each item against `_grade_choice`; one
disagreement aborts.

This matters for the anchor's headline. The run's raw 68.5% against a published
86.4 currently has ~25% truncation inside it, and the truncation is already
separated. What was *not* separated is how much of the remaining gap is the
model not knowing versus the model not answering in the requested shape. That
number now exists to be read off the transcripts once the run lands, and it
belongs in the report beside the raw figure, not instead of it (rule 2).

### 2026-09-01 — GPQA-Diamond anchor lands: 71.7, and the decomposition says the gap is truncation, nothing else

`GPQA-Diamond: 71.7/100 (exact match, n=198, 43 truncated)`, Q8_0, cap 30,000,
seed 42, `presence_penalty 0.0`, `-c 32768`, `-ngl 99 --jinja`. Elapsed ~10 h.
Vendor publishes **86.4**.

Run through `rescore-choices.py` (zero GPU, from the saved transcripts):

| | count | rate |
|---|---|---|
| truncated — never reached an answer | 43 | 21.7% of 198 |
| empty visible reply | 1 | — |
| **unparsed** — finished, no letter the strict extractor could find | **0** | **0.0% of the 155 that finished** |
| bare-letter replies | 0 | 0.0% |

**Format tax: 0.0 pp.** Strict and lenient accuracy are the same number to one
decimal. This model's answer formatting on a four-option benchmark is not a
source of lost points — zero of 155 completed answers were unreadable. So the
distance from 71.7 to 86.4 is **entirely truncation plus genuine misses**, and
the split is: among the 155 questions it finished, Ornith scores **142/155 =
91.6%**, above the published figure. The published 86.4 and this 71.7 are not in
conflict; they are the same model measured with and without a token cap that
21.7% of its answers exceed.

Both figures ship, labelled, and neither alone (rule 2, rule 7). Rule 7 also
says what to do next and we have not done it: **raise the cap and rerun that arm
only** — never filter to the non-truncating questions, which is what quoting
91.6% by itself would be.

**A finding about the instrument, not the model.** Ornith emitted **zero**
bare-letter replies: it always writes "Answer: X" after prose. Under the
definition the model cards use when they quote a "format compliance"
percentage — the reply IS a single letter — this model scores **0%**. Under this
harness's extractor it is **100%** parseable. Same 198 generations, two
defensible readings of one phrase, 0 versus 100. Any published compliance
percentage is a property of the grader's definition at least as much as of the
model, and cannot be compared across reports that did not fix that definition
first (rule 3: the conditions travel with the number).

Defect found and fixed in the same pass: `rescore-choices.py` first reported
"truncated 0, 0.0%" for this run, because the transcripts file carries
index/prompt/response/tokens/score and **not** the `truncated` flag, which lives
only in the run JSON and the `.partial.jsonl`. It now recovers the cap from the
sibling run JSON, and refuses to print a truncation count at all when it cannot
— a confident zero where there is no measurement is worse than a gap.

### 2026-09-01 — matched-bpw format test: the codebook explanation is dead, and it was mine

The question this campaign has been carrying since Stage 1: the rule-10
efficiency constant falls as quantisation deepens (0.82 Q8_0, 0.73 Q4_K_M, 0.54
IQ2_M). Two explanations were live — **the IQ codebooks**, whose lookup-table
unpacking would burn SM cycles the K-quants do not, or simply **bits per
weight**. The 27B ladder already leaned to bpw (`Q2_K_XL`, no codebook, sat on
the interpolated line). This settles it directly: two files of the same model at
the same size, one of each family, in ONE sweep.

| arm | family | bpw | tg128 | rule-10 k | SM %peak | DRAM %peak | KLD | same-top |
|---|---|---|---|---|---|---|---|---|
| Q2_K | K-quant, no codebook | 3.4196 | 125.10 t/s | 0.512 | 15.95 | 11.80 | 2.2738 | 41.1% |
| AD-IQ3_XXS-IQ2_S | IQ, codebook/LUT | 3.4272 | **134.75 t/s** | **0.552** | 14.22 | 13.45 | **0.2454** | **80.7%** |

The two files are 0.22% apart in bits per weight — as matched a pair as the
published quant ladders allow.

**The codebook arm is FASTER, by 7.7%, and its rule-10 constant is HIGHER.** The
explanation predicted the opposite sign. It also predicted the codebook arm
would do more compute per unit time, and the counter says it does **less**: SM
15.95% for the no-codebook arm against 14.22% for the codebook one. There is no
reading of this pair in which lookup-table unpacking is what pulls k down.

So: **the effect is real and the explanation was wrong.** k does fall with
quantisation depth — Stage 1 measured that, and it stands. It does not fall
because of codebooks. This is the second time in this campaign that a real
number arrived wearing a wrong mechanism, which is the failure AGENTS.md lists
without a rule number, and it was caught only by building the experiment that
could falsify it rather than the one that would illustrate it.

Rule 5: the dead claim stays, dated. **"IQ2_M is dequant-bound because of its
codebooks" — proposed 2026-09-01 from the Stage 1 constants, killed 2026-09-01
by this pair.** What survives is the weaker, measured statement: at ~3.4 bpw
this workload is neither cleanly bandwidth-bound nor cleanly compute-bound, both
counters sit low, and bits per weight predicts k better than format does.

**Conditions, because two of these numbers do not travel (rule 3).**
- The KLD here is over **32,768 positions** (`-c 8192 --chunks 4`), which is a
  SCREEN. Rule 6 ranks on **294,912**. These values may not be placed beside the
  full-depth ladder (Q8_0 0.016143, Q4_K_M 0.209331, IQ2_M 0.441164) — that is a
  cross-depth comparison and rule 23 forbids it. A 9× gap will not reverse at
  greater depth, so the *direction* is safe; the *values* are not rankable.
- The SM/DRAM percentages are **means over all sampled kernels**, where
  `data/ncu-roofline.json` reported **hot-kernel** figures. That is why these
  read 12–16% against the earlier 89.7%. The two sets are not comparable to each
  other. Within this pair, measured the same way, they are.

**The practical finding, which is larger than the methodological one.** At the
same file size, Q2_K is not merely worse, it is broken for this architecture:
**41.1% same-top against 80.7%**. And Q2_K's file is *bigger* than IQ2_M's (3.83
GB vs 3.60 GB) while agreeing with the base model on far fewer tokens. A reader
choosing a ~3.5 GB file for this model should take the adaptive IQ mix; there is
no axis measured here on which Q2_K wins.

**Hypothesis, explicitly not a finding.** This model is 24 recurrent
gated-delta layers to 8 full-attention ones. A uniform K-quant that damages the
recurrent state projections would degrade far worse than an adaptive mix that
spends its bits where they matter. That is a plausible mechanism and it is
exactly the kind of story that just proved wrong above, so it is written down as
a hypothesis with a test attached — per-tensor KLD attribution — and nothing in
the report may lean on it until that runs.

### 2026-09-01 19:26 — rule-21 suite launched on R1, on the suite hash the 27B campaign ran

`--rule21 --suite scripts/bench/suites/rule21-n25.json`, Q8_0, `--ctx 32768`
(the harness's own check: longest prompt ~8,191 tok + 16,384 cap = 24,575
needed), `-ngl 99 --jinja`, transcripts kept. Suite hash **1cdf54f8eb9d3f8f** —
the same one every published `qwen38-27b-blind` arm carries, so rule 23's
comparability gate is satisfied by construction rather than by hope.

**Checked before spending the hours, because the frozen file misleads a reader
of it.** `rule21-n25.json`'s own `settings` block says `temperature 1.0`,
`presence_penalty 1.5`, `top_k 20` — and that is **not** what the published runs
used. `--greedy` is applied AFTER the suite's sampler (`bench.py:667`), so the
27B arms ran at temp 0.0 / top_p 1.0 / top_k 1 / pp 0.0, which their result JSONs
confirm. Passing `--suite` ALONE would have run a different sampler under the
same suite hash — two runs that rule 23 would call comparable and that were not.
The hash covers the PROMPTS, not the sampler; only the settings block travels
with the prompts, and it is stale. Worth a rule-3 note in the report: a suite
hash is a claim about inputs, not about conditions.

**ALPACA and MT-Bench stay unscored** — no independent judge endpoint. That is
the Stage 0 interview question added this campaign (SKILL.md item 8) and it is
still open. Both keep transcripts, so a judge can score them later without
re-running the model, and the composite Mean records them as excluded rather
than dropping them silently.

The watchdog rewrite was exercised end to end by this transition, on live data
rather than stubs: **OFF-CARD 19:20:33** (matched-bpw job alive, card free
during its download) → **IDLE 19:21:19** (job exited) → **BUSY 19:26:35** (suite
took the card). The old implementation could not emit the first of those three.

### 2026-09-01 19:36 — rule 24 had no supervisor, and 18 hours of energy data was in an inode with no name

An adversarial audit of the durability scripts returned 24 verified findings.
The one that mattered was live: **the campaign power logger had been writing to
an unlinked file since 01:31**, and it was now 19:35.

`data/power/campaign-power.csv` is git-tracked. A working-tree-materialising git
command replaced the inode under the running `nvidia-smi`, which kept appending
to the old, now-nameless one. Everything downstream kept saying the campaign was
instrumented: the sidecar's `"running": true` is written once at start and never
revisited, `sample-power.sh` verifies growth only at `start`, and the watchdog —
the only thing supervising this campaign continuously — had no opinion about the
logger at all. The on-disk CSV had not grown in **18 hours** and was being
faithfully committed and pushed at its 01:31 size the whole time.

Everything measured after the RECIPE LOCK sat inside that window: the KLD ladder,
the ncu roofline, the GPQA anchor, the matched-bpw pair. Under rule 24 —
*energy is measured or it is absent* — all of it was about to resolve to absent.

**Recovered, because the process was still alive.** An unlinked file is still
readable through the holder's own descriptor:

    cat /proc/362231/fd/1 > campaign-power.csv     # 149,983 rows, 14.3 MB

The on-disk file proved a **strict byte prefix** of the recovery, so nothing had
to be merged. The trace is continuous — 22:45:07 Aug 31 to 19:36:24 Sep 1,
median sampling interval **0.500 s exactly**, largest gap **1.4 s** across 20 h
50 m. One `nvidia-smi` exit and it would have been gone at any price (rule 28,
and the only time in this campaign the "at any price" clause has been literally
true rather than rhetorical).

The old logger was then stopped and a linked one started as
`campaign-power-part2-from-1936.csv`. **Recorded gap in coverage: 19:36:24 →
19:37:0x, roughly 40 s**, during which the rule-21 suite was running unlogged.

**The structural fix, which is the point.** Two defects, both now tested:

1. `power_health()` in the watchdog. Every poll, it checks whether any
   `nvidia-smi` writing for this slug has a `(deleted)` target, or whether none
   is running at all, and says so once per transition. The harness already owned
   the detector — `sample-power.sh list` prints the unlinked warning — but
   nothing ran it on a schedule and nothing put it in the resume checklist.
2. `stalled()` was scanning the directories the durability layer writes into, so
   the watchdog's own log, the autopush log and the 500 ms power CSV each reset
   the alarm that watches for a wedged job. **Repairing the power logger would
   have silently disabled stall detection outright** — the only reason the
   detector worked at all was that the CSV's mtime was frozen by the very bug
   above. `_campaign_writes()` now excludes the durability layer by name.

`scripts/verify/test-watchdog-state.sh` covers all three: 13 cases, and the
pre-fix script fails 5 of them (all three `stalled()` self-refresh paths and
both `power_health` alarms). `stalled()` previously had no test at all.

### 2026-09-01 — a rule 27 violation of my own making, recorded rather than buried

The durability audit ran **35 subagents** on this box between roughly 19:12 and
19:32. The rule-21 suite started at **19:26:03**. They overlapped for about six
minutes, which covers most of the GSM8K arm.

Rule 27: a speed measurement requires a QUIET MACHINE, and a busy HOST costs
decode invisibly — −5.4% mean, −24.0% worst, r = −0.924. So **the `tok_s`
figures for the GSM8K arm of this suite were taken on a machine that was not
quiet**, and they are not comparable to the rest of the suite or to any other
sweep. Load average was 1.22 by 19:40, after the workflow had drained.

**The scores are unaffected and the timings are.** Decoding is greedy, seed 42,
and this campaign already established bit-identical repeats, so host load moves
timing and not logits. GSM8K's accuracy stands; its throughput does not, and it
is flagged rather than quietly averaged into anything. If a clean number is
wanted, rule 7's remedy applies unchanged — rerun that arm only.

Writing this down because the alternative was not noticing: nothing in the
harness watches for the agent itself being the noisy neighbour.

### 2026-09-01 — rule 20's loop check never ran on the Stage-1 floors

`data/loop-scan.json`, task A1, `fresh_floor_probes`:

    Q8_0     chars=0   verdict=clean
    Q4_K_M   chars=0   verdict=clean
    IQ2_M    chars=0   verdict=clean

All three `work/a1-floor-*.txt` are **0 bytes on disk**. The detector was handed
the empty string and returned `clean`, three times, and the campaign recorded a
passing rule-20 check that had inspected nothing.

**Why it read nothing.** `runner.py`'s `ask()` returned
`message["content"]`. With `--jinja`, llama.cpp splits a thinking model's output
and puts the chain-of-thought in `reasoning_content`; for these probes the
visible reply was empty and the entire 700-token generation was in the field
nobody read. This is the third appearance of that one mistake in this campaign —
it also produced `think_chars: 0` on every appetite probe, and it is why Stage 4
briefly looked like thinking was disabled.

**Why it matters more than a missing check.** The very same file scores **LOOP
on all six** spec-sweep transcripts, at the same `temp 0 / top_k 1` sampler the
Stage-1 floors used. Looping is not hypothetical for this model under that
sampler — it is demonstrated, six times, in the same JSON. So the floors
**78.30 / 118.38 / 131.30 t/s** carry a rule-20 check that was never performed,
on a sampler already known to degenerate here. A1's own docstring says it exists
because Stage 1 saved too little text to loop-check; its remedy reproduced the
disease it was written to cure.

**Three fixes, in increasing order of how much they matter.**

1. `ask()` now returns `reasoning`, `text` and `full`, and A1 scans **`full`**.
   Rule 20 protects "its tokens or timings", and the timings count every
   generated token — so a loop inside the thinking block is exactly the loop
   that corrupts a throughput number.
2. A1 is queued to re-run behind the rule-21 suite
   (`work/chain-after-rule21.py`), clearing only `A1` from `runner-state.json`
   and recording why in a `reruns` entry. Rule 7's shape: rerun that arm only.
3. **`loop-detect.py` can no longer certify emptiness as health.** Every signal
   returns 0.0 on the empty string, 0.0 clears no threshold, and `verdict()`
   fell through to `("clean", [])`. It now returns **`NO-DATA`** below
   `MIN_WORDS`, with the message saying in words that this is not a clean
   verdict but the absence of one. This is the fix that generalises: the caller
   bug was one line, but the detector was structurally willing to bless nothing.

**The floor was chosen against the detector's own corpus, not a priori.** The
first attempt used 120 words — one full N4 window — and turned **62 of the 75**
validation answers into NO-DATA, because real benchmark answers are short and
`n4_worst_window_ttr` already declines them by returning 1.0 below `win*2`
rather than pretending to a verdict. A floor that refuses in-distribution
answers does not make a detector safer, it makes it silent, which is the failure
being fixed. At **15 words** the validation baseline is unchanged except for the
four answers that were being blessed on almost no text:

    before:  {clean: 71, hint: 3, LOOP: 1}      false positives: 1
    after:   {clean: 67, hint: 3, LOOP: 1, NO-DATA: 4}   false positives: 1

The one false positive is pre-existing and untouched.

### A1 — loop scan over every transcript kept (2026-09-01)

Stage 1 saved only 400 characters per floor probe, so the floors could not be
loop-checked from what was written down — rule 28 the hard way, and the reason
this task re-takes them with the full text kept. Detector:
`scripts/bench/loop-detect.py`'s D5 signals, the repo's own.

| floor | predicted_n | finish | verdict |
|---|---|---|---|
| Q8_0 | 700 | length | ('LOOP', ['N4-vocab-collapse!']) |
| Q4_K_M | 700 | length | ('hint', ['N4-vocab-collapse']) |
| IQ2_M | 700 | length | ('hint', ['N4-vocab-collapse']) |

Spec-sweep transcripts: spec-mtp-n10-p0.5__rep1__00-rbtree-code.txt=('LOOP', ['N3-compresses!', 'N4-vocab-collapse!']), spec-mtp-n10-p0__rep1__00-rbtree-code.txt=('LOOP', ['N3-compresses!', 'N4-vocab-collapse!']), spec-mtp-n16-p0.5__rep1__00-rbtree-code.txt=('LOOP', ['N3-compresses!', 'N4-vocab-collapse!']), spec-mtp-n4-p0.75__rep1__00-rbtree-code.txt=('LOOP', ['N3-compresses!', 'N4-vocab-collapse!']), spec-mtp-n6-p0.5__rep1__00-rbtree-code.txt=('LOOP', ['N3-compresses!', 'N4-vocab-collapse!']), spec-none__rep1__00-rbtree-code.txt=('LOOP', ['N3-compresses!', 'N4-vocab-collapse!'])

**Floors showing a loop: none**

### 2026-09-01 — rule-21 suite lands; and the repaired loop scan disqualifies the Stage-1 floors

**Rule-21 suite, R1 (Q8_0), suite hash `1cdf54f8eb9d3f8f`, greedy, seed 42,
n=25, cap 16,384, `-c 32768`. 4,231 s.**

| dataset | score | truncated | scorer |
|---|---|---|---|
| GSM8K | **100.0** | 0 | exact match |
| MATH-500 | 60.0 | 3 | exact match |
| HumanEval | 88.0 | 1 | execution pass@1 |
| MBPP | 72.0 | 5 | execution pass@1 |
| MeetingBank | 24.3 | 0 | ROUGE-L F1 |
| ALPACA | — | — | unscored: no independent judge |
| MT-Bench | — | — | unscored: no independent judge |
| **Mean** | **68.9** | | composite over the five scored |

**Nine truncations at the 16,384 cap** (3 MATH-500, 1 HumanEval, 5 MBPP). Rule 7:
reported, not filtered, and the remedy is to raise the cap and rerun those arms
only — not to quote a mean over the questions that happened to fit. MeetingBank's
24.3 reads against the ~10 floor this repo documents for ROUGE-L, not against 0.
**GSM8K's `tok_s` is disqualified by rule 27** (the 35-agent audit overlapped its
window); its score is greedy and stands.

### The floors are loop-contaminated

Task A1 re-ran with `ask()` repaired, and the scan it should always have done
says:

| arm | t/s | chars | reasoning | content | n4_worst_ttr | verdict |
|---|---|---|---|---|---|---|
| Q8_0 | 83.37 | 2,334 | 2,332 | **0** | 0.2833 | **LOOP** |
| Q4_K_M | 118.96 | 2,517 | 2,515 | **0** | 0.3250 | hint |
| IQ2_M | 131.28 | 2,537 | 2,535 | **0** | 0.3333 | hint |

`content` is **zero on all three** — the entire generation was reasoning, which
is why the old scan saw nothing. And those t/s values are the published Stage-1
floors: **78.30 / 118.38 / 131.30**, the same probe, the same sampler.

So R1's floor is a timing taken from a generation the detector calls a LOOP, and
rule 20 says that check happens *before* the tokens or timings are trusted. The
number was never checked; now it has been, and it does not pass.

**Deliberately NOT re-measured tonight.** The obvious repair is the same probe
under the model card's own sampler — temp 1.0 / top_p 0.95 / top_k 20 /
**presence_penalty 1.5**, whose anti-repetition term is exactly the knob at
issue — and `work/a1b-floor-card-sampler.py` is written and ready. It was
launched and `gpu_lock`'s preflight refused it: `Committed_AS` 29.9 GB against a
24.5 GB `CommitLimit`, 6 of 7 GB swap in use, a foreign 3.9 GB process
(`/root/Workspace/fresh/.../e2e_tests`) plus Steam, Chrome and a second Claude
session resident.

The refusal was correct and the deeper reason to honour it is rule 27: a busy
host costs decode invisibly, −5.4% mean and −24.0% worst. Replacing a
loop-contaminated floor with a host-contaminated one is not a repair. **The
floors stand as published, now carrying their loop verdicts**, until the box is
quiet — which is a decision for whoever owns that foreign process, not something
to work around by lowering the memory cap.

There is a pleasing irony in the sampler. The frozen suite's `settings` block —
flagged earlier the same day as stale and misleading because `--greedy`
overrides it — carries `presence_penalty 1.5`. That is the model card's
anti-degeneration preset, and it is the exact remedy for what greedy decoding
just did to these floors.

### 2026-09-01 21:55 — floors re-taken under BOTH samplers in one sweep

Operator accepted the non-quiet host (Steam, Chrome, a second Claude session, a
foreign 3.9 GB test binary; **GPU itself idle at 661 MiB / 0%**). Memory cap
lowered to **14 GB** via `MEASURED_INFERENCE_MEM_CAP_GB` so `gpu_lock`'s
preflight would admit the job — a condition, recorded per rule 3 as the refusal
message requires. Every probe carries SM clock, board power, temperature and
load1; load ran **1.25–1.78** throughout, SM 1590–1965 MHz.

4 reps × 2 samplers × 3 arms, first rep discarded (rule 12), sampler order
alternated by arm (rule 30), one server per arm so the pair is an in-sweep
comparison.

| arm | greedy | card preset | greedy verdicts | card verdicts |
|---|---|---|---|---|
| Q8_0 | 83.63 (83.50–83.83) | **78.60** (77.91–79.28) | LOOP ×3 | LOOP, clean, hint |
| Q4_K_M | 118.59 (118.32–119.48) | **109.46** (109.45–111.03) | hint ×3 | clean, hint |
| IQ2_M | 131.78 (131.52–132.17) | **121.61** (121.26–122.15) | hint ×3 | clean ×3 |

**The effect: greedy reads 6.4–8.4% faster, reproducibly, in one sweep.**

**The explanation is NOT that looping inflates throughput, and this is the third
time in this campaign a real number has arrived wearing a wrong story.** Convert
to time per token:

    Q8_0    11.957 -> 12.723 ms   extra 0.765 ms
    Q4_K_M   8.432 ->  9.136 ms   extra 0.703 ms
    IQ2_M    7.588 ->  8.223 ms   extra 0.635 ms

The extra is **near-constant at ~0.70 ms/token** while the percentage climbs
6.4 → 8.4% purely because the base per-token time shrinks. That is the shape of
a **fixed per-token sampling cost** — top_k 20 plus top_p 0.95 plus a presence
penalty, over a 248,320-entry vocabulary — and there is no reason for a content
effect from repetition to produce a constant time offset. The ~20% drift across
arms (0.765 → 0.635) means "consistent with", not "proved"; a small content
term is not excluded, only demoted below the dominant one.

**What this does to the published floors.** The lock publishes 78.30 / 118.38 /
131.30. Against this sweep, **Q4_K_M and IQ2_M match their GREEDY numbers** —
they were measured under a sampler no reader will use. Under the card's own
preset they are **109.46** and **121.61**: IQ2_M's headline drops **7.4%**.

Q8_0's published 78.30 lands on the *card-sampler* median 78.60 instead. That is
luck, not method: Stage 1 read 78.30 and the A1 re-take read 83.59, the lock
said **"quote the lower"**, and quoting the lower happened to select the
non-degenerate value. The instruction was right for a reason it did not know.

**Q8_0 still loops under the card preset** — LOOP, clean, hint across three
probes. So repetition on this code prompt is a property of the arm, not merely of
greedy decoding, and the card's anti-repetition term does not fully suppress it.
IQ2_M, the most quantised arm, was **clean on all three**.

#### AMENDMENT to the RECIPE LOCK — floors restated by sampler

The lock is not rewritten; it is amended, dated, with the old numbers left
standing (rule 5). R1's floor is **78.60 t/s under the model card's preset**,
which is what a reader following the card will get. The greedy figures stay
published as what greedy decoding yields, labelled with their loop verdicts, and
never as the number a reader should expect. Both travel with their sampler,
because on this model the sampler is worth ~0.70 ms on every token (rule 3).

### 2026-09-01 22:04 — energy attribution, on the trace that was nearly lost

Rule 24 work, over the recovered 23.3-hour trace (three contiguous segments,
gaps of 18 s and 29 s at the two logger handovers, both recorded).
**Instrumentation tier: in-band GPU board power via NVML/`nvidia-smi`. PSU,
wall and PUE are excluded** — this is board draw, not site draw. Idle subtracted
at the campaign's measured loaded-idle **31.12 W**.

| window | span | mean W | Wh gross | Wh net | J/token net |
|---|---|---|---|---|---|
| GPQA anchor, 198 q | 7 h 55 m | 287.2 | 2,275.79 | 2,029.20 | 3.266 |
| rule-21 suite, 175 prompts | 70 m | 313.4 | 366.88 | 330.45 | 3.493 |
| floor Q8_0 | 61 s | 348.2 | 5.90 | 5.37 | **3.454** |
| floor Q4_K_M | 43 s | 346.9 | 4.14 | 3.77 | **2.424** |
| floor IQ2_M | 39 s | 345.0 | 3.74 | 3.40 | **2.186** |

**Deployment numbers a reader can act on.** The GPQA anchor cost **2,029 Wh net
for 142 correct answers — 14.29 Wh, or 51.4 kJ, per correct answer.** At 21.7%
truncation, roughly **441 Wh of that produced nothing at all**: answers that hit
the cap and were scored zero. That is the cost of rule 7's cap choice stated in
joules rather than in apology.

**The energy curve confirms the roofline result, from a different instrument.**
Normalising energy per token by file size:

| arm | J/tok net | ×Q8_0 | file GB | ×Q8_0 bytes | J/tok per GB |
|---|---|---|---|---|---|
| Q8_0 | 3.454 | 1.000 | 9.11 | 1.000 | 0.379 |
| Q4_K_M | 2.424 | 0.702 | 5.38 | 0.591 | 0.451 |
| IQ2_M | 2.186 | 0.633 | 3.60 | 0.395 | 0.607 |

Cutting the file to **0.395×** buys only **0.633×** the energy per token, and
`J/tok per GB` rises monotonically — 0.379 → 0.451 → 0.607. Deep quantisation
returns less than the byte reduction promises, and it returns less at every
step. That is the same shape as rule 10's efficiency constant falling 0.82 →
0.73 → 0.54, measured by a completely different instrument on a different day.
**Two independent cheap metrics agreeing (rule 4)** — and this time the
agreement is about the *effect*, with the *mechanism* still open after the
matched-bpw pair killed the codebook story.

**Cross-check on Q8_0.** Three windows, three different workloads: GPQA 3.266,
rule-21 3.493, floor probe 3.454 J/token. The floor probe sits between the two
long runs. Nothing here rests on a single window.

**And it buys a different model.** IQ2_M's 0.633× energy comes with KLD 0.441
and agreement with BF16's argmax on only **76.0%** of tokens. The energy table
is not a recommendation; it is one axis, and §5 of the report has to carry the
fidelity axis beside it or a reader will read the cheapest row as the best one.

**Caveats, which travel (rule 3).**
- **Coarse windows: prefill is not separated from decode.** The tool says so
  itself; `J/decode-token` here includes prefill energy. For the 700-token floor
  probes off one short prompt that is small; for GPQA's long stems it is not
  negligible, and the 3.266 is therefore an upper bound on true decode cost.
  Separating them needs the request-event JSONL this campaign did not capture.
- **The floor windows were derived from probe COMPLETION timestamps**, so each
  clips its leading edge: energy is slightly under-attributed and J/token
  slightly optimistic. The bias is systematic and identical across all three
  arms, so the **ratios are sound and the absolutes are floors**.
- The floor probes ran on the operator-accepted non-quiet host; the GPQA and
  rule-21 windows did not.

### 2026-09-01 22:15 — vision capability confirmed three ways, and an undeclared audio modality

Checked before spending GPU hours on Stage 6's vision work, because rule 19 makes
hallucinated sight the worst outcome and the harness had declared
`vision.supported: true` from **the presence of an mmproj file alone**.

**Confirmed, three independent sources:**

1. **Online, vendor.** `ornith-ai/Ornith-1.5-9B`'s card shows image-URL message
   content (`{"type": "image", "url": ...}`) and `AutoModelForMultimodalLM`. The
   base, `Qwen/Qwen3.5-9B`, is published as *"Causal Language Model with Vision
   Encoder"* with MMMU 78.4 and video benchmarks.
2. **The projector file.** `mmproj-Ornith-1.5-9B-BF16.gguf` is a real CLIP GGUF:
   `general.architecture clip`, `clip.has_vision_encoder true`,
   `clip.projector_type qwen3vl_merger`, 27 vision blocks, image size 768, patch
   16, and **`clip.vision.projection_dim 4096`, which matches the LM's
   `hidden_size` 4096** — the pairing check, not just a file that exists.
3. **The LM's own vocabulary.** Control tokens 248053-248057:
   `<|vision_start|>`, `<|vision_end|>`, `<|vision_pad|>`, `<|image_pad|>`,
   `<|video_pad|>`, plus grounding tokens `<|object_ref_start|>`,
   `<|box_start|>`, `<|quad_start|>`. And `qwen35.rope.dimension_sections
   [11, 11, 10, 0]` — the multimodal-rope section layout, which a text-only
   export would not carry.

**A correction to my own first pass, recorded because the failure shape
generalises.** My initial scan reported "vision/image tokens present: NONE" and
I nearly wrote the capability off. The scan matched correctly and then printed
`want[:15]` — and in a 248,320-entry vocabulary the control tokens sit at the
very end, so the slice ended 248,038 entries before the answer. A truncated
display read as a negative result. The lesson is the one this repo keeps
relearning from a different direction: **an absence reported by an instrument is
only evidence if the instrument could have shown the presence** — the same
principle that made `loop-detect.py` return NO-DATA instead of `clean` earlier
today.

**Undeclared capability: AUDIO.** The same control block carries
`<|audio_start|>`, `<|audio_end|>`, `<|audio_pad|>`, and a TTS group
`<tts_pad>`, `<tts_text_bos>`, `<tts_text_eod>`, `<tts_text_bos_single>`
(248070-248076). `model-*.json` records
`capabilities: ["text", "vision", "drafter", "effort"]` — **audio is not in
it.** No audio projector ships in this campaign's file set, so the modality is
almost certainly not exercisable here, but the harness should say "declared in
the vocabulary, no projector available, untested" rather than silently omitting
it. That is rule 19's own logic applied to a modality it does not yet enumerate:
a capability the agent cannot see is a capability the report will not mention.

## Stage 6c — vision  ·  2026-09-01 22:41

Q8_0 + `mmproj-Ornith-1.5-9B-BF16.gguf`, `-c 32768`, `-ngl 99 --jinja`, greedy.
Chrome 152 present, so the critique loop was measurable here rather than
skipped. Nonce generated at run time: digits **686954**, colour **crimson**, a
black **circle** drawn as the shape actually present.

### Rule 19 — the hallucinated-sight hunt

| arm | what it tests | result |
|---|---|---|
| **B — NO image, same question** | does it claim to see what was never sent? | **PASS-honest** |
| **C — image, asked about absent content** | does it invent a red triangle? | **PASS-not-fooled** |
| A — image + nonce, at 1024×1024 | can it read the nonce? | see below — the verdict was mine, not the model's |

Arm B is the one rule 19 is written for, and it is unambiguous:

> *"I don't see any image attached to your message. Could you please upload the
> image so I can help you identify the six-digit number?"*

**This model does not hallucinate sight.** Arm C confirms it from the other
side: asked whether a red triangle was present, it said no and named the black
circle that was.

**Arm A's `FAIL-blind` is an artefact of my own design and is retracted as a
capability verdict.** It sent the 1024×1024 image — and the same run's
resolution map had already read the identical nonce correctly at 1920×1080. Arm
A measured my choice of resolution. The honest question is not whether the model
can see but *where it stops being able to read*, so that was measured.

### Text acuity — the threshold, 3 repeats per rung, one nonce

| resolution | pixels | image tokens | correct | what it read instead |
|---|---|---|---|---|
| 768×768 | 589,824 | 585 | 0/3 | 202014 |
| 1280×720 | 921,600 | 929 | 0/3 | 688546 |
| 1024×1024 | 1,048,576 | 1,033 | 0/3 | 868054 |
| 1536×864 | 1,327,104 | 1,305 | 0/3 | 666964 |
| **1600×900** | 1,440,000 | 1,409 | **3/3** | **686954** ✓ |
| 1280×1280 | 1,638,400 | 1,609 | **0/3** | 868954 |
| 1920×1080 | 2,073,600 | 2,049 | 3/3 | 686954 ✓ |

**The transition is sharp — 0/3 to 3/3 in one step — and it is NOT a pixel
count.** 1280×1280 carries 1,638,400 pixels and 1,609 image tokens, *more of
both* than 1600×900, and still fails every repeat. Any explanation has to
account for that inversion, and this campaign does not have one: the projector's
patch grid (patch 16, `spatial_merge_size` 2, canonical `image_size` 768) and
how a given aspect ratio is resized onto it are the obvious suspects, and they
are **suspects, not findings**. Written down as an open question rather than a
mechanism, because this campaign has already published two mechanisms that were
wrong.

**The failure mode is worse than blindness, and it is the reason this belongs in
the report.** The model never says it cannot read the number. It returns a
confident six-digit answer — 868054, 688546, 666964 — and returns the *same*
wrong answer on all three repeats. Greedy decoding makes the misreading
deterministic, so a reader who runs it twice gets agreement and reads that as
confirmation. **There is no uncertainty signal at all.** Sight is honest here;
acuity is not self-reporting.

Practical rule for a reader: **feed this model screenshots at 1600×900 or
wider.** Below that it will still answer, fluently and wrongly.

### Resolution → prompt tokens (rule 18: cost is resolution, not file size)

| resolution | pixels | file bytes | image tokens | pixels/token |
|---|---|---|---|---|
| 512×512 | 262,144 | 10,491 | 265 | 989 |
| 768×768 | 589,824 | 17,475 | 585 | 1,008 |
| 1024×1024 | 1,048,576 | 24,517 | 1,033 | 1,015 |
| 1920×1080 | 2,073,600 | 30,619 | 2,049 | 1,012 |
| 3840×2160 | 8,294,400 | 74,759 | 4,089 | **2,028** |

**~1,010 pixels per image token, flat, until the cost stops rising.** At 4K the
ratio doubles — the encoder is downsampling roughly 2× in area, so **image
tokens cap near 4,096** and a 4K screenshot costs the same as a 2K one while
carrying half the detail per token. Rule 18 holds and the file size is the
control: bytes grow 7.1× across the map while tokens grow 15.4×, so bytes
predict nothing.

Text-only baseline was 23 prompt tokens, subtracted from every row above.

### Critique loop — measured, with a discriminator

Two pages rendered and screenshotted with Chrome headless: one correct, one
deliberately broken (heading and paragraph overlapped by absolute positioning,
an `<img>` pointing at a file that does not exist, a button pushed off-canvas).

- **broken page: named the overlap AND the missing image.** Both real defects,
  neither in the prompt.
- **good page: did not call it fine, and did not report the broken page's
  defects in it.**
- **Verdict: PASS-discriminates.** The point of the pair is that a model which
  praises both, or condemns both, is reading neither.

### A cross-cutting observation

`content` came back **empty** on most vision replies with the answer sitting
entirely in `reasoning_content` — the same split that hid the loop scan and the
appetite `think_chars` earlier in this campaign. Any consumer of this model's
vision output that reads only `content` will see nothing at all.

## Interview item 8 — the judge decision, CLOSED  ·  2026-09-01 23:35

The question Stage 0 asks and this campaign left open: ALPACA and MT-Bench are
2 of rule 21's 7 benchmarks, they are judge-gated, and a model may not grade its
own answers. **Decision: the three-seat blind panel, published BESIDE the
composite Mean and never folded into it.**

**Why not folded in.** The reference campaign `qwen38-27b-blind` publishes
Mean **74.9** — a mean of FIVE, with ALPACA and MT-Bench recorded as
`excluded: unscored: no independent judge`. Our suite Mean is **68.9**, also of
five. Adding judged scores to ours would silently redefine the metric and make
the two incomparable under rule 23. So the Mean stays a mean of five in both,
and the judged pair is a separate labelled result — the same treatment GPQA and
IFEval get as adjunct sets.

**The instrument, and its disclosure.** `scripts/bench/judge-panel.py`,
protocol `rule21-judge-panel-v1`: three blind seats, opaque salted ids, per-seat
shuffles, ratings 1-10 normalised `(r-1)/9*100`. **The judge is Claude Opus 5
and so is the author of this report: a CORRELATED INSTRUMENT.** That is why the
protocol publishes inter-rater spread beside every mean rather than a bare
number, and why this paragraph exists.

One improvement on the reference run: the three seats were **twelve independent
subagents**, one per packet, rather than one context rating the same material
three times. Three "seats" inside a single context are correlated by
construction and their agreement measures nothing.

| dataset | mean rating | score | sd across items | seat spread (mean / max) |
|---|---|---|---|---|
| ALPACA | 7.08 / 10 | **67.6** | 2.081 | 0.36 / 2 |
| MT-Bench | 8.19 / 10 | **79.9** | 1.054 | 0.60 / 3 |

50 answers, 150 ratings, **rated 50/50, 0 missing, 0 partial**.

**Against the reference campaign, carefully.** `qwen38-27b-blind`'s `low` arm
scored ALPACA 70.2 and MT-Bench 80.7 under the identical protocol and the same
suite hash `1cdf54f8eb9d3f8f`. Ours are 67.6 and 79.9 — **2.6 and 0.8 points
apart at n=25 with item sd above 2.0.** Rule 8 is explicit that point
differences at this n are not real, and the panel instances are different
sessions of the same instrument, which adds variance the spread columns do not
capture. **The defensible statement is that the two are indistinguishable on
this judged pair**, not that either is better — and a 9B being indistinguishable
from a 27B here is the interesting part, stated as a tie rather than a win.

### ALPACA[23]: rule 7's remedy applied, and it did not work

The panel flagged ALPACA `provisional: true` — item 23 hit the 16,384 cap and
came back empty. Rule 7 forbids filtering it and prescribes raising the cap and
rerunning that arm, which the reference campaign did at 32,768. Done, and:

    prompt 24/25: 32768 tok, 78.6 tok/s

**It truncated again at double the cap.** This is not a cap that was set too
low; it is a generation that does not terminate. It sits with the other greedy
finding from today — Q8_0 scored LOOP on all three floor probes under
`temp 0 / top_k 1`, the sampler this suite runs. Raising the cap a third time
would burn an hour to reach the same place, so the arm is closed here:
**the item is scored 1 (unusable) by unanimous seats, ALPACA stands at 67.6, and
the truncation is published as a MODEL BEHAVIOUR under greedy decoding rather
than as a harness cap choice.** Rule 7 is satisfied by having raised the cap and
reported the result, not by having made the truncation disappear.

### And the reason we cannot see what it did

The re-run's transcript for that item reads **`chars=0` against 32,768 generated
tokens**. `bench.py`'s `run_one` returned `message["content"]` alone — its own
comment noted that `--jinja` splits thinking into `reasoning_content`, and then
it discarded that half. Scoring was unaffected (the graded answer does live in
`content`), but every transcript this harness has written is missing whatever
stayed in the reasoning channel, including the GPQA anchor's **43 truncated
answers, all stored empty**. Rule 20 wants long greedy output spot-read for
repetition; that is impossible against a corpus with the text removed, and rule
28 says it cannot be recovered afterwards at any price.

Fixed: `run_one` now returns both, transcripts carry `response` and `reasoning`
as separate fields — separate so the scorers keep seeing exactly what they
scored — and the per-question crash file carries both too. **Third appearance of
this single mistake in one campaign** (`think_chars: 0` on the appetite probes,
`runner.py`'s loop scan, and now the benchmark harness itself). It is the
campaign's most repeated defect and it has never once changed a score — only
ever destroyed the evidence.

`loop-detect.py`'s NO-DATA guard, added this morning, is what caught it here: it
refused the empty string instead of returning `clean`.
