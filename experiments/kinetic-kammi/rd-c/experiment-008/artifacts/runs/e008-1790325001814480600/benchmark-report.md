# R&D-C / Experiment 008 — Source Offer

**Status: synthetic engineering benchmark, exploratory.** The run uses 8 independently seeded development worlds and 16 held-out worlds (6,144 held-out episodes). Ordinary route plans were frozen before held-out labels and source replies were written. The oracle is evaluation-only. E007 remains sealed and is included as hashed provenance.

## Decision contract

The runtime estimates `Δ = P(wrong→right) − P(right→wrong) − P(baseline-right unresolved)`. It computes `Vλ = Δ̂ − λ × quoted query price − 0.02 × offer request cost`, requires `Vλ > 0`, then ranks eligible candidates by positive value. Budgets 16/32/64 are maximum calls per world; zero calls are valid. Price λ values are 0.000, 0.010, and 0.030. Avoided wrong commits are reported separately from completion.

The costed mode tests a paid quote refresh for a candidate selected from the pushed/cached snapshot. A returned quote is receipted and value is recomputed before inspection. It therefore measures marginal quote refresh cost and quote changes; the initial snapshot remains zero-marginal.

## Integrity gates

- Illegal authority commits: **0** (PASS).
- Duplicate endpoint charges in benchmark lanes: **0** (PASS).
- Journal replay identities: **1360 / 1360 plans passed** (PASS).
- Injected crash boundaries: **5 / 5 passed** (PASS).
- Offer input audit rows: **2064384**; deterministic field or field-pair/full-signature groups with support ≥8: **1** (flagged; held-out bank retained unchanged).

The input audit flagged at least one repeated offer signature. It is retained as a visible low-support held-out collision; the bank was not retuned, and the fitted policy does not use full-signature lookup. Treat model transfer as exploratory rather than promoting on pooled completion alone.

`Unknown` and `Failed` remain no-action typed results. Replay covers the authority receipt identity, paid-query journal, and hash-chained offer receipts. Exactly-once charging depends on endpoint deduplication by stable request ID.

## Held-out completion frontier

Values below are means over worlds; world is the variability unit. `completion gain` is relative to the paired zero-inspection floor. Query and offer costs are reported separately in `summary.csv` and `completion-cost-frontier.csv`.

