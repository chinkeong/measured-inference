# What to type

Copy a block, change what is in `<ANGLE BRACKETS>`, paste it to your agent.

Every prompt here opens with **`Read AGENTS.md, then skills/field-guide/SKILL.md.`**
Keep that line. Claude Code loads `CLAUDE.md` on its own and opencode loads
`AGENTS.md`, but Pi loads neither, and a prompt that works in two harnesses out
of three is a prompt that fails silently on the third.

Plain text is deliberate. A campaign usually runs on a borrowed or rented box
reached over SSH, where there is no browser to open a form in — so the interface
is a block you paste, which works the same in a terminal, a VS Code extension, a
desktop app, and a web session.

**If you read one thing, read [the fill-in form](#the-fill-in-form).** It is the
Stage 0 interview as an answer sheet: fill it in one pass, paste it once, and the
campaign runs to the end without stopping to ask you anything (rule 27). Every
field prints its default, so you can delete any line you do not care about.

> **Before any of this works**, the machine needs a runtime. On an NVIDIA box
> that is one `sudo` line and `./scripts/setup.sh --cuda` — see
> [Pre-flight](#pre-flight--prove-the-machine-is-ready-before-you-type-a-word-to-the-agent).
> The agent cannot run `sudo` for you.


## Contents

- [Start here](#start-here)
  - [Pre-flight — prove the machine is ready before you type a word to the agent](#pre-flight--prove-the-machine-is-ready-before-you-type-a-word-to-the-agent)
  - [The simplest prompt that works](#the-simplest-prompt-that-works)
  - [The fill-in form](#the-fill-in-form)
  - [What the agent does with it — the first ten minutes](#what-the-agent-does-with-it--the-first-ten-minutes)
- [Campaign shapes](#campaign-shapes)
  - [1. Single model, full field guide — the default shape](#1-single-model-full-field-guide--the-default-shape)
  - [2. The quant ladder — one model, many quants, ranked](#2-the-quant-ladder--one-model-many-quants-ranked)
  - [3. The multi-model shootout — the one people get wrong](#3-the-multi-model-shootout--the-one-people-get-wrong)
  - [4. A single question, not a campaign](#4-a-single-question-not-a-campaign)
- [Running it in the real world](#running-it-in-the-real-world)
  - [Benchmarks only — inherit a recipe, jump straight to Stage 6a](#benchmarks-only--inherit-a-recipe-jump-straight-to-stage-6a)
  - [One benchmark, not seven — the subset run](#one-benchmark-not-seven--the-subset-run)
  - [A hard stop at a given time — the rented machine](#a-hard-stop-at-a-given-time--the-rented-machine)
  - [Handover, part 1 — what the DEPARTING shift types](#handover-part-1--what-the-departing-shift-types)
  - [Handover, part 2 — what the ARRIVING shift types](#handover-part-2--what-the-arriving-shift-types)
  - [Resume after a crash or a lost session](#resume-after-a-crash-or-a-lost-session)
  - [Running it unattended overnight](#running-it-unattended-overnight)
- [Beyond the basics](#beyond-the-basics)
  - [Price a sweep before you run it](#price-a-sweep-before-you-run-it)
  - [Prove every probe still starts — four seconds, no GPU](#prove-every-probe-still-starts--four-seconds-no-gpu)
  - [A campaign where energy is the point](#a-campaign-where-energy-is-the-point)
  - [Energy on Linux: the sampler is PowerShell, the integrator is not](#energy-on-linux-the-sampler-is-powershell-the-integrator-is-not)
  - [A screenshot-loop campaign — and the hallucinated-sight hunt](#a-screenshot-loop-campaign--and-the-hallucinated-sight-hunt)
  - [Numbers for a card you do not have](#numbers-for-a-card-you-do-not-have)
  - [Troubleshooting: six failures, symptom then fix](#troubleshooting-six-failures-symptom-then-fix)
---

## Start here

This repo turns one local LLM on one GPU into `results/<slug>/index.html` — a single-page
field guide in which every recommendation carries the number that justifies it: which quant,
which context window, which reasoning effort, what it costs in tokens per second and watts,
and under exactly which conditions that was true. You drive it by pasting a prompt into a
coding agent; the agent interviews you **once**, then runs for hours to days without asking
anything again. The shape of the run is fixed: cheap probes buy the map (~4 h), the map locks
the recipes (no GPU at all), and only locked recipes earn the expensive hours.

There is one part the agent cannot do for you. On Linux + NVIDIA there are no official CUDA
binaries of llama.cpp, so the bootstrap refuses to install a Vulkan build behind your back and
exits 3 instead — you run `sudo apt-get install -y nvidia-cuda-toolkit cmake build-essential git`
yourself (an agent cannot type `sudo`), then `./scripts/setup.sh --cuda`, which builds from
source in about 4 minutes on an RTX 3090. Do that before you paste anything.

### Pre-flight — prove the machine is ready before you type a word to the agent

Run these five yourself, in the clone, top to bottom. Nothing here loads a model or spends GPU
time; the whole block is about four minutes, almost all of it the CUDA build. Do it now rather
than discovering a missing toolchain forty minutes into a campaign.

```sh
# 1. You are inside the clone. Every stage ends in a checkpoint commit, so this must be a git repo.
git rev-parse --show-toplevel

# 2. The driver sees the card. If this prints nothing, no amount of prompting fixes it.
nvidia-smi -L

# 3. HUMAN STEP — the agent cannot type sudo. Linux + NVIDIA only; skip on Windows/macOS.
sudo apt-get install -y nvidia-cuda-toolkit cmake build-essential git

# 4. Installs llama.cpp into bin/llama.cpp/ and creates the repo-local .venv. Nothing global.
#    ~4 min measured on an RTX 3090. Add --dry-run first to see the plan without touching anything.
./scripts/setup.sh --cuda

# 5. Prints what resolves on THIS machine and why — the fastest readiness check in the repo.
python scripts/lib/paths.py
```

On Windows, steps 3 and 4 collapse into `.\scripts\setup.ps1` — Windows *does* have official
CUDA binaries, so that path is a download, not a source build, and needs no toolchain and no
admin. macOS and Intel/AMD GPUs: drop `--cuda`, the official binary release is the right build
there.

After step 4, use the interpreter setup just created for every Python line in this guide —
`.venv/bin/python` on POSIX, `.venv\Scripts\python.exe` on Windows. `paths.py` itself is stdlib
only and runs under any Python 3.10+, which is why step 5 works even if step 4 failed.

**What step 5 prints on a fresh clone, before anything is installed:**

```
repo_root      /home/you/measured-inference
campaign.json  absent - would be /home/you/measured-inference/results/qwen38-27b-blind/campaign.json
machine.json   absent - would be /home/you/measured-inference/results/qwen38-27b-blind/machine.json
llama-server   NOT FOUND (see the message this raises when a run needs it)
llama-perplexity NOT FOUND (see the message this raises when a run needs it)
llama-tokenize NOT FOUND (see the message this raises when a run needs it)
board          unavailable - no machine.json
desktop        unavailable - no machine.json
```

Read the lines, not the exit code: `paths.py` is a printer, not a gate, and exits 0 even when
everything is missing. After a good setup the three tool lines must name real files under
`bin/llama.cpp/`. `campaign.json` / `machine.json` absent is *correct* at this point — Stage 0
writes them, and it closes only when both exist. The `qwen38-27b-blind` in those "would be"
paths is not yours: it is the closed worked example that ships with the repo, and it is the only
`results/` directory on a fresh clone, so `paths.py` names it for lack of an alternative. Once
your own `results/<slug>/` exists the line points there. Once *two* campaigns exist, `paths.py`
refuses to guess and tells you to set `MEASURED_INFERENCE_SLUG=<slug>` — set it and the
ambiguity is gone.

**The failures you will actually hit, and what each one means:**

- **exit 3, "NVIDIA GPU detected, but the backend on offer is 'vulkan', not CUDA"** — you left
  off `--cuda` on Linux. This is the refusal working, not a bug: a Vulkan number and a CUDA
  number differ in prefill, decode, acceptance and VRAM ceiling for reasons that have nothing to
  do with the model. Run the sudo line, then `--cuda`. `MEASURED_INFERENCE_ALLOW_VULKAN=1`
  overrides it deliberately, and the backend then becomes a published condition of every number.
- **exit 3, "--cuda needs the CUDA toolkit, and nvcc is not on PATH"** — step 3 has not run, or
  CUDA lives somewhere unusual: `CUDA_HOME=/usr/local/cuda ./scripts/setup.sh --cuda`.
- **exit 3, "--cuda needs cmake" / "--cuda needs git"** — the same apt line covers both.
- **exit 4, "cmake configure failed"** — retry with `./scripts/setup.sh --cuda --cuda-arch 121`;
  `native` is the default and DGX Spark GB10 is the known case where it is not supported.
- **exit 5** — a frozen input no longer matches its committed bytes, which on Windows is almost
  always CRLF rewriting. It matters because two reports only compare when their suite hashes
  match. Fix the checkout, or proceed knowingly with `MEASURED_INFERENCE_ALLOW_CRLF=1`.
- **exit 6** — no usable Python 3.10+ or venv: `sudo apt-get install -y python3 python3-venv python3-pip`.

### The simplest prompt that works

One model, defaults everywhere, no vision, no agents. Paste this whole block as your first
message. Cost: about 4 hours of cheap probing through Stage 5, then 6–10 hours of measurement
in Stage 6 if you say overnight.

```
Read AGENTS.md, then skills/field-guide/SKILL.md.

I want a field guide for <https://huggingface.co/ORG/REPO-GGUF>.
Slug: <somenew-32b>
Time budget: overnight (~8 h)
Use cases: text coding only
Philosophy: quality-first
Coding agents to test: none
Publish to: results/<somenew-32b>/index.html

Run the Stage 0 interview in ONE round: propose the quant roster from the repo's
file listing, prove download access with a range request before the interview
closes, and show me the machine detection to confirm. Then run autonomously to
the end — after Stage 0 closes, do not stop to ask me anything (rule 27).
```

The opening line is not decoration. Claude Code auto-loads `CLAUDE.md`, opencode auto-loads
`AGENTS.md`, and Pi loads neither — spelling out both files is what makes one prompt work in
every harness. The agent will still come back to you once, with the proposed quant roster and
the detected hardware; that single round **is** the interview, not a failure to be autonomous.
If you would rather answer everything in one pass and never be interrupted, use the form below.

### The fill-in form

This is the whole interview on one sheet. Fill it in, paste it back as a single message, and
Stage 0 closes on the spot. Free — no GPU. It covers all seven interview questions in order, so
an agent that receives it has no legitimate reason to ask you anything else for the rest of the
campaign.

```
=== MEASURED-INFERENCE STAGE-0 ANSWER SHEET v1 ===
Read AGENTS.md, then skills/field-guide/SKILL.md. Treat this sheet as the CLOSED
Stage 0 interview: record it in results/<slug>/campaign.md and run autonomously
to the end (rule 27). Any line I deleted takes the default printed beside it.
Three fields are MANDATORY: Q1 repo URL, Q4 time budget, Q6 slug.

Q1  MODEL  (repo URL MANDATORY)
    repo URL ............ <https://huggingface.co/ORG/REPO-GGUF>
    also compare ........ <URL2> <URL3>   (optional - default: none. If I list
                          any, they run as arms in ONE sweep, never as separate
                          campaigns: three campaigns cannot be compared on
                          absolutes - rule 30)
    quants .............. [x] you propose the roster from the file listing (default)
                          [ ] exactly these: <Q4_K_M> <UD-IQ4_XS> <...>
    vision projector .... [x] use the repo's mmproj if one exists (default)
                          [ ] skip vision entirely
    gated repo? ......... [x] no, public (default)
                          [ ] yes, token: <hf_...>
                          Prove access NOW, before this interview closes:
                          curl -sI -r 0-1023 <resolve-url>  -> expect 206/200.
                          A 401/403 here is the whole point of asking: the
                          listing API answers fine for gated repos, so a
                          successful listing is NOT proof of access. This repo
                          has no model downloader and no HF-token plumbing —
                          you download by hand and put the token on that
                          command yourself.

Q2  MACHINE  (optional - default: accept the auto-detection as printed)
    desktop state ....... <idle, monitors on, browser closed>
    RAM channels ........ <2>       (a single-stick box halves every offload
                                     and iGPU estimate - say so if you know)
    backend ............. <none>    (only if what setup installed differs from
                                     what nvidia-smi implies)
    what the box cannot report about itself: <e.g. power limit raised to 350 W>

Q3  USE CASES  (optional - default: text coding only. Decides Stage 6's optional work)
    [x] text coding
    [ ] vision / screenshot loops
    [ ] coding agents end-to-end
    [ ] long context — the depth I actually work at: <65536> tokens

Q4  TIME BUDGET  (MANDATORY - pick exactly one. Stages 0-5 run in every budget,
                  ~4 h; the budget buys Stage 6)
    [ ] overnight (~8 h)  primary + 1 challenger get the full treatment (n=200
                          accuracy, full PPL); other survivors get load-and-speed
                          probes only; effort quality = 2 runs x 3 levels, one file
    [ ] multi-day         every surviving quant gets the full treatment, plus the
                          per-file ceiling sweep and per-effort-level accuracy
    [ ] less than overnight — accepted as a SMOKE TEST ONLY: publish no quant
                          ranking from it and say so in the report
    hard stop at ........ <2026-09-01 08:00 local>   (optional - default: none.
                          There is no deadline flag: you hold the clock, running
                          one arm at a time with --only <id> --resume and checking
                          the time before each invocation)

Q5  PHILOSOPHY  (optional - default: quality-first)
    [x] quality-first — ship max effort wherever the window allows
    [ ] latency-first — smallest settings that still hold quality
    effort/thinking knob  [x] read the chat template and decide (default)
                          [ ] force off — skip Stage 4 appetite probes and the
                              Stage 6 effort arms entirely

Q6  PUBLISH  (slug MANDATORY)
    slug ................ <somenew-32b>   (the repo name lowercased, a SINGLE
                          path component, -GGUF dropped. Reuse it verbatim
                          after any crash — never derive a second one)
    also publish to ..... <none>          (optional - a git remote or a site dir)

Q7  CODING AGENTS  (optional - default: test whatever is already on PATH)
    test these .......... [x] whatever you detect on PATH (default)
                          [ ] none — skip the agent work and say so in the report
                          [ ] exactly: <opencode> <aider> <qwen> <pi> <dsh> <claude>
    may you install missing ones? (npm/pip, user scope only)
                          [x] no (default — this machine may be borrowed)
                          [ ] yes

ANYTHING ELSE
    <e.g. do not install anything globally; the GPU is shared after 09:00>

=== END STAGE-0 ANSWER SHEET v1 ===
```

How to use it: copy the block, fill it in wherever you see `<angle brackets>` and move the `[x]`
to the option you want, delete any optional line you do not care about, and paste the result as
one message. The version marker and the end marker are how the agent recognises a filled sheet
and knows nothing was truncated. An agent that receives it treats the interview as closed —
it writes your answers into `results/<slug>/campaign.md` and does not ask again, because
questions are allowed at Stage 0 only. If it still asks something, the answer is almost always a
field you deleted that was mandatory.

### What the agent does with it — the first ten minutes

- **Minute 0–1, no GPU.** Reads `AGENTS.md` (30 invariants plus a routing table) and
  `skills/field-guide/SKILL.md`, then lists `results/*/campaign.md` to check whether it is
  resuming an old campaign rather than starting yours. It should say out loud that
  `results/qwen38-27b-blind/` is the shipped worked example, is closed, and will not be
  continued. If it starts reading that campaign's log as if it were yours, stop it.
- **Minute 1–3, network only.** Resolves the HuggingFace file listing, proposes the quant roster
  (a Q4-class primary plus challengers, and the `mmproj` projector if one exists), and proves
  download access with a range request. This is the last moment a gated repo can be caught: with
  the interview closed there is no way to ask you for a token later.
- **Minute 3–5.** Runs `python scripts/detect-machine.py --slug <slug> --desktop-state "<...>"`
  and writes `results/<slug>/machine.json`. It reads the board and briefly rewrites the power
  limit to the value already in force to learn whether that needs elevation; no model is loaded.
  This file replaces the reference 3090's hardcoded board size — without it, a 12 GB card would
  happily report comfortable free VRAM while spilling to host RAM.
- **Minute 5–6.** Copies `results/TEMPLATE-campaign.json` to `results/<slug>/campaign.json` and
  fills in slug, port, `llama_dir`, `model_dir` and every logical model name the sweeps will
  reference. The sweep files carry no paths at all, so this is the only place `Q4_K_M` becomes a
  real `.gguf`; skip it and the roster resolves to nothing mid-run.
- **Minute 6–8.** Starts the 500 ms `nvidia-smi` power logger detached, writing
  `results/<slug>/data/power/campaign-power.csv`, and takes the **cold** idle baseline — 15+
  samples with nothing loaded, dated in `campaign.md`. Keep the box quiet for these two minutes:
  a board still warm from other work reads far high, and every idle-subtracted watt for the rest
  of the campaign is measured against this number.
- **Minute 8–10.** Writes the interview record into `results/<slug>/campaign.md` and commits.
  Stage 0 is now closed — the test is simply that `campaign.json` and `machine.json` both exist.
  Re-run `python scripts/lib/paths.py`: it should now print your slug, both files present, and a
  real board and desktop figure. That output is your "it is working" signal.
- **After minute 10, the GPU is finally used.** Stage 1 downloads the weights (expect tens of GB
  and a long quiet stretch — there is no downloader script, so this is a plain `curl`/`wget`),
  launches the first `llama-server`, verifies `-ngl`, and runs one floor probe per quant, about
  an hour. From here it is autonomous for hours. Ctrl-C during an arm is safe: the server is
  stopped and every completed probe stays in the ledger, and `--resume` picks up where it
  stopped. What is *not* safe is `kill` on a detached run — on Linux that orphans `llama-server`
  holding your VRAM.

---

## Campaign shapes

Four kinds of run come out of this repo, and they are not interchangeable. Pick the
shape first, because the shape decides your slug, your arm files, and whether your
numbers are comparable to each other at the end. Every prompt below opens with the same
line — `Read AGENTS.md, then skills/field-guide/SKILL.md.` — because Claude Code
auto-loads `CLAUDE.md`, opencode auto-loads `AGENTS.md`, and Pi loads neither. That one
line is what makes these prompts portable across harnesses.

All four assume you have already run the bootstrap (`scripts/setup.sh` on POSIX,
`scripts/setup.ps1` on Windows) or that the prompt's first step tells the agent to.

---

### 1. Single model, full field guide — the default shape

This is what the repo is for: one model, one machine, one published HTML field guide in
which every recommendation carries the number that justifies it. Stages 0–5 (the map and
the RECIPE LOCK, ~4 h) run in **every** budget — they are what makes the expensive hours
safe. What your time budget actually buys is Stage 6. Use the overnight variant when you
have a night; use the multi-day variant when you want a quant ranking you can defend.

**Variant A — overnight (~8 h).** Costs about 4 h of cheap mapping, then ~4 h of
characterization, then ~1 h of publishing.

```
Read AGENTS.md, then skills/field-guide/SKILL.md.

Run a full field-guide campaign on <HUGGINGFACE MODEL URL, e.g. https://huggingface.co/unsloth/SomeNew-32B-GGUF>.

Interview me once, now, in a single round — that is Stage 0 and it is the only
place you may ask me anything. Here are my answers in advance so the round is
short:

  - Slug: <SLUG, the repo name lowercased as ONE path component, -GGUF dropped>
  - Use cases: <text coding | vision-screenshot loops | coding agents | long context>
  - Time budget: OVERNIGHT (~8 h)
  - Philosophy: <quality-first | latency-first>
  - Publish target: results/<SLUG>/index.html <and: push to <GIT REMOTE OR SITE DIR>>
  - Coding agents to test: <none | the ones you detect on PATH>

Still ask me the things you must confirm rather than assume: the quant roster you
propose from the HF file listing, whether an mmproj/vision projector exists, the
auto-detected machine facts, and — before the round closes — prove download access
with a range request on one chosen file (curl -sI -r 0-1023 <resolve-url>; expect
206/200, not 401/403). If it 401s, ask me for an HF token in this same round.

Close Stage 0 only when results/<SLUG>/campaign.json AND results/<SLUG>/machine.json
both exist. Then run autonomously to Stage 7 and do not stop to ask me anything.

Overnight budget means, per SKILL.md Stage 0 item 4: the primary quant and ONE
challenger get the full treatment (n=200 accuracy each, full PPL on those two);
every other surviving quant gets load-and-speed probes only; effort quality runs
at 2 runs x 3 levels on one file. Say that scope in the report.

Checkpoint-commit after every stage. Append every decision and finding to
results/<SLUG>/campaign.md as you go — that file is my recovery point if the
session dies.
```

**Variant B — multi-day.** Same campaign, a bigger Stage 6. Reach for it when the
deliverable is a quant *ranking* rather than a recommended config, or when you want the
context-ceiling sweep run per file instead of once.

```
Read AGENTS.md, then skills/field-guide/SKILL.md.

Run a full field-guide campaign on <HUGGINGFACE MODEL URL>, slug <SLUG>.

Time budget: MULTI-DAY. Per SKILL.md Stage 0 item 4 that means every surviving
quant gets the full treatment (n=200 per arm, full PPL on every file), plus the
Stage-2 ceiling sweep per file and Stage-6 accuracy per effort level.

Interview me once in a single round (Stage 0), confirm the quant roster and the
detected machine, prove download access before the round closes, then run
autonomously to Stage 7.

My other answers: use cases <...>, philosophy <quality-first | latency-first>,
publish to results/<SLUG>/index.html, coding agents <none | list>.

I am not available between now and Monday. If something is ambiguous mid-run,
resolve it in this order and keep going: the interview record in campaign.md,
then the measured default, then record the assumption in campaign.md and proceed.
Never stop to ask.

Checkpoint-commit after every stage.
```

Below the block, the things a first-timer gets wrong:

- **Anything shorter than overnight is a smoke test.** SKILL.md is explicit: a
  below-overnight run must say so in the report and may **never** publish a quant
  ranking. If you have three hours, run shape 4 instead and ask one question properly.
- **The slug is one path component, and you pick it once.** `unsloth/SomeNew-32B-GGUF`
  becomes `somenew-32b` — lowercased, no slashes, `-GGUF`/`-gguf` dropped. After a crash
  you reuse that exact string; deriving a second slug splits your results across two
  directories.
- **There is no model downloader in this repo and no HF-token plumbing.** Stage 1 pulls
  weights with plain resumable `curl` into `models/`. A gated repo will pass the
  interview's listing step and fail at download time, which is why the access check is a
  range request on a real file and why the token has to be handed over during Stage 0 —
  after the interview closes, the agent is forbidden from asking you for it.
- **Linux + NVIDIA needs a human first.** `scripts/setup.sh` exits **3** rather than
  silently installing a Vulkan build, because a Vulkan campaign is not comparable to a
  CUDA one. Building from source is `./scripts/setup.sh --cuda` (~4 min of build measured
  on an RTX 3090; `stages/stage-1.md` budgets 10–25 min including the toolchain install),
  and it needs `sudo apt-get install -y nvidia-cuda-toolkit cmake build-essential git`
  first — **the agent cannot run that sudo**, so do it yourself before you paste.
- **Do not point a new campaign at `results/qwen38-27b-blind/`.** It ships as the closed
  worked example. It is not resumable and a new campaign must not continue it.

---

### 2. The quant ladder — one model, many quants, ranked

One model family, several GGUF files, ordered worst-to-best on evidence. This is the
shape the shipped worked example report used (`templates/example-report.html` ranks nine
versions of one 27B model). Reach for it when the real question is "which file should I
actually keep on this card". It is a multi-day shape: perplexity is 36 x 8,192-token
chunks per file, and that is per file, not per campaign.

```
Read AGENTS.md, then skills/field-guide/SKILL.md.

Quant-ladder campaign on <HF REPO URL>, slug <SLUG>. Time budget: MULTI-DAY.

The deliverable is a RANKING of these files, largest to smallest:
  <FILE 1, e.g. SomeNew-32B-Q6_K.gguf>
  <FILE 2, e.g. SomeNew-32B-Q4_K_M.gguf>
  <FILE 3, e.g. SomeNew-32B-UD-IQ4_XS.gguf>
  <FILE 4, e.g. SomeNew-32B-UD-Q3_K_XL.gguf>
  <FILE 5, e.g. SomeNew-32B-UD-IQ2_S.gguf>   <- include a rung that clearly FAILS
plus the projector <mmproj FILE, or "none">.

Interview me once (Stage 0), confirm this roster against the HF file listing,
detect the machine, prove download access, then run autonomously.

Rank them by PERPLEXITY over 294,912 token positions (36 x 8,192-token chunks of
the frozen wikitext-2-raw test corpus) — METHODOLOGY rule 6. Accuracy at n<=25 is
a SMOKE TEST that detects only ~20-point collapses; it may locate where the model
breaks and it may never order one file against another. If you print an accuracy
column, label it that way in the table itself.

Stage 1's pruning gate is the point of this shape: a file that is slower AND
worse is dropped there, before it earns expensive hours, and the report lists it
as "screened out at the Stage-1 gate" with the numbers that screened it out — so
no reader mistakes a pruned file for an untested one.

Run the ranking with scripts/quant-ladder/run-ladder.ps1 driven by a manifest
modelled on scripts/quant-ladder/ladder-manifest.json, one rung per file. If this
machine is not Windows, that runner does not exist for it: drive llama-perplexity
yourself at the manifest's conditions (-ngl 99 -c 8192 -fa on --load-mode mmap,
f16 KV, the md5-pinned corpus) and budget that port BEFORE spending the hours.

Checkpoint-commit after every stage.
```

- **Perplexity ranks, accuracy does not.** This is the single most common misreading of
  a ladder table. Rule 6's arithmetic: detecting a 20-point gap needs ~25 samples; a
  10-point gap ~100–150; a 5-point gap ~300–500; a 1–3-point gap needs *thousands*. Quant
  gaps live in that last band. A 25-question cell cannot see them.
- **Include a rung you expect to fail.** A ladder whose every rung passes has not found
  the floor, it has just run out of files.
- **`run-ladder.ps1` is Windows PowerShell and this repo ships no POSIX equivalent.** The
  prompt above says so out loud so the agent budgets the port instead of discovering it
  at hour six. It is resumable either way (a rung whose RESULT or FAILED line is already
  in the ledger is skipped), and `-Once` does one rung per invocation if your harness
  kills long tasks.
- **Perplexity is a within-family tool only.** It is tokenizer-dependent, so it ranks
  quants of one model and nothing else. See shape 3 for what to do across models.
- **Weights arrive by hand.** Same as shape 1: `curl` into `models/`, verify byte sizes
  against the HF listing, and never download a file you are not going to measure.

---

### 3. The multi-model shootout — the one people get wrong

Three different models at two quant levels each, ranked against one another. The mistake
is obvious once stated and nearly universal in practice: people run three campaigns and
put the three throughput numbers in one table. **That table is not measuring the models.**
A shootout must be ONE campaign, ONE slug, and all six files as arms in ONE sweep group.

```
Read AGENTS.md, then skills/field-guide/SKILL.md.

Comparison campaign — do NOT run three separate campaigns. ONE campaign, ONE
slug, all six files as arms inside ONE sweep group.

Slug: <SLUG, e.g. shootout-2026-08>
Files (two quants each, three models):
  <MODEL A> : <A-Q4 FILE>, <A-IQ4 FILE>
  <MODEL B> : <B-Q4 FILE>, <B-IQ4 FILE>
  <MODEL C> : <C-Q4 FILE>, <C-IQ4 FILE>

Interview me once (Stage 0), confirm the roster, detect the machine, prove
download access on ALL SIX files before the round closes, then run autonomously.
Time budget: <OVERNIGHT | MULTI-DAY>.

Write ONE new arm file under scripts/arms/ with all six as arms carrying the SAME
"sweep" value, and leave "order" at its default "alternate" so every second pass
runs the group backwards — METHODOLOGY rule 30 says arm POSITION must not be
mistakable for a property of the arm. Map each file to a logical model name in
results/<SLUG>/campaign.json "models" so the arm file stays path-free.

Dry-run it first, then run it:
  python scripts/arms.py --arms scripts/arms/<MY-SHOOTOUT>.json --slug <SLUG> --dry-run
  python scripts/arms.py --arms scripts/arms/<MY-SHOOTOUT>.json --slug <SLUG>

Rule 30 binds what I may be told at the end: compare arms INSIDE this one sweep,
never a number from this sweep against a number from any other. Publish the level
a reader usually gets, not the best one observed.

Rule 6 binds the QUALITY comparison: raw perplexity is tokenizer-dependent and
compares nothing across model families. For the cross-model quality row use
bits-per-byte (each model's OWN token count) or the rule-21 scored benchmarks —
both tokenizer-independent. Raw PPL is allowed only WITHIN one model's two quants.

The deliverable is a comparison document, not three field guides — SKILL.md scopes
the report to one model on one machine. Write it as a comparison and say in its
own text which claims are cross-model (ratios, scored benchmarks, bits-per-byte)
and which are within-model only.

Checkpoint-commit after every stage.
```

**Why three separate campaigns cannot be compared on absolutes, in plain terms.** On the
reference rig, twenty-three runs of one *identical* configuration produced twenty results
between 75.71 and 78.65 t/s and three at about 88 — two levels roughly 13% apart, with
nothing in between and nothing recorded that predicts which one you get. (Seven causes
were tested and every one was eliminated; the cause is unmeasured, so do not name one.)
Run three campaigns on three evenings and each lands on whichever level it lands on, so a
table reading "model A 78 t/s, model B 88 t/s" may be showing you the level and not the
model at all. Inside one sweep the arms run back-to-back with their order alternated, and
what survives that is the *relationship* between them: when the reference drafter sweep
was re-run last-to-first, every relationship kept its sign and rough size (f16 KV −8.9%
then −8.2%; `-c 180224` −3.1% then −4.7%) while the baseline arm itself moved 76.32 to
67.41, −11.7%. Ratios travel. Levels do not.

- **If you have already run three separate campaigns, you are not stuck — you are
  limited.** What stays legitimate is the ratios *within* each campaign, each measured
  against its own baseline in its own sweep: "the drafter bought +18% on model A and +9%
  on model B" is a real comparison. What dies is every absolute across them: t/s, tokens
  per joule, any single-figure throughput claim. You cannot fix it by averaging, and you
  cannot fix it after the fact — the only repair is one sweep with all the arms in it.
- **Six files means six downloads and six access checks.** One gated repo out of six
  fails at Stage 1 with the no-questions rule already in force. Make the interview prove
  access on all six.
- **The report spec is scoped to one model family.** SKILL.md's product is "a
  single-page HTML field guide for one model on one machine". A shootout is a different
  document, so ask for it as one; asking for "three field guides" gets you three
  campaigns and the mistake this whole shape exists to prevent.
- **Six files is six times the Stage-6 bill.** Rule 21's suite is 175 prompts per arm and
  the bench README budgets ~4–8 h per model at max effort on a 24 GB card. Say overnight
  and expect load-and-speed probes for most of the roster.

---

### 4. A single question, not a campaign

Sometimes you do not want a report. You want one number: *what is the largest `-c` this
card will hold with this file*, or *does the drafter actually help on my workload*. The
repo answers both with existing arm files and no campaign at all. Cost is minutes to about
an hour, and the dry run costs nothing.

**"What is the best `-c` I can run on this card with this file?"** — `ctx-ceiling.json`,
25 arms, stepping `-c` upward to the spill tipping point.

```
Read AGENTS.md, then skills/field-guide/SKILL.md.

I do not want a campaign. I want one answer: the largest -c I can run on this
card with <MY GGUF FILE> <and the projector <mmproj FILE> | with no projector>.

Set up only what a sweep needs: results/<SLUG>/campaign.json with my file mapped
to the logical model names that scripts/arms/ctx-ceiling.json declares, and
results/<SLUG>/machine.json from `python scripts/detect-machine.py --slug <SLUG>`.
Confirm with `python scripts/lib/paths.py` that the binary and the weights both
resolve before touching the GPU.

Then DRY RUN first — it launches nothing and writes nothing:
  python scripts/arms.py --arms scripts/arms/ctx-ceiling.json --slug <SLUG> --dry-run

Show me the plan, then run the ladder. It is a ladder, so its order is "fixed" on
purpose — walk it and stop at the first arm that fails to start.

I have a hard stop at <TIME>. arms.py has no deadline flag, so YOU hold the clock:
run one arm at a time with `--only <ARM ID> --resume` and check the time before
each invocation. results/<SLUG>/work/heartbeat.json names the arm in flight if
anything dies.

Report the two ceilings separately — fully resident and shallow-safe — plus the
collapse point, and label each with the file, drafter, projector and desktop state
it was measured under (rule 13). Do not label a window without a deep-fill probe
near its top.
```

**"Does the drafter help on my workload?"** — `spec-sweep.json`, 6 arms, one code probe
each, speculative decoding off vs. five n-max/p-min settings.

```
Read AGENTS.md, then skills/field-guide/SKILL.md.

One question, no campaign: does speculative decoding help on MY workload?

Slug <SLUG>; map my file(s) into results/<SLUG>/campaign.json "models" under the
logical names scripts/arms/spec-sweep.json declares, and write machine.json with
`python scripts/detect-machine.py --slug <SLUG>`.

Dry-run first and show me the exact argv it prints:
  python scripts/arms.py --arms scripts/arms/spec-sweep.json --slug <SLUG> --dry-run

Then run it. The stock probe is a red-black-tree code prompt; if my workload is
not code, say so in the output rather than pretending the number transfers, and
tell me what a workload-matched probe would cost.

Report BOTH acceptance rate AND mean draft length (rule 11 — acceptance IS the
speedup, but mean draft length is the throughput predictor). Compare the six arms
against each other only; do not put any of these numbers beside a figure from a
different sweep.

If I ask for a second opinion afterwards, re-run with --resume rather than from
scratch.
```

- **`--dry-run` costs nothing and prints the exact argv.** It resolves every binary and
  every model path up front, prints the full plan — every arm, its resolved model path,
  its complete `llama-server` command line, every probe and the exact request body — and
  refuses the GPU outright while doing it, so a plan that accidentally tried to launch
  something becomes a stack trace instead of a wasted hour. An arm whose model it cannot
  find is printed as `UNRESOLVED` and the run exits 2, which makes the dry run a "are my
  weights findable" check as well. There is never a good reason to skip it before
  committing hours.
- **`--dry-run` still needs a slug; `--list` does not.** `--list` resolves no paths at
  all, so `python scripts/arms.py --arms scripts/arms/spec-sweep.json --list` runs on a
  laptop with no GPU and no weights and shows you the arms, flags and probes. Use it to
  read a sweep before you own the hardware.
- **The stock arm files name logical models, not paths.** They declare names like
  `Q4_K_M`, `UD-IQ4_XS` and `mmproj`, resolved through `campaign.json`. Map your own
  files onto those names — `"models": {"Q4_K_M": "/path/to/your-file.gguf"}` is accepted —
  or have the agent write a new arm file. No absolute path ever belongs inside an arm
  file; that is what lets one file run on Windows today and Linux tomorrow.
- **The five stock arm files, so you know what already exists:** `ctx-ceiling.json` (25
  arms), `spec-sweep.json` (6), `acceptance.json` (2), `depth-series.json` (2),
  `effort-sweep.json` (11).
- **Ctrl-C mid-arm is safe.** The server is stopped and the ledger keeps every completed
  probe; re-run the same command with `--resume` and it skips the units already recorded.
  A *detached* run killed with a plain `kill` on Linux orphans `llama-server` — check with
  `python scripts/bench/gpu_lock.py status` and `... kill` if it names a holder.
- **One question is not a report.** Nothing here has been through the Stage-5 RECIPE LOCK
  or the Stage-7 review gates, so a number from shape 4 is a number you measured, not a
  number you may publish as a recommendation.

---

## Running it in the real world

The campaign skill assumes a clean start on a machine you own. Real runs are not
like that: the box is rented, the shift ends, the SSH session drops, the session
dies at 03:00. These templates cover the cases where the clock or the machine —
not the methodology — is the thing that changed.

Three facts govern all of them, and every template below leans on one:

- **The GPU takes one job at a time**, enforced by a machine-wide lockfile
  (`python scripts/bench/gpu_lock.py status` / `kill`). Rule 20.
- **The ledger is written as you go.** `scripts/arms.py` appends and *fsyncs* one
  JSON line per probe to `results/<SLUG>/data/arms/<STEM>.jsonl` the moment the
  probe returns. An interruption costs at most the arm in flight. Rule 28.
- **Questions happen at Stage 0 only.** After the interview closes the campaign
  is autonomous, so the prompt has to carry everything the run needs *before* it
  starts. Rule 27. Every template ends by saying so out loud.

---

### Benchmarks only — inherit a recipe, jump straight to Stage 6a

Skips Stages 1–5 entirely and runs rule 21's seven-benchmark suite on settings
you already measured. Reach for it when a previous campaign on this same box
produced a recipe and you only want fresh accuracy numbers for a new file.
**Cost: 4–8 h per model at max effort on a 24 GB card**, and it holds the card
for that whole time.

```
Read AGENTS.md, then skills/field-guide/SKILL.md.

This is NOT a full campaign. Do not run Stages 1-4 and do not sweep anything.
I already have this model's settings from an earlier campaign on this same
machine, and I want Stage 6a accuracy only.

  slug:            <SLUG>
  model file:      <ABSOLUTE PATH TO THE .gguf>
  recipe source:   <results/<OTHER-SLUG>/campaign.md RECIPE LOCK, or a report URL>
  window (-c):     <CTX, e.g. 32768>
  server flags:    <-ctk q8_0 -ctv q8_0 --spec-type draft-mtp --spec-draft-n-max 4 --spec-draft-p-min 0.75>
  cap:             <MAX COMPLETION TOKENS, e.g. 16384>
  effort level:    <LEVEL, or none>
  same machine as the recipe: <YES / NO>
  judge endpoint:  <http://<OTHERBOX>:1300/v1, or NONE>
  judge model id:  <NAME, or n/a>

Steps, in order:

1. Readiness, no GPU:
     python scripts/lib/paths.py
   It must resolve llama-server and the model file. If campaign.json is
   missing, copy results/TEMPLATE-campaign.json to
   results/<SLUG>/campaign.json and fill in slug, models and port. Then:
     python scripts/detect-machine.py --slug <SLUG> \
       --desktop-state "<WHAT THE DESKTOP IS DOING RIGHT NOW>"
   Stage 0 is closed only when campaign.json AND machine.json both exist.

2. Write the RECIPE LOCK before spending a GPU minute. Rule 25 admits no
   exception for an inherited recipe. Append a dated "RECIPE LOCK (inherited)"
   section to results/<SLUG>/campaign.md carrying: the file, the window, the
   full flag list, the cap, the effort ceiling, and where the recipe came
   from. If "same machine" above is NO, record it as an inherited HYPOTHESIS
   rather than a lock, verify the window actually loads once before the suite,
   and label every published number as measured here, not there.

3. Run the suite exactly as rule 21 defines it - seed 42, n=25, 16,384 cap,
   all seven benchmarks:

     python scripts/bench/bench.py --model <ABSOLUTE PATH TO THE .gguf> \
       --rule21 --ctx <CTX> \
       --server-args "<SERVER FLAGS>" \
       --judge-url <JUDGE URL> --judge-model <JUDGE MODEL ID>

   Drop the two --judge flags if there is no judge endpoint. Do NOT add
   --datasets: --rule21 already names all seven, and narrowing or widening it
   changes what the Mean means.

4. When it finishes: copy the run's .json, .png and any _transcripts.json out
   of scripts/bench/results/ into results/<SLUG>/data/ (scripts/bench/results/
   is gitignored, so anything left there is not in the record). Append the
   composite Mean AND its "included" list to campaign.md. Checkpoint commit.

5. If any answer truncated, rule 7 applies: raise the cap and rerun that arm
   only - greedy decoding makes the other arms byte-identical, so it is cheap.
   Never filter the truncating questions out.

Do not ask me questions after this message; rule 27 closed the interview.
Record any assumption you have to make in campaign.md and keep going.
```

**What a first-timer gets wrong here.**

- `bench.py` launches its own llama-server with `-m -c -ngl 99 --parallel 1
  --jinja --host --port` **fixed**. Put the window in `--ctx`; put everything
  else in `--server-args`; do not repeat `-c`, `-ngl`, `--parallel` or `--jinja`
  there.
- Without `--ctx`, `--rule21` sizes the window itself — the smallest power of two
  above the longest prompt plus the cap, which is **32768** at the default 8192
  prompt guard. Pass `--ctx` only when your locked window differs, and remember
  a bigger window costs VRAM you may not have.
- `--server-args` is whitespace-split, and a JSON value like
  `--chat-template-kwargs {"reasoning_effort":"high"}` does not survive
  PowerShell 5.1's quoting. Set it in the environment instead —
  `LLAMA_ARG_CHAT_TEMPLATE_KWARGS` — which llama-server reads and `bench.py`
  records into the result JSON under `backend.server_env`, so the one condition
  that dominates the result is not silently lost.
- **No judge endpoint is not a failure.** ALPACA and MT-Bench still *run*; they
  stay unscored, and the Mean then covers five benchmarks instead of seven. The
  JSON's `composite.included` says which. You can score them later with **zero
  GPU** from the saved transcripts: `python scripts/bench/judge-panel.py build`,
  then `score`, then `compare`.
- **There is no model downloader in this repo and no HF-token plumbing.** The
  `.gguf` has to be on disk already, at the path you paste. A gated repo passes
  the interview's access check and then fails at download time.

---

### One benchmark, not seven — the subset run

Runs one or two datasets instead of the suite. Reach for it when you are
escalating a suspicious n=25 cell to n=200, or when you have forty minutes
rather than eight hours. **Cost: samples × datasets × (cap ÷ tok/s)** — roughly
30 minutes for 10 samples × 7 datasets at ~25 s/prompt, so one dataset at n=200
is the same order.

```
Read AGENTS.md, then skills/field-guide/SKILL.md.

Subset benchmark run on an already-locked recipe. No sweeps, no new stages.

  slug:          <SLUG>
  model file:    <ABSOLUTE PATH TO THE .gguf>
  window (-c):   <CTX>
  server flags:  <SERVER FLAGS>
  datasets:      <GSM8K>     (choose from: GSM8K, MATH-500, HumanEval, MBPP,
                              ALPACA, MeetingBank, MT-Bench, GPQA-Diamond)
  samples:       <200>
  cap:           <4096>
  why I am doing this: <escalating a suspicious n=25 cell / smoke test / ...>

Run:

  python scripts/bench/bench.py --model <ABSOLUTE PATH TO THE .gguf> \
    --datasets <DATASETS> --samples <SAMPLES> --max-tokens <CAP> \
    --seed 42 --greedy --score --ctx <CTX> --server-args "<SERVER FLAGS>"

Then write this into campaign.md, and into any table this run feeds, in these
words: "This run scored <DATASETS> only. Its Mean is a composite index over
that set and is NOT comparable with a rule-21 Mean." Do not place a subset Mean
in a column beside a full-suite Mean.

Do not ask me questions; rule 27 closed the interview.
```

**What a first-timer gets wrong here.**

- **A subset breaks the composite Mean's comparability, and the tool will not
  stop you.** The Mean is a composite index over whatever was scored — the
  result JSON's `composite.included` names the exact set — so a subset produces
  a perfectly real number that is simply not the same number. Two Means compare
  only when their scored sets *and* their suite hashes match. That is why the
  sentence above is part of the template rather than advice underneath it.
- **GPQA-Diamond is not one of rule 21's seven.** It is the eighth dataset this
  repo ships, and scoring it into a run you then call a rule-21 Mean voids the
  comparison. Two ways to trip over it: adding `--datasets ...,GPQA-Diamond` to a
  `--rule21` run, and — the quieter one — running `bench.py` with **no**
  `--datasets` at all, because the non-`--rule21` default list in `bench.py` is
  all eight names, GPQA included. Name your datasets explicitly, always.
- A single n=25 cell is a smoke test, ±~16 points: it detects a ~20-point
  collapse and nothing finer. Escalate to n=200 on the one dataset before the
  cell becomes a claim. That is what this template is *for*.
- If a run stopped early, its prefix is not a sample — several of these files are
  subject-ordered. `--offset <N>` skips the first N rows before selecting, which
  is how you run the complement of the prefix instead of re-running everything.

---

### A hard stop at a given time — the rented machine

Runs a sweep under an agent-held clock so nothing is in flight when the box goes
away. Reach for it whenever the machine has an expiry: 8 working hours booked,
overrun possible, hard cutoff. **Cost: whatever fits.** The point of the template
is that an overrun costs one arm, not the campaign.

```
Read AGENTS.md, then skills/field-guide/SKILL.md.

HARD DEADLINE RUN. This machine goes away at <CUTOFF, e.g. 2026-09-02 18:00
local> and does not come back. It is now <START TIME>.

  slug:      <SLUG>
  arm file:  scripts/arms/<ARMFILE>.json
  cutoff:    <CUTOFF>
  margin:    <20 minutes>   (stop STARTING arms this long before the cutoff)

scripts/arms.py has NO deadline flag. You hold the clock. Do this:

1. Cost the plan without touching the GPU:
     python scripts/arms.py --arms scripts/arms/<ARMFILE>.json --list
     python scripts/arms.py --arms scripts/arms/<ARMFILE>.json --slug <SLUG> --dry-run
   --list resolves no paths and runs anywhere. --dry-run prints every arm, its
   resolved model path, its full argv and every probe, and is hard-wired to
   refuse any launch. Write down the arm ids in the order the plan prints them.

2. Confirm the card is free:
     python scripts/bench/gpu_lock.py status

3. Run ONE arm. Then check the clock. Then decide. Repeat, in the plan's order:
     python scripts/arms.py --arms scripts/arms/<ARMFILE>.json --slug <SLUG> \
       --only <ARM ID> --resume
   After each arm, record its wall time in campaign.md, and start the next one
   ONLY if now + that wall time + <margin> is still before <cutoff>. When it is
   not, stop starting arms - do not gamble the last one.
   --resume makes every one of these invocations cheap: an arm the ledger
   already records complete is skipped with a printed reason, not repeated.

4. At the cutoff, whatever state you are in:
   - append to results/<SLUG>/campaign.md: the cutoff, the arm ids that
     completed, the arm ids never started, and the ledger path;
   - checkpoint commit results/<SLUG>/ ;
   - publish only what completed. An arm that did not run is reported as not
     run - never interpolated from its neighbours.

Do not ask me questions; rule 27 closed the interview. Record assumptions in
campaign.md and continue.
```

**When the cutoff arrives mid-arm.**

- **Ctrl-C in the foreground is safe, and it is the right move.** `arms.py` stops
  the server in a `finally` block, waits for the port to actually free, and
  releases the GPU lock on the way out. Every probe already recorded is in the
  ledger, fsynced as it returned. You lose the arm in flight and nothing else,
  and `--resume` reruns exactly that one.
- **A plain `kill` on a detached run is not safe on Linux.** SIGTERM ends the
  Python process without running its cleanup, and on POSIX there is no job object
  holding the child, so `llama-server` survives with the model resident and the
  next run starts on top of it. (Windows differs: `gpu_lock` puts the child in a
  job object with KILL_ON_JOB_CLOSE, so it dies with its parent.) Either way the
  recovery is the same two commands:
  `python scripts/bench/gpu_lock.py status`, then `... kill`.
- `--only` filters the file to one arm, so the ledger's `order` and `pos` fields
  record a one-arm group instead of the sweep's real order. With the five arm
  files this repo ships that changes no measurement — every one of them is
  `repeat 1`, so a single pass in file order is exactly what a full run would
  have done. If you have edited a file to `repeat 2` or more, note in
  `campaign.md` that the order was operator-controlled, because rule 30's
  alternation is the thing you gave up.
- Do not try to squeeze a benchmark suite into the tail of the booking. A
  `--rule21` arm is 4–8 h on a 24 GB card and `bench.py` has no `--resume`.

---

### Handover, part 1 — what the DEPARTING shift types

Leaves the campaign in a state a stranger can pick up cold. Reach for it at the
end of a shift, before a timezone handoff, or any time you are about to stop
being the person watching. **No GPU, about ten minutes.**

```
Read AGENTS.md, then skills/field-guide/SKILL.md.

END OF SHIFT. I am handing this campaign to <WHO / WHICH TIMEZONE>, who picks
it up on <THE SAME MACHINE / A DIFFERENT MACHINE: <DESCRIBE IT>>. Do not start
any new GPU work. Leave it findable.

  slug: <SLUG>

1. Stop cleanly. If a sweep is running in the foreground, Ctrl-C it - that is
   safe. Then:
     python scripts/bench/gpu_lock.py status
   Nothing should hold the lock and no server should be live. If one is:
     python scripts/bench/gpu_lock.py kill

2. Read results/<SLUG>/work/heartbeat.json and quote it into the log. It names
   the arm in flight, the probe, the ledger path, the pid, the done/total
   count, and a state of running / ok / arm_failed / finished.

3. Append a dated "HANDOVER" section to results/<SLUG>/campaign.md holding:
   - the stage in flight and the exact command that was running (its argv is
     recorded on the FIRST line of the ledger, the sweep_start record - read it
     rather than reconstructing it from memory);
   - arm ids complete and arm ids not started, from
     results/<SLUG>/data/arms/<ARMFILE STEM>.jsonl;
   - the RECIPE LOCK still in force, or the words "no RECIPE LOCK yet - Stage 5
     has not run", which tells the next shift they may not start expensive work;
   - anything the next shift must NOT do (an arm file you edited, a port that is
     taken, a dataset still downloading);
   - the ONE next command, spelled out in full, no abbreviation.

4. Move anything bench.py produced out of scripts/bench/results/ into
   results/<SLUG>/data/. That directory is gitignored and does not travel.

5. Checkpoint commit results/<SLUG>/ and push if there is a remote. The commit
   is what the next shift trusts: the resume protocol in AGENTS.md treats the
   highest checkpoint commit as ground truth and anything campaign.md claims
   past it as "in flight when the session died".

Do not start another arm to fill the time left in my shift.
```

**The hard rule, and it is the whole reason this template exists.**

- **One arm FILE is the smallest unit that may cross a machine boundary.** Rule
  30 says arms are compared *inside* one sweep. Run half a sweep's arms on box A
  and half on box B and the arms within that sweep are no longer comparable to
  each other — which was the sweep's entire purpose. Same machine, different
  human, mid-sweep: fine, resume it. **Different box: finish the arm file where
  it started, or restart the whole file on the new box.** Never split one.
- `machine.json` describes the box and never travels; `campaign.json` describes
  the campaign and does. On a new machine the arriving shift re-runs
  `detect-machine.py`, which **keeps the previous profile beside the new one** as
  `machine-<timestamp>.json` rather than overwriting it. That pair is the
  evidence that the campaign moved, and the report has to say it did.
- `*.log` is gitignored, so server logs do **not** survive the commit. If a log
  matters to the handover — an arm that died with a server error — paste its tail
  into `campaign.md`. The ledger already carries `server_log_tail` on a failed
  arm's record, so check there first.

---

### Handover, part 2 — what the ARRIVING shift types

The first thing typed at the start of a shift, before touching anything.
**No GPU, about five minutes.**

```
Read AGENTS.md, then skills/field-guide/SKILL.md.

I am picking up a campaign somebody else started. Do NOT re-interview me and
do NOT start a new campaign.

  slug: <SLUG>
  I am on: <THE SAME MACHINE AS THE LAST SHIFT / A DIFFERENT MACHINE>

1. Read results/<SLUG>/campaign.md end to end. Then:
     git log --oneline
     cat results/<SLUG>/work/heartbeat.json
   The highest checkpoint commit is ground truth; anything campaign.md claims
   past it was in flight when the last session ended. If the log uses the old
   Phase 0-11 numbering, map it with SKILL.md's "Old numbering -> stages" table
   and record the mapping you used in your first entry.

2. Confirm the box is ready and idle:
     python scripts/lib/paths.py
     python scripts/bench/gpu_lock.py status
   If a server is live, or the lock is held by a pid that is gone:
     python scripts/bench/gpu_lock.py kill

3. If I am on a DIFFERENT MACHINE:
     python scripts/detect-machine.py --slug <SLUG> --desktop-state "<...>"
   and then respect the boundary: do NOT continue a sweep that started on the
   other box. Finish it there, or restart that whole arm file here. Record in
   campaign.md which arms were measured on which machine.

4. Check the RECIPE LOCK before anything expensive. No dated RECIPE LOCK
   section in campaign.md means Stage 5 never ran, and rule 25 forbids starting
   Stage 6 above it. Write the lock first.

5. Append a dated "shift start" line to campaign.md, then run the one next
   command the handover named - adding --resume if it is an arms.py command.

Rule 27: the interview is closed. Resolve uncertainty from the campaign.md
record, then the measured default, then record the assumption and proceed.
```

**What a first-timer gets wrong here.**

- `results/qwen38-27b-blind/` ships as the **closed worked example**. It is not
  your campaign, it is not resumable, and nothing may be appended to it. If it is
  the only thing under `results/`, you are starting fresh, not arriving.
- `--resume` **refuses to skip a unit whose arm spec changed** since it ran —
  every ledger line carries a 12-character spec hash — and prints
  `the arm SPEC CHANGED (<old> -> <new>) - rerunning`. If the departing shift
  edited the arm file, that message is the guard doing its job, not a bug.
- An arm the ledger records as **failed** is skipped rather than retried:
  `SKIPPED, the ledger records it FAILED (delete that line to retry it)`. Read
  that record's `server_log_tail` and understand the failure before you delete
  anything.

---

### Resume after a crash or a lost session

Short and mechanical. Reach for it when the session died, the box rebooted, or
you came back to a terminal that is no longer there. **No GPU until step 4; the
crash costs you the arm that was in flight, nothing else.**

```
Read AGENTS.md, then skills/field-guide/SKILL.md.

The previous session died. Resume it. Do not re-interview and do not start a
second campaign.

  slug: <SLUG>

1. Read, in this order:
     results/<SLUG>/campaign.md            (end to end)
     git log --oneline                     (highest checkpoint = ground truth)
     results/<SLUG>/work/heartbeat.json    (arm, probe, ledger, pid, done/total, state)
   Then the FIRST line of the ledger it names - the sweep_start record - which
   carries the exact argv, the arm file path and the order mode that ran.

2. Make sure nothing survived the crash and is still holding the card:
     python scripts/bench/gpu_lock.py status
     python scripts/bench/gpu_lock.py kill   # only if it names a holder or a live server

3. Append a dated "resumed after session loss" line to campaign.md, naming the
   arm the heartbeat was on.

4. Re-run the SAME command, with --resume:
     python scripts/arms.py --arms scripts/arms/<ARMFILE>.json --slug <SLUG> --resume
   It prints every unit it skips and why.

WHAT IS LOST - check each of these before concluding anything is gone:
  - arms.py: nothing but the in-flight arm. Every probe was appended and
    fsynced to results/<SLUG>/data/arms/<STEM>.jsonl as it returned.
  - bench.py: it has NO --resume. But it rewrites its result JSON after every
    dataset, and appends every completed prompt as it goes to
    scripts/bench/results/<LABEL>_<STAMP>.json.partial.jsonl. If even that is
    missing and you still have the console log, rebuild from it:
      python scripts/bench/reconstruct-from-log.py --log <LOG> --dataset <NAME> --out <PATH>
    The artefact it writes is marked reconstructed and names the log it came
    from, so it is never mistaken for one the harness wrote itself.
  - Anything outside arms.py and bench.py may not resume at all. Check, do not
    assume.

Rule 27: do not ask me questions. Record assumptions in campaign.md.
```

**What a first-timer gets wrong here.**

- If the sweep aborts instantly with `PORT ... IS ALREADY IN USE, before this arm
  launched anything`, that is the guard working, not a failure. Something was
  listening and would have answered every probe under the *wrong* flags, which is
  unrecoverable after the fact. `gpu_lock.py kill`, then rerun with `--resume`.
- **An idle GPU with arms still pending is an alarm, not a rest.** Check
  `heartbeat.json`'s modification time. That exact shape — dead runner, dead
  watcher, silence reading as "busy" — cost the reference campaign two GPU hours.
- Resuming into Stage 6 with no dated RECIPE LOCK in `campaign.md` means Stage 5
  never ran. Go back and write it before spending hours (rule 25).

---

### Running it unattended overnight

Sets up a run that survives a disconnected SSH session, and says exactly what to
look at in the morning. **Cost: the sweep's own cost; the setup is minutes and
saves the night.**

```
Read AGENTS.md, then skills/field-guide/SKILL.md.

Unattended overnight run. My session will disconnect. Set it up so the run does
not die with it, then tell me exactly what to check in the morning.

  slug:     <SLUG>
  arm file: scripts/arms/<ARMFILE>.json
  platform: <LINUX / WINDOWS>

BEFORE detaching - all cheap, all no-GPU:
  python scripts/verify/probe-smoke-test.py --fail
  python scripts/lib/paths.py
  python scripts/arms.py --arms scripts/arms/<ARMFILE>.json --slug <SLUG> --dry-run
  python scripts/bench/gpu_lock.py status
Parsing is not loading. A script that parses is not a script that runs, and
finding that out at 02:00 costs the whole night.

DETACH at the OS level, not as a harness background task - those can be killed
near ten minutes:

  Linux / macOS:
    setsid nohup python scripts/arms.py --arms scripts/arms/<ARMFILE>.json \
      --slug <SLUG> --resume > results/<SLUG>/work/overnight.log 2>&1 &
    echo $! > results/<SLUG>/work/overnight.pid

  Windows (PowerShell; the backtick is the line continuation):
    Start-Process powershell -WindowStyle Hidden `
      -ArgumentList "-NoProfile","-ExecutionPolicy","Bypass","-Command", `
        "python scripts\arms.py --arms scripts\arms\<ARMFILE>.json --slug <SLUG> --resume" `
      -RedirectStandardOutput results\<SLUG>\work\overnight.log `
      -RedirectStandardError  results\<SLUG>\work\overnight.err

BEFORE YOU GO, write into campaign.md: the exact command, the log path, the
ledger path, and the arm ids you expect to be finished by morning.

IN THE MORNING, in this order:
  cat results/<SLUG>/work/heartbeat.json        # state + done/total
  tail -40 results/<SLUG>/work/overnight.log
  wc -l results/<SLUG>/data/arms/<STEM>.jsonl   # one line per probe
  python scripts/bench/gpu_lock.py status       # the card should be free
Success is "state": "finished" in the heartbeat AND a sweep_end line at the end
of the ledger. Anything else: read the last ledger line, then re-run the same
command with --resume.

Rule 27: do not ask me questions overnight. Record assumptions in campaign.md
and keep going.
```

**What a first-timer gets wrong here.**

- **The heartbeat is rewritten per probe, not on a timer.** A probe that
  legitimately runs for twenty minutes leaves a twenty-minute-old heartbeat, so
  any staleness alarm has to sit above your longest legitimate probe — and an
  uncapped effort probe can run a very long time. Its `state` field is one of
  `running`, `ok`, `arm_failed`, `finished`.
- `*.log` is gitignored: the overnight log is a working file, not a record. What
  the report cites is the ledger, and the ledger *is* tracked. The per-arm server
  log lives at `results/<SLUG>/work/arms/<STEM>/<ARM ID>-rep1.log`; `bench.py`'s
  server log is `scripts/bench/results/llama-server.log` and is **truncated on
  every run**, so copy it before starting the next one if it matters.
- **Killing the detached run: do not `kill` the pid and walk away** (Linux).
  SIGTERM ends Python without running its cleanup and POSIX has no job object, so
  `llama-server` keeps the model resident and the next run loads on top of it.
  Use `python scripts/bench/gpu_lock.py kill`, which stops the servers and clears
  a stale lock in one command. On Windows the job object kills the child with its
  parent, so this bites less — but the same command is still the right cleanup.
- **Windows quoting.** The `-Command` form above is fine because the command it
  wraps contains no quotes of its own. The moment yours does — a `--server-args
  "..."`, a `--chat-template-kwargs` JSON — put the command in a `.ps1`, launch
  it with `-File`, and parse-check it *before* detaching:
  `[scriptblock]::Create((Get-Content -Raw .\run.ps1)) | Out-Null` throws on a
  parse error. A detached script that never parsed dies instantly and leaves an
  empty log.
- **Bootstrap is a human step; do it before bed, not after.** `scripts/setup.sh`
  (POSIX) / `scripts/setup.ps1` (Windows). On Linux + NVIDIA there are no official
  CUDA binaries, so setup **exits 3** rather than quietly installing a Vulkan
  build that would move every throughput number for reasons that have nothing to
  do with the model. `./scripts/setup.sh --cuda` builds from source (~4 min
  measured on an RTX 3090) but needs
  `sudo apt-get install -y nvidia-cuda-toolkit cmake build-essential git` first —
  and **the agent cannot sudo**. Same for the weights: there is no downloader
  script here, so the `.gguf` must be on disk before you detach.

---

## Beyond the basics

Everything above gets a campaign running. This section is for the day after: how
to find out what a run costs *before* you pay for it, how to make energy the
product instead of an appendix, how to measure a model's eyes without fooling
yourself, what you may honestly publish about a card you do not own — and the
six things that actually break on a first run.

Every template still opens with the same line. Claude Code auto-loads
`CLAUDE.md`, opencode auto-loads `AGENTS.md`, Pi loads neither; that one line is
what makes the rest portable.

---

### Price a sweep before you run it

Both preview flags are free and neither touches the GPU. `--list` resolves no
paths at all, so it runs on a machine where nothing is installed yet; `--dry-run`
resolves every binary and weight file and prints the exact `argv` each arm will
launch. Reach for this before any sweep you have not run before, and always
before an arm file you edited. Cost: seconds.

```
Read AGENTS.md, then skills/field-guide/SKILL.md.

Do not touch the GPU. I want a cost preview of <ARM FILE, e.g. scripts/arms/ctx-ceiling.json>
before I commit to it. Run exactly these two commands and report their output:

  python scripts/arms.py --arms <ARM FILE> --list
  python scripts/arms.py --arms <ARM FILE> --slug <SLUG> --dry-run

From --list tell me: the sweep name, the arm count, the sweep GROUPS (rule 30 —
arms are only comparable inside one group), the order mode, and the total probe
count.

From --dry-run tell me: the ledger path, the heartbeat path, how many frozen
prompts reproduced, and every UNRESOLVED or WARNING line. An UNRESOLVED arm is a
sweep that would have died partway through, so name each one and what is missing.

Then price it: per arm, one server load plus (probes x repeat) generations at its
n_predict. Convert to wall clock using a decode rate ALREADY MEASURED on this
machine, and name the run it came from. If no such number exists yet, say so and
give me the range explicitly labeled as derived arithmetic — rule 1 has three
categories (measured, cited, labeled-derived) and no fourth.

Write the estimate into results/<SLUG>/campaign.md under today's date, then STOP.
Do not run the sweep.
```

**Pass `--slug` even for a dry run.** Without it the slug falls back to "the one
campaign under `results/`", which on a fresh clone is `qwen38-27b-blind` — the
closed worked example. Verified on this repo: `--dry-run` with no `--slug`
printed its ledger as `results\qwen38-27b-blind\data\arms\acceptance.jsonl`. That
example must never be continued or appended to.

**The five arm files, so you know what you are pricing:** `ctx-ceiling.json`
(25 arms, two groups `q4km-ceiling` / `iq4xs-ceiling`, `order: fixed` because a
ladder's walk depends on its order), `effort-sweep.json` (11 arms, three groups),
`spec-sweep.json` (6, one group), `acceptance.json` (2), `depth-series.json` (2,
and its 7 frozen prompt hashes are re-rendered and checked before a single server
starts — rule 23).

**`--dry-run` cannot start anything by accident.** It sets the gpu_lock dry-run
environment variable, under which any launch raises rather than taking the card.
If that variable is already set in your shell and you *didn't* pass `--dry-run`,
arms.py refuses to start rather than failing eight arms in.

A 25-arm ceiling sweep is also the case for holding the clock yourself: arms.py
has **no deadline flag**, so a hard stop means running one arm at a time with
`--only <arm-id> --resume` and checking the time before each invocation.

---

### Prove every probe still starts — four seconds, no GPU

Parsing is not loading. A syntax check proves the text is Python; it does not
prove the module's top level runs, that its imports resolve, or that argparse can
build its own help. Each of those has failed in this repo at least once — one
probe had its provenance block land *above* `import sys` and would have died on
its first line after a human committed an hour of GPU time to it. Run this on any
fresh clone, and again after `setup`. Cost: seconds, no GPU, no model.

```
Read AGENTS.md, then skills/field-guide/SKILL.md.

Before we spend any GPU time on this machine, run the three cheap pre-checks and
report each verbatim:

  python scripts/lib/paths.py
  python scripts/bench/gpu_lock.py status
  python scripts/verify/probe-smoke-test.py

paths.py is the readiness check: it prints what resolves and why — repo root,
campaign.json, machine.json, llama-server / llama-perplexity / llama-tokenize,
board VRAM and desktop reserve. Anything printed as absent or NOT FOUND is a job
that would fail later, so list those first.

For the smoke test, sort every FAIL into exactly one bucket and give me the counts:
  (a) ENVIRONMENT — the failure names a llama.cpp binary path, a dataset, or a
      module this box has not installed yet. The probe is fine; setup has not run.
  (b) DEFECT — the probe cannot start for its own reasons: a syntax error, an
      import that will never resolve, an argparse that cannot build --help, or
      work done at module import time.

Then run setup, re-run the smoke test, and diff the two FAIL lists. Anything
still in bucket (b) is a probe I must not schedule GPU time against. Append both
lists and the diff to results/<SLUG>/campaign.md.
```

**A big red number on a fresh clone is normal — read it before believing it.**
Measured on this repo with llama.cpp not yet built: **18 of 74 failed, and 10 of
those 18 ended in the `llama-server` path** — bucket (a), every one. The rest were
genuine bucket-(b) findings (a script whose `--help` raises `KeyError`, one that
needs a positional argument, an import that does not resolve). The whole point of
the two buckets is that "18 FAILED" and "18 broken probes" are not the same
sentence.

`--fail` makes it exit non-zero, for a hook or CI. It checks only whether a probe
would *start* — not whether it measures the right thing, and not whether its
conditions are honest. It is a smoke test and claims nothing else.

**It takes no GPU** — the import stage runs each module in a subprocess with the
gpu_lock dry-run variable set, so a probe that regressed into launching something
raises instead. It is not, however, guaranteed side-effect-free on disk: a module
that does work at import time does that work here too. Observed on this repo
2026-08-29, the run left one new untracked PNG under
`results/qwen38-27b-blind/figures/`. Check `git status` after the run and delete
anything it created; a module that writes a file merely by being imported is
itself a bucket-(b) finding worth recording.

---

### A campaign where energy is the point

Rule 24, quoted because it is the whole discipline: **every watt carries its
instrumentation tier and every joule its phase; energy is measured or it is
absent — TDP is not a measurement.** A campaign that cannot read a counter writes
"unmeasured", never an estimate. Read `scripts/power/README.md` before Stage 6e.
The expensive mistake this template prevents is re-running hours of GPU work
later "for the watts": start the logger at Stage 0 and every later stage becomes
an energy arm for free.

```
Read AGENTS.md, then skills/field-guide/SKILL.md.
Then read scripts/power/README.md and METHODOLOGY rule 24 in full before you
touch anything. Energy is measured or it is absent; TDP is not a measurement.

Campaign: <MODEL HF URL>, slug <SLUG>. Energy is the deliverable I care about
most, so Stage 6e is the point of this campaign, not an appendix.

STAGE 0, before the first model load:
  - start the 500 ms power logger and leave it running for the entire campaign:
      Windows: .\scripts\power\sample-power.ps1 -Start -Csv results\<SLUG>\data\power\campaign-power.csv
      Linux:   the sampler is PowerShell — use the nvidia-smi loop in the next
               template instead, and record its pid in campaign.md
  - take the COLD, no-server idle baseline. Discard the first 60 s (a board still
    cooling from earlier work reads high — one reference log's first 10 samples
    averaged 58.0 W against a 33.2 W cold reading). Write it into campaign.md with
    its date and its tier label.
  - python scripts/power/attribute-power.py --selftest
    (synthetic data, no GPU, no server — it proves the integrator's arithmetic
    before any number depends on it)

STAGE 1: take the LOADED idle baseline — server up, model resident, answering
nothing — dated, in campaign.md. Every idle-subtracted figure downstream depends
on these two numbers, so a remembered constant is not acceptable.

THEN RUN THE CAMPAIGN NORMALLY. Every arms.py sweep is already an energy arm: its
per-probe ledger writes t_start_iso and label alongside the server's own timings,
which is exactly what the integrator's --events wants. After each sweep:

  python scripts/power/attribute-power.py \
    --power results/<SLUG>/data/power/campaign-power.csv \
    --events results/<SLUG>/data/arms/<ARM FILE STEM>.jsonl \
    --idle-w <THE MEASURED LOADED IDLE W> --drop-first \
    --json results/<SLUG>/data/power/<STEM>-energy.json

Do not re-run one GPU hour just for watts.

STAGE 6e DELIVERABLE — the per-axis J/token matrix, one row per arm, columns:
mean W | J/decode-token | J/prompt-token | tokens/kWh | EDP (J.s) | verdict.
Axes: quant, drafter (--spec-type off vs each tuned config), KV dtype (f16 vs
q8_0), --parallel (1 vs 2, aggregate), depth, effort level, token regime
(thinking vs answer). An axis we did not measure gets its own row reading "not
measured" — silence is the omission the rule already bans.

LABELS, non-negotiable: head every energy table with the tier —
"in-band GPU board power (NVML); PSU losses and PUE excluded". Never call it
system power, never divide an electricity bill by it, never inflate it by a
guessed PSU efficiency. Wh/answer is reported twice, gross AND idle-subtracted.
On a single-GPU box, E_comm is stated as "N/A — single GPU, no interconnect",
not omitted.

THE POWER CAP: nvidia-smi -pl <W> (3090 stock 350 W; Linux may need -pm 1 first)
needs an elevated shell. If you can elevate, sweep it (350/300/250/200 W) into
the same matrix. If you cannot, print the command and the stock cap and mark the
row "unmeasured on this machine (requires administrator)". Do not estimate it.
```

**Why `--drop-first` is not optional.** A request fired at a cold or idle board
runs at 900–990 MHz against 1,455 MHz settled. Both its wattage and its
throughput are low, so J/token comes out looking *better* than steady state —
an artifact, not an efficiency win. The logger records `clocks.sm`, `pstate` and
`utilization.gpu` precisely so you can prove a low-watt sample was a ramping
board. The same trap runs the other way for short probes: 10 s recipe probes read
277–287 W where multi-minute runs sustained ~344 W.

**Check `cov%` on every row.** A logger restart or a sleep leaves a hole; the
integrator credits any gap at most `--max-gap` seconds (default 2 s) and reports
the rest as excluded, so coverage below 100% is visible rather than fabricated
energy. Below `--min-coverage` (default 0.9) you get a warning — a mean W over a
half-logged window is a lie.

**If you use `capture-request.ps1` instead of the arms ledger**, note
`-CachePrompt` is OFF by default on purpose: llama-server's prompt cache defaults
to *on*, and a cached prefill costs almost no energy, which silently destroys any
J/prompt-token number the second time you send the same prompt.

---

### Energy on Linux: the sampler is PowerShell, the integrator is not

`scripts/power/sample-power.ps1` and `capture-request.ps1` are PowerShell and do
not run on Linux. `attribute-power.py` is stdlib Python and runs everywhere —
and since `arms.py`'s ledger already carries the six fields the join needs
(`t_start_iso`, `prompt_ms`, `predicted_ms`, `prompt_n`, `predicted_n`, `label`),
the only piece a Linux box actually has to replace is the CSV logger.

```
Read AGENTS.md, then skills/field-guide/SKILL.md, then scripts/power/README.md.

This is Linux, so the PowerShell sampler is unavailable. Replace ONLY the logger,
keep everything else.

1. Start the logger yourself, with the same columns and cadence the PowerShell
   one uses, and record its pid in campaign.md:

     nvidia-smi \
       --query-gpu=timestamp,power.draw,power.draw.instant,clocks.sm,clocks.mem,utilization.gpu,utilization.memory,memory.used,memory.reserved,temperature.gpu,pstate \
       --format=csv,nounits -lms 500 \
       -f results/<SLUG>/data/power/campaign-power.csv &

   Note in campaign.md that this is a hand-started logger: scripts/power's -Stop
   deliberately refuses to kill a logger it did not start, so stopping this one
   is `kill <pid>` and nothing else.

2. Everything downstream is unchanged:
     python scripts/power/attribute-power.py --selftest
     python scripts/power/attribute-power.py \
       --power results/<SLUG>/data/power/campaign-power.csv \
       --events results/<SLUG>/data/arms/<STEM>.jsonl \
       --idle-w <MEASURED LOADED IDLE> --drop-first --json <out.json>

3. If this machine is NOT NVIDIA, name the counter and its scope before using it:
   Intel Arc / iGPU on Linux = RAPL (/sys/class/powercap/intel-rapl/*/energy_uj,
   differenced over the window: J = delta_uJ/1e6, kWh = J/3.6e6) — that is PACKAGE
   scope, not board, and the table must say so. On Windows, HWiNFO64 sensor
   logging to CSV. Apple Silicon: sudo powermetrics --samplers gpu_power,cpu_power
   -i 1000. If no counter is readable without installing something on a machine
   that may be borrowed, mark the energy work UNMEASURED — do not estimate from
   TDP, and do not silently drop the section.
```

The integrator is deliberately tolerant of what a hand-rolled logger produces: it
reads both `--format=csv,nounits` and the older unit-suffixed style, with or
without a header row, drops `[N/A]` samples, strips the UTF-8 BOM PowerShell 5.1
writes, and merges and de-duplicates multiple `--power` files.

---

### A screenshot-loop campaign — and the hallucinated-sight hunt

Rule 19: **agents drop images silently unless capability is declared, and
hallucinated "sight" is the worst outcome — it must be hunted explicitly.** Rule
18: image cost is resolution, not file size. If your answer to interview item 3
is "vision / screenshot loops", say so in the first round — it is what turns on
Stage 6c, and after Stage 0 closes the campaign cannot come back and ask.

```
Read AGENTS.md, then skills/field-guide/SKILL.md.
Read METHODOLOGY rules 18 and 19 before Stage 6c, and read
reference/failure-library.md's "Agents that silently drop images" entry.

Model: <MODEL HF URL — one with an mmproj/vision projector>. Slug: <SLUG>.
Machine: <GPU, VRAM>. Use case, interview item 3: VISION — screenshot loops. I
paste screenshots at <RESOLUTION, e.g. 2560x1440> into <AGENT, e.g. opencode> and
ask it what is wrong with the page. Time budget: <overnight | multi-day>.
Coding agents to test (interview item 7): <LIST, or "none">.

What I need out of Stage 6c, in this order:

1. THE PROJECTOR PAIR (Stage 2): VRAM with the mmproj loaded and without, as an
   on/off pair, because it comes straight off my context ceiling.

2. THE RESOLUTION -> TOKEN MAP: sweep --image-min-tokens / --image-max-tokens and
   measure prompt_tokens for a REAL screenshot at my resolution, not a synthetic
   square. Give me the token cost per resolution so I can budget a window.

3. AN ACUITY MEASUREMENT WITH A CONTROL. scripts/vision/make-detail-target.py
   generates a 2560x1440 target whose every answer is known exactly, and
   scripts/vision/entry6-image-budget.py runs the three arms — FULL (the shipped
   budget), REDUCED (--image-max-tokens 1024), and BLIND (no image attached).
   BLIND is not optional: it is the control that separates reading from guessing,
   and it should score at or near zero. Report the coarse questions (96/54 px
   type) separately from the fine ones (12-15 px): coarse holds + fine collapses
   is a RESOLUTION result; both collapse is a PLUMBING result and must not be
   published as acuity.

4. THE CRITIQUE LOOP, only if a browser already exists. Detect in this order:
   chrome / google-chrome / chromium on PATH; then stock Edge, which needs no
   install on Windows (msedge --headless=new --disable-gpu --screenshot=shot.png
   --window-size=1920,1080 file:///...); then Playwright or Puppeteer if either is
   already present. If none exists, DO NOT install a browser on this machine and
   DO NOT fake the loop — run the still-valid parts and record in campaign.md and
   in the report that the critique loop was not measured here, and why.

5. THE AGENT-ATTACH MATRIX, on the locked vision recipe, for every agent I named.
   The probe question must be UNANSWERABLE without the pixels. Verdicts:
   PASS (names real content) / FAIL-honest (says it cannot see an image) /
   FAIL-hallucinated (confidently describes content that is not there). Flag every
   hallucination loudly — it is the worst outcome, not a middling one. If a CLI
   flag errors, verify it against the installed version's --help and document the
   delta; never publish a FAIL produced by an invocation you invented.
```

**The capability gates, because "configured" is not "declared".** OpenCode needs
`"attachment": true` **and** `"modalities": {"input": ["text","image"]}` on the
model — a bare model entry reads the PNG as raw bytes (verified v1.18.21, issue
#15728). Qwen Code needs the model in `settings.json` `modelProviders` with
`capabilities: {vision: true}`; an env-vars-only setup appears to work and
silently drops images. aider needs `supports_vision: true` in
`.aider.model.metadata.json`. Pi's provider `models.json` must list `"image"` in
`input`. The DeepSeek Harness needs `input: [text, image]` in **both** the
provider block and the `agent-default-model` routing block, or you get
`MISSING_CREDENTIAL`, and it needs a client-side `maxTokens` or long replies
truncate.

**No mmproj, no Stage 6c.** The interview resolves the repo's file listing and
tells you whether a projector exists; if there is none, vision is reported as not
applicable rather than attempted.

---

### Numbers for a card you do not have

You measured one card. Readers have others. Rule 10 lets you scale decode
arithmetically — `decode ≈ GB/s ÷ file GB × 0.7` — and rule 1 decides what you
are allowed to call the result: measured, cited, or labeled-derived. There is no
fourth category, and a guess in a monospace block reads exactly like a
measurement, which is why an unrun config's *first* line is its verification
status.

```
Read AGENTS.md, then skills/field-guide/SKILL.md.
Read METHODOLOGY rule 10 and rule 1 (all three sub-clauses) and
templates/REPORT-SPEC.md section 7 before writing anything.

The campaign at results/<SLUG>/ measured <CARD I HAVE, e.g. RTX 3090, 24 GB,
936 GB/s>. Readers will ask about <CARD I DO NOT HAVE, e.g. RTX 4070 Ti SUPER,
16 GB>. Produce the "other hardware" section, honestly.

1. RE-DERIVE THE EFFICIENCY CONSTANT from one measured point on THIS machine,
   per file format — do not reuse 0.7 as a law. The reference campaign measured
   ~0.70 for K-quants and ~0.65 for IQ formats; whatever you derive, show the
   measured point it came from.

2. SCALE DECODE, NOT PREFILL. Prefill is compute-bound; bandwidth / file size
   does not scale it. If any recommendation in this report is for agentic or
   long-context work, publish a PREFILL-SCALED row beside the decode row, and
   state the prompt:completion ratio behind every wall-clock estimate.

3. COVER THE WHOLE ROSTER, not just the card I asked about — REPORT-SPEC section
   7 makes it a rule: NVIDIA 24-32 GB (3090/4090/5090), 16 GB
   (5080/4080/4070 Ti S/5060 Ti) and 12 GB (3060/5070) classes; DGX Spark (GB10,
   128 GB unified, 273 GB/s); Intel Arc Pro B70 (32 GB, 608 GB/s) and B50 (16 GB,
   224 GB/s); and the Arc B390-class iGPU with its RAM-channel caveat stated
   inline. Verify each card's bandwidth and VRAM against current online sources at
   campaign time and cite them — specs drift. A card this machine cannot represent
   stays as a derived row; it is never dropped.

4. MARK EVERY ROW measured or derived-by-bandwidth. A derived number inherits its
   WEAKEST input's grade, and its derivation DEPTH is counted: name every borrowed
   constant it passes through. If a row assumes a drafter speed-up, or a backend
   nobody ran, say so in the row.

5. ANY RECIPE FOR A CARD WE DID NOT RUN gets, as the block's FIRST line:
       UNVERIFIED — DERIVED CONFIG
   not a trailing comment. Inside it, mark each flag measured-here or
   carried-over-unverified. A KV-quant verdict verified on CUDA is not verified on
   the backend it was pasted onto.

6. Anything that cannot be scaled honestly — VRAM fit is arithmetic, but
   acceptance rate and desktop slack are not — says "not derivable from this
   campaign" rather than getting a number.
```

Note what this template does **not** let you do: publish a second campaign on a
second machine and compare absolutes against the first. Rule 30 — compare arms
*inside* one sweep, never across sweeps, and never across campaigns. If you want
two cards compared as measurements, they are two rows of one sweep on one
machine, not two reports.

---

### Troubleshooting: six failures, symptom then fix

**1. `setup.sh` exits 3 on an NVIDIA box: "the backend on offer is 'vulkan', not CUDA".**
Working as designed — there are no official Linux CUDA binaries, and a silent
Vulkan build would move every throughput, acceptance and VRAM number for a reason
that has nothing to do with the model. Fix: `sudo apt-get install -y
nvidia-cuda-toolkit cmake build-essential git` (the sudo is a human step, the
agent cannot do it), then `./scripts/setup.sh --cuda` — measured at ~4 min on an
RTX 3090; the script's own message quotes 10–25 min as typical, so budget for the
wider range on a slower box. To take a non-comparable backend deliberately and on
the record:
`MEASURED_INFERENCE_ALLOW_VULKAN=1 ./scripts/setup.sh`.

**2. `llama-server not found` — a probe or a dry run dies before it launches.**
The resolution chain is printed in the error, ending with `<repo>/bin/llama.cpp/`.
Fix: run `scripts/setup.sh` / `scripts/setup.ps1`, or point at an existing build
with `LLAMA_DIR=<dir>` or `LLAMA_SERVER=<file>` or `"llama_dir"` in
`results/<slug>/campaign.json`; `python scripts/lib/paths.py` confirms it
resolved. On Windows the message also flags a Linux ELF binary it deliberately
skipped, which is the usual cause on a dual-booted checkout.

**3. `machine.json absent` — paths.py says board and desktop are "unavailable".**
Stage 0 does not close until `campaign.json` **and** `machine.json` both exist,
and every VRAM budget in Stage 2 reads from it. Fix: `python
scripts/detect-machine.py --slug <slug>`, then re-run `python
scripts/lib/paths.py` and confirm `board` and `desktop` now print numbers.

**4. A gated HuggingFace repo that passed the interview fails at download time.**
There is no model downloader script and no HF-token plumbing in this repo: the
listing API succeeds on gated repos, so a listing is not proof of access, and by
Stage 1 the no-questions rule (rule 27) has locked the agent out of asking for a
token. Fix: prove access *inside* the interview with a range request on one
chosen file — `curl -sI -r 0-1023 <resolve-url>` must return 206/200, not
401/403 — and if it 401s, hand over the token in that same round and confirm it
works with `Authorization: Bearer <token>` before the interview closes.

**5. `probe-smoke-test.py` reports failures you did not cause.**
On a fresh clone before setup, most FAILs are environment, not defects — measured
here: 18 of 74, of which 10 named the missing `llama-server` binary. Fix: run it
once before setup and once after, diff the lists, and treat only what survives
setup as a real defect; a probe still failing on `--help` or on import is one you
must not schedule GPU time against.

**6. A sweep will not resume where you expected.**
Two different causes, two different messages. If the arm file changed since the
unit ran, resume prints `the arm SPEC CHANGED (<old> -> <new>) - rerunning` and
re-runs it — correct behaviour, because the recorded numbers describe a
configuration that no longer exists. If the ledger records the unit as FAILED,
resume prints `SKIPPED, the ledger records it FAILED` and moves on. Fix: for the
first, accept the rerun or restore the arm file byte-for-byte; for the second,
delete that ledger line in `results/<slug>/data/arms/<stem>.jsonl` to retry it.
`results/<slug>/work/heartbeat.json` names the arm that was in flight.

**Three more a first run hits, from `reference/failure-library.md`:**

- **20–35 t/s flat at every context size, dedicated VRAM pinned near full,
  shared GPU memory growing, no warning:** silent sysmem spill — the driver
  overflows to system RAM instead of refusing. Free the VRAM (browsers held 2–3 GB
  on the reference box); prevent it in NVIDIA Control Panel → Manage 3D Settings →
  Program Settings → llama-server.exe → CUDA — Sysmem Fallback Policy → **Prefer
  No Sysmem Fallback**, which turns a slow day into a startup OOM.
- **Decode fixed low at every window, GPU utilization 53–67%, survives a
  reboot:** the `-ngl` off-by-one — the output projection counts as layer n+1.
  Always `-ngl 99`.
- **The whole desktop hangs and only the power button ends it:** two or more
  llama-servers resident at once (host commit exhaustion; `Kernel-Power 41` with
  `BugcheckCode = 0` and no dump). Never launch a server with a bare
  `subprocess.Popen` / `Start-Process` — use `gpu_lock.serve()` or
  `Start-GuardedServer`; `python scripts/bench/gpu_lock.py status` names the
  holder and `... kill` clears it.

**And two habits that prevent most of the rest.** Ctrl-C mid-arm is safe — the
server is stopped and the ledger keeps every completed probe — but a detached run
killed with a plain `kill` orphans `llama-server` on Linux, so check
`gpu_lock.py status` before starting anything after a kill. And
`results/qwen38-27b-blind/` is the **closed** worked example: it is not resumable,
a new campaign must not continue it, and it is the slug `arms.py` will silently
default to if you forget `--slug`.

---

