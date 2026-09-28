# R1 Stage 1 Probe Execution Specification v0.1

Status: `FROZEN_PRE_FIT`. This is an executable translation of the frozen v0.2 sensor protocol. It changes no task, target, split, threshold, estimator family, or scientific gate.

## Authority and order

Qualification identity is `R1-STAGE1-SENSOR-QUALIFICATION-v03`, manifest SHA-256 `ae755731c8b377b2672e9ce1aae3be0a1d8469b5e453475fc1297102a23190b0`. The frozen feature source is `sensor-extraction-v03`; its independent exact-row integrity receipt v04 must be `PASS`, and `PROBE-ROW-AUDIT-v01.json` must be `PASS` before any fit.

The only fit order is semantic, then binding, then action relevance. Each rung creates a prediction lock before the scorer opens that rung's evaluation truth. A failed rung writes its exact stop label and blocks every later rung. No particles, proposal/value training, protected search evaluation, or PHENO work is authorized.

## Input construction

Family split, public render variants, private target meanings, action sample generation, and evaluator inputs are inherited byte-for-byte from the v03 qualification manifest and its five prepared files. Each rendered public task maps to one family; no family crosses train, validation, or evaluation. Evaluation rows are built with label `-1` and contain no target label as a predictor.

The four model arms are `real`, `shuffled`, `surface`, and `template`. `template` is a nested diagnostic and is not a gate comparator except where a report explicitly displays it. Every arm uses the same row keys, family IDs, conditions, labels for train/validation, head family, seeds, optimizer schedule, and held-out coverage.

### Real and shuffled inputs

* Semantic: one 2048D clause vector predicts six clause kinds in fixed order `Same, Different, FixedRole, ForbiddenRole, ExactlyOneRole, ImpliesNotRole`.
* Binding: clause vector 2048D + candidate-name vector 2048D + slot one-hot 4D + candidate-kind one-hot 2D = 4102D. Training/validation rows are generated for applicable typed slots. Held-out inference emits every slot/candidate query; the scorer uses private truth only after lock to retain applicable slots and score the exact candidate target.
* Action: mean clause vector 2048D (all zeros for a zero-clause task) + global vector 2048D + assignment one-hot 48D + active-entity mask 12D + active-role mask 4D + edit-entity one-hot 12D + old-role one-hot 4D + new-role one-hot 4D = 4180D. Output order is `improve, neutral, worsen`. No exact violation count, solution distance, or solution multiplicity enters a predictor.

The shuffled semantic/binding control permutes clause vectors within each split and render variant using a SHA-256-derived seed; labels and non-LFM query fields stay fixed. The shuffled action control permutes the complete mean-clause/global representation pair within train/validation split and render variant, and within each held-out evaluation condition. State/edit fields and labels stay fixed. The permutations are fixed and label-blind.

### Surface controls

The 24D task metadata vector is template one-hot 3, vocabulary one-hot 2, entity-count one-hot 12, role-count one-hot 4, role-anonymous flag, clause-count/24, and global-text-length/1024. Per-clause surface metadata is entity incidence 12, role incidence 4, character length/512, whitespace word count/64, normalized clause position, entity mention count/4, and role mention count/2 (21D).

Semantic surface input is 45D: task metadata + clause surface metadata. Semantic template-only is 29D: task metadata + the five scalar clause length/count/position values. Binding surface adds slot one-hot 4, kind one-hot 2, candidate identity one-hot 12, and candidate-mentioned flag to the 45D per-clause surface vector (64D). Binding template-only is 35D: task metadata + five scalar clause summaries + slot and kind one-hots. Action surface is 124D: task metadata + per-entity/per-role clause incidence counts (16D) + the same 84D state/edit input. Action template-only is 108D: task metadata + state/edit input. No clause words, typed labels, private AST, or target-derived values appear in these controls.

## Models and fitting

Every head is `input -> Linear(128) -> GELU -> Dropout(0.10) -> output Linear`, with 6 semantic logits, one binding logit, or 3 action logits. Inputs are normalized per arm using train-only population mean and standard deviation; standard deviations below `1e-6` are replaced by 1.0.

Seeds are `20260926, 20260927, 20260928`. Each arm/seed fit uses AdamW (`lr=3e-4`, `weight_decay=1e-4`), batch 256, at most 40 epochs, gradient norm cap 1.0, patience 6. Training sample weights are inverse class frequency calculated on train rows, normalized within family so every task family has equal total weight. Training row order is seeded and deterministic. Torch intra-op/inter-op threads are 1, TF32 is disabled, deterministic algorithms are enabled, and `CUBLAS_WORKSPACE_CONFIG=:4096:8` is pinned.

The validation score chooses the earliest epoch with the maximum score: balanced accuracy for semantic and action; validation micro-F1 for binding. Binding thresholds are searched over `{0.10, 0.15, ..., 0.90}`; ties select the threshold closest to 0.50, then the lower threshold. Evaluation labels do not select epochs, thresholds, or seeds.

## Frozen gates

* Semantic: for every seed and each of four conditions, real balanced accuracy `>=0.90` and real-minus-shuffled `>=0.20`.
* Binding: for every seed and condition, real micro-F1 `>=0.90`, real-minus-shuffled `>=0.20`, and real-minus-surface `>=0.05`. Exact typed-slot top-1 is diagnostic.
* Action relevance: for every seed, equal-weight mean balanced accuracy across `id_seen, template_ood, vocabulary_ood, joint_ood` is `>=0.60`; each condition is `>=0.55`; mean exceeds each of shuffled and surface controls by `>=0.10`; and the 95% family-cluster bootstrap interval for real minus the better of those two controls excludes zero. Bootstrap uses 2,000 resamples of the 32 evaluation families with replacement and keeps each sampled family's full four-condition panel together.

All three seeds must pass a rung. Failure dispositions are `R1_SENSOR_FAIL_SEMANTIC`, `R1_SENSOR_FAIL_BINDING`, and `R1_SENSOR_FAIL_ACTION_RELEVANCE`. Action anatomy by nearest-solution Hamming distance, violations-before, solution multiplicity, role-anonymous status, problem size, and edit class is descriptive only.

## Lock and score flow

The fit runner writes per-fit receipts, weights, train-only normalizer, and held-out logits, then hashes the complete 3-seed x 4-arm rung surface in `PREDICTION-LOCK.json`. It does not open evaluation labels for scoring. The scorer verifies the source lock, prediction lock, artifact hashes, row keys/order, and frozen input hashes, then opens truth and emits `RUNG-SCORE.json` plus `RUNG-GATE.json`. No later rung may be fit without the previous gate status `PASS`.

The probe runner, feature builder, scorer, row-audit source, test source, extraction-integrity validator, runtime, parent artifacts, prepared inputs, and extraction receipt are pinned in `R1-STAGE1-PROBE-EXECUTION-MANIFEST-v01.json`. Any source or input drift stops before fitting.
