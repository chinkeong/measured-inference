# `scripts/power/` — energy attribution for local inference

Four tools that turn a GPU power log plus a llama-server's own timings into
defensible per-arm energy numbers: **J/token, Wh/answer, tokens/kWh, EDP**,
split by **prefill vs decode**.

| file | role |
|---|---|
| `sample-power.ps1` | start / stop / list the detached 500 ms `nvidia-smi` CSV logger — **Windows** |
| `sample-power.sh` | the same logger, columns 1–11 of the same CSV plus a twelfth, a sidecar of the same name — **POSIX** (Linux, WSL2) |
| `capture-request.ps1` | POST one generation, stamp `t_start`, append the request-event JSONL — **the join point, Windows only; section 7 says what POSIX does instead** |
| `attribute-power.py` | integrate the power log over each window, split the phases, emit the metrics (stdlib only) |

**The logger reaches parity; the join point does not.** The two starters write
the same columns 1–11 in the same order — section 3, where the POSIX one's
twelfth column is also declared — and `attribute-power.py` is stdlib Python with
no platform in it, so it integrates a Linux log exactly as it integrates a
Windows one. `capture-request.ps1` has **no POSIX twin**, and nothing in
`scripts/` replaces it. `scripts/arms.py`'s per-probe ledger carries two of the
six fields that join wants flat — `t_start_iso` and `label` — and the other four
(`prompt_ms`, `predicted_ms`, `prompt_n`, `predicted_n`) nested under `timings`,
where the integrator does not look, so pointing `--events` at a raw arms ledger
dies on the first non-probe line and then, once those are filtered out, reports
zero joules for every label. Section 7 carries the converter that closes the gap,
and the run that shows it closing.

The GPU power cap needs an elevated shell and is section 4, with the arm that
measures it. `power-cap-arms.py`, `slots-telemetry.py`, `host-telemetry.ps1`,
`metrics-telemetry.py`, `silicon-telemetry.py`, `agentic-cost.py` and
`make-powercap-chart.py` also live in this directory and carry their own
headers.

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

## 3. The logger — `sample-power.ps1` on Windows, `sample-power.sh` on POSIX

Two files, one contract — and the places where the contract is looser than it
reads are named here rather than left to be discovered. Both start, stop and
list the same detached 500 ms `nvidia-smi` CSV logger, write the same eleven
columns in the same order — the POSIX one appends
a twelfth, below — drop a `<csv>.logger.json` sidecar under the same name beside
the CSV, and refuse the same two things: a second logger on a CSV one is already
writing, and an existing non-empty CSV. Both refusals are overridable —
`-Force`, `--force`.

**The two sidecars are not the same record.** `sample-power.ps1` writes nine
keys — `pid`, `csv`, `mode`, `interval_ms`, `query`, `started_iso`,
`started_by`, `tier`, `verified`. `sample-power.sh` writes a **sixteen-key
superset**: those nine under the same spellings, plus `gpu_index`, `gpu_name`,
`driver_version`, `enforced_power_limit_w`, `euid`, `elevated` and
`stderr_log` — the rule-3 conditions the CSV rows cannot carry, and a stderr
path that has to outlive the starting shell. Either platform's `stop` can read
the other's record, because `pid` is the only key either one reads back; a
consumer that expects the nine and finds sixteen is reading a superset, not a
different file. Section 4's table lists the extras and says why each is there.

```powershell
# Windows — start (one file per phase is the convention)
.\sample-power.ps1 -Start -Csv results\<slug>\data\power\campaign-power.csv

# see every nvidia-smi telemetry loop on the box (read-only, kills nothing)
.\sample-power.ps1 -List

# stop the one writing that CSV
.\sample-power.ps1 -Stop -Csv results\<slug>\data\power\campaign-power.csv
```

```bash
# POSIX — the same three, in the same order, from the repo root
bash scripts/power/sample-power.sh start --csv results/<slug>/data/power/campaign-power.csv
bash scripts/power/sample-power.sh list
bash scripts/power/sample-power.sh stop  --csv results/<slug>/data/power/campaign-power.csv

bash scripts/power/sample-power.sh stop --pid 12345   # explicit target, still verified
bash scripts/power/sample-power.sh --help             # starts nothing, stops nothing
```

