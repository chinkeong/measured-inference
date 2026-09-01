---
name: failure-library
description: Diagnosed failures with their measured signatures — grep the SYMPTOM lines for the exact string you are seeing (a speed, an error text, a counter reading) before blaming hardware or the model. Do not read whole.
---

# Failure library — grep by symptom

One entry per failure: **SYMPTOM** (the grep-able strings) → **CAUSE** → **FIX**
→ **EARNED BY** (the campaign incident that paid for it). Diagnose from here
before blaming hardware, the quant, or the model. Platform traps and
diagnostic commands live in `platform-notes.md`.

---

## Silent VRAM spill (sysmem fallback)

**SYMPTOM** — `20-35 t/s` flat at *every* context size · dedicated GPU memory
pinned at `23.5-24.0 / 24.0` · **shared GPU memory growing** during the run ·
CPU ~70% · the server loaded with **no warning at all** · shrinking `-c` does
not help.

**CAUSE** — the NVIDIA driver does not refuse an over-VRAM allocation; by
default it quietly overflows into shared system memory across PCIe. Weights
stay spilled regardless of window size, which is why shrinking the context
changes nothing. On the reference machine two open browsers held ~2-3 GB of
VRAM and about 1.9 GB of a 122,880-context config spilled.

**FIX** — free the VRAM (close the apps holding it). **Prevention**: NVIDIA
Control Panel → Manage 3D Settings → Program Settings → llama-server.exe →
CUDA — Sysmem Fallback Policy → **Prefer No Sysmem Fallback**, which turns an
over-budget load into a startup out-of-memory error instead of a slow day.
Detection commands: `platform-notes.md`, Windows section.

**EARNED BY** — reference campaign 2026-08-22; documented as example-report §10
Failure 1. It is METHODOLOGY rule 14's reason for existing.

---

## The -ngl off-by-one

