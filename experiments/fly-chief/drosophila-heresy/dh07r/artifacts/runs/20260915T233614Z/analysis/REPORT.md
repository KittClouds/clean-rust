# DH-07R measured analysis

**OPPOSITE_DIRECTION_EFFECT**

The primary paired estimate compares the endogenous residual direction with the locally matched feasible null direction in both parallel contexts.

Structured minus matched-null final old-map margin: **+0.003991**; paired seed-level 95% t interval **[+0.003227, +0.004755]** and 95% percentile bootstrap interval **[+0.003257, +0.004699]**.

The estimate uses 32 fresh seed bundles and 20,000 deterministic bootstrap resamples. Each seed contributes one value after equal averaging across both slices and both taus.

## Parallel contexts

| Context | Mean true minus null old-map margin | Paired 95% t interval |
|---|---:|---:|
| Parallel off | +0.003474 | [+0.002722, +0.004225] |
| Parallel on | +0.004507 | [+0.003609, +0.005406] |
| On minus off | +0.001034 | [+0.000393, +0.001675] |

## Manipulation validity

All 65,536 committed null events across 256 E-arm null cells passed the frozen gates.

| Diagnostic | Observed maximum | Frozen upper gate |
|---|---:|---:|
| axial_error_over_total_norm | 3.24519833e-08 | 1e-07 |
| norm_relative_error | 2.41774962e-08 | 1e-07 |
| residual_norm_relative_error | 2.41729708e-08 | 1e-07 |
| residual_abs_cosine | 2.13589408e-08 | 1e-05 |
| support_size_relative_difference | 0.00897281371 | 0.01 |

Boundary symmetric difference, outside-support changes, bound violation, and hot-loop allocations were exactly zero for every null event.

## Integrity and limits

- The input contained exactly 32 seeds, two slices, two taus, two arms, and eight conditions: 2,048 result cells.
- Acquisition hashes matched across conditions within each seed, slice, tau, and arm. Fixed-weight Z scientific outputs were condition invariant.
- This estimates an adaptive direction-replacement policy: after arms diverge, each null is matched in its own current state.
- Seeds are paired computational replicates from one synthetic specimen. They are not independent animals or evidence of a biological mechanism.
- A nonzero effect identifies residual-direction specificity under the frozen matching contract; it does not by itself establish latent-memory recovery or transfer to other tasks.

## Machine-readable outputs

- `summary.json`: primary inference, manipulation gates, and integrity receipts
- `seed_contrasts.csv`: one paired primary value per seed bundle
- `cells.csv`: one row per result cell
- `trajectory.csv`: one row per checkpoint and result cell
- `manipulation_cells.csv`: one row per E-arm null-policy cell
