"""Download, cache, build prompts for — and score — the benchmark datasets.

TWO CLASSES OF SET, and the difference is load-bearing:

    RULE21_SETS     the seven of METHODOLOGY rule 21 — GSM8K, MATH-500,
                    HumanEval, MBPP, ALPACA, MeetingBank, MT-Bench. These and
                    only these are DATASET_NAMES, which is what bench.py's
                    DEFAULTS sweeps and what its composite Mean averages.
    ADJUNCT_SETS    GPQA-Diamond, IFEval — registered, frozen, scored, runnable
                    by name, and OUTSIDE the seven. bench.py's _suite_hash
                    hashes dataset name plus every prompt, and rule 23 makes two
                    reports comparable IFF their suite hashes match, so a set
                    added to the seven retroactively voids every published
                    comparison. An adjunct never joins a composite Mean:
                    composite_index drops it by name even when a caller passes
                    its score in.

Every set loads in METHODOLOGY rule 23's order — the committed frozen copy in
./datasets-frozen/, then the ./datasets/ cache, then (once) its canonical public
source. The network is a fallback, never a dependency.

Scoring follows METHODOLOGY rule 21: every *scored* benchmark normalizes to
0-100 by its own scorer, and only scored benchmarks enter the composite Mean.

    GSM8K, MATH-500     exact match (final #### number / last \\boxed{})
    GPQA-Diamond        exact match on the chosen option letter. An answer the
                        extractor cannot read scores WRONG, not unscored, so the
                        denominator stays at all 198 questions — see
                        _grade_choice for why that direction is the safe one
    HumanEval, MBPP     execution pass@1 — runs the generated code locally
                        (ScoreOptions(exec_enabled=False) -> unscored)
    MeetingBank         ROUGE-L F1 against the reference summary
    IFEval              deterministic instruction verifier, no judge and no
                        model: 25 checkable instruction types over 541 prompts.
                        This repo publishes PROMPT-LEVEL STRICT and nothing else
                        — see IFEVAL_PUBLISHED and README.md for why an unpinned
                        choice among the four IFEval numbers stops two runs
                        being comparable
    ALPACA, MT-Bench    1-10 judge rubric on an independent OpenAI-compatible
                        endpoint; unscored when none is configured, because a
                        model judging its own outputs is not a score

No dependencies beyond `requests`: ROUGE-L and the IFEval verifier are
implemented here, and the judge speaks plain HTTP. The official IFEval scorer
loads an NLTK punkt pickle and calls langdetect at scoring time; both are
replaced here, deterministically and offline — `python datasets_io.py
--ifeval-dry-run` proves the verifier without a GPU.
"""

import gzip
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile

import requests

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "datasets")
# METHODOLOGY rule 23: test cases committed to the repo win over anything the
# network could hand back
FROZEN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "datasets-frozen")

SOURCES = {
    "GSM8K": {
        "url": "https://raw.githubusercontent.com/openai/grade-school-math/master/grade_school_math/data/test.jsonl",
        "file": "gsm8k_test.jsonl",
    },
    "MATH-500": {
        "url": "https://huggingface.co/datasets/HuggingFaceH4/MATH-500/resolve/main/test.jsonl",
        "file": "math500_test.jsonl",
    },
    "HumanEval": {
        "url": "https://raw.githubusercontent.com/openai/human-eval/master/data/HumanEval.jsonl.gz",
        "file": "humaneval.jsonl",
        "gzip": True,
    },
    "MBPP": {
        "url": "https://raw.githubusercontent.com/google-research/google-research/master/mbpp/mbpp.jsonl",
        "file": "mbpp.jsonl",
    },
    "ALPACA": {
        # tatsu-lab/alpaca ships on the Hub as parquet only, and parsing parquet
        # would mean adding pyarrow. This is the upstream file the Hub dataset is
        # built from — same 52,002 rows, same order. Verified row-identical at
        # offsets 0, 1, 17333, 34666 and 52001 against the Hub copy via the
        # dataset-viewer API (re-check any time, no extra deps):
        #   https://datasets-server.huggingface.co/rows?dataset=tatsu-lab%2Falpaca&config=default&split=train&offset=0&length=1
        "url": "https://raw.githubusercontent.com/tatsu-lab/stanford_alpaca/main/alpaca_data.json",
        "file": "alpaca_data.jsonl",
        "json_array": True,
    },
    "MeetingBank": {
        # huuuyeah/meetingbank, test split (862 meetings). The repo names it
        # .json but the bytes are JSON Lines, so it caches as-is.
        "url": "https://huggingface.co/datasets/huuuyeah/meetingbank/resolve/main/test.json",
        "file": "meetingbank_test.jsonl",
    },
    "MT-Bench": {
        "url": "https://raw.githubusercontent.com/lm-sys/FastChat/main/fastchat/llm_judge/data/mt_bench/question.jsonl",
        "file": "mtbench_questions.jsonl",
    },
    "GPQA-Diamond": {
        # A MIRROR, and it must be labelled as one. The canonical dataset,
        # Idavidrein/gpqa, is gated ("gated": "auto" on the Hub API) and the
        # token on this machine is refused by it. This copy is ungated, carries
        # exactly 198 rows, and presents the canonical FOUR-OPTION multiple
        # choice with the options already shuffled into A/B/C/D and the answer
        # as a letter.
        #
        # A second ungated mirror was rejected after inspection:
        # hendrydong/gpqa_diamond has been converted to FREE-RESPONSE with
        # LaTeX-boxed answers. That is a different task with no 25% guess floor,
        # and scoring it against a published multiple-choice figure would have
        # compared two different benchmarks. Checked before use, not after.
        #
        # Frozen at scripts/bench/datasets-frozen/gpqa_diamond.jsonl,
        # sha256 71991ea576f83033e20ec1e57be0b83b7a909ccab601803416dcf57227faa4f9,
        # 132,103 bytes, 198 rows. Answer distribution A 55 / B 54 / C 48 / D 41.
        # Fetched via the dataset-viewer API, which needs no parquet reader:
        #   https://datasets-server.huggingface.co/rows?dataset=fingertap%2FGPQA-Diamond&config=default&split=test&offset=0&length=100
        #
        # THE SHUFFLE IS THIS MIRROR'S, NOT THE PUBLISHER'S. Option order is
        # fixed here, which makes our runs reproducible, but it is not the order
        # that produced any published score. Position bias is a real effect in
        # language models, so a comparison against a published number inherits
        # an unquantified difference on top of everything else.
        "url": "https://datasets-server.huggingface.co/rows?dataset=fingertap%2FGPQA-Diamond&config=default&split=test&offset=0&length=100",
        "file": "gpqa_diamond.jsonl",
        "frozen_only": True,
    },
    "IFEval": {
        # Zhou et al., "Instruction-Following Evaluation for Large Language
        # Models", arXiv 2311.07911. 541 prompts, 834 instructions, 25
        # verifiable instruction types. Licence: Apache 2.0 — the
        # google-research monorepo's root LICENSE covers
        # instruction_following_eval/ and this data file with it.
        #
        # THE URL IS PINNED TO A COMMIT, not to master. The data file has been
        # edited since publication: commit 26d8ccda (2024-06-11, "Fix an eval
        # prompt") changed exactly one prompt against 066e1eda (2023-11-27) —
        # key 2785 asked for "at least one placeholder" while its kwargs said
        # num_placeholders 3, and the prompt was corrected to match. The kwargs
        # and instruction lists are identical across both commits. So a
        # published IFEval figure predating 2024-06-11 was measured on one
        # differing prompt out of 541; nothing else moved.
        #
        # Frozen at scripts/bench/datasets-frozen/ifeval.jsonl,
        # sha256 67ffeee0fcb87c317c5b08a2de85557b4a7e96ada6178aa645b4954fe4b53d49,
        # 207,111 bytes, 541 rows, LF endings (.gitattributes marks
        # datasets-frozen/** binary, so a Windows clone cannot rewrite them).
        "url": "https://raw.githubusercontent.com/google-research/google-research/26d8ccdab6fec61b5c83ad6327ea8bda9e580288/instruction_following_eval/data/input_data.jsonl",
        "file": "ifeval.jsonl",
    },
}

# ---- membership: the seven, and everything else ----
#
# METHODOLOGY rule 21 fixes the suite at seven benchmarks; rule 23 makes two
# reports comparable IFF their suite hashes match, and bench.py's _suite_hash
# hashes dataset name plus every prompt. So the seven are a CLOSED SET: adding
# one moves the hash and retroactively voids every published comparison.
#
# DATASET_NAMES is that closed set, and it is deliberately not
# `list(SOURCES.keys())` any more. bench.py builds DEFAULTS["datasets"] from it,
# so a set that merely EXISTS in SOURCES used to join every run without
# --rule21, and that run's composite Mean, by existing — GPQA-Diamond, shipped
# frozen and outside the seven, already did. An adjunct is declared here
# instead, and stays out of both the default sweep and the Mean.
RULE21_SETS = ("GSM8K", "MATH-500", "HumanEval", "MBPP", "ALPACA",
               "MeetingBank", "MT-Bench")
ADJUNCT_SETS = ("GPQA-Diamond", "IFEval")

DATASET_NAMES = list(RULE21_SETS)             # the default sweep, the Mean
ALL_DATASET_NAMES = list(RULE21_SETS) + list(ADJUNCT_SETS)   # runnable by name

ADJUNCT_REASON = ("adjunct set: outside METHODOLOGY rule 21's seven, "
                  "never averaged into a composite Mean")

# Register a set in SOURCES and forget to declare it here and the run dies at
# import, on the developer's own machine, with the fix in the message — instead
# of quietly appearing in a Mean three weeks later. Every string this file
# RAISES stays ASCII: a Windows console is cp1252 and mangles the rest.
_undeclared = [n for n in SOURCES if n not in ALL_DATASET_NAMES]
_missing = [n for n in ALL_DATASET_NAMES if n not in SOURCES]
if _undeclared or _missing:
    raise RuntimeError(
        "datasets_io: dataset registration is inconsistent. "
        f"in SOURCES but declared in neither RULE21_SETS nor ADJUNCT_SETS: "
        f"{_undeclared}; declared but absent from SOURCES: {_missing}. "
        "A new set goes in ADJUNCT_SETS: adding it to RULE21_SETS changes "
        "bench.py's suite hash and voids every prior comparison (rule 23).")

