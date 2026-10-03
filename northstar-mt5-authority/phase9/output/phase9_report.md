# RG2 Phase 9 — coverage and QC

**Decision: `HOLD_RG2_FOR_LIFECYCLE_COVERAGE_REVIEW`**

This report describes dataset geometry only. It contains no strategy labels, win rate, feature selection, or model.

## Corpus integrity

- Status: **PASS**
- Runs: 20 across 6 instruments and 1 data source
- Observed bars: 21,235 (1769.6 bar-hours)
- Scheduled window span: 2356.2 hours
- Data gaps: 0 unexpected; profile bar delta 0
- Replay: PASS (1 exact duplicate)
- Replay canonical hash agreement: True
- Relational invariant failures: 0
- Corpus fingerprint: `3de4a043f52ff997e3e8de9428a4bbfcb17d94b41935a2ce9b64ebc0dce80a34`

- Semantic result hash: `119d87d2be6d9b4337e6af0d7752596c61873c05598f4438514a016ec81574ae`

## Population

- Nodes: 2,294 created; 2,077 retired; 217 persisted at cutoff
- Events: 38,957
- Attempts: 7,764
- Episodes: 1,462 (1,434 resolved, 28 right-censored; 1.92%)
- Transits: 628
- Behavioral episode resolutions: 186 (12.72%)

## Principal geometry finding

- `NODE_RETIRED`: 853 resolved + 3 censored/provisional rows; 59.48% of resolved episodes.
- Those resolved retirement episodes begin on nodes with median age **5s**, median width **0.091 ATR**, and median duration **946s**; 692/853 begin before node age one hour.
- `TIMEOUT`: 395 resolved + 5 censored/provisional rows; 27.55% of resolved episodes.
- Those resolved timeout episodes begin on nodes with median age **4.46h**, median width **2.486 ATR**, and median duration **3.54h**; 240/395 are wider than 1 ATR.
- Structurally retired nodes have median observed lifetime **2.00h**. Nodes persisted at cutoff have median observed age **20.88h** and remain censored.
- This separation is descriptive. It does not establish whether lifecycle churn or grammar thresholds should change.

## Instrument coverage

| value | count | share | censored_count | censoring_rate |
|---|---|---|---|---|
| US500 | 311 | 21.27% | 6 | 1.93% |
| JPN225 | 295 | 20.18% | 4 | 1.36% |
| US30 | 234 | 16.01% | 5 | 2.14% |
| FRA40 | 221 | 15.12% | 6 | 2.71% |
| DE40 | 215 | 14.71% | 4 | 1.86% |
| USTEC | 186 | 12.72% | 3 | 1.61% |

## Regional coverage

| value | count | share | censored_count | censoring_rate |
|---|---|---|---|---|
| MEDIAN_CORE | 848 | 58.00% | 12 | 1.42% |
| BELOW | 294 | 20.11% | 6 | 2.04% |
| ABOVE | 243 | 16.62% | 5 | 2.06% |
| FAR_BELOW | 47 | 3.21% | 3 | 6.38% |
| FAR_ABOVE | 29 | 1.98% | 2 | 6.90% |
| EXTREME_BELOW | 1 | 0.07% | 0 | 0.00% |

## Auction resolutions

| value | count | share | censored_count | censoring_rate |
|---|---|---|---|---|
| NODE_RETIRED | 856 | 58.55% | 3 | 0.35% |
| TIMEOUT | 400 | 27.36% | 5 | 1.25% |
| TRANSIT_TO_NEXT_NODE | 91 | 6.22% | 4 | 4.40% |
| RECLAIM_AFTER_BREAK | 47 | 3.21% | 0 | 0.00% |
| RETURN_TO_SOURCE_NODE | 22 | 1.50% | 0 | 0.00% |
| ACCEPT_AND_HOLD_RETEST | 16 | 1.09% | 0 | 0.00% |
| REJECT_TO_ORIGIN | 13 | 0.89% | 10 | 76.92% |
| ACCEPT_AND_FAIL_RETEST | 8 | 0.55% | 4 | 50.00% |
| ACCEPT_THROUGH_NODE | 7 | 0.48% | 0 | 0.00% |
| NONE | 2 | 0.14% | 2 | 100.00% |

## Attempt ordinal

