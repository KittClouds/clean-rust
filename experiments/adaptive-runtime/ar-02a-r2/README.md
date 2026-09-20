# AR-02A-R2 — Verifier placebo-strata audit

Status: diagnostic complete; engineering-only and toy-scale. This is a new experiment directory on the existing dated branch. AR-02A and R1 are left unchanged.

## Question

At the P16/V48 operating point, does a meaningful training-data partition improve verification estimates beyond quota balancing alone? The diagnostic compares estimator quality on frozen runtime snapshots before authorizing any additional full-training arms.

## Frozen protocol

- Reuse the exact AR-02A Gaussian-cell dataset (96 training and 48 validation samples; SHA-256 `a83d5dcce8bd8926cf1d548c58d4a9cbbef0ca97c72e1fd4331bc5d825a7a14a`).
- Replay the unchanged P16/V48-random K2 runtime for the three R1 seeds. Capture states after commits 600, 2,400, and 4,200. A unit test compares replayed train and validation losses to the committed R1 curve checkpoints within `1e-7`.
- At each snapshot, recreate the next P16 proposal batch and the active pair schedule. Freeze the K2 shortlist: top-2 singleton actions per coordinate, then four exact candidate compounds per pair (plus the proposal-selected singleton candidate for the unmatched coordinate).
- Calculate each candidate's exact per-training-example utility vector on all 96 training examples. Validation is never used to build strata, score a candidate, or select a program.
- For each snapshot, draw 64 independent verifier panels from each construction:
  - IID random 48 with replacement (R1 control).
  - IID random 48 without replacement.
  - Cell-stratified: 4 of 8 examples without replacement from each of 12 true latent cells.
  - Bayes-margin-stratified: 4 of 8 without replacement from each of 12 class-conditional margin quartiles.
  - Eight deterministic hash-random placebo partitions. Each partitions the 96 training indices into 12 groups of 8; each panel takes 4 without replacement per group. All eight are retained and reported separately; none is selected by outcome.
- All 48 selected examples have equal weight. For each panel, report utility RMSE and sign error against per-candidate full-training utility; within-block regret; cross-block opportunity regret; selected-program regret; and false-positive authorization. The selected-program regret decomposition is asserted at runtime.
- This phase is diagnostic only. No panel affects training. Any training follow-up requires reviewing the frozen diagnostic output first.

## Outputs

- `r2-panel-audit.csv`: one row per method × seed × snapshot × panel.
- `r2-replay-checkpoints.csv`: replayed snapshot losses and parameter fingerprints.
- `r2-diagnostic-report.json`: panel metric means by construction.
- `gaussian-cells.bin`: immutable copy of the R1 dataset artifact.

## Results

The release audit completed in 20.80 seconds and produced 6,912 rows: 12 constructions × 3 seeds × 3 snapshots × 64 panels. Every method has 576 panel observations. Bounds left 241–245 feasible programs per snapshot; all verifier constructions score the same candidate universe at each state. The R2 dataset SHA-256 matches R1. All nine replayed train/validation checkpoint values match the R1 curve at its recorded precision; the unit-test replay check also passes within `1e-7`. The selected-program regret decomposition is asserted for every panel.

Mean conditional panel metrics (not independent training-run estimates):

| Construction | Utility RMSE | Sign error | Cross-block regret | Selected-program regret | False authorization |
|---|---:|---:|---:|---:|---:|
| IID 48 with replacement | 8.590e-4 | 33.42% | 6.145e-4 | 7.760e-4 | 25.52% |
| IID 48 without replacement | 5.984e-4 | 29.33% | 5.629e-4 | 6.958e-4 | 21.53% |
| Cell, 4 per true cell | **4.332e-4** | **21.85%** | **4.126e-4** | **5.073e-4** | **14.24%** |
| Class × Bayes-margin, 4 per stratum | 5.081e-4 | 25.92% | 4.994e-4 | 5.942e-4 | 16.67% |
| Hash placebo, mean over 8 partitions | 6.216e-4 | 29.80% | 5.395e-4 | 6.686e-4 | 20.68% |

Across the nine seed/snapshot states, cell stratification beat the mean of the eight placebos on utility RMSE and sign error in all nine; it also lowered cross-block and selected-program regret in eight of nine. Each placebo's pooled RMSE was between `6.140e-4` and `6.322e-4`, and its selected-program regret between `6.398e-4` and `7.295e-4`. Margin stratification also improved the pooled diagnostics over the placebo mean, though less than cell stratification. The placebo results track IID without replacement much more closely than either true partition.

This supports a bounded conclusion: at the frozen P16/V48 random-trajectory states, the *contents* of the cell and margin partitions improve verifier-estimator quality beyond equal-quota mechanics alone. It does not establish a general sampling rule. R1 already contains full-training runs for the random, cell, and margin V48 arms (mean validation losses `0.4509`, `0.3603`, and `0.4176`, respectively); R2 adds no new training arm. No post-hoc choice among the eight placebo partitions was made.

The main alternative is that these task-informed strata happen to explain heterogeneity in candidate per-example utilities on this synthetic dataset. The audit conditions on only three seeds and three snapshots from the random-verifier trajectory; it does not show that the same strata help on another task, or that panel-estimator gains alone cause the final-loss differences. Accordingly, the result is estimator-level and toy-scale. The AR-02B path-source crossover is now eligible to proceed; no broader optimizer claim follows.

## Interpretation limits

There are three training seeds and three dependent snapshots per seed. The 64 panels estimate conditional verifier behavior at those states; they are not 64 independent training replications. Eight placebo partitions reduce dependence on one arbitrary partition but still do not establish universal sampling geometry. No training outcome is inferred from estimator RMSE alone. Results remain engineering-only, with no biological correspondence or general optimizer claim.

## Build

Release/test artifacts are directed to `D:\adaptive-runtime-targets\ar-02a-r2`, on the configured `:G` target volume.
