# `scripts/power/` — energy attribution for local inference

Three tools that turn a GPU power log plus a llama-server's own timings into
defensible per-arm energy numbers: **J/token, Wh/answer, tokens/kWh, EDP**,
split by **prefill vs decode**.

| file | role |
|---|---|
| `sample-power.ps1` | start / stop / list the detached 500 ms `nvidia-smi` CSV logger |
| `capture-request.ps1` | POST one generation, stamp `t_start`, append the request-event JSONL — **the join point** |
| `attribute-power.py` | integrate the power log over each window, split the phases, emit the metrics (stdlib only) |

---

## 1. The instrumentation tier — read this before quoting any number

Everything these tools produce is **in-band GPU board power**: the NVML
telemetry the RTX 3090 reports through `nvidia-smi --query-gpu=power.draw`.

**What is inside the number:** the graphics board — GPU die, VRAM, VRM losses,
board fans.

**What is NOT inside it, and is unmeasured on this machine:**

* PSU conversion loss (a 350 W board pulls meaningfully more than 350 W at the wall);
* the rest of the node — CPU, system RAM, drives, chassis fans, the display;
* idle-state platform draw;
* datacentre PUE (cooling, distribution) if you are extrapolating to one.

So: **never call this "system power" or "wall power"**, and never divide an
electricity bill by it. Label every published table exactly like the tool
does:

> in-band GPU board power (NVML); PSU losses and PUE excluded

The three tiers, for context — (1) **in-band** device telemetry (this),
(2) **node-level** (IPMI / a smart PSU), (3) **wall / PDU** (a plug meter).
Only tier 3 states total cost of an answer. If a wall meter ever gets attached
to this machine, log it alongside and publish both tiers; that is the only
honest way to state the PSU + platform overhead as *measured* rather than
assumed.

**Reference baselines measured on this box (2026-08-22/23):** cold board idle,
no server: **33.2 W**. Loaded idle, model resident and server up but answering
nothing: **30.7–31.1 W** — a resident model costs almost nothing until asked.
Sustained decode: **~344 W**. `--idle-w` defaults to **31.0** for that reason.

---

## 2. The clock-ramp caveat — the trap that fakes good efficiency

A request issued on a **cold or idle board** does not run at the board's
settled clock. Measured here: the SM clock only reaches **900–990 MHz** during
a prefill that starts right after idle, against **1455 MHz** once the board has
settled. Both the wattage *and* the throughput of that first request are low,
and J/token can come out looking **better** than the steady state — which is an
artifact, not an efficiency win.

Two defences, use at least one and say which:

* `capture-request.ps1 -Warmup` — sends a throwaway 8-token request first,
  recorded nowhere, purely to lift the clocks;
* `attribute-power.py --drop-first` — discards the first request of every
  label. (It warns loudly if that leaves a label with nothing.)

The same applies in reverse to **short probes**: a 10 s recipe probe on this
machine read 277–287 W where multi-minute runs sustained 344 W, because the
early samples catch the ramp. Quote per-1k-token figures from *sustained* runs
for planning, and say which kind of run each number came from.

The logger records `clocks.sm`, `pstate` and `utilization.gpu` on purpose:
they are how you *prove* a low-watt sample was a ramping board rather than an
efficient one.

---

## 3. `sample-power.ps1`

```powershell
# start (one file per phase is the convention)
.\sample-power.ps1 -Start -Csv results\<slug>\data\power\campaign-power.csv

# see every nvidia-smi telemetry loop on the box (read-only, kills nothing)
.\sample-power.ps1 -List

# stop the one writing that CSV
.\sample-power.ps1 -Stop -Csv results\<slug>\data\power\campaign-power.csv
```

Emits the same columns the campaign already uses:

```
timestamp, power.draw [W], power.draw.instant [W], clocks.current.sm [MHz],
clocks.current.memory [MHz], utilization.gpu [%], utilization.memory [%],
memory.used [MiB], memory.reserved [MiB], temperature.gpu, pstate
```

**Start it at the top of the campaign and leave it running.** It costs one
process and a few MB a day, and it retroactively converts every later phase —
the spec sweep, the ceiling sweep, the depth series, the effort runs — into an
energy arm *for free*. Re-running those later just for watts is hours you do
not need to spend.

