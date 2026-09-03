# qwen35-9b-family — a comparison, not a field guide

Governed by `templates/COMPARISON-SPEC.md`, not `REPORT-SPEC.md`.

**ANCHOR: `Qwen/Qwen3.5-9B`**, the base every arm in this roster is defined
against. COMPARISON-SPEC: *"Prefer the base model as anchor when the roster is a
family."* Every sweep in this document, forever, includes it, and every
cross-sweep claim is published as a RATIO to the anchor measured in that same
sweep.

## 2026-09-02 — why this campaign exists

`results/ornith-1.5-9b-mtp/` measured Ornith-1.5-9B exhaustively over two days.
Every comparison it makes against Qwen3.5-9B is **cited, not measured** — the
vendor's published MMMU 78.4, Terminal-Bench 18.9, SWE-bench 53.2 — and that
campaign itself recorded that those baselines were produced *by Ornith*, the
vendor whose model they are the baseline for.

Rule 1 allows a cited number. Rule 30 does not allow a comparison built from
one: **arms compare only INSIDE one sweep.** So no legal Ornith-vs-Qwen3.5
claim existed anywhere in this repo, and this campaign is the sweep that makes
one possible.

## Roster and the file choice, which was the first trap

| arm | file | source | block_count | size |
|---|---|---|---|---|
| **Qwen3.5-9B** (anchor) | `Qwen3.5-9B-Q8_0.gguf` | `unsloth/Qwen3.5-9B-MTP-GGUF` | **33** | 9.11 GiB |
| Ornith-1.5-9B | `Ornith-1.5-9B-MTP-Q8_0.gguf` | `protoLabsAI` (MTP) | **33** | 9.11 GiB |

The Ornith campaign's Stage 0 found that third-party conversions silently drop
the multi-token-prediction layer — 243,290,624 parameters — leaving a 32-block
model, and that the file size gives it away. That finding reproduced exactly
here, across a different model, before anything was downloaded:

    Q8_0 with the MTP layer     9.79 GB   unsloth/...-MTP-GGUF, bartowski
    Q8_0 without it             9.53 GB   lmstudio-community

Those are the same two sizes the Ornith table records for its own lineages.
Taking `lmstudio-community`'s 9.53 GB file would have put a **32-block model
against a 33-block one** and published the difference as a model comparison.

## Tier and the gates

**TIER 1, verified at the GGUF header** rather than only at the HF config:
`arch qwen35`, `block_count 33`, `context_length 262144`, `embedding_length
4096`, `head_count 16`, `head_count_kv 4`, `head_dim 256`, and an identical
`kv_bytes_per_token` table. So architecture, KV arithmetic, the fit table and
the roofline are properties of the SHAPE and are measured ONCE.

**Two differences, both of which matter and neither of which is architectural:**

- **The chat templates differ** (different sha256). This is not cosmetic here:
  Ornith's own published benchmark footnotes say they *"adjust the Qwen chat
  template to ensure consistency between training and inference"* — and their
  Qwen3.5-9B baseline row never says it received the same fix. A template
  difference is a condition that travels with every scored number (rule 3), and
  each arm runs with its OWN template, which is the only defensible choice.
- **Qwen3.5-9B ships NO draft head** (`drafter: null`); Ornith ships one. The
  speculative-decoding arms of the Ornith campaign therefore have no counterpart
  here and no ratio may be formed for them. Published as an asymmetry, not
  quietly dropped.

## What is being measured for the anchor, and what is deliberately not

Ornith-1.5-9B is the subject; Qwen3.5-9B is the **anchor**, and an anchor needs
only what a legal comparison requires — not a second full field guide.

| | why |
|---|---|
| **A — paired anchor sweep** | both arms in ONE sweep, fully crossed over 2 samplers, 4 reps with the first discarded (rule 12), alternating order (rule 30). This is what makes any Ornith-vs-Qwen speed claim legal, and it publishes the anchor's own absolute so a later sweep can form ratios against it. |
| **B — rule-21 suite on Qwen3.5-9B** | the same frozen suite hash `1cdf54f8eb9d3f8f` the Ornith arm and `qwen38-27b-blind` ran, so the composite Means are comparable by construction (rule 23). |
| ~~GPQA Diamond~~ | **NOT queued, deliberately.** It cost 7 h 55 m on Ornith and its value there was validating the harness against a published figure. Re-spending a day on the anchor buys a number this comparison does not need. Recorded as an omission rather than left to look like an oversight. |
| ~~KLD across models~~ | **not a legal instrument here.** KL divergence asks how far a quant is from ITS OWN unquantised weights; pointed at two different models it compares distributions that were never meant to agree. A shared tokenizer is a necessary condition for that comparison, not a sufficient one. |
| ~~speculative arms~~ | **impossible, not skipped.** Qwen3.5-9B ships no draft head, so there is no counterpart to Ornith's MTP arms and no ratio can be formed. |