Verbs are `start` / `stop` / `list`. Flags: `--csv` (required by `start`, and
by `stop` unless `--pid`), `--interval-ms` (default 500), `--index N` to log one
GPU instead of all, `--force`, `--verify-seconds` (default 8, how long the file
must be watched growing before the logger is believed) and `--pid`. Exit codes:
**0** did what was asked, **2** usage, **3** refused or the target could not be
ended, **4** no `nvidia-smi` or no samples appeared, **5** nothing to stop.
Put the CSV under `results/<slug>/data/power/` — that is the only place
`arms.py`'s freshness check looks.

**Invoke it as `bash scripts/power/sample-power.sh …` and the executable bit
does not matter.** That is the form every command in this file uses, and the
reason. `./scripts/power/sample-power.sh` does need the bit, and git carries it:
the index records mode `100755` for this file, the same mode it records for
`scripts/setup.sh` and `scripts/probe-config.sh`, so a fresh clone gets it
executable. Restore it with
`git update-index --chmod=+x scripts/power/sample-power.sh` if it is ever lost.

**Nothing asserts that bit — it is remembered, not checked.** Checked
2026-08-30: `scripts/verify/ubuntu-dryrun.sh:37` is
`[ -x scripts/setup.sh ] || { echo "FAIL: setup.sh is not executable on a fresh clone"; exit 11; }`,
which is a different file's bit. `scripts/arms.py` names `sample-power.sh` in
the remedy it prints when a sweep starts with no power log, so the file is
referenced — but a reference is not an assertion: no ship step and no
verify-lane check ever tests that the bit is set. An earlier edition of this paragraph said the dry-run asserted it; that
sentence transferred a guarantee that does not exist, in the one paragraph a
reader opens when the fresh-clone case breaks.

Emits the same columns the campaign already uses:

```
timestamp, power.draw [W], power.draw.instant [W], clocks.current.sm [MHz],
clocks.current.memory [MHz], utilization.gpu [%], utilization.memory [%],
memory.used [MiB], memory.reserved [MiB], temperature.gpu, pstate
```

`sample-power.sh` appends one more, `clocks_event_reasons.active`, as column 12
— the rule-28 note below says why, and what the PowerShell script still owes.

**Columns 1–11 are identical today, and nothing in this repository checks that
they stay so.** Diffed by hand on 2026-08-30: `sample-power.ps1`'s
`$script:QUERY` and `sample-power.sh`'s `QUERY` carry the same eleven fields in
the same order, so `nvidia-smi` writes the same header names in the same
sequence on both. No test, no gate member and no lane in
`scripts/verify/run-all.py` compares the two strings. The alignment is a
convention with a measurement behind it, held by whoever edits one query
remembering the other — not an invariant something enforces, and this paragraph
used to claim it was.

The one difference in the bytes is the line terminator, which is `nvidia-smi`'s
own (CRLF on Windows, LF on Linux) and which `attribute-power.py` never sees: it
opens the file with Python's universal newlines and strips every field before
using it. A Linux log and a Windows log are therefore the same measurement of
the same board, and either integrates with no flag and no conversion.

**Reordering a field costs nothing; renaming one is read off the wrong column,
silently.** `attribute-power.py` resets its power column for every file it opens
(`attribute-power.py:106`) and finds it in that file's header by name (`:115-130`),
so a reordered-but-headered CSV is read correctly and two differently-ordered
logs still merge. Measured 2026-08-30 against this repo's own
`rule21-power.csv`, one 40 s window: the file as written, the same rows with
`power.draw` moved to the last column, and both merged in one invocation all
integrate to **13,858.7 J**. Rename it instead — `power.draw [W]` relabelled,
nothing else touched — and the header search falls through to the next column
whose name still starts with `power.draw`, integrating `power.draw.instant`:
**13,875.6 J** over that same window, a different column reported with no error
and no warning. A headerless file is read positionally and carries the same
exposure. **The field NAMES are what must not move**; the order is held fixed so
that the two queries stay diffable by eye, which is the only check there is.

**One rule-28 field is now in the POSIX logger and still missing from the
PowerShell one.** Rule 28 requires every energy sample to carry
`utilization.memory` **and** `clocks_event_reasons.active` beside `power.draw`,
because two runs can report the same J/token for opposite reasons — one starved
of bandwidth, the other clipped by its power limit — and watts alone cannot
separate them. `sample-power.sh` gained the second field on 2026-08-30,
appended LAST so columns 1–11 stay identical; `sample-power.ps1`'s
`$script:QUERY` still carries eleven fields and **must gain the same one in the
same last position**. `scripts/bench/refarm.py`, `power-cap-arms.py` and
`scripts/verify/energy-four-sets.py` already collect it.

