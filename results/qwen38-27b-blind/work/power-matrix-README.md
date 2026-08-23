# `power-matrix.ps1` — runbook

The post-sweep energy matrix for Qwen3.8-27B on the RTX 3090. One row per arm:
**mean W · J/decode-token · J/prompt-token · tokens/kWh · EDP (J·s) · Wh/answer**,
gross and idle-subtracted, for speculation, quantization, KV dtype, token
regime, depth, batching, and the GPU power cap.

* script: `E:\AI\measured-inference\results\qwen38-27b-blind\work\power-matrix.ps1`
* tooling it drives: `E:\AI\measured-inference\scripts\power\{sample-power.ps1, capture-request.ps1, attribute-power.py}`
* everything it writes: `E:\AI\measured-inference\results\qwen38-27b-blind\data\power-matrix\`
* power CSVs: `...\data\power\power-matrix-<stamp>.csv` (the campaign's `rule21-power.csv` is never touched)

---

## 0. Do not start it yet

**A `llama-server` is running right now (the rule-21 sweep) and a hand-started
`nvidia-smi` logger is writing `rule21-power.csv`.** This matrix restarts the
server for every arm, so it would destroy that sweep. The script refuses to
start while any `llama-server` is alive:

```
REFUSED a llama-server is already running - that is very likely the rule-21
        benchmark sweep. ...
```

`-Force` overrides the guard. Do not use it until the sweep is finished.

Safe to run at any time, including right now — it starts no server, no logger,
and no inference:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File `
  E:\AI\measured-inference\results\qwen38-27b-blind\work\power-matrix.ps1 -Plan