`work/run-to-publish.py` runs A then B unattended: resumable through
`data/chain-state.json`, a heartbeat before and after every step, each child
taking the GPU lock itself so rule 20 holds without the chain knowing anything
about the card, and a checkpoint commit after each step.

## Stage 7 publish target — mirrored, never auto-pushed

The finished report is `results/qwen35-9b-family/index.html`, and it is mirrored
to **`~/Workspace/chinkeong.github.io/qwen-9b/index.html`** —
`github.com/chinkeong/chinkeong.github.io`, branch `master`. The precedent is
`results/qwen38-27b-blind` → `qwen-27b/`, which carries `index.html`,
`figures/`, `quant-ladder.png` and the standalone agentic reports.

`scripts/report/mirror-to-pages.sh <slug> <page-dir>` does the copy. **It does
not commit and it does not push, deliberately.** Everything else in this tree
pushes automatically because measured data on one disk is at risk (rule 28) and
that remote is the author's own working repo. This target is a **public
website**: a wrong number on a public page is read, cached and cited before it
can be corrected, so the last step stays a human decision. The script stages the
bytes, refuses outright while `index.html` is absent or still contains
TODO/PLACEHOLDER/FIXME, and prints the two commands that would publish.

### 2026-09-02 01:10 — the first launch died on a defect a comparison campaign always triggers

`A-anchor-sweep` failed instantly, the chain stopped as designed, and the card
sat idle for 15 minutes before anyone looked:

    2 campaigns have a campaign.json (ornith-1.5-9b-mtp, qwen35-9b-family).
    Name the one you mean: pass --slug, or set MEASURED_INFERENCE_SLUG=<slug>.

`scripts/lib/paths.py` auto-detects the campaign from whichever
`results/*/campaign.json` it finds and refuses when there is more than one. That
is correct behaviour and it is also a **structural trap for this kind of
campaign**: a comparison is *by definition* a second campaign standing beside the
field guide it compares against, so the ambiguity is not an edge case here, it is
the normal state from the moment the directory is created. Every future
comparison hits it on its first launch.

Fixed by pinning `MEASURED_INFERENCE_SLUG` inside `anchor-sweep.py` before
`paths` is imported, and by having `run-to-publish.py` pass the slug down to
every child it spawns, so no caller has to remember.

**The monitor was not the thing that failed, and this is worth being precise
about.** `results/qwen35-9b-family/work/watchdog.log`:

    00:48:46 GPU OFF-CARD — a campaign job is alive but the card is free ...
    00:48:46 POWER LOGGER ABSENT — nothing is logging power for this campaign ...
    00:54:49 GPU IDLE — lock free, no llama.cpp tool live. The next campaign
             task can start now.

Both alarms were correct and both fired within seconds. The **OFF-CARD** state,
added yesterday, correctly described a job that was alive but downloading; the
**IDLE** line names the exact condition six seconds after the chain exited; and
**POWER LOGGER ABSENT** caught a genuine rule-24 gap — this campaign had no
logger at all, because the running one writes into the *Ornith* campaign's
directory. A logger for this slug is now running.

What was missing is that **nothing acts on those alarms**. The campaign watchdog
reports and deliberately never starts jobs — that is rule 20's whole point — so
acting is the session loop's job, and it was on a 30-minute cadence against a
chain that stops on first failure. Two changes: the loop now runs **every 9
minutes**, and it reads the failing step's log *before* relaunching and refuses
to relaunch a step that has already failed twice with the same error, because
re-running a deterministic failure just burns ticks.

### First measurement off the anchor, before the sweep even finished

    Qwen3.5-9B  rep1 greedy  84.26 t/s  LOOP
    Qwen3.5-9B  rep1 card    78.67 t/s  LOOP

**Qwen3.5-9B loops under greedy too.** The Ornith campaign found Q8_0 scoring
LOOP on every greedy floor probe and recorded it as a property of that arm; the
anchor does the same thing at the same sampler on the same prompt. That points
at the base model or the family's chat template rather than at Ornith's training,
and it is the first claim in this document that could only be made because the
anchor was measured rather than cited.

