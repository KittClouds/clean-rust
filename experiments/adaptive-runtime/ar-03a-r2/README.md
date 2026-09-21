# AR-03A-R2 — Objective-and-initialization portability

Status: frozen diagnostic-only crossed replication. It tests whether the raw current-state per-example gradient partition from R1 beats balanced hash partitions across new empirical objectives and new model initializations. Gradient partitions never control training or verifier sampling. No end-to-end optimizer comparison is part of this run.

## Frozen question

Does candidate-independent per-example gradient geometry predict held-out candidate-utility response homogeneity across a crossed `3 datasets × 3 initializations` design, with development/evaluation streams and action combinations held apart within each cell?

The replication unit is the dataset×initialization cell (9 cells). Two development and two evaluation evidence streams are nested in each cell; checkpoints 600, 2,400, and 4,200 are nested within streams. Panels and checkpoints are not independent replication units.

## Frozen substrate and runtime

- **Data family:** the R1 eight-dimensional interaction-defined synthetic classification generator, unchanged except for its seed. Each dataset contains 96 examples, three classes, heteroskedastic observation noise, and no validation split. Dataset seeds are `a303dada00000001`, `a303dada00000002`, and `a303dada00000003`.
- **Model:** fully connected `8-8-8-3` ReLU MLP, 171 parameters, bounds `[-2,2]`. Three independently seeded parameter initializations use iid normal draws with standard deviation `0.16`, frozen by seeds `a3031a1700000001`, `a3031a1700000002`, and `a3031a1700000003`. Each initialization seed is crossed with every dataset seed.
- **Action/runtime:** exact R1 K2 machinery: action values `{0, ±0.005, ±0.01, ±0.02}`, P16 singleton proposals, top-2×top-2 exact pair verification on independent V48 samples, four commits per evidence draw, deterministic rotating pair schedule, and immediate commit/replan. The action scale is `alpha=1` only. R1's development/evaluation action-split salt, hash-placebo construction, and balanced-k-means initialization seed are preserved.
- **Evidence streams:** 18 development and 18 evaluation seeds, each used in exactly one dataset×initialization cell. Within each cell, two streams per role are assigned consecutively in the frozen arrays below. All 42 dataset, initialization, and stream seeds are distinct.

| Role | Frozen seeds, in cell order (2 per cell) |
| --- | --- |
| Development | `a303de0000000001`–`a303de0000000012` |
| Evaluation | `a303ea0000000001`–`a303ea0000000012` |

The compact ranges above are consecutive hexadecimal seed identifiers, inclusive. The complete arrays are serialized in `report.json` after the run. Within each role, cell order is dataset 0/init 0–2, dataset 1/init 0–2, dataset 2/init 0–2.

## Held-out state/action design

- Replay the frozen K2 runtime separately for the four streams in each dataset×initialization cell. Capture the three post-commit checkpoints from every stream.
- At each checkpoint, construct the same K2 candidate universe as R1 from the next P16 proposal: legal top-2×top-2 programs for every pair block. Within each block, the fixed R1 rank-combination split assigns two programs to development actions and two to held-out evaluation actions. The split is identical across all cells and states.
- The development-response partition is fitted separately inside each cell using only the six development stream×checkpoint states and their development actions. It is then evaluated on that same cell's held-out evaluation streams and actions.
- The per-evaluation-state response comparator uses that evaluation state's held-out utility matrix and is diagnostic ceiling only. It does not influence training, partitions used by other states, or runtime decisions.
- Every partition has exactly 12 strata of 8 examples. Each of 64 paired panels samples 4 examples without replacement from each stratum and uses the correct equal population weight. Eight frozen hash-placebo partitions are evaluated on the same panels.
- The observable proxy set is intentionally limited to one method: the full raw 171D per-example gradient partition. Input-only, scalar-state, projected-gradient, action-aware-gradient, and learned proxies are excluded. A single `alpha=1` Taylor audit is retained as diagnostic telemetry; the action-scale sidecar is removed.

## Primary measures and aggregation

At alpha 1, report within-stratum candidate-utility variance, analytically predicted finite-population RMSE, observed panel RMSE, sign error, cross-block opportunity regret, selected-program regret, and false authorization. Also report the Taylor fit `u_a(x)` versus `-g_x·delta_a` as a secondary mechanism diagnostic.

Aggregation order is fixed:

1. Average the 64 panel replicates within state and method.
2. Average the three checkpoints within each evaluation stream.
3. Average the two evaluation streams within each dataset×initialization cell.
4. Report equal-cell overall means, plus separate equal-weight dataset and initialization marginal summaries.

Show each of the 9 cells and all stream-level summaries. Compare raw-gradient partitions against the mean of eight hash-placebo partitions. The development-response oracle and per-state response comparator are diagnostic references only. No arbitrary pass/fail threshold is introduced after seeing results.

## Frozen seeds

Dataset seeds:

```text
a303dada00000001
a303dada00000002
a303dada00000003
```

Initialization seeds:

```text
a3031a1700000001
a3031a1700000002
a3031a1700000003
```

Development stream seeds:

```text
a303de0000000001 a303de0000000002 a303de0000000003
a303de0000000004 a303de0000000005 a303de0000000006
a303de0000000007 a303de0000000008 a303de0000000009
a303de000000000a a303de000000000b a303de000000000c
a303de000000000d a303de000000000e a303de000000000f
a303de0000000010 a303de0000000011 a303de0000000012
```

Evaluation stream seeds:

```text
a303ea0000000001 a303ea0000000002 a303ea0000000003
a303ea0000000004 a303ea0000000005 a303ea0000000006
a303ea0000000007 a303ea0000000008 a303ea0000000009
a303ea000000000a a303ea000000000b a303ea000000000c
a303ea000000000d a303ea000000000e a303ea000000000f
a303ea0000000010 a303ea0000000011 a303ea0000000012
```

## Integrity and stop rules

- Run unit, protocol, action-split, schedule, gradient finite-difference, and deterministic-partition checks before data collection; run strict Clippy before freezing.
- Verify all 42 seeds are distinct and disjoint from previous AR-00 through AR-03A-R1 seed records. Preserve R1 source/artifacts unchanged.
- Verify all nine dataset×initialization cells, each with 6 development and 6 evaluation state snapshots; no cross-cell stream reuse.
- Require exact 12×8 quotas, two development plus two evaluation programs per eligible pair block, finite outputs, and parseable JSON/CSV. Keep dataset hashes and the ordered model-state hash in the report.
- The main comparison is raw gradient versus hash-placebo within each cell. Report dataset and initialization marginal patterns separately; do not treat the 54 evaluation snapshots, 36 streams, or panel repetitions as 54/36/2,304 independent dataset-level replications.
- If development-response partitions fail to transfer within cells, persistent response geometry is not supported under this crossed design. If the response comparator shows headroom but gradients do not consistently beat hash partitions across cells, raw-gradient portability is not supported. If gradients beat hash across most/all cells, H47 earns bounded multi-objective portability within this synthetic family only.
- No runtime use of gradient strata, AR-03B, end-to-end training comparison, feature search, action-aware metric, action-scale sweep, extra seed sweep, or new substrate is authorized by this run.

## Result

Pending the frozen diagnostic run. No outcome-dependent changes to seeds, proxy definitions, action split, or protocol are permitted.
