# Local dataset benchmark

Benchmarks local models over the seven standard datasets — GSM8K, MATH-500,
HumanEval, MBPP, ALPACA, MeetingBank, MT-Bench — measuring **scores**
(`--score`), per-request mean acceptance length (with speculative decoding), or
generation throughput, and renders the results as a dark table PNG. The runner
launches **llama-server** (llama.cpp) itself for each model, waits for it to
become healthy, and reads llama.cpp's `timings` from every response — no
external server or management app involved.

`--rule21` runs METHODOLOGY's standard benchmark protocol end to end.

Two further datasets ship as **adjunct sets** — GPQA-Diamond and IFEval. They
are registered, frozen and scored, they run on `--datasets <name>`, and they are
deliberately outside the seven and outside the Mean. See *Adjunct sets* below
before adding a benchmark to anything.

## Requirements

- A llama.cpp build with `llama-server` — found via `--server-bin`, the
  `LLAMA_SERVER` env var, or PATH (`scripts/setup.*` installs one into
  `bin/llama.cpp/`, which the runner finds automatically).
- Python 3.10+ with `requests` and `Pillow` — that is the whole dependency list
  *for collection*, because ROUGE-L, the pass@1 runner and the judge client are
  implemented here. Publishing needs three more (`numpy`, `matplotlib`, `scipy`,
  imported by twelve files under `scripts/report/` and `scripts/quant-ladder/`).
  Install `requirements-min.txt` on a machine that only measures and
  `requirements.txt` on the one that renders the report.

**Install those two into a repo-local venv, never globally** — the machine may
be borrowed. From the repo root (`.venv/` is gitignored):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-min.txt    # Windows
# POSIX: python3 -m venv .venv && ./.venv/bin/python -m pip install -r requirements-min.txt
```

Then run every `python bench.py …` / `python render_table.py …` below with that
interpreter (`..\..\.venv\Scripts\python.exe bench.py …` from this directory),
or activate the venv first. If a venv cannot be created, `pip install --user`
is the fallback — say so in the report's methodology trail, because it is the
one thing the campaign left on the host.

## The standard benchmark protocol (METHODOLOGY rule 21)

```powershell
python bench.py --model a.gguf --rule21
```

`--rule21` is exactly:

```
--score --greedy --seed 42 --samples 25 --max-tokens 16384 \
  --datasets GSM8K,MATH-500,HumanEval,MBPP,ALPACA,MeetingBank,MT-Bench
```

175 prompts per arm, and `-c` sized automatically from the suite's longest
prompt plus the cap (see *Context sizing*). Any flag you pass explicitly wins
over the preset, so `--rule21 --samples 200` is the escalation run. All seven
benchmarks are must-run: a missing one breaks cross-report comparability and
voids the Mean.

Expect **~4–8 h per model at max effort on a 24 GB card**.

## Scoring

Every scored benchmark normalizes to **0–100 by its own scorer**:

| Benchmark | Scorer | Normalization |
|---|---|---|
| GSM8K | exact match on the final `####` number, numeric-tolerant | pass rate ×100 |
| MATH-500 | exact match on the last `\boxed{}`, LaTeX-normalized | pass rate ×100 |
| HumanEval | execution pass@1 — prompt + completion + the dataset's `check(entry_point)` | pass rate ×100 |
| MBPP | execution pass@1 — generated code + the full `test_list` (all asserts, not just the one shown in the prompt) | pass rate ×100 |
| MeetingBank | ROUGE-L F1 vs the reference summary | F1 ×100 |
| ALPACA | independent judge, 1–10 rubric | `(r-1)/9 ×100` |
| MT-Bench | independent judge, 1–10 rubric | `(r-1)/9 ×100` |
| GPQA-Diamond † | exact match on the chosen option letter; an unreadable answer scores wrong, not unscored | pass rate ×100 |
| IFEval † | deterministic instruction verifier — 25 checkable instruction types, no judge and no model | prompt-level strict pass rate ×100 |

