# R1 Stage 1 Sensor Qualification Protocol v0.2

Status: `PROTOCOL_AND_PREMODEL_SUPPORT_FROZEN`; no LFM forward pass or probe fit has occurred under this identity. This version carries one implementation-only input-schema repair from v0.1.

## Question and order

Test three gates in order: semantic identity, typed-argument binding, then action relevance. A rung only opens after the preceding rung passes. The terminal failure labels are `R1_SENSOR_FAIL_SEMANTIC`, `R1_SENSOR_FAIL_BINDING`, and `R1_SENSOR_FAIL_ACTION_RELEVANCE`. There is no combined “almost passed” disposition. A failure stops the LFM-backed R1 path; it does not authorize particles.

## Frozen data design

The parent is Stage 0 construction attempt v02, exactly 96 independently generated task families. Split families by sorting `SHA256("R1-STAGE1-FAMILY-SPLIT-v1\\0" || UTF8(family_id))` lexicographically by digest: first 48 train, next 16 validation, final 32 evaluation. No family crosses splits.

Invented vocabularies V0 and V1, their ordered 12-entity and 4-role names, all three global renderings, and all six clause-kind rendering templates are literal constants in `prepare_sensor_qualification.py`. Train and validation use V0 with T0/T1. Evaluation reuses the same 32 held-out families under four equal-weight conditions: `id_seen` (T0/T1,V0), `template_ood` (T2,V0), `vocabulary_ood` (T0/T1,V1), and `joint_ood` (T2,V1). No task, rendering, or vocabulary is selected using target polarity or model output.

The public encoder input is exactly `public-probe-tasks.jsonl` plus `name-queries.jsonl`. Private clause AST targets, solution counts, action states, and `sign(delta violations)` labels are kept in separate private files and are not accepted by the extraction runner. Each family contributes 32 hash-seeded complete assignments; all non-noop one-coordinate role edits are labeled by the independent exact validator. The output of the validator is diagnostic/training truth only.

## Frozen-backbone feature

Use `LiquidAI/LFM2.5-1.2B-Base` revision `7453bca97ca1e67754c4035a4b4c584e1c9dd725`, local snapshot only, `trust_remote_code=false`, `AutoModel` final hidden layer, one text at a time, tokenizer defaults for special tokens, no padding/truncation, eval plus inference mode, deterministic algorithms, BF16 on the declared CUDA device when supported, and cast each visible activation to float32 before arithmetic mean. Save 2048D little-endian float32 vectors for each clause, global task text, and 32 unique candidate names. Backbone parameters remain frozen.

## Probe definitions

All probes use a two-layer MLP: input → 128 → GELU → dropout(0.10) → output. Semantic output is six logits; binding output is one binary logit; action output is three logits. No attention, recurrent state, pretrained probe, or task-private field is permitted.

1. **Semantic identity:** one clause vector `h_j ∈ R^2048` predicts the six typed clause kinds. Train on all T0/T1 train families, select epoch on T0/T1 validation families, and evaluate each of the four held-out-family render conditions separately.
2. **Binding:** concatenate clause vector (2048), candidate-name vector (2048), one-hot argument slot (4), and one-hot candidate kind (2), total 4102. For each applicable typed argument slot, score every in-task candidate of the matching kind; targets identify the exact local AST argument occupying that slot. Report binary micro-F1 and exact slot top-1 accuracy. The F1 threshold is selected on validation only from `{0.10,0.15,...,0.90}`; ties choose the threshold closest to 0.50, then the smaller threshold.
3. **Action relevance:** concatenate mean clause vector (2048), global vector (2048), flattened assignment one-hot padded to 12×4 (48), active-entity mask (12), active-role mask (4), edited-entity one-hot (12), old-role one-hot (4), and new-role one-hot (4), total 4180. Predict `sign(delta violations)` as improve/neutral/worsen. No exact violation count or solution-distance feature is allowed in the predictor.

## Controls

For every rung, fit the same head family and training schedule on (a) a surface-metadata control and (b) a shuffled-feature control. Surface metadata contains only declared names/IDs, mention-incidence masks, template/vocabulary IDs, N/K and length/count summaries; it contains no typed clause labels, clause words, private AST, validator output, or target-derived feature. For action, it additionally receives the public clause-to-entity/role incidence summary and the same assignment/edit encoding. The shuffled control keeps labels and state/edit inputs fixed but deterministically permutes LFM clause vectors (semantic/binding) or whole task representations (action) within the same data split; action shuffling is within evaluation condition. Permutations are derived from domain-separated SHA-256 keys and never use labels.

The surface control is a shortcut audit, not a substitute encoder. Also report template-only performance as a nested diagnostic using template/vocabulary IDs, N/K, and length/count summaries only.

## Fit schedule and metrics

Use three paired initialization seeds `20260926`, `20260927`, `20260928`; one deterministic torch thread; CUDA TF32 disabled; AdamW learning rate `3e-4`, weight decay `1e-4`, batch size 256, maximum 40 epochs, gradient norm cap 1.0, early-stop patience 6. Training loss uses inverse-frequency class weights estimated from train only and equal total weight per task family. The validation metric chooses the earliest epoch attaining the best score. No evaluation labels select epochs, thresholds, or seeds.

For semantic identity, each seed must reach balanced accuracy ≥0.90 in every evaluation condition and exceed shuffled control by ≥0.20 in each condition. For binding, each seed must reach binary micro-F1 ≥0.90 in every condition, exceed shuffled control by ≥0.20, and exceed surface-metadata control by ≥0.05. For action relevance, the equal-weight mean of the four condition balanced accuracies must be ≥0.60, each condition must be ≥0.55, and the mean must exceed each control by ≥0.10; a 95% task-family-cluster bootstrap interval for real-minus-best-control must exclude zero. All three seeds must meet the rung gate. If a rung fails, stop at its exact failure label.

Action diagnostics, with no additional gates: balanced accuracy by nearest-solution Hamming distance, initial violated-constraint count, exact canonical solution-class multiplicity, role-anonymous/specific, N, and legal edit destination. `nearest_solution_hamming` is offline truth only and never a feature.

## Integrity and run order

Before LFM contact, freeze and hash the parent artifacts, preparation outputs, model inventory, extraction source, protocol, environment, seeds, and thresholds. Run support validation and tests first. Extract features once, verify repeated inference byte identity, and freeze feature hashes. Before the first probe fit, freeze and hash the probe-training and analysis sources. Fit/score semantic, then binding, then action; no later rung runs after a failure. Preserve logits/receipts and full control results. No proposal, value head, particle/search run, protected evaluation, or PHENO work is included.

## Pre-model support result

The deterministic 48/16/32 split contains 48/16/32 families. Independent exhaustive enumeration reconciles all 96 raw solution counts with the Stage 0 exhaustion receipts. The prepared public input has 320 rendered task records; support meets the frozen minimum for each clause kind, argument slot, and action class in train, validation, evaluation, and each held-out rendering condition. Support status is `SUPPORT_PASS_PREMODEL`. This is a data-readiness result, not a sensor result.

## v0.2 input-schema repair

The frozen Stage 0 bank contains one valid task with zero constraints. Version 0.1's extraction parser rejected this valid public record before importing Torch or loading the model. Version 0.2 accepts an empty `clauses` array while preserving the task and family in every manifest and action-label file; it does not synthesize a dummy clause. Its mean clause representation for action input is the all-zero 2048D vector when a task has no clauses. The zero-clause family is in train. The prepared task bytes, split, targets, support counts, architecture, and thresholds are unchanged. This repair does not alter the prior v0.1 stop record.
