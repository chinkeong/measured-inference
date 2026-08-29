# ARM-PROVENANCE — what `scripts/arms/*.json` may be quoted for

Read this before quoting any number an arm file produces. Twenty-three arms and
four bench arms across the five files were checked against the PowerShell
originals in `scripts/reference-3090/` on 2026-08-29: every flag, every value,
its order, the model each arm runs, the probe prompt character for character,
the caps, the repeat counts and the discard protocol. All 27 flag lists and all
33 probe specifications reproduce from their sources. Twelve arms carry a
reconstruction that the shipped launcher contradicts, and four of those twelve
name windows nothing shipped records as measured.

A wrong flag does not fail loudly. It produces a real number for a
configuration nobody chose, and rule 3 says a number without its true
conditions is unfalsifiable — so the grade column below is the condition, and
the last section is the list of arms whose numbers do not ship without a
re-measurement.

## How each grade was reached

| Grade | Meaning |
|---|---|
| CONFIRMED | Every token reproduces from the `.ps1` the arm names in `derived_from`. |
| RECONSTRUCTED-PLAUSIBLE | The `.ps1` never stated it; the value comes from `serve-menu-example.bat` entry [4] and is consistent with everything else shipped. |
| SUSPECT | Cannot be derived from anything shipped, or contradicts the original. |

Four checks produced the grades, all read-only and none touching a GPU:

1. **Flag diff.** Each arm's argv was re-derived by parsing the `.ps1` array or
   the `.bat` launch block, dropping `-m` / `--api-key dummy` / `--host` /
   `--port`, collapsing the duplicate `-ngl` onto its first slot, and replacing
   weight paths with the logical model names — then diffed token for token
   against the arm file. **27 of 27 flag lists reproduce.**
2. **Probe diff.** Prompt strings, `max_tokens`, `temperature`, `top_k`,
   repeat and discard were lifted out of each `.ps1` by regex, never retyped,
   and compared. **Every probe reproduces**, including the 546-character
   verbatim-copy prompt and its LF newlines.
3. **Frozen-hash reproduction.** All seven `prompt_sha256` values in
   `depth-series.json` were rebuilt twice — once in Python, once in Windows
   PowerShell 5.1.26100.9168 using the `Filler()` function lifted verbatim out
   of `nuance-suite.ps1` — and **7 of 7 match**, character counts included.
4. **Parse gate.** `python scripts/arms.py --arms scripts/arms/<file>.json
   --list` lists all five files and raises no arm warning. Four of them exit 0;
   `ctx-ceiling.json` exits 2 and names the two commands that write
   `results/<slug>/plan.json`, because its two arms are rung templates and this
   repo carries no plan for them. That abort is the file's declared design, not
   a defect — expect it, and run `scripts/plan-campaign.py` first.

Reproduce check 3 with the repo alone:

```python
note = lambda i: ('Note %d: subsystem alpha-%d reported latency %d ms on shard %d, '
                  'retry budget %d, digest fragment %x, remark: threshold crossed only '
                  'when the moving median over window %d exceeded baseline by %d percent.'
                  % (i, (i*7)%97, (17*i)%993, i%13, (3*i)%29, (i*48271)%1048573,
                     (5*i)%47, (11*i)%83))
build = lambda pre, n, suf: pre + '\n'.join(note(i) for i in range(1, n+1)) + suf
# hashlib.sha256(build(probe["prefix"], probe["filler_notes"], probe["suffix"]).encode()).hexdigest()
```

## Arm → grade → evidence

### `scripts/arms/spec-sweep.json` — 6 arms, stage 3

| Arm | Grade | Evidence |
|---|---|---|
| `spec-none` | CONFIRMED | `spec-sweep.ps1` config 1/6 appended to `probe-config.ps1`'s 38-token base argv; diff empty. |
| `spec-mtp-n10-p0` | CONFIRMED | config 2/6; diff empty. |
| `spec-mtp-n10-p0.75` | CONFIRMED | config 3/6; diff empty. |
| `spec-mtp-n16-p0.5` | CONFIRMED | config 4/6; diff empty. |
| `spec-mtp-n6-p0.5` | CONFIRMED | config 5/6; diff empty. |
| `spec-mtp-n4-p0.75` | CONFIRMED | config 6/6; diff empty. |

