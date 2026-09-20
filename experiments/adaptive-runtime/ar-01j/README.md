# AR-01J — Short-Horizon Counterfactual Value

Status: completed diagnostic-only experiment.

Scope: engineering-only, toy-scale, no biological correspondence, no general optimizer claim.

## Question

AR-01I showed that the fixed G3 runtime often selects a block that is not the full-support immediate-loss winner, and sometimes selects a block with negative full-96 immediate utility. AR-01J asks whether those choices are merely tolerated noise or can produce a better short-horizon trajectory.

For every fixed G3 trajectory snapshot, two cloned branches receive different first commits:

1. `G3`: the block/program selected by the stratified-64 verifier.
2. `greedy-first`: the full-96 immediate-utility winner from the same K2 shortlist universe.

After that first action, both branches receive the identical deterministic G3 future stream: proposal batches, stratified verification batches, pair schedule, action grammar, and K2 commit policy. Horizons are 1, 2, 4, 8, 16, 32, and 64 commits. Counterfactual measurement never affects the base trajectory.

The primary quantity is:

```text
Delta_h = full_train_loss(G3 branch at h)
          - full_train_loss(greedy-first branch at h)
```

Negative `Delta_h` means the G3 branch has overtaken the greedy-first branch.

The diagnostic also records validation loss and the future opportunity landscape: best available full-96 utility, positive-block count, harmful-block count, and positive-utility summaries.

## Result

The full-96 immediate-best branch leads at horizon 1 by construction. That advantage shrinks with continuation. Across all three seeds, G3 reaches nonzero reversal rates among initially inferior first actions by h=2 and approximately 42–53% reversal rates by h=64:

| horizon | seed `2b7e...` mean Delta | reversal | seed `77a...` mean Delta | reversal | seed `1111...` mean Delta | reversal |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 0.000613 | 0.0% | 0.000657 | 0.0% | 0.000515 | 0.0% |
| 8 | 0.000295 | 37.8% | 0.000348 | 28.9% | 0.000134 | 36.8% |
| 16 | 0.000060 | 48.6% | 0.000016 | 42.2% | 0.000114 | 48.7% |
| 32 | 0.000042 | 50.0% | 0.000029 | 49.4% | 0.000015 | 52.6% |
| 64 | **-0.000040** | 41.9% | **-0.000174** | 50.6% | **-0.000259** | 52.6% |

The same pattern appears in the aggregate `G3_better_rate`: at h=64 it is 32.3%, 43.8%, and 41.7% for the three seeds. Thus the result is not merely that G3 survives an inferior first action; some initially inferior G3 branches later overtake their immediate-greedy counterfactual under the shared continuation.

### Hypothesis updates

**AR-H33 — Short-horizon value inversion:** supported on AR-01J. Some transitions that are inferior under immediate full-96 utility produce a better trajectory after a fixed continuation of G3 decisions. The effect is present by h=8 in all seeds and is strongest around h=16–64.

**AR-H34 — Immediate-greedy optimization can reduce future opportunity quality:** not supported as a general explanation by this run. Future opportunity deltas are small and mixed. At h=64, G3 has lower mean best-opportunity value for two seeds and slightly higher value for one; the opportunity-better rate remains below 50% in all three. No consistent “G3 creates more future options” signature was found.

The safe conclusion is therefore narrower:

> Full-support immediate utility is not a complete predictor of short-horizon trajectory value on this toy runtime. The observed reversals do not yet establish a specific future-opportunity or authority mechanism.

The strongest alternative explanation is trajectory robustness/slack: the immediate-greedy branch is better at the first step, but later nonlinear pair updates under the shared G3 stream can erase or reverse that small early advantage without requiring the first G3 move to improve future opportunity quality.

## Integrity and artifacts

- Three fixed AR-01 seeds; 96 snapshots per seed; 288 snapshot rows.
- Full-96 reference is immediate utility only, not a globally optimal trajectory oracle.
- Validation loss is diagnostic only and never influences a branch decision.
- Counterfactual branches are cloned from the same snapshot and share the same future exogenous stream.
- Source tests: 4/4; all-target smoke: passed; clippy with `-D warnings`: passed; format check: passed.

Artifacts:

- `artifacts/ar-01j-report.json` — complete machine-readable report and per-snapshot horizon records.
- `artifacts/ar-01j-runs.csv` — one summary row per seed and horizon.
- `artifacts/ar-01j-snapshots.csv` — one row per seed, snapshot, and horizon.

AR-01J remains diagnostic. No controller, confidence gate, or new optimization policy was added.
