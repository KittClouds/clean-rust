# Baseline Ladder v1

## Purpose

`phoenix-baseline-ladder/v1` establishes the minimum evidence a learned graph model must beat. Every family consumes identical observed proposal rows, one certified feature schema, chronological splits, normalization certificates, and BLAKE3-derived seeds.

## Families

1. **Train-prior heuristic** uses Laplace-smoothed positive prevalence from training labels. It proves whether features add value beyond class balance.
2. **FTRL logistic** is a sparse-friendly online linear baseline with proximal L1/L2 regularization. Its 16-feature dot product uses two `f32x8` SIMD lanes.
3. **MLP-16** is a deterministic one-hidden-layer ReLU network with 16 hidden units, SIMD forward passes, shuffled SGD, and L2 regularization.

The ladder intentionally stops before R-GCN, HGT, and hypergraph networks. Those models are unjustified until they beat these cheaper baselines under the same protocol.

## Selection and test lock

Each family trains once per certified seed. The report exposes train and validation metrics for every run.

Family selection uses:

1. highest mean validation average precision;
2. lowest mean validation Brier score as the tie-break.

Only the selected family receives held-out test metrics. Losing-family test metrics remain absent, preventing test-set shopping. A split must contain at least one observed positive and one observed negative or execution fails closed.

## Metrics

- **Average precision** is the primary imbalanced-class ranking metric.
- **ROC-AUC** is secondary and omitted when a class is absent.
- **Log loss** measures probabilistic sharpness and punishes confident errors.
- **Brier score** measures squared probability error.
- **Expected calibration error** uses the protocol's certified fixed bin count.

Probabilities are clipped only inside log-loss calculation. Report identities are BLAKE3-addressed over the complete deterministic result.

## Promotion rule

An R-GCN, HGT, or hypergraph model may enter the ladder only after its features are certified as derived from training-visible topology. It must improve validation average precision without materially worsening Brier score, repeat across certified seeds, and report only one locked-test evaluation after selection.
