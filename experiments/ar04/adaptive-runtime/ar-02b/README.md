# AR-02B — Gaussian-cell path-source crossover

Status: diagnostic complete. This experiment is isolated in its own directory on the dated cleanroom branch. AR-02A, R1, and R2 are not modified.

## Question

On the non-spiral Gaussian-cell task, does the relative consequence of a selected first pair program depend on whether the subsequent frozen update path was generated from the selected state or from a same-block, immediate-utility-matched control state?

The selected AR-02A transition is cell-stratified P16/V48 K2. It is called the selected state below; `g3` identifiers in inherited implementation fields are compatibility labels only and do not imply that the spiral G3 policy is being used.

## Frozen protocol

- Reuse the exact R1/R2 Gaussian-cell dataset (96 train, 48 validation); selection and measurement use only the 96 training examples. Validation is never read by this diagnostic.
- Reproduce the P16/V48 cell-weighted runtime for the three frozen R1 seeds. Capture states after commits 600, 2,400, and 4,200.
- At each captured state, select the next K2 pair program using the same proposal stream, cell-weighted verifier, action vocabulary, bounds, and broad pair schedule as R1. Retain only selected two-coordinate programs.
- Find up to two controls from the same parameter pair by exhaustive full `7×7` action enumeration. A control must be legal, have the same positive/neutral/harmful full-training-utility stratum, and differ in immediate full-training utility by no more than the inherited `5e-5` tolerance. No tolerance widening or replacement controls.
- Apply each first program to a clone of the same frozen state. From each resulting state, generate a 63-commit path by rerunning the same K2 policy with the same deterministic P16 proposal/verifier stream and schedule phase 0. Generate the selected-state path once per snapshot and reuse it for its matched controls; generate each control-state path independently.
- Freeze each generated path and replay it into both initial states without replanning. Before every replayed action, validate bounds in both branches. Stop at the first invalid action; never clamp or replace it.
- Measure the full-training-loss gap at horizons 1, 2, 4, 8, 16, 32, and 64. For each path, check `D_H - D_1 = sum(J)`; for the source crossover, check `Delta_selected_path - Delta_control_path = sum(J_selected_path) - sum(J_control_path)` wherever both paths are valid. Tolerance: `2e-6`.

## Outputs

- `artifacts/ar-02b-report.json` — protocol counts, complete-case horizon-64 means, sign categories, and integrity residuals.
- `artifacts/ar-02b-crossovers.csv` — paired path-source outcomes at each frozen horizon.
- `artifacts/ar-02b-paths.csv` — per-commit common-path replay and mixed-difference ledger.
- `artifacts/ar-02b-matches.csv` — selected programs and strict same-block matched controls, including unmatched slots.
- `artifacts/ar-02b-checkpoints.csv` — replayed cell-V48 states, loss, and parameter fingerprint.
- `artifacts/ar-02b-seeds.csv` — complete-case horizon-64 means and win counts, reported by seed.
- `artifacts/gaussian-cells.bin` — immutable copy of the R1/R2 dataset.

## Results

The release run took 24.23 seconds. All nine cell-V48 checkpoints (three seeds × commits 600/2,400/4,200) reproduce the R1 training-loss values at saved CSV precision. The copied dataset hash matches R1/R2. All nine snapshots selected a pair program; strict same-block matching found 12 controls across six snapshots, with no valid controls at the remaining three snapshots. The 12 immediate utility gaps averaged `8.58e-6` (maximum `4.71e-5`, below the frozen `5e-5` tolerance); all controls matched the selected program's positive/neutral/harmful stratum. All 18 generated source paths and all 24 cross-state replays completed without a bounds-invalid action. The horizon-64 analysis therefore has 12 complete comparisons and no bounds censoring.

The aggregate horizon-64 gaps are:

| Frozen path source | Mean `L(selected state) - L(matched state)` |
|---|---:|
| Selected-state-generated path (`P_G`) | `+2.515e-5` |
| Matched-control-generated path (`P_C`) | `+1.234e-4` |
| Source interaction (`Delta_G - Delta_C`) | `-9.827e-5` |

The negative interaction means the selected initial state is *less disadvantaged* under its own generated path on average. It does not mean that the selected state wins on average: both mean loss gaps remain positive. The per-seed source-interaction means are heterogeneous: seed `2b7e151628aed2a6`, `-1.893e-5` (`n=6`); seed `77a19d3c4e280b51`, `-3.050e-4` (`n=4`); seed `1111222233334444`, `+7.720e-5` (`n=2`). Thus two seeds have a negative mean source interaction and one has the opposite sign; the comparison counts differ because the frozen strict match rule found different numbers of controls.

The 12 comparison-level sign categories are also not a universal source-alignment pattern: selected state is better under both paths in 4, only better under `P_G` in 1, matched state is better under both paths in 3, and 4 are mixed or tied. This is a small, heterogeneous diagnostic signal—not a clean replication of AR-01Q's sign pattern. The path identities and mixed-difference telescoping checks pass exactly at the saved decimal precision (maximum residuals `0`); maximum parameter-distance drift is `3.73e-8`.

Across the 12 matched comparisons, six selected-state and control-state generated action sequences were identical; all six had zero source interaction. The other six first differed at future commits 2 (two comparisons), 3 (two), 9 (one), and 58 (one). This is consistent with source interaction arising only when the frozen continuations differ, but does not establish why those different paths produce the observed loss gaps.

## Interpretation and alternative explanation

AR-02B establishes that on this Gaussian-cell task, changing which initial state generates an otherwise common frozen continuation can materially alter the relative loss gap in aggregate. It does **not** establish reliable source-aligned advantage: the selected state remains worse on average under both sources, the source-interaction sign differs by seed, and only one of twelve comparisons has the strict selected-only-under-`P_G` sign pattern. This is weaker and more heterogeneous than AR-01Q, so the path-source phenomenon has not yet earned a portability claim.

The strongest alternative is that the aggregate is driven by a few high-magnitude comparisons in a tiny, selected set of snapshots and by this task-specific cell-V48 continuation; it may not reflect a repeatable property of the runtime. The strict same-block match rule also leaves three of nine states without controls. No controller or training policy was changed by this diagnostic.

## Interpretation limits

This is a path-source crossover, not an optimizer comparison. Replayed paths are open-loop after generation. A source interaction only describes these selected/control states, evidence stream, schedule, and frozen horizon. Three seeds and three dependent checkpoints are descriptive, not independent inferential units. The full-grid controls are diagnostic alternatives and need not have been present in the runtime's K2 shortlist. Results are engineering-only, toy-scale, and have no biological correspondence or general optimizer implication.

## Build

Release and test artifacts target `D:\adaptive-runtime-targets\ar-02b` (`:G` in the supplied workspace convention).
