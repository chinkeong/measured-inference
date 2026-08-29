# ledger-notes — the cross-campaign measurements ledger

`scripts/ledger.py` turns every campaign under `results/` into one JSONL file
of measurements, and then refuses to put two of them in one comparison unless
the fields that must match do match. Grep this file for the symptom; do not
read it whole.

| Situation | Section |
|---|---|
| what the thing is, and why a catalogue is not one | The distinction |
| which command does what | Commands |
| what one row holds | The row |
| why a comparison was REFUSED | The gate |
| the gaps this found in the reference campaign | What the artefacts carry |
| appetite, prompt budget, output ceiling | The three catalogue columns |
| an error string you are staring at | Symptoms |
| making a NEW campaign gate-clean | Checklist |
| what the tool cannot do | Known limits |

---

## The distinction

A **catalogue** says `Qwen3.8-27B does 86.91 t/s`. A **ledger** says
`on machine M, build B, at conditions C, on 2026-08-23: 86.91 t/s`.

Rule 30 forbids the first across sweeps — 86.91 t/s was reached in 3 of 23
attempts of one identical configuration, and the same five-arm sweep re-run
last-to-first moved its baseline arm from 76.32 to 67.41 t/s while every
relationship kept its sign. Absolutes do not travel. Ratios do. The ledger row
is rule 3 compliant by construction, and the gate is rule 30 written as a
function that exits 2.

The ledger is **generated, never hand-edited**. `build` derives it from
`results/*/`, sorts it, and hashes the body into the header, so a hand-edit is
visible to `check` and a rebuild that changed nothing rewrites nothing. Commit
it: the diff is the record of what changed and when.

---

## Commands

```
python scripts/ledger.py build                      # derive results/ledger.jsonl
python scripts/ledger.py check                      # rows unfit to be compared
python scripts/ledger.py rows    --metric appetite.MATH-500
python scripts/ledger.py compare --metric composite.mean --source rule21/arm
python scripts/ledger.py compare --metric throughput.decode --ratio
python scripts/ledger.py selftest                   # no GPU, no model, no network
```

`--check` is accepted as a synonym for the `check` subcommand. Selectors are
shared by `rows` and `compare`: `--metric`, `--class`, `--campaign`, `--model`,
`--source` (substring of the path), and `--where field=value` on any dotted
field, repeatable; `--where field=` selects rows that do not name it.

Exit codes: `check` returns 1 when any row is blocked or the body hash does not
match (`--warn-only` returns 0); `compare` returns 2 on a refusal. Both are
usable as gates in a script.

`build` costs seconds and touches no GPU. Run it at the end of every stage that
writes an artefact, and again before publishing.

---

## The row

One line per (model file, machine, build, conditions, metric, value, date,
source path):

```json
{"row":"c5131e8d0513","campaign":"qwen38-27b-blind",
 "model_file":"Qwen3.8-27B-UD-IQ4_XS.gguf","model_label":"low-cap32k (7-benchmark, judged)",
 "machine":"NVIDIA GeForce RTX 3090 | 596.36 | Windows-10-10.0.26200-SP0",
 "build":"llama.cpp 0.1.2-dev build 10502 commit 0adcc3bb5",
 "metric":"composite.mean","class":"accuracy","value":80.2,"unit":"index 0-100",
 "date":"2026-08-23T05:40:29","conditions":{"suite_hash":"1cdf54f8eb9d3f8f", …},
 "source":"results/qwen38-27b-blind/data/rule21/arm-low-judged.json",
 "extractor":"bench-suite/v1","provenance":"DERIVED: mean of the scored set"}
```

`row` is a hash of the identity, so it is stable across rebuilds and safe to
quote in a report. `machine` is `gpu | driver | os` and deliberately excludes
the hostname: what moves a throughput number is the card, its driver and the
OS scheduler, `provenance.py` records those three and no hostname, and gating
on the hostname would refuse every comparison between a `provenance.py`
artefact and a `bench.py` one while naming no physical difference. `check`
reports the absent hostname as THIN instead.

Three extractors read three shapes, and a shape none of them recognises is
skipped in silence rather than guessed at:

| Extractor | Reads | Sweep identity |
|---|---|---|
| `bench-suite/v1` | `suite_hash` + `results` — `scripts/bench/bench.py` | none; the artefact does not name one |
| `arm-sweep/v1` | `{"arms":[…]}` — `attribute-power.py`, the drafter and ts-pick sweeps, the head-to-heads | the file: those arms ran together |
| `arms-ledger/v1` | `kind:"probe"` and `kind:"arm_failed"` lines, under the `kind:"sweep_start"` header that supplies provenance — `scripts/arms.py` | `armfile:sweep`, already on every line |

