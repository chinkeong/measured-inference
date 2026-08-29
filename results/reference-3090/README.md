# reference-3090 — the two result files the reference campaign left outside the repo

`scripts/reference-3090/` holds the scripts the reference campaign ran
(Qwen3.8-27B on an RTX 3090, Windows/NVIDIA, 2026-08-22). This directory holds
two of the files those scripts WROTE. They lived on the author machine at
`E:\AI\aider\qwen\`, which no clone has, and `results/ARM-PROVENANCE.md` named
both of them as the artefacts that would settle open questions about what the
campaign actually measured. They are copied here byte for byte — BOM, CRLF and
all — because a primary record of an event that has already happened cannot be
re-created by any command (rule 29), and because the settled answer below is
worth nothing if a reader cannot check it.

    file                    bytes  written           sha256 (first 16)
    sweep-summary.txt         614  2026-08-22 11:38  3e122ff222bec8a9
    ctx-limit-result.txt      738  2026-08-22 02:49  97afb7bfd9ad1c76

Neither was edited on the way in. `sweep-summary.txt` was written by
`sweep-tune.ps1` (`$summary | Set-Content …`) and then appended to by
`sweep-pass2.ps1` (`$summary | Add-Content …`), which is why it carries three
pass-1 rows, three pass-2 rows, and one probe line above all of them.
`ctx-limit-result.txt` was written by `ctx-limit-sweep.ps1` in one call, and its
shape reproduces that script's `$result` array line for line.

## What `sweep-summary.txt` settles: the four unmeasured windows

`sweep-tune.ps1` phase 1 probes `-c 122880` first and walks DOWN to 98,304 /
81,920 / 65,536 / 49,152 only when that probe reads below its 40 t/s target:

    if ((Probe $MAXC) -ge $targetTps) { $good = $MAXC }   # done, no walk
    else { foreach ($c in @(98304, 81920, 65536, 49152)) { … } }

The artefact's own probe log holds **exactly one line**, and its header names
the window that was chosen:

    context: 122880 (probe results below)
    ctx=122880  probe(temp0): 700 tok in 13.6s = 51.3 t/s

**51.3 t/s against a 40 t/s target, so the walk never ran and the four lower
windows were probed ZERO times.** That is the whole of the evidence and it is
one line long: `$probeLog` is appended to by `Probe()` and by nothing else, so a
walk that had happened would have left four more lines here.

Consequence, and it is a licence rather than a restriction: the four
`tune-ctx-probe` arms below `-c 122880` in `scripts/arms/effort-sweep.json` were
**never measured by the reference campaign**, flatly. Any run of them is a new
measurement of that window under its own date (rule 1), never a reproduction of
a published figure.

## What `ctx-limit-result.txt` settles: the published ceiling's own probe log

The Q4_K_M context ceiling `templates/example-report.html` publishes — "about
131,000 tokens for the reference configuration" fully resident, and "about
213,000" before the server refuses to start — has its fourteen-probe walk here,
with the dedicated-VRAM reading beside every rung:

    largest spill-free context: 212992
    first degraded/failed context: 217088
    reference: 122880 = 55.4 t/s, floor = 41.6 t/s

55.4 × 0.75 = 41.55, rounded to 41.6 by the script's own
`[math]::Round($refTps * 0.75, 1)`. The walk steps +8,192 from 122,880 to
221,184, where 19.5 t/s falls through the floor, and the binary refinement then
takes one probe at 217,088 (41.2 t/s, still under 41.6) — which is how 212,992
comes to be the answer rather than 217,088. `scripts/arms/ctx-ceiling.json`'s
`reference_rungs` list is that ladder, and `arms.py --dry-run` prints the ladder
THIS machine derives against it as REPRODUCED or DIFFERENT.

## What neither file settles

Say this wherever these numbers are used.

* **Neither names its model file.** `ctx-limit-result.txt` says "current
  serve-qwen.bat flags" and `sweep-summary.txt` says nothing at all, so the
  `serve-menu-example.bat` entry [4] reconstruction — `ARM-PROVENANCE.md` entry
  2, twelve arms — is exactly as settled as it was before. What would close it
  is the real `serve-qwen.bat` as it stood on 2026-08-22, or a server log from
  those runs naming its `-m` path.
* **Neither records `-ngl`.** `ARM-PROVENANCE.md` entry 3's live doubt about
  the pass-1 effort figures (`confirm-benchmarks.ps1`: "the old runs through
  serve-qwen\*.bat may have carried the -ngl 64 handicap") is untouched by
  these files.
* **The pass-1 and pass-2 throughput rows are wall-clock, not server timings.**
  Both scripts compute `completion_tokens / stopwatch seconds`, which includes
  prefill; rule 20's instrument-first note is the reason that is a different
  quantity from the `predicted_per_second` every later probe reports. Read the
  `~57.9 t/s` column as the shape of the effort economics, not as a decode
  level.
* **51.3 t/s and 55.4 t/s do not stand beside each other**, and neither is a
  throughput reading this repo would publish today. They are single greedy
  probes from two different scripts, on two different prompts (a 700-token
  marine-aquarium essay against a 400-token red-black-tree code probe), in two
  different server loads — which is rule 3's content-and-regime clause and rule
  30's one-sweep clause at the same time. The `ctx-limit-sweep.ps1` numbers are
  also **the first request after each load**, with no warm-up discarded: rule
  12 says a first post-prefill probe reads up to 45% low, so every rung in that
  ladder is on ramping clocks. That does not damage the walk, because the floor
  is taken against a rung measured the same way — it is why the LEVELS in it are
  not quotable. Both probes are cited here for what they DECIDED: a branch not
  taken, and a floor computed.