# which scorer each set uses (rule 21)
EXACT_MATCH_SETS = ("GSM8K", "MATH-500", "GPQA-Diamond")
EXEC_SETS = ("HumanEval", "MBPP")
ROUGE_SETS = ("MeetingBank",)
JUDGED_SETS = ("ALPACA", "MT-Bench")
VERIFIER_SETS = ("IFEval",)     # deterministic checker, no judge, no model

NO_JUDGE_REASON = "unscored: no independent judge"
NO_EXEC_REASON = "unscored: --no-exec (code execution disabled)"

# rule 21 sizes the server's -c from the longest prompt; 4 chars/token is the
# coarse estimate used for that guard and for the MeetingBank truncation cap
CHARS_PER_TOKEN = 4
DEFAULT_MAX_PROMPT_TOKENS = 8192

EXEC_TIMEOUT_S = 10
ROUGE_MAX_WORDS = 8000          # bounds the O(n*m) LCS on a runaway generation
JUDGE_MAX_ANSWER_CHARS = 24000  # keep one answer inside a judge's own window


def est_tokens(text):
    """Coarse token estimate (4 chars/token) — used for context budgeting only."""
    return (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


def resolve_name(name):
    """Canonical dataset name for a user-typed one, or None. Case-insensitive,
    so --datasets MEETINGBANK and --datasets MeetingBank are the same suite.

    Resolves over ALL_DATASET_NAMES, the seven plus the adjuncts: an adjunct is
    out of the default sweep and out of the Mean, but `--datasets IFEval` and
    `--datasets GPQA-Diamond` still have to work.
    """
    key = name.strip().lower()
    return {n.lower(): n for n in ALL_DATASET_NAMES}.get(key)


def _exists(path):
    return os.path.exists(path) and os.path.getsize(path) > 0


def dataset_path(name):
    """The file to read this dataset from, in METHODOLOGY rule 23's order:
    frozen file -> local cache -> network. The network is a fallback, never a
    dependency, so a dead website or an air-gapped machine can't break a run —
    and the download print is the record of having touched it."""
    frozen = os.path.join(FROZEN_DIR, SOURCES[name]["file"])
    if _exists(frozen):
        return frozen
    return _download(name)


def _download(name):
    src = SOURCES[name]
    path = os.path.join(CACHE_DIR, src["file"])
    if _exists(path):
        return path
    os.makedirs(CACHE_DIR, exist_ok=True)
    print(f"  downloading {name} from {src['url']} "
          f"(no frozen copy in datasets-frozen/) ...")
    r = requests.get(src["url"], timeout=300)
    r.raise_for_status()
    data = r.content
    if src.get("gzip"):
        data = gzip.GzipFile(fileobj=io.BytesIO(data)).read()
    if src.get("json_array"):
        # cache every set in the same JSON-Lines shape, whatever it arrived as
        rows = json.loads(data.decode("utf-8"))
        data = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows).encode("utf-8")
    # write-then-rename so an interrupted download can't leave a partial
    # file that passes the size>0 cache check
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    return path