Only `results/<slug>/<data_dir>/` is scanned. `work/` is declared scratch by
`results/TEMPLATE-campaign.json` — "safe to lose" — and a number whose source
is re-creatable scratch has no source.

**One artefact supersedes another when its arms are a strict superset, in the
same directory.** `attribute-power.py` writes the whole sweep and a file per
arm, so the same joules otherwise appear three times; the multi-arm file wins
and the others' file-level conditions are folded in. That fold is what carries
rule 24's instrumentation tier onto the 147 power-matrix rows, since the tier
lives in the `.json` and the arms live in the `.jsonl`. Same directory only:
`register/` holds a dozen unrelated sweeps and pooling their file-level fields
would attach one probe's tier to another probe's watts.

---

## The gate

`CLASSES` at the top of `scripts/ledger.py` is the whole rule set. Each class
names the fields that must MATCH, the conditions rule 3 wants beside the
number, and whether it travels between sweeps.

| Class | Must match | Travels | Rule |
|---|---|---|---|
| `accuracy` | suite hash, datasets, samples, seed, max_tokens, temperature, top_k, top_p | yes | 21, 23 |
| `appetite` | suite hash, datasets, samples, seed, max_tokens, temperature | yes | 16, 21, 23 |
| `count` | suite hash, datasets, samples, max_tokens | yes | 7, 21 |
| `throughput` | machine, build, **sweep** | **no** | 30 |
| `energy` | machine, build, **sweep**, tier, phase | **no** | 24, 30 |
| `acceptance` | machine, build, spec flags, kv, temperature, top_k, top_p | yes | 3, 11, 30 |
| `memory` | machine, build, ctx, model | yes | 13, 14 |
| `load` | machine, build, model, ctx | yes | 13 |
| `ratio` | what was divided by what, and the model | yes | 30 |

Acceptance is **not** gated on the sweep, and that is a measurement rather than
an oversight: rule 30 eliminated the drafter as a cause of the two throughput
levels by finding acceptance and mean draft length bit-identical across
sessions. Sampling is gated, because rule 3 says acceptance is a property of
which token the drafter must guess.

A refusal comes in two shapes, and they are different failures:

- **NOT NAMED** — the field is absent on some rows. Unknown is never equal to
  unknown: two rows that do not name their sweep are not thereby in the same
  sweep.
- **DIFFERS** — every row names it and the values disagree.

Every refusal prints the field, what each side holds, a FIX keyed to that
field, the largest subset the refusal still allows (with the command, carrying
your selection forward), and the `--assert-same` override. An assertion is
printed above the result every time it is used: *ASSERTED BY THE OPERATOR, not
by any artefact.*

---

## What the artefacts carry

Built 2026-08-29 from commit `83de5d4`: **958 rows from 43 artefacts** in one
campaign, of which **569 rows from 42 artefacts are BLOCKED** from any
comparison. Five findings, each reproducible with one command.

**1. A shared suite hash does not make two scores comparable.** All five
MATH-500 rows under `rule21/arm-low*` carry hash `1cdf54f8eb9d3f8f`, and one of
them measured MATH-500 alone while the others measured all seven benchmarks.
`bench.py` records the frozen suite's hash even when `--datasets` narrows the
run, so rule 23's test passes while rule 21's scored set differs.

```
$ python scripts/ledger.py compare --metric accuracy.MATH-500 --source rule21/arm-low
REFUSED. 5 row(s) of accuracy.MATH-500 (class accuracy) may not stand in one comparison.
  conditions.datasets  DIFFERS
         4 row(s)  GSM8K,MATH-500,HumanEval,MBPP,ALPACA,MeetingBank,MT-Bench
         1 row(s)  MATH-500
  conditions.max_tokens  DIFFERS
         3 row(s)  32768
         2 row(s)  16384
```
(the class rationale and the two FIX lines are elided from that block)

**2. The judged effort arms measured MATH-500 at two different caps.** The
low and xhigh arms carry `max_tokens_by_dataset.MATH-500 = 32768` after their
rule-7 re-runs; the medium arm carries 16384. All three truncated zero MATH-500
answers at their own cap, which is the campaign's stated grounds for carrying
the cells over — so this is the case `--assert-same conditions.max_tokens`
exists for, and the assertion prints above the numbers. The composite Mean
compares without an assertion because all three artefacts record the same
mixed-cap string, `16384/32768 (see max_tokens_by_dataset)`: the composite row
inherits the artefact's own summary of its caps, and the per-cell rows carry
the true per-dataset ones. When the cap matters, compare the cells.

**3. The forward drafter sweep names no build.** `ts-pick-probe.json` carries
no `toolchain` block and `ts-pick-probe-reversed.json` carries one, so an
absolute comparison across the pair is refused twice over — on the machine and
the build, and again on the sweep.