```

`-Plan` prints the arm table, the per-arm estimate and the total wall clock,
then exits. Its only GPU contact is two read-only `nvidia-smi --query-gpu`
calls (power limit + default limit) — the same query the running logger already
makes twice a second.

---

## 1. Instrumentation tier — put this on every figure

Everything here is **in-band GPU board power** (NVML, `nvidia-smi
--query-gpu=power.draw`, 500 ms).

* **inside the number:** GPU die, VRAM, VRM losses, board fans.
* **not in the number, and unmeasured on this machine:** PSU conversion loss,
  CPU / system RAM / drives / chassis fans / display, and datacentre PUE.

There is no wall meter on this box, so the PSU + platform overhead is
**unmeasured, not estimated**. Never call these numbers "system power" or "wall
power", and never divide an electricity bill by them. If a plug meter is ever
attached, log it alongside and publish both tiers.

Reference baselines already measured here (2026-08-22/23): **33.2 W** cold board
idle, **30.7–31.1 W** loaded idle, **~344 W** sustained decode. Arms A1 and A2
re-measure the first two under this script's own protocol, so the matrix carries
its own baseline instead of importing one.

---

## 2. Protocol, and why each piece is there

Every timed arm:

1. start `llama-server` with that arm's flags; wait for `/health`;
2. **one discarded probe** — the clock-ramp rule. A request issued on an idle
   board runs at 900–990 MHz against 1455 MHz settled; it draws fewer watts *and*
   emits fewer tokens, and its J/token comes out looking **better** than steady
   state. That is an artifact. It is recorded in the events file and removed by
   `attribute-power.py --drop-first`;
3. **cooldown** — 20 s, or 30 s for the depth arms (the M2b/M2d cooled protocol
   that removed the 18.27–26.60 t/s spread from a *fixed* configuration);
4. **N=3 timed probes**, 5 s apart, `temperature 0`, `top_k 1`, `n_predict 700`,
   thinking off unless the arm says otherwise;
5. stop the server; integrate the power log over each request's own
   `prefill = [t_start, +prompt_ms]` and `decode = [+prompt_ms, +predicted_ms]`
   windows and emit the metrics.

**Prompt caching stays OFF** (`capture-request.ps1`'s deliberate default).
llama-server caches prefills by default, and a cached prefill costs almost no
energy — it would silently destroy J/prompt-token on the second identical
prompt. The price is that the depth arms re-prefill on *every* probe, which is
why F3 alone is budgeted at ~9 minutes. It buys the thing the framework asks
for: **J per prompt-token at depth**, measured rather than assumed.

**One variable per arm.** Prompt, `n_predict`, sampler and port are identical
everywhere; `-ngl 99`, `--parallel 1`, `-ctk/-ctv q8_0` and the MTP flags follow
`serve-qwen.bat`.

---

## 3. The arms (19), with estimates

Estimates come from the campaign's measured t/s and load times and include each
arm's server load, discarded probe, cooldown, timed probes and inter-arm settle.

| arm | est | what it isolates |
|---|---|---|
| `A1-idle-noserver` | 1:40 | board idle, **no server**, 60 s window |
| `A2-idle-loaded` | 2:40 | loaded idle — server up, model resident, zero requests, 60 s |
| `B1-spec-none` | 2:30 | IQ4_XS `-c 32768`, `--spec-type none` |
| `B2-spec-mtp-n4-p075` | 2:00 | MTP n-max 4 / p-min 0.75 |
| `B3-spec-mtp-n10-p05` | 1:55 | MTP n-max 10 / p-min 0.5 |
| `C1-quant-iq4xs` | 2:30 | UD-IQ4_XS 13.3 GiB, no spec — **repeats B1 on purpose** |
| `C2-quant-q4km` | 2:55 | Q4_K_M 15.4 GiB, no spec |
| `C3-quant-nvfp4-high` | 3:35 | NVFP4-MTP-HIGH 17.6 GB, no spec |
| `D1-kv-f16` | 2:35 | KV cache f16 |
| `D2-kv-q8` | 2:30 | KV cache q8_0 — **third measurement of the B1 config** |
| `E1-think-on` | 2:55 | thinking ON (`--reasoning-preserve`), n4/p0.75 |
| `E2-think-off` | 2:00 | thinking OFF, n4/p0.75 — **second measurement of the B2 config** |
| `F1-depth-1k5` | 2:20 | ~1.5k fill, `-c 131072`, n4/p0.75, cooled |
| `F2-depth-28k` | 4:15 | ~28k fill |
| `F3-depth-91k` | 9:15 | ~91k fill (four full prefills — cache is off) |
| `G1-parallel-1` | 2:00 | `--parallel 1`, two requests back to back, aggregate |
| `G2-parallel-2` | 2:00 | `--parallel 2`, two **concurrent** requests, aggregate |
| `H1-plimit-250` | 2:30 | section B's winner at `nvidia-smi -pl 250` |
| `H2-plimit-300` | 2:30 | section B's winner at `nvidia-smi -pl 300` |

**Full matrix: 19 arms, estimated 54.6 min (3275 s).** The script prints this
table and the total up front on every run, and recomputes the total for the arms
still pending when you resume.

### Three arms are deliberate duplicates

`C1` re-measures `B1`'s configuration, `D2` re-measures it a third time, and
`E2` re-measures `B2`'s. Nothing else in this matrix tells you how big a
difference has to be before it is real. Three independent measurements of one
identical configuration, spread across an hour of drifting board temperature,
are this matrix's **noise floor** — read the spread across `B1 / C1 / D2` before
believing any gap smaller than it. They cost about 5 minutes.

### The two arms that are measured differently, and why

`G1` and `G2` are **coarse windows**, not phase-split arms. Two concurrent
requests overlap in time, so summing their per-request energy would count the
same joules twice. The honest aggregate is one window over the whole burst,
divided by the tokens both answers actually produced — which is exactly what
batching amortization means. `G1` is the matched `--parallel 1` comparator run
the same way, so the pair is internally consistent; neither is comparable to a
phase-split arm's J/token, and both are tagged `mode=window-coarse` and
`NOTE=coarse-window-includes-prefill` in the log.

The two requests in `G2` are launched from two jobs that spin until the same
absolute instant, so both POSTs land within tens of ms of each other rather than
one PowerShell start-up apart. The measured skew is logged as `start_skew_ms`;
if it is ever more than a few hundred ms, treat that arm as suspect.

---

## 4. Running it

```powershell
# preview only - safe with the sweep running
.\power-matrix.ps1 -Plan

# the whole matrix, attached
.\power-matrix.ps1

# the whole matrix, detached (returns immediately, writes power-matrix.pid)
.\power-matrix.ps1 -Detach

# one section
.\power-matrix.ps1 -Only B1-spec-none,B2-spec-mtp-n4-p075,B3-spec-mtp-n10-p05

# re-run an arm the log already has
.\power-matrix.ps1 -Only D1-kv-f16 -Redo D1-kv-f16