def _read_jsonl(path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


# ---- prompts ----

MEETING_INSTRUCTION = (
    "Summarize this meeting.\n\nWrite a single-paragraph summary (roughly 60-120 "
    "words) of the transcript below, covering the items discussed and the "
    "decisions taken. Answer with the summary only.\n\n--- TRANSCRIPT ---\n")


def _fit_transcript(transcript, max_prompt_tokens):
    """Head-truncate a transcript so instruction+transcript fits the guard.

    Returns (text, note). max_prompt_tokens <= 0 disables the guard — then the
    operator owns the server's -c sizing (rule 21: -c > longest prompt + cap).
    """
    if max_prompt_tokens and max_prompt_tokens > 0:
        marker = "\n\n[transcript truncated: {} of {} characters shown]"
        budget = (max_prompt_tokens - est_tokens(MEETING_INSTRUCTION)
                  - est_tokens(marker.format(999999, 999999))) * CHARS_PER_TOKEN
        if budget > 0 and len(transcript) > budget:
            kept = transcript[:budget]
            return (kept + marker.format(len(kept), len(transcript)),
                    f"prompt truncated to ~{max_prompt_tokens} tokens "
                    f"({len(kept)} of {len(transcript)} transcript chars kept)")
    return transcript, None


def build_item(name, row, max_prompt_tokens=DEFAULT_MAX_PROMPT_TOKENS):
    """One benchmark item: the user-turn prompt, its reference (None when the
    set has no mechanical ground truth), and a note about how it was built."""
    note = None
    if name == "GSM8K":
        prompt = row["question"] + "\n\nPlease reason step by step, and put your final answer after \"####\"."
    elif name == "MATH-500":
        prompt = row["problem"] + "\n\nPlease reason step by step, and put your final answer within \\boxed{}."
    elif name == "HumanEval":
        prompt = ("Complete the following Python function. Return the full function "
                  "implementation in a single code block.\n\n```python\n" + row["prompt"] + "\n```")
    elif name == "MBPP":
        tests = "\n".join(row.get("test_list", [])[:1])
        prompt = (row["text"] + "\n\nYour code should satisfy this test:\n" + tests +
                  "\n\nReturn the solution in a single Python code block.")
    elif name == "GPQA-Diamond":
        # The row already ends in its four labelled options, so the prompt only
        # has to fix the ANSWER FORMAT. "Answer: X" on its own final line is
        # asked for explicitly because this model reasons at length by default
        # and an unconstrained reply buries the choice in prose, where an
        # extractor has to guess - and a guessing extractor scores the
        # extractor, not the model.
        prompt = (row["question"].rstrip() +
                  "\n\nAnswer with the single letter of the correct option. "
                  "End your reply with a final line in exactly this form:\n"
                  "Answer: X")
    elif name == "IFEval":
        # THE PROMPT SHIPS VERBATIM. Every other set here appends an answer-
        # format instruction; this one must not, because the prompt IS the thing
        # under test. "Answer with the single letter" would add a comma to a
        # punctuation:no_comma item, capitals to a change_case:english_lowercase
        # item and words to a length_constraints:number_words item — the
        # harness would then be scoring its own wrapper.
        prompt = row["prompt"]
    elif name == "ALPACA":
        instruction = (row.get("instruction") or "").strip()
        extra = (row.get("input") or "").strip()
        prompt = instruction + ("\n\n" + extra if extra else "")
    elif name == "MeetingBank":
        transcript, note = _fit_transcript(row.get("transcript") or "",
                                           max_prompt_tokens)
        prompt = MEETING_INSTRUCTION + transcript
    elif name == "MT-Bench":
        prompt = row["turns"][0]
    else:
        raise ValueError(f"unknown dataset {name}")
    return {"prompt": prompt, "ref": reference_answer(name, row), "note": note}


def build_prompt(name, row, max_prompt_tokens=DEFAULT_MAX_PROMPT_TOKENS):
    """Return the user-turn prompt string for one dataset row."""
    return build_item(name, row, max_prompt_tokens)["prompt"]


def reference_answer(name, row):
    """Everything a scorer needs for one row: a string for the exact-match sets,
    a dict for the ones whose scorer needs tests or a reference summary, and
    None where the row carries no ground truth (ALPACA, MT-Bench — judged)."""
    if name == "GSM8K":
        return row["answer"].split("####")[-1].strip()
    if name == "MATH-500":
        return str(row.get("answer", "")).strip() or None
    if name == "HumanEval":
        return {"prompt": row["prompt"], "test": row["test"],
                "entry_point": row["entry_point"]}
    if name == "MBPP":
        return {"test_list": row.get("test_list", []),
                "test_setup_code": row.get("test_setup_code", "")}
    if name == "MeetingBank":
        return {"summary": row.get("summary", ""), "uid": row.get("uid")}
    if name == "GPQA-Diamond":
        a = str(row.get("answer", "")).strip().upper()
        return a if a in ("A", "B", "C", "D") else None
    if name == "IFEval":
        # The reference is the instruction spec, not an answer: ids, their
        # kwargs, and the prompt itself — combination:repeat_prompt is checked
        # against the prompt text, and `key` keeps a failing item traceable to
        # its row in the frozen file.
        return {"key": row.get("key"),
                "instruction_id_list": list(row.get("instruction_id_list") or []),
                "kwargs": [dict(k or {}) for k in (row.get("kwargs") or [])],
                "prompt": row.get("prompt", "")}
    return None


def _evenly_spaced(rows, n_samples):
    """Deterministic subset: evenly spaced indices, no RNG. Pure function of
    (rows, n_samples) — same file + same n -> byte-identical picks anywhere."""
    if n_samples >= len(rows):
        return list(rows)
    step = len(rows) / n_samples
    return [rows[int(i * step)] for i in range(n_samples)]


def load_items(name, n_samples, max_prompt_tokens=DEFAULT_MAX_PROMPT_TOKENS,
               offset=0):
    """Up to n_samples items ({prompt, ref, note}), deterministically spread
    over the dataset. For guaranteed cross-machine fairness, freeze them into a
    suite file (bench.py --freeze-suite) and share that file instead."""
    rows = _read_jsonl(dataset_path(name))
    # OFFSET IS APPLIED BEFORE THE SPACING, and it exists for one reason: a
    # run stopped early leaves a PREFIX, and on a subject-ordered file a
    # prefix is not a sample. gpqa_diamond.jsonl is ordered by subject - 106
    # adjacent same-subject pairs against 48.1 expected, permutation
    # p < 0.00005 - so stopping the anchor at question 100 left quantum at 3
    # of 21 covered and biology at 16 of 16. Running the COMPLEMENT and
    # combining is what removes that, and it needs an offset.
    #
    # The determinism guarantee is unchanged and now reads: same file, same
    # offset, same n_samples -> byte-identical picks on any machine.
    if offset:
        rows = rows[offset:]
    rows = _evenly_spaced(rows, n_samples)
    return [build_item(name, r, max_prompt_tokens) for r in rows]


def load_prompts(name, n_samples, offset=0):
    """Return up to n_samples prompt strings, deterministically spread over the dataset.

    Selection is a pure function of (dataset file, n_samples): evenly spaced
    indices. Same file + same n_samples -> byte-identical prompts on any machine.
    For guaranteed cross-machine fairness, freeze them into a suite file
    (bench.py --freeze-suite) and share that file instead.
    """
    return [it["prompt"] for it in load_items(name, n_samples, offset=offset)]


def load_qa(name, n_samples):
    """Like load_prompts but returns (prompt, reference_answer) pairs;
    the answer is None where the dataset isn't mechanically gradeable."""
    return [(it["prompt"], it["ref"]) for it in load_items(name, n_samples)]


# ---- exact match (GSM8K, MATH-500) ----

def _last_boxed(text):
    """Content of the last \\boxed{...} in text, brace-balanced."""
    i = text.rfind("\\boxed{")
    if i < 0:
        return None
    j = i + len("\\boxed{")
    depth = 1
    out = []
    while j < len(text) and depth:
        ch = text[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if not depth:
                break
        out.append(ch)
        j += 1
    return "".join(out) if not depth else None


# Two spellings of the same value must compare equal, or the scorer measures
# LaTeX style instead of mathematics. Every rewrite below is presentation-only
# and is applied to the prediction AND the reference, so two *different* values
# can never be normalized into a match — only one value written two ways.
_LATEX_SYNONYMS = (("\\dfrac", "\\frac"), ("\\tfrac", "\\frac"),
                   ("\\dbinom", "\\binom"), ("\\tbinom", "\\binom"))
# markup that carries no value: spacing macros and the unit marks a reference
# spells out but an answer often doesn't (145 vs 145^\circ)
_LATEX_JUNK = ("\\left", "\\right", "\\!", "\\,", "\\;", "\\:",
               "\\quad", "\\qquad", "~", "^\\circ", "^{\\circ}", "\\degree",
               "°", "\\%", "%", "\\$")
# "\ " is a thin space, but the second half of a "\\ " row break is not one:
# stripping that blindly turns a matrix's \\ separator into a single backslash
_THIN_SPACE = re.compile(r"(?<!\\)\\ ")
_GSM8K_NUMBER = re.compile(r"-?\d[\d,]*\.?\d*")       # the number in "#### 156 kg"
_WHITESPACE = re.compile(r"\s+")
_ROW_SPACING = re.compile(r"\\\\\[[^\]]*\]")          # \\[6pt] between rows
_INT_FRAC = re.compile(r"(?<![\d/])(\d+)/(\d+)(?![\d/])")   # 16/49 -> \frac{16}{49}


def _norm_answer(s):
    """Canonical form of one answer string, for exact match.

    The spacing macros are stripped *before* whitespace is squeezed out: "\\ "
    is backslash-space, so removing spaces first would leave a bare backslash
    behind and (6,\\ 31,\\ -1) would never match (6,31,-1).
    """
    s = s.strip()
    for a, b in _LATEX_SYNONYMS:
        s = s.replace(a, b)
    s = _ROW_SPACING.sub(lambda m: "\\\\", s)
    s = _THIN_SPACE.sub("", s)
    for junk in _LATEX_JUNK:
        s = s.replace(junk, "")
    s = s.replace("$", "").replace(",", "")
    # all whitespace, not just spaces: a boxed matrix is often laid out over
    # several lines, and a newline is layout, never value
    s = _WHITESPACE.sub("", s)
    s = _INT_FRAC.sub(lambda m: "\\frac{%s}{%s}" % (m.group(1), m.group(2)), s)
    return s.rstrip(".")


def grade(name, response, ref):
    """True/False: does the model's response match the reference answer?"""
    if ref is None or not isinstance(ref, str):
        return None
    if name == "GSM8K":
        if "####" in response:
            # the tail after "####" can be EMPTY — a response ending in a bare
            # "####" (first seen from a 2.15-bpw quant) grades wrong, never
            # crashes the scorer
            tail = response.rsplit("####", 1)[-1].strip().splitlines()
            pred = tail[0] if tail else ""
            # GSM8K references are bare numbers, but a model that reasoned in
            # units answers "#### 156 kg" or "#### 5 hours". Take the number
            # out of the answer line, as the canonical GSM8K scorer does —
            # comparing the whole line marks a right answer wrong.
            m = _GSM8K_NUMBER.search(pred)
            if m:
                pred = m.group(0)
        else:
            nums = re.findall(r"-?\d[\d,]*\.?\d*", response)
            pred = nums[-1] if nums else ""
    elif name == "MATH-500":
        pred = _last_boxed(response) or ""
    elif name == "GPQA-Diamond":
        return _grade_choice(response, ref)
    else:
        return None
    a, b = _norm_answer(pred), _norm_answer(ref)
    if a == b:
        return True
    try:
        return abs(float(a) - float(b)) < 1e-6
    except (TypeError, ValueError):
        return False


# Leading markdown is tolerated as well as trailing. Models bold their
# conclusion as **Answer: D**, and a pattern that allowed only the trailing
# asterisks scored that as unparsed - a failure that would have been charged to
# the model rather than to this regex.
_CHOICE_TAGGED = re.compile(
    r"(?:^|\n)[\s*_#>]*(?:final\s+)?answer\s*[:\-]?\s*[\(\[]?\*{0,2}([ABCD])\b",
    re.IGNORECASE)
_CHOICE_BARE = re.compile(r"(?:^|\n)\s*\(?\*{0,2}([ABCD])[\.\)\*\s]*$",
                          re.MULTILINE)


def _grade_choice(response, ref):
    """Did the model pick the right option letter?

    Returns True or False. None is returned ONLY when the row carries no
    reference answer - a data fault, not a model fault - because the harness
    drops None-scored items from the denominator entirely
    (accuracy = sum(scores)/len(graded)).

    AN UNREADABLE ANSWER IS SCORED WRONG, DELIBERATELY. On a four-option
    question a reply the extractor cannot resolve is a failure to answer, and
    the published figures this is meant to be compared against are means over
    all 198 questions. Returning None here would silently shrink the
    denominator and inflate the score by exactly the rate at which the model
    ignores the requested format - the one failure most likely to correlate
    with a broken chat template, which is what this benchmark exists to detect.
    OpenAI's simple-evals scores an unextractable multiple-choice answer as
    incorrect for the same reason.

    The diagnostic is preserved elsewhere: run with transcripts kept, and the
    unparsed rate can be recovered by re-running this extractor over them. A
    high rate means the prompt or the template is wrong, not that the model is
    poor, and it must be checked before any score from this set is quoted.

    THINKING IS STRIPPED FIRST. This model reasons inside <think> blocks by
    default, and that reasoning routinely contains sentences like "so the answer
    would be B" on the way to rejecting B. Scoring the visible reply only is the
    difference between grading the model's answer and grading its scratch work.

    Extraction runs in order of how much the model committed to the choice:
      1. a tagged final answer - "Answer: C", "final answer: (C)", "Answer - C"
      2. a bare letter alone on the last line
    The LAST match wins in both cases, because a reply that revises itself ends
    on its conclusion.
    """
    if ref is None:
        return None
    body = strip_think(response or "")
    pred = None
    m = list(_CHOICE_TAGGED.finditer(body))
    if m:
        pred = m[-1].group(1).upper()
    else:
        m = list(_CHOICE_BARE.finditer(body.rstrip()))
        if m:
            pred = m[-1].group(1).upper()
    if pred is None:
        return False
    return pred == str(ref).strip().upper()


# ---- ROUGE-L (MeetingBank) ----

_WORD = re.compile(r"[a-z0-9]+")


def rouge_l(candidate, reference):
    """ROUGE-L F1 in 0.0-1.0: the longest common subsequence of the two word
    sequences, harmonic-meaned over precision and recall.

    Same definition as the `rouge_score` package's rougeL fmeasure (lowercased,
    non-alphanumerics dropped, no stemming), implemented here so the harness
    keeps its two-dependency footprint. The LCS table rolls one row at a time:
    O(len(cand) * len(ref)) time, O(len(ref)) memory.
    """
    cand = _WORD.findall((candidate or "").lower())[:ROUGE_MAX_WORDS]
    ref = _WORD.findall((reference or "").lower())[:ROUGE_MAX_WORDS]
    if not cand or not ref:
        return 0.0
    prev = [0] * (len(ref) + 1)
    for c in cand:
        cur = [0]
        for j, r in enumerate(ref):
            cur.append(prev[j] + 1 if c == r else max(cur[j], prev[j + 1]))
        prev = cur
    lcs = prev[-1]
    if not lcs:
        return 0.0
    precision, recall = lcs / len(cand), lcs / len(ref)
    return 2 * precision * recall / (precision + recall)


# ---- execution pass@1 (HumanEval, MBPP) ----

_FENCE = re.compile(r"```[ \t]*([A-Za-z0-9_+#-]*)[ \t]*\r?\n(.*?)```", re.S)


def _trim_blank_lines(text):
    """Drop blank lines at both ends but keep the first content line's
    indentation — a bare HumanEval continuation only assembles onto its prompt
    if it stays indented."""
    lines = text.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines).rstrip()


def strip_think(text):
    """Drop chain-of-thought so a scorer only ever sees the final answer.
    With --jinja llama-server already splits thinking into reasoning_content;
    this catches models that inline the block anyway."""
    text = text or ""
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[-1]
    if "<think>" in text:  # unterminated: the tail is all thinking
        text = text.split("<think>", 1)[0]
    return _trim_blank_lines(text)


def extract_code(text):
    """The final Python source out of a chat answer: think blocks dropped, then
    the largest fenced block that looks like code (models often print a usage
    example beside the solution); the whole answer if it was never fenced."""
    text = strip_think(text)
    blocks = [b for lang, b in _FENCE.findall(text)
              if lang.lower() in ("", "python", "py", "python3")]
    if not blocks:
        blocks = [b for _, b in _FENCE.findall(text)]
    code_like = [b for b in blocks if re.search(r"^\s*(def |class |import |from )", b, re.M)]
    pool = code_like or blocks
    return max(pool, key=len).strip("\n") if pool else text


def run_program(source, timeout=EXEC_TIMEOUT_S):
    """Run one generated program in a throwaway directory; True iff it exits 0.

    This executes model-written code on this machine. That is deliberate — the
    operator started the benchmark — but it is NOT a security sandbox: the child
    is a plain interpreter in isolated mode (-I -E: no PYTHONPATH, no user
    site-packages, no cwd on sys.path), stdin closed so input() fails instead of
    hanging, a 10 s wall clock, and a temp cwd that is deleted afterwards.
    bench.py --no-exec turns HumanEval and MBPP back into unscored runs.
    """
    with tempfile.TemporaryDirectory(prefix="bench_exec_") as tmp:
        path = os.path.join(tmp, "prog.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write(source)
        try:
            r = subprocess.run([sys.executable, "-I", "-E", path], cwd=tmp,
                               stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               timeout=timeout)
        except (subprocess.TimeoutExpired, OSError, ValueError):
            return False
        return r.returncode == 0


def build_test_program(name, response, ref):
    """The self-checking program for one generated answer: solution + the
    dataset's own tests. Exit code 0 means the sample passed."""
    code = extract_code(response)
    if name == "HumanEval":
        # prompt first: it carries the imports and the signature, so a bare
        # indented continuation attaches to it and a full re-definition
        # shadows it — both shapes of answer assemble into valid Python
        return (ref["prompt"] + "\n" + code + "\n\n" + ref["test"] +
                f"\n\ncheck({ref['entry_point']})\n")
    if name == "MBPP":
        parts = [code, ""]
        if ref.get("test_setup_code"):
            parts.append(ref["test_setup_code"])
        parts.extend(ref.get("test_list") or [])
        return "\n".join(parts) + "\n"
    raise ValueError(f"{name} has no execution tests")


def pass_at_1(name, response, ref):
    """1.0 if the generated code passes every test for this sample, else 0.0."""
    try:
        program = build_test_program(name, response, ref)
    except (KeyError, TypeError, ValueError):
        return 0.0
    return 1.0 if run_program(program) else 0.0


# ---- IFEval: a deterministic instruction verifier (adjunct set) ----
#
# Zhou et al., arXiv 2311.07911. 541 prompts carrying 834 instructions of 25
# verifiable types ("write at least 300 words", "no commas", "end with this
# exact phrase"). Nothing below calls a model or a judge, which is why this set
# is affordable at its full published size — rule 6 makes accuracy at n<=25 a
# smoke test, so a benchmark truncated to 25 items buys almost nothing, and this
# one never has to be.
#
# NOT A BYTE-FOR-BYTE PORT, and the differences are listed here and in
# README.md because a divergence a reader cannot see gets charged to the model.
# The official implementation (google-research/instruction_following_eval)
# reaches the network at SCORING time — nltk.data.load("nltk:tokenizers/punkt/
# english.pickle") for sentence counting and word tokenising, langdetect for the
# three language checks — and rule 23 forbids that. Both are replaced with
# deterministic offline code:
#
#   1. SENTENCES. Upstream count_sentences() is punkt. Here it is the regex
#      splitter that the same upstream module already ships
#      (instructions_util.split_into_sentences, used there for a disabled
#      instruction type), ported unchanged. Its disagreement rate against punkt
#      is UNMEASURED on this machine: nltk is not installed, and fetching the
#      pickle to measure it is the thing rule 23 forbids. Reaches
#      length_constraints:number_sentences — 52 of 834 instructions, on 46 of
#      the 541 prompts.
#   2. LANGUAGE. Upstream is langdetect, which is itself nondeterministic unless
#      langdetect.DetectorFactory.seed is set, and the official scorer does not
#      set it. Here: dominant Unicode script, then a marker tie-break among the
#      languages sharing that script, and the target passes when no competing
#      same-script language outscores it. That is the LENIENT direction wherever
#      two languages share a script and the reply carries no discriminating
#      marker. Reaches language:response_language (31 instructions),
#      change_case:english_capital (25) and change_case:english_lowercase (39).
#   3. WORD TOKENS. change_case:capital_word_frequency counts tokens through
#      nltk.word_tokenize (Treebank) upstream. Here a Unicode word regex that
#      keeps hyphens, apostrophes and internal periods together — which matches
#      upstream's own "hyphenated words will count as one word" comment and
#      differs on clitics: "DON'T" is one token here and two under Treebank.
#      Reaches 25 instructions.
#   4. OUT-OF-RANGE LETTERS. keywords:letter_frequency upstream rejects any
#      letter outside a-z and substitutes random.choice(string.ascii_letters),
#      unseeded — so on those items the official scorer grades a different,
#      random constraint on every run. Two of the 541 prompts are affected: key
#      1122 asks for four '#' hashtags, key 1129 for six '!' marks. Here the
#      character the prompt names is counted.
#
# The frozen file is scored on the STRIPPED reply (strip_think), as every other
# scorer in this module is: a <think> block is full of commas, capitals and
# words, and scoring it would fail punctuation:no_comma on a model that got the
# answer right.

# The published number, pinned. IFEval defines four: prompt-level and
# instruction-level, each strict and loose. This repo publishes prompt-level
# strict and labels it, because an unpinned choice is how two runs stop being
# comparable, and because the harness averages one score per item — prompt-level
# IS that mean, while instruction-level needs a weighting by the 1-3 instructions
# each prompt carries and cannot come out of this plumbing correctly.
IFEVAL_PUBLISHED = "prompt-level strict"

IFEVAL_RELATIONS = ("less than", "at least")
IFEVAL_CONSTRAINED_RESPONSES = ("My answer is yes.", "My answer is no.",
                                "My answer is maybe.")

# --- upstream's own sentence splitter, ported (divergence 1) ---
_IF_ALPHABETS = "([A-Za-z])"
_IF_PREFIXES = "(Mr|St|Mrs|Ms|Dr)[.]"
_IF_SUFFIXES = "(Inc|Ltd|Jr|Sr|Co)"
_IF_STARTERS = (r"(Mr|Mrs|Ms|Dr|Prof|Capt|Cpt|Lt|He\s|She\s|It\s|They\s|"
                r"Their\s|Our\s|We\s|But\s|However\s|That\s|This\s|Wherever)")
_IF_ACRONYMS = "([A-Z][.][A-Z][.](?:[A-Z][.])?)"
_IF_WEBSITES = "[.](com|net|org|io|gov|edu|me)"
_IF_DIGITS = "([0-9])"
_IF_MULTIPLE_DOTS = r"\.{2,}"


def ifeval_split_sentences(text):
    """Sentences of `text`, by the regex splitter upstream ships.

    Transcribed from instruction_following_eval/instructions_util.py
    (Apache 2.0) so that counting sentences needs no punkt pickle and no
    network at scoring time.
    """
    text = " " + text + "  "
    text = text.replace("\n", " ")
    text = re.sub(_IF_PREFIXES, "\\1<prd>", text)
    text = re.sub(_IF_WEBSITES, "<prd>\\1", text)
    text = re.sub(_IF_DIGITS + "[.]" + _IF_DIGITS, "\\1<prd>\\2", text)
    text = re.sub(_IF_MULTIPLE_DOTS,
                  lambda m: "<prd>" * len(m.group(0)) + "<stop>", text)
    if "Ph.D" in text:
        text = text.replace("Ph.D.", "Ph<prd>D<prd>")
    text = re.sub(r"\s" + _IF_ALPHABETS + "[.] ", " \\1<prd> ", text)
    text = re.sub(_IF_ACRONYMS + " " + _IF_STARTERS, "\\1<stop> \\2", text)
    text = re.sub(_IF_ALPHABETS + "[.]" + _IF_ALPHABETS + "[.]"
                  + _IF_ALPHABETS + "[.]", "\\1<prd>\\2<prd>\\3<prd>", text)
    text = re.sub(_IF_ALPHABETS + "[.]" + _IF_ALPHABETS + "[.]",
                  "\\1<prd>\\2<prd>", text)
    text = re.sub(" " + _IF_SUFFIXES + "[.] " + _IF_STARTERS,
                  " \\1<stop> \\2", text)
    text = re.sub(" " + _IF_SUFFIXES + "[.]", " \\1<prd>", text)
    text = re.sub(" " + _IF_ALPHABETS + "[.]", " \\1<prd>", text)
    if "”" in text:
        text = text.replace(".”", "”.")
    if '"' in text:
        text = text.replace('."', '".')
    if "!" in text:
        text = text.replace('!"', '"!')
    if "?" in text:
        text = text.replace('?"', '"?')
    text = text.replace(".", ".<stop>")
    text = text.replace("?", "?<stop>")
    text = text.replace("!", "!<stop>")
    text = text.replace("<prd>", ".")
    sentences = [s.strip() for s in text.split("<stop>")]
    if sentences and not sentences[-1]:
        sentences = sentences[:-1]
    return sentences


def ifeval_count_words(text):
    """Word count, identical to upstream's nltk RegexpTokenizer(r"\\w+")."""
    return len(re.findall(r"\w+", text))


# Treebank keeps a hyphenated word whole and splits a clitic; this keeps both
# whole. Only change_case:capital_word_frequency reads it (divergence 3).
_IF_WORD_TOKEN = re.compile(r"\w+(?:[-'’.]\w+)*")

# --- language, without langdetect (divergence 2) ---
#
# Script ranges first, exactly and with no model: 8 of the 22 languages the
# frozen file asks for own their script outright (bn, gu, kn, ko, pa, ta, te,
# th). The other 14 share one — hi/mr/ne, ar/fa/ur, ru/bg, and six in Latin —
# and go to the marker tie-break below.
_IF_SCRIPTS = (
    ("latin", ((0x0041, 0x005A), (0x0061, 0x007A), (0x00C0, 0x024F),
               (0x1E00, 0x1EFF))),
    ("cyrillic", ((0x0400, 0x052F),)),
    ("hebrew", ((0x0590, 0x05FF),)),
    ("arabic", ((0x0600, 0x06FF), (0x0750, 0x077F), (0xFB50, 0xFDFF),
                (0xFE70, 0xFEFF))),
    ("devanagari", ((0x0900, 0x097F),)),
    ("bengali", ((0x0980, 0x09FF),)),
    ("gurmukhi", ((0x0A00, 0x0A7F),)),
    ("gujarati", ((0x0A80, 0x0AFF),)),
    ("tamil", ((0x0B80, 0x0BFF),)),
    ("telugu", ((0x0C00, 0x0C7F),)),
    ("kannada", ((0x0C80, 0x0CFF),)),
    ("malayalam", ((0x0D00, 0x0D7F),)),
    ("thai", ((0x0E00, 0x0E7F),)),
    ("hangul", ((0x1100, 0x11FF), (0x3130, 0x318F), (0xAC00, 0xD7AF))),
    ("kana", ((0x3040, 0x30FF),)),
    ("han", ((0x4E00, 0x9FFF),)),
)

# The 30 ISO 639-1 codes upstream's LANGUAGE_CODES table defines, grouped by the
# script they are written in. A code absent from that table cannot appear in the
# data, so it is absent here too.
_IF_SCRIPT_LANGS = {
    "latin": ("en", "es", "pt", "fr", "de", "it", "pl", "vi", "sw", "fi"),
    "cyrillic": ("ru", "uk", "bg"),
    "arabic": ("ar", "fa", "ur"),
    "devanagari": ("hi", "mr", "ne"),
    "hebrew": ("he",), "bengali": ("bn",), "gurmukhi": ("pa",),
    "gujarati": ("gu",), "tamil": ("ta",), "telugu": ("te",),
    "kannada": ("kn",), "malayalam": ("ml",), "thai": ("th",),
    "hangul": ("ko",), "kana": ("ja",), "han": ("ja",),
}

# (distinctive characters, distinctive function words) per language, used only
# to separate languages that share a script. A character costs 1, a word 2.
_IF_LANG_MARKERS = {
    "en": ('',
           ('the', 'and', 'of', 'to', 'in', 'is', 'that', 'for', 'with', 'this',
            'you', 'not')),
    "es": ('ñ¿¡',
           ('el', 'la', 'los', 'las', 'una', 'por', 'para', 'con', 'es', 'pero')),
    "pt": ('ãõç',
           ('de', 'que', 'não', 'uma', 'dos', 'das', 'para', 'com', 'mais',
            'são')),
    "fr": ('çàèêœ',
           ('le', 'les', 'des', 'une', 'est', 'dans', 'pour', 'qui', 'vous',
            'sont')),
    "de": ('äöüß',
           ('der', 'die', 'das', 'und', 'ist', 'nicht', 'ein', 'eine', 'mit',
            'auch', 'sich')),
    "it": ('àèìòù',
           ('il', 'di', 'che', 'una', 'per', 'con', 'non', 'sono', 'della',
            'gli')),
    "pl": ('ąęłńśźż',
           ('nie', 'jest', 'się', 'że', 'dla', 'jak', 'przez')),
    "vi": ('ăâđêôơư',
           ('và', 'của', 'là', 'có', 'không', 'được', 'một', 'trong')),
    "sw": ('',
           ('na', 'ya', 'kwa', 'ni', 'katika', 'wa', 'kuwa', 'hii', 'zaidi')),
    "fi": ('äö',
           ('ja', 'on', 'ei', 'että', 'ovat', 'kuin', 'myös', 'olla', 'sekä')),
    "ru": ('ыэё',
           ('и', 'не', 'что', 'это', 'как', 'для')),
    "uk": ('іїєґ',
           ('та', 'що', 'не', 'для')),
    "bg": ('',
           ('и', 'на', 'за', 'да', 'се', 'от', 'като', 'това')),
    "hi": ('',
           ('है', 'हैं', 'का', 'की', 'के', 'और', 'में', 'नहीं')),
    "mr": ('ळ',
           ('आहे', 'आणि', 'मध्ये', 'नाही', 'त्या')),
    "ne": ('',
           ('छ', 'हो', 'र', 'गर्न', 'भएको', 'लागि')),
    "ar": ('ةيك',
           ('في', 'من', 'على', 'هذا', 'التي', 'إلى')),
    "fa": ('گچپژ',
           ('است', 'را', 'می', 'این', 'برای', 'های')),
    "ur": ('ٹڈڑںھے',
           ('ہے', 'کے', 'کو', 'میں', 'اور', 'سے')),
}

# Word-splitting for the marker test only. Python's \w does not match a
# Devanagari vowel sign — a combining mark is not alnum — so re.findall(r"\w+")
# over a Hindi sentence returns the consonants with their matras stripped, and a
# marker word would never match. Splitting on whitespace and trimming edge
# punctuation (the danda included) keeps every mark attached to its consonant.
_IF_EDGE_PUNCT = " \t\r\n.,;:!?।॥؟،()[]{}\"'“”‘’*_#-"


def _ifeval_dominant_script(text):
    """The script most of `text` is written in, or None when it has no letters."""
    counts = {}
    for ch in text:
        code = ord(ch)
        for script, ranges in _IF_SCRIPTS:
            if any(lo <= code <= hi for lo, hi in ranges):
                counts[script] = counts.get(script, 0) + 1
                break
    if not counts:
        return None
    return max(sorted(counts), key=counts.get)


def _ifeval_marker_score(text, lang):
    chars, words = _IF_LANG_MARKERS.get(lang, ("", ()))
    lowered = text.lower()
    tokens = {t.strip(_IF_EDGE_PUNCT) for t in lowered.split()}
    return (sum(1 for c in chars if c in lowered)
            + 2 * sum(1 for w in words if w in tokens))


def ifeval_language_matches(text, target):
    """Is `text` written in ISO 639-1 language `target`?

    Script decides the family; markers decide inside a family. A target that
    ties for the best marker score PASSES — absence of evidence is not evidence
    of another language, and the alternative is charging the model for this
    file's short stopword lists. Twelve of the sixteen scripts carry a single
    candidate — Bengali, Thai, Kannada and Hangul among them — and there the
    answer is exact; Latin, Cyrillic, Arabic and Devanagari are the four that
    need the tie-break.

    A text with no letters at all returns True: upstream counts a response that
    langdetect cannot read as following the instruction, and this keeps that.
    """
    script = _ifeval_dominant_script(text)
    if script is None:
        return True
    candidates = _IF_SCRIPT_LANGS.get(script, ())
    if target not in candidates:
        return False
    if len(candidates) == 1:
        return True
    scores = {c: _ifeval_marker_score(text, c) for c in candidates}
    return scores[target] >= max(scores.values())


def _ifeval_relation(actual, threshold, relation):
    if relation == IFEVAL_RELATIONS[0]:
        return actual < threshold
    if relation == IFEVAL_RELATIONS[1]:
        return actual >= threshold
    raise ValueError(f"IFEval: relation must be one of {IFEVAL_RELATIONS}, "
                     f"got {relation!r}: the frozen file and this verifier "
                     "disagree; fix the input, do not paper over it")


def _ifeval_search(pattern, value, flags=re.IGNORECASE):
    """Upstream matches a keyword as a REGEX, not as a literal, so a keyword
    carrying a metacharacter changes what is checked. No keyword in the frozen
    file carries one (verified over all 834 instructions), so this is identical
    on that file; the fallback only stops a hand-edited keyword crashing a run
    that has already cost GPU hours."""
    try:
        return re.search(pattern, value, flags)
    except re.error:
        return re.search(re.escape(pattern), value, flags)


def _ifeval_findall(pattern, value, flags=re.IGNORECASE):
    try:
        return re.findall(pattern, value, flags)
    except re.error:
        return re.findall(re.escape(pattern), value, flags)


# --- the 25 checkers ---

def _if_keywords_existence(v, kw, prompt):
    return all(_ifeval_search(k, v) for k in kw["keywords"])


def _if_keywords_frequency(v, kw, prompt):
    n = len(_ifeval_findall(kw["keyword"].strip(), v))
    return _ifeval_relation(n, kw["frequency"], kw["relation"])


def _if_keywords_forbidden(v, kw, prompt):
    return not any(_ifeval_search(r"\b" + w + r"\b", v)
                   for w in kw["forbidden_words"])


def _if_keywords_letter_frequency(v, kw, prompt):
    letter = kw["letter"].strip().lower()
    return _ifeval_relation(v.lower().count(letter), kw["let_frequency"],
                            kw["let_relation"])


def _if_language(v, kw, prompt):
    return ifeval_language_matches(v, kw["language"])


def _if_number_sentences(v, kw, prompt):
    return _ifeval_relation(len(ifeval_split_sentences(v)),
                            kw["num_sentences"], kw["relation"])


def _if_number_paragraphs(v, kw, prompt):
    paragraphs = re.split(r"\s?\*\*\*\s?", v)
    n = len(paragraphs)
    for index, paragraph in enumerate(paragraphs):
        if not paragraph.strip():
            if index == 0 or index == len(paragraphs) - 1:
                n -= 1
            else:
                return False
    return n == kw["num_paragraphs"]


def _if_number_words(v, kw, prompt):
    return _ifeval_relation(ifeval_count_words(v), kw["num_words"],
                            kw["relation"])


def _if_nth_paragraph_first_word(v, kw, prompt):
    paragraphs = re.split(r"\n\n", v)
    n = len(paragraphs)
    for paragraph in paragraphs:
        if not paragraph.strip():
            n -= 1
    nth = kw["nth_paragraph"]
    if nth > n:
        return False
    paragraph = paragraphs[nth - 1].strip()
    if not paragraph:
        return False
    word = paragraph.split()[0].strip().lstrip("'").lstrip('"')
    first_word = ""
    for letter in word:
        if letter in {".", ",", "?", "!", "'", '"'}:
            break
        first_word += letter.lower()
    return n == kw["num_paragraphs"] and first_word == kw["first_word"].lower()


def _if_placeholders(v, kw, prompt):
    return len(re.findall(r"\[.*?\]", v)) >= kw["num_placeholders"]


def _if_postscript(v, kw, prompt):
    marker = kw["postscript_marker"].strip()
    v = v.lower()
    if marker == "P.P.S":
        pattern = r"\s*p\.\s?p\.\s?s.*$"
    elif marker == "P.S.":
        pattern = r"\s*p\.\s?s\..*$"
    else:
        pattern = r"\s*" + marker.lower() + r".*$"
    return bool(re.findall(pattern, v, flags=re.MULTILINE))


def _if_bullet_lists(v, kw, prompt):
    n = (len(re.findall(r"^\s*\*[^\*].*$", v, flags=re.MULTILINE))
         + len(re.findall(r"^\s*-.*$", v, flags=re.MULTILINE)))
    return n == kw["num_bullets"]


def _if_constrained_response(v, kw, prompt):
    v = v.strip()
    return any(option in v for option in IFEVAL_CONSTRAINED_RESPONSES)


def _if_highlighted_sections(v, kw, prompt):
    n = 0
    for highlight in re.findall(r"\*[^\n\*]*\*", v):
        if highlight.strip("*").strip():
            n += 1
    for highlight in re.findall(r"\*\*[^\n\*]*\*\*", v):
        if highlight.removeprefix("**").removesuffix("**").strip():
            n += 1
    return n >= kw["num_highlights"]


def _if_multiple_sections(v, kw, prompt):
    pattern = r"\s?" + kw["section_spliter"].strip() + r"\s?\d+\s?"
    return len(re.split(pattern, v)) - 1 >= kw["num_sections"]


def _if_json_format(v, kw, prompt):
    v = (v.strip().removeprefix("```json").removeprefix("```Json")
         .removeprefix("```JSON").removeprefix("```").removesuffix("```")
         .strip())
    try:
        json.loads(v)
    except ValueError:
        return False
    return True


def _if_title(v, kw, prompt):
    return any(t.lstrip("<").rstrip(">").strip()
               for t in re.findall(r"<<[^\n]+>>", v))


def _if_two_responses(v, kw, prompt):
    valid = []
    responses = v.split("******")
    for index, response in enumerate(responses):
        if not response.strip():
            if index != 0 and index != len(responses) - 1:
                return False
        else:
            valid.append(response)
    return len(valid) == 2 and valid[0].strip() != valid[1].strip()


def _if_repeat_prompt(v, kw, prompt):
    to_repeat = kw.get("prompt_to_repeat") or prompt or ""
    return v.strip().lower().startswith(to_repeat.strip().lower())


def _if_end_checker(v, kw, prompt):
    return v.strip().strip('"').lower().endswith(
        kw["end_phrase"].strip().lower())


def _if_capital_word_frequency(v, kw, prompt):
    n = sum(1 for w in _IF_WORD_TOKEN.findall(v) if w.isupper())
    return _ifeval_relation(n, kw["capital_frequency"], kw["capital_relation"])


def _if_english_capital(v, kw, prompt):
    return v.isupper() and ifeval_language_matches(v, "en")


def _if_english_lowercase(v, kw, prompt):
    return v.islower() and ifeval_language_matches(v, "en")


def _if_no_comma(v, kw, prompt):
    # ASCII comma only, exactly as upstream: a fullwidth comma passes there too,
    # and matching the reference matters more here than being stricter than it.
    return not re.search(r"\,", v)


def _if_quotation(v, kw, prompt):
    v = v.strip()
    return len(v) > 1 and v[0] == '"' and v[-1] == '"'


IFEVAL_CHECKERS = {
    "keywords:existence": _if_keywords_existence,
    "keywords:frequency": _if_keywords_frequency,
    "keywords:forbidden_words": _if_keywords_forbidden,
    "keywords:letter_frequency": _if_keywords_letter_frequency,
    "language:response_language": _if_language,
    "length_constraints:number_sentences": _if_number_sentences,
    "length_constraints:number_paragraphs": _if_number_paragraphs,
    "length_constraints:number_words": _if_number_words,
    "length_constraints:nth_paragraph_first_word": _if_nth_paragraph_first_word,
    "detectable_content:number_placeholders": _if_placeholders,
    "detectable_content:postscript": _if_postscript,
    "detectable_format:number_bullet_lists": _if_bullet_lists,
    "detectable_format:constrained_response": _if_constrained_response,
    "detectable_format:number_highlighted_sections": _if_highlighted_sections,
    "detectable_format:multiple_sections": _if_multiple_sections,
    "detectable_format:json_format": _if_json_format,
    "detectable_format:title": _if_title,
    "combination:two_responses": _if_two_responses,
    "combination:repeat_prompt": _if_repeat_prompt,
    "startend:end_checker": _if_end_checker,
    "change_case:capital_word_frequency": _if_capital_word_frequency,
    "change_case:english_capital": _if_english_capital,
    "change_case:english_lowercase": _if_english_lowercase,
    "punctuation:no_comma": _if_no_comma,
    "startend:quotation": _if_quotation,
}


def ifeval_follows(instruction_id, kwargs, value, prompt=None):
    """Does `value` satisfy one instruction? True/False.

    An unknown instruction id RAISES. The frozen file and this table are checked
    against each other by --ifeval-dry-run, so the only way here is a newer or
    hand-edited data file, and scoring an unchecked constraint as "not followed"
    would charge a harness fault to the model.
    """
    checker = IFEVAL_CHECKERS.get(instruction_id)
    if checker is None:
        raise ValueError(
            f"IFEval: no checker for instruction {instruction_id!r}. The data "
            f"file carries an instruction type this verifier does not "
            f"implement; add it to IFEVAL_CHECKERS or the run scores a "
            f"constraint nobody checked.")
    return bool(checker(value, kwargs, prompt))


def _ifeval_loose_variants(response):
    """The eight responses upstream's LOOSE pass tries, in its order."""
    lines = response.split("\n")
    remove_first = "\n".join(lines[1:]).strip()
    remove_last = "\n".join(lines[:-1]).strip()
    remove_both = "\n".join(lines[1:-1]).strip()
    return [response, response.replace("*", ""), remove_first, remove_last,
            remove_both, remove_first.replace("*", ""),
            remove_last.replace("*", ""), remove_both.replace("*", "")]


def ifeval_grade(response, ref):
    """Both IFEval passes over one response, or None when the row carries no
    instructions.

    Returns {"key", "instruction_ids", "strict", "loose", "prompt_strict",
    "prompt_loose"} — per-instruction booleans plus the two prompt-level
    verdicts, so instruction-level numbers stay recoverable from a run's
    transcripts even though prompt-level strict is the published one.
    """
    if not isinstance(ref, dict):
        return None
    ids = ref.get("instruction_id_list") or []
    kwargs = ref.get("kwargs") or []
    if not ids or len(ids) != len(kwargs):
        return None
    prompt = ref.get("prompt")
    body = strip_think(response or "")
    variants = _ifeval_loose_variants(body)
    strict, loose = [], []
    for instruction_id, kw in zip(ids, kwargs):
        strict.append(bool(body.strip())
                      and ifeval_follows(instruction_id, kw, body, prompt))
        loose.append(any(v.strip()
                         and ifeval_follows(instruction_id, kw, v, prompt)
                         for v in variants))
    return {"key": ref.get("key"), "instruction_ids": list(ids),
            "strict": strict, "loose": loose,
            "prompt_strict": all(strict), "prompt_loose": all(loose)}


def ifeval_report(graded):
    """All four IFEval numbers over a list of ifeval_grade() results.

    The published one is prompt-level strict (IFEVAL_PUBLISHED); the other three
    ride along as diagnostics and must be labeled as such wherever they appear.
    """
    graded = [g for g in graded if g]
    if not graded:
        return None
    flat = [(i, s, l) for g in graded
            for i, s, l in zip(g["instruction_ids"], g["strict"], g["loose"])]
    by_type = {}
    for instruction_id, s, l in flat:
        row = by_type.setdefault(instruction_id, {"n": 0, "strict": 0, "loose": 0})
        row["n"] += 1
        row["strict"] += bool(s)
        row["loose"] += bool(l)
    return {
        "published": IFEVAL_PUBLISHED,
        "prompt_strict": round(100.0 * sum(g["prompt_strict"] for g in graded)
                               / len(graded), 1),
        "prompt_loose": round(100.0 * sum(g["prompt_loose"] for g in graded)
                              / len(graded), 1),
        "instruction_strict": round(100.0 * sum(s for _, s, _ in flat)
                                    / len(flat), 1),
        "instruction_loose": round(100.0 * sum(l for _, _, l in flat)
                                   / len(flat), 1),
        "n_prompts": len(graded), "n_instructions": len(flat),
        "by_instruction_type": by_type,
    }


# ---- judge (ALPACA, MT-Bench) ----

class Judge:
    """An independent OpenAI-compatible endpoint that rates answers 1-10.

    A model must never judge its own outputs (METHODOLOGY rule 21) — bench.py
    refuses a judge URL pointing at the server under test unless
    --allow-self-judge is passed, and records the fact either way.
    """

    # MT-Bench's single-answer grading rubric (FastChat, judge_prompts.jsonl:
    # "single-v1"), reused verbatim for ALPACA so both sets share one scale.
    RUBRIC = (
        "[Instruction]\nPlease act as an impartial judge and evaluate the quality "
        "of the response provided by an AI assistant to the user question "
        "displayed below. Your evaluation should consider factors such as "
        "helpfulness, relevance, accuracy, depth, creativity, and level of "
        "detail. Begin your evaluation by providing a short explanation. Be as "
        "objective as possible. After providing your explanation, you must rate "
        "the response on a scale of 1 to 10 by strictly following this format: "
        "\"[[rating]]\", for example: \"Rating: [[5]]\".\n\n"
        "[Question]\n{question}\n\n"
        "[The Start of Assistant's Answer]\n{answer}\n[The End of Assistant's Answer]"
    )

    def __init__(self, url, model, api_key=None, timeout=300, self_judge=False):
        self.url = self._endpoint(url)
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.self_judge = self_judge
        self.calls = 0
        self.errors = 0
        self.ratings = []

    @staticmethod
    def _endpoint(url):
        url = url.rstrip("/")
        if url.endswith("/chat/completions"):
            return url
        return url + ("/chat/completions" if url.endswith("/v1")
                      else "/v1/chat/completions")

    @staticmethod
    def parse_rating(text):
        """The 1-10 rating out of a judge's reply, or None if it never gave one."""
        m = re.findall(r"\[\[\s*(\d+(?:\.\d+)?)\s*\]\]", text or "")
        if not m:
            m = re.findall(r"(?:rating|score)\D{0,12}(\d+(?:\.\d+)?)", text or "",
                           re.IGNORECASE)
        if not m:
            return None
        try:
            return min(10.0, max(1.0, float(m[-1])))
        except ValueError:
            return None

    def rate(self, question, answer):
        """Raw 1-10 rating for one answer, or None when the judge failed."""
        answer = strip_think(answer)
        if len(answer) > JUDGE_MAX_ANSWER_CHARS:
            answer = answer[:JUDGE_MAX_ANSWER_CHARS] + "\n[answer truncated for the judge]"
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": self.RUBRIC.format(
                question=question, answer=answer)}],
            "temperature": 0.0,
            "max_tokens": 512,
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        self.calls += 1
        for attempt in range(2):
            try:
                r = requests.post(self.url, json=payload, headers=headers,
                                  timeout=self.timeout)
                r.raise_for_status()
                text = r.json()["choices"][0]["message"].get("content") or ""
            except (requests.RequestException, KeyError, IndexError, ValueError) as e:
                if attempt:
                    print(f"    judge failed: {e}")
                continue
            rating = self.parse_rating(text)
            if rating is not None:
                self.ratings.append(rating)
                return rating
        self.errors += 1
        return None

    def info(self):
        return {"url": self.url, "model": self.model,
                "self_judge": self.self_judge,
                "scale": "1-10 rubric, normalized (r-1)/9 -> 0-100",
                "calls": self.calls, "errors": self.errors,
                "mean_rating": (round(sum(self.ratings) / len(self.ratings), 2)
                                if self.ratings else None)}


