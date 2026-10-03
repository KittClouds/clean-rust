# FAS-S10-v02: Cross-Depth Observer Transport

## Question and scope

S10 measures whether a fixed linear observer fit at source layer `i` remains useful when applied to a target representation from layer `j`. It is a descriptive replay over the sealed S09 feature cache and probe states. The S01 grouped split was already revealed, so the results are exploratory.

For each surface (`M=mean_full`, `F=final_position`), the primary transport matrix is

```text
T[i,j] = balanced_accuracy(labels_test, observer_i(representation_j))
row i    = observer source layer
column j = representation target layer
```

## Bound inputs

- S09 result tree root: `664af5b22f071b28d52a67d748e9f6f93ae3e67d587edec80b921dd529945880`.
- S09 feature cache root: `82f9eb6ba0b9c37e58c415b03ec1bc4be00032f73cc43e70b3987ac4108f7653`.
- Feature layout: 16 layers × 2 surfaces, 106,496 rows × 2,048 FP32 values, little-endian.
- Frozen probe states: the 32 sealed S09 layer/surface states. No refitting or parameter mutation.
- Labels and test rows: the sealed S01-3 event metadata and exact-target split already bound by S09.

The runner must verify both parent hash trees before analysis. It must also reproduce every S09 native diagonal probability array byte-for-byte and every diagonal metric object exactly before sealing a successful S10 result.

## Frozen calculation

For each surface, target layer, and source observer, apply the source state’s stored training-only scaler and probe to the target layer’s test rows. Preserve S09 runtime semantics: scaler arrays are converted to FP32 for prediction, features and probe arrays are FP32, probability predictions use batches of 16,384 rows, TF32 is disabled, deterministic CUDA algorithms are enabled, and no probe is fit.

Report for every cell: balanced accuracy, accuracy, class support, per-class recall, confusion matrix, and a SHA-256 of ordered predicted class IDs. Retain the full 16×16 BA, accuracy, and prediction-hash tables for M and F.

Report diagonal native performance; forward and backward transport by layer distance; both directions for every adjacent pair; and observer-retention ratio `T[i,j] / T[j,j]`. If the target layer’s native BA is zero, retention is undefined and serialized as null.

For each surface, compare the rank-2 native observer decision planes at adjacent layers using the frozen S09 effective-geometry semantics. Report both principal angles and normalized squared-cosine overlap. These are observer-space comparisons in shared indexed residual coordinates, not circuit or semantic-feature claims.

## Prohibitions and interpretation limits

No model load, feature extraction, new representation view, probe fitting, FAS-00 access, significance test, threshold, layer selection, or adaptive mechanism. Cross-layer transport uses each source layer’s complete scaler-plus-probe pipeline without refitting. Weak transport is not evidence that task information is absent. S10 does not identify circuits or causal transformer mechanisms.

## Terminal states

```text
S10_PARENT_TREES_VERIFIED      true/false
S10_DIAGONAL_REPRODUCTION      PASS/FAIL
S10_TRANSPORT_COMPLETE         true/false
S10_V02_RESULT_SEALED              true/false
S10_MODEL_CONTACT              false
S10_PROBE_FITTING              false
```
