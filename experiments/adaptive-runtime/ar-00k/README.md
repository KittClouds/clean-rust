# AR-00K — Minimal Exact Beam

Engineering-only continuation of AR-00J. This experiment keeps width 2 and the deterministic broad pair-coverage schedule fixed, then varies only the exact Cartesian verification beam.

## Frozen protocol

- XOR MLP and initialization from `ar-00`.
- Four memory-mapped XOR samples.
- Three frozen schedule seeds.
- 3,000 training epochs.
- 11 primitive actions per coordinate, unchanged bounds and commit semantics.
- K0 evaluates all `11 x 11 = 121` pair programs.
- K1–K5 evaluate singleton proposals, retain the top `k` actions per side, and exactly evaluate the `k x k` Cartesian beam.
- The audit replays each arm on its own trajectory at epochs `0, 10, 50, 100, 250, 500, 1000, 2000` while evaluating the exhaustive width-2 oracle in shadow.

## Integrity gates

`cargo test --release`, `cargo clippy --release --all-targets -- -D warnings`, `cargo run --release`, and `cargo bench` passed. The smoke test covers all six arms and the audit cardinality.

## Three-seed result summary

| Arm | Mean final loss | Mean exact compounds | Mean proposal evals | Audit shortlist recall | Audit cross-block order |
| --- | ---: | ---: | ---: | ---: | ---: |
| K0 exhaustive | 0.01358598 | 3,928,144 | 45,577 | 1.0000 | 1.0000 |
| K1 1x1 | 0.30281617 | 27,328 | 639,280 | 0.9271 | 0.9449 |
| K2 2x2 | 0.01724851 | 126,731 | 741,627 | 0.9792 | 0.9762 |
| K3 3x3 | 0.01586274 | 287,568 | 747,952 | 0.9688 | 0.9732 |
| K4 4x4 | 0.01510721 | 511,957 | 748,979 | 0.9896 | 0.9970 |
| K5 5x5 | 0.01468280 | 813,400 | 761,644 | 0.9844 | 0.9955 |

All arms reached 100% XOR accuracy. K2 is the first compact beam in the low-loss basin and uses about 3.2% of K0's exact compound evaluations. K5 is closest to K0 on mean loss among the beams, but spends about 20.7% of K0's exact compound evaluations. The three-seed spread remains material, especially for K1 and K2.

## Failure split

Across the 24 audited planning snapshots per arm, the diagnostic scheduler-failure count was zero for every beam. The observed audited failures were shortlist failures: 8 for K1, 3 for K2, 6 for K3, 1 for K4, and 2 for K5. This supports the current proposal/verification factorization on this toy system, while not proving that scheduler failure cannot occur elsewhere.

## Artifacts

- `artifacts/ar-00k-report.json` — protocol, run results, and audit summaries.
- `artifacts/ar-00k-runs.csv` — one row per arm and seed.
- `artifacts/ar-00k-curves.csv` — epoch curves with proposal and compound evaluation counts.
- `artifacts/ar-00k-audit.csv` — on-policy exact-oracle audit summaries.

The result remains engineering-only, toy-scale, and carries no biological correspondence or general optimizer claim.
