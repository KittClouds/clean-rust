# F4-CALIBRATION-02 v0.2 — Canonical Encoder Promotion

**Status:** prospective qualification contract v0.2  
**Scope:** engineering calibration only; no measured REACH-03 execution  
**Parent evidence:** F4-SYMMETRY-03 `QREP1-IMPLFIX1`, qualification-only  
**Encoder:** frozen D arm from F4-SYMMETRY-03, unchanged

## 0. Version boundary

This version follows `F4-CALIBRATION-02-QPROMO1`, which stopped before fit 1 because the fit launcher rejected a pre-fit receipt field-name mismatch. A separate read-only audit also found an integrity-launch import-path omission; the correction addendum records this distinction. The stop receipt and its correction addendum (4bb1fb284fa1d666e5e71bb00c7247ec1ccd3b19cb06e7bb3e91c5739f6f4f8c) record zero fits, zero predictions, no analysis, and no held-out target reads. This version keeps the same encoder, scientific population rule, estimator settings, and calibration gates; it uses fresh ordinary task seeds and a corrected launcher under a new execution identity. The v0.1 identity remains preserved and non-promotable.

**Run identity:** `F4-CALIBRATION-02-QPROMO2`.

## 1. Question

Does the frozen D representation and estimator meet the existing learned-F4 calibration gate on fresh ordinary qualification task blocks?

This is a calibration promotion trial. It does not measure the native F0–F3b observability ladder, alter native learning, install a polarity controller, reopen PHENO, or promote a biological claim.

## 2. Authority and frozen sources

The controlling prior F4 calibration gate is `runs/qualification-v2/QUALIFICATION-TERMINAL-RECEIPT.json` (SHA-256 `29f073c42de3160a7cb60385747daa247c43892fa19da6d56a1883d6ee7fea18`). Its thresholds remain unchanged:

- pooled IPW-balanced error at most 0.10, equivalently pooled `Omega_hat >= 0.80`;
- each evaluable held-out block has `Omega_hat >= 0.70`, equivalently balanced error at most 0.15.

The encoder and D feature semantics are inherited without modification from F4-SYMMETRY-03 contract SHA-256 `7c49b8419896dca4418de3497ecd8566b2167d1c6bf24d7860d904d70f87afe0`. The frozen implementation sources are:

- model: `experiments/fly-reach-03/scripts/f4_symmetry_01_model.py`, SHA-256 `92e260bd0057115867bf69b343d8193bab141035f3338af4586c5e0af61c47f8`;
- feature and normalization helpers: `experiments/fly-reach-03/f4-symmetry-03/scripts/common.py`, SHA-256 `27024a001f2c89f520b5230bf3796ee8691e499f29ce73c71597ad7c303debf5`;
- D feature construction: `experiments/fly-reach-03/f4-symmetry-03/scripts/prepare_fit.py`, SHA-256 `9da88d9a2e147cad551e8e4e2c8b11ba460b435f5743f57527fbf46d7eb09497`;
- fit recipe: `experiments/fly-reach-03/f4-symmetry-03/scripts/fit.py`, SHA-256 `0c8a84f2418c8b2d7fa222675860771e7e4e64b871ad333ec0fb5e3e65af5026`.

Any calibration-specific wrapper may change only the frozen eight-block/two-arm orchestration into twelve blocks and D-only fitting. D feature values, training procedure, normalization semantics, model architecture, initialization rule by ascending fold index, optimizer, epochs, batch size, and order must remain identical. Any other change stops this identity.

## 3. Fresh ordinary task bank

Generate exactly twelve fresh task blocks with IDs and task/simulator seeds `305012` through `305023`. Use the existing deterministic task schedule procedure: four cues, 8,192 trials per block, twelve delay steps, two positive and two negative cue labels, and schedule seed `block_id XOR 0x545241494E`.

Use all nine frozen substrates, both sides, and the existing fixed 64-coordinate-per-cell manifest. No incidence-pattern screen, pattern balancing, task difficulty selection, or outcome-conditioned block selection is permitted. Generate and freeze all twelve blocks before native collection. Retain every generated block, including blocks later found to have zero or one target class in the common U* population. Do not replace blocks or rows.

## 4. Collection and fit matrix

Collect native-only trajectories for the complete `12 blocks × 9 substrates × 2 sides` panel. Use the existing U* rule and inclusion probabilities. Create one D fit per held-out block, for twelve leave-one-block-out fits. Each fit trains on the eligible rows from the other eleven blocks and predicts only its held-out block. No C, A, or B fit is part of this trial.

Use D exactly as frozen: the 66D admissible base plus the same canonically ordered 24D relational sidecar, 90D float32 model input, fold-training-only normalization, architecture 90→128→64→1, 200 epochs, batch size 2,048, Adam at 0.001 with the frozen beta/epsilon settings, and contiguous global row order without shuffling. Preserve identical source code and initialization mapping except for the twelve-fold list.

Predictions must be written and hashed for all twelve held-out blocks before scoring truth is opened. An independent integrity pass must verify the frozen 12-row fit grid, paired row identity and training semantics, finite predictions, exact prediction coverage, and no missing/duplicate cells before analysis.

## 5. Evaluable-block support rule

A held-out block is **evaluable for balanced error** only when its U* rows include at least one `Y=+1` and one `Y=-1`. A zero-row or one-class block remains in the frozen twelve-block panel; its blockwise balanced error is `undefined`, it is not assigned a fabricated score, and it counts as non-evaluable for this support gate. Its available rows still contribute to pooled out-of-fold class-conditional error.

At least **10 of 12** held-out blocks must be evaluable. This is the prospectively frozen 80% support rule rounded up to an integer block count. If fewer than ten qualify, the calibration disposition is `NOT_EVALUABLE_SUPPORT`; do not replace blocks, alter the population, or relax the gate.

For every evaluable block, require IPW-balanced error ≤0.15 (`Omega_hat ≥0.70`). Every evaluable block must pass; do not average away a failing evaluable fold. The pooled out-of-fold population must contain both target classes and meet IPW-balanced error ≤0.10 (`Omega_hat ≥0.80`). Pooled error is computed over all available held-out U* rows from the twelve frozen blocks, including rows from a one-class block. Empty blocks contribute no rows.

Define `Omega_hat = max(0, 1 - 2 * epsilon_balanced)` using the frozen inverse-inclusion-probability weights and equal class weighting. Report the unclipped value as well. No denominator floor or imputation is permitted for empty or one-class block scores.

The calibration passes only if all three conditions hold: at least 10/12 blocks are evaluable, every evaluable block meets the 0.70 Omega floor, and pooled error/Omega meet the original 0.10/0.80 gate. Otherwise preserve the failing qualification receipt and close this frozen D candidate without post-result tuning.

## 6. Decision boundary

A pass establishes only that the frozen D estimator clears its practical learned-F4 calibration gate on this fresh qualification population. It makes a separately sealed measured REACH-03 preparation eligible. It does not itself create or execute the measured namespace. Measured native-only collection still requires its own frozen manifest and authorization.

A fail or support failure closes this D calibration candidate. Do not change features, task difficulty, estimator capacity, thresholds, or support rules under this identity.

No biological promotion, mechanism claim, controller, or PHENO work is authorized by this contract.