# ---- the scoring front door ----

class ScoreOptions:
    """What the scorers may do on this run: execute generated code, and/or call
    an independent judge. Both are off unless the operator turned them on."""

    def __init__(self, exec_enabled=True, judge=None,
                 max_prompt_tokens=DEFAULT_MAX_PROMPT_TOKENS):
        self.exec_enabled = exec_enabled
        self.judge = judge
        self.max_prompt_tokens = max_prompt_tokens


def is_scored(name, opts):
    """Does this dataset produce a number under these options?

    Scored and averaged are two different questions: an adjunct set is scored —
    it produces a real number and a real column — and composite_index still
    refuses to average it (rule 21's Mean is over the seven).
    """
    if name in EXACT_MATCH_SETS or name in ROUGE_SETS or name in VERIFIER_SETS:
        return True
    if name in EXEC_SETS:
        return bool(opts and opts.exec_enabled)
    if name in JUDGED_SETS:
        return bool(opts and opts.judge)
    return False


def is_binary_scorer(name):
    """True where a sample is simply right or wrong (so the console can say
    CORRECT/wrong instead of printing a partial score)."""
    return (name in EXACT_MATCH_SETS or name in EXEC_SETS
            or name in VERIFIER_SETS)


def scorer_name(name, opts):
    """Human-readable scorer for a dataset, or None when it isn't scored."""
    if not is_scored(name, opts):
        return None
    if name in EXACT_MATCH_SETS:
        return "exact match"
    if name in EXEC_SETS:
        return "execution pass@1"
    if name in ROUGE_SETS:
        return "ROUGE-L F1"
    if name in VERIFIER_SETS:
        # The scorer's name carries the pinned choice, so a run JSON that
        # outlives this README still says which of the four numbers it holds.
        return f"IFEval verifier, {IFEVAL_PUBLISHED}"
    return f"judge 1-10 ({opts.judge.model})"