| Lane | Stratum | Cap | λ | Offer path | Mean completion gain | Worlds with gain | Mean calls | Mean total cost |
|---|---|---:|---:|---|---:|---:|---:|---:|
| e007_eight_feature_positive_stop | all | 64 | 0.000 | pushed_or_cached | 0.00 | 0 | 0.00 | 0.00 |
| offer_simple | all | 64 | 0.000 | pushed_or_cached | -24.69 | 1 | 64.00 | 420.44 |
| offer_simple | all | 64 | 0.010 | pushed_or_cached | -25.44 | 1 | 64.00 | 258.94 |
| offer_simple | all | 64 | 0.030 | pushed_or_cached | -26.19 | 1 | 64.00 | 124.94 |
| offer_simple | all | 64 | 0.010 | costed_refresh_request | -20.62 | 1 | 64.00 | 453.50 |
| offer_simple | reliability_shift | 64 | 0.010 | pushed_or_cached | -17.50 | 1 | 64.00 | 234.50 |
| offer_simple | new_ids | 64 | 0.010 | pushed_or_cached | -27.50 | 0 | 64.00 | 224.50 |
| offer_simple | historical_reliability_misleading | 64 | 0.010 | costed_refresh_request | -29.50 | 0 | 64.00 | 536.00 |
| offer_fitted | all | 64 | 0.000 | pushed_or_cached | 0.00 | 0 | 0.00 | 0.00 |
| offer_fitted | all | 64 | 0.010 | pushed_or_cached | 0.00 | 0 | 0.00 | 0.00 |
| offer_fitted | all | 64 | 0.030 | pushed_or_cached | 0.00 | 0 | 0.00 | 0.00 |
| offer_fitted | all | 64 | 0.010 | costed_refresh_request | 0.00 | 0 | 0.00 | 0.00 |
| offer_fitted | reliability_shift | 64 | 0.010 | pushed_or_cached | 0.00 | 0 | 0.00 | 0.00 |
| offer_fitted | new_ids | 64 | 0.010 | pushed_or_cached | 0.00 | 0 | 0.00 | 0.00 |
| offer_fitted | historical_reliability_misleading | 64 | 0.010 | costed_refresh_request | 0.00 | 0 | 0.00 | 0.00 |
| shuffled_offers | all | 64 | 0.000 | pushed_or_cached | 0.00 | 0 | 0.00 | 0.00 |
| shuffled_offers | all | 64 | 0.010 | pushed_or_cached | 0.00 | 0 | 0.00 | 0.00 |
| shuffled_offers | all | 64 | 0.030 | pushed_or_cached | 0.00 | 0 | 0.00 | 0.00 |
| shuffled_offers | all | 64 | 0.010 | costed_refresh_request | 0.00 | 0 | 0.00 | 0.00 |
| shuffled_offers | reliability_shift | 64 | 0.010 | pushed_or_cached | 0.00 | 0 | 0.00 | 0.00 |
| shuffled_offers | new_ids | 64 | 0.010 | pushed_or_cached | 0.00 | 0 | 0.00 | 0.00 |
| shuffled_offers | historical_reliability_misleading | 64 | 0.010 | costed_refresh_request | 0.00 | 0 | 0.00 | 0.00 |
| matched_random | all | 64 | 0.000 | pushed_or_cached | 0.00 | 0 | 0.00 | 0.00 |
| matched_random | all | 64 | 0.010 | pushed_or_cached | 0.00 | 0 | 0.00 | 0.00 |
| matched_random | all | 64 | 0.030 | pushed_or_cached | 0.00 | 0 | 0.00 | 0.00 |
| matched_random | all | 64 | 0.010 | costed_refresh_request | 0.00 | 0 | 0.00 | 0.00 |
| matched_random | reliability_shift | 64 | 0.010 | pushed_or_cached | 0.00 | 0 | 0.00 | 0.00 |
| matched_random | new_ids | 64 | 0.010 | pushed_or_cached | 0.00 | 0 | 0.00 | 0.00 |
| matched_random | historical_reliability_misleading | 64 | 0.010 | costed_refresh_request | 0.00 | 0 | 0.00 | 0.00 |
| evaluation_oracle | all | 64 | 0.000 | pushed_or_cached | 41.81 | 16 | 41.81 | 218.94 |
| evaluation_oracle | all | 64 | 0.010 | pushed_or_cached | 41.81 | 16 | 41.81 | 218.94 |
| evaluation_oracle | all | 64 | 0.030 | pushed_or_cached | 41.81 | 16 | 41.81 | 218.94 |
| evaluation_oracle | reliability_shift | 64 | 0.010 | pushed_or_cached | 51.00 | 2 | 51.00 | 212.00 |
| evaluation_oracle | new_ids | 64 | 0.010 | pushed_or_cached | 46.00 | 2 | 46.00 | 238.00 |

The full world-by-world and stratum-by-stratum results are in `world-summary.csv`; pooled episode counts are not used for uncertainty. The matched-random audit records call-count and spend residuals after paid quote refresh.

## Outcome accounting

For each queried episode, the report preserves wrong→right, right→wrong, unresolved baseline-right, unresolved baseline-wrong, and avoided wrong commits as distinct counts. A query returning `Unknown` or `Failed` can avoid a wrong commit but strands a baseline-right episode; it does not authorize the active action. Selected-query calibration is in `value-calibration.csv`, grouped by predicted-value bins and source-quality bins. Unselected inspection outcomes are not treated as observed runtime events.

## Limitations

This is a deterministic synthetic harness with generated offers and source replies. Held-out world variation tests the specified shifts, not deployment transfer. The simple rule is hand-specified; the fitted value estimate is trained only on development worlds. The evaluation oracle uses held-out truth and source replies after ordinary route plans are frozen and is an upper-bound diagnostic only. Cost units are synthetic and are not monetary prices.

Run contains 16 held-out worlds, 15881 selected-query trace rows, and 1360 world-plan rows. E007 zero-call control has 0 selected calls across its held-out plans.