Adding it to one logger alone was once ruled out here on the grounds that it
would end the column match. That was wrong, and the reason is measured: the
integrator re-picks the power column per file by header name, so an
eleven-column log and a twelve-column log integrate to the same numbers and
merge in one invocation — checked 2026-08-30 on 201 rows of `rule21-power.csv`
cut both ways, **13,858.7 J** over the same 40 s window from the eleven-column
file, the twelve-column file, and the two together. **The two loggers differing
by one column is therefore a debt, not a design.** Until the `.ps1` edit lands,
a Windows `campaign-power.csv` cannot support a throttle-reason attribution, and
a J/token taken from one carries that limit with it.

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

**The remedy it prints names the PowerShell starter on every platform.** The
`power log : NONE` block in `arms.py` prints
`pwsh scripts/power/sample-power.ps1 -Start -Csv results/<slug>/data/power/campaign-power.csv`
whatever the operating system is, so on Ubuntu the one place the runner tells an
operator how to fix a missing power log names a file that will not run there.
Run this instead, then re-run the sweep:

```bash
bash scripts/power/sample-power.sh start --csv results/<slug>/data/power/campaign-power.csv
```

### On Linux `nvidia-smi -f` buffers, so the POSIX logger redirects stdout

`sample-power.ps1` prefers `-f <csv>`, because that puts the destination inside
`nvidia-smi`'s own command line where `-Stop` can read it back, and falls back
to stdout redirection when `-f` misbehaves. `sample-power.sh` inverts that
order, and the inversion is measured, not assumed. On 2026-08-30 (RTX 3090,
driver 596.36, WSL2 Ubuntu 24.04) a `-f` logger showed **0 rows after 6 s** and
dumped all **13** at exit, while `stdbuf -oL nvidia-smi … > csv` showed **7
rows after 3 s** and **13 after 6 s**. A file that materialises only at exit is
not a log: `attribute-power.py` cannot integrate a window that has not been
written, and `arms.py`'s freshness check reads exactly that file's last row and
its mtime, so a buffered logger reads as no logger at all.

So the POSIX starter redirects a line-buffered stdout first, keeps `-f` as a
fallback, proves either mode by watching the file GROW before it reports
success, and recovers the destination from `/proc/<pid>/fd/1` when the command
line does not carry it, which in redirect mode it never does. The measurement is
recorded in the script's own header, and the symptom is filed in
`reference/platform-notes.md` under "the power CSV exists but is empty while the
logger is running".

### How `stop` decides what to kill (the safety contract)

`-Stop` **never** kills by process name. A logger is addressed by **the CSV it
writes**, resolved two ways, both verified over WMI/CIM:

1. the path is in `nvidia-smi`'s own command line, because `-Start` launches it
   with `-f <csv>`;
2. the sidecar `<csv>.logger.json` that `-Start` drops next to the CSV records
   the pid — re-checked at stop time to still be an `nvidia-smi` query loop.

**Route 2 verifies the wrong property, and this is a live defect in
`sample-power.ps1`.** The re-check asks *is this pid a telemetry loop*, never
*is it writing this CSV* (`sample-power.ps1:139-153`), so a pid that ended and
was recycled onto a **different** `nvidia-smi` query loop is reachable through a
stale sidecar. That is not a hypothetical: the identical route in the POSIX
script was reproduced on 2026-08-30 killing the logger of a different CSV — a
stale `…/a.csv.logger.json` naming the live pid of the loop writing `…/b.csv`
made `stop --csv …/a.csv` end `b.csv`'s logger and report success — and the
POSIX script **dropped route 2 entirely** in response. Windows cannot make the
same repair for free: nothing outside a Windows process can read where its
stdout went, so for a `-Start` that fell back to redirection the sidecar is the
only handle there is, and dropping it would leave the script unable to stop a
logger it started. Until that is decided, treat a `-Stop -Csv` on Windows as
addressing *the pid the sidecar names* and not only *the CSV*, and delete a
sidecar whose logger you ended by hand.

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

**On POSIX the contract is narrower in one place and wider in another, and
both changes are in the operator's favour.** `stop` still needs an explicit
target (`--csv <path>` or `--pid <n>`), never a process name, and still verifies
over `/proc` that the target really is an `nvidia-smi` query loop (comm is
`nvidia-smi`, `--query-gpu` in argv, a loop flag in argv) before it signals
anything.

