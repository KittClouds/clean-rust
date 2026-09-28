# FAS-S06: Representation × Scaler × Probe Compatibility Cube

## Question

Determine whether the sealed `mean_full`/`final_position` readout compatibility
effect is primarily associated with scaler centering, scaler scale, probe
orientation, or their interactions. This is a fixed replay of sealed states.

## Authority and scope

Use only the sealed S05 v07 population and replay artifacts, and the exact
feature and scaler-plus-probe artifacts bound by S05 from FAS-00, S01, and S02.
Do not load LFM or a tokenizer. Do not extract features, fit or alter probes,
continue optimizers, tune, run significance tests, or train an SAE. Preserve
FAS-00's failed sensor disposition and all later-phase authorization limits.

## Fixed populations

1. Original FAS-00/S02: S05's 512-event deduplicated union, reporting its 512
   union, 412 context-term-3, and 212 entity-term-7 slices.
2. S01 controlled: S05's 4,933 sealed factorial-balanced quartets and 19,732
   events.

No events may be added, dropped, reordered for selection, or relabeled. S06
must reproduce the S05 diagonal cell predictions on both populations before
accepting any crossed output.

## Replay cube

Each fitted readout `j` is split into center `mu_j`, diagonal scale `sigma_j`,
weight matrix `W_j`, and bias `b_j`. For representation `r`, center source
`c`, scale source `d`, and probe source `k`, replay:

```text
z = (h_r - mu_c) / sigma_d
logits = W_k z + b_k
```

Run all 16 combinations `r,c,d,k ∈ {M,F}`. The eight `c=d` cells are the
contracted representation × bundled-scaler × probe cube. The eight `c!=d`
cells prospectively separate center and scale transport. The exact requested
controls are included: `(mu_F,sigma_M)` is center-only transport and
`(mu_M,sigma_F)` is scale-only transport. On each representation, score these
controls with both sealed probes; also report comparisons that hold the
representation's native probe fixed.

Use FAS-00 FP64 arithmetic and S01 FP32 standardization/matmul exactly as the
sealed parents prescribe. Convert only recorded margins and summaries to
FP64. For S01, predictions and metrics use per-event semantic-state ordering;
effective weight geometry remains in the probe's fixed candidate-slot
coordinate order because candidate ordering varies by event.

## Analytic affine geometry

For each scaler/probe combination, compute in FP64 from the sealed parameter
values:

```text
N[d,k] = W[k] / sigma[d]
c[c,d,k] = b[k] - N[d,k] @ mu[c]
logits(h) = N[d,k] @ h + c[c,d,k]
```

Report class-normal norms, pairwise decision-normal norms, pairwise cosine and
angle against the matched native cell for that representation, intercepts
and intercept displacement, plus observed class-logit means and variances.
The affine geometry is descriptive; cell scoring uses the prescribed direct
standardize-then-probe replay.

## Contracted outputs

For every cell, population, and declared slice, report accuracy, balanced
accuracy, per-class support/recall, target-row confusion matrix, distribution
summaries for the three pairwise margins and target-vs-best-rival margin, and
class-logit means/variances overall and conditioned on target class. Record
all cell-pair prediction and correctness transitions. Report fixed paired
comparisons for probe-only, bundled-scaler, center-only, scale-only, and full
foreign-pipeline transport. Do not select a winning cell.

All predictions, logits, margins, affine geometry, summaries, and receipts are
sealed before interpretation. No significance tests, confidence intervals,
alternate metric, or post-result subset is allowed.

## Gates and dispositions

Fail closed on any parent hash/root mismatch, population identity/count
mismatch, invalid scaler/probe dimension, non-finite result, or diagonal
prediction mismatch. On success:

```text
S06_PARENT_BINDING_PASS = true
S06_EIGHT_CELL_CUBE_COMPLETE = true
S06_CENTER_SCALE_CONTROLS_COMPLETE = true
S06_RESULT_READY = true
FAS00_SENSOR_PASS = false
FAS00_PHASE4_AUTHORIZED = false
SAE_ANALYSIS_AUTHORIZED = false
```

S06 makes no causal claim beyond descriptive fixed-state compatibility on the
two bound populations. Stop after the result tree is independently verified.
