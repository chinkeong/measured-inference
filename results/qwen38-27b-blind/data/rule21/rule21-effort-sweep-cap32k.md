| Benchmark | Scorer | low-cap32k | medium-cap32k | xhigh-cap32k |
|---|---|---|---|---|
| GSM8K | exact match | 100% | 100% | 100% |
| MATH-500 | exact match | 96% | 100% | 100% |
| HumanEval | execution pass@1 | 100% | 96% | 92% (2 trunc) |
| MBPP | execution pass@1 | 92% | 84% | 92% (1 trunc) |
| ALPACA | judge 1-10 - **no judge: unscored** | unscored | unscored | unscored |
| MeetingBank | ROUGE-L F1 | 22.6 | 22.4 | 22.3 |
| MT-Bench | judge 1-10 - **no judge: unscored** | unscored | unscored | unscored |
| **Mean (composite, 5 scored sets)** | - | **82.1** | **80.5** | **81.3** |

| Per-arm | low-cap32k | medium-cap32k | xhigh-cap32k |
|---|---|---|---|
| Wall time | 0.38 h | 0.53 h | 2.40 h |
| Truncated at cap (of 175) | 0 | 0 | 3 |
| Mean output tokens (all 7 sets) | 883 | 1232 | 2633 |
| Decode tok/s (mean) | 42.0 | 41.8 | 41.6 |