## The measured comparison  ·  2026-09-02

### Speed — one sweep, alternating, first probe discarded

| arm | greedy | × anchor | card preset | × anchor | loop verdicts |
|---|---|---|---|---|---|
| **Qwen3.5-9B** (anchor) | **84.17 t/s** | 1.0000 | **78.52 t/s** | 1.0000 | LOOP |
| Ornith-1.5-9B | 83.80 | **0.9956** | 78.77 | **1.0032** | LOOP, clean |

**Decode speed is the same model to within 0.5%**, on both samplers. That is
what TIER 1 predicts and it is worth stating as a finding rather than an
absence: identical shape, identical file size, identical quantisation format —
so a throughput claim that separated these two would have been measuring the
rig, not the models.

**Both loop under greedy.** The Ornith campaign recorded Q8_0 scoring LOOP on
every greedy floor probe and treated it as a property of that arm. The anchor
does the same thing on the same prompt at the same sampler. **The repetition is
inherited, not trained in** — and that claim was impossible to make while
Qwen3.5-9B existed here only as a citation.

### Quality — rule 21, same frozen suite hash `1cdf54f8eb9d3f8f`

| dataset | Qwen3.5-9B | Ornith-1.5-9B | truncated (Q / O) |
|---|---|---|---|
| GSM8K | 92.0 | **100.0** | 2 / 0 |
| MATH-500 | 48.0 | **60.0** | 13 / 3 |
| HumanEval | **92.0** | 88.0 | 0 / 1 |
| MBPP | 56.0 | **72.0** | 8 / 5 |
| MeetingBank | 20.0 | **24.3** | 0 / 0 |
| **Mean (five scored)** | **61.6** | **68.9** | **23 / 9** |

**What is robust and what is not.** At n=25 a single dataset's difference is
worth about ±10 points of binomial noise, so MATH-500's 12 points and MBPP's 16
are each roughly one sigma — suggestive, not settled (rule 8: point differences
at this n are not real). HumanEval runs the *other* way. The composite favours
Ornith by 7.3 and is the better-powered figure, but it is still a mean of five
noisy cells and should be read as a lean, not a verdict.

**What IS large and consistent is the truncation rate: 23 against 9**, and it is
the same finding in every cell where the two differ.

### The finding neither model card reports

    Qwen3.5-9B     10,235 s
    Ornith-1.5-9B   4,231 s

**Identical decode speed, and Ornith finishes the same 175 prompts in 41% of the
wall clock.** Nothing about tokens-per-second explains it — that was measured as
equal above. The entire gap is termination: every truncated answer burns the
full 16,384-token cap and then scores zero, so Qwen spends 2.4× the time to
produce a lower Mean.

That is the practical shape of what Ornith's post-training bought on this
hardware, and it is invisible in a benchmark table: a scores column shows 61.6
against 68.9 and says nothing about the hour and a half of extra card time. It
was only measurable because both arms ran the same 175 prompts under the same
cap on the same box.

**A caveat that must travel with it (rule 3).** The two models run their OWN
chat templates, which differ. Ornith's own published footnotes say they adjust
the Qwen template for train/inference consistency, and their Qwen baseline row
never says it received the same fix. Some part of this termination gap may be
template rather than weights, and this campaign cannot separate them — a
template-swapped arm would, and is not run here.

### The judged pair — same panel protocol, same seats discipline

`rule21-judge-panel-v1`: three blind seats, opaque salted ids, per-seat shuffles,
1-10 normalised `(r-1)/9*100`. Twelve **independent subagent seats**, one per
packet, rather than one context rating the same material three times — three
seats inside one context are correlated by construction and their agreement
measures nothing. 50 answers, 150 ratings, **rated 50/50, 0 missing, 0 partial**
for both arms.

**The judge is Claude Opus 5 and so is this document's author: a CORRELATED
INSTRUMENT**, which is why inter-rater spread is published beside every mean.

| dataset | arm | mean 1-10 | score | sd across items | at-cap items |
|---|---|---|---|---|---|
| ALPACA | Qwen3.5-9B | 6.52 | **61.3** | 2.965 | **5** |
| ALPACA | Ornith-1.5-9B | 7.08 | **67.6** | 2.081 | 1 |
| MT-Bench | Qwen3.5-9B | 7.75 | **75.0** | 1.809 | 1 |
| MT-Bench | Ornith-1.5-9B | 8.19 | **79.9** | 1.054 | 0 |