| value | count | share | censored_count | censoring_rate |
|---|---|---|---|---|
| 1 | 1174 | 15.12% | 1 | 0.09% |
| 2 | 692 | 8.91% | 0 | 0.00% |
| 3 | 543 | 6.99% | 3 | 0.55% |
| 4 | 444 | 5.72% | 1 | 0.23% |
| 5 | 385 | 4.96% | 0 | 0.00% |
| 6 | 338 | 4.35% | 2 | 0.59% |
| 7 | 303 | 3.90% | 1 | 0.33% |
| 8 | 273 | 3.52% | 0 | 0.00% |
| 9 | 248 | 3.19% | 0 | 0.00% |
| 10 | 227 | 2.92% | 3 | 1.32% |
| 11 | 209 | 2.69% | 0 | 0.00% |
| 12 | 189 | 2.43% | 1 | 0.53% |
| 13 | 177 | 2.28% | 0 | 0.00% |
| 14 | 161 | 2.07% | 0 | 0.00% |
| 15 | 145 | 1.87% | 0 | 0.00% |
| 16 | 134 | 1.73% | 0 | 0.00% |
| 17 | 118 | 1.52% | 0 | 0.00% |
| 18 | 110 | 1.42% | 1 | 0.91% |
| 19 | 101 | 1.30% | 0 | 0.00% |
| 20 | 97 | 1.25% | 1 | 1.03% |
| 21 | 88 | 1.13% | 0 | 0.00% |
| 22 | 86 | 1.11% | 1 | 1.16% |
| 23 | 79 | 1.02% | 1 | 1.27% |
| 24 | 74 | 0.95% | 0 | 0.00% |
| 25 | 70 | 0.90% | 0 | 0.00% |
| 26 | 66 | 0.85% | 0 | 0.00% |
| 27 | 60 | 0.77% | 0 | 0.00% |
| 28 | 56 | 0.72% | 0 | 0.00% |
| 29 | 52 | 0.67% | 0 | 0.00% |
| 30 | 48 | 0.62% | 0 | 0.00% |
| 31 | 47 | 0.61% | 0 | 0.00% |
| 32 | 47 | 0.61% | 0 | 0.00% |
| 33 | 45 | 0.58% | 0 | 0.00% |
| 34 | 43 | 0.55% | 1 | 2.33% |
| 35 | 39 | 0.50% | 0 | 0.00% |
| 36 | 37 | 0.48% | 0 | 0.00% |
| 37 | 35 | 0.45% | 0 | 0.00% |
| 38 | 34 | 0.44% | 0 | 0.00% |
| 40 | 32 | 0.41% | 0 | 0.00% |
| 39 | 32 | 0.41% | 0 | 0.00% |
| 41 | 30 | 0.39% | 0 | 0.00% |
| 42 | 30 | 0.39% | 0 | 0.00% |
| 43 | 28 | 0.36% | 0 | 0.00% |
| 45 | 23 | 0.30% | 0 | 0.00% |
| 44 | 23 | 0.30% | 0 | 0.00% |
| 47 | 21 | 0.27% | 0 | 0.00% |
| 46 | 21 | 0.27% | 0 | 0.00% |
| 48 | 20 | 0.26% | 1 | 5.00% |
| 49 | 19 | 0.24% | 0 | 0.00% |
| 50 | 18 | 0.23% | 0 | 0.00% |
| 54 | 16 | 0.21% | 0 | 0.00% |
| 53 | 16 | 0.21% | 0 | 0.00% |
| 52 | 16 | 0.21% | 0 | 0.00% |
| 51 | 16 | 0.21% | 0 | 0.00% |
| 55 | 15 | 0.19% | 0 | 0.00% |
| 57 | 13 | 0.17% | 0 | 0.00% |
| 56 | 13 | 0.17% | 0 | 0.00% |
| 58 | 12 | 0.15% | 0 | 0.00% |
| 59 | 12 | 0.15% | 0 | 0.00% |
| 60 | 12 | 0.15% | 0 | 0.00% |
| 66 | 11 | 0.14% | 0 | 0.00% |
| 63 | 11 | 0.14% | 0 | 0.00% |
| 62 | 11 | 0.14% | 0 | 0.00% |
| 64 | 11 | 0.14% | 0 | 0.00% |
| 65 | 11 | 0.14% | 0 | 0.00% |
| 61 | 11 | 0.14% | 0 | 0.00% |
| 67 | 10 | 0.13% | 0 | 0.00% |
| 68 | 9 | 0.12% | 0 | 0.00% |
| 71 | 8 | 0.10% | 0 | 0.00% |
| 69 | 8 | 0.10% | 0 | 0.00% |
| 72 | 8 | 0.10% | 0 | 0.00% |
| 70 | 8 | 0.10% | 0 | 0.00% |
| 77 | 7 | 0.09% | 0 | 0.00% |
| 74 | 7 | 0.09% | 0 | 0.00% |
| 76 | 7 | 0.09% | 0 | 0.00% |
| 75 | 7 | 0.09% | 0 | 0.00% |
| 79 | 7 | 0.09% | 0 | 0.00% |
| 78 | 7 | 0.09% | 0 | 0.00% |
| 73 | 7 | 0.09% | 0 | 0.00% |
| 80 | 6 | 0.08% | 0 | 0.00% |
| 84 | 5 | 0.06% | 0 | 0.00% |
| 89 | 5 | 0.06% | 0 | 0.00% |
| 90 | 5 | 0.06% | 1 | 20.00% |
| 82 | 5 | 0.06% | 0 | 0.00% |
| 88 | 5 | 0.06% | 0 | 0.00% |
| 85 | 5 | 0.06% | 0 | 0.00% |
| 87 | 5 | 0.06% | 0 | 0.00% |
| 86 | 5 | 0.06% | 0 | 0.00% |
| 83 | 5 | 0.06% | 0 | 0.00% |
| 81 | 5 | 0.06% | 0 | 0.00% |
| 92 | 3 | 0.04% | 0 | 0.00% |
| 91 | 3 | 0.04% | 0 | 0.00% |
| 94 | 3 | 0.04% | 0 | 0.00% |
| 93 | 3 | 0.04% | 0 | 0.00% |
| 95 | 3 | 0.04% | 0 | 0.00% |
| 96 | 2 | 0.03% | 0 | 0.00% |
| 97 | 2 | 0.03% | 1 | 50.00% |
| 101 | 1 | 0.01% | 0 | 0.00% |
| 107 | 1 | 0.01% | 0 | 0.00% |
| 100 | 1 | 0.01% | 0 | 0.00% |
| 108 | 1 | 0.01% | 0 | 0.00% |
| 102 | 1 | 0.01% | 0 | 0.00% |
| 104 | 1 | 0.01% | 0 | 0.00% |
| 103 | 1 | 0.01% | 0 | 0.00% |
| 105 | 1 | 0.01% | 0 | 0.00% |
| 106 | 1 | 0.01% | 0 | 0.00% |
| 98 | 1 | 0.01% | 0 | 0.00% |
| 99 | 1 | 0.01% | 0 | 0.00% |