def unscored_reason(name, opts):
    """Why a dataset carries no score — the string that lands in the run JSON."""
    if is_scored(name, opts):
        return None
    if name in JUDGED_SETS:
        return NO_JUDGE_REASON
    if name in EXEC_SETS:
        return NO_EXEC_REASON
    return "unscored: no mechanical scorer for this dataset"


def score_response(name, response, ref, prompt=None, opts=None):
    """Normalized score in 0.0-1.0 for one response (x100 = the 0-100 scale
    rule 21's composite averages), or None when this dataset isn't scored here.
    """
    opts = opts or ScoreOptions(exec_enabled=False)
    if not is_scored(name, opts):
        return None
    if name in EXACT_MATCH_SETS:
        verdict = grade(name, response, ref)
        return None if verdict is None else float(bool(verdict))
    if name in EXEC_SETS:
        return pass_at_1(name, response, ref)
    if name in VERIFIER_SETS:
        # PROMPT-LEVEL STRICT, pinned (IFEVAL_PUBLISHED): 1.0 only when every
        # instruction on this prompt is followed. The per-instruction booleans
        # and the loose pass are not thrown away — ifeval_grade() returns them,
        # and a run kept with --transcripts can be re-graded for the other three
        # numbers without touching the GPU.
        graded = ifeval_grade(response, ref)
        return None if graded is None else float(graded["prompt_strict"])
    if name in ROUGE_SETS:
        summary = (ref or {}).get("summary") if isinstance(ref, dict) else ref
        if not summary:
            return None
        return rouge_l(strip_think(response), summary)
    if name in JUDGED_SETS:
        if not prompt:
            return None
        rating = opts.judge.rate(prompt, response)
        # a 1-10 rubric floors at 1, so 1 -> 0 and 10 -> 100
        return None if rating is None else (rating - 1.0) / 9.0
    return None


