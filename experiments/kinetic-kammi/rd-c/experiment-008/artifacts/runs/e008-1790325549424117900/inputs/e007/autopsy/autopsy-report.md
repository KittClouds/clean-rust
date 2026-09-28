# E007 post-hoc autopsy v1

Source run: `e007-1790316330677261600`. This analysis reads the sealed E007 run and writes only under `analysis/e007-autopsy-v1/`.

**Status: exploratory and outcome-conditioned.** Held-out labels and source replies are used below for reconciliation, calibration, and cross-world diagnostics. None of these estimates are runtime evidence or a promotion result.

## 64-call completion reconciliation

The full held-out feature-router lane reconciles exactly: `130 - 171 - 221 = -262` net completions. Residual is zero in every world and stratum.

Unresolved outcomes split into **Unknown**: 105 baseline-right and 51 baseline-wrong; **Failed**: 116 baseline-right and 53 baseline-wrong. Thus 221 previously correct tasks were stranded, while 104 unresolved cases avoided a wrong commit. Those avoided commits are safety outcomes and contribute zero completions relative to the zero-query floor.

### By stratum

| Stratum | W→R | R→W | U right | U wrong | F right | F wrong | Avoided wrong commits | Net gain | Residual |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| familiar_ids | 47 | 20 | 17 | 10 | 33 | 12 | 22 | -23 | 0 |
| new_ids | 25 | 21 | 21 | 11 | 41 | 18 | 29 | -58 | 0 |
| reliability_shift | 31 | 47 | 35 | 13 | 30 | 14 | 27 | -81 | 0 |
| stale_sources | 27 | 83 | 32 | 17 | 12 | 9 | 26 | -100 | 0 |

`world-reconciliation.csv` gives the same decomposition for all 16 worlds. `unresolved-breakdown.png` shows the four Unknown/Failed × baseline-right/wrong components per world.

## Frozen predicted value, realized value, and query price

The frozen E007 development model predicts completion delta from the original eight features. Its selection score is predicted delta divided by query cost. Score-bin cut points are derived from development score quantiles and reused for held-out worlds, so the cohort rows are directly comparable. Held-out slices use hidden status only for post-hoc grouping. Unknown and Failed rates describe the stored reply if queried, including episodes the router did not select. Whiskers use standard errors across worlds, not individual episodes.

| Cohort | Development score bin | Episodes | Mean predicted Δ | Mean realized Δ | Mean query cost | Unknown rate | Failed rate |
|---|---:|---:|---:|---:|---:|---:|---:|
| development | 1 | 205 | -0.3052 | -0.3756 | 1.00 | 0.107 | 0.254 |
| development | 2 | 205 | -0.2863 | -0.3463 | 1.46 | 0.107 | 0.244 |
| development | 3 | 205 | -0.3076 | -0.2634 | 2.00 | 0.117 | 0.180 |
| development | 4 | 204 | -0.2728 | -0.3137 | 2.00 | 0.083 | 0.206 |
| development | 5 | 205 | -0.2679 | -0.2585 | 2.29 | 0.093 | 0.224 |
| development | 6 | 205 | -0.2932 | -0.3366 | 2.96 | 0.132 | 0.254 |
| development | 7 | 204 | -0.2931 | -0.2794 | 3.51 | 0.098 | 0.201 |
| development | 8 | 205 | -0.2705 | -0.2537 | 3.83 | 0.127 | 0.190 |
| development | 9 | 205 | -0.2922 | -0.2390 | 5.28 | 0.117 | 0.205 |
| development | 10 | 205 | -0.2600 | -0.2146 | 5.98 | 0.117 | 0.180 |
| heldout | 1 | 93 | -0.3074 | 0.1075 | 1.00 | 0.065 | 0.097 |
| heldout | 2 | 133 | -0.3094 | -0.0301 | 1.70 | 0.143 | 0.143 |
| heldout | 3 | 246 | -0.3086 | -0.0691 | 2.00 | 0.118 | 0.142 |
| heldout | 4 | 232 | -0.2724 | -0.1422 | 2.00 | 0.125 | 0.172 |
| heldout | 5 | 285 | -0.2725 | -0.0632 | 2.34 | 0.123 | 0.189 |
| heldout | 6 | 300 | -0.2905 | -0.1033 | 2.95 | 0.197 | 0.173 |
| heldout | 7 | 522 | -0.2926 | -0.1801 | 3.51 | 0.148 | 0.148 |
| heldout | 8 | 680 | -0.2792 | -0.2544 | 4.00 | 0.141 | 0.176 |
| heldout | 9 | 756 | -0.2914 | -0.1733 | 5.25 | 0.167 | 0.142 |
| heldout | 10 | 2897 | -0.2756 | -0.2520 | 8.97 | 0.167 | 0.156 |

