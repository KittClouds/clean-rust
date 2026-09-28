# DH-07R: Realized-Geometry Direction Specificity

Status before measured execution: `FROZEN_UNOPENED`.

## Lineage and correction

DH-07R follows DH-06 and the blocked pre-seal DH-07 constructor. DH-06 measured behavioral contrasts remain valid, but its directional components were defined before the final bound clamp. The precise lineage statement is therefore: DH-06 separated pre-clamp acquisition-aligned and support-masked orthogonal components; final bounded f32 storage could introduce additional acquisition-axis displacement.

`Q07-BoundedNull-v1` qualified a replacement intervention on non-measured seeds 9000 through 9005. It starts from the committed endogenous true endpoint and rotates only true-interior coordinates. Every committed null update must match the true update's realized acquisition-axis displacement and L2 magnitude while changing its feasible residual direction. The qualification covered 12,288 closed-loop events with no gate failure. The DH-06 post hoc clamp audit is descriptive lineage evidence only and does not alter any DH-06 endpoint.

## Question

Given the plasticity directions available to the bounded learner at its current state, does replacing the endogenous realized residual direction with a decorrelated feasible direction change old-map expression when realized axial displacement and total update magnitude are matched?

This is an adaptive policy contrast. After true and null arms diverge, each receives a locally matched intervention calculated from its own current state. Cumulative dose is an outcome of those policies, not a fixed matched treatment.

## Fixed design

- One synthetic specimen: MaleCNS-derived right and left slices used throughout the frozen lineage.
- Fresh computational seed bundles: 7000 through 7031, exactly 32, with no top-up.
- Tau values: 4 and 16. Both are averaged within a seed bundle before inference.
- Sides: R and L. Both are averaged within a seed bundle before inference.
- Arms: learning arm E and fixed-weight negative-control arm Z.
- Acquisition and reversal schedule: 512 trials, 16 cues, 12 delay steps, reversal checkpoints 0, 16, 32, 64, 128, and 256.
- Fixed learning parameters: eta 0.05 and glutamate sign -1.
- Neural interval state is restored in all four geometry cells under the inherited DH-03 operation.

The eight conditions are:

| Condition | Parallel component | Residual direction |
| --- | ---: | --- |
| immediate | inherited reference | no distractor interval |
| quiet | inherited reference | quiet interval |
| neither | off | none |
| parallel_only | on | none |
| true_perpendicular | off | endogenous true residual |
| null_perpendicular | off | feasible matched replacement |
| both_true | on | endogenous true residual |
| parallel_null | on | feasible matched replacement |

All conditions share acquisition streams, reversal stimuli, distractor schedules, exogenous simulator RNG, task rules, and reward rules within a bundle. Realized rewards may differ because reward is action-contingent.

## Committed geometry contract

For each null-policy event, let `W_B` be the committed f32 state after the common update and optional parallel component. Let `W_T` be the normally constrained true endpoint and define the realized displacement `d_T = W_T - W_B` from committed values. With normalized acquisition vector `A_hat`, define:

- `p_T = d_T dot A_hat`
- `r_T = ||d_T||_2`
- `u_T = d_T - p_T A_hat`

The constructor commits a feasible `W_N` and remeasures `d_N`, `p_N`, and `u_N` from stored f32 values. It may modify only the interval-permitted support. Coordinates at a bound in the true endpoint remain fixed; rotations use true-interior coordinates. Deterministic event keys include protocol salt, seed, tau, side, trial/event ordinal, and sweep. The constructor consumes no simulator RNG and allocates nothing in the hot intervention loop.

Every measured null event must satisfy all gates:

- `|p_N - p_T| / ||d_T|| <= 1e-7`
- relative total-norm error `<= 1e-7`
- relative residual-norm error `<= 1e-7`
- `|cos(u_N, u_T)| <= 1e-5`
- exact boundary-membership equality
- zero changed coordinates outside permitted support
- relative realized nonzero-support count difference `<= 0.01`
- zero bound violation
- zero hot-loop allocations

Each E-arm null condition must contain 256 passing event receipts. A missing, non-finite, or failed receipt invalidates the measured run. The true and null interventions need not share identical nonzero realized support because box constraints can force exact zeros.

## Primary outcome and inference

The sole scientific primary outcome is E-arm old-map margin at reversal trial 256. For each seed, first average each condition over both taus and both sides. Then calculate:

`Delta_direction = 0.5 * [(M_true_perpendicular - M_null_perpendicular) + (M_both_true - M_parallel_null)]`.

The directional prediction is `Delta_direction < 0`: the endogenous residual direction suppresses old-map expression more than its locally matched feasible replacement.

Inference uses the 32 seed-bundle contrasts as the units. Report the mean, sample standard deviation, standard error, ordinary paired 95% t interval, and a deterministic 20,000-resample seed-level percentile bootstrap interval using seed 2026091507. There is one primary hypothesis and no multiplicity adjustment.

Interpretation is frozen:

- If both the paired 95% t interval and the 95% percentile bootstrap interval are wholly below zero and manipulation validity passes, conclude that endogenous residual direction has direction-specific behavioral effect under the matched realized-geometry contract.
- If the two intervals disagree in direction or either includes zero, conclude that DH-07R did not resolve direction specificity under this design.
- If both intervals are wholly above zero, conclude that the matched alternate policy suppresses the old map more strongly.
- Any manipulation, lineage, cardinality, or Z-arm integrity failure invalidates the scientific comparison.

## Secondary and descriptive outcomes

Prespecified secondary estimates are the direction contrast separately with parallel off and on, their interaction, true and null residual cells versus neither/parallel-only baselines, final acquisition-axis coordinate contrasts, and full checkpoint trajectories. These receive ordinary 95% intervals and are descriptive.

Manipulation diagnostics include event-level axial error, norm error, residual norm error, residual cosine, support counts, boundary occupancy, number of rotation moves and sweeps, and all integrity gates. The fixed-weight Z arm must preserve condition-invariant scientific outputs and unchanged weights. Immediate and quiet are descriptive lineage anchors and do not enter the primary contrast.

## Execution firewall

The exact release executable, source, Cargo lockfile, config, anatomy inputs, analysis code, Python interpreter identity, NumPy version, Q07 qualification evidence, this protocol, and qualification logs are hashed before execution. The measured executable runs once against seeds 7000 through 7031. Analysis reads only the completed output.

The sealed executable contains no mode that can open a subset of measured seeds. Full measured execution is accepted only from the frozen executable in its sealed repository run directory, with the sealed config, sealed anatomy, and run seal present; the executable verifies its own hash plus config and complete anatomy membership against that seal. It atomically claims a repository-wide `DH07R_MEASURED_SEEDS_OPENED.json` and writes the run-local `MEASURED_SEEDS_OPENED.json` before loading the task. Any crash therefore leaves a permanent one-use receipt that forbids relaunch from every run directory. Post-run verification checks the complete archived file manifests and hashes. Plots are generated from archived measured output and do not rerun the simulator.

No result can establish biological validity, connectome advantage, a latent recoverable memory, or generality beyond this one synthetic specimen.
