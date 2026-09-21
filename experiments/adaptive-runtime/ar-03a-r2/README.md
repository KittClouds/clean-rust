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

### Run identity and integrity

- Frozen protocol/source commit: `ef667f6c` (`exp(ar-03a-r2): freeze crossed portability protocol`). Release execution completed in `393.46 s`; outputs are in `artifacts/run-20260921-r2/`. No validation set was generated or read.
- Preflight: 11 Rust tests pass; strict Clippy (`-D warnings`), formatting check, and optimized release build pass. The 42 frozen dataset, initialization, and stream seeds are unique and do not collide with prior adaptive-runtime records.
- The run has 108 snapshots: 54 development and 54 evaluation. Every dataset×initialization×role cell has six snapshots from two streams, each at the three frozen checkpoints. The nine cells are the replication units; streams/checkpoints/panels remain nested.
- Output counts: 36,668 candidate rows (18,334 per action split), 57,888 partition assignments, 38,016 panel rows, 594 state/method metrics, and 54 alpha-1 Taylor records. All 9,167 candidate-block groups have exactly two development and two evaluation actions. All 603 partitions have exactly 12 strata of 8 examples. Output values are finite; report JSON parses. Dataset and ordered model-state hashes in `report.json` independently match the files.
- Dataset class counts are `31/35/30`, `27/32/37`, and `25/34/37`. Dataset SHA-256 values are `82249938c79f82d2d484780602244f424f3a5b4a831fca666a04229e32491b8c`, `005388d66f614e49a60f15c7ac19a00dd8b35fb0febbefdef93326fa766cd67f`, and `c5ee81741b5cfc7f20db776e42ef612885c28a0c0454bae5bb72c2b6dd2d33f8`.

### Held-out response geometry at alpha 1

Overall estimates first average checkpoints within stream, then the two evaluation streams within each dataset×initialization cell, and finally equally weight the nine cells. The eight hash-placebo partitions are averaged as the control.

| Partition | Within-stratum utility variance | Predicted RMSE | Observed panel RMSE | Sign error | Cross-block regret | Selected-program regret | False authorization |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Hash-placebo mean | `3.5320e-5` | `5.7705e-4` | `5.7748e-4` | 31.69% | `5.0415e-4` | `5.8861e-4` | 19.58% |
| **Current-state gradient (171D)** | **`2.7200e-5`** | **`4.9300e-4`** | **`4.9251e-4`** | **28.98%** | **`4.6377e-4`** | **`5.3377e-4`** | **16.38%** |
| Development-response oracle | `2.8970e-5` | `5.1353e-4` | `5.1358e-4` | 29.91% | `4.8132e-4` | `5.5209e-4` | 17.27% |
| Per-evaluation-state response comparator | `2.6705e-5` | `4.8848e-4` | `4.8955e-4` | 29.10% | `4.6699e-4` | `5.3608e-4` | 16.03% |

Against the hash-placebo mean, gradient partitions reduce overall within-stratum utility variance by 23.0%, predicted RMSE by 14.6%, and observed panel RMSE by 14.7%. Sign error falls by 2.71 percentage points, cross-block regret by 8.0%, selected-program regret by 9.3%, and false authorization by 3.20 points. The analytical finite-population RMSE closely matches panel RMSE (gradient: `4.9300e-4` predicted vs `4.9251e-4` observed; hash: `5.7705e-4` vs `5.7748e-4`).

The gradient proxy beats hash-placebo in **all 9 cells** on within-stratum variance, predicted and observed RMSE, sign error, cross-block regret, and selected-program regret; it lowers false authorization in 8 of 9. Observed-RMSE improvement ranges from 10.1% to 19.2% by cell. The per-cell reduction matrix is:

| Dataset seed index \ Initialization seed index | 0 | 1 | 2 |
| --- | ---: | ---: | ---: |
| 0 | 10.1% | 12.4% | 15.9% |
| 1 | 15.7% | 17.7% | 14.6% |
| 2 | 14.4% | 14.9% | 19.2% |

Equal-weight dataset-marginal RMSE reductions are 12.4%, 16.0%, and 16.0%; initialization-marginal reductions are 13.1%, 15.0%, and 16.5%. Gradient RMSE also wins in all 18 evaluation streams. The cell-fitted development-response oracle improves observed RMSE over hash-placebo in all 9 cells, showing held-out stream/action transfer within each cell; its partition is fit separately per cell and is not evidence of transfer between different datasets or initializations.

At alpha 1, Taylor `R²` averages `0.9887` across 54 nested evaluation snapshots (range `0.9506–0.9993`). This remains secondary evidence: it is compatible with the local linear response explanation but does not show that Taylor prediction mediates the entire gradient-partition benefit.

### Disposition and limits

**AR-H47 is supported descriptively across new datasets and initializations within this one synthetic generator/model family.** Raw current-state per-example gradients repeatedly organize held-out action responses into more utility-homogeneous strata than arbitrary balanced partitions, and the improvement is consistent across all nine crossed cells for the primary estimator/decision-quality metrics. This extends R1 beyond one empirical objective and one initialization lineage.

The strongest alternative explanation is scope, not a visible failed cell: all three datasets still come from the same eight-dimensional generator, all models use the same `8-8-8-3` ReLU architecture and small frozen action grammar, and the panel audit evaluates the same 96 examples that define each empirical objective. A per-evaluation-state gradient partition is recomputed using full per-example gradients over those 96 examples; its computation cost is not included in the sampling-error comparison and may overwhelm any eventual runtime savings. There are only nine dataset×initialization units. The nested streams/checkpoints and repeated panels must not be counted as additional dataset-level replications. This is not generalization to unseen datapoints, a real dataset, a different architecture, or an end-to-end optimizer result.

**Gate result:** the diagnostic portability criterion is met within the frozen synthetic family. This closes AR-03A-R2 and earns review of a separately specified efficiency/runtime experiment. It does not authorize AR-03B, runtime use of gradient strata, cheaper feature searches, action-aware metrics, or another substrate run. No such follow-on work was started.
