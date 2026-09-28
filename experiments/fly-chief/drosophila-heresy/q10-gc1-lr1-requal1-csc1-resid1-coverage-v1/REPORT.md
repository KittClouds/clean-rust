# RESID1 readout coverage audit

This was a read-only receipt audit. No replay or residual interpretation was performed.

| Order | Records | Full `readout_bits` | `readout_sha256` | Residual row analysis |
|---:|---:|---:|---:|---|
| 1 | 3696 | 0 | 3696 | Blocked |
| 2 | 9530 | 9530 | 9530 | Available |
| 3 | 1090580 | 0 | 1090580 | Blocked |

Order-3 residual reachability and near-frontier mismatch-mask audits are blocked by receipt coverage. A readout hash identifies a vector but does not reveal its row-level mismatch mask. Producing missing vectors requires a separately sealed materialization or replay identity.