The model is right, and it is the trap the brief names: `probe-config.ps1`
defaults to `Qwen3.8-27B-Q4_K_M.gguf`, `spec-sweep.ps1` sets no `PROBE_MODEL`,
and all six arms carry `Q4_K_M`. The probe prompt is `spec-sweep.ps1`'s
exported `PROBE_TEXT`, not `probe-config.ps1`'s own marine-aquarium default —
162 characters, byte-identical. `max_tokens 700`, `temperature 0`, `top_k 1`,
one probe per arm, no discard: all four come straight from
`probe-config.ps1`'s request body.

`-ngl` is 99 in every arm. `probe-config.ps1` writes `-ngl 64` into its base
and every one of its four callers — `spec-sweep.ps1`, `spec-sweep2.ps1`,
`accept-demo.ps1`, `confirm-benchmarks.ps1` — appends a later `-ngl 99`, which
wins. The arm files collapse the pair onto the base's slot, so the effective
offload is unchanged and rule 15 is satisfied by the value that actually ran.

### `scripts/arms/acceptance.json` — 2 arms, stage 3

| Arm | Grade | Evidence |
|---|---|---|
| `accept-novel-code` | CONFIRMED | `accept-demo.ps1` `$novel`, 162 chars, byte-identical; extras `-ngl 99 --spec-type draft-mtp --spec-draft-n-max 10 --spec-draft-p-min 0.5` reproduce. |
| `accept-verbatim-copy` | CONFIRMED | `$copy` rebuilt as instruction line + two LF + the `@'…'@` here-string: 546 chars, byte-identical, no CR. |

The LF claim in the file's own notes holds: `accept-demo.ps1` carries 34 LF and
zero CR, `.gitattributes` sets `* -text` repo-wide, and `git check-attr text`
returns `unset` — so an Ubuntu clone gets the same bytes and the same token
count. Had the here-string arrived CRLF, the acceptance figure would have moved
and nothing would have said so.

`templates/example-report.html` confirms this pair independently: *"same card,
same flags (n-max 10, p-min 0.5, temperature 0), only the content differs …
51.5 t/s at acceptance 0.47 … 119.8 t/s at acceptance 0.93 … on the reasoning
stream"*. The reasoning stream is what `--reasoning-preserve` plus
`reasoning_effort: low` produce, and both arms carry both.

### `scripts/arms/depth-series.json` — 2 arms, 7 probes, stage 3

| Arm | Grade | Evidence |
|---|---|---|
| `iq4xs-c122880-depth-ladder` | CONFIRMED | `nuance-suite.ps1` PART 1 argv, diff empty; depths 60 / 220 / 460 / 925 / 1400 / 1850 lifted from its own `foreach`; cap 400; six frozen hashes reproduce. |
| `iq4xs-c196608-deep-decode-460` | CONFIRMED | `deep-decode-probe.ps1` argv, diff empty; 460 notes lifted from its loop bound; cap 700; frozen hash reproduces. |

The two prefixes differ on purpose and the file says so — `Read these notes,
then do the task at the end.` against `Reference notes for the task below. Read
them, then do the task at the end.` — which is why the same 460 notes hash
differently at 94,994 and 95,023 characters. Neither arm loads a projector, and
neither `.ps1` does. This is the strongest-provenance file of the five: its
inputs are frozen by hash, so a drifted prompt aborts the sweep before a server
starts (rule 23).

### `scripts/arms/ctx-ceiling.json` — 2 template arms, stage 2