† **Adjunct set.** Scored, published as its own column, and never averaged into
the Mean — *Adjunct sets* below says why that is a rule-23 requirement rather
than a preference.

Before scoring, thinking is stripped (`<think>…</think>`, terminated or not) and
code is pulled out of markdown fences — the largest fenced block that actually
looks like code, so a usage example printed beside the solution doesn't get
graded. An answer that hit `--max-tokens` never reached its final answer: it
scores **0** and is reported separately as a truncation, never dropped
(METHODOLOGY rule 7 — filtering to non-truncating questions is selection bias).

### The judge rule

ALPACA and MT-Bench have no mechanical ground truth. They are scored only when
an **independent** OpenAI-compatible endpoint is configured:

```powershell
python bench.py --model a.gguf --rule21 --judge-url http://otherbox:1300/v1 --judge-model gpt-oss-120b
# key, if the endpoint wants one: --judge-key, else $JUDGE_API_KEY / $OPENAI_API_KEY
```

The rubric is MT-Bench's single-answer grading prompt (FastChat `single-v1`),
parsed from `[[rating]]`.

**A model must never judge its own outputs.** A `--judge-url` pointing at the
host and port under test is refused; `--allow-self-judge` overrides it and
stamps `"self_judge": true` into the result JSON and the PNG caption, where it
reads *"SELF-JUDGE — not an independent score"*. Without a judge the two
benchmarks still **run** — the gate is on scoring, not on running — and the run
records `"unscored: no independent judge"` plus every generation in
`results/<run>_transcripts.json` for blind human judging later.

A judge on this machine (different port) is allowed but warned about: it
competes for the GPU. Timings come from llama.cpp's own counters so tok/s stays
valid, but wall clock inflates.

### Judging transcripts after the fact — `judge-panel.py`

The live `--judge-url` path needs a second endpoint at benchmark time. When you
did not have one, the transcripts are still kept, and `judge-panel.py` scores
them later with **zero GPU** — it never touches the model, only the recorded
answers:

```powershell
python judge-panel.py build     # blinded packets + the sealed key
#   ... hand each packet to one judge seat; each writes ratings/<packet>.json
python judge-panel.py score     # per-arm scores + inter-rater spread
python judge-panel.py compare   # paired bootstrap, arm against arm
```

`build` emits one packet per ⟨dataset × half × seat⟩ holding `{id, question,
answer}` with **opaque salted ids**, and seals the id→arm map in
`key-SEALED.json`. Each seat gets its own shuffle seed, so ordering effects do
not correlate across seats. A judge seat is told to read its packet and nothing
else — reading the key would void the blinding.

`score` refuses to publish if any answer is unrated or rated by only some
seats: rule 7 forbids filtering, so a partial panel is not a smaller panel, it
is no result. Empty and truncated answers are rated like any other (an empty
answer is a 1) and are flagged `at_cap`, which marks that arm's score
`provisional` until the rule-7 re-run lands.

`compare` is how arm-against-arm claims are made — a 20,000-resample paired
bootstrap over per-prompt differences, because the same prompts went to every
arm. It prints the win/loss/tie counts with each interval and labels an
interval that barely clears zero as **marginal**.

**Disclose a correlated judge.** If the judge shares a vendor or family with
whoever wrote the report, the self-grading gate is satisfied but independence
is not. Say so beside the numbers, publish the seat spread, and carry
"a second-vendor or human judge" as an open item. The packets, the key and
every rating are kept precisely so another judge can be run over the identical
answers.

### Code execution

HumanEval and MBPP pass@1 **runs model-generated code on this machine**. That is
deliberate — the operator started the benchmark — but it is not a security
sandbox. Each sample runs as `sys.executable -I -E` (isolated: no `PYTHONPATH`,
no user site-packages, no cwd on `sys.path`), stdin closed so `input()` fails
instead of hanging, a 10 s wall clock, and a temporary cwd deleted afterwards.
The runner itself makes no network calls.

