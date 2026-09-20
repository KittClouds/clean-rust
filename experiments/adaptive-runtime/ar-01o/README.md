# AR-01O — Closed-Loop vs Frozen-Action Continuation

Status: diagnostic-only. Scope: engineering-only, toy-scale; no biological correspondence and no general optimizer claim.

## Question

AR-01K/L/N found a small same-block matched-program trajectory effect under the original continuation that weakens under shifted pair schedules. O asks whether that difference requires later branch-specific K2 replanning.

## Frozen protocol

- Recreate the three unbranched G3 base trajectories and select the same-block matched controls from N2's complete 7×7 program universe using the existing `5e-5` immediate-utility matching rule.
- O1: branch-specific closed-loop continuation under L0 and L2 schedule phases 17 and 36. It uses the same evidence seeds, minibatches, K2 selector, and horizon semantics as N.
- O2: both first-action branches receive the identical future committed-program sequence recorded from the unbranched original G3 base trajectory. The source trajectory is extended only as far as necessary to provide the last snapshot's 64-commit horizon.
- O2 also evaluates each branch's would-select G3 decision in shadow. Shadow choices are never committed.
- A frozen program is executable only if every changed parameter remains in `[-2, 2]` in both branches. If it would violate bounds in either branch, the paired O2 continuation is marked unevaluable from that step onward; no clamping or replacement action is used.
- Horizons are 1, 2, 4, 8, 16, 32, and 64 commits. Negative `loss(G3) - loss(control)` means G3 is better.

## Decision telemetry

At the first shadow-policy disagreement, record whether the chosen block/no-op changed or the program changed within the same block, each branch's best-versus-runner-up block-utility margin, and the first subsequent paired revisit of either initially changed coordinate. The margin is diagnostic telemetry, not a confidence estimate or controller input.

## Interpretation limits

O1 is the closed-loop reproduction; O2 removes branch-specific action selection while retaining the nonlinear effect of applying a common future action sequence to two different states. O2 is not a new optimizer and does not test arbitrary schedules. A first shadow disagreement is temporal association, not by itself proof that the disagreement mediates the loss difference. Report bound-invalid O2 horizons separately and do not impute them.

## Observed result

- O1 reproduces all 42 N2 summary cells across L0/L2, controls A/B, and seven horizons; maximum absolute difference in mean train-loss delta is `5e-9`. The recreated base G3 final train/validation metrics also match N per seed exactly at reported precision.
- O2 has 210 control-A and 179 control-B comparisons; no frozen action violated bounds.
- Mean `loss(G3) - loss(control)` in O2 is slightly control-favoring at horizons 2 and 4, then G3-favoring from horizon 8 onward. At horizon 64 the means are `-7.790386e-5` (A) and `-7.760885e-5` (B); G3 wins 51.9% and 49.7% of paired rows respectively. The pooled medians are near zero (`-1.408e-6` and `0`), so this is a small, heterogeneous effect rather than a broad per-snapshot win.
- Every seed/control subgroup has a negative mean O2 horizon-64 delta, but the comparison rows are repeated snapshots within only three seeds; treat these as descriptive, not independent significance tests.
- O2 shadow choices diverge in 139/210 control-A and 120/179 control-B comparisons. Under L0, the first divergence averages about 12.6 commits; block/no-op changes are more common than same-block program changes. These shadow decisions are not executed in O2, so their divergence cannot be required to explain O2's loss reversal.
- For all L0 shadow-divergence cases, divergence is at or after the first later paired revisit of either initially changed coordinate (58 coincide with that first revisit; 201 occur later). This timing alone is not causal evidence. The recorded first-divergence margins lack an agreeing-decision margin baseline, so low-margin enrichment remains untested.

Bounded update: branch-specific replanning is **not necessary** for the observed average O2 reversal under the one shared unbranched-G3 action sequence tested. It may amplify the larger O1 effect. The surviving alternative is a path-dependent response to the initial parameter difference under common subsequent updates; this experiment does not identify its data-distribution or curvature mechanism. H40b/H40c remain open.

## Artifacts

- `artifacts/ar-01o-report.json` — protocol, per-seed base metrics, and summary table.
- `artifacts/ar-01o-runs.csv` — mode/stream/control/horizon aggregates.
- `artifacts/ar-01o-snapshots.csv` — matched comparison/horizon rows, divergence margins, revisits, and bounds validity.
- `artifacts/spiral-dataset.bin` — deterministic memory-mapped dataset.

The standalone crate owns its Cargo workspace boundary because the parent Phoenix workspace currently has an unrelated missing external dependency.