## Producer combinations

| value | count | share | censored_count | censoring_rate |
|---|---|---|---|---|
| VOLKITT+WAYNE | 3378 | 43.51% | 14 | 0.41% |
| DAY_SWINGS+VOLKITT+WAYNE | 1395 | 17.97% | 0 | 0.00% |
| DAY_SWINGS+WAYNE | 1090 | 14.04% | 1 | 0.09% |
| WAYNE | 908 | 11.70% | 4 | 0.44% |
| VOLKITT | 563 | 7.25% | 1 | 0.18% |
| DAY_SWINGS+VOLKITT | 341 | 4.39% | 0 | 0.00% |
| DAY_SWINGS | 89 | 1.15% | 0 | 0.00% |

## Node lifecycle

| value | count | share | censored_count | censoring_rate |
|---|---|---|---|---|
| RETIRED | 2077 | 90.54% | 0 | 0.00% |
| PERSISTED_AT_CUTOFF | 217 | 9.46% | 217 | 100.00% |

## Continuous distributions

| unit | metric | count | missing_count | censoring_rate | p05 | median | p95 | mean | std |
|---|---|---|---|---|---|---|---|---|---|
| episode | duration_seconds | 1462 | 0 | 0.01915 | 9.05 | 3600 | 3.069e+04 | 8052 | 1.156e+04 |
| episode | node_width_atr | 1462 | 0 | 0.01915 | 0.0004251 | 0.1088 | 11.44 | 2.149 | 4.126 |
| episode | node_age_seconds | 1462 | 0 | 0.01915 | 0 | 155 | 1.423e+05 | 2.363e+04 | 5.046e+04 |
| episode | start_median_sigma | 1462 | 0 | 0.01915 | -1.237 | -0.006793 | 1.151 | -0.05388 | 0.7083 |
| attempt | duration_seconds | 7764 | 0 | 0.002576 | 34 | 421 | 7349 | 1397 | 2923 |
| attempt | penetration_atr | 7764 | 0 | 0.002576 | 0 | 0.2183 | 2.87 | 0.6628 | 1.211 |
| attempt | inside_seconds | 7764 | 0 | 0.002576 | 0 | 24 | 1438 | 298.5 | 1029 |
| attempt | approach_efficiency | 7764 | 0 | 0.002576 | 0 | 0.1228 | 1 | 0.2556 | 0.3072 |
| attempt | node_width_atr | 7764 | 0 | 0.002576 | 0.01688 | 1.087 | 11.84 | 3.113 | 4.268 |
| attempt | node_age_seconds | 7764 | 0 | 0.002576 | 3 | 1.553e+04 | 1.805e+05 | 4.42e+04 | 6.271e+04 |
| attempt | start_median_sigma | 7764 | 0 | 0.002576 | -1.381 | -0.007927 | 1.091 | -0.05009 | 0.7061 |
| attempt | feature_price_from_cog_sigma | 7764 | 0 | 0.002576 | -1.218 | 0.1434 | 2.339 | 0.4005 | 1.143 |
| attempt | feature_cog_median_gap_sigma | 7764 | 0 | 0.002576 | -1.81 | -0.2934 | 0.4251 | -0.4506 | 0.7535 |
| attempt | feature_regional_sigma_log_change_per_bar | 7764 | 0 | 0.002576 | -0.03621 | 0 | 0.002417 | -0.002041 | 0.02849 |
| transit | distance_atr | 628 | 0 | 0 | 0.5848 | 3.38 | 13.84 | 4.924 | 5.737 |
| transit | duration_seconds | 628 | 0 | 0 | 0 | 206 | 6452 | 1155 | 2942 |