*Narrower:* **`sample-power.sh` has no route 2.** Selection is by path only —
the `-f` argument read out of argv, then `/proc/<pid>/fd/1` — taken from the
kernel at the instant of asking, so nothing `stop` acts on rests on a file
written earlier. The sidecar is still written, and when `stop --csv`
finds nothing it is **reported** rather than acted on: the script prints what
the record says and what that pid is *now* (already ended, recycled onto
something else, a live loop writing a different file, or unreadable at this
euid), together with the exact `stop --pid <n>` that would act on it. It is
never a target.

*Wider:* nothing outside a Windows process knows where its stdout went, but on
Linux the kernel does, so `stop --csv foo.csv` **will** find and end a
hand-started `nvidia-smi … > foo.csv`. Tested on 2026-08-30; it did. That is
the same fact that lets `start` refuse a second logger on a CSV a hand-started
one already holds, which the Windows script cannot do. `stop` sends SIGTERM and
then SIGKILL after 2 s; TERM was enough on this box, the sampler was gone inside
200 ms.

The `-f` argument is read **before** `/proc/<pid>/fd/1`, because a `-f`
logger's stdout goes to `/dev/null`: reading fd/1 first answers a true question
about the process and a false one about the log. That ordering was a defect
found by running `list` against a `-f` logger and reading `writes: /dev/null`,
not by review.

---

## 4. Elevation — what root buys, what it costs, what records it

**Running the campaign from an elevated shell is a supported operating mode.**
An agent launched from an Administrator `cmd.exe`, or under a root account on
Ubuntu that can already `sudo`, does the whole campaign with nobody at the
keyboard, and some power registers read no other way. It is a deliberate
choice, and this repository records it as a condition of the run rather than
objecting to it. Nothing here refuses to run elevated and nothing warns about
it; what follows is what changes.

**What elevation buys.**

* **The power cap becomes measurable, and it is the only axis that lowers the
  draw.** `nvidia-smi -pl <W>` (3090 stock **350 W**; Linux may need `-pm 1`
  first) needs root, and `power-cap-arms.py` is the arm that turns it. On the
  reference machine that register entry sat open for the whole campaign for a
  privilege and not a hardware limit. Closing it on 2026-08-25 produced the
  exception to the energy chapter's own negative finding — 350 / 300 / 250 W
  read **75.61 / 71.82 / 65.90 t/s** at **305.4 / 271.2 / 229.6 W**, so
  J/decode-token fell **4.033 → 3.771 → 3.479**, which is **-6.5%** and **-13.7%** against stock while throughput gave up about half of what
  the power did each time. The stock arm never reaches its own cap (305.4 W
  mean against a 350 W limit), which is why the first 50 W of capping costs
  almost nothing.
* **Other tiers.** Intel RAPL package energy and Apple `powermetrics` read only
  as root — `reference/platform-notes.md`, "Energy counters by platform". NVML
  board power is not one of these; see below.
* **The bootstrap runs itself.** On Linux the `sudo apt-get install` step ahead
  of `scripts/setup.sh --cuda` is the one thing an unelevated agent cannot do,
  and it is what turns an autonomous campaign into a stop-and-wait. `PROMPTS.md`
  carries both paths.

**What elevation costs, and it is one named field.**
`scripts/detect-machine.py`'s `pl_write_test()` asks whether the power limit is
writable **without** elevation, by setting it to the value already in force, so
a success changes nothing and a failure changes nothing. It declines to run in
**three** cases and says which. First, before elevation is consulted at all:
a card with no readable `power.limit` has nothing to set, so there is nothing
to test. Then the two elevation cases. Under an elevated shell: a set that succeeds
because the shell was privileged says nothing about the unelevated case. And
when elevation itself could not be determined — the field is named for a
condition, so a process that cannot say whether it was elevated cannot fill it,
and nothing is set. `machine.json` therefore records
`pl_writable_without_elevation: null` with the reason attached, and
**an all-elevated campaign never learns the answer.** Rule 28 is unforgiving
here — a question not asked during the run cannot be asked afterwards at any
price. If the answer matters, and it is what tells a reader on the same card
whether they can run the cap arms without root, run
`python scripts/detect-machine.py` once as an ordinary user.

