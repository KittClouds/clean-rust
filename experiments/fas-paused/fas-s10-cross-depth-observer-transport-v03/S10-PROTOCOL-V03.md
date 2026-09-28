# FAS-S10 v03: Cross-Depth Observer Transport

## Question and scope

Measure whether a fixed linear observer fit at source layer `i` remains useful on a target representation from layer `j`, separately for `M=mean_full` and `F=final_position`. This is a descriptive replay over the sealed S09 cache and probe states. The S01 grouped split was already revealed, so the results are exploratory.

For each surface:

```text
T[i,j] = balanced_accuracy(labels_test, observer_i(representation_j))
row i    = source observer layer
column j = target representation layer
```

## Bound inputs

- S09 result tree root: `664af5b22f071b28d52a67d748e9f6f93ae3e67d587edec80b921dd529945880`.
- S09 feature cache root: `82f9eb6ba0b9c37e58c415b03ec1bc4be00032f73cc43e70b3987ac4108f7653`.
- S09 protocol root: `c1cf07e8b04ac1a3deff583e10257dcd3c5f3040e48bd4b05738cb3c4d4794b2`.
- S09 analysis seal file SHA-256: `44518d3901bf578a417d8897dda3485e9741262e80a676857d48297736cdcefc`.
- Layout: 16 layers × 2 surfaces, 106,496 rows × 2,048 FP32 values, little-endian.
- Labels and test rows: exact S09 S01-3 target split; 21,272 ordered test rows.
- Probes: all 32 sealed layer/surface scaler-plus-probe states; no fitting or changes.

The v02 parent-preflight receipt attests byte-level verification of the S09 protocol, result, analysis, and feature-cache trees. Before calculation, v03 verifies the receipt's exact SHA-256 and every contracted root/count field; it relies on that sealed-input verification rather than rereading tens of gigabytes. No S09 artifact was changed after the receipt. The runner must reproduce all 32 native diagonal probability arrays byte-for-byte and all diagonal metric objects exactly before sealing a successful result.

## Frozen transport calculation

For each surface and target layer, materialize the ordered S09 test rows exactly once as one contiguous FP32 array. Record its shape, row order, and byte SHA-256. Reuse those same immutable feature bytes for all 16 source observers, applying each source observer's own frozen scaler and probe.

Each prediction uses the S09 arithmetic order: FP32 feature, scaler, weights, and bias; cast scaler arrays to FP32; subtract mean then divide by scale; FP32 logits and softmax; batches of 16,384 rows. Deterministic CUDA algorithms are enabled and TF32 is disabled. Materialization changes only the read plan; it creates no new representation or feature extraction.

Report every cell's balanced accuracy, accuracy, class support, per-class recall, confusion matrix, and ordered predicted-class SHA-256. Retain the full 16×16 BA, accuracy, and prediction-hash tables for M and F; diagonal native scores; forward/backward transport by layer distance; adjacent bidirectional transport; and observer-retention ratio `T[i,j] / T[j,j]` (null when the denominator is zero).

Compare adjacent-layer rank-2 native decision planes per surface using the frozen S09 effective-geometry method. Report principal angles and normalized squared-cosine overlap. These compare observer normals in shared indexed residual coordinates; they do not identify circuits or semantic features.

## Preserved v02 attempt

S10 v02 completed all parent-tree verification and verified the 32-matrix feature cache. Its transport loop was interrupted after sustained no-output execution because it repeatedly gathered the same mapped test rows for each of 16 observers. The v02 attempt status is recorded at `D:/codex-runs/fas-s10-cross-depth-observer-transport-v02/execution-attempt-status-v02.json`, SHA-256 `a03941b5ebb2d6355dd557c2150ea4dea800f1925630f47f526c59b9be5dac69`. It contains no transport metrics, predictions, or result seal and is not a scientific result.

## Prohibitions and interpretation limits

No model load, feature extraction, new representation view, probe fitting, FAS-00 access, significance test, threshold selection, layer selection, or adaptive mechanism. Cross-layer cells transport each source layer's complete sealed scaler-plus-probe without refitting. Weak transport does not establish information absence. No causal transformer mechanism is claimed.

## Terminal states

```text
S10_PARENT_TREES_VERIFIED       true/false
S10_DIAGONAL_REPRODUCTION       PASS/FAIL
S10_TRANSPORT_COMPLETE          true/false
S10_V03_RESULT_SEALED            true/false
S10_MODEL_CONTACT                false
S10_PROBE_FITTING                false
```
