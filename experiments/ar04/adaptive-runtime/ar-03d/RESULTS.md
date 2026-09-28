# AR-03D — Projected-order versus hash verifier control

Run: `run-20260921-ar03d1`
Status: integrity-valid, single frozen collection; descriptive runtime result, not a confirmed general effect.

## Frozen protocol and integrity

AR-03D compared only the verifier-panel partition: a fixed one-dimensional Rademacher projection of the 27D output-affine gradient, sorted into 12 balanced strata and refreshed every 100 decision slots, against one of eight prospectively assigned balanced hash partitions. Both drew V48 panels (four examples from each of 12 strata), reused the frozen P16 proposal stream, and ran the unchanged R2 K2 selector/pair schedule for 4,200 slots. No shadow result affected selection. The full-training shadow scored only the chosen program; no best-unselected-action oracle search was run.

The primary held-out endpoint used one independent 96-example evaluation set per training dataset. Those three sets were fixed across initializations and streams within the same dataset and were used only at the four declared readouts. Thus the 18 streams and nine dataset × initialization cells are paired/nested measurements, not 18 independent datasets.

Frozen source commit: `848295638fdfe302c9341882c073bfc594456782`

AR-03C parent: `f850f537e15e28024cca163b43ad6e4052b2b535`

Executable SHA-256: `7b6bd52de21a362e41524e38ecb24c5d46aad2124fd18ec24dc59dea380fcdc3`

Integrity validation passed:

- Receipt says `integrity_valid=true`; executable and frozen source hashes match the run receipt.
- All six generated dataset files match their recorded SHA-256 hashes; training, evaluation, initialization, development, and stream seed sets are disjoint.
- 36 trajectories, each with 4,200 decisions; 151,200 decision rows; 37,800 panels; 144 checkpoints; 774 partition-build records (756 projected refreshes plus 18 fixed hash partitions).
- All 18 paired streams have identical proposal fingerprints at all 1,050 evidence rounds (18,900 paired panel checks) and identical pair-schedule offsets at all 4,200 slots (75,600 paired decision checks).
- Every panel is V48 and quota-valid; there are exactly nine cell rows and one separate equal-cell aggregate row.
- Paired initial-state fingerprints and initial train/evaluation readouts match exactly. All ledger files parse and all reported utilities/losses are finite.
- The run used the clean, pushed source commit and its recorded optimized executable. Collection completed in 333.15 seconds.

## Primary outcome

Final held-out cross-entropy, equal-weighted over the nine dataset × initialization cell means:

| Arm | Held-out loss | Held-out accuracy |
| --- | ---: | ---: |
| Projected 1D ordering | 1.860914 | 54.63% |
| Hash placebo | 1.964142 | 52.26% |
| Paired difference (projected − hash) | **−0.103228** | **+2.37 percentage points** |

Projected ordering had lower final loss in 6/9 cells and 11/18 nested stream comparisons; accuracy was higher in 5/9 cells. The cell loss differences ranged from −0.454160 to +0.214130, with median −0.125035. The direction is favorable on average but heterogeneous. With only three datasets and three initializations in one crossed synthetic family, this run does not establish a reproducible runtime benefit or a broad generalization claim.

| Dataset | Initialization | Projected loss | Hash loss | Difference | Projected accuracy | Hash accuracy |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 0 | 2.942816 | 3.067850 | −0.125035 | 51.04% | 53.65% |
| 0 | 1 | 1.465843 | 1.378337 | +0.087506 | 54.69% | 57.81% |
| 0 | 2 | 1.847082 | 2.199590 | −0.352508 | 48.96% | 54.17% |
| 1 | 0 | 2.069951 | 1.855821 | +0.214130 | 50.00% | 48.44% |
| 1 | 1 | 1.600839 | 1.818747 | −0.217908 | 57.29% | 47.92% |
| 1 | 2 | 1.618508 | 1.791468 | −0.172960 | 47.92% | 52.08% |
| 2 | 0 | 1.643814 | 1.480905 | +0.162910 | 58.85% | 54.69% |
| 2 | 1 | 1.487738 | 1.941898 | −0.454159 | 63.54% | 55.21% |
| 2 | 2 | 2.071635 | 2.142664 | −0.071029 | 59.38% | 46.35% |