If that is not acceptable on this host, `--no-exec` turns both benchmarks back
into unscored transcript runs (`"unscored: --no-exec (code execution
disabled)"`), and they drop out of the Mean.

### The Mean

The **composite index**: each *scored* benchmark's 0–100 score, averaged. It is
never an accuracy, and an unscored benchmark is **excluded, never counted as a
zero**. The result JSON carries the whole story:

```json
"composite": {
  "mean": 61.0,
  "included": ["GSM8K", "MATH-500", "HumanEval", "MBPP", "MeetingBank"],
  "scores": {"GSM8K": 88.0, "...": 0},
  "excluded": {"ALPACA": "unscored: no independent judge",
               "MT-Bench": "unscored: no independent judge"},
  "label": "composite index over GSM8K, MATH-500, HumanEval, MBPP, MeetingBank"
}
```

The table renders it as a **`Mean (composite)`** row and spells the label out in
the caption. Two Means are comparable only when their scored sets *and* suite
hashes match — a report run without a judge endpoint must state that its Mean
excludes the judge-gated pair.

### Interpretation guardrails

- **A single N=25 cell is a smoke test** (±~16 pts). Never rank effort levels,
  quants or machines by one cell.
- **The Mean is the interpretable result**: it aggregates ~175 samples per arm
  and carries near-n=200 power. So are categorical collapses (works vs crashes).
- **Escalate before claiming**: any suspicious cell goes to n=200 on that
  benchmark alone (`--datasets MBPP --samples 200`) before it becomes a claim.
- Greedy decoding makes reruns of the other arms byte-identical, so an
  escalation or a raised cap only costs the arm that needed it.

## Adjunct sets: registered, scored, outside the seven

Nine datasets ship here. Seven are rule 21's suite; **GPQA-Diamond** and
**IFEval** are adjunct sets, and the line between the two classes is arithmetic
rather than taste.

`bench.py`'s `_suite_hash` hashes the dataset name plus every prompt, and rule
23 makes two reports comparable **iff their suite hashes match**. Add an eighth
benchmark to the seven and every published comparison stops being a comparison —
the old reports do not become wrong, they become unmeasurable against the new
one, and the only way back is re-running every arm. So the seven are a closed
set, and everything else is an adjunct:

| | the seven | an adjunct |
|---|---|---|
| in `DEFAULTS["datasets"]` — a plain `bench.py --model x` run | yes | **no** |
| in `--rule21` | yes | **no** |
| runs on `--datasets <name>` | yes | yes |
| enters the composite Mean | yes | **never** |
| moves the rule-21 suite hash | — | no |

Membership is declared in `datasets_io.py`: `RULE21_SETS` is the seven,
`ADJUNCT_SETS` is the rest, `DATASET_NAMES` is the seven (what `DEFAULTS`
sweeps), and `ALL_DATASET_NAMES` is everything `--datasets` accepts. Two guards
hold the line:

- **Registering a set in `SOURCES` without declaring it in one of the two lists
  raises at import**, on your own machine, with the fix in the message. Before
  that check, `DEFAULTS["datasets"]` was `",".join(DATASET_NAMES)` over every
  registered set — so a newly registered benchmark joined every non-`--rule21`
  run, and that run's composite Mean, by existing.
- **`composite_index` drops an adjunct by name**, whatever a caller passes in,
  and returns it under `excluded` with the reason `"adjunct set: outside
  METHODOLOGY rule 21's seven, never averaged into a composite Mean"`. The run
  JSON therefore records that a number existed and was deliberately not
  averaged, which is the difference between an exclusion and a silent drop.

Adding IFEval left the rule-21 suite hash where it was:

```
# on the tree before the change:
$ python bench.py --rule21 --freeze-suite before.json
froze suite -> before.json (hash 1cdf54f8eb9d3f8f, 175 prompts). ...

# with IFEval registered:
$ python bench.py --rule21 --freeze-suite after.json
froze suite -> after.json (hash 1cdf54f8eb9d3f8f, 175 prompts). ...

$ python -c "import json; a=json.load(open('before.json')); b=json.load(open('after.json')); print(a['hash'], b['hash'], a['prompts'] == b['prompts'])"
1cdf54f8eb9d3f8f 1cdf54f8eb9d3f8f True
```

`1cdf54f8eb9d3f8f` is also the hash inside the shipped `suites/rule21-n25.json`,
so the frozen suite every published arm ran against is still the suite this tree
produces.

Run that pair before and after touching anything in `SOURCES`, `build_item` or
`RULE21_SETS`. A moved hash means every prior report has become incomparable,
and it is far cheaper to find that out here than in a report.

## IFEval (adjunct)

Zhou et al., *Instruction-Following Evaluation for Large Language Models*
([arXiv 2311.07911](https://arxiv.org/abs/2311.07911)). **541 prompts carrying
834 instructions of 25 verifiable types** — "write at least 300 words", "no
commas", "wrap the whole reply in double quotes", "end with this exact phrase".
Every one is checked by code. No judge, no second model, no rubric.

That is what makes it affordable at its **full published size**, which is the
reason to run it at all: rule 6 makes accuracy at n≤25 a smoke test, so a
benchmark that has to be truncated to 25 items buys almost nothing, and this one
never has to be. Scoring all 541 replies costs milliseconds — the entire cost is
generation.

```powershell
python bench.py --model a.gguf --datasets IFEval --samples 541 `
  --score --greedy --seed 42 --max-tokens 16384 --ctx 32768
```

- `--samples 541` takes the whole set (the selection is evenly spaced, so
  anything smaller is a real subset and must say so).
- `--ctx 32768`: the longest prompt is ~465 tokens at 4 chars/token, plus the
  16,384 cap, rounded up to the next power of two. `--rule21` sizes `-c` itself;
  this run does not use `--rule21`, so pass it.
- `--greedy` for any score you intend to compare, as everywhere else here.
- Add `--transcripts` to keep the generations — see *the other three numbers*.

For a cross-machine run, freeze the prompts instead: `--freeze-suite
ifeval-541.json` writes the 541 prompts and their instruction specs and prints
**hash `fe07c5430542f497`**. Two machines printing that hash ran the same
benchmark.

### The published number is prompt-level strict

IFEval defines **four** accuracies, and reports in the wild quote whichever is
kindest. This harness publishes one and labels it:

| | strict | loose |
|---|---|---|
| **prompt-level** (all instructions on a prompt followed) | **PUBLISHED** | diagnostic |
| instruction-level (each instruction counted separately) | diagnostic | diagnostic |

Pinned in `datasets_io.IFEVAL_PUBLISHED`, and written into every run JSON as the
scorer name — `"scorer": "IFEval verifier, prompt-level strict"` — so a result
file that outlives this README still says which of the four it holds.

Three reasons, in order of force:

1. **An unpinned choice is how two runs stop being comparable.** All four are
   called "IFEval", and on identical text they are far apart: echoing every
   prompt straight back at all 541 scores **24.8** prompt-level strict against
   **41.4** instruction-level loose, a 16.6-point spread with not one token
   changed. Two arms that pinned different ones would differ by an artefact of
   the scorer.
2. **Prompt-level is the one this plumbing computes correctly.** The harness
   averages one score per item; prompt-level accuracy *is* that mean.
   Instruction-level weights by the 1–3 instructions a prompt carries and cannot
   come out of a per-item average — a run that reported it from this path would
   be reporting the wrong statistic.
3. **Strict over loose.** Loose passes an instruction if any of eight mechanical
   rewrites of the reply satisfies it (first line dropped, last line dropped,
   both, each with `*` stripped). That is an upper bound on the model, and the
   prime directive is that no reader measures less than the report promised.

### The other three numbers, without touching the GPU

`ifeval_grade()` returns the per-instruction booleans for **both** passes, so
strict, loose, prompt-level and instruction-level are all recoverable from a run
that kept its generations. Run with `--transcripts`, then:

```python
import json, sys
sys.path.insert(0, "scripts/bench")
import datasets_io as D

tr = json.load(open("scripts/bench/results/<run>_transcripts.json", encoding="utf-8"))
refs = [it["ref"] for it in D.load_items("IFEval", 541)]   # same --samples as the run
graded = [D.ifeval_grade(g["response"], refs[g["index"]])
          for g in tr["generations"]["IFEval"]]
print(json.dumps(D.ifeval_report(graded), indent=2))
```

`ifeval_report` returns all four, plus `n_prompts`, `n_instructions`, a
breakdown by instruction type, and the name of the published one. Anything but
`prompt_strict` is a diagnostic and must be labelled as one wherever it appears.

### Read the score against a floor of about 10, not against 0

A reply that ignores every instruction still satisfies some of them by accident:
66 of the 834 instructions are `punctuation:no_comma`, and a short answer with
no commas passes. Measured over all 541 prompts:

| canned reply | prompt-level strict |
|---|---|
| empty | 0.0 |
| one plain sentence, no formatting | 10.5 |
| the prompt echoed back | 24.8 |

Those three are assertions in the dry run, so they double as a lock on the
verifier: change any checker and one of them moves. (10.5 is that specific
sentence — a different null reply lands a point or two away. The claim is the
floor's existence and rough size, not the digit.)

### Provenance and licence

- **Licence: Apache 2.0** — the `google-research` monorepo's root `LICENSE`
  covers `instruction_following_eval/`, data and scorer alike. The sentence
  splitter in `datasets_io.py` is transcribed from that scorer under it.
- **Frozen** at `datasets-frozen/ifeval.jsonl` — 207,111 bytes, 541 rows,
  sha256 `67ffeee0fcb87c317c5b08a2de85557b4a7e96ada6178aa645b4954fe4b53d49`, LF
  endings (`.gitattributes` marks `datasets-frozen/** binary`, so a Windows
  clone cannot rewrite them). Byte-identical to upstream.
- **The source URL is pinned to a commit**, not to `master`, because the data
  file has been edited since publication. Commit `26d8ccda` (2024-06-11, *"Fix
  an eval prompt"*) changed exactly one prompt against `066e1eda` (2023-11-27):
  key 2785 asked for "at least one placeholder" while its kwargs demanded three,
  and the prompt was corrected to match. Instruction lists and kwargs are
  identical across both commits. So an IFEval figure published before
  2024-06-11 was measured with one differing prompt out of 541.

### What this verifier does differently, and why

The official implementation reaches the network **at scoring time** — it loads
an NLTK punkt pickle and calls `langdetect` — which rule 23 forbids. Both are
replaced with deterministic offline code. Four differences follow, and they are
listed here because a divergence a reader cannot see gets charged to the model:

| # | Check | Upstream | Here |
|---|---|---|---|
| 1 | `length_constraints:number_sentences` (52 instructions, 46 prompts) | punkt pickle, fetched at scoring time | the regex sentence splitter the **same upstream module already ships** (`instructions_util.split_into_sentences`), transcribed unchanged. Its disagreement rate against punkt is **unmeasured** on this machine: nltk is not installed, and fetching the pickle to measure it is the thing rule 23 forbids |
| 2 | `language:response_language` (31), `change_case:english_capital` (25), `change_case:english_lowercase` (39) | `langdetect`, which is itself nondeterministic unless `DetectorFactory.seed` is set — the official scorer does not set it | dominant Unicode script, then a marker tie-break among languages sharing that script. Exact for the 8 of the 22 requested languages that own their script (bn, gu, kn, ko, pa, ta, te, th); **lenient** for the other 14, where two or more share a script and the reply carries no discriminating marker |
| 3 | `change_case:capital_word_frequency` (25) | `nltk.word_tokenize` (Treebank) | a Unicode word regex keeping hyphens, apostrophes and internal periods together — matching upstream's own "hyphenated words will count as one word" comment, differing on clitics ("DON'T" is one token here, two under Treebank) |
| 4 | `keywords:letter_frequency`, 2 of 541 prompts | rejects any letter outside `a-z` and substitutes `random.choice(string.ascii_letters)`, **unseeded** — so those two items grade a different random constraint on every run | counts the character the prompt names: key 1122 asks for four `#` hashtags, key 1129 for six `!` marks |

Two more properties worth knowing before quoting a number:

- **Thinking is stripped before scoring** (`strip_think`), as it is for every
  other scorer here. A `<think>` block is full of commas, capitals and words; a
  model that answered correctly would fail `punctuation:no_comma` on its own
  scratch work.
- **The prompt reaches the model verbatim.** Every other set here appends an
  answer-format instruction; IFEval must not, because the prompt *is* the thing
  under test. The dry run asserts it.

### Proving the verifier without a GPU

```powershell
python datasets_io.py --ifeval-dry-run
```

89 assertions, 0.2 s, no model and no network: every one of the 25 checkers
against a hand-written pass **and** a hand-written fail (a checker that always
returns `True` passes a one-sided test and inflates a published number for as
long as nobody looks), the strict/loose split, `<think>` stripping, the empty
reply, the frozen file's sha256 and row counts, every instruction type in the
file having a checker, the prompt going out verbatim, all 541 rows scored
against three canned replies, and the adjunct guards:

```
IFEval verifier dry run: hand-written cases, no model and no GPU

per-instruction checks (each of the 25 types, both directions)
  ok   keywords:existence -> True
  ok   keywords:existence -> False
  ...
the whole frozen corpus against three canned replies
  ok   an empty reply scores 0.0
  ok   one plain sentence scores 10.5: the floor a model gets for ignoring every instruction
  ok   echoing the prompt back scores 24.8
  ok   the same text scores 41.4 instruction-level loose

end to end through score_response, on a real frozen row
  ok   scorer is the pinned one
  ok   a compliant reply scores 1.0
  ok   a non-compliant reply scores 0.0

adjunct membership (rule 21's seven, rule 23's suite hash)
  ok   IFEval stays out of the default sweep
  ok   the seven are exactly rule 21's
  ok   --datasets IFEval still resolves
  ok   the Mean refuses the adjunct
  ok   and says why
  ok   so the Mean is unmoved

89 passed, 0 failed
```

Run it after touching any checker, and read the exit code — it is 1 on any
failure.

### One rough edge

`render_table.py` prints an IFEval cell as a plain 0–100 number (`42.3`) rather
than a pass rate (`42%`), because its `PCT_SCORERS` tuple lists scorer names and
does not know this one. The number is right either way. To give it the `%` sign,
add `"IFEval verifier, prompt-level strict"` to `PCT_SCORERS` in
`render_table.py`.

## Context sizing (`-c`)

Rule 21: **the server's `-c` must exceed the suite's longest prompt + the
`--max-tokens` cap**, and MeetingBank transcripts are long — the test split's
p90 is ~9k tokens and the longest is ~91k.

Two guards handle it:

- `--max-prompt-tokens` (default **8192**, estimated at 4 chars/token)
  head-truncates over-long MeetingBank transcripts, marks the cut inside the
  prompt itself, and records `prompt_truncated_n` in the results. At n=25, 2 of
  the 25 sampled meetings hit this. `0` disables the guard — then the longest
  prompt is ~14.5k tokens at n=25 and you own the `-c` arithmetic.
- Every run prints the arithmetic (`longest prompt ~N tok + max_tokens M = ~N+M
  needed`) and warns when `-c` cannot hold it. With `--rule21`, `-c` is *sized*
  from it instead: **`-c 32768`** at the default guard.

`--no-spawn` runs can't set `-c` for you — the warning tells you what the
already-running server needs.

## What it measures

**Mean acceptance length** exists only with speculative decoding, which is
configured server-side and passed through:

```powershell
--server-args "--spec-type draft-mtp --spec-draft-n-max 10 --spec-draft-p-min 0.5"
# external drafter (e.g. DFlash2): --server-args "-md path\to\drafter.gguf --spec-type draft-dflash --spec-draft-n-max 4"
```

llama-server reports `draft_n` / `draft_n_accepted` in its `timings`; since
lossless rejection sampling emits `accepted + 1` tokens per verification pass:

```
mean acceptance length = predicted_n / (predicted_n - draft_n_accepted)
```

This is a *speed* metric, not a quality score — lossless rejection sampling
means the output distribution is identical to the base model's; a higher
number only means more tokens per verification pass.

Without a draft model the run still works and the table shows **tokens/sec,
TTFT, and mean output tokens** instead.

Default sampling: temperature 1.0, top-p 0.95, top-k 20, presence penalty 1.5.
`--greedy` (temperature 0, top-k 1) is mandatory for any score you intend to
compare.

## Usage

`--model` takes GGUF file paths (comma-separated for several -> also a
comparison PNG). The spawned server defaults: `-ngl 99 --parallel 1 --jinja
-c 8192` on port 1236; add anything else via `--server-args`.

```powershell
python bench.py --model a.gguf --rule21                            # the standard protocol
python bench.py --model a.gguf --rule21 --judge-url http://box:1300/v1 --judge-model judge
python bench.py --model a.gguf --rule21 --no-exec                  # no code execution on this host
python bench.py --model C:\models\a.gguf                           # throughput over all seven
python bench.py --model a.gguf,b.gguf --samples 25 --max-tokens 2048
python bench.py --model a.gguf --datasets GSM8K,MT-Bench --samples 5      # quick check
python bench.py --model a.gguf --datasets MBPP --samples 200 --greedy --score  # escalation
python bench.py --model a.gguf --datasets IFEval --samples 541 --score --greedy --ctx 32768  # adjunct set, full size
python bench.py --model a.gguf --server-args "--spec-type draft-mtp --spec-draft-n-max 10"
python bench.py --model a.gguf --no-spawn --port 1234              # benchmark an already-running server
```

Dataset names are case-insensitive (`MEETINGBANK` = `MeetingBank`). The adjunct
sets resolve the same way but are absent from `--help`'s list, which is built
from the seven: `--datasets IFEval` and `--datasets GPQA-Diamond` work.

Each run writes `results/<model>_<timestamp>.json` and a matching `.png`, plus
`results/<model>_<timestamp>_transcripts.json` whenever a scored run had
benchmarks it could not score (`--transcripts` keeps them for every dataset).
Re-render or combine old runs any time:

```powershell
python render_table.py --latest
python render_table.py results\run1.json results\run2.json   # comparison table
```

## Frozen inputs and fair comparisons (rule 23)

Datasets load **frozen file → local cache → network**, in that order:

1. `datasets-frozen/` — committed test cases; these win over everything.
2. `datasets/` — gitignored local cache (this is where a download lands).
3. the canonical public source, fetched once. The `downloading …` line is the
   record that the run had to touch the network.

All nine sets are committed frozen, ALPACA (21 MB) and MeetingBank (13 MB)
included — the pair landed in `datasets-frozen/` at commit `0772924` — so a
machine with no network at all scores every benchmark here. IFEval is 207 KB of
that; the two large sets are 33 MiB of it. A fork that has to clone faster can
delete the pair and they download on first use instead, and the **suite
manifest** below keeps runs comparable while they are gone, because it pins the
exact prompts and is small enough to commit.

Prompt selection is deterministic by construction (evenly spaced indices, no
RNG), but for guaranteed cross-machine runs freeze the exact prompts + settings
into a portable **suite file** and use that everywhere:

```powershell
python bench.py --rule21 --freeze-suite suite_rule21.json        # once, on any machine
# copy suite_rule21.json to each machine, then on every machine:
python bench.py --model <model-key> --suite suite_rule21.json --greedy --score
```

The suite pins the prompts (SHA-256 verified — a corrupted/edited file refuses
to run), the references its scorers need, the truncation notes, sampler
settings, seed, `max_tokens` and `max_prompt_tokens`; `--samples/--max-tokens`
are taken from the suite so nobody can accidentally diverge. Every result JSON
and PNG caption records the suite hash plus the machine fingerprint (host, GPU,
driver, OS), so two tables are comparable iff their suite hashes match.

A fixed `--seed` (default 42) is sent with every request. Note what this does
and doesn't buy you: given identical logits it makes sampling reproducible, but
different backends (CUDA/Metal/SYCL) produce slightly different logits from the
same weights, so generations can still diverge across hardware — that wobble is
inherent, not a flaw in the test. Interpretation guide:

- **Different quants of the same model** (Q4_K_M vs NVFP4 vs ...): systematic
  differences — separate columns in a comparison table.
- **Same file on different hardware**: noise, not quality — report as one cell
  with a ± range; speed metrics (tok/s, acceptance length) are the real signal.
- For **quality-style comparisons** where you want decoding itself
  deterministic per machine, add `--greedy` (temperature 0, top-k 1).

## Self-test

```powershell
python selftest.py
python datasets_io.py --ifeval-dry-run
```

`selftest.py` holds offline assertions (it prints the count) over deterministic
sampling, prompt construction and the MeetingBank truncation guard, ROUGE-L,
code extraction, execution pass@1 (real subprocesses, including a
runaway-generation timeout), the scoring policy, the judge normalization and
self-judge guard, and the composite Mean. `--ifeval-dry-run` holds 89 more over
the IFEval verifier and the adjunct guards — see *Proving the verifier without a
GPU*. No server, no model, no network — run both after touching any scorer.

## Files

- `bench.py` — runner: spawns llama-server per model, sends prompts, scores, collects stats
- `datasets_io.py` — loads/caches the seven plus the two adjunct sets, declares which is which (`RULE21_SETS` / `ADJUNCT_SETS`), builds prompts, and holds every scorer including the IFEval instruction verifier (`--ifeval-dry-run`)
- `render_table.py` — renders result JSON into a dark table PNG
- `selftest.py` — offline self-test of the sampling and scoring paths
- `datasets-frozen/` — committed test cases (rule 23); `datasets/` — local cache
- `results/` — run JSONs, transcripts and PNGs

## Notes

- Runtime estimate: samples x datasets x (max_tokens / tok_s). 10 samples x 7
  datasets x ~25 s/prompt is roughly 30 minutes per model; a full `--rule21`
  arm is 4–8 h at max effort on a 24 GB card.
- Prompts are deterministically spread across each dataset, so runs with the
  same `--samples` are comparable across models.
- ALPACA loads from `tatsu-lab/stanford_alpaca`'s `alpaca_data.json`, the
  upstream file the Hub's `tatsu-lab/alpaca` parquet is built from (parsing
  parquet would mean adding pyarrow). Same 52,002 rows, same order — verified
  at offsets 0, 1, 17333, 34666 and 52001 against the Hub copy via
  `https://datasets-server.huggingface.co/rows?dataset=tatsu-lab%2Falpaca&config=default&split=train&offset=0&length=1`.
  MeetingBank loads the `huuuyeah/meetingbank` test split (862 meetings), which
  the Hub stores as JSON Lines under a `.json` name.