def composite_index(scores, order=None, excluded=None):
    """Rule 21's Mean: the scored benchmarks' 0-100 scores, averaged.

    Always labeled "composite index over <list>" — it is not an accuracy, and a
    benchmark with no scorer must never silently count as a zero.

    ADJUNCT SETS ARE DROPPED HERE, BY NAME, whatever the caller passes in. They
    are scored, they are published, and they are not part of rule 21's seven; a
    Mean that quietly absorbed one would not be comparable against any earlier
    report, and the caller that did it would be a one-line change in a script
    nobody re-reads. They come back in "excluded" with the reason, so the run
    JSON records that a number existed and was deliberately not averaged.
    """
    excluded = dict(excluded or {})
    order = [d for d in (order or list(scores)) if d in scores]
    for name in order:
        if name in ADJUNCT_SETS:
            excluded.setdefault(name, ADJUNCT_REASON)
    order = [d for d in order if d not in ADJUNCT_SETS]
    if not order:
        return None
    values = [scores[d] for d in order]
    return {
        "mean": round(sum(values) / len(values), 1),
        "included": order,
        "scores": {d: round(scores[d], 1) for d in order},
        "excluded": excluded,
        "label": "composite index over " + ", ".join(order),
    }


# ---- the IFEval dry run: prove the verifier without a GPU ----