**Something now checks that it is still alive, and it is not this script.**
The logger is a detached `nvidia-smi` that does not survive a reboot, and until
2026-08-30 no runner ever looked unasked — `-List` above answers the question,
but only to an operator who thought to ask it. A sweep run after a restart
produced a complete ledger, no energy at all, and no record anywhere that there
had been none. `scripts/arms.py` now looks at sweep start — is there a non-empty
`.csv` under `results/<slug>/data/power/` holding a sample newer than 300 s? —
and writes `power_logging` true|false plus the whole `power_logging_check` block
(directory, file count, newest file, age by the last row's own timestamp AND by
mtime, which of the two answered, the threshold, and the sentence that states
the verdict in words) onto its `sweep_start` line. The two ages are kept
separately because each is wrong in a way the other is not: mtime knows nothing
about time zones, and a row timestamp survives a filesystem that has not noticed
the appends yet. The fresher of the two wins, and the freshest file wins over
the others.

**It does not start a logger, and that is deliberate.** Launching one
mid-sweep would change the machine the numbers are being taken on. It prints
the command instead — the `-Start` line above, with the campaign's own CSV path
filled in — at the START of the sweep, where acting on it costs the arms
already run and nothing else. Rule 24 says energy is measured or it is absent;
`power_logging: false` on a `sweep_start` line is that absence written down at
the time it happened, rather than inferred by a later stage that found no rows.

### How `-Stop` decides what to kill (the safety contract)

`-Stop` **never** kills by process name. A logger is addressed by **the CSV it
writes**, resolved two ways, both verified over WMI/CIM:

1. the path is in `nvidia-smi`'s own command line, because `-Start` launches it
   with `-f <csv>`;
2. the sidecar `<csv>.logger.json` that `-Start` drops next to the CSV records
   the pid — and that pid is re-checked, at stop time, to still be an
   `nvidia-smi` query loop (so a recycled pid cannot be hit).

**Consequence, stated plainly:** a logger somebody started by hand with shell
redirection — `nvidia-smi --query-gpu=... > foo.csv`, which is what the
campaign's own long-running logger uses — carries **no path in its command
line** and has no sidecar. `-Stop -Csv foo.csv` will report `NONE` and kill
nothing, whatever path you pass. That is deliberate: this script cannot
accidentally end a logger it did not start. Use `-List` to read its pid, then
`-Stop -ProcessId <pid>` to end it on purpose (still verified: a pid that is
not an `nvidia-smi` telemetry loop is refused).

`-Start` also refuses to overwrite an existing non-empty CSV, or to start a
second logger on the same path, unless you pass `-Force`. If `nvidia-smi -f`
turns out to buffer or lock the file on this driver, `-Start` detects that
within a few seconds, kills that process and relaunches using stdout
redirection instead, reporting which mode it ended up in.

---

## 4. `capture-request.ps1` — the join point

A power CSV alone can only say what the board drew between two wall-clock
instants. It cannot say which of those seconds were **prefill** and which were
**decode**. The server's `timings` block can — `prompt_ms` and `predicted_ms` —
but only if something recorded the wall-clock instant the request started.

```powershell
.\capture-request.ps1 -Label baseline -PromptFile .\prompts\code.txt `
    -BaseUrl http://127.0.0.1:1234 -Events .\data\power\events.jsonl `
    -NPredict 700 -Repeat 3 -Warmup
```

Per request it stamps `t_start` **before** the POST in the same local, naive,
millisecond format `nvidia-smi` uses, archives the raw response JSON, and
appends one JSONL line:

```json
{"t_start_iso":"2026-08-23T10:49:00.000","t_end_iso":"...","label":"baseline",
 "prompt_n":1500,"prompt_ms":4200.0,"predicted_n":700,"predicted_ms":60000.0,
 "wall_ms":64350.0,"overhead_ms":150.0,"seq":1,"endpoint":"/completion", ...}
