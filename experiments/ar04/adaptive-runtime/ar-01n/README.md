# AR-01N — Same-Block Matched-Program Control

Status: diagnostic-only experiment.

Scope: engineering-only, toy-scale, no biological correspondence, no general optimizer claim.

## Question

AR-01L found that the G3 trajectory advantage weakens when the future pair schedule changes. AR-01N separates two possibilities:

> Does the signal live primarily in the selected parameter pair, or in the exact program applied to that pair?

For every G3-selected pair, controls are matched within the same pair and the same immediate full-training-loss utility stratum. The matching tolerance is `5e-5` in absolute utility gap.

## Domains

| Domain | Control universe |
| --- | --- |
| N1 | The selected pair's existing K2 `top-2 × top-2` shortlist; four programs maximum. |
| N2 | The selected pair's complete `7 × 7` action grammar; 49 programs maximum. |

N1 controls were available to the K2 runtime. N2 is a diagnostic expansion and is not claimed to have been available to the original decision.

Snapshots with a singleton G3 selection or no same-block match remain in the artifacts as unmatched rows. They are not force-matched.

## Continuations

Each G3/control branch receives the same continuation stream within a paired comparison:

| Stream | Evidence | Pair schedule |
| --- | --- | --- |
| L0 | original deterministic evidence | original schedule |
| L2-17 | original deterministic evidence | schedule phase shifted by 17 |
| L2-36 | original deterministic evidence | schedule phase shifted by 36 |

Horizon values use the L/K sign convention:

```text
Delta_h = full_train_loss(G3 at h) - full_train_loss(same-block control at h)
```

Negative values mean G3 is better.

## Required interpretation

- If G3 keeps an advantage against same-block controls, the exact program carries trajectory-relevant signal beyond pair identity.
- If the advantage disappears, the signal primarily lives in block identity and its future revisit structure.
- Mixed results must be reported by domain and continuation; do not collapse N1 and N2 or L0 and L2.

The full-training loss is an immediate-utility reference, not a trajectory oracle. This experiment does not add a schedule-aware controller, a trajectory predictor, or a learned selector.

## Artifacts

- `artifacts/ar-01n-report.json` — per-seed snapshots and protocol metadata.
- `artifacts/ar-01n-runs.csv` — domain/stream/control/horizon summaries.
- `artifacts/ar-01n-snapshots.csv` — raw matched-control continuation rows.
- `artifacts/spiral-dataset.bin` — memory-mapped deterministic dataset.

## Validation

The standalone crate is formatted and compile-gated independently from the parent Phoenix workspace. The parent workspace has an unrelated missing external dependency, so AR-01N owns its `[workspace]` boundary.