# elevated, for section H
#   (right-click PowerShell -> Run as administrator, then the same command)
```

Useful switches: `-NPredict 700`, `-Repeat 3`, `-CooldownSec 20`,
`-DepthCooldownSec 30`, `-SettleSec 5`, `-InterArmSec 15`, `-IdleW 31.0`,
`-IdleWindowSec 60`, `-Port 1235`, `-LoadMode mmap`, `-Python python`,
`-SkipPowerLimit`, `-Force`.

### Watching a detached run

```powershell
Get-Content ...\data\power-matrix\power-matrix-log.txt -Wait -Tail 20
Get-Content ...\data\power-matrix\console-<stamp>.log  -Wait -Tail 40
Get-Process -Id (Get-Content ...\data\power-matrix\power-matrix.pid)
```

Stop it with `Stop-Process -Id <pid>`; re-running resumes. A run killed
mid-arm leaves that arm without a `RESULT` line, so it is retried — but check
that the killed arm's `llama-server` really died, and that the GPU power limit
is back at its default (`nvidia-smi --query-gpu=power.limit,power.default_limit
--format=csv`). The script restores a stale cap automatically on its next start.

---

## 5. Resume semantics

Each arm appends **exactly one** line:

* `RESULT <id> ...` — measured; counts as done, skipped on the next run;
* `SKIPPED <id> reason=... ` — deliberately not measured (missing model, no
  admin, `-SkipPowerLimit`); also counts as done;
* `FAILED <id> reason=...` — server failed to load, attribution came back empty,
  or the arm threw. **Does not count as done** — the next run retries it.

Resume matching is anchored (`^RESULT <id> ` / `^SKIPPED <id> `), so
`B1-spec` never matches `B1-spec-none`. The log is written without a BOM so
line 1 stays matchable.

Force a re-run with `-Redo <id>[,<id>...]`. A re-run deletes that arm's events
file first, so a retry never inherits stale requests.

---

## 6. Output files

| path (under `...\data\power-matrix\`) | what |
|---|---|
| `power-matrix-log.txt` | the resumable result log — one `RESULT`/`SKIPPED` line per arm, plus `LOAD`, `WARN` and run headers |
| `power-matrix-arms.jsonl` | one JSON record per arm (the full attribution object) |
| `arms.json` / `arms.csv` / `report.txt` | the combined attribution over **every** phase-split arm measured so far, regenerated at the end of each run |
| `arm-<id>.json` | that arm's own attribution |
| `events\events-<id>.jsonl` | the request events (`t_start_iso`, `prompt_ms`, `predicted_ms`, `prompt_n`, `predicted_n`) that make the phase split possible |
| `events\raw-events-G*.jsonl` | the G arms' raw requests — excluded from the combined report on purpose (overlapping windows) |
| `events\req-<label>-<stamp>.json` | the archived server responses |
| `prompts\prompt-{std,d28k,d91k}.txt` | the generated probes |
| `srv\srv-<id>.{err,out}.log` | llama-server's own logs per arm |
| `..\power\power-matrix-<stamp>.csv` | this run's 500 ms power log (one per run; all of them are merged at attribution time) |

A `RESULT` line looks like:

```
RESULT B2-spec-mtp-n4-p075 mode=phase-split n=3 mean_W=340.2 peak_W=351.0
  J_dec_tok=12.780 J_dec_tok_net=11.6 J_prompt_tok=0.2600 tok_kWh=281000
  tok_kWh_net=310000 EDP_Js=71000 dec_tps=83.50 Wh_ans=2.5 Wh_ans_net=2.3
  J_gross=9000 pre_s=1.8 dec_s=8.4 prompt_n=1533 pred_n=700 cov_pct=100.0
  vram_board=15900 vram_shr=0 cfg="IQ4_XS c32768 spec=n4/p0.75 ..."