```

which gives the integrator its windows:

```
prefill = [t_start,                t_start + prompt_ms]
decode  = [t_start + prompt_ms,    +  predicted_ms]
```

Two behaviours worth knowing:

* **`-CachePrompt` is OFF by default.** llama-server's prompt cache defaults to
  *on*, and a cached prefill costs almost no energy — which silently destroys
  any J/prompt-token measurement the second time you send the same prompt. Turn
  it on only when the cache is the thing you are measuring.
* **The `t_start` bias is measured, not hidden.** `t_start` is stamped
  client-side, so HTTP round-trip and server-side queueing land *inside* the
  prefill window and inflate `J_prefill`. Every line carries
  `overhead_ms = wall_ms - (prompt_ms + predicted_ms)`, which is the size of
  that bias. Locally it is tens of ms — negligible against a multi-second
  prefill, material only for very short prompts. Correct for it with
  `attribute-power.py --lead-ms <overhead_ms>`.

Any JSONL with `t_start_iso`, `prompt_ms`, `predicted_ms`, `prompt_n`,
`predicted_n`, `label` works — this script is a convenience, not a
requirement. Existing harnesses can emit the same six fields.

---

## 5. `attribute-power.py`

```bash
python attribute-power.py --selftest          # synthetic assertions, no GPU needed

# fine-grained: real prefill/decode split from server timings
python attribute-power.py --power power.csv --events events.jsonl \
       --idle-w 31.0 --drop-first --json arms.json --csv-out arms.csv

# coarse: you only know when an arm started and stopped
python attribute-power.py --power power.csv \
       --window 2026-08-23T10:49:00 2026-08-23T10:52:00 spec-none \
       --window 2026-08-23T10:52:00 2026-08-23T10:55:00 spec-n4 \
       --label-tokens spec-n4=1400/1500
```

Per label it emits **J, Wh, mean W, peak W, J/decode-token, J/prompt-token,
tokens/kWh, EDP (J·s), decode tok/s**, each **gross and idle-subtracted**.

Definitions used, so they can be checked:

| metric | formula |
|---|---|
| J over a window | trapezoid on `power.draw` between samples, edges linearly interpolated |
| mean W | `J / covered_s` (**not** window length — see coverage below) |
| J/decode-token | `J_decode / predicted_n` |
| J/prompt-token | `J_prefill / prompt_n` |
| tokens/kWh | `predicted_n / (J_decode / 3.6e6)` |
| EDP | `J_decode × decode_seconds`, per request, averaged over the arm |
| Wh/answer | `(J_prefill + J_decode) / 3600`, gross and idle-subtracted |
| idle-subtracted | `J − idle_W × covered_s`, `--idle-w` default 31.0 |

Robustness details that matter for real logs:

* **Gap capping (`--max-gap`, default 2 s).** A logger restart, a sleep, or a
  crashed sampler leaves a hole between two timestamps. Integrating straight
  across it would *fabricate* energy at whatever the board happened to be
  drawing. Any segment longer than `--max-gap` is credited **at most**
  `max-gap` seconds and the remainder is counted as *excluded*, which shows up
  as a **cov%** below 100 and a warning. Selftest 3 asserts this: two samples
  10 s apart at 100 W integrate to 200 J, not 1000 J.
* **Coverage is reported, never assumed.** `cov%` is `covered_s / window_s`.
  Below `--min-coverage` (default 0.9) the arm gets a warning saying how many
  seconds had no samples. A mean W over a half-logged window is a lie; this
  makes it visible.
* **Header and unit tolerance.** Reads both the `--format=csv,nounits` style
  (`349.26`) and the older unit-suffixed style (` 98.71 W`), with or without a
  header row, picks the `power.draw` column by name when a header exists,
  drops `[N/A]` samples, and strips the UTF-8 BOM PowerShell 5.1 writes.
  `--use-instant` integrates `power.draw.instant` instead.
* **Multiple logs.** `--power` repeats; logs are merged, sorted, and
  duplicate timestamps de-duplicated.

### `--selftest`

Runs on synthetic data, needs no GPU and no server, and asserts:

1. constant **100 W for 10 s == 1000 J** (and mean 100 W, coverage 1.0);
2. trapezoid correctness on a ramp with **sub-sample window edges**
   (`∫ 100+10t` over 2.5→7.5 s == 750 J);
3. the **gap cap** (above);
4. the **phase split**: 200 W for 2 s prefill + 100 W for 8 s decode →
   `J_prefill=400`, `J_decode=800`, `J/prompt-token=4.0` (100 prompt tokens),
   `J/decode-token=10.0` (80 decode tokens), `tokens/kWh=360000`,
   `EDP=6400 J·s`;
5. **idle subtraction** arithmetic;
6. **CSV parsing** of both formats, including `[N/A]` and header-name column
   selection;
7. **coarse `--window` + `--label-tokens`** mode.

---

## 6. Worked example

Assume the logger has been running since the campaign started.

```powershell
# 1. logger already up; confirm and note the file
.\sample-power.ps1 -List