```
$ python scripts/ledger.py compare --metric throughput.decode --source ts-pick-probe
REFUSED. 10 row(s) of throughput.decode (class throughput) may not stand in one comparison.
  machine  NOT NAMED       5 of 10 row(s) …  results/…/followup/ts-pick-probe.json
  build    NOT NAMED       5 of 10 row(s) …
  conditions.sweep  DIFFERS
         5 row(s)  ts-pick-probe-reversed
         5 row(s)  ts-pick-probe
```
(the class rationale, the FIX lines and the override note are elided)

The ratio the refusal points at reproduces rule 30's published evidence out of
the artefacts, baseline `A-32k-q8` at 76.32 t/s forward and 67.41 t/s reversed:

```
$ python scripts/ledger.py compare --metric throughput.decode \
      --source ts-pick-probe --ratio --baseline A-32k-q8
Do the ratios travel? Each pair, across 2 sweeps:

  B-32k-f16        / A-32k-q8              -8.9%     -8.2%      sign HELD, spread 0.007
  C-180k-q8        / A-32k-q8              -3.1%     -4.7%      sign HELD, spread 0.016
  D-32k-ngram      / A-32k-q8            +300.8%   +243.1%      sign HELD, spread 0.577
  E-32k-n4-p0      / A-32k-q8              +8.4%    +13.2%      sign HELD, spread 0.048
```

The first three reproduce the percentages METHODOLOGY rule 30 publishes for
this pair of passes. `D-32k-ngram` is the arm rule 30 does not quote, and its
spread of 0.577 is the reminder that a held sign is not a held magnitude.

**4. No energy row can be gated.** All 165 name neither the machine nor the
build: `attribute-power.py` writes the tier, the idle draw and the phase split
and no provenance block at all, and `power-cap-arms*.json` records no tier
either. Rule 24's tier is present on 147 of them only because the supersession
fold recovered it from the per-arm files. The fix is one call to
`provenance.toolchain()` in the writer.

**5. Every throughput figure a benchmark arm produced is uncomparable as an
absolute.** A `bench.py` artefact records no sweep, so the 13 `throughput.GSM8K`
rows for `IQ4_XS` — spread over the effort sweep, the cap-32k re-runs and the
quant-ladder anchor, across three days — are refused as a group, all 13 on the
same field. This is the shape of the retracted 83-86 t/s band: throughput
numbers lifted out of accuracy runs that were never one sweep.

```
$ python scripts/ledger.py compare --metric throughput.GSM8K --model IQ4_XS
REFUSED. 13 row(s) of throughput.GSM8K (class throughput) may not stand in one comparison.
  conditions.sweep  NOT NAMED
      13 of 13 row(s) carry no value for it: …
```

Two more that `check` reports as THIN rather than blocking, both from rule 3's
own enumeration: 335 throughput rows name no token regime, no desktop state
and no prior state — the regime one matters most, because a blind reproduction
measured the same file at 39 against 70 t/s at equal depth across regimes.

---

## The three catalogue columns

These are the columns an external model catalogue cannot get anywhere else,
and every campaign already measures them and then throws them away.

**Reasoning appetite** — `appetite.<DATASET>`, the mean output tokens per
answer, one row per benchmark per effort level. Read it beside
`conditions.max_tokens`: an appetite that reaches the cap did not degrade, it
truncated (rule 16).

```
python scripts/ledger.py compare --metric appetite.MATH-500 --source rule21/arm \
    --where conditions.judged=True --assert-same conditions.max_tokens
```

**Usable prompt budget** — `conditions.ctx` rides every row, and `vram.slack`
says how much board headroom was left at that window. The largest `ctx` that
produced rows for one (model, machine, build) is the largest window that was
actually measured, not the largest that was claimed.

```
python scripts/ledger.py rows --metric vram.slack --model IQ4_XS
```

**Practical output ceiling** — `truncation.<DATASET>` against
`conditions.max_tokens`. In the reference campaign the low arm truncated 1
MATH-500 answer at a 16,384 cap and 0 after the rule-7 re-run at 32,768; the
xhigh arm truncated 2 at 16,384. That pair of numbers is the ceiling, and it
is what a reader needs to size their own cap.

```
python scripts/ledger.py rows --metric truncation.MATH-500 --source rule21/arm
```

---

## Symptoms

