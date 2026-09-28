# AR-03D-R1 — Independent 5×5 projected-order replication

Run: `run-20260921-ar03dr1-5x5`
Disposition: integrity-valid; the predeclared runtime-benefit replication reversed direction. Close the AR-03D closed-loop benefit claim; retain H49 as diagnostic-only.

## Frozen protocol and integrity

R1 changed only the dataset/init/stream seeds and crossed-factor cardinality from AR-03D. It retained two paired evidence streams per cell, the 27D output-gradient projection, 12×8 balanced partition, fixed K=100 refresh, V48, P16, K2 selector and pair schedule, 4,200 slots, full-training chosen-action shadow, and the same measurement-only held-out-loss endpoint.

Frozen source commit: `3e42df7830a65092f4e8b104db566da6328642d1`
AR-03D parent: `2df36ced17a9d347f49fd64dc08631217c55227a`
Executable SHA-256: `52d488e2cdcfcfc2993477344985c32f66a3616e0fd0699208389abf6644faae`

All integrity gates passed:

- Receipt reports `integrity_valid=true`; source and optimized executable hashes match the frozen receipt.
- Ten generated data files (five training plus five held-out) match their recorded SHA-256 hashes. All 115 R1 seed values are unique and the runtime guard rejects the AR-03D seed namespaces.
- Completed 25 cells, 50 unique paired streams, 100 trajectories, 420,000 decision records, 105,000 V48 panel records, 400 checkpoints, and 2,150 partition-build records (2,100 projected refreshes and 50 fixed hash partitions).
- All 52,500 paired evidence-round proposal fingerprints match; all 210,000 paired decision schedule offsets match; all 50 paired initial states match in parameter fingerprint and initial losses.
- Every panel is 48 examples and quota-valid; the hash-placebo IDs occur six or seven times each. The cell table has 25 rows, factor-marginal table 10 rows, and overall table one row; all ledgers parse.
- Collection completed in 967.92 seconds. The clean frozen-source preflight passed format, 14 tests, strict Clippy, and optimized release build.

The five held-out sets are one per training dataset and are shared across that dataset's five initialization cells and streams. They are measurement-only, but this means the 25 cells are crossed dataset × initialization outcomes, not 25 independent held-out datasets.

## Primary outcome

Primary difference is final held-out cross-entropy, projected minus hash; positive means projected ordering is worse.

| Arm | Equal-cell final held-out loss | Equal-cell accuracy |
| --- | ---: | ---: |
| Projected 1D | 1.854741 | 55.46% |
| Hash placebo | 1.774218 | 55.75% |
| Difference | **+0.080523** | **−0.29 percentage points** |

The projected arm is about 4.5% higher in terminal held-out loss. Hash has lower loss in 18/25 cells and 31/50 nested stream comparisons. Projected is lower in 7/25 cells and 19/50 nested streams. Cell differences have median +0.067581 and range −0.517444 to +0.430878. No inferential interval is reported; streams are nested and the five held-out datasets are shared within dataset.

Cell loss-difference matrix:

| Dataset \ Init | 0 | 1 | 2 | 3 | 4 | Dataset marginal |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | +0.423234 | −0.041088 | +0.234671 | +0.430878 | −0.033959 | +0.202747 |
| 1 | −0.203089 | +0.067581 | +0.234605 | −0.022342 | +0.050169 | +0.025385 |
| 2 | +0.196192 | +0.109517 | +0.048517 | −0.092973 | +0.072485 | +0.066748 |
| 3 | +0.171288 | +0.153614 | +0.063916 | −0.517444 | +0.019856 | −0.021754 |
| 4 | +0.174900 | +0.044683 | −0.181075 | +0.287388 | +0.321539 | +0.129487 |
| Initialization marginal | +0.152505 | +0.066862 | +0.080127 | +0.017101 | +0.086018 | **+0.080523 overall** |

Only one of five dataset marginals favors projected ordering; all five initialization marginals favor hash. That is the opposite of the D pattern, where the projected arm had a favorable mean. R1 therefore fails to replicate D’s closed-loop benefit and materially reverses its direction under the predeclared decision tree.

Equal-cell checkpoints:

| Slot | Train loss P / H | Held-out loss P / H | Difference | Held-out accuracy P / H |
| ---: | ---: | ---: | ---: | ---: |
| 0 | 1.115066 / 1.115066 | 1.108439 / 1.108439 | 0.000000 | 32.79% / 32.79% |
| 600 | 0.860842 / 0.881404 | 1.047750 / 1.042583 | +0.005167 | 47.56% / 46.75% |
| 2,400 | 0.447824 / 0.476851 | 1.353914 / 1.294457 | +0.059457 | 52.94% / 53.21% |
| 4,200 | 0.241105 / 0.248138 | 1.854741 / 1.774218 | +0.080523 | 55.46% / 55.75% |

Both arms lower train loss while held-out loss rises substantially. Projected ordering has slightly lower terminal train loss but worse held-out loss; it does not resolve the fixed runtime’s overtraining behavior.

## Secondary diagnostics and cost

All trajectories selected and committed at every slot; mean no-op count was zero in both arms. Outcome-blind full-training shadow summaries:

| Measure, trajectory mean | Projected 1D | Hash placebo |
| --- | ---: | ---: |
| Non-positive selected-program rate | 32.21% | 32.97% |
| Cumulative harmful selected utility relative to no-op | 0.558309 | 0.603958 |
| Cumulative beneficial selected utility | 1.432270 | 1.470886 |

These diagnostics mildly favor projected ordering on harmful outcomes, but it also accumulates less beneficial utility and does not change the primary conclusion. The shadow did not evaluate unselected actions, so these are not oracle regrets.

| Mean component per trajectory | Projected 1D | Hash placebo |
| --- | ---: | ---: |
| Feature acquisition | 0.336 ms | 0 |
| Partition/order construction | 0.413 ms | 0.005 ms |
| Selector/policy time | 9.618 s | 9.605 s |
| Measured wall time | 9.676 s | 9.662 s |

Projected feature plus partition construction remains below 1 ms per roughly 9.7-second trajectory in this harness. The small measured wall-time difference is not a controlled performance benchmark.

## Independent R1 disposition

AR-03D was favorable/inconclusive; R1’s independently analyzed primary result is unfavorable to projected ordering, with hash lower in most cells, in four of five dataset marginals, and in all five initialization marginals. This is a material reversal, not a weak replication of the D mean. Under the frozen decision rule:

- AR-H49 remains a bounded diagnostic estimator/response-geometry finding; this run does not invalidate the earlier estimator-level result.
- The AR-03D closed-loop runtime-benefit claim is **not replicated and is closed**. Do not promote projected ordering as a runtime improvement on this evidence.
- Do not pool D and R1 to recover a favorable aggregate, and do not tune, rematch, or launch another confirmation on this substrate under this claim.

The complete immutable output is alongside this report: dataset manifest and binaries, integrity receipt, trajectory/checkpoint/cell/factor summaries, and full decision, panel, and partition-build ledgers. AR-03D parent artifacts remain untouched; CF-01 remains untouched.