| Arm | Grade | Evidence |
|---|---|---|
| `iq4xs-mmproj-c{rung.c}` | CONFIRMED | `iq4-ctx-sweep.ps1` builds its own argv; diff empty. No sampler flags, no `--reasoning-preserve`, no `--chat-template-kwargs`, no `--image-min-tokens` — exactly as the `.ps1` has it. Cap 400, temp 0, top_k 1. |
| `q4km-mmproj-c{rung.c}` | RECONSTRUCTED-PLAUSIBLE | `ctx-limit-sweep.ps1` shells out to `serve-qwen.bat low <ctx>`, which this repo never shipped. The flag list reproduces token for token from `serve-menu-example.bat` entry [4]; the entry number is the reconstruction. |

The `q4km` reconstruction carries the strongest external evidence in the repo,
and it is worth writing down because a stranger checking the `.bat` alone will
reach the opposite answer. `serve-menu-example.bat` auto-picks entry [1]
(UD-IQ4_XS) after eight seconds when no model argument is given, and
`ctx-limit-sweep.ps1` gives none. Four shipped sources say the default it
actually took was entry [4]:

- `templates/example-report.html`: *"Probed 2026-08-22 with Q4_K_M (q8_0 KV,
  drafter on, projector loaded …) by stepping -c upward with short
  temperature-0 decode probes: speed holds at 50–55 t/s all the way to -c
  212992, turns borderline at 217,088 (41.2 t/s), and collapses at 221,184
  (19.5 t/s)."* That names the file, the KV width, the drafter and the
  projector, and the file is the one thing the menu's own default disagrees
  with.
- 217,088 is arithmetic, not coincidence: it is `floor(((212992 + 221184) / 2)
  / 4096) * 4096`, the exact midpoint `ctx-limit-sweep.ps1`'s binary refine
  computes between its last good rung and its first bad one.
- `iq4-ctx-sweep.ps1`'s header treats the Q4_K_M ceiling as measured before
  that script ran (*"Q4_K_M measured ~131k resident / ~213k shallow"*), and
  `scripts/reference-3090/README.md` maps the two scripts to Q4_K_M then
  IQ4_XS.
- `serve-menu-example.bat`'s own header carries the result: *"Q4_K_M (15.4
  GiB) … +mmproj resident at -c 122880 (ceiling ~131k)"*.

**If that reconstruction is wrong, exactly two things change**: the model
becomes `UD-IQ4_XS` and `--image-max-tokens 10580` joins the flag list. Every
other token of entry [1] and entry [4] is identical, `-ngl 99` included.

Two more properties of this file check out. The `reference_rungs` are the
generator's, not the campaign's: `ctx-limit-sweep.ps1` breaks at the first rung
below its floor, so rungs above 221,184 were never measured — and the file's
`stop_rule` says exactly that. The `iq4xs` rungs reproduce the `.ps1`'s jump
from 122,880 straight to 180,224 and then +16,384 steps, rather than smoothing
it into a uniform ladder. The floor rule matches the source line
(`$floor = [math]::Round($refTps * 0.75, 1)`).

### `scripts/arms/effort-sweep.json` — 11 arms + 4 bench_arms, stage 6

| Arm | Grade | Evidence |
|---|---|---|
| `effort-pass1-low` / `-medium` / `-xhigh` | RECONSTRUCTED-PLAUSIBLE | `sweep-efforts.ps1` passes the effort and nothing else, so `-c 122880` is entry [4]'s own default. Flags reproduce from entry [4]. Uncapped, no sampler keys — `sweep-efforts.ps1` sends neither `max_tokens` nor `temperature`, which is verified by grep, and the arms carry `n_predict: -1` with no sampler block. |
| `effort-pass2-low` / `-medium` / `-xhigh` | RECONSTRUCTED-PLAUSIBLE | `sweep-pass2.ps1` passes `<effort> 122880`, so the window is stated by the original and only the entry number is reconstructed. |
| `tune-ctx-probe-c122880` | RECONSTRUCTED-PLAUSIBLE | `sweep-tune.ps1` phase 1 probes 122,880 first. Warm-up `Say OK.` at 16 tokens with no sampler, then the marine-aquarium essay at 700 tokens, temp 0, top_k 1; `discard_first: true` drops the warm-up, which is rule 12 in the original's hand-rolled form. |
| `tune-ctx-probe-c98304` / `-c81920` / `-c65536` / `-c49152` | RECONSTRUCTED-PLAUSIBLE † | The `-c` values are literals in `sweep-tune.ps1`; the flags are entry [4]'s. **† The original reaches these four only on a condition nothing shipped records as met — see the last section.** |
| `gsm8k200-low` / `-medium` / `-xhigh` | CONFIRMED | `effort-gsm8k.ps1` builds its own argv: `-c 32768`, no projector, `--chat-template-kwargs` per level. Diff empty. Bench line reproduces `--datasets GSM8K --samples 200 --max-tokens 4096 --greedy --score`. |
| `gsm8k200-xhigh-16k` | CONFIRMED | `xhigh-16k.ps1`, diff empty, cap 16,384. Rule 7's raise-the-cap-and-rerun-that-arm-only, and the arm's own `derived_from` states why low and medium need no rerun in the `.ps1`'s own words. |