![Frozen router calibration by score bin, reliability, stale-source status, unseen IDs, and price](value-calibration-price.png)

See `score-calibration.csv` for held-out bins split by reliability-shift and stale-source strata, actual stale/fresh source status, and unseen/familiar domain IDs. `episode-value-diagnostics.csv` contains the post-hoc per-episode prediction, price, typed result, and realized completion delta for development and held-out rows.

The frozen scorer predicted negative net completion delta for 2048/2,048 development episodes and 6144/6,144 held-out episodes. At the exact 64-call cap, the feature router bought 1024 inspections for 9214 cost units total (9.00/query), versus 1024 matched-random calls for 6171 units (6.03/query). Since the router ranks `predicted_delta / price` in descending order, dividing a negative estimate by a larger price moves its score toward zero and can rank a more expensive query above a cheaper one. This score ordering explains the elevated spend; the exact-call budget made it impossible to stop at zero.

For the next policy specification, treat each query budget as a maximum. A router needs a calibrated net-value-after-price-and-unresolved-risk estimate and must permit zero calls when that estimate is negative. This autopsy does not alter the sealed runtime.

## Cross-world feature-only ranking estimate

For each held-out world, an outer leave-one-world-out fold holds all 384 of its outcomes out. The other 15 worlds supply exploratory training data. Three inner world-group folds select among standardized ridge regressors and uniform K-nearest-neighbor regressors; each candidate ranks by predicted completion delta divided by public query price. The best candidate on inner-world mean completion gain is refit on the other 15 worlds and scored on the untouched outer world.

This estimates transfer available to the eight public features under the tested model families. It is not a mathematical feature-information ceiling: other estimators could do better, and the development-world training boundary is intentionally relaxed for this post-hoc diagnostic only.

| Max queries/world | No-inspection floor | Frozen E007 feature | Matched random | Cross-world feature-only | Full-information oracle |
|---:|---:|---:|---:|---:|---:|
| 16 | 0.00 | -4.12 | -4.00 | -0.81 | 16.00 |
| 32 | 0.00 | -8.94 | -6.31 | -1.50 | 31.31 |
| 64 | 0.00 | -16.38 | -12.94 | -4.81 | 49.25 |

The inner folds selected {'knn_256': 11, 'ridge_0.001': 2, 'ridge_0.01': 2, 'knn_128': 1} across 16 outer worlds. The cross-world ranker uses held-out labels from other worlds, so its results are an exploratory estimate of feature signal, not an independent replication. Within the tested ridge/KNN families, feature-only ranking stays below the zero-call floor at all three exact budgets while the full-information oracle is positive. This evidence argues against another ridge-weight tweak. Other estimators may extract more value from these features.

![World-held-out feature-only ranking compared with the frozen router and full-information oracle](feature-only-ceiling.png)

## Zero-call stopping diagnostic

As a diagnostic of removing forced spending, each frozen or cross-world estimate selects only episodes with predicted completion delta above zero, ranked by prediction/query-cost, capped at 64 per world. The frozen scorer makes zero calls; the cross-world fit makes only three calls across all 16 worlds and loses two completions. No completion-to-cost exchange rate is specified here, so this tests the sign gate and cost ordering only; it does not claim net economic optimality.

| Diagnostic policy | Mean calls/world | Worlds with zero calls | Mean realized gain/world | Total gain | Mean cost units/world |
|---|---:|---:|---:|---:|---:|
| crossworld_feature_positive_stop | 0.19 | 15 | -0.12 | -2 | 0.94 |
| frozen_feature_positive_stop | 0.00 | 16 | 0.00 | 0 | 0.00 |

## Interpretation boundary

E007’s deterministic authority and paid-query recovery result remains intact. The inspection policy regressed completion because harmful contradictions and unresolved results outweighed corrections. This autopsy does not specify a second evidence path or a new lifecycle. That design question remains open until the breakdown above identifies recoverable unresolved cases.

The bank has 16 held-out worlds with 384 episodes each. Outcome-conditioned feature fitting uses 15 held-out worlds to predict the remaining world and rotates across all worlds. Results describe these generators and feature semantics only.