| You see | It means |
|---|---|
| `REFUSED … NOT NAMED` | some rows carry no value for a gate field; record it, or narrow the selection |
| `REFUSED … DIFFERS` | the field is named on both sides and disagrees; follow the printed `--where` |
| `REFUSED. These rows span N metric classes` | narrow with `--metric` or `--class`; each class has its own gate |
| `A ratio is defined INSIDE one sweep` | the rows carry no `conditions.sweep`; run them through `scripts/arms.py` |
| `HAND-EDITED OR TRUNCATED -- body_sha256 does not match` | somebody edited the ledger; rebuild before trusting a row |
| `958 row(s), unchanged -- not rewritten` | nothing changed; `--force` restamps the header date |
| `no ledger at results/ledger.jsonl` | run `build` first |
| `rows built: got N, want M` in `selftest` | an extractor changed what it emits; fix the extractor or the expected count, never both blindly |

---

## Checklist — making a new campaign gate-clean

Do these during the run. Rule 28: a field not written down during the run
cannot be recovered at any price.

1. `python scripts/detect-machine.py --slug <slug>` before anything else. Every
   row whose artefact names no box falls back to `machine.json`, and the
   fallback is recorded as `conditions.machine_source` so it stays visible.
2. Put `provenance.toolchain(server_path, model_path, server_log=...)` at the
   top level of every artefact a probe writes. That one block supplies the
   machine, the build and the EXECUTION context — which backend decoded, and
   which device it resolved — for the gate. Where the box cannot answer the
   backend question, NAME it: `backend=` on the call, or
   `scripts/arms.py --backend cuda|vulkan|openvino|rocm|sycl|metal|cpu` at the
   runner, which is what an operator actually types. On Linux with an NVIDIA
   card it is never derivable, because `scripts/setup.sh` installs the Vulkan
   build unless `--cuda` was given.
3. Run multi-arm work through `scripts/arms.py`. Its per-probe ledger already
   carries the sweep, the arm, the pass, the position, the window and the
   window's source on every line — and, since 2026-08-30, the toolchain on
   `sweep_start` plus `backend`, `device`, `model_file`, `gpu` and the whole
   `execution` block on every probe line, taken once per arm launch after
   `/health` so the arm's own server log can be read for the device OpenVINO
   actually resolved. A line that says `toolchain: "NOT RECORDED: <reason>"`
   instead of those five is a line whose provenance import failed; fix that
   before the sweep, not after.
4. Write sampling as **fields**, not as a prose `conditions` line. The gate
   compares fields; `temperature: 0.0, top_k: 1, top_p: 1.0` is readable to it
   and `"greedy, temp 0 / top_k 1"` is not. Keep the prose line as well.
5. Name the instrumentation tier and the phase on every energy artefact
   (rule 24), and the K/V type and the `--spec-*` flags on every arm that
   reports acceptance (rules 3 and 11).
6. Give every artefact a `date` or `generated` field. Both ts-pick artefacts
   omit one, and a row that cannot be placed in time is blocked.
7. Run `python scripts/ledger.py check` before the report is written. Anything
   it blocks is something the report must not compare.

---

## Known limits

- **Conditions are copied, not interpreted.** A free-text `conditions` string
  travels with the row and is never parsed into fields; the gate cannot read
  it. That is deliberate — parsing prose into a comparability decision is how
  a wrong comparison gets a confident label.
- **Result arrays leak into `conditions`.** An artefact that puts its own
  summary statistics at the top level (`cold_means`, `hot_mean`) has them
  recorded as conditions. Over-recording is the rule-28 side of the trade.
- **The composite Mean inherits the artefact's own cap summary**, so a
  per-dataset cap difference inside a composite is invisible at that row.
  Compare the per-dataset cells when the cap is load bearing (finding 2).
- **A sweep is a file.** Two artefacts written by one script in one session are
  two sweeps to this tool unless one supersedes the other by the arm-subset
  rule. Use `scripts/arms.py`, which names the sweep explicitly.
- **The noise floor is not in the ledger.** `compare` prints the span and says
  so; rule 26's band is published once per campaign, page-wide, and this tool
  does not know it.
- **No cross-campaign row identity for models.** Two campaigns measuring the
  same `.gguf` produce rows whose `model_file` matches and whose `sha256` is
  not recorded here; `scripts/inspect-model.py` writes it into `model-*.json`
  and joining the two is not yet done.

---

## Registering it

`AGENTS.md` is capped at 120 lines and a new tool registers ONE routing line.
This tool's line is IN the router, as of 2026-08-30, immediately after the
arms.py row:

```
| comparing numbers across campaigns, or building the ledger | `scripts/ledger.py --help` — one row per measurement, and a gate that refuses illegal comparisons |
```

It was paid for by deleting the `<slug>` derivation paragraph from that file's
LAYOUT section, which restated `skills/field-guide/SKILL.md` item 6 — a Stage-0
procedure, in a router whose first row already sends every campaign start and
every resume to that file.
