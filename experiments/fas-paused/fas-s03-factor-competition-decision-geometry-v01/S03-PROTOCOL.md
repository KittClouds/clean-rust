# FAS-S03 Protocol v01

## Objective

Describe the linear decision geometry associated with the S02 context-transfer improvement and entity-transfer decline. Use only the existing sealed `mean_full` and `final_position` caches, their already-fitted S02 probe states, and original FAS-00 Phase 1 metadata.

The analysis asks how pre-update logits and margins differ across the two complete readout pipelines on the same original test events. It does not fit or update a model.

## Frozen scope

- Inputs: the S02-2 sealed result tree; the S02-1 final-position cache; the FAS-00 Phase 2A `FULL` cache; the Phase 1 v03 event corpus; the two probe NPZ files; the successful S02 receipts and predictions.
- Event set: unique union of the prospectively defined test context-term-3 and test entity-term-7 slices. Retain both slice-membership flags. Emit one ledger row per unique event.
- Views: existing `mean_full` and existing `final_position` only.
- Probes: existing Phase 3 `HELDOUT_TERM_EXACT_TARGET` mean probe and S02 final-position probe only. Read weights, biases, training means, and scales; never fit or mutate them.
- Classes: `[safe, risky, idle]`, indices `[0,1,2]`.
- No LFM loading, feature extraction, probe fitting, significance testing, confidence intervals, threshold changes, rescue analyses, or adaptive mechanisms.

## Definitions

For each event and view, let `z = [z_safe,z_risky,z_idle]` be the exact pre-softmax linear logits computed from the sealed FP32 feature row converted to FP64 and transformed with that probe's sealed training mean and scale.

Canonical class-boundary margins are `z_a - z_b` for ordered pairs `(safe,risky)`, `(safe,idle)`, `(risky,idle)`. For true class `y`, retain both directed true-versus-rival margins `z_y-z_r` for each `r != y`; the target margin is their minimum, equivalently `z_y-max(z_r:r!=y)`. The top-two margin is the largest logit minus the second-largest logit. Prediction is NumPy argmax with the lowest class index winning a tie.

For every event metric, the paired delta is `final_position - mean_full`. This is a comparison of the two complete fitted readout pipelines. Since the two probe states and standardizers were fitted separately, a delta is not an isolated representation-only causal effect.

For distributions, report `n`, mean, median, p10, p90, minimum, maximum, and positive/zero/negative counts where signed. Quantiles use NumPy `method="linear"`. No inferential statistics are computed.

## Frozen summaries

1. Event ledger: metadata, both slice flags, both views' three logits, three canonical pair margins, two true-versus-rival margins, target margin, top-two margin, argmax, correctness, and all paired deltas.
2. Per-slice summary: support, accuracy, balanced accuracy, class recall, paired correctness transitions, target-margin sign transitions, and distributions of class logits, target margins, pair margins, top-two margins, and their paired deltas.
3. Conditioned margin tables: separately by slice and target class, grouped by (a) context term, (b) entity term, (c) world seed, (d) observation answer, (e) context term × entity term, and (f) world family × task structure × feedback condition. Include counts and the same frozen descriptive distributions.
4. Membership overlap: counts for neither/context-only/entity-only/both slice membership; paired correctness transitions and target-margin delta sign counts per membership cell; event IDs in the intersection with each paired correctness transition.
5. Linear decision normals: for each canonical class pair and view, report the standardized-space and original-hidden-coordinate effective coefficient norms. Report cosine between views for each corresponding class-boundary normal and effective intercepts. These are coordinate descriptions, not semantic axes or causal factor effects.

Conditioned target-versus-rival margins indicate whether a view's fitted decision surface favors the true class within a subgroup. Context/entity subgroup variation is descriptive only: the original test corpus is not a randomized counterfactual intervention.

## Integrity and fail-closed gates

Before computing logits, verify all parent roots and artifact hashes, corpus row identity, full feature-cache tensor and manifest hashes, feature row bindings, probe artifact hashes/shapes/finiteness, S02 result-tree seal and status, and S02 prediction event/label/slice identities. Recompute both argmax predictions and require exact row-wise parity with the sealed S02 prediction files. Require contracted event counts, class order, and score reproduction metrics.

Any mismatch stops execution without an analysis result seal. Do not edit any parent artifact to recover a mismatch.

## Terminal disposition

On success, seal the complete S03 output tree and report:

```text
S03_PARENT_INTEGRITY_PASS = true
S03_S02_PREDICTION_PARITY = true
S03_DECISION_GEOMETRY_READY = true
S03_MODEL_CONTACT = false
S03_PROBE_FITTING = false
S03_SIGNIFICANCE_TESTING = false
FAS00_SENSOR_PASS = false
FAS00_PHASE4_AUTHORIZED = false
S04_OR_COMPOSITIONAL_INTERVENTION_AUTHORIZED = false
```

No scientific promotion follows automatically from a successful descriptive analysis.
