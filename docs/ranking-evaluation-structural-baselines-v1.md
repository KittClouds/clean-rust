# Ranking Evaluation and Structural Baselines v1

## Purpose

`phoenix-ranking-evaluation/v1` is the authoritative evaluator for typed-link prediction and hyperedge-role completion. It consumes the candidate rows certified by Train-Topology Feature Derivation v1 and never reads live graph state.

The evaluator is framework-neutral. Candle, Burn, or another Rust model runtime supplies one finite score per borrowed `DerivedFeatureRow`; Phoenix owns candidate grouping, filtering assumptions, rank calculation, validation selection, test locking, and immutable reporting.

## Filtered candidate contract

Link negatives were already filtered against every asserted or candidate edge with the same source and relation. Hyperedge-role negatives were filtered against every incidence with the same hyperedge and role.

A query must contain exactly one positive. A positive with no safe negative candidates is omitted as unrankable rather than treated as rank one. Rankable query and candidate counts remain explicit in every metric surface, and each task separately reports zero-negative omissions by split.

Missing or multiple positives, mixed splits inside one query, score-array shape drift, and non-finite framework scores fail closed.

## Tie policy

Ranks use:

`1 + candidates scoring above positive + 0.5 * negative candidates tied with positive`

MRR uses the reciprocal of that average rank. Hits@1/3/10 receives fractional credit when a tie block crosses the cutoff. This removes candidate-order bias while preserving the uncertainty created by an uninformative scorer.

## Structural baseline ladder

Typed-link prediction evaluates:

1. common outgoing plus incoming neighbors;
2. source/target relation-degree prior;
3. preferential attachment.

Hyperedge-role completion evaluates:

1. participant-role prior;
2. global role prior;
3. composite train-topology incidence and graph degree.

Each task selects its family using highest validation filtered MRR, then validation Hits@10. Stable family order resolves an exact final tie. Test metrics are computed only for the selected family. Tasks without rankable validation queries report `insufficient-validation-queries` and do not unlock test.

## Metrics

Every available split records:

- rankable query count;
- candidate count;
- filtered mean reciprocal rank;
- filtered Hits@1;
- filtered Hits@3;
- filtered Hits@10.

## Candle and Burn integration seam

`evaluate_ranking_scores(rows, scores, split)` accepts ordinary borrowed Rust slices. A Candle or Burn adapter should:

1. load the zero-copy `.ttf` feature records;
2. create framework tensors without changing row order;
3. return one `f32` score per row;
4. pass those scores to Phoenix evaluation.

The adapter does not implement filtering, ranking, split selection, or test access. Model artifacts must reference the derivation id and evaluation protocol id.

## Immutable report

`RankingEvaluationBundle::write` installs `<report-id>.ranking.json` using create-new, `sync_all`, and rename. The report id is BLAKE3-addressed over derivation identity, protocol identity, tie policy, all validation results, selected families, and the selected-family test results.

## Entry points

- `evaluate_ranking_scores` evaluates arbitrary Candle/Burn/framework scores.
- `run_structural_ranking_baselines` executes the framework-free ladder.
- `RankingEvaluationBundle::write` persists the immutable report.
- `GraphStageApi::evaluate_structural_rankings` performs the full store-backed freeze, tensorize, certify, derive, and rank path.
