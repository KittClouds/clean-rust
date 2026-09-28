# AR-02A-R2-VAR1 — finite-population variance sidecar

Status: diagnostic-only; no training or policy decisions are run here.

## Question

Does the exact finite-population variance of the verifier-utility estimator predict the R2 ordering between meaningful cell/margin strata and equal-quota hash-placebo strata?

## Frozen inputs and method

- Read the immutable dataset and R2 panel/checkpoint artifacts from `../ar-02a-r2/artifacts/`.
- Replay only the three already-frozen R2 random-proposal trajectories to commits 600, 2,400, and 4,200; verify each reconstructed state against the saved train/validation losses and parameter fingerprint.
- Reconstruct the same K2 candidate universe and each candidate's 96 per-example utility values. No model update is selected or committed by this sidecar.
- Compute the finite-population variance analytically for IID-with-replacement, IID-without-replacement, 4-per-cell, 4-per-class×Bayes-margin, and each of the eight 4-per-hash-stratum placebo estimators.
- Compare each predicted candidate-averaged RMSE with the root-mean-square of the 64 observed R2 panel RMSE values at that state and construction.

For strata `h`, use `W_h=N_h/N` and the exact without-replacement estimator variance

`sum_h W_h^2 * (1 - n_h/N_h) * S_h^2/n_h`,

where `S_h^2` uses denominator `N_h-1`. Here the true and placebo strata each have `N_h=8`, `n_h=4`; the full population objective gives each example equal weight.

## Outputs

- `artifacts/r2-variance-states.csv`: one row per frozen seed/snapshot/construction (108 rows).
- `artifacts/r2-variance-summary.csv`: pooled predicted-versus-observed RMSE and within-stratum variance by construction.

## Results

The sidecar reconstructed 2,195 candidate/state utility vectors across the nine frozen states and emitted 108 state/method rows. Every replayed train/validation loss and parameter fingerprint matched the R2 checkpoint receipt; no training or action selection was performed. Each of the 12 constructions has 576 observed panel rows (nine states × 64 panels).

| Construction | Predicted RMSE from exact finite-population variance | Observed RMS panel RMSE | Mean variance component |
|---|---:|---:|---:|
| IID with replacement | `9.842e-4` | `9.996e-4` | `4.649e-5` |
| IID without replacement | `6.996e-4` | `6.822e-4` | `4.698e-5` |
| Cell, 4 per true cell | **`5.312e-4`** | **`5.371e-4`** | **`2.709e-5`** |
| Class × Bayes-margin, 4 per stratum | `5.953e-4` | `6.080e-4` | `3.402e-5` |
| Hash placebo, mean over 8 partitions | `7.090e-4` | `7.077e-4` | `4.826e-5` |

Predicted and observed RMS panel RMSE differ by a mean 3.65% relative across the 108 rows (maximum 13.43%). Cell and margin stratification both have lower predicted and observed RMS than the hash-placebo mean at all nine states. The cell partition's mean within-stratum utility variance component is 43.8% below the placebo mean; the margin partition's is 29.5% below.

This supports the specific mechanism that these prospective task-informed strata group candidate-example consequences more homogeneously, reducing equal-allocation estimator variance. It does not show that variance reduction alone caused the full-training trajectory gains, nor that arbitrary task partitions will transfer. The evidence remains conditional on the R2 candidate universe and nine dependent states.

All claims are engineering-only and conditional on the saved R2 states/candidate universe. Analytical variance matching empirical panels does not by itself establish a causal training benefit.
