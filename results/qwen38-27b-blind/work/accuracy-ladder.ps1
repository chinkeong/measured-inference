# accuracy-ladder.ps1 - score the WHOLE quant ladder on the frozen suite.
#
# WHY THIS EXISTS. The ladder ranked nine files on perplexity and probed each
# once with the detectors. Neither instrument answers the question a reader
# actually asks - "is this rung any good?" - and this campaign proved it:
# UD-IQ2_XXS and UD-IQ1_M sit 1.67 % apart at 1.7 sigma, so perplexity cannot
# rank them, while the detectors pass a rung whose lexical diversity has
# collapsed to 0.358. Exactly ONE sub-Q4 file has ever been scored on
# benchmarks (UD-IQ2_XXS, mean 78.70).
#
# THE QUESTION: does the ACCURACY cliff sit at the same rung as the PERPLEXITY
# cliff (UD-Q2_K_XL, 2.91 bits/weight)? Two instruments already disagree about
# where this model breaks; there is no reason to assume a third agrees with
# either.
#
# CONDITIONS - identical to the UD-IQ2_XXS arm already in the ledger, so every
# new number is directly comparable to its 78.70 and to gemma's 73.30:
#   frozen suite 1cdf54f8eb9d3f8f, GSM8K/HumanEval/MBPP, n=25, greedy, seed 42,
#   cap 16,384 with -c 32768, -ctk q8_0 -ctv q8_0, reasoning_effort=low,
#   no drafter. Rule-7 cap raise pre-authorised ONCE per arm.
#
# The anchor runs FIRST: bench-arm.py's three-set arm is NOT a rule-21 run, so
# its Mean is not comparable to section 09's seven-set Mean and needs its own
# in-suite reference point.
$ErrorActionPreference = 'Continue'
$M = 'C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF'
$arms = @(
    "qwen-iq4xs-anchor|$M\Qwen3.8-27B-UD-IQ4_XS.gguf|qwen",
    "qwen-q3kxl|$M\Qwen3.8-27B-UD-Q3_K_XL.gguf|qwen",
    "qwen-iq3xxs|$M\Qwen3.8-27B-UD-IQ3_XXS.gguf|qwen",
    "qwen-q2kxl|$M\Qwen3.8-27B-UD-Q2_K_XL.gguf|qwen",
    "qwen-iq2s|$M\Qwen3.8-27B-UD-IQ2_S.gguf|qwen",
    "qwen-iq1m|$M\Qwen3.8-27B-UD-IQ1_M.gguf|qwen",
    "qwen-iq1s|$M\Qwen3.8-27B-UD-IQ1_S.gguf|qwen"
)
& 'E:\AI\measured-inference\scripts\quant-ladder\decisive-arm.ps1' -Arms $arms -DeadlineMinutes 420
