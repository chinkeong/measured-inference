"""Offline self-test for the bench harness: deterministic sampling, prompt
construction, ROUGE-L, the 0-100 normalizations, the composite Mean, code
extraction and execution pass@1 — all against hardcoded fixtures.

No server, no model, no network, no GPU. It does spawn short-lived Python
subprocesses, because that is exactly what the pass@1 scorer does.

    python selftest.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import bench
import datasets_io as dio

PASSED, FAILED = [], []


def check(name, got, want, tol=None):
    ok = (abs(got - want) <= tol) if tol is not None else (got == want)
    (PASSED if ok else FAILED).append(name)
    print(f"  {'ok  ' if ok else 'FAIL'} {name}: got {got!r}"
          + ("" if ok else f", want {want!r}"))


def section(title):
    print(f"\n{title}")


# ---- 1. deterministic sampling -------------------------------------------
section("deterministic sampling (evenly spaced, no RNG)")
rows = [{"i": i} for i in range(100)]
picked = dio._evenly_spaced(rows, 25)
check("picks n rows", len(picked), 25)
check("evenly spaced indices", [r["i"] for r in picked], list(range(0, 100, 4)))
check("stable across calls", dio._evenly_spaced(rows, 25), picked)
check("n >= len(rows) keeps everything", len(dio._evenly_spaced(rows[:10], 25)), 10)
check("first row always included", dio._evenly_spaced(rows, 3)[0]["i"], 0)

# ---- 2. prompts + references ---------------------------------------------
section("prompt construction")
alpaca_plain = dio.build_item("ALPACA", {"instruction": "Name three colors.",
                                         "input": "", "output": "..."})
check("ALPACA instruction only", alpaca_plain["prompt"], "Name three colors.")
check("ALPACA has no mechanical reference", alpaca_plain["ref"], None)
alpaca_input = dio.build_item("ALPACA", {"instruction": "Summarize the text.",
                                         "input": "The rain in Spain."})
check("ALPACA instruction + input", alpaca_input["prompt"],
      "Summarize the text.\n\nThe rain in Spain.")

short = dio.build_item("MeetingBank", {"transcript": "Council meeting. Motion carries.",
                                       "summary": "A motion carried.", "uid": "X_1"})
check("MeetingBank prompt says summarize",
      short["prompt"].startswith("Summarize this meeting."), True)
check("MeetingBank keeps the transcript",
      short["prompt"].endswith("Council meeting. Motion carries."), True)
check("MeetingBank keeps the reference summary",
      short["ref"]["summary"], "A motion carried.")
check("short transcript is not truncated", short["note"], None)

long_row = {"transcript": "word " * 20000, "summary": "s", "uid": "X_2"}
cut = dio.build_item("MeetingBank", long_row, max_prompt_tokens=1024)
check("long transcript truncated", cut["note"] is not None, True)
check("truncation stays inside the guard (4 chars/token)",
      dio.est_tokens(cut["prompt"]) <= 1024, True)
check("truncation is recorded in the prompt itself",
      "[transcript truncated:" in cut["prompt"], True)
check("guard 0 disables truncation",
      dio.build_item("MeetingBank", long_row, max_prompt_tokens=0)["note"], None)

check("MEETINGBANK resolves case-insensitively", dio.resolve_name("MEETINGBANK"),
      "MeetingBank")
check("alpaca resolves case-insensitively", dio.resolve_name("alpaca"), "ALPACA")
check("unknown dataset rejected", dio.resolve_name("HellaSwag"), None)

# ---- 3. ROUGE-L -----------------------------------------------------------
section("ROUGE-L F1")
check("identical text scores 1.0", dio.rouge_l("the cat sat", "the cat sat"),
      1.0, tol=1e-9)
check("disjoint text scores 0.0", dio.rouge_l("alpha beta", "gamma delta"),
      0.0, tol=1e-9)
# cand/ref = 6 words each, LCS "the cat on the mat" = 5 -> P = R = F = 5/6
check("partial overlap (LCS 5 of 6)",
      dio.rouge_l("the cat sat on the mat", "the cat is on the mat"),
      5 / 6, tol=1e-9)
# subsequence, not substring: LCS("a b c", "c b a") = 1 -> P = R = F = 1/3
check("order matters (LCS 1 of 3)", dio.rouge_l("a b c", "c b a"), 1 / 3, tol=1e-9)
check("case and punctuation are normalized away",
      dio.rouge_l("The CAT, sat!", "the cat sat"), 1.0, tol=1e-9)
check("empty candidate scores 0.0", dio.rouge_l("", "the cat sat"), 0.0, tol=1e-9)
check("thinking is stripped before scoring",
      dio.score_response("MeetingBank",
                         "<think>hmm the dog barked</think>the cat sat",
                         {"summary": "the cat sat"}, opts=dio.ScoreOptions()),
      1.0, tol=1e-9)

# ---- 4. code extraction ---------------------------------------------------
section("code extraction")
messy = ("<think>let me plan this out\nfirst the loop</think>\n"
         "Here is the solution:\n\n"
         "```python\nfrom typing import List\n\n\n"
         "def add_one(numbers: List[int]) -> List[int]:\n"
         "    return [n + 1 for n in numbers]\n```\n\n"
         "Example use:\n\n```python\nprint(add_one([1, 2]))\n```\n")
code = dio.extract_code(messy)
check("think block dropped", "let me plan" not in code, True)
check("solution block kept", "return [n + 1 for n in numbers]" in code, True)
check("usage-example block dropped", "print(add_one" not in code, True)
check("unfenced answer passes through",
      dio.extract_code("    return x + 1"), "    return x + 1")
check("unterminated think block drops the tail",
      dio.strip_think("answer\n<think>still thinking"), "answer")

# ---- 5. execution pass@1 --------------------------------------------------
section("execution pass@1 (runs generated code in a subprocess)")
HE_REF = {
    "prompt": ("from typing import List\n\n\n"
               "def add_one(numbers: List[int]) -> List[int]:\n"
               "    \"\"\" Add one to every number in the list.\n"
               "    >>> add_one([1, 2])\n    [2, 3]\n    \"\"\"\n"),
    "test": ("def check(candidate):\n"
             "    assert candidate([1, 2]) == [2, 3]\n"
             "    assert candidate([]) == []\n"),
    "entry_point": "add_one",
}
check("HumanEval: correct fenced answer passes",
      dio.pass_at_1("HumanEval", messy, HE_REF), 1.0)
check("HumanEval: wrong answer fails",
      dio.pass_at_1("HumanEval", "```python\ndef add_one(numbers):\n"
                                 "    return [n + 2 for n in numbers]\n```", HE_REF),
      0.0)
check("HumanEval: bare indented continuation assembles onto the prompt",
      dio.pass_at_1("HumanEval", "    return [n + 1 for n in numbers]", HE_REF), 1.0)
check("HumanEval: prose-only answer fails",
      dio.pass_at_1("HumanEval", "You just add one to each element.", HE_REF), 0.0)

MBPP_REF = {"test_list": ["assert double(3) == 6", "assert double(-1) == -2"],
            "test_setup_code": ""}
check("MBPP: correct answer passes",
      dio.pass_at_1("MBPP", "Sure.\n```python\ndef double(x):\n    return x * 2\n```",
                    MBPP_REF), 1.0)
check("MBPP: answer that passes only the shown test fails the full test_list",
      dio.pass_at_1("MBPP", "```python\ndef double(x):\n    return 6\n```",
                    MBPP_REF), 0.0)
check("runaway generation is killed, not waited on",
      dio.run_program("while True:\n    pass\n", timeout=2), False)

# ---- 6. scoring policy ----------------------------------------------------
section("scoring policy")
full = dio.ScoreOptions(exec_enabled=True, judge=None)
noexec = dio.ScoreOptions(exec_enabled=False, judge=None)
check("HumanEval scored when execution is on", dio.is_scored("HumanEval", full), True)
check("HumanEval unscored under --no-exec", dio.is_scored("HumanEval", noexec), False)
check("--no-exec reason recorded", dio.unscored_reason("MBPP", noexec),
      "unscored: --no-exec (code execution disabled)")
check("ALPACA unscored without a judge", dio.is_scored("ALPACA", full), False)
check("no-judge reason recorded", dio.unscored_reason("ALPACA", full),
      "unscored: no independent judge")
check("MT-Bench unscored without a judge", dio.unscored_reason("MT-Bench", full),
      "unscored: no independent judge")
check("unscored datasets return no score",
      dio.score_response("ALPACA", "any answer", None, prompt="q", opts=full), None)
check("GSM8K exact match still grades",
      dio.score_response("GSM8K", "so the answer is\n#### 18", "18", opts=full), 1.0)
check("GSM8K wrong answer",
      dio.score_response("GSM8K", "#### 19", "18", opts=full), 0.0)
check("legacy grade() unchanged", dio.grade("MATH-500", "x = \\boxed{42}", "42"), True)

# ---- 7. judge normalization (1-10 -> 0-100) -------------------------------
section("judge rubric normalization")
check("[[8]] parsed", dio.Judge.parse_rating("Explanation... Rating: [[8]]"), 8.0)
check("bare 'Rating: 6' fallback", dio.Judge.parse_rating("Rating: 6/10"), 6.0)
check("out-of-range clamped", dio.Judge.parse_rating("Rating: [[47]]"), 10.0)
check("no rating -> None", dio.Judge.parse_rating("I refuse to rate this."), None)
check("/v1 endpoint completed", dio.Judge("http://box:1300/v1", "m").url,
      "http://box:1300/v1/chat/completions")
check("bare host endpoint completed", dio.Judge("http://box:1300", "m").url,
      "http://box:1300/v1/chat/completions")


class FakeJudge(dio.Judge):
    """No network: hands back a fixed rating so the normalization is testable."""

    def __init__(self, rating):
        super().__init__("http://judgebox:1300/v1", "fake-judge")
        self.fixed = rating

    def rate(self, question, answer):
        return self.fixed


for rating, want in ((1.0, 0.0), (5.5, 50.0), (10.0, 100.0)):
    opts = dio.ScoreOptions(judge=FakeJudge(rating))
    got = dio.score_response("ALPACA", "answer", None, prompt="q", opts=opts)
    check(f"rating {rating} -> {want}/100", round(got * 100, 6), want)
check("a judge makes MT-Bench scored",
      dio.is_scored("MT-Bench", dio.ScoreOptions(judge=FakeJudge(7))), True)
check("scorer named with the judge model",
      dio.scorer_name("ALPACA", dio.ScoreOptions(judge=FakeJudge(7))),
      "judge 1-10 (fake-judge)")

# ---- 8. the composite Mean ------------------------------------------------
section("composite index (rule 21 Mean)")
scores = {"GSM8K": 88.0, "MATH-500": 60.0, "HumanEval": 72.0, "MBPP": 64.0,
          "MeetingBank": 21.0}
excluded = {"ALPACA": dio.NO_JUDGE_REASON, "MT-Bench": dio.NO_JUDGE_REASON}
comp = dio.composite_index(scores, order=["GSM8K", "MATH-500", "HumanEval",
                                          "MBPP", "ALPACA", "MeetingBank",
                                          "MT-Bench"], excluded=excluded)
check("mean over scored benchmarks only", comp["mean"], 61.0)
check("unscored benchmarks are excluded, never counted as zero",
      comp["included"], ["GSM8K", "MATH-500", "HumanEval", "MBPP", "MeetingBank"])
check("exclusions carry their reason", comp["excluded"]["MT-Bench"],
      "unscored: no independent judge")
check("labeled as a composite index", comp["label"],
      "composite index over GSM8K, MATH-500, HumanEval, MBPP, MeetingBank")
check("nothing scored -> no Mean at all", dio.composite_index({}), None)
check("table labels the Mean row as composite",
      bench.render_table._mean_label({"composite": comp}), "Mean (composite)")
check("pass-rate cell keeps its % sign",
      bench.render_table._score_cell({"accuracy": 0.88, "score": 88.0,
                                      "scorer": "exact match", "graded_n": 25}),
      "88% (25)")
check("continuous scorer is not shown as a percentage",
      bench.render_table._score_cell({"accuracy": 0.212, "score": 21.2,
                                      "scorer": "ROUGE-L F1", "graded_n": 25}),
      "21.2 (25)")
check("legacy result files still render as accuracy",
      bench.render_table._score_cell({"accuracy": 0.6, "graded_n": 200}),
      "60% (200)")

# ---- 9. the self-judge guard ---------------------------------------------
section("self-judge guard")
check("same host and port is self-judging",
      bench._is_self_judge("http://127.0.0.1:1236/v1", 1236), True)
check("localhost by name is still the same server",
      bench._is_self_judge("http://localhost:1236/v1", 1236), True)
check("a different local port is allowed",
      bench._is_self_judge("http://127.0.0.1:1300/v1", 1236), False)
check("a remote judge is allowed",
      bench._is_self_judge("http://otherbox:1236/v1", 1236), False)

# ---- 10. rule-21 preset ---------------------------------------------------
section("rule-21 preset")
check("n = 25 per benchmark", bench.RULE21["samples"], 25)
check("max_tokens = 16384", bench.RULE21["max_tokens"], 16384)
check("seed = 42", bench.RULE21["seed"], 42)
check("the seven-dataset suite", bench.RULE21["datasets"].split(","),
      ["GSM8K", "MATH-500", "HumanEval", "MBPP", "ALPACA", "MeetingBank", "MT-Bench"])
check("every suite name is a real dataset",
      [dio.resolve_name(d) for d in bench.RULE21["datasets"].split(",")],
      dio.DATASET_NAMES)
check("-c is sized from the longest prompt + the cap, not left at 8192",
      bench._round_up_ctx(8192 + 16384), 32768)

print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
if FAILED:
    for name in FAILED:
        print(f"  FAILED: {name}")
    sys.exit(1)
