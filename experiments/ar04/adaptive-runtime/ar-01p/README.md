# AR-01P — Mixed-Difference Path Ledger

Status: diagnostic-only. Scope: engineering-only, toy-scale; no biological correspondence and no general optimizer claim.

## Question

Under an identical frozen sequence of future pair programs, how does the full-training-loss gap between an N2 G3 program and its same-block, immediate-utility-matched control change along the shared parameter path? Which future actions, data strata, and hidden-layer activation-mask changes account for that change?

## Frozen protocol

- Recreate the three deterministic unbranched G3 trajectories and the N2 same-block controls from the copied AR-01O lineage. A control is selected from the complete 7×7 action grammar using the inherited `5e-5` utility-match tolerance.
- L0 applies the same future committed programs as the unbranched original G3 trajectory, beginning at commit `snapshot + 1`.
- L2 begins from the snapshot after its G3 initial program, generates 63 G3 programs with evidence seed unchanged and deterministic pair-schedule phase 17, then freezes that sequence and applies it identically to the G3 and control branches.
- The first differing program is committed once in each branch; then each branch receives the same 63 future programs. No branch-specific policy replanning occurs during either measured path.
- A frozen program is applied only if every changed coordinate remains in `[-2, 2]` for both branches. The path stops at the first invalid program; no clamp or replacement action is used for that path.
- The three geometry strata per class in the 8-way radial order use the spiral dataset's existing class-major ordering: 32 examples per class, split into 8 consecutive groups of 4.
- ReLU masks record whether each post-ReLU unit is positive in hidden layers 1 and 2 (16 bits per example). Structural relation labels are exclusive coarse categories relative to the actual nonzero parameter support of the initial branch difference; “adjacent layer” is only a layer-index heuristic, not a claim of graph-path distance.
- `reversal_horizon` is the first measured horizon at which the loss-gap sign crosses its initial sign. Because N2 initial gaps are often close to zero, a sign crossing is descriptive and is not itself evidence of a material performance reversal.

## Exact mixed-difference ledger

At each common future program `u`, the recorded full-train gap is `D = loss(G3) - loss(control)` and the exact ledger increment is `J = D_after - D_before`. A second calculation decomposes the four-state difference per example:

```text
j(x) = loss(G3_after, x) - loss(control_after, x)
     - loss(G3_before, x) + loss(control_before, x)
```

The path invariant is `D_end - D_start = sum(J)`. The executable rejects the run if either the telescoping residual or the difference between path-level `J` and the per-example decomposition exceeds `2e-6`.

## Outputs

- `artifacts/ar-01p-report.json` — protocol, counts, identity tolerance and residuals, L0/L2 final-gap and sign-reversal summaries.
- `artifacts/ar-01p-runs.csv` — stream-level descriptive aggregates.
- `artifacts/ar-01p-comparisons.csv` — one row per seed/snapshot/control/stream with concentration, reversal and exact-identity summaries.
- `artifacts/ar-01p-path.csv` — one row per valid shared future commit, including `J`, gap endpoints, per-example decomposition, class and geometry-stratum means, ReLU-mask counts and structural action relation.
- `artifacts/ar-01p-structure.csv` — J totals by coarse structural relation.
- `artifacts/ar-01p-geometry.csv` — J attribution by class and geometry stratum.
- `artifacts/ar-01p-mask.csv` — ReLU-mask difference summaries and none/new/expanding/contracting/turnover/stable transition counts for the exact top decile of `|J|` events versus the rest.
- `artifacts/spiral-dataset.bin` — deterministic memory-mapped dataset.

## Interpretation limits

The mixed-difference identity is algebraic bookkeeping, not evidence for any one curvature mechanism. The structural bins are hand-defined coarse labels. Per-example, class, and geometry aggregation is descriptive. Snapshots repeat within only three seeds and are not independent inferential units. L0 versus L2 compares two specified frozen common paths; it does not isolate every schedule feature. ReLU-mask association with large `|J|` is not by itself causal. This audit adds no controller and makes no claim about biological correspondence or optimizer generality.

## Observed AR-01P results

- Three seeds produced 282 eligible selected-pair snapshots and 389 full-domain N2 matched controls. Each control was traced under L0 and L2: 778 paired paths and 49,014 shared future commits. No path encountered a bounds-invalid frozen action.
- L0 endpoint gaps at horizons 1 and 64 match the saved O2 comparison rows for all 389 controls; maximum discrepancy is `5.0e-10`, consistent with O's CSV decimal precision. The loss-gap telescoping residual is exactly zero in this run. The maximum per-example decomposition residual is `1.252e-6`, below the frozen `2e-6` tolerance.
- Mean initial gap is `-1.8813e-6` for both streams. Mean horizon-64 gap is `-7.7768e-5` for L0 and `-6.8171e-5` for L2. The average mixed-interaction sum is therefore slightly G3-favoring on both tested frozen paths; shifting the common path by phase 17 does not erase that pooled direction. These are repeated-snapshot descriptions across three seeds, not independent inferential estimates.
- Initial-to-final sign crossings occur in 244/389 L0 and 243/389 L2 comparisons. Of 145 comparisons where G3 starts worse (`D0 > 0`), 74 (L0) and 73 (L2) finish with G3 no worse. Many initial gaps are tiny, so crossing counts must be read beside the magnitude summaries.
- Favorable negative `J` contributions are moderately concentrated: mean per-path top-1 / top-5 / top-10 shares are `12.3% / 39.6% / 58.0%` for L0 and `11.5% / 38.9% / 57.2%` for L2. Most favorable contribution is not carried by one or two events, though the largest ten of 63 account for more than half on average.
- Direct-overlap events have the largest mean absolute `J` (`2.53e-4` L0; `2.59e-4` L2), but their net contribution is positive, hence control-favoring (`+0.0368` and `+0.0589` summed across the respective path populations). Same-hidden-unit events are net negative (`-0.0397`, `-0.0392`); coarse adjacent-layer events are also net negative (`-0.0187`, `-0.0405`). Same-layer-unrelated and structural-remote events contribute smaller negative sums. Counts differ markedly by category, and no permutation/null comparison was run, so this is not a formal structural enrichment result.
- All class-level and 8-way geometry-stratum mean contributions are modestly negative in the aggregate for both paths; no single class or stratum dominates the pooled favorable interaction. This averaging can conceal snapshot-level heterogeneity.
- The exact top decile of `|J|` events has mean `|J| = 2.62e-4`, about 21 times the remainder's `1.24e-5`. It also averages about 2.03 examples with branch-specific ReLU-mask differences before the future action, versus 0.48 in the remainder; new/expanding/contracting/turnover mask transitions are more frequent in that top decile. This is an association only, not proof that activation gating caused the large mixed differences.

Bounded update: P confirms the exact mixed-difference decomposition and shows that the L0 average reversal persists under the tested phase-17 frozen common path. Direct coordinate revisits are not the net favorable source in these aggregates; structurally related non-overlap categories contribute negative sums, while direct-overlap interactions are high-magnitude but net adverse to G3. The strongest remaining alternative is ordinary nonlinear, path-dependent response (including possible ReLU-region changes) under the shared updates; P does not establish a single causal category or a general schedule law. H41a is mixed (moderate concentration), H41b is suggestive descriptively but lacks a null, H41c is weakened for these two frozen paths, and H41d shows broadly distributed aggregate contributions rather than one dominant class/stratum.

The crate owns its Cargo workspace boundary because the parent Phoenix workspace may contain unrelated dependency state. Build artifacts should target `D:\adaptive-runtime-targets\ar-01p` (`:G` in the supplied workspace convention).