# (instruction id, kwargs, response, expected verdict). Every one of the 25
# registered checkers appears twice, once expecting True and once expecting
# False: a checker that always returns True passes a one-sided test and inflates
# a published number for as long as nobody looks.
_IFEVAL_CASES = (
    ("keywords:existence", {"keywords": ["llama", "gguf"]},
     "A llama reads the GGUF file.", True),
    ("keywords:existence", {"keywords": ["llama", "gguf"]},
     "A llama reads the file.", False),

    ("keywords:frequency", {"keyword": "cache", "frequency": 3,
                            "relation": "at least"},
     "cache, Cache and CACHE again.", True),
    ("keywords:frequency", {"keyword": "cache", "frequency": 3,
                            "relation": "at least"},
     "cache and Cache.", False),

    ("keywords:forbidden_words", {"forbidden_words": ["fast"]},
     "It is quick, and breakfast is served.", True),
    ("keywords:forbidden_words", {"forbidden_words": ["fast"]},
     "It is fast.", False),

    ("keywords:letter_frequency", {"letter": "q", "let_frequency": 3,
                                   "let_relation": "at least"},
     "quick quiet queue", True),
    ("keywords:letter_frequency", {"letter": "q", "let_frequency": 3,
                                   "let_relation": "at least"},
     "quick quiet", False),
    # divergence 4: upstream would substitute a random a-z letter here
    ("keywords:letter_frequency", {"letter": "#", "let_frequency": 4,
                                   "let_relation": "at least"},
     "#one #two #three #four", True),

    ("language:response_language", {"language": "de"},
     "Der Vogel ist nicht sehr gross und die Katze liegt auf dem Sofa.", True),
    ("language:response_language", {"language": "de"},
     "The bird is not very big and the cat is on the sofa.", False),
    ("language:response_language", {"language": "ko"},
     "안녕하세요. 이것은 "
     "한국어 문장입니다.", True),
    ("language:response_language", {"language": "hi"},
     "यह एक हिंदी "
     "वाक्य है और यह "
     "सही है।", True),
    # same script, different language: the marker tie-break has to catch it
    ("language:response_language", {"language": "hi"},
     "हे एक मराठी "
     "वाक्य आहे आणि "
     "ते बरोबर आहे।",
     False),

    ("length_constraints:number_sentences",
     {"num_sentences": 3, "relation": "at least"},
     "One thing. Two things. Three things.", True),
    ("length_constraints:number_sentences",
     {"num_sentences": 3, "relation": "at least"},
     "One thing. Two things.", False),

    ("length_constraints:number_paragraphs", {"num_paragraphs": 2},
     "First part.\n***\nSecond part.", True),
    ("length_constraints:number_paragraphs", {"num_paragraphs": 2},
     "First part. Second part.", False),

    ("length_constraints:number_words", {"num_words": 5,
                                         "relation": "at least"},
     "one two three four five", True),
    ("length_constraints:number_words", {"num_words": 5,
                                         "relation": "at least"},
     "one two three four", False),

    ("length_constraints:nth_paragraph_first_word",
     {"num_paragraphs": 2, "nth_paragraph": 2, "first_word": "second"},
     "First paragraph here.\n\nSecond paragraph here.", True),
    ("length_constraints:nth_paragraph_first_word",
     {"num_paragraphs": 2, "nth_paragraph": 2, "first_word": "third"},
     "First paragraph here.\n\nSecond paragraph here.", False),

    ("detectable_content:number_placeholders", {"num_placeholders": 2},
     "Send it to [address] before [date].", True),
    ("detectable_content:number_placeholders", {"num_placeholders": 2},
     "Send it to [address] tomorrow.", False),

    ("detectable_content:postscript", {"postscript_marker": "P.S."},
     "The answer is here.\nP.S. one more thing", True),
    ("detectable_content:postscript", {"postscript_marker": "P.S."},
     "The answer is here. One more thing.", False),

    ("detectable_format:number_bullet_lists", {"num_bullets": 3},
     "* first\n* second\n* third", True),
    ("detectable_format:number_bullet_lists", {"num_bullets": 3},
     "* first\n* second", False),

    ("detectable_format:constrained_response", {},
     "My answer is yes.", True),
    ("detectable_format:constrained_response", {},
     "Yes.", False),

    ("detectable_format:number_highlighted_sections", {"num_highlights": 2},
     "Read *this part* and also *that part*.", True),
    ("detectable_format:number_highlighted_sections", {"num_highlights": 2},
     "Read *this part* only.", False),

    ("detectable_format:multiple_sections",
     {"section_spliter": "Section", "num_sections": 2},
     "Section 1\nintroduction\nSection 2\nconclusion", True),
    ("detectable_format:multiple_sections",
     {"section_spliter": "Section", "num_sections": 2},
     "Section 1\nintroduction only", False),

    ("detectable_format:json_format", {},
     "```json\n{\"answer\": 42}\n```", True),
    ("detectable_format:json_format", {},
     "The answer is 42.", False),

    ("detectable_format:title", {}, "<<A Short Title>>\nThe body.", True),
    ("detectable_format:title", {}, "A Short Title\nThe body.", False),

    ("combination:two_responses", {},
     "First answer.\n******\nSecond answer.", True),
    ("combination:two_responses", {},
     "First answer.\nSecond answer.", False),

    ("combination:repeat_prompt", {"prompt_to_repeat": "Write a haiku."},
     "Write a haiku. Here is one: ...", True),
    ("combination:repeat_prompt", {"prompt_to_repeat": "Write a haiku."},
     "Here is a haiku: ...", False),

    ("startend:end_checker", {"end_phrase": "Any other questions?"},
     "That is the whole method. Any other questions?", True),
    ("startend:end_checker", {"end_phrase": "Any other questions?"},
     "Any other questions? Thanks for reading.", False),

    ("change_case:capital_word_frequency",
     {"capital_frequency": 2, "capital_relation": "at least"},
     "THIS IS the shape of it.", True),
    ("change_case:capital_word_frequency",
     {"capital_frequency": 2, "capital_relation": "at least"},
     "THIS is the shape of it.", False),

    ("change_case:english_capital", {},
     "THIS IS AN ENGLISH SENTENCE AND IT IS ALL CAPITALS.", True),
    ("change_case:english_capital", {},
     "This is an English sentence and it is not all capitals.", False),

    ("change_case:english_lowercase", {},
     "this is an english sentence and it is all lowercase.", True),
    ("change_case:english_lowercase", {},
     "This Is An English Sentence And It Is Not.", False),

    ("punctuation:no_comma", {}, "No commas anywhere in this reply.", True),
    ("punctuation:no_comma", {}, "Commas, sadly, appear here.", False),

    ("startend:quotation", {}, "\"The whole reply is quoted.\"", True),
    ("startend:quotation", {}, "The whole reply is not quoted.", False),
)


