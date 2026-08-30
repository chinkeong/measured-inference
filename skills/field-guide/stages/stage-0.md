---
name: stage-0
description: Load when opening a campaign — Stage 0's instrumentation half. The interview itself is in SKILL.md; this file writes the four artefacts every later stage resolves against — campaign.json, machine.json, a model-*.json per roster file and the derived plan.json — starts the 500 ms power logger, and takes the cold idle baseline before anything loads.
---

# Stage 0 — interview + instrumentation on
The interview is `skills/field-guide/SKILL.md`'s "Stage 0 — the interview"
section: one round of questions, then autonomous to the end. It closes only when
four machine-readable files exist — `campaign.json`, `machine.json`, one
`model-<LABEL>.json` per roster file, and `plan.json` — and Stage 0 then adds two
nearly-free instruments that pay for themselves across the whole campaign.

**The bootstrap runs before Stage 0 can start.** `scripts/setup.sh` (POSIX) or
`scripts/setup.ps1` (Windows) installs a llama.cpp build into `bin/llama.cpp/`,
creates `.venv` and installs `requirements-min.txt` — the interpreter this
campaign's Python steps run under. On an NVIDIA box a non-CUDA backend is a
hard stop rather than a silent downgrade: setup exits non-zero instead of
installing the Vulkan build, because a campaign measured on Vulkan is not
comparable to one measured on CUDA (rule 3). `./scripts/setup.sh --cuda` builds
CUDA from source, which is the NVIDIA path on Linux — there is no official Linux
CUDA binary; `MEASURED_INFERENCE_ALLOW_VULKAN=1` overrides deliberately, and the
backend it installs is then a condition of every number the campaign publishes.

**Write the machine half first — `campaign.json` and `machine.json`.** Rule 31
gives no second chance: every path, port and file name a later stage needs is
decided here or not at all.

- **`results/<slug>/campaign.json`**, copied from
  `results/TEMPLATE-campaign.json` and filled in — slug, port, `llama_dir`,
  `model_dir`, `work_dir`, `data_dir`, corpus, and every logical model name the
  arm files reference (`Q4_K_M`, `UD-IQ4_XS`, `mmproj`, whatever this campaign's
  roster needs) mapped to a real file. The arm files name their models
  logically and carry no paths, so this is the only place those names become
  files: without it `scripts/lib/paths.py` falls back to the environment and
  `PATH`, the roster resolves to nothing, and the stage stops on exactly the
  mid-run question rule 31 forbids.
- **`results/<slug>/machine.json`**, written by
  `python scripts/detect-machine.py --slug <slug>`. It replaces `BOARD = 24576`
  and `RESERVE = 1796`, the reference 3090's pair that four probes carried: on a
  12 GB card `slack = BOARD - used` still reads comfortably positive, and rule
  13b's deep-fill probe then stamps PASS on a window that is spilling to host
  RAM — a correctness gate, not bookkeeping. A missing machine.json is fatal by
  design, and every field it writes is MEASURED, DERIVED, CITED, or null with
  the reason it is null. Name what the desktop is doing with `--desktop-state`,
  and pass `--ram-channels` / `--backend` for what this box cannot report: an
  idle-desktop reserve is not a fence for a loaded desktop (rule 14).
  It also records the PRIVILEGE this run had — `elevated`, `sudo_nopasswd`,
  `privilege_path` — because an elevated run can do things an unelevated one
  cannot, and that is a condition of every number (rule 3). Running the campaign
  from a root shell or an Administrator prompt is a supported choice; the one
  thing it forfeits is `pl_writable_without_elevation`, which stays `null` by
  design because a power-limit set that succeeds under root says nothing about
  an ordinary user. Rule 28 makes that permanent for this campaign, so if the
  answer matters, run `detect-machine.py` once as a normal user before the
  elevated run. `scripts/power/README.md` section 4 carries the whole trade.

**Prove the request before the interview closes.** Two things fail at Stage 1 and
cannot be asked about once rule 31 has closed the round: a gated repo, and a
quant that does not fit the card. Both are network and arithmetic, so settle
them here:

```
python scripts/check-request.py <org/repo> --quant <LABEL> --c-min <N>
```

It derives the slug, lists the GGUFs, proves ACCESS with a range request that
reads real bytes and checks the GGUF magic — a listing succeeds on a gated repo,
so only the range request is proof — and prices the FIT as
`weights + KV(c_min) + projector` against `machine.json`'s measured board minus
the desktop reserve, showing the arithmetic. It reports UNPROVEN rather than
PASS when machine.json is missing, because a guessed board size is how a
spilling window gets stamped PASS (rule 13). A FAIL here costs a re-pick; the
same FAIL at Stage 1 costs the download and the hours after it.

**Then write the model half — the profile per file, then the plan.** Both are
header reads and arithmetic: no download, no GPU, no `.venv` needed.

