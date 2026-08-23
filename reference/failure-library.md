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