def _ifeval_dry_run():
    """Score hand-written cases with known answers — no model, no server, no
    GPU, no network — then check the frozen file against the checker table.

    Returns a process exit code: 0 when every case matched.
    """
    passed, failed = [], []

    def check(label, got, want):
        (passed if got == want else failed).append(label)
        print(f"  {'ok  ' if got == want else 'FAIL'} {label}"
              + ("" if got == want else f": got {got!r}, want {want!r}"))

    print("IFEval verifier dry run: hand-written cases, no model and no GPU")

    print("\nper-instruction checks (each of the 25 types, both directions)")
    for instruction_id, kwargs, response, want in _IFEVAL_CASES:
        check(f"{instruction_id} -> {want}",
              ifeval_follows(instruction_id, kwargs, response), want)

    print("\nprompt-level verdicts (the published number is prompt-level strict)")
    two = {"key": 1, "prompt": "p",
           "instruction_id_list": ["punctuation:no_comma",
                                   "detectable_format:title"],
           "kwargs": [{}, {}]}
    g = ifeval_grade("<<Title Here>>\nA reply with no commas at all.", two)
    check("both instructions followed -> prompt strict", g["prompt_strict"], True)
    g = ifeval_grade("<<Title Here>>\nA reply with commas, sadly.", two)
    check("one instruction broken -> prompt fails", g["prompt_strict"], False)
    check("the per-instruction record survives", g["strict"], [False, True])

    quoted = {"key": 2, "prompt": "p",
              "instruction_id_list": ["startend:quotation"], "kwargs": [{}]}
    g = ifeval_grade("Sure!\n\"the quoted answer\"", quoted)
    check("a preamble fails STRICT", g["prompt_strict"], False)
    check("and passes LOOSE (first line dropped)", g["prompt_loose"], True)

    nocomma = {"key": 3, "prompt": "p",
               "instruction_id_list": ["punctuation:no_comma"], "kwargs": [{}]}
    g = ifeval_grade("<think>Well, let me think, hmm.</think>No commas here.",
                     nocomma)
    check("thinking is stripped before scoring", g["prompt_strict"], True)
    g = ifeval_grade("", nocomma)
    check("an empty reply follows nothing", g["prompt_strict"], False)

    report = ifeval_report([{"instruction_ids": ["punctuation:no_comma", "x"],
                             "strict": [True, False], "loose": [True, True],
                             "prompt_strict": False, "prompt_loose": True},
                            {"instruction_ids": ["punctuation:no_comma"],
                             "strict": [True], "loose": [True],
                             "prompt_strict": True, "prompt_loose": True}])
    check("report: prompt-level strict", report["prompt_strict"], 50.0)
    check("report: instruction-level strict", report["instruction_strict"], 66.7)
    check("report: prompt-level loose", report["prompt_loose"], 100.0)
    check("report names the published number", report["published"],
          IFEVAL_PUBLISHED)

    print("\nthe frozen file (rule 23: frozen -> cache -> network)")
    path = dataset_path("IFEval")
    check("loads from datasets-frozen/",
          os.path.dirname(path) == FROZEN_DIR, True)
    with open(path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    check("sha256 unchanged", digest,
          "67ffeee0fcb87c317c5b08a2de85557b4a7e96ada6178aa645b4954fe4b53d49")
    rows = _read_jsonl(path)
    check("541 prompts", len(rows), 541)
    ids = [i for r in rows for i in r["instruction_id_list"]]
    check("834 instructions", len(ids), 834)
    check("25 instruction types", len(set(ids)), 25)
    check("every instruction type has a checker",
          sorted(set(ids)), sorted(IFEVAL_CHECKERS))
    check("every checker is exercised above",
          sorted({c[0] for c in _IFEVAL_CASES}), sorted(IFEVAL_CHECKERS))
    check("every kwargs list lines up with its instruction list",
          all(len(r["instruction_id_list"]) == len(r["kwargs"]) for r in rows),
          True)
    # A requested language the script table does not know scores every reply
    # WRONG (the target is in no candidate list), which is a harness fault
    # charged to the model — the one direction that must never fail silently.
    langs = sorted({k["language"] for r in rows
                    for i, k in zip(r["instruction_id_list"], r["kwargs"])
                    if i == "language:response_language"})
    known = {code for codes in _IF_SCRIPT_LANGS.values() for code in codes}
    check("22 languages are requested", len(langs), 22)
    check("every requested language is in the script table",
          [code for code in langs if code not in known], [])

    print("\nthe prompt reaches the model verbatim")
    items = load_items("IFEval", 3)
    picked = _evenly_spaced(rows, 3)
    check("no answer-format wrapper is appended",
          [it["prompt"] for it in items], [r["prompt"] for r in picked])

    # Fifty hand-written cases exercise every checker; these three exercise
    # every checker against all 834 real kwargs at once, and lock the verifier's
    # behaviour to three numbers. Change any checker and one of them moves.
    print("\nthe whole frozen corpus against three canned replies")
    refs = [reference_answer("IFEval", r) for r in rows]

    def corpus(reply_for):
        return ifeval_report([ifeval_grade(reply_for(r), ref)
                              for r, ref in zip(rows, refs)])

    check("an empty reply scores 0.0",
          corpus(lambda r: "")["prompt_strict"], 0.0)
    check("one plain sentence scores 10.5: the floor a model gets for "
          "ignoring every instruction",
          corpus(lambda r: "This is a canned reply with no special "
                           "formatting whatsoever.")["prompt_strict"], 10.5)
    echoed = corpus(lambda r: r["prompt"])
    check("echoing the prompt back scores 24.8", echoed["prompt_strict"], 24.8)
    # The same text, scored by the four IFEval definitions: 16.6 points apart.
    # This is why IFEVAL_PUBLISHED is pinned rather than chosen per run.
    check("the same text scores 41.4 instruction-level loose",
          echoed["instruction_loose"], 41.4)

    print("\nend to end through score_response, on a real frozen row")
    row = [r for r in rows if r["key"] == 2015][0]
    ref = reference_answer("IFEval", row)
    check("scorer is the pinned one", scorer_name("IFEval", ScoreOptions()),
          f"IFEval verifier, {IFEVAL_PUBLISHED}")
    check("a compliant reply scores 1.0",
          score_response("IFEval", "\"Come for the jokes. Stay for the seats.\"",
                         ref), 1.0)
    check("a non-compliant reply scores 0.0",
          score_response("IFEval", "Come for the jokes. Stay for the seats.",
                         ref), 0.0)

    print("\nadjunct membership (rule 21's seven, rule 23's suite hash)")
    check("IFEval stays out of the default sweep",
          "IFEval" in DATASET_NAMES, False)
    check("the seven are exactly rule 21's", DATASET_NAMES, list(RULE21_SETS))
    check("--datasets IFEval still resolves", resolve_name("ifeval"), "IFEval")
    comp = composite_index({"GSM8K": 80.0, "IFEval": 40.0},
                           order=["GSM8K", "IFEval"])
    check("the Mean refuses the adjunct", comp["included"], ["GSM8K"])
    check("and says why", comp["excluded"]["IFEval"], ADJUNCT_REASON)
    check("so the Mean is unmoved", comp["mean"], 80.0)

    print(f"\n{len(passed)} passed, {len(failed)} failed")
    for label in failed:
        print(f"  FAILED: {label}")
    return 1 if failed else 0


if __name__ == "__main__":
    if "--ifeval-dry-run" in sys.argv[1:]:
        sys.exit(_ifeval_dry_run())
    for ds in ALL_DATASET_NAMES:
        prompts = load_prompts(ds, 3)
        # ascii(): a Windows console is cp1252, and a non-Latin prompt in a
        # smoke test must not be what kills the smoke test
        print(f"{ds}: ok, sample prompt: {ascii(prompts[0][:80])}")
