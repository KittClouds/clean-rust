# AR-01A — Stochastic Verification on a 3-Class Spiral

This is the first post-graduation test of the frozen AR-00 K2 primitive under minibatch evidence. It is engineering-only and does not feed evidence back into Drosophila Heresy.

## Frozen protocol

- 2-8-8-3 ReLU MLP, 123 parameters.
- Deterministic 3-class spiral: 96 balanced training samples and 48 balanced validation samples from the same distribution with independent deterministic jitter.
- Minibatch size 16, 3,000 minibatch steps, three frozen seeds.
- Fixed action grammar: `{0, ±0.02, ±0.01, ±0.005}` and bounds `[-2, 2]`.
- Deterministic round-robin pair schedule; 7,503 possible pairs, with pair coverage reported explicitly.
- A0 AdamW; A1 bounded sign descent; A2 K2 same-batch verification; A3 K5 same-batch verification; A4 K2 with independent proposal and verification batches.
- Every 50 steps, the selected program is compared against a full-training-set 7x7 pair reference. Audits classify shortlist misses, verification noise, and scheduler misorders.

## Valid result

| Arm | Mean train loss | Mean validation loss | Mean validation accuracy | Mean exact compounds | Audit failures total |
| --- | ---: | ---: | ---: | ---: | ---: |
| A0 AdamW | 0.000886 | 0.003731 | 100.0% | 0 | 0 |
| A1 sign | 0.259625 | 0.336934 | 95.1% | 0 | 0 |
| A2 K2 same-batch | 0.743351 | 0.766573 | 55.6% | 735,000 | 187 |
| A3 K5 same-batch | 0.736011 | 0.760026 | 56.2% | 4,578,000 | 185 |
| A4 K2 independent verification | 0.611472 | 0.639044 | 63.2% | 735,000 | 202 |

Independent verification improves K2 from 55.6% to 63.2% mean validation accuracy, but does not approach the sign control or AdamW. K5 does not rescue same-batch verification despite its much larger exact-search budget.

The audit shows that all three stochastic failure classes occur. Across the nine runtime runs, there were 249 shortlist misses, 325 verification-noise events, and 162 scheduler-misorder events. This is a direct contrast with AR-00, where audited failures were shortlist-only.

## Interpretation

AR-H19 is not supported in this configuration: minibatch-local exact verification is not reliable enough to preserve the AR-00 optimization regime.

AR-H20 receives bounded support: independent verification improves the outcome, but not enough to make K2 competitive.

AR-H21 is weakened: K2 shortlist recall from deterministic full-objective AR-00 does not survive noisy minibatch proposals/verification.

The strongest alternative explanation is that this runtime needs more than pairwise verification under stochastic training: the one-program-per-round schedule, fixed action scale, and small batch may all be limiting. Those are not disentangled here; no tuning campaign is promoted from this result.

## Rejected preliminary runs

- The first run was rejected because validation contained only one class due to class-blocked storage.
- The second was rejected because validation used a different radial/angle segment, turning the task into extrapolation rather than held-out estimation.

The final artifacts use balanced same-distribution train/validation strata and supersede both preliminary runs.

## Artifacts

- `artifacts/ar-01a-report.json`
- `artifacts/ar-01a-runs.csv`
- `artifacts/ar-01a-curves.csv`
- `artifacts/spiral-dataset.bin`

Release tests, smoke tests, clippy, execution, and benchmarks passed with the requested D:-target build validation.
