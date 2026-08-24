# Local dataset benchmark

Benchmarks local models over the seven standard datasets — GSM8K, MATH-500,
HumanEval, MBPP, ALPACA, MeetingBank, MT-Bench — measuring **scores**
(`--score`), per-request mean acceptance length (with speculative decoding), or
generation throughput, and renders the results as a dark table PNG. The runner
launches **llama-server** (llama.cpp) itself for each model, waits for it to
become healthy, and reads llama.cpp's `timings` from every response — no
external server or management app involved.

`--rule21` runs METHODOLOGY's standard benchmark protocol end to end.

## Requirements

- A llama.cpp build with `llama-server` — found via `--server-bin`, the
  `LLAMA_SERVER` env var, or PATH (`scripts/setup.*` installs one into
  `bin/llama.cpp/`, which the runner finds automatically).
- Python 3.10+ with `requests` and `Pillow`. That is the whole dependency list:
  ROUGE-L, the pass@1 runner and the judge client are implemented here, so
  nothing else is ever installed on a borrowed machine.

**Install those two into a repo-local venv, never globally** — the machine may
be borrowed. From the repo root (`.venv/` is gitignored):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install requests Pillow    # Windows
# POSIX: python3 -m venv .venv && ./.venv/bin/python -m pip install requests Pillow
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
python bench.py --model a.gguf --server-args "--spec-type draft-mtp --spec-draft-n-max 10"
python bench.py --model a.gguf --no-spawn --port 1234              # benchmark an already-running server
```

Dataset names are case-insensitive (`MEETINGBANK` = `MeetingBank`).

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

ALPACA (21 MB) and MeetingBank (13 MB) are not in `datasets-frozen/` — they
would dominate a repo that must clone in seconds — so they download on first
use. Their apples-to-apples guarantee is the **suite manifest** below, which
pins the exact 25 prompts and is small enough to commit. To make them offline
too, copy `datasets/alpaca_data.jsonl` and `datasets/meetingbank_test.jsonl`
into `datasets-frozen/` on the machine that has them.

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
```

78 offline assertions over deterministic sampling, prompt construction and the
MeetingBank truncation guard, ROUGE-L, code extraction, execution pass@1 (real
subprocesses, including a runaway-generation timeout), the scoring policy, the
judge normalization and self-judge guard, and the composite Mean. No server, no
model, no network — run it after touching any scorer.

## Files

- `bench.py` — runner: spawns llama-server per model, sends prompts, scores, collects stats
- `datasets_io.py` — loads/caches the 7 datasets, builds prompts, and holds every scorer
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
