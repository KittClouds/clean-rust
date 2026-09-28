# FAS-S05: Crossed Representation × Readout Decomposition

## Question

The fixed linear observers for `mean_full` and `final_position` are both
complete pipelines: feature standardization plus their sealed linear weights
and biases. S05 replays each pipeline on both existing representation
surfaces, producing this 2×2 table:

| Cell | Representation | Readout pipeline |
|---|---|---|
| MM | `mean_full` | sealed `mean_full` scaler and probe |
| FM | `final_position` | sealed `mean_full` scaler and probe |
| MF | `mean_full` | sealed `final_position` scaler and probe |
| FF | `final_position` | sealed `final_position` scaler and probe |

For each scalar outcome `Y`, report the reference-anchored decomposition:

```text
representation_at_M_readout = Y(F,M) - Y(M,M)
readout_at_M_representation = Y(M,F) - Y(M,M)
interaction = Y(F,F) - Y(F,M) - Y(M,F) + Y(M,M)
diagonal_total = Y(F,F) - Y(M,M)
```

The first three terms sum to the diagonal total. These are descriptive
decompositions of fitted systems, not population causal effects.

## Frozen populations

### Original FAS-00 corpus

Use the deduplicated union of the sealed S02 held-out context-term-3 and
entity-term-7 prediction rows. The union contains 512 unique events; report
the full union, the 412-event context slice, and the 212-event entity slice.
An event in both slices appears once in the union and once in each applicable
slice. Bind row identity to event ID and Phase 1 JSONL row index. Read
`mean_full` from Phase 2A row `2 * row_index`; read S02 `final_position` from
row `row_index`. The target classes are fixed in order `safe`, `risky`,
`idle` (IDs 0, 1, 2).

The MM and FF cells must reproduce the sealed S02 predictions exactly on all
unique events and reproduce its exact context/entity supports and metrics
before S05 is accepted.

### S01 controlled corpus

Use only the 4,933 already-sealed S04 factorial-balanced held-out quartets
(19,732 events), with their sealed feature-row indices, test-row indices,
candidate order, and candidate-identity to semantic-state mapping. Report the
one frozen factorial test population. Do not add other S01 tracks or test
quartets.

The MM and FF cells must match the sealed S01-3 exact-target saved prediction
argmax for every selected event. Probe class slots are candidate positions;
reorder each cell's logits into semantic state-ID order using each event's
sealed candidate mapping. Preserve the invented state names `zavik`, `nurex`,
and `pavom`.

## Replay and measures

No model or tokenizer is loaded. No feature is extracted and no probe is fit,
updated, continued, or tuned. Use only the two sealed representation arrays
and two sealed scaler-plus-probe states for each corpus.

For FAS-00, preserve the fixed S02 float64 pipeline: cast stored FP32 feature
rows to FP64, apply the corresponding readout's stored FP64 mean and scale,
then calculate `x @ weights.T + bias` in FP64. For S01, preserve the sealed
S01-3 FP32 replay: cast scaler moments to FP32, standardize FP32 features,
then apply FP32 weights and bias. The readout state always travels with its
scaler.

For each cell and population, report accuracy, balanced accuracy, support and
recall by class, mean/median/p10/p90 of the three pairwise logit margins and
target-versus-best-rival margin. Report all six cell-pair event prediction
transition matrices and correctness transitions. For each scalar metric and
margin, report the four cell values and the reference-anchored decomposition
above. Record per-event cell logits, predictions, correctness, margins and
margin decomposition in the ledger.

No significance tests, confidence intervals, post-hoc subsets, alternate
scaling, or post-result interpretation thresholds are permitted.

## Interpretation limits

The two readouts were separately fitted, and their scalers are part of those
readouts. Crossed cells measure transport of one fixed complete pipeline onto
the other representation surface. Changes may reflect the representation,
readout, training distribution, or their interaction. A poor crossed cell is
reported as a transport outcome, not treated as a software failure if its
identity, finite-value, and replay checks pass.

The original and S01 populations use different tasks and fitted probes. Their
decompositions must remain separate and cannot be pooled. S05 does not revise
FAS-00 or authorize an SAE, adaptive mechanism, model contact, or later phase.