# 2. three measured requests for one arm, clocks warmed first
.\capture-request.ps1 -Label spec-n4 -PromptFile .\prompts\code.txt `
    -BaseUrl http://127.0.0.1:1235 -Events .\data\power\events.jsonl `
    -NPredict 700 -Repeat 3 -Warmup

# 3. change one variable (e.g. restart the server with --spec-type none),
#    then the same command with -Label spec-none
```

```bash
# 4. attribute
python attribute-power.py \
  --power results/<slug>/data/power/campaign-power.csv \
  --events results/<slug>/data/power/events.jsonl \
  --idle-w 31.0 --drop-first --json results/<slug>/data/power/arms.json
```

Real output shape (run against this machine's live `rule21-power.csv`, with
synthetic request events so no GPU work was disturbed):

```
--- ARM SUMMARY ---
label      n   wall_s   cov%   mean_W   peak_W    J_gross  Wh_gross     J_net   Wh_net
arm-A      2   128.80 100.0%    333.5    349.8    42949.1   11.9303   38956.3  10.8212
arm-B      1    69.00 100.0%    329.5    330.4    22736.1    6.3156   20597.1   5.7214

--- PHASE ATTRIBUTION ---
label    prefill_s  J_prefill  J/prompt_tok  decode_s  J_decode  J/dec_tok  tokens/kWh    EDP_J.s
arm-A         8.30     2667.7        0.8892    120.50   40281.4     28.367      126907    1213429
arm-B        21.00     6919.3        0.2471     48.00   15816.8     24.334      147944     759206
```

Read it as: prefill is **cheap per token** (0.25–0.89 J) because it processes
thousands of tokens per second; decode is **expensive per token** (24–28 J)
because the board burns ~330 W to emit ~12 tokens/s. That asymmetry is the
whole reason the phases must be split before any J/token is published.

---

## 7. What this is for — the mechanisms worth measuring

One row per arm, columns `mean W · J/decode-token · J/prompt-token ·
tokens/kWh · EDP · verdict`. Change **one** variable per arm, keep the prompt
and `n_predict` fixed, and take ≥2 requests after a warm-up:

| axis | arms to run | what to expect |
|---|---|---|
| quantization | Q4_K_M (14.9 GB) vs UD-IQ4_XS (13.3 GB) vs NVFP4 | smaller weights → less VRAM traffic per token |
| speculative decoding | `--spec-type none` vs MTP n4/p0.75 vs n10/p0.5 | t/s rises at roughly constant W, so J/token should **fall** — quantify it |
| batching | `--parallel 1` vs `2`, aggregate | measured here: +11 % throughput at −40 % per-request latency; a fixed board draw amortised over more tokens |
| KV cache dtype | `f16` vs `q8_0` | less KV traffic per token |
| depth | 1.5k / 28k / 91k context | t/s falls with depth — does W fall too, and what does J/token do? |
| token regime | thinking on vs off | 36.6 vs 62.0 t/s on the same server → same W, very different J/answer |
| reasoning effort | low / medium / xhigh | measured here: 20.55 / 35.96 / 120.21 Wh per answer; Wh/1k tokens 1.19 → 1.83 |

**The one knob this toolkit cannot turn: the GPU power cap.**
`nvidia-smi -pl <W>` (3090 stock **350 W**; Linux may need `-pm 1` first) is
the classic efficiency lever — capping usually costs a little throughput and
buys a lot of J/token. It requires an **elevated shell**. If the campaign
cannot elevate, do **not** estimate it: print the command, state the stock cap,
and mark it *"unmeasured on this machine (requires administrator)"*. A sweep
would be 350 / 300 / 250 / 200 W into the same matrix.
