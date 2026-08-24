## The ladder

| rung | role | GiB | bits/weight | PPL +/- err | vs IQ4_XS | bits/byte | GiB saved | %PPL/GiB | detectors |
|---|---|---|---|---|---|---|---|---|---|
| UD-IQ4_XS | rig-gate | 13.274 | 4.223 | 6.5956 +/- 0.04453 | +0.00% | 0.6267 |  |  | PASS |
| NVFP4-MTP-VERY-LOW | rig-gate | 13.842 | 4.404 | 6.8774 +/- 0.04716 | +4.27% | 0.6406 |  |  | PASS |
| UD-Q3_K_XL | pass1 | 12.244 | 3.895 | 6.7691 +/- 0.04667 | +2.63% | 0.6353 | 1.60 | -0.99 | PASS |
| UD-IQ3_XXS | pass1 | 10.184 | 3.240 | 6.9187 +/- 0.04777 | +4.90% | 0.6426 | 2.06 | 1.07 | PASS |
| UD-Q2_K_XL | pass1 | 9.154 | 2.912 | 6.9957 +/- 0.04794 | +6.07% | 0.6463 | 1.03 | 1.08 | PASS |
| UD-IQ2_S | pass2 | 7.797 | 2.481 | 7.5481 +/- 0.05383 | +14.44% | 0.6715 | 1.36 | 5.82 | PASS |
| UD-IQ2_XXS | pass1 | 6.767 | 2.153 | 8.0079 +/- 0.05695 | +21.41% | 0.6912 | 1.03 | 5.91 | PASS |
| UD-IQ1_M | pass1 | 6.267 | 1.994 | 8.1418 +/- 0.05586 | +23.44% | 0.6967 | 0.50 | 3.34 | PASS |
| UD-IQ1_S | right-anchor | 5.767 | 1.835 | 8.9265 +/- 0.06202 | +35.34% | 0.7272 | 0.50 | 19.28 | FAIL (rep=CLEAN json=FAIL(empty) fence=PASS(fences=2)) |

## Marginal cost of shrinking

| segment | GiB saved | %PPL added | %PPL per GiB | vs median above |
|---|---|---|---|---|
| NVFP4-MTP-VERY-LOW -> UD-Q3_K_XL | 1.60 | -1.57 | -0.99 | - |
| UD-Q3_K_XL -> UD-IQ3_XXS | 2.06 | +2.21 | 1.07 | - |
| UD-IQ3_XXS -> UD-Q2_K_XL | 1.03 | +1.11 | 1.08 | 1.0x |
| UD-Q2_K_XL -> UD-IQ2_S | 1.36 | +7.90 | 5.82 | 5.4x |
| UD-IQ2_S -> UD-IQ2_XXS | 1.03 | +6.09 | 5.91 | 5.5x |
| UD-IQ2_XXS -> UD-IQ1_M | 0.50 | +1.67 | 3.34 | 3.1x |
| UD-IQ1_M -> UD-IQ1_S | 0.50 | +9.64 | 19.28 | 5.8x |

**KNEE: UD-Q2_K_XL.** The UD-Q2_K_XL -> UD-IQ2_S segment costs 5.82 %PPL per GiB, 5.4x the median 1.07 of every segment above it. UD-Q2_K_XL is the last rung before the curve turns up.

## Detector matrix

| rung | verdict | D1 immediate-loop | D2 line-loop | D3 tail-ngram | D4 global-repeat | JSON echo | fenced block | probe-A tokens | t/s |
|---|---|---|---|---|---|---|---|---|---|
| UD-IQ4_XS | PASS | PASS(0) | PASS(0) | PASS(0) | PASS(0) | PASS(exact) | PASS(fences=2) | 1202 | 40.02 |
| NVFP4-MTP-VERY-LOW | PASS | PASS(0) | PASS(0) | PASS(0) | PASS(0) | PASS(exact) | PASS(fences=2) | 1017 | 39.43 |
| gemma-4-12B-QAT-Q4_0 | PASS | PASS(0) | PASS(0) | PASS(0) | PASS(0) | PASS(exact) | PASS(fences=2) | 1147 | 82.13 |
| UD-Q3_K_XL | PASS | PASS(0) | PASS(0) | PASS(0) | PASS(0) | PASS(exact) | PASS(fences=2) | 1047 | 42.58 |
| UD-IQ3_XXS | PASS | PASS(0) | PASS(0) | PASS(0) | PASS(0) | PASS(exact) | PASS(fences=2) | 1133 | 44.03 |
| UD-Q2_K_XL | PASS | PASS(0) | PASS(0) | PASS(0) | PASS(0) | PASS(exact) | PASS(fences=2) | 915 | 45.90 |
| UD-IQ2_S | PASS | PASS(0) | PASS(0) | PASS(0) | PASS(0) | PASS(exact) | PASS(fences=2) | 993 | 47.85 |
| UD-IQ2_XXS | PASS | PASS(0) | PASS(0) | PASS(0) | PASS(0) | PASS(exact) | PASS(fences=2) | 1136 | 49.44 |
| UD-IQ1_M | PASS | PASS(0) | PASS(0) | PASS(0) | PASS(0) | PASS(exact) | PASS(fences=2) | 1287 | 50.96 |
| UD-IQ1_S | FAIL | PASS(0) | PASS(0) | PASS(0) | PASS(0) | FAIL(empty) | PASS(fences=2) | 1276 | 53.25 |

Smallest detector-passing 27B rung: **UD-IQ1_M** at 6.267 GiB (PPL 8.1418, +23.44% vs IQ4_XS)

## Withdrawn rows (measured, NOT publishable)

| gemma-4-12B-QAT-Q4_0 | 6.497 GiB | PPL: **WITHDRAWN** | bits/byte: **WITHDRAWN** | detectors: PASS |

> PPL and bits-per-byte for the gemma-4 family are NOT MEASURABLE on this stack (llama.cpp build 10502 / 0.1.2-dev, commit 0adcc3bb5) via llama-perplexity. The measured PPL=1159.7186 / bpb=2.3285 is an apparatus reading, not a model property, and is withdrawn from every table. The cross-model comparison is carried ENTIRELY by the scored benchmark arm (GSM8K/HumanEval/MBPP), tokenizer-independent and always rule 6's designated cross-family instrument. | ts=2026-08-23T18:43:15


## Rig gates

- `RIGGATE UD-IQ4_XS | expected=6.5956 | measured=6.5956 | delta_pct=0.000 | tol_pct=0.5 | PASS`
- `RIGGATE UD-IQ4_XS | expected=6.5956 | measured=6.5956 | delta_pct=0.000 | tol_pct=0.5 | PASS`
- `RIGGATE NVFP4-MTP-VERY-LOW | expected=6.8774 | measured=6.8774 | delta_pct=0.000 | tol_pct=0.5 | PASS`
