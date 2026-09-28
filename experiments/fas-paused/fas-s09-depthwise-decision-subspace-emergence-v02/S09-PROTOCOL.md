# FAS-S09: Depthwise Decision-Subspace Emergence

Protocol revision 02 records a pre-model-contact path correction to the first sealed construction. Revision 01 and its unsealed partial preflight attempt remain preserved at their original paths. The scientific parents, extraction views, probe recipe, measurements, and fail-closed gates are unchanged.

## Question

Across the 16 transformer layers of the pinned frozen LFM, when do the exact-target linear observers for `mean_full` and final-position representations become accessible, and how do their rank-two decision subspaces separate across depth?

This is exploratory diagnostic work on the already-revealed S01 controlled split. It is not a new confirmatory evaluation and does not modify FAS-00, S01, S08, or S07.

## Frozen inputs

S09 is bound to the sealed S01-2 corpus, token/input row manifest, feature cache, S01-3 split/labels/probe recipe, and S08 S01 terminal geometry. The model is `LiquidAI/LFM2.5-1.2B-Base`, revision `7453bca97ca1e67754c4035a4b4c584e1c9dd725`. The existing pinned model asset is copied into the S09 run and its bytes are verified against the S01 asset manifest.

The S01 test split, grouped quartet assignment, training-row rules, and exact-target labels remain unchanged. All A/C/E/P siblings remain together. Results are descriptive because this split was already revealed in S01.

## Layer features

Use every transformer block output, layer indices 1 through 16. The Hugging Face hidden-state tuple index 0 is the embedding output and is excluded. For each event and each layer `l`, materialize exactly:

```text
M_l = mean of H_l over all model-visible token positions [0, sequence_length)
F_l = H_l at sequence_length - 1
```

The final layer must match the sealed S01-2 `V0_MEAN_FULL` and `V1_FINAL_POSITION` arrays byte-for-byte over every event before any probe is fitted. The final layer output exposed through the hidden-state tuple must equal `last_hidden_state`. A failure stops S09 before depth interpretation.

Extraction uses the exact S01 token IDs, one event per forward call, exact sequence length, no padding, no tokenizer call, frozen parameters loaded as FP32, FP32 output, CUDA device 0 on the NVIDIA GeForce RTX 3080, SDPA attention, TF32 disabled, and deterministic algorithms. Backbone parameter identity is hashed before and after extraction. A repeat extraction of the first 256 sealed input rows must reproduce all 32 layer/surface vectors byte-for-byte.

## Fixed readout

Fit one three-class exact-target multinomial linear logistic readout independently for each `(layer, surface)`, for 32 fits total. Copy the S01-3 `linear_core.py` implementation unchanged. Use its exact target fit rows, grouped split, training-only float64 population standardization, zero initialization, unregularized intercept, L2 coefficient `1e-4`, deterministic CUDA FP32 LBFGS settings (`max_iter=300`, `max_eval=375`, `tolerance_grad=1e-7`, `tolerance_change=1e-9`, `history_size=10`, strong-Wolfe line search), and class order. Do not tune or extend the solver.

Fit the layer-16 M and F readouts first. Before fitting any earlier layer, require exact equality with sealed S01-3 terminal probe states, scalers, probabilities, row ordering, and contracted metrics; require the derived M/F rank-two planes to match the sealed S08 terminal planes within the frozen subspace tolerance. Any failure stops the run.

## Measurements

For every layer and surface report accuracy, balanced accuracy, per-class recall, confusion matrix, log loss, Brier score, target-vs-best-rival margins, and all three class-pair margins on the full S01 test set and every sealed exact-target test condition.

At each layer, treat a readout as its full scaler-plus-probe pipeline. Score the four fixed cells: `M_l` with its native M pipeline, `F_l` with its native F pipeline, `M_l` with the F pipeline, and `F_l` with the M pipeline. Report paired predictions and metrics for native versus cross-surface transport. No new fit is used for a cross cell.

Derive effective raw-coordinate class normals as `weights / scaler_scale`; pairwise normals are class-normal differences. Compute rank, singular values, principal angles, and normalized squared-cosine overlap for `U_M,l` versus `U_F,l`, and compare each surface's plane at layer `l` with its sealed S08 layer-16 terminal plane. Use the S08 SVD tolerance rule. Intermediate rank loss is a measurement, not an extraction failure.

No threshold is introduced to label a categorical “emergence layer.” Show the complete depth curves. No significance tests, view selection, layer selection, adaptive stopping, or FAS-00 transfer are part of S09.

## Fail-closed gates and disposition

Before model load, verify and seal the protocol, source snapshot, every parent seal, corpus/cache identities, split metadata, probe artifacts, S08 plane artifact, pinned model asset identities, runtime, GPU, and storage floor. Before probe fitting, verify complete features, backbone identity, determinism, and terminal feature parity. Before fitting layers 1–15, verify terminal probe and S08 plane reproduction exactly as contracted.

Only a fully verified result receives `S09_RESULT_READY=true`. S09 does not authorize FAS-00 Phase 4, online adaptation, or any later FAS phase. Preserve failures and partial outputs under their versioned S09 run identity.