Equal-cell held-out loss trajectories were:

| Slot | Train loss P/H | Held-out loss P/H | Loss difference | Held-out accuracy P/H |
| ---: | ---: | ---: | ---: | ---: |
| 0 | 1.121746 / 1.121746 | 1.097100 / 1.097100 | 0.000000 | 38.31% / 38.31% |
| 600 | 0.863475 / 0.891941 | 1.132057 / 1.117016 | +0.015041 | 43.98% / 41.09% |
| 2,400 | 0.502134 / 0.527456 | 1.405516 / 1.474302 | −0.068786 | 52.20% / 48.84% |
| 4,200 | 0.295996 / 0.309938 | 1.860914 / 1.964142 | −0.103228 | 54.63% / 52.26% |

Both arms reduced mean training loss from 1.121746 to 0.295996 (projected) and 0.309938 (hash), while held-out loss rose substantially over training. Final held-out accuracy was modest. The primary loss difference should therefore be interpreted in this small synthetic setup, not as evidence of generally improved learning or generalization.

## Decision and cost diagnostics

Every trajectory committed on all 4,200 slots; there were no no-op slots. Under the outcome-blind full-training observer, the mean fraction of selected programs with non-positive full-training utility was 32.61% for projected ordering and 33.59% for hash. Mean cumulative harmful selected utility relative to no-op was 0.5885 versus 0.6468, respectively; mean cumulative beneficial selected utility was 1.4142 versus 1.4586. These are selected-program diagnostics, not regret against an uncomputed oracle winner.

The mean number of verifier programs actually evaluated per decision was 340.532 (projected) and 340.719 (hash), with per-slot range 335–341. The small difference is recorded because bounds and divergent states can change legal candidate counts; the protocol matched evidence size and policy budget, not an assumed identical number of legal evaluations.

| Mean component per trajectory | Projected 1D | Hash placebo |
| --- | ---: | ---: |
| Feature acquisition | 0.324 ms | 0 |
| Partition/order construction | 0.359 ms | 0.0045 ms |
| Panel construction | 1.937 ms | 1.926 ms |
| Selector/policy time | 9.207 s | 9.170 s |
| Outcome-blind shadow time | 49.75 ms | 49.58 ms |
| Measured trajectory wall time | 9.262 s | 9.223 s |

The projected feature plus partition work averaged about 0.683 ms per roughly 9.26-second trajectory; measured wall time was about 0.039 seconds (0.42%) higher. These component timings are instrumentation from this run, not a controlled microbenchmark. The run shows the frozen projected construction is inexpensive in this harness, but does not establish a stable speed advantage or production cost profile.

## Interpretation and disposition

AR-03C's diagnostic estimator advantage translated into a favorable but mixed closed-loop mean on this one frozen run. The endpoint pattern is consistent with a runtime benefit, but 6/9 cell wins, 11/18 nested stream wins, wide cell heterogeneity, and the small reused evaluation sets prevent a robust-benefit claim. AR-H49 remains a diagnostic, bounded finding; AR-03D does not yet promote it to a reliable controller benefit.

Strongest alternative explanation: ordinary finite-run variation and state divergence may account for the aggregate loss difference. The nine cells share only three training datasets and three initializations; two streams per cell are nested and are not independent replications. The small evaluation sets are shared within dataset. Also, the full-training shadow is one-step and cannot say whether the sampled panel chose the best available action.

No post-result tuning or follow-up training run was performed. The next decision should be review/authorization of an independent, prospectively frozen replication or closure of the closed-loop claim. The AR-03C raw receipts were not edited, and CF-01 remains untouched.