## Question-readiness ledger

| question | unit | evidence_count | readiness | reason |
|---|---|---|---|---|
| Why do resolved episodes terminate through node retirement? | episode | 853 | READY_DESCRIPTIVE | semantic lifecycle audit; no expectancy |
| Is node retirement concentrated by instrument? | episode | 186 | READY_DESCRIPTIVE | all six instruments populated |
| What contexts accompany node-to-node transit? | transit | 628 | READY_DESCRIPTIVE | descriptive geometry only |
| What contexts accompany reclaim after break? | episode | 47 | READY_DESCRIPTIVE | cross-cells may remain sparse |
| What contexts accompany accepted retest failure? | episode | 4 | INSUFFICIENT | too few for conditional inference |
| How do EXTREME_ABOVE episodes behave? | episode | 0 | EMPTY | empty regional cell |
| How do EXTREME_BELOW episodes behave? | episode | 1 | INSUFFICIENT | near-empty regional cell |
| Does repeated testing differ by attempt ordinal? | episode | 886 | READY_DESCRIPTIVE | episodes with repeated attempts; within-episode attempts remain dependent |
| Do exact producer combinations differ? | attempt | 89 | PRELIMINARY_ONLY | 7 combinations have at least 30 attempts |
| Are both approach directions represented? | episode | 701 | READY_DESCRIPTIVE | from-above and from-below mirrors are both populated |
| Can behavior be compared across data sources? | run | 1 | EMPTY_COMPARISON | RG2 contains one data source |
| Can behavior be compared across core sigma bands? | episode | 177 | READY_DESCRIPTIVE | minimum cell across negative core, median core, and positive core |
| Can behavior be compared at absolute sigma above two? | episode | 17 | PRELIMINARY_ONLY | both extreme sigma tails combined |
| Can node age and width be audited against retirement/timeout? | episode | 1462 | READY_DESCRIPTIVE | stratified continuous and categorical geometry available |
| How does corridor geometry differ across resolutions? | attempt | 7764 | READY_DESCRIPTIVE | continuous distributions and cross-coverage available |
| Can RG2 support a predictive model? | corpus | 1462 | BLOCKED_BY_DESIGN | Phase 9 forbids modeling; outcome imbalance requires review |

## QC interpretation

- The corpus is coherent and replay-stable.
- Node retirement and timeout dominate episode resolution; that is a semantic coverage finding, not a trading result.
- Right-censored episodes may retain their latest provisional resolution. Completed behavioral evidence excludes those rows.
- Extreme regional cells and accepted/retest outcomes remain too sparse for conditional research.
- Percentages in coverage tables always retain counts and unit-specific censoring rates.
- Persisted nodes at cutoff are censored lifecycle observations, not inferred retirements.

## Output contract

The adjacent CSV/JSON artifacts contain the full coverage, cross-coverage, missingness, continuous-distribution, node-lifecycle, run-QC, and readiness tables.