**SYMPTOM** — decode `25.7` vs `39.7 t/s`, **fixed, at every window** ·
prefill `106` vs `290 t/s` · GPU utilization `53-67%` instead of ~90% · a stack
of CPU threads pinned · **shared GPU memory stays flat** · **survives a
reboot** (it lives in your command line, not in the machine's state).

**CAUSE** — llama.cpp counts the output projection as layer n+1. A 64-layer
model with `-ngl 64` reads as complete and leaves the output layer — a
5120 × ~151k-vocab matmul that runs for every generated token — on the CPU.

**FIX** — always `-ngl 99`. Any number past the real count means "everything",
with no off-by-one to get wrong. **Note**: `probe-config.ps1` defaults to
`-ngl 64` and relies on callers passing `-ngl 99` (its header warns);
`scripts/probe-config.sh` defaults correctly. Cross-check any floor probe
against rule 10's arithmetic (GB/s ÷ file GB × 0.7).

**RED HERRING** — the log line `failed to fit params to free device memory:
n_gpu_layers already set by user` only means an explicit `-ngl` overrode the
automatic fit. **Any** value triggers it, `-ngl 99` included. It is not the
symptom.

**EARNED BY** — reference campaign; worth ~35% of decode speed. METHODOLOGY
rule 15.

---

## High CPU alone (the non-failure)

**SYMPTOM** — 50-70% CPU during decode on a 20-thread machine.

**CAUSE** — llama.cpp worker threads busy-spin while waiting on the GPU. This
is **normal** during perfectly healthy all-GPU decode.

**FIX** — none needed. The trouble signal is the *combination*: high CPU **and**
low t/s. Both failures above show both.

**EARNED BY** — reference campaign debugging session; example-report §10.

---

## The clock-ramp low probe

**SYMPTOM** — a probe fired right after a long prefill reads **up to 45% low** ·
scatter like `18-26 t/s` where the settled number is much higher · SM clock
`900-990 MHz` in the log against `1455 MHz` settled · prefill itself reaching
only ~65% of settled clocks · the *first* request of an arm looks
suspiciously **efficient** in J/token.

**CAUSE** — the board's clocks are still ramping. Steady-state temperature moves
decode only ~1%; ramping moves it enormously. In energy work the same artifact
runs both ways: an unrepresentative wattage over an unrepresentative duration
can make J/token come out *better* than steady state.

**FIX** — **discard the first post-prefill probe at every rung** and time only
settled probes (rule 12); for energy, discard the first post-idle request and
say which samples were dropped (rule 24), or warm up first
(`capture-request.ps1 -Warmup`, `attribute-power.py --drop-first`). Keep
`clocks.current.sm`, `pstate` and `utilization.gpu` in the power log for exactly
this: they prove a low sample was a ramping board and not an efficient one.
Short probes understate sustained load the same way — 10 s recipe probes read
277-287 W where multi-minute runs sustained 344 W.

**EARNED BY** — reference campaign; METHODOLOGY rules 12 and 24.

---

## The drafter's VRAM bill (the "no VRAM cost" error)

**SYMPTOM** — a window labeled **"fully resident"** collapsing to `8 t/s` at
deep fill (measured: 8.0 t/s at 91k fill) · a ceiling that reproduced on one
machine failing on the same machine with speculation enabled · a config that
"fits" by arithmetic but spills in practice.

**CAUSE** — the drafter carries a real VRAM cost that a drafter-off ceiling
sweep never sees: reference measurement **1,008 MiB fixed + 5,120 B per window
token + 898 MiB more at n-max 10 vs 4**. "The drafter has no VRAM cost" was
published in the reference guide and was **wrong** — a blind, framework-free
reproduction caught it in one night after multiple framework-holding review
passes had missed it.

**FIX** — measure the drafter as an **on/off VRAM pair** before any ceiling
sweep, and scope every ceiling to ⟨file + drafter on/off + projector on/off +
desktop state⟩. **No window is labeled resident or safe without at least one
deep-fill probe near its top** — a shallow probe on an overcommitted window
reads fast right up until deep pages are touched.

**EARNED BY** — the blind reproduction, reference campaign. METHODOLOGY rule 13.
This is also the project's standing example of REASONING's projection check:
your framework is your largest blind spot precisely because it is what you see
with.

---

## Client-side max_tokens cut-off

**SYMPTOM** — an **empty answer with the thinking complete** · a generation that
stops mid-sentence · vision requests returning nothing after a visibly long
think · a truncated answer that cannot be resumed.

**CAUSE** — cut-offs are client-side. The server generates until told to stop;
truncation comes from the client's `max_tokens`, its request timeout, or Ctrl+C.
With OpenAI-compatible APIs a cut generation cannot seamlessly resume. Prompt +
thinking + output share **one token pool** ≤ context; the model has no awareness
of its limits and cannot budget its own thinking.

**FIX** — size `max_tokens` and the client timeout so the whole run fits one
response. Some clients enforce this client-side and need it set explicitly:
**Pi and the DeepSeek Harness both require a client-side `maxTokens`** or long
replies truncate. Vision is not exempt — a thinking model reasons about the
image before answering.

**EARNED BY** — reference campaign; example-report §03 and §11.

---

## Benchmark budget truncation

**SYMPTOM** — an arm scoring 0 on items that should pass · a truncation count
above zero in a scored run · an effort arm producing **zero deliverable** after
burning wall time and watts.

**CAUSE** — a cap set near the appetite *median* rather than above its upper
tail is a truncation machine. The reference case: the xhigh effort arm ran
**21 minutes and ~120 Wh inside a 65,536-token window**, and the campaign
*afterwards* measured xhigh's thinking appetite at **61-76k tokens**. The arm
truncated; the deliverable was zero.

**FIX** — set caps at Stage 5, from Stage 4's measured appetite distribution,
and size the serving `-c` above longest-prompt + cap so truncation is impossible
by construction. If an arm truncates anyway the **lock was wrong**: raise the
cap and **rerun that arm only** (greedy determinism makes the others
byte-identical). **Never filter to non-truncating questions** — that selects the
test set on one arm's behavior and drops exactly the hard items.

**EARNED BY** — reference campaign 2026-08-22; the dated case study in
METHODOLOGY rule 25, and the reason Stage 5 exists as a gate. Rules 7 and 21.

---

## Hours spent to publish one word (no early pruning)

**SYMPTOM** — a candidate file carried through full perplexity, full accuracy
and full sweeps to earn a one-word verdict like "pointless".

**CAUSE** — no cheap screen before expensive treatment. The reference campaign
took UD-Q4_K_XL through the full treatment to conclude exactly that.

**FIX** — the Stage-1 pruning gate: throughput probe + file size + a short PPL
screen over identical chunks. **Drop any file that is both slower AND worse**,
record the drop with both numbers and the words "screened out at the Stage-1
gate", and publish it as screened out — never as untested. A file that is slower
but better, or faster but worse, is a real trade-off and survives.

**EARNED BY** — reference campaign; METHODOLOGY rule 25's prune-before-you-treat
clause.

---

## Greedy repetition loop

**SYMPTOM** — implausibly high t/s on a long generation · a token count far
above the level's usual appetite · visibly repeating text in a thinking trace or
transcript · an appetite measurement that would push every downstream window up.

**CAUSE** — degenerate repetition. **Greedy decoding makes the loop
deterministic, not rare**, and a looping transcript inflates both t/s and token
counts with garbage.

**FIX** — **spot-read** any long greedy generation before its tokens or timings
feed a claim. This applies twice: to Stage 4's appetite probes (a looping trace
inflates appetite, which then inflates every window Stage 5 sizes) and to Stage
6a's long transcripts.

