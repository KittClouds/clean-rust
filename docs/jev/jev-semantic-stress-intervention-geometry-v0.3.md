# Jev Semantic Stress & Intervention Geometry v0.3

Status: frozen-readout research slice. QLoRA is not authorized by this slice.

This experiment keeps the canonical `jev-like-decision-dataset/v1` contract unchanged. The new material is a typed, keyed stress manifest:

```text
canonical episode/query/candidate IDs
        +
jev-semantic-stress/v0.3 metadata
        -> stress evaluation geometry
```

The sidecar is deliberate. Ontology distance, split regime, and intervention diagnostics are evaluation annotations, not new gold truth. They are therefore not inserted into the frozen semantic payload or used to change the exact posterior.

## Research question

Does a frozen backbone already contain useful semantic and probabilistic geometry, with remaining failure caused by sparse stress coverage or a restricted compatibility head? Or do failures persist after head capacity, layer location, and dense intervention coverage are controlled, indicating a representation-level deficit?

No backbone weights change. Phoenix is outside the experiment.

## Stress manifest

`stress-metadata.jsonl` contains one record per canonical episode:

```json
{
  "contract": "jev-semantic-stress/v0.3",
  "episode_id": "system_diagnosis-000117-candidate-local_plus_unrelated_distractor",
  "parent_episode_id": "system_diagnosis-000117",
  "stress_family_id": "candidate_ontology:system_diagnosis-000117",
  "intervention_class": "schema_intervention",
  "operation": "local_plus_unrelated_distractor",
  "expected_relation": "recomputed",
  "schema_regime": "in_distribution",
  "lexical_regime": "in_distribution",
  "world_regime": "in_distribution",
  "representation": "prose",
  "ontology_id": "stress-ontology-system_diagnosis",
  "candidate_profiles": ["name", "name_definition", "opaque_definition", "opaque_only"],
  "gold_recomputed": false,
  "queries": [
    {
      "query_id": "q_choice_closed",
      "target_semantic_id": "root_cause=hardware_failure",
      "candidate_distances": {"...": 0, "...": 1, "stress_unrelated_d4": 4},
      "semantic_density": "hard_local"
    }
  ]
}
```

The canonical episode remains authoritative for the world, evidence, query, candidate definitions, and exact target. The sidecar adds:

- explicit D0–D4 structural candidate distance;
- sibling-family identity and parent linkage;
- representation/schema/world regime labels;
- intervention class and operation;
- whether the child target was recomputed by the exact generator.

Distances are assigned by an explicit generator-side ontology rule. They are not inferred from pretrained embeddings. The current pilot maps the local candidate branch and adds a D4 unrelated distractor with zero gold mass where a choice query permits it. A future ontology generator should replace the provisional positional mapping with richer world-family topology while retaining the same sidecar fields.

## Generated pilot

The Rust generator is `experiments/jev-semantic-stress-v03` and uses the v0.1 exact finite-world generator plus the v0.2 canonical adapter. It emits:

```text
stress-episodes.jsonl
stress-metadata.jsonl
stress-manifest.json
```

The validated pilot contains:

| Object | Count |
|---|---:|
| parent worlds | 120 |
| canonical episodes | 2,426 |
| evidence-removal siblings | 386 |
| world-intervention siblings | 840 |
| representation siblings | 240 |
| candidate-ontology variants | 600 |
| definition-paraphrase variants | 240 |
| sibling families | 120 |

Every emitted episode passed the v1 validator and semantic-fingerprint check. The split builder keeps each parent and all descendants in one partition. No random row split is used.

Known pilot limits:

- observation interventions currently remove visible facts; strong/weak evidence labels are not yet promoted from likelihood tables;
- the world-family OOD marker is a split-design placeholder, not a true held-out causal family;
- affected-query IDs are derived diagnostically in analysis from changed variables; they are not yet generator-side gold metadata;
- the current pilot is synthetic-only for stress analysis. External human-disagreement and OOS rows remain separate from exact posterior metrics.

## Frozen evaluation protocol

All three backbones use the same final-layer, mean-full state/candidate features and the validated v0.2 MLP compatibility head:

```text
MiniCPM5-1B-Base  459,009 trainable head parameters
Qwen3-0.6B        327,937 trainable head parameters
K2-Horizon-0.9B   459,009 trainable head parameters
```

The backbone is frozen. The head accepts runtime candidate representations and is not a fixed-inventory classifier.

The dense-bank primary fit uses 5,000 training groups, L3 semantic+Brier+invariance loss, `name_definition` training profile, and candidate-reorder augmentation. Evaluation includes all available held-out stress groups in the test partition.

