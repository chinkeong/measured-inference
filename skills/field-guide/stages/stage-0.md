---
name: stage-0
description: Load when opening a campaign — Stage 0's instrumentation half. The interview itself is in SKILL.md; this file writes the campaign.json and machine.json every later stage resolves against, starts the 500 ms power logger, and takes the cold idle baseline before anything loads.
---

# Stage 0 — interview + instrumentation on
The interview is `skills/field-guide/SKILL.md`'s "Stage 0 — the interview"
section: one round of questions, then autonomous to the end. It closes only when
the two files below exist, and Stage 0 then adds two nearly-free instruments that
pay for themselves across the whole campaign.

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

**Write two machine-readable files before the interview closes.** Rule 27 gives
no second chance: every path, port and file name a later stage needs is decided
here or not at all.

- **`results/<slug>/campaign.json`**, copied from
  `results/TEMPLATE-campaign.json` and filled in — slug, port, `llama_dir`,
  `model_dir`, `work_dir`, `data_dir`, corpus, and every logical model name the
  arm files reference (`Q4_K_M`, `UD-IQ4_XS`, `mmproj`, whatever this campaign's
  roster needs) mapped to a real file. The arm files name their models
  logically and carry no paths, so this is the only place those names become
  files: without it `scripts/lib/paths.py` falls back to the environment and
  `PATH`, the roster resolves to nothing, and the stage stops on exactly the
  mid-run question rule 27 forbids.
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

**Prove the request before the interview closes.** Two things fail at Stage 1 and
cannot be asked about once rule 27 has closed the round: a gated repo, and a
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

**Start the power logger now and leave it running** — this is METHODOLOGY rule
24's instrumentation, opened at campaign start. A 500 ms CSV log costs one
process and a few MB a day, and it retroactively converts every later stage into
power data: the drafter sweep, the ceiling sweep, the depth ladder, the rule-21
suite and the effort arms all become energy arms *for free* if the log was
already running when they ran. Rerunning them later for watts is hours you do not
need to spend.

```powershell
# Windows — detached; survives harness session restarts
$q = "timestamp,power.draw,power.draw.instant,clocks.current.sm," +
     "clocks.current.memory,utilization.gpu,utilization.memory," +
     "memory.used,memory.reserved,temperature.gpu,pstate"
Start-Process nvidia-smi -WindowStyle Hidden `
  -ArgumentList "--query-gpu=$q","--format=csv","-lms","500" `
  -RedirectStandardOutput results/<slug>/data/power/campaign-power.csv
```
```bash
# POSIX
nohup nvidia-smi --query-gpu=timestamp,power.draw,power.draw.instant,\
clocks.current.sm,clocks.current.memory,utilization.gpu,utilization.memory,\
memory.used,memory.reserved,temperature.gpu,pstate \
  --format=csv -lms 500 > results/<slug>/data/power/campaign-power.csv &
```
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