**EARNED BY** — METHODOLOGY rule 20's greedy repetition check.

---

## Agents that silently drop images

**SYMPTOM** — an agent answers a vision question **honestly** ("I cannot see an
image") — or worse, **confidently describes content that is not there** · the
PNG is read as raw bytes · env-var-only setups appear to work but never carry
the image.

**CAUSE** — capability must be *declared*, not merely configured. Known gates:
OpenCode needs `"attachment": true` **and** `"modalities": {"input":
["text","image"]}` on the model (a bare model entry reads the PNG as bytes —
verified v1.18.21, issue #15728); Qwen Code needs the model in `settings.json`
`modelProviders` with `capabilities: {vision: true}` (env-vars-only silently
drops images); aider needs `supports_vision: true` in
`.aider.model.metadata.json`; Pi's provider `models.json` must list `"image"` in
`input`; the DeepSeek Harness needs `input: [text, image]` in **both** the
provider block and the `agent-default-model` routing block (else
`MISSING_CREDENTIAL`).

**FIX** — test every agent with a question **only answerable by seeing the
image**, and record verdicts as PASS / FAIL-honest / **FAIL-hallucinated** (flag
hallucination loudly — it is the worst outcome). Agent CLIs drift: if a command
errors, verify flags against the installed version's `--help` and document the
delta. **Never publish a FAIL produced by an invocation you invented.**

**EARNED BY** — reference campaign agent-attach matrix, 2026-08-22. METHODOLOGY
rule 19.

---

## PowerShell 5.1: `Write-Output` pollutes a function's return value

**SYMPTOM** — a function returns an array where a scalar was expected · log text
appearing inside a captured result · a numeric parse failing on a value that
"looks right" in the console.

**CAUSE** — in PowerShell every uncaptured expression inside a function is
emitted into the pipeline, so `Write-Output` used for logging becomes part of
the return value.

**FIX** — use `Write-Host` for logs inside functions; reserve `Write-Output` (or
a bare expression) for the single value the function returns.

**EARNED BY** — reference campaign standing rule; carried since the first
PowerShell sweep scripts.

---

## PowerShell 5.1: the `$base` / `lib.ps1` variable collision

**SYMPTOM** — a run **wedges** with no error · a health poll that never returns
· requests to a nonsense URL such as `-c 131072 ... /health` · the failure
hidden inside a `try {} catch {}`.

**CAUSE** — PowerShell variable names are **case-insensitive**, so a local
`$base` silently overwrites `lib.ps1`'s `$script:BASE` (the server URL), and
`Start-Srv`'s health poll then polls forever.

**FIX** — **never name a variable `$base` in a script that dot-sources
`lib.ps1`.** More generally, do not shadow a dot-sourced script scope's
variables; the case-insensitivity makes the collision invisible.
`results/qwen38-27b-blind/work/followup-m2e.ps1` and `followup-m2f.ps1` carry
the warning in their headers.

**EARNED BY** — reference campaign follow-up batch; cost one wedged 10-minute
run.

---

## PowerShell 5.1: large-image POST never leaves the client

**SYMPTOM** — a vision request returns **nothing** and the **server log shows no
task at all** · no useful error is thrown · the identical request from Python
succeeds (measured: 3.8 s).

**CAUSE** — Windows PowerShell 5.1's `Invoke-RestMethod` cannot post the
~261 KB body a 1440p PNG data-URI produces. The request never reaches the
server.

**FIX** — send image requests from **Python**. The reference vision phase was
rewritten as `results/qwen38-27b-blind/work/phase8b.py` for exactly this. This
is published as a troubleshooting entry because it looks like a model problem
and is not.

**EARNED BY** — reference campaign 2026-08-22, Phase 8 first attempt.

---

## PowerShell 5.1: the power integrator's `TryParseExact`

**SYMPTOM** — the PowerShell power-integration script fails on timestamp
parsing; `[datetime]::TryParseExact` overload resolution errors.

**CAUSE** — 5.1 cannot resolve the `TryParseExact` overload the integrator
needs.

**FIX** — **use the Python integrator**: `scripts/power/attribute-power.py`, or
the campaign's `results/qwen38-27b-blind/work/power-integrate.py`. A
`power-integrate.ps1` exists beside it and is the one that tripped.

**EARNED BY** — reference campaign; recorded in `campaign.md` as one of two
measurement steps moved from PowerShell to Python.

---

## Agentic bucket (rule 22) — three paid-for failures

**SYMPTOM** — `litellm.ContextWindowExceededError: request (65577 tokens)
exceeds the available context size (65536 tokens)`.
**CAUSE** — mini-swe-agent does **no summarization**, so history grows
monotonically; the reference validation run overflowed 65,536 after just 22
calls. **FIX** — serve with `-c 131072` minimum and check the bigger KV still
fits VRAM. **EARNED BY** — `agentic/setup-log.md`, validate-01.

**SYMPTOM** — requests hitting `/v1/responses`, which llama.cpp does not
implement.
**CAUSE** — mini-swe-agent silently routes any `openai/...` model name to the
OpenAI **Responses** API. **FIX** — pass `--ak model_class=null` (documented CLI
behaviour, no patching). Also ensure `--alias` matches the model name LiteLLM
sends after stripping the `openai/` prefix. **EARNED BY** —
`agentic/setup-log.md`, Stage 3.

**SYMPTOM** — `TCP_DENIED/403` in the squid access log; the agent container
cannot reach the model on port 1235.
**CAUSE** — Pier's squid sidecar `Safe_ports` ACL allows destination ports 80
and 443 only, and this is not configurable through Pier. **FIX** — serve on
**port 80**. **EARNED BY** — `agentic/setup-log.md`, Stage 4 (measured
standalone before spending a multi-GB image pull). See also
`platform-notes.md`, WSL2.

---

## Where the measured signatures are published

The example report's §10 documents the spill, the -ngl off-by-one and the
busy-spin non-failure with their full measured signatures and a distinguishing
table. Any campaign that meets a new failure adds it **here**, symptom first —
not to `AGENTS.md`.

## Get-Content -Tail hangs for minutes on a single-huge-line file

SYMPTOM: `Get-Content -Tail N` on a file that is one enormous line (e.g.
`llama-tokenize --ids` output, ~1.7 MB on one line) spins for minutes at
high CPU with no output.
CAUSE: -Tail walks the file backwards character by character looking for
line breaks; a file with none makes it scan nearly the whole file in the
slowest possible way.
FIX: seek-read the tail directly - open a FileStream, `Seek(-4096,
[IO.SeekOrigin]::End)`, read the block (measured: 47 ms vs minutes).
EARNED BY: the quant-ladder build (2026-08-23), parsing tokenizer output
for the cross-model bits-per-byte rows.

## tail -f from Git Bash silently blocks and drops PowerShell Add-Content lines

SYMPTOM: a runner writes ledger lines with Add-Content; some lines never
appear in the file, with no error anywhere - the runner believes it wrote
them. Meanwhile someone is watching the file with Git Bash `tail -f`.
CAUSE: Git Bash tail opens Windows files without FILE_SHARE_WRITE, so the
writer is intermittently denied the handle; PowerShell Add-Content can
fail non-terminating and the line vanishes.
FIX: never tail a file the runner appends to (poll with a seek-read copy
instead); make ledger writers retry (~30 s) and spill to a side file
rather than drop; keep every result ALSO in the phase's own log so a
dropped ledger line is recoverable, not gone.
EARNED BY: quant-ladder rig gate (2026-08-23) - three ledger lines
(RESULT, RIGGATE, DETECT) swallowed; recovered from the runner log. The
class of failure this repo cares most about: a measurement that happened
but the report would never know about.

## Gemma-4-instruct models read absurd perplexity on llama-perplexity

SYMPTOM: llama-perplexity on any gemma-4 -it model returns PPL in the
hundreds-to-thousands (measured here: 12B-QAT 1,159.7; published:
E4B 52.7, E2B 144.5, 26B-A4B 6,617.8) while the same pipeline reads
sane values for other families and for gemma-3-it (9.04) and gemma-4
BASE models (7.1-8.3).
CAUSE: undiagnosed upstream (issue tracker has no maintainer answer;
stale-closed). Ecosystem-wide, instruct-tuning-correlated for this
family; NOT a local rig fault - a rig control on gemma-4-E2B matched
the published value within 8% across different hardware/precision.
FIX: withdraw the PPL/bits-per-byte row for this family with the
documented external cause; carry cross-model comparisons on scored
benchmarks (rule 21) instead. Always run a same-family published-value
control before blaming your rig (instrument-first, rule 20) - and note
llama-perplexity DEFAULTS to -c 512, so any published PPL without an
explicit -c is a 512-token run, not comparable to yours.
EARNED BY: the quant-ladder cross-model arm (2026-08-23); the agent
also retracted its own SWA hypothesis when the evidence did not
support it (published blowups occur where the sliding window never
binds).

## GPU idle for hours while pipeline work is pending - the silent stall

SYMPTOM: nvidia-smi shows ~1% util / near-empty VRAM while the campaign
still has queued arms; the runner heartbeat file mtime is hours old; no
agent or task notification fired; the last ledger line is a completed
item, not an error.
CAUSE: layered liveness failure - the detached runner died (often at a
state transition, e.g. the moment new input files arrived) AND the
monitor watching it died or was never re-armed, so the completion-based
notification chain had nothing to fire on. Silence from every layer
reads as "busy" unless something is checking.
FIX: rule 20 liveness protocol - runner heartbeat (<=2 min), an
independent watchdog with a stale threshold above the longest legitimate
quiet stretch, and a session-level fallback wake (~30 min) that checks
the watchers themselves. Recovery is cheap when runners are resumable:
diagnose the death from the runner log tail, restart, it skips completed
work. Treat idle-GPU-with-pending-work as an alarm, never a rest.
EARNED BY: the quant-ladder stall (2026-08-23 21:14 - 00:45) - two GPU
hours lost, caught only by the user asking for status.

## Runner exits cleanly at its wall while gate-blocked behind another GPU job

SYMPTOM: the run-ladder/runner log ends with "GPU gate never opened
before the deadline ... DONE" - no error, no crash; hours earlier the
gate line names another llama process; meanwhile the pending work count
never moved.
CAUSE: priority inversion - a secondary job (often an AUTOMATIC rule-7
cap-raise rerun, unbounded by design) held the single-file GPU ahead of
the deadline-bound primary. Every safety mechanism worked; the schedule
was wrong. The exit is clean, so completion-based notifications read it
as success.
FIX: primaries before unbounded secondaries; secondary escalations are
deliberate priced decisions (rule 25); a deadline runner that exits with
pending work must say so LOUDLY in its last line and its watchdog must
treat pending>0 at exit as an alarm, not a completion.
EARNED BY: the quant-ladder deadline exit (2026-08-23 22:08) behind the
gemma decisive-arm rerun - 2.5 h of invisible idle followed.

## A .pid file names a process that is no longer that process

SYMPTOM: you kill the PID in a runner's .pid file, verify with
`Get-Process -Id <pid>` that it is gone, and report the job stopped - but
the job keeps writing to its log, keeps holding its gate, and every
downstream waiter stays blocked. The "verification" passed because
nothing with that PID was running: the PID was stale, and the check
you ran cannot tell "I killed it" from "it was never there".
CAUSE: the .pid file was written by an EARLIER invocation of the same
script (check its mtime against the run you care about - hours apart is
the tell). PIDs are also reused by the OS, so a stale PID can name an
unrelated live process; killing it is worse than a no-op.
FIX: never resolve a runner by .pid alone. Resolve it by COMMAND LINE:
`Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
Select ProcessId, CreationDate, CommandLine` and match both the script
path and a CreationDate consistent with the log line that started it.
Then verify the kill by the EFFECT you wanted - the chain log advancing,
the gate opening - never by the absence of a PID. Absence of a PID is
absence of evidence.
EARNED BY: the ladder poller (2026-08-24). run-ladder.ps1 finished its
last rung at 12:35 and sat in an empty poll loop. The session killed
`runner.pid` = 9984, written at 00:46 by a PREVIOUS run, confirmed
"runner alive: 0", and ended the turn believing the chain was released.
The live poller was PID 32148, started 11:20:35 - matching the chain log
exactly. THREE HOURS of idle GPU followed, with a rule-7 rerun queued
behind a gate that could not open. The watchdog caught it; the
self-verification did not, because it verified the wrong proposition.

## Raising the cap reproduces the truncation exactly

SYMPTOM: an arm truncates, you apply the rule-7 remedy and rerun at double
the cap, and the rerun returns the SAME score, the same per-benchmark
cells and the same truncation count - at roughly double the wall clock.
Or, on a single item: empty at 16,384 and empty again at 32,768.
CAUSE: the truncation was never a budget shortfall. It is a
NON-TERMINATING generation - the model enters a state it does not leave,
and the cap is only what eventually stops it. The signature is a
completion whose content length is ZERO while the token count sits
exactly on the cap: the runaway is inside an unterminated thinking block,
so the harness stores an empty content field (llama-server with --jinja
splits thoughts into reasoning_content, and bench.py stores content).
FIX: the raise is a DIAGNOSTIC. One raise distinguishes the two causes;
a second raise is not licensed and only buys the same zero at more GPU
hours. Retire the provisional mark the first raise earned, keep the item
in the denominator (rule 7 forbids filtering it out), and report it as a
termination finding beside the score. To find the mechanism, spend
minutes not hours: rerun the offending prompt with --reasoning-format
none to make the raw thought stream visible, and again with --reasoning
off. If it terminates cleanly with thinking disabled, the runaway lives
in the thinking block and is a property of that model's default mode.
EARNED BY: three cases, two model families, 2026-08-23/24. gemma-4-12B-QAT
19 of 75 items - identical scores at 16,384 and 32,768, 5,365 s -> 9,552 s
to reproduce a number already in hand. Qwen UD-IQ2_XXS MBPP, 1 item.
Qwen UD-IQ4_XS at xhigh, ALPACA item 21 - empty at both caps, while all
24 sibling answers reproduced byte-identically.

## An arm scores badly and the truncation count says almost nothing is wrong

SYMPTOM: a scored arm's mean drops sharply against its reference, but the
truncation column reads 0 or 1. The per-item scores show zeros you
cannot account for by wrong answers.
CAUSE: EMPTY completions that terminated NORMALLY. The model spent its
budget inside the reasoning block, emitted its end-of-turn marker, and
returned zero characters of content. `finish_reason` is `stop`, not
`length`, so no cap was hit and no truncation counter incremented. The
harness stores `msg["content"]`, which is empty, and the scorer marks it
wrong - correctly - but silently.
FIX: count EMPTY ANSWERS as their own metric, separate from truncations,
and publish both. The check is one line over the saved transcripts -
`not str(it["response"]).strip()` - and it needs the transcripts, which
is the whole reason rule 20 makes read-back mandatory. Compare the same
item indices against a high-quality reference arm before blaming the
prompt: if the anchor answers them fine, it is the rung, not the item.
EARNED BY: the accuracy ladder, 2026-08-24. UD-IQ2_XXS (2.15 bpw) on the
frozen 3-benchmark suite: 3 empty answers of 75, of which only ONE was a
truncation. The other two stopped by themselves at 3,939 and 7,296 tokens
against a 16,384 cap. The same three items at the 4.2-bpw anchor all
scored 100.0 with 701 / 4,152 / 1,829 tokens of real content. The arm
reported "truncations=1"; the real failure count was three.

---

## Host OOM: the desktop hangs and the campaign dies with it

**SYMPTOM** - the whole machine stops responding, mouse included, and only the
power button ends it. Afterwards, in the Windows System log: `Kernel-Power 41`
with **`BugcheckCode = 0`** and **no dump** in `C:\Windows\MEMORY.DMP` or
`Minidump\`; `EventLog 6008` "the previous system shutdown ... was unexpected";
`Application Popup 26` **"Out of Virtual Memory"**; `Volsnap 25` shadow copies
deleted "because the shadow copy storage could not grow in time"; and a run of
`Resource-Exhaustion-Detector 2004` naming **more than one `llama-server.exe`**:

    llama-server.exe (41604) consumed 19,815,084,032 bytes
    llama-server.exe (37864) consumed 18,742,063,104 bytes
    llama-server.exe (41852) consumed 18,741,641,216 bytes

Read them with:

    Get-WinEvent -FilterHashtable @{LogName='System'; Id=41,2004,6008,26} -MaxEvents 40 |
        Select-Object TimeCreated,Id,Message | Format-List

**CAUSE** - two or more llama-servers resident at once. `BugcheckCode = 0` plus
no dump rules out a crash, a driver and hardware: this is pure commit
exhaustion, the host paging itself to death. Rule 20's "one GPU job at a time"
was prose only, and twenty scripts called `subprocess.Popen` on llama-server
independently - each correct alone, any two at once fatal. An agent that
backgrounds a probe and starts another, or a detached run whose parent dies and
leaves an 18 GB orphan for the next run to start on top of, gets there without
anyone doing anything obviously wrong.

**FIX** - never launch a server with a bare `subprocess.Popen` or
`Start-Process`. Use `scripts/bench/gpu_lock.py`'s `serve()` (Python) or
`scripts/gpu-lock.ps1`'s `Start-GuardedServer` (PowerShell). They share one
lockfile, so the second job fails in a second with a message naming the first;
they cap the child's commit; and they put it in a job object that kills it when
its parent dies, so orphans cannot accumulate. To inspect or clear:

    python scripts/bench/gpu_lock.py status     # holder, live servers, commit
    python scripts/bench/gpu_lock.py kill       # kill servers, clear the lock

If a legitimate arm genuinely needs more than the cap, raise it with
`MEASURED_INFERENCE_MEM_CAP_GB` and **record the change** - it is a condition
the numbers travel with (rule 3), not a config detail.

**EARNED BY** - 2026-08-29 00:25, reference machine (31.8 GB RAM, 28 GB
pagefile, 59.8 GB commit limit). Four llama-server pids alive; the top three
wanted ~53 GB. The last log line of any kind was 00:23:38; the power button was
pressed at 00:31:59, eight minutes into a dead box. First warning had been at
23:59:11, twenty-four minutes earlier, while the desktop was still usable.

## Every row of an arms.py sweep is REFUSED by the ledger's comparability gate

SYMPTOM: `python scripts/ledger.py compare --metric throughput.decode`
prints "REFUSED ... backend NOT NAMED / device NOT NAMED" for rows that
came out of results/<slug>/data/arms/*.jsonl, and the same sweep run on
another box cannot be stood beside this one at all.
CAUSE: the sweep recorded no provenance. Before 2026-08-30 arms.py never
called scripts/bench/provenance.py, so no line named a backend, a device
or a build, and "unknown" is never equal to "unknown".
FIX: re-run under a runner that stamps it, and NAME the backend where the
box cannot: `python scripts/arms.py --arms <file> --backend cuda`. On an
NVIDIA card on Linux the backend is not derivable - scripts/setup.sh
installs the Vulkan build unless --cuda was given - so ledger.py leaves
such a row unnamed and blocked, which is correct: two backends running
one file are two experiments. arms.py warns at sweep_start when nothing
named it, and records what it used as sweep_start.backend_cited.
Installing through setup.sh answers it the other way, by writing
bin/llama.cpp/INSTALL.json.
EARNED BY: the Windows-to-Ubuntu comparison this campaign exists to make,
which the gate would have refused on arrival.

## --resume duplicated probe lines after a crash MID-ARM

SYMPTOM: a 3-probe arm shows FOUR probe lines in the ledger, probe_index
0 twice, both naming one response_file; ledger.py emits four
throughput.decode rows for three probes that happened, and the body on
disk is the second generation while the first line's response_chars
still describes the first.
CAUSE: --resume skipped whole (arm, rep) units only. A unit with some but
not all of its probes recorded fell through every branch and RESTARTED
the arm, re-appending the probes it already had.
FIX: fixed in arms.py 2026-08-30, in two halves. The duplicate: a resumed
unit skips the probe indices the ledger already holds at that spec hash
and issues only the rest, and says RESUMING MID-ARM when it does. The
rule 12 half: the discard follows the POSITION IN THE LOAD, not the
probe number, so on a discard_first arm the first probe the fresh server
answers is discarded even though its probe_index is not 0. Read
load_probe_index on the resulting lines to see which probe that was; the
runner has already dropped it, so nothing is left for you to correct by
hand. The cost of the crash is that the arm ends one KEPT probe short of
a run that never crashed - rerun the whole arm if you need the full n.
EARNED BY: two defects in one code path. The duplicate was reproduced
against scripts/verify/fake-llama-server.py, indices [0, 0, 1, 2]. The
rule 12 half was reproduced the same way after the first fix landed: the
cold probe was kept and the summary published it as 55.00 t/s n=1 while
the warm probe read 100.00 - the stub's own constants (--rate 100, ramp
factor 0.55), so that gap IS rule 12's 45%, arriving as a number a
reader would have used. The regression test for the duplicate half is
the resume-mid-arm case in scripts/verify/test-arms.py; it uses no
discard_first arm, so it does not yet cover the rule 12 half.

## a long scored run crashes and its .partial.jsonl has no generations

SYMPTOM: `<run>.json.partial.jsonl` holds one row per question with
tokens, tok_s, score, correct and truncated - and no response text. The
end-of-run `*_transcripts.json` was never written because the run died
before its last question. Every text-dependent diagnostic is then
unavailable for a run that otherwise completed: the unparsed-answer
rate, the format tax, the repetition-loop spot-read of rule 20.
CAUSE: bench.py's per-question crash-protection append wrote `rec`, and
`rec` has had its text popped out one line earlier (`text =
rec.pop("text")`) so the text can be routed to the transcripts dict
instead. That dict is only serialised by checkpoint_cb, which fires once
per DATASET - for a single-dataset anchor run, once, at the very end.
So the safety net covered the cheap fields and dropped the expensive one.
`_grade_choice`'s docstring promised the diagnostic was recoverable by
"re-running this extractor over" the transcripts; that promise was void
for exactly the runs the safety net exists for.
FIX: fixed in bench.py 2026-09-01 - the partial row carries `response`
whenever the run is keeping transcripts (`keep_text`). Cost is one extra
short write per question. `scripts/bench/rescore-choices.py` reads either
artefact, and refuses a pre-fix .partial.jsonl by name rather than
reporting a textless run as a clean one.
EARNED BY: a 198-question GPQA-Diamond anchor at ~10 h wall clock,
noticed at question 185 while checking whether the harness could split
that score into knowledge and format. Rule 28 in the exact shape the rule
describes: the field was recoverable for free during the run and at no
price afterwards. Nothing was lost - that run reached its end - which is
the only reason this is a library entry and not a case study.

## a capability, token or field reads as ABSENT and the check truncated its own output

SYMPTOM: a scan reports a capability missing -- "vision/image tokens
present: NONE", "no matches", an empty list -- and the thing is
demonstrably there. The scan matched correctly; the DISPLAY was sliced.
CAUSE: `print(matches[:15])` over a 248,320-entry vocabulary whose
control tokens (`<|vision_start|>`, `<|image_pad|>`, `<|audio_pad|>`)
live at ids 248044-248076, i.e. at the very END. Ordinary word pieces
that also matched the substring filled the slice, so the answer was
248,038 entries past where the output stopped. Measured 2026-09-01: this
nearly wrote off a modality the vendor card, the projector header and
the model's own vocabulary all confirmed.
FIX: when a scan is being read as EVIDENCE OF ABSENCE, print the COUNT
before the sample, and slice from the end as well as the start --
special/control tokens sort last in every GGUF vocabulary. Better, ask
the structured question rather than a substring one: llama.cpp types
control tokens as `tokenizer.ggml.token_type == 3`, and enumerating
those 27 entries answers the modality question exactly, with no filter
and no slice.
EARNED BY: the general principle this repo keeps rediscovering from new
directions -- AN ABSENCE REPORTED BY AN INSTRUMENT IS ONLY EVIDENCE IF
THE INSTRUMENT COULD HAVE SHOWN THE PRESENCE. Same day, same lesson from
the other end: `loop-detect.py` returned ("clean", []) for the empty
string because every signal is 0.0 there and 0.0 fires no threshold, and
that verdict was published for three quant arms whose generations had
never been read. It now returns NO-DATA. A scan that cannot fail loudly
will fail quietly, and quiet failures get published.

## a check reports the SAFE answer for a condition it could not evaluate

SYMPTOM: a guard passes, a scan returns empty, a count returns zero, a
push reports success -- and none of it was measured. `servers: none`
from a process scan that could not run. `ahead=0` from a ref that could
not be resolved. `PUSHED 3 commit(s)` from a push that published
nothing. A resume key that says "already measured" for an arm whose
measurement failed. `verdict: clean` for a generation of zero bytes.
CAUSE: one shape, wearing eight costumes. Every instance is an
expression whose failure path produces the value that means EVERYTHING
IS FINE:
  `except Exception: pass; return out`     -> [] means "nothing running"
  `$(git rev-list ... || echo 0)`          -> 0 means "nothing to push"
  `if os.path.getsize(f) > 1e9: return`    -> big enough means "complete"
  `if rec.get("tg128"):`                   -> one field means "all three"
  `if os.path.exists(dat):`                -> exists means "written fully"
  `os.kill(pid, 0)`                        -> alive means "still the same
                                              process" (pids are reused)
FIX: make the failure path produce the ALARMING value, or an explicit
unknown that callers must handle. Concretely, in this tree: raise
`ServerScanFailed` rather than returning []; report "UNKNOWN, not zero"
rather than 0; compare the download against Content-Length; require
every field the record claims; write incremental files to `.part` and
`os.replace()` them; check argv, not just liveness. Then VERIFY THE
POSTCONDITION -- re-count after a push, re-read the lockfile after
taking it -- because a zero exit status is not proof that the thing
happened.
EARNED BY: an adversarial audit of this repo's durability scripts,
2026-09-01, which returned 24 verified findings; eight of the high ones
were this single shape. The reason it is worth its own entry is that
NONE of them announced themselves: each produced a plausible, reassuring
line in a log that a human was reading precisely to be reassured. The
sibling entries "a capability reads as ABSENT and the check truncated
its own output" and the `loop-detect.py` NO-DATA change are the same
principle from the other side -- an instrument that cannot fail loudly
will fail quietly, and quiet failures get published.