**What elevation does NOT change: the watts.** Reading board power needs no
privilege at all. The same `nvidia-smi --query-gpu=power.draw … -lms 500`
samples identically at euid 1000 and at euid 0, so a log started unelevated and
a log started under `sudo` are the same measurement of the same board. What
elevation changes is **visibility**, and the script says which of the two it
is hitting. `/proc/<pid>/fd` is readable by the process owner and root only, so
an unelevated `list` sees another user's `nvidia-smi` loop but not the file it
writes; it prints that this one is another user's and names elevation as the
reason, and the "rerun under `sudo`" footer fires only when such a loop actually
exists. An fd 1 that reads back as `/dev/null`, as an unlinked path, or as a
pipe is a different answer with the same empty destination, and each gets its
own line — elevation would change none of them. Measured 2026-08-30 against a
root-owned logger started in an elevated WSL shell: **unelevated `stop --csv`
finds nothing and exits 5** (it cannot read that fd, so it cannot claim the
path), unelevated `stop --pid <n>` finds the loop and fails on EPERM with the
`sudo` hint and exit 3, and elevated `stop --csv` resolves it by path and ends
it. Files an elevated logger leaves behind — the CSV and the stderr log — are
owned by root, so the next unelevated `start` on that path is refused with that
reason.

**It is recorded on every line, because it is a condition (rules 3 and 28).**

| where | fields |
|---|---|
| `<csv>.logger.json`, written by `sample-power.sh` at start | `euid`, `elevated`, and `enforced_power_limit_w` — the cap in force when the log began — beside `gpu_name`, `driver_version`, `gpu_index` and `stderr_log` |
| every probe line, and the `sweep_start` header, through `provenance.py`'s `execution` block | `elevated`, `sudo_nopasswd`, `privilege_path`, each with its `MEASURED` / `DERIVED` / `UNKNOWN` label in `execution.how` |
| `machine.json` | the same three, beside `pl_writable_without_elevation` |

`elevated` is literally `true`, `false` or `null`, and never a string: a
non-empty "could not tell" is truthy, so `if row["elevated"]` downstream would
read *could not tell* as *was elevated*, which is the direction that invents a
privilege the run did not have. **`null` means unrecorded, never unelevated.**
`sudo_nopasswd` is `sudo -n true` — it never prompts, and `true` sets nothing —
answered `null` when the process is already root, because a success there says
nothing about the unelevated case either, and `null` again on Windows, where the
`how` reads `UNKNOWN: not applicable …` because sudoers has no Windows
equivalent. **It is probed once per interpreter, not once per arm.** A `sudo`
invocation is an authentication event on the box being measured, and an uncached
probe wrote one `authpriv` record per arm launch: measured 2026-08-30 on WSL2
Ubuntu 24.04, sudo 1.9.15p5 — three calls, three records; one after the fix.
Rule 27. Its `how` carries the local time that one probe ran, so a later arm's
row says **when** its answer was taken rather than reading as freshly measured.

`privilege_path` is the labelled DERIVED join of the two — `"direct"`,
`"sudo -n"` or `null`, and a **string** where the other two are tristate
booleans. It is the field to read before attempting `nvidia-smi -pl`, and its
`null` does not mean one thing. `execution.how` says which: *no route was found
**here***, the one reading where an absence was actually measured — and not the
same as no route existing, since polkit, file capabilities and device
permissions go untested — or *the question could not be fully asked*, when
elevation was undetermined, or the `sudo -n` probe returned no answer, or both.
Four branches, four sentences. **The block never reports an unasked question as
an absence**; until 2026-08-30 it did, publishing "no passwordless sudo route
was found" on a platform where nothing had looked.

**How to read two rows whose elevation differs.** They are not thereby
incomparable — the watts do not move with the shell. What is not comparable is
an arm taken at one enforced power limit set beside an arm taken at another,
and only an elevated run can have changed that limit. So read the pair
together: `enforced_power_limit_w` and the row's own `power_limit_w` are the
difference, and `elevated` is the explanation of how two rows came to sit at
different caps. **A power-cap arm from an elevated sweep standing beside a
stock arm from an unelevated one is a condition difference, and rule 3 puts the
burden on the destination**, which is the place that quotes the number rather
than the place that measured it. Rows written before 2026-08-30 carry no
elevation field at all and cannot be given one — see
`reference/ledger-notes.md`.

---

## 5. `capture-request.ps1` — the join point

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

## 6. `attribute-power.py`

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

## 7. Worked example

Assume the logger has been running since the campaign started.

**On POSIX there is no step 2 to run, and the arms ledger is not a drop-in for
one.** `capture-request.ps1` has no POSIX twin and nothing in `scripts/`
replaces it. `arms.py`'s per-probe ledger is the closest thing there is, and it
needs one conversion before `--events` will read it. Measured 2026-08-30,
against a ledger built to `arms.py`'s own record shapes and this repo's
`rule21-power.csv`:

* pointed straight at the ledger, `attribute-power.py` **dies** with
  `KeyError: 't_start_iso'` at `attribute-power.py:328` — it subscripts that key
  directly, and the `sweep_start`, `load`, `sweep_end` and `error` lines do not
  carry it;
* with the non-probe lines filtered out it **runs and reports nothing**: `n` 0,
  `J_gross` 0.0, every column `n/a`, and the warning *"event without timings and
  without t_end_iso skipped"* on every label. The integrator reads `prompt_ms`,
  `predicted_ms`, `prompt_n` and `predicted_n` **flat** (`:329-330`, `:367-368`);
  `arms.py` writes all four nested under `timings`, and no flat copies exist.

So flatten the probe lines first. This is the whole conversion, and it is what
produced the figures below:

```bash
# 1. logger already up; confirm and note the file
bash scripts/power/sample-power.sh list

# 2. no capture step: turn the sweep's own ledger into an events file
LEDGER=results/<slug>/data/arms/<stem>.jsonl
EVENTS=results/<slug>/data/power/events-from-arms.jsonl
python3 - "$LEDGER" "$EVENTS" <<'PY'
import json, sys
src, dst = sys.argv[1], sys.argv[2]
n = 0
with open(src) as fin, open(dst, "w") as fout:
    for line in fin:
        r = json.loads(line)
        # sweep_start / load / sweep_end / error carry no t_start_iso, and
        # attribute-power.py subscripts it rather than .get()-ing it.
        if r.get("kind") != "probe" or not r.get("t_start_iso"):
            continue
        t = r.get("timings") or {}
        fout.write(json.dumps({
            "t_start_iso":  r["t_start_iso"],
            "label":        r.get("label"),
            "prompt_n":     t.get("prompt_n"),
            "predicted_n":  t.get("predicted_n"),
            "prompt_ms":    t.get("prompt_ms"),
            "predicted_ms": t.get("predicted_ms"),
        }) + "\n")
        n += 1
print("%d probe line(s) -> %s" % (n, dst))
PY
```

Two things it does not do, and both are conditions of the number it produces.
It keeps every probe including the ones `arms.py` marked `discarded` (rule 12's
first post-prefill probe), so drop those yourself or use `--drop-first` below.
And `label` is `<arm>/<probe>`, so each arm/probe pair is its own row rather
than one row per arm; `--drop-first` then drops the first **repeat** of each
pair, not the first probe of each arm.

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
# 4. attribute  (on POSIX, --events "$EVENTS" from step 2)
python attribute-power.py \
  --power results/<slug>/data/power/campaign-power.csv \
  --events results/<slug>/data/power/events.jsonl \
  --idle-w 31.0 --drop-first --json results/<slug>/data/power/arms.json
```

**The converter closes the gap, and the number is the check.** Against
`results/qwen38-27b-blind/data/power/rule21-power.csv` and a two-probe
arms-shaped ledger on 2026-08-30, the same integrator call that reported `n` 0
and `J_gross` 0.0 on the raw ledger reported **21,650.8 J** and **20,578.9 J**
for the two probes once the lines had been flattened — 100.0% coverage, a 4.2 s
prefill against a 60.0 s decode, 29.049 J per decode token. This converter
belongs in `scripts/` and not in a README; there is no such script yet, and that
is recorded beside the missing `capture-request` twin rather than left implied.

Output shape, from a separate run over that same log with more requests per
label (synthetic request events, so no GPU work was disturbed):

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

## 8. What this is for — the mechanisms worth measuring

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

**The one knob that needs an elevated shell: the GPU power cap — and
`power-cap-arms.py` is the arm that turns it.** `nvidia-smi -pl <W>` (3090
stock **350 W**; Linux may need `-pm 1` first) is the classic efficiency lever,
and it is the only setting on this page that lowers the board's draw rather
than shortening the time it is drawn: measured at 350 / 300 / 250 W it cost
5.0% and 12.8% of throughput and bought 6.5% and 13.7% of J/decode-token
(2026-08-25 — section 4 carries the arms, the mechanism and what the three
probes do not establish). The cap is a **persistent hardware setting** that
outlives the process, so the script reads the default before it changes
anything, restores it in a `finally`, and verifies the restore by reading the
value back rather than trusting an exit code. A campaign that cannot elevate
does **not** estimate this row: print the command, state the stock cap, and
mark it *"unmeasured on this machine (requires administrator)"*.
