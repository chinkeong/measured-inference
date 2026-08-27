| Benchmark | Scorer | low | medium | xhigh |
|---|---|---|---|---|
| GSM8K | exact match | 100% | 100% | 100% |
| MATH-500 | exact match | 92% (1 trunc) | 100% | 92% (2 trunc) |
| HumanEval | execution pass@1 | 100% | 96% (1 trunc) | 84% (4 trunc) |
| MBPP | execution pass@1 | 92% | 84% (1 trunc) | 88% (2 trunc) |
| ALPACA | judge 1-10 - **no judge: unscored** | unscored | unscored | unscored |
| MeetingBank | ROUGE-L F1 | 22.6 | 22.4 | 22.3 |
| MT-Bench | judge 1-10 - **no judge: unscored** | unscored | unscored | unscored |
| **Mean (composite, 5 scored sets)** | - | **81.3** | **80.5** | **77.3** |

| Per-arm | low | medium | xhigh |
|---|---|---|---|
| Wall time | 1.00 h | 1.47 h | 2.70 h |
| Truncated at cap (of 175) | 1 | 2 | 8 |
| Mean output tokens (all 7 sets) | 830 | 1228 | 2217 |
| Decode tok/s (mean) | 42.2 | 42.0 | 41.9 |