Both arms are **provisional** under the panel's own rule-7 flag, and the reason
is the same one the whole comparison keeps arriving at: **six of Qwen's fifty
judged answers hit the cap and came back empty, against one of Ornith's.** An
empty answer is rated 1 by unanimous seats, so a large part of the 6.3 and 4.9
point gaps is not "worse writing" — it is **not finishing**.

Ornith's item sd is also lower on both sets (2.081 vs 2.965, 1.054 vs 1.809): it
is not only rated higher on average but more consistently, which at n=25 is the
more trustworthy half of the observation.

**Judged scores are published BESIDE the composite Mean and never folded into
it**, exactly as in the Ornith campaign — the reference `qwen38-27b-blind` Mean
is a mean of five with both excluded, and adding them would silently redefine
the metric (rule 23).

## The template crossover — pre-registered before it ran  ·  2026-09-02

The campaign's headline is that Ornith finishes the same 175 prompts in 41% of
the wall clock at identical decode speed, and that the whole gap is termination.
The two arms run their **own** chat templates, so weights and template are
confounded, and this repo has already published two mechanisms in this campaign
that were wrong in exactly that way. So the confound gets cut rather than
footnoted.

**Design: a 2×2 crossover, scoped to where the effect lives.** MATH-500 and MBPP
carry **21 of Qwen's 23 truncations and 8 of Ornith's 9**, so 50 prompts per arm
answers the question at a quarter of a full-suite crossover.

| | Qwen template | Ornith template |
|---|---|---|
| **Qwen weights** | 13 + 8 truncations (measured) | **new arm** |
| **Ornith weights** | **new arm** | 3 + 5 truncations (measured) |

If truncation follows the TEMPLATE, both new arms swap their truncation counts.
If it follows the WEIGHTS, neither moves. Nothing else separates them.

**What the templates actually differ by, read before running.** Qwen's is 7,992
chars (sha `8452ca85…`), Ornith's 7,756 (sha `a4aee8af…`). The difference is a
**39-line system-message merging block** that Qwen has and Ornith does not —
Qwen merges two consecutive `system`/`developer` messages into one; Ornith
does not. `system` appears 14 times in Qwen's template against 8 in Ornith's.

**The reasoning machinery is IDENTICAL in both**: `enable_thinking` 1/1,
`<think>` 4/4, `reasoning` 7/7. Nothing in either template controls thinking
differently.

**PRE-REGISTERED PREDICTION, written before the run.** Rule-21 prompts are
single user messages with **no system message**, so the block the two templates
differ by should never fire. The prediction is therefore that **the crossover
shows no effect and termination is a property of the weights** — Ornith's
post-training, not its packaging. Recording it now so the result cannot be read
back onto a story chosen afterwards, which is the failure this campaign has
already made twice.

### The crossover result — and why the experiment was the wrong instrument

**The 2×2, all four cells, MATH-500 + MBPP truncations (and scores):**

| | Qwen template | Ornith template |
|---|---|---|
| **Qwen weights** | 13 / 8 · (48.0, 56.0) | **13 / 8 · (48.0, 56.0)** |
| **Ornith weights** | **3 / 5 · (60.0, 72.0)** | 3 / 5 · (60.0, 72.0) |

Not similar — **bit-identical**, truncation counts and scores alike. Neither
swapped arm moved by a single item.

**PRE-REGISTERED PREDICTION: half held, half does not follow, and the half that
does not follow is the half that mattered.**

- *"The crossover shows no effect"* — **HELD.**
- *"Therefore termination is a property of the weights"* — **DOES NOT FOLLOW**,
  and calling it confirmed would have been the fourth time this campaign
  mistook a real effect for a demonstrated mechanism.

**Why, from a control that took three seconds and should have run first.**
Rendering every suite prompt through both templates:

    identical renders: 175    different: 0    (of 175 suite prompts)

Every rule-21 prompt is a bare single user turn with no system message and no
tools, and the only thing the two templates differ by is a 39-line
system-message merging block. **So the templates emit the same bytes for this
entire suite.** The crossover could not have detected a template effect here
under any outcome. It was a valid experiment with **zero power**, and its
identical results are a restatement of the control, not independent evidence.