```
(one physical line; wrapped here for reading).

---

## 7. Section H — the GPU power cap

`nvidia-smi -pl` needs an **elevated shell**. At start-up the script probes the
capability by setting the limit to the card's *own default* — a no-op that
requires exactly the same privilege — and records the result.

* **Not elevated (or the driver refuses):** H1 and H2 are logged as
  `SKIPPED ... reason=needs-admin`, carrying the exact commands and the card's
  stock default limit, and the matrix continues. That is the honest outcome:
  the cap is then **the one knob unmeasured on this machine**. Do not estimate
  it.
* **Elevated:** the script picks section B's **winner** — the B arm with the
  lowest J/decode-token, read back out of the log so it survives a resume — and
  re-runs that exact configuration at 250 W and at 300 W. Only the cap differs.

To measure H later, on its own, in an elevated shell:

```powershell
.\power-matrix.ps1 -Only H1-plimit-250,H2-plimit-300
```

The commands, if you ever want them by hand:

```powershell
nvidia-smi --query-gpu=power.limit,power.default_limit,power.min_limit,power.max_limit --format=csv
nvidia-smi -pl 250        # cap
nvidia-smi -pl 300
nvidia-smi -pl 350        # restore (3090 stock default; confirm with the query above)
```

**Restoration:** the script restores the card's default limit in a `finally`
block, so it runs even on an exception or a Ctrl-C. It also detects and repairs
a stale non-default cap at start-up. If it ever reports
`PLIMIT RESTORE FAILED`, run the restore command by hand — a card left capped
would silently bias every later measurement on this machine.

---

## 8. Reading the results

* **Prefill is cheap per token, decode is expensive per token.** Prefill chews
  through ~865 tok/s; decode burns a nearly fixed ~344 W to emit tens of tokens
  per second. Expect J/prompt-token in the 0.2–0.9 range and J/decode-token in
  the 10–30 range. That asymmetry is why the phases must be split before any
  J/token is published.
* **Speculation should cut J/token at roughly constant W.** The board draws the
  same watts either way; MTP just emits more tokens per second. If B2/B3 show a
  large *wattage* change instead, look at `clocks.sm` before believing it.
* **`mean_W` far below ~344 W on a decode arm is a red flag**, not an efficiency
  win — the script warns when it sees one. Check `clocks.sm` in the CSV for a
  ramping board.
* **`cov_pct` below 100** means the power log had holes inside that arm's
  windows; below 90 % the script warns and the mean is understated. `mean W` is
  `J / covered_s`, never `J / window_s` — a mean over a half-logged window is a
  lie.
* **`vram_shr` > 0 is the spill signature**: part of the model is living in
  system RAM, decode collapses, and that arm's J/token is measuring the spill,
  not the mechanism. The script warns at load time.
* **`pred_n` varies between arms.** `n_predict 700` is a ceiling; a code answer
  can hit EOS early, and the thinking-ON arm may hit the ceiling mid-reasoning.
  J/token and tokens/kWh normalize for that; **Wh/answer and EDP do not** — read
  them alongside `pred_n`.
* **Idle-subtracted columns** remove `31.0 W × covered_s` (`-IdleW`). Use the
  gross numbers for "what did this answer cost", the net numbers for "what did
  the *work* cost".
* Cross-check the depth ladder against the campaign's own cooled measurements —
  the F prompts are byte-identical to M2d's, which read **86.3 / 80.2 / 64.8
  t/s** at 1.5k / 28k / 91k. If `dec_tps` there disagrees badly, something about
  the machine changed, not the energy.

---

## 9. Deviations and assumptions, stated

1. **Port 1235, not 1234.** LM Studio holds 1234 on this machine; the campaign
   already measures on 1235. Port affects nothing measured. `-Port` overrides.
2. **`--api-key` is omitted.** `serve-qwen.bat` ships `--api-key dummy`, but
   `capture-request.ps1` sends no `Authorization` header, so an api-key server
   would 401 every probe. The key has no energy cost.
3. **The `serve-qwen.bat` sampler defaults are omitted** (`--temp 1.0 --top-p
   0.95 --top-k 20 --min-p 0.0`). Every request pins `temperature 0` /
   `top_k 1` for determinism, which overrides them anyway. Sampling has no
   measurable energy cost at these token rates.
4. **`--load-mode mmap`, not `none`.** `serve-qwen.bat` uses `none`; the campaign
   harness (`lib.ps1`, and every `followup-m2*` run this matrix cross-checks
   against) uses `mmap`. Load mode changes load time, not decode. `-LoadMode`
   overrides.
5. **Reasoning effort is left at the server default for `E1-think-on`**
   (`--reasoning-preserve`, exactly as `followup-m2e.ps1` ran it) rather than
   pinned to low/medium/xhigh. The per-effort energy is already measured
   (20.55 / 35.96 / 120.21 Wh per answer); E is about the *token regime*, not
   the effort ladder.
6. **`-c 32768` for B, C, D, E, G; `-c 131072` for F.** B was specified at
   32768; C/D/E/G hold it there so every shallow arm is comparable. F needs
   131072 to hold a 91k fill, which is why F1 is not identical to B2.
7. **NVFP4 is the HIGH variant** (17.6 GB, `serve-qwen-nvfp4.bat`'s default) with
   `--spec-type none`, matching C1/C2. On sm_86 there are no FP4 tensor cores,
   so this measures the dequant fallback path — the size benefit without
   Blackwell's speed. At 17.6 GB plus a 32k q8_0 KV cache it is the tightest arm
   in the matrix: if `vram_shr > 0` appears, the arm is measuring a spill.
8. **A missing model file is a graceful `SKIPPED`**, not a crash. All three
   backbones were present when this was written
   (`Qwen3.8-27B-UD-IQ4_XS.gguf`, `Qwen3.8-27B-Q4_K_M.gguf`,
   `Qwen3.8-27B-NVFP4-MTP-HIGH.gguf`).
9. **The script starts its own logger** into `power-matrix-<stamp>.csv` and stops
   only that one. The campaign's hand-started `rule21-power.csv` logger carries
   no path in its command line and is invisible to `sample-power.ps1 -Stop` by
   design — it cannot be touched. Every run gets a fresh CSV, and attribution
   passes **all** `power-matrix-*.csv` files, so a resumed matrix still
   integrates cleanly across runs.
10. **Only `llama-server` processes that started after this script did are ever
    killed.** An older one is left alone and reported.
11. **`n=3` timed probes per arm.** Enough to see the spread, not enough for a
    confidence interval. Quote the median and the range, and lean on the
    B1/C1/D2 triplicate for the noise floor.
12. **Estimates are estimates.** Each arm logs its actual wall clock next to its
    estimate; the load times in particular depend on the OS file cache.