K2 internal-layer probing is not attempted: its custom Transformers path did not expose a validated hidden-state stack. K2 remains in the final-layer comparison.

## Stress measurements

### Hard sibling geometry

Choice rows are grouped by explicit ontology distance and candidate cardinality. Reported metrics are NLL, Brier, accuracy, posterior entropy, and model entropy. The evaluator does not replace semantic IDs with row positions when comparing siblings.

### Schema OOD

The pilot separates `in_distribution`, `lexical_ood`, and `schema_composition_ood` labels. These are not pooled. The current regimes are generated assignment strata; a true held-out schema family must be added before treating them as a strong OOD claim.

### Interventions

For each parent/child pair, the analyzer aligns candidates by semantic ID and computes:

```text
model delta = child prediction - parent prediction
gold delta  = child exact posterior - parent exact posterior
```

It reports sign agreement, Pearson and Spearman delta correlation, absolute delta error, magnitude correlation, and bins for tiny/small/medium/large gold movement.

### Locality

For world interventions, affected queries are derived from changed latent variables and query semantic IDs. The diagnostic locality ratio is:

```text
mean movement on affected queries
----------------------------------
mean movement on unaffected queries + epsilon
```

This is not a gold benchmark metric until affected-query annotations are generated directly by the world/query compiler.

### Information value

The present report calls the observed quantity `realized_entropy_change_parent_minus_child`. A single sampled evidence removal can have either sign because it compares one realized observation to its marginalized sibling. It is not yet an expected mutual-information estimate. A future exact implementation should enumerate possible observations and compute expected information gain under the world model.

## Current frozen-head observations

On the 5k dense-bank primary runs, the held-out stress metrics were:

| backbone | accuracy | Brier | NLL | trainable params |
|---|---:|---:|---:|---:|
| MiniCPM5-1B | 0.558 | 0.099 | 0.951 | 459,009 |
| Qwen3-0.6B | 0.579 | 0.101 | 0.958 | 327,937 |
| K2-Horizon-0.9B | 0.563 | 0.102 | 0.953 | 459,009 |

Intervention geometry in this pilot shows high sign agreement for large world changes but weak evidence-removal magnitude correlation. Qwen has the slightly strongest world-intervention delta correlation, while MiniCPM is weakest on evidence-removal magnitude correlation. This is diagnostic evidence, not a model promotion claim.

The schema-binding report compares all four runtime profiles. The opaque-definition condition is preserved as a separate readout, and opaque-only is not treated as semantically equivalent to definition-conditioned candidates.

## Layer and capacity controls

MiniCPM and Qwen were probed at 25%, 50%, 75%, and 100% depth with the same small head. K2 is final-layer-only. A small projection control (about 50k parameters) and a larger projection control (about 0.8–1.05M parameters, depending on backbone) were run for all three backbones with a smaller one-epoch budget.

These controls are not substituted for the primary 5k result. Their purpose is to identify obvious readout-capacity or layer-location effects before any weight adaptation.

## QLoRA gate

`reports/qlora-promotion-decision.json` records:

```text
QLoRA authorized: false
decision: defer_and_expand_frozen_readout_coverage
```

Reason: residual hard-sibling and intervention failures are visible, but head-learning saturation has not been established. This pilot has 1k and 5k stress training points, not a completed 10k stress scaling curve. Condition A of the promotion rule is therefore false. Condition B is observed; Condition C is only partially observed under smaller control budgets.

The next decisive frozen experiment is a 1k/5k/10k stress-bank scaling curve with per-family splits, generator-side affected-query metadata, and a real held-out ontology/world-family bank. Only if the residuals persist after that saturation test should QLoRA be reconsidered.

## Artifact map

Repository implementation:

```text
experiments/jev-semantic-stress-v03/Cargo.toml
experiments/jev-semantic-stress-v03/src/main.rs
experiments/jev-semantic-stress-v03/prepare_stress_bank.py
experiments/jev-semantic-stress-v03/analyze_stress.py
experiments/jev-semantic-stress-v03/summarize_controls.py
```

External run artifacts:

```text
D:\codex-runs\jev-semantic-stress-v03\bank
D:\codex-runs\jev-semantic-stress-v03\features
D:\codex-runs\jev-semantic-stress-v03\features-layers
D:\codex-runs\jev-semantic-stress-v03\runs
D:\codex-runs\jev-semantic-stress-v03\reports
```

Required report files are present under the external `reports` directory:

```text
hard-sibling-curves.json
schema-ood.json
opaque-definition-binding.json
definition-paraphrase.json
intervention-delta.json
counterfactual-locality.json
information-value.json
layer-probe.json
head-capacity.json
backbone-behavior-map.json
qlora-promotion-decision.json
```
