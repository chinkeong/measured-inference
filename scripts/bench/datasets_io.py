"""Download, cache, build prompts for — and score — the benchmark datasets:
GSM8K, MATH-500, GPQA-Diamond, HumanEval, MBPP, ALPACA, MeetingBank, MT-Bench.

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
    ALPACA, MT-Bench    1-10 judge rubric on an independent OpenAI-compatible
                        endpoint; unscored when none is configured, because a
                        model judging its own outputs is not a score

No dependencies beyond `requests`: ROUGE-L is implemented here, and the judge
speaks plain HTTP.
"""

import gzip
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
}

DATASET_NAMES = list(SOURCES.keys())

# which scorer each set uses (rule 21)
EXACT_MATCH_SETS = ("GSM8K", "MATH-500", "GPQA-Diamond")
EXEC_SETS = ("HumanEval", "MBPP")
ROUGE_SETS = ("MeetingBank",)
JUDGED_SETS = ("ALPACA", "MT-Bench")

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
    so --datasets MEETINGBANK and --datasets MeetingBank are the same suite."""
    key = name.strip().lower()
    return {n.lower(): n for n in DATASET_NAMES}.get(key)


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
    """Does this dataset produce a number under these options? Only sets that
    say yes may enter rule 21's composite Mean."""
    if name in EXACT_MATCH_SETS or name in ROUGE_SETS:
        return True
    if name in EXEC_SETS:
        return bool(opts and opts.exec_enabled)
    if name in JUDGED_SETS:
        return bool(opts and opts.judge)
    return False


def is_binary_scorer(name):
    """True where a sample is simply right or wrong (so the console can say
    CORRECT/wrong instead of printing a partial score)."""
    return name in EXACT_MATCH_SETS or name in EXEC_SETS


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
    """
    order = [d for d in (order or list(scores)) if d in scores]
    if not order:
        return None
    values = [scores[d] for d in order]
    return {
        "mean": round(sum(values) / len(values), 1),
        "included": order,
        "scores": {d: round(scores[d], 1) for d in order},
        "excluded": dict(excluded or {}),
        "label": "composite index over " + ", ".join(order),
    }


if __name__ == "__main__":
    for ds in DATASET_NAMES:
        prompts = load_prompts(ds, 3)
        print(f"{ds}: ok, sample prompt: {prompts[0][:80]!r}")
