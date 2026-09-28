# AR-01Q — Frozen-Path Source Crossover

Status: diagnostic-only. Scope: engineering-only, toy-scale; no biological correspondence and no general optimizer claim.

## Question

Does the AR-01N G3-versus-same-block matched-control loss-gap reversal persist when both initial states are evaluated under a frozen future program sequence generated from either state?

## Frozen protocol

- Rebuild the three deterministic G3 training trajectories from the copied AR-01O code. At every eligible 50-commit snapshot, select the G3 pair and find N2 controls from the same pair using the full 7×7 program domain and the inherited utility-match tolerance. No tolerance widening or replacement matches.
- From the G3 state after its initial program, generate `P_G`; from each matched-control state after its initial program, generate `P_C`. Each path contains up to 63 future programs selected by the inherited G3 continuation policy with identical family-0 evidence seed and phase-0 pair schedule. The policy is run only while generating the source path.
- For each comparison, replay `P_G` into both the G3 and control branches, then replay `P_C` into both branches. No re-planning occurs during replay. A source path is generated once per G3 snapshot and reused for its matched controls; each control gets its own `P_C`.
- Use the 96-example training objective for selection and measurement. Validation examples are not used.
- Before every source or replay commit, verify that each changed parameter remains within `[-2, 2]` in the relevant model. Stop at the first invalid action, report it, and do not clamp or substitute another action.
- Record the horizons 1, 2, 4, 8, 16, 32, and 64. At each shared future update, `J = D_after - D_before`, where `D = loss(G3 branch) - loss(control branch)`. Verify the exact telescoping identity `D_H - D_1 = sum(J)` and the crossover identity `Delta_G - Delta_C = sum(J_PG) - sum(J_PC)` at shared observed horizons, within `2e-6`.

## Outputs

- `artifacts/ar-01q-report.json` — protocol, counts, integrity residuals, endpoint means, and horizon-64 sign categories.
- `artifacts/ar-01q-runs.csv` — paired means by frozen horizon.
- `artifacts/ar-01q-comparisons.csv` — one row per seed/snapshot/control with program identities, immediate utility match, both source-path endpoints, mixed-interaction sums, distances, and validity.
- `artifacts/ar-01q-horizons.csv` — one row per comparison and measured horizon with `Delta_G`, `Delta_C`, source interaction, both cumulative mixed sums, and parameter distances.
- `artifacts/ar-01q-path.csv` — each replayed common program and its exact gap increment under both initial states, including first-step and invalid-action records.
- `artifacts/spiral-dataset.bin` — deterministic memory-mapped dataset.

## Interpretation limits

`P_G` and `P_C` are two state-generated closed-loop program sequences, but their replay is open-loop. A difference between `Delta_G` and `Delta_C` therefore identifies path-source dependence for these paired states, evidence stream, and schedule; it does not establish intrinsic action value, foresight, a general schedule law, or a biological correspondence. Repeated snapshots within three seeds are descriptive rather than independent inferential units. Exact mixed-difference accounting is an identity, not a causal claim about any particular curvature or activation mechanism.

## Observed results

- Three seeds yielded 282 eligible snapshots and 389 N2 same-block controls. The run generated 671 frozen paths: one shared `P_G` path per snapshot and one `P_C` path per matched control.
- All 389 `P_G` replay endpoints at horizon 64 exactly match the corresponding AR-01P L0 records (maximum absolute difference `0` in the saved decimal values). This is the lineage/replay parity check.
- All `P_G` paths replayed fully. Sixteen `P_C` replays stopped at a first bounds-invalid action; source generation itself had zero invalid paths. No action was clamped or replaced. Therefore horizon-64 paired crossover means use the 373 comparisons complete under both paths; the exact counts are present by seed in `ar-01q-runs.csv`.
- On those 373 complete comparisons, mean `Delta_G` under `P_G` is `-7.8029e-5`, while mean `Delta_C` under `P_C` is `+7.5417e-5`. The mean source interaction `Delta_G - Delta_C` is `-1.5345e-4`. Thus, in aggregate, the G3 initial state is favored under the G3-generated path and the matched control state under the control-generated path.
- Per-seed complete-case means have the same direction (G3/control): seed `2b7e151628aed2a6`: `-6.6235e-5 / +9.2098e-5` (`n=116`); seed `77a19d3c4e280b51`: `-9.5213e-5 / +1.1854e-4` (`n=131`); seed `1111222233334444`: `-7.1022e-5 / +1.5230e-5` (`n=126`). These are descriptive repeats, not inferential replicates.
- The paired sign categories at horizon 64 are not a majority of per-comparison source alignment: 143 comparisons favor G3 under both paths, 42 favor the source state under each path, 112 favor the control under both, 3 favor G3 only under `P_C`, and 73 include an exact zero/tie. The strong mean source interaction is therefore magnitude-weighted and does not mean every initial state wins under its own path.
- Both exact identities pass with zero observed residual: each path's `D_H-D_1 = sum(J)`, and the source interaction equals the difference between the two cumulative mixed-interaction sums. Maximum parameter-distance drift under common commits is `5.96e-8`, consistent with floating-point rounding.

Bounded interpretation: Q supports a strong **aggregate path-source interaction** under this L0 continuation and N2 matched-control set, while the per-comparison signs are heterogeneous and 16 control-sourced replays are right-censored by the frozen bounds rule. It does not support the stronger claim that each transition is intrinsically best under its own path, nor any general self-consistency or foresight mechanism. The next cleanroom step is to seal AR-01 and test only the bounded mechanism on a different stochastic substrate.

Build artifacts target `D:\adaptive-runtime-targets\ar-01q` (`:G` in the supplied workspace convention).