**What this DOES establish, which is what the run was for.** The template
confound is **eliminated for the rule-21 suite** — the 23-vs-9 truncation gap
cannot be a template artifact, because there is no template difference to be an
artifact of. The confound is cut. That was the question.

**What it does NOT establish.** That the weights *cause* the termination
difference. Weights are now the only remaining candidate among {weights,
template} *for this input class*, which is elimination, not demonstration. And
it says nothing about workloads that DO carry system messages or tools — where
the templates genuinely differ and where an agentic harness lives. A tool-using
or system-prompted comparison would need this run again, properly powered.

**The methodological cost, recorded because it is the useful part.** Two hours
of GPU time bought a result a three-second render comparison would have
predicted exactly, and would have predicted *better* — because the render
comparison also says WHY, and bounds where the conclusion stops applying. The
lesson is not "don't run the control experiment"; it is **run the cheap
falsification of your experiment's power BEFORE spending the GPU hours on the
experiment** (rule 25's own logic: cheap probes buy the map, and the map decides
which expensive hours are worth it). The control was cheap, available from the
start, and I ran it afterwards.

---

## Stage 7 complete / published

Recorded 2026-09-03. Every step this campaign defined has run and the artefact
is live.

| step | outcome |
|---|---|
| download-gate | `Qwen3.5-9B-Q8_0.gguf` byte-exact against Content-Length, 9,786,061,152 |
| A-anchor-sweep | OK 2026-09-02 01:13:46 — commit `e2d7e86` |
| B-rule21-qwen | OK 2026-09-02 04:04:35, suite `1cdf54f8eb9d3f8f` — commit `9a67433` |
| judge panel | 12 packets, 150 ratings, 0 missing, 0 partial — commit `fdfcc7e` |
| template crossover | both cells, plus the 3 s render control that showed zero power — commits `039aa8f`, `c291533`, `9e40d49` |
| Stage 7 | `index.html`, nine sections — commit `2c90dd9`, corrections `b9cbcd7` / `4582f99` / `6c9b3bc` |
| mirror | staged, committed and **pushed** to `chinkeong.github.io/qwen-9b/` at 2026-09-02 21:14:51 +0800, `origin/master` `0a0aa1e` |

GPQA Diamond was never queued for the anchor and that remains deliberate, not an
oversight: it cost 7 h 55 m on the Ornith arm and buys this comparison nothing.

**Why this entry exists at all.** AGENTS.md's "RESUMING A CRASHED CAMPAIGN" tells
an agent to list `results/*/campaign.md` and, if the last entry is not "Stage 7
complete / published", to resume rather than interview. This log's last dated
section was the template crossover, written about ten hours before Stage 7
landed, so for a day this finished and published campaign read as one that died
mid-flight. A session on 2026-09-03 did exactly that and spent a turn
reconstructing state that was never lost.

**One correction shipped with this entry.** The GPQA decomposition figcaption in
`report-ornith-1.5-9b.html` — and in its source, `results/ornith-1.5-9b-mtp/index.html`
— read "Cap 30,000 tokens, greedy, seed 42". The run was not greedy. The run
JSON's `settings` block records `temperature 1.0`, `top_p 0.95`, `top_k 20`,
`presence_penalty 0.0`, which is the model card's general preset, and
`campaign.md` line 1162 had it right the whole time; only the caption was wrong.
A wrong condition line on a published page is a rule 3 defect, and this one was
live on the public site. Corrected in all three copies. The mirror is re-staged;
the push, as always, is a human's to make.

**Roster note for whoever adds the next arm.** A candidate was screened on
2026-09-03 and rejected before any GPU time:
`Jackrong/Qwopus3.5-9B-v3-GGUF` is **TIER 1 illegal** — `block_count 32`, no
`nextn_predict_layers`, 427 tensors against the anchor's 442, the 15 missing
being exactly all of `blk.32`. That is the MTP silent-drop trap for the third
time in this repository. Its own `config.json` declares
`mtp_num_hidden_layers: 1` against `num_hidden_layers: 32`, so the upstream
weights have the layer and the GGUF conversion lost it; the repo ships no BF16,
so it cannot be repaired in place. Nothing on its model card would have caught
it. `Jackrong/DeepSeek-V4-Pro-Qwen3.5-9B-MTP-GGUF` screened **TIER 1 legal** —
442 tensors, zero differences from the anchor in names, shapes or per-tensor
quant types. Both verdicts came from the header, not from the file size;
`scripts/verify/gguf-shape-gate.py` is the gate that now makes that check
routine.
