# F4-PRECISION-01 — Qualification result

**Identity:** F4-PRECISION-01-ANALYSIS-01  
**Active contract:** `F4-PRECISION-01-CONTRACT-v0.1.8.json`  
**Contract SHA-256:** `5d421392c7d07d0d6c9692033ceb22e311016ddf2efc3bce3f6ba35f6461aada`  
**Scope:** qualification only; the F4-CAPACITY-01 parent receipt and REACH-03 measured namespace remain untouched.

## Disposition

**F32 quantization as the cause of cross-block polarity failure is not supported under this frozen 80D representation and estimator.** The f64 and quantized-f32/f64 arms had identical pooled balanced-error and margin-ladder classification metrics. The f64 arm did not recover positive extractable observability, including on the predeclared `|g| > 1e-8` subset. This is a bounded result about this feature map, MLP, and four qualification blocks; it does not show that raw F4 lacks information or that the 80D feature map is sufficient.

The f64 arm improved raw pooled balanced error slightly versus the original f32 arm, but that contrast jointly changes feature arithmetic and model arithmetic. It cannot identify which part caused the small change. All three clipped `Omega_hat` values remain zero.

## Integrity and sequence status

- Structural/hash audit: **PASS_WITH_OUTCOME_ACCESS_SEQUENCE_DEVIATION**; 265 frozen input hashes checked.
- A/B/C streams: 72/72/72; 13,420 paired rows; 12 expected fold fits.
- Missing/duplicate cells, duplicate row identities, and nonfinite values: zero.
- Arm A reproduced the four frozen parent fold errors within the declared `1e-8` tolerance.
- **Sequence deviation:** I opened the completed analysis JSON before writing the independent integrity receipt. The audit passed afterward, but this is classified as a qualification diagnostic, not a blind confirmation. No analysis settings or outputs were changed in response.
- Measured namespace: absent. Biological promotion: none. PHENO status: unchanged.

## Pooled cross-block result

| Arm | Features / model | Balanced error | Unclipped `Omega_hat` | Clipped `Omega_hat` |
|---|---|---:|---:|---:|
| A | 80D float32 / float32 MLP | 0.733430017 | -0.466860034 | 0.000000000 |
| B | 80D float64 / float64 MLP | 0.729606778 | -0.459213557 | 0.000000000 |
| C | B features quantized to float32 then promoted / float64 MLP | 0.729606778 | -0.459213557 | 0.000000000 |

- B minus A raw balanced error: **-0.003823239** (a modest improvement; not an isolated precision effect).
- B minus C raw balanced error: **0.000000000**.
- All three clipped `Omega_hat` values are zero because pooled balanced error remains above 0.5.

## Fold diagnostics

| Held-out task block | A balanced error | B balanced error | C balanced error | Two-class support? |
|---:|---:|---:|---:|:---:|
| 303000 | 0.776328598 | 0.766089010 | 0.766089010 | yes |
| 303001 | 0.500000000 | 0.500000000 | 0.500000000 | yes |
| 303002 | 0.757895777 | 0.758061578 | 0.758061578 | yes |
| 303003 | 0.237536298 | 0.237802594 | 0.237802594 | no |

Block 303003 contains only one target class. Its fold score reproduces the parent evaluator’s denominator-floor convention and is explicitly class-degenerate; it is not interpreted as a two-class balanced generalization estimate.

## Frozen margin ladder

| Minimum reference magnitude `gamma` | Rows | A balanced error | B balanced error | C balanced error | Any positive clipped `Omega_hat`? |
|---:|---:|---:|---:|---:|:---:|
| `|g| > 1e-12` | 13,420 | 0.733430017 | 0.729606778 | 0.729606778 | no |
| `|g| > 1e-11` | 10,515 | 0.804386019 | 0.800601584 | 0.800601584 | no |
| `|g| > 1e-10` | 7,286 | 0.787865445 | 0.786557759 | 0.786557759 | no |
| `|g| > 1e-09` | 4,665 | 0.676903977 | 0.676901632 | 0.676901632 | no |
| `|g| > 1e-08` | 1,865 | 0.533315945 | 0.533626982 | 0.533626982 | no |

Even on the largest-margin slice (`|g| > 1e-8`, 1,865 rows), balanced error is slightly worse than chance. The ladder is not a monotonic recovery of polarity as the target moves away from zero.

## Representation diagnostics

- F64→F32→F64 quantization changed 292,219 of 1,073,600 feature cells (27.2%); every row had at least one changed cell.
- Mean absolute feature delta: `4.284e-09`; RMSE: `1.514e-08`; maximum absolute delta: `2.384e-07`.
- Exact opposite-label float32 collision groups: 0 in A and 0 in C.
- The within-panel nearest-neighbor diagnostic had 5,548 rows with both same- and opposite-label neighbors available. Opposite-label neighbors were nearer or tied for 0.667% of those rows. This uses the full qualification panel and is descriptive geometry, not held-out predictive evidence.

## Bounded interpretation

This result weakens the specific hypothesis that float32 feature quantization near `g=0` explains the cross-block failure. B and C had indistinguishable pooled classification outcomes, and the large-margin subset still did not produce positive `Omega_hat`. The exact replay ceiling remains `Omega(F4)=1`; this test does not establish that the compact 80D representation preserves all F4 information, nor does it establish that no estimator can extract polarity from it.

Do not infer a biological mechanism or promote this result into the REACH-03 filtration ladder. The next reasonable qualification question, if separately authorized, is whether structured task-conditioned relational features recover cross-block polarity—not whether a larger MLP can rescue the same 80D map.
