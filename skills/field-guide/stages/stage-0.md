---
name: stage-0
description: Load when opening a campaign — Stage 0's instrumentation half. The interview itself is in SKILL.md; this file starts the 500 ms power logger and takes the cold idle baseline before anything loads.
---

# Stage 0 — interview + instrumentation on
The interview is `skills/field-guide/SKILL.md`'s "Stage 0 — the interview"
section: one round of questions, then autonomous to the end. Stage 0 then closes
with two nearly-free things that pay for themselves across the whole campaign.

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
