# FAS-S08: Exact Decision-Surface Attribution

## Question

Characterize the S06 matched-observer effect directly in the original frozen feature coordinates. Measure (1) the relationship between the two native decision subspaces, (2) order-independent contributions of all four S06 factorial factors to event-level margins, and (3) whether native decision contributions are concentrated in a small set of coordinates or distributed broadly.

## Disposition of S07

S07 remains closed at `SAE_NOT_FAITHFUL_FOR_COMPATIBILITY_ANALYSIS`. Its training and gate trees remain unchanged. S08 does not load S07 sparse codes, inspect SAE features, alter the S07 disposition, or use SAE reconstruction as an analysis surface.

## Identity and parent binding

S08 is a new, read-only analysis identity. It binds to the sealed S06 v02 result, its corrected protocol and parent binding, the S01-2 feature cache and row manifest, the S01-3 metadata/result tree, the FAS-00 mean feature/readout, and the S02 final-position feature/readout. Exact file identities are listed in `contracts/parent-binding-v01.json` and rechecked before execution.

S06's row ledger supplies the complete 16-cell replay and fixed test populations. S01 training coordinates are selected only from rows whose sealed `split_bucket` is 1, 2, 3, or 4. The primary held-out S01 population is exactly the 19,732 rows in S06's `S01_CONTROLLED/FACTORIAL_TEST` ledger. The 512 FAS-00 rows and their slices are external diagnostics only; no selector, threshold, or coordinate set may depend on their outcomes.

## Boundary

Permitted: read and hash bound feature arrays, readouts, S06 ledger/population metadata, S01 event metadata, calculate the contracted geometry and statistics, select coordinate groups from S01 training rows, and intervene on the sealed feature vectors by setting selected native-standardized coordinates to zero.

Forbidden: LFM/tokenizer loading, feature extraction, probe/scaler fitting or mutation, SAE use, statistical significance tests, confidence intervals, architecture or hyperparameter search, FAS-00 use for coordinate selection, changes to S06/S01/FAS-00 artifacts, adaptive mechanisms, and layerwise analysis.

The interventions are fixed-readout feature-coordinate interventions. They do not establish causality inside the transformer.

## Stage 1: Native decision geometry

For each dataset and each native observer (O\in\{M,F\}), let (W_O,b_O,\mu_O,\sigma_O) be its sealed probe and native scaler. Use the S06-prescribed parameter dtypes: FAS-00 values remain float64; S01 scaler and weight/bias values are cast to float32 as in the sealed S06 replay, then promoted to float64 for analytical geometry.

Compute effective class normals (N_O=W_O/\sigma_O) (column-wise) and class intercepts (q_O=b_O-N_O\mu_O). For output classes (a,b\in\{0,1,2\}), compute pair normal (n_{ab,O}=N_{O,a}-N_{O,b}) and pair intercept \(\beta_{ab,O}=q_{O,a}-q_{O,b}\). Then the affine pair margin is (m_{ab}=n_{ab,O}h+\beta_{ab,O}). Preserve the exact effective class/pair normals, intercepts, bases, and singular values in sealed numeric outputs, in addition to the JSON summaries.

Compute numerical rank and orthonormal bases for (U_M=\mathrm{span}(n_{01,M},n_{02,M})) and (U_F=\mathrm{span}(n_{01,F},n_{02,F})), using float64 SVD and the standard threshold `max(matrix_shape) * machine_epsilon * largest_singular_value`. Report both ranks, both principal angles, squared-cosine overlap `sum(cos(angle)^2)`, overlap normalized by the smaller rank, pairwise corresponding-normal cosines/angles, normal norms, and pair intercepts.

For every bound event population, report pair-margin distributions for each representation under each native observer after projection onto each plane (U_M,U_F), alongside the unprojected margins. Projection uses the plane through the origin in the sealed hidden coordinates. The observer's own plane must preserve its full pair margins to numerical tolerance; fail closed if it does not.

## Stage 2: Exact four-factor decomposition

Use the sealed S06 ledger margins, which already apply the contracted semantic mapping for each event. Factor order is `R,C,D,W`, each at levels `M=-1` and `F=+1`. For each event and each of the three fixed semantic pair margins, compute the complete 16-term Walsh-Hadamard decomposition:

`beta[S] = (1/16) * sum_cell margin[cell] * product(level[f] for f in S)`.