```
python scripts/inspect-model.py <org/repo> --quant <LABEL> --slug <slug>
python scripts/plan-campaign.py --slug <slug>
```

- **`results/<slug>/model-<LABEL>.json`**, one per model FILE — run
  `inspect-model.py` once per file on the roster, mmproj and draft head
  included. It reads the GGUF's own header over a few ranged GETs (measured
  2026-08-29: 6 MiB in 6 requests for `unsloth/Qwen3-1.7B-GGUF`; 23 MiB in 23
  requests for the reference 27B, its `mmproj-F16.gguf` and its MTP head) and
  records `arch` and whether this build can load it, `context_length`,
  `block_count`, the head counts, the tensor table with exact params and bpw,
  `kv_bytes_per_token` for f16/q8_0/q4_0 with the arithmetic that produced each,
  a sibling mmproj and its projector type, a sibling draft head, and the chat
  template including whether it exposes an effort knob. Every field is MEASURED,
  DERIVED, CITED, or null with a `why`. `capabilities` is the list Stages 3, 4
  and 6 are gated on: the reference 27B reads `text, vision, drafter, effort`,
  `unsloth/Qwen3-1.7B-GGUF` reads `text, effort`.
- **`results/<slug>/plan.json`**, every `model-*.json` crossed with
  `machine.json`: the fit table, the DERIVED ceiling rungs Stage 2 sweeps, and a
  RUNS/SKIPPED verdict with a quotable reason for every stage unit and every
  `scripts/arms/*.json`. Exit 0 is a complete plan; **1 is a campaign that cannot
  start** — an architecture this build does not list, or nothing that fits at any
  window — and stops Stage 0 here rather than at the first load; **2 is a plan
  with an UNKNOWN in it**, and an unsized fit is not a plan.

Without them the campaign runs the reference 27B's assumptions over whatever
model was asked for: a 25-arm ceiling ladder sized for a 24 GB card, a drafter
sweep on a model with no draft head, a vision stage with no projector. The
profile is what turns each of those into an explicit, quotable SKIPPED instead of
a silently missing axis, which a reader cannot tell from a measured negative
(rule 2).

**Start the power logger now and leave it running** — this is METHODOLOGY rule
24's instrumentation, opened at campaign start. A 500 ms CSV log costs one
process and a few MB a day, and it retroactively converts every later stage into
power data: the drafter sweep, the ceiling sweep, the depth ladder, the rule-21
suite and the effort arms all become energy arms *for free* if the log was
already running when they ran. Rerunning them later for watts is hours you do not
need to spend.

```powershell
# Windows — detached; survives harness session restarts
.\scripts\power\sample-power.ps1 -Start -Csv results\<slug>\data\power\campaign-power.csv
```
```bash
# POSIX — the same eleven columns plus a twelfth, the same 500 ms
bash scripts/power/sample-power.sh start --csv results/<slug>/data/power/campaign-power.csv
```
**Use the shipped starters rather than a hand-rolled `nvidia-smi` line.**
Columns 1–11 of their `--query-gpu` lists are identical, so a Windows log and a
Linux log integrate and merge as one measurement; the POSIX one appends
`clocks_event_reasons.active` as column 12, which rule 28 wants and the
PowerShell one still owes. Each watches the CSV GROW before reporting success,
refuses a second logger on the same path and an existing non-empty CSV
(`-Force` / `--force`), and drops a `<csv>.logger.json` sidecar recording the
pid, the query, the tier label, and — on POSIX — `euid`, `elevated` and
`enforced_power_limit_w`, the cap in force when the log began. **On Linux never
hand-roll `nvidia-smi ... -f <file>`**: it block-buffers and flushes only at
exit, so the CSV reads as empty for the whole run and `arms.py` records
`power_logging: false` while a logger is in fact running (measured 2026-08-30;
`reference/platform-notes.md`). `list` shows every telemetry loop on the box and
kills nothing; `stop --csv <path>` / `-Stop -Csv <path>` ends one by the file it
writes, never by process name.

Clocks, pstate and util are in the query on purpose: they are how you prove a
low-watt sample was a **ramping** board (rule 24's clock-ramp caveat) rather
than an efficient one. One file per stage is fine — record each filename and its
start time in `campaign.md`, and restart the logger after any reboot.

**Take the cold idle baseline before anything loads**: board idle, no server,
n≥15 samples, dated, tier-labeled (reference 2026-08-22: **33.2 W**). Take it
**cold** — a board still cooling from earlier work reads high (one reference
log's first 10 samples averaged 58.0 W against the 33.2 W cold reading) — or
state which it was. The loaded-idle flavor is taken in Stage 1, the first time a
server is up and idle (reference: **30.7–31.1 W** — a resident model costs
almost nothing until asked). Both go in `campaign.md` with date and tier label;
every idle-subtracted figure downstream depends on them.