One note in this file was wrong and is now fixed. It described the
`tune-ctx-probe` group as *"sweep-tune.ps1 phase 1's published
throughput-vs-window curve"*. No such curve is published: `81,920` appears
nowhere in `templates/example-report.html`, and neither does any five-point
window curve from `sweep-tune.ps1`. The note now states what the five values
are — literals in the `.ps1` — and that four of the five may never have run.

## Do not publish these numbers without a re-measurement

Six entries. Each names what is unsettled and what would settle it.

**1. `tune-ctx-probe-c98304`, `-c81920`, `-c65536`, `-c49152` — four windows
the reference campaign probably never measured.** `sweep-tune.ps1` phase 1
probes 122,880 first and walks down to these four only when that probe measures
below its 40 t/s target, breaking at the first rung that clears it. So the
original took between zero and four of them, decided at runtime by the desktop
VRAM load of the day, and no artefact in this repo records which. `arms.py`
walks no data-dependent stop rule, so a plain run takes all five. Publish a
reading from any of the four as a new measurement of that window, under the
date it was taken, never as a reproduction of a reference figure (rule 1).
*Settled by:* the `sweep-summary.txt` or `ctx-limit-result.txt` the originals wrote to
`E:\AI\aider\qwen\`, neither of which is in the repo. Absent those, treat the
four as unmeasured and say so.

**2. Every arm launched through `serve-menu-example.bat` entry [4] — twelve
arms.** `q4km-mmproj-c{rung.c}`, the six `effort-pass*` arms and all five
`tune-ctx-probe` arms take their model and flags from a menu entry that the
shipped `.bat` does not select. The evidence for entry [4] is strong for the
ceiling ladder and weaker for the effort sweeps, where it rests on
`$modelName = 'Qwen3.8-27B-Q4_K_M'` in `sweep-efforts.ps1` and
`sweep-tune.ps1` — an output filename, which a stale label can survive — plus
the inference that one launcher had one default on one day. Numbers from these
arms carry the model as a reconstructed condition, not a measured one.
*Settled by:* the real `serve-qwen.bat` as it stood on 2026-08-22, or any
server log from those runs naming its `-m` path.

**3. The pass-1 effort figures, if any are carried forward rather than
re-run.** `confirm-benchmarks.ps1`'s header records a live doubt about exactly
these runs: *"the old runs through serve-qwen\*.bat may have carried the -ngl
64 handicap"*. The arms carry `-ngl 99`, which is the correct value to run
(rule 15) and is supported for 2026-08-22 by `sweep-tune.ps1`'s own dated
comment (*"healthy temp-0 essay probe with MTP measures ~43 t/s … (2026-08-22,
-ngl 99)"*) and by `templates/example-report.html`'s 50–55 t/s ceiling ladder,
a band `-ngl 64` cannot reach. The flag is right; what is not established is
that every published pass-1 number came from a server carrying it. Re-run
rather than quote.

**4. Any absolute t/s placed beside a number from another sweep.** Rule 30
holds across these files: `ctx-ceiling.json` alone contains two sweeps with
different flag sets — `iq4xs-ceiling` passes no sampler flags, no
`--reasoning-preserve`, no `--chat-template-kwargs` and no `--image-min-tokens`
— and `depth-series.json` contains two ladders of different parity, window,
alias and cap. Compare inside one `sweep` field or not at all.

**5. Any window from `ctx-ceiling.json` labelled resident or safe.** Its
probe is 400 tokens on a freshly loaded server, which finds the shallow-safe
ceiling and the load-failure point and nothing else. Rule 13 requires a
deep-fill probe near the top of any window before it is labelled; take it from
`depth-series.json`. The file says this; it is repeated here because the
`stop_rule` reads like a ceiling and is not one.

**6. Every arm in all five files, on the ramp.** Six of the eleven
`effort-sweep` arms and every arm in the other four files carry `repeat: 1`
and `discard_first: false`, because that is what ran. Rule 12 says the first
probe after a server load reads up to 45% low. Only the five `tune-ctx-probe`
arms discard, and only because `sweep-tune.ps1` hand-rolled a warm-up. A
cooled rerun raises `repeat` and sets `discard_first` — and is then a new
sweep, not a rung-by-rung comparison against the published numbers.

## Gaps a stranger will hit

**`spec-sweep2.ps1` is not ported, and stage-3 promises its arms.**
`skills/field-guide/stages/stage-3.md` says *"Sweep n-max × p-min on a
realistic code probe (~10 configs; run: `python scripts/arms.py --arms
scripts/arms/spec-sweep.json`)"*. That command runs 6. The missing four are
`spec-sweep2.ps1`'s refinement round — `n4/p0.5`, `n6/p0.75`, `n4/p0.9`,
`n3/p0.75` — around the n4/p0.75 winner, and they are the arms that justify
shipping n4/p0.75 over its neighbours. Each is the same base argv with those
two values changed and the same 162-character red-black-tree prompt, so the
port is mechanical. This report does not make it: adding arms is a build, and
the four extra server loads are the owner's GPU hours to spend.

**`nuance-suite.ps1` PART 3 and PART 4 have no arm file.** `depth-series.json`
takes PART 1 and says so. PART 3 (`--parallel 2` at `-c 131072`, 65,536 per
slot) and PART 4 (three images at `--image-max-tokens 10580`) are not in
`scripts/arms/`, so the concurrency and multi-image measurements have no
Linux-runnable implementation. PART 4 is the hallucinated-sight check rule 19
demands — three different screenshots, ranked, with the model asked which one
looks broken — and no arm file carries it.

**`confirm-benchmarks.ps1` and `dflash-real-code.ps1` are not ported.** The
first is the pass that re-ran every cited number with `-ngl 99` and sets
`PROBE_MODEL` and `PROBE_CTX` per probe across Q4_K_M and two NVFP4 files; the
second is the external-drafter comparison. Both are runnable through
`probe-config.ps1`'s base argv, which `spec-sweep.json` and `acceptance.json`
transcribe correctly.

**`effort-sweep.json` declares `"stage": 6`, and `reference-3090/README.md`
maps its scripts to two stages** — Stage 4 for the appetite measurement, Stage
6b for the judged arms. A Stage 4 agent listing arm files by stage will not see
it.

## What is settled

The mechanical fidelity of these files is settled. Twenty-seven flag lists,
thirty-three probe specifications, seven frozen prompt hashes and every
`-ngl` reproduce from the shipped originals, and the two places where the port
departs from the source text — the collapsed `-ngl` duplicate and the dropped
`--api-key` / `--host` / `--port` — are declared in every file's notes and are
semantics-preserving. `scripts/probe-config.sh` drops `--api-key` the same way
and `scripts/bench/bench.py` injects the transport the same way, so the two
departures are the repo's convention rather than this port's invention.

What is not settled is which menu entry four PowerShell scripts selected on
2026-08-22, and whether four of the five `tune-ctx-probe` windows were ever
measured at all. Those are the two questions to answer before any number from
the twelve reconstructed arms is published as a reproduction.