Store the empty-set grand mean and all 15 main/interaction coefficients. Also report `2*beta[S]` as the balanced high-minus-low effect for each nonempty term. Reconstruct all 16 cell margins from the coefficients and fail closed if the maximum absolute residual exceeds `1e-10` in float64.

Report descriptive coefficient summaries overall and by target state, native correctness transition (`both_correct`, `M_only`, `F_only`, `both_wrong`), and the frozen factors available in metadata. For S01 these are variant A/C/E/P, context novelty, entity novelty, their four-way combination, and world family. For FAS-00 they are the contracted slices, target label, world family, task structure, and feedback condition. Do not run significance tests or confidence intervals.

## Stage 3: Coordinate contribution census and frozen group selection

Subspace and coordinate census use fixed probe output-class order (candidate-position slots for S01; safe/risky/idle for FAS-00). For each pair and event, coordinate contribution is `c[j] = n[j] * (h[j] - mu[j])`; the exact affine identity is `pair_margin = sum_j c[j] + pair_intercept`. S01 labels used for row accuracy are the sealed `exact_target` candidate-position targets.

On S01 training rows only, report contribution magnitude and signed contribution by coordinate and boundary, M/F top-coordinate overlap at `k={8,16,32,64,128,256}`, sign agreement over paired nonzero contributions, and rank stability between two deterministic quartet-hash halves. On held-out S01, report event-level concentration `K50/K80/K90/K95`, the minimum number of coordinates accounting for the indicated fraction of `sum_j abs(c[j])`, by observer, boundary, and target slot. Report the intercept separately; it is not counted as a coordinate.

Freeze four selector families using S01 training rows only. For each dimension `j`:

1. `native_magnitude_M` and `native_magnitude_F`: mean absolute `c[j]` across training rows and the three pair boundaries for that observer.
2. `paired_surface_difference`: mean absolute `c_F[j]-c_M[j]` across paired training rows and boundaries.
3. `effective_normal_disagreement`: root-mean-square difference between M and F pair-normal coordinates across the three boundaries.
4. `stable_signed_M` and `stable_signed_F`: mean across boundaries of the absolute training-row mean signed contribution.

For each resulting selector, retain top `k={8,16,32,64,128,256}` dimensions, descending score with ascending dimension ID as tie-break. For each selected group, build one disjoint matched control group of equal size from unselected coordinates. Greedy matching visits selected coordinates in descending selector score, ties by ID; each match is the nearest unused unselected coordinate by squared Euclidean distance in training-standardized covariates `[log1p(var_M), log1p(var_F), log1p(mean_abs_c_M), log1p(mean_abs_c_F)]`, ties by coordinate ID. Standardization uses training coordinates only.

## Stage 4: Held-out coordinate interventions

For every frozen selected and matched-control group, separately in native `M/M` and `F/F` systems, set only those coordinates of the native-standardized held-out representation to zero, equivalent to replacing the corresponding hidden coordinate by its native training mean. Keep the sealed native probe, scaler, bias, and all other coordinates fixed.

Report baseline and intervened accuracy, balanced accuracy, per-class support/recall, confusion matrix, target and pair-margin distributions, mean/median paired margin changes, and prediction/correctness transitions on the 19,732 S06-bound held-out S01 rows. Preserve event-level K50/K80/K90/K95 counts, selector score vectors, frozen coordinate groups, and controls in sealed numeric/JSON outputs. There is no result threshold and no group selection may be changed after these outcomes are computed.

Seal all S01 geometry, factorial, census, selected groups, controls, and held-out intervention results first. Verify that S01 seal before loading FAS-00 feature values for analysis.

## External FAS-00 transfer

After the S01 analysis seal is complete, compute the same descriptive native geometry and Walsh decomposition on the S06-bound 512 FAS-00 events, and apply the already-frozen S01 coordinate groups and matched controls to the two FAS-00 native systems. Report the union plus the sealed context-term-3 and entity-term-7 slices. Do not select, reorder, or alter coordinates using FAS-00 results. Seal the transfer stage separately.

## Fail-closed invariants and terminal authority

Stop before outcome interpretation if any parent root/hash, row/event identity, expected count, feature shape, class order, readout identity, finite-value check, native diagonal prediction parity, affine margin identity, projection identity, Walsh reconstruction, or output completeness check fails.

No phase after S08 is authorized. Terminal authority remains `FAS00_SENSOR_PASS=false`, `FAS00_PHASE4_AUTHORIZED=false`, `S08_MODEL_CONTACT=false`, `S08_PROBE_FITTING=false`, and `S08_LAYERWISE_AUTHORIZED=false`.
