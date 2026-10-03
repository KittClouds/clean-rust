# Jev Frozen Saturation & True OOD Gate v0.4

Status: frozen protocol specification. This document authorizes characterization only; it does not authorize QLoRA, LoRA, prefix tuning, adapter tuning, or backbone-weight modification.

The protocol is the final planned frozen-backbone characterization before reconsidering targeted adaptation. It answers:

```text
Has a reasonable family of frozen readouts exhausted the semantic decision
geometry recoverable from each backbone on the declared stress domain?
```

## Scope and fixed models

Backbones and pinned revisions are inherited from v0.3:

```text
MiniCPM5-1B-Base
Qwen3-0.6B-Base
IFM/K2-Horizon-0.9B
```

Use the validated v0.3 compatibility head as the primary readout. A larger compatibility head and one frozen-feature oracle are diagnostic controls, not replacement production heads. K2 remains final-layer-only unless a separately validated internal-state path is established.

Phoenix, Phoenix production datasets, and current Phoenix trajectories remain out of scope.

## Freeze-before-outcomes rule

Before any v0.4 fit, freeze and hash:

- generator and adapter revisions;
- canonical episode, ontology-family, and world-family identities;
- train/dev/test and OOD family assignments;
- nested training-bank membership;
- primary and diagnostic head definitions;
- loss, optimizer, schedule, augmentation, and seed identities;
- primary endpoints and material-improvement thresholds;
- bootstrap units and confidence procedure;
- QLoRA gate and artifact manifest.

No OOD family, metric, threshold, or promotion rule may be changed after v0.4 outcomes are inspected. The stress sidecar remains evaluation metadata and cannot alter canonical target truth.

## Nested scaling banks

Construct family-safe nested banks:

```text
B1k is a subset of B5k
B5k is a subset of B10k
```

Membership is defined by deterministic parent-family ordering, not by independently sampled rows. Each bank preserves matched source proportions. All descendants of a parent world remain in one partition. The held-out evaluation bank is identical across 1k, 5k, and 10k.

For every backbone and scale, keep fixed: head architecture, loss, optimizer and schedule, candidate representation, augmentation policy, family-safe splits, evaluation bank, and seed identities where applicable.

Required replication:

```text
1k:  one reference seed
5k:  at least three seeds
10k: at least three seeds
```

A 20k point is allowed once, and only if the frozen saturation gate fails because the 5k-to-10k improvement remains material.

## Uncertainty and bootstrap units

Sibling rows are correlated and must not be treated as independent bootstrap observations. Use the largest applicable semantic cluster as the resampling unit:

```text
parent world for intervention siblings
stress family for schema/representation siblings
ontology/world family for OOD cells
```

Report per seed, mean, standard deviation, and a family-cluster bootstrap interval. The contract freezes 1,000 bootstrap replicates and a 95% interval for the primary decision, with a fixed seed recorded in the run manifest.

## Primary saturation endpoints

Orient every endpoint so higher means better.

### Semantic discrimination

```text
hard-sibling rank accuracy
held-out ontology rank accuracy
held-out world rank accuracy
```

### Probability quality

```text
negative log likelihood, sign-reversed for orientation
Brier score, sign-reversed for orientation
```

### Intervention geometry

```text
gold-delta correlation
counterfactual locality ratio, with false-movement diagnostics
```

Accuracy, pairwise ranking, top-2 margin, ECE, entropy error, posterior L1, AUROC where valid, and failure-family overlap remain secondary diagnostics. Semantic ordering and probability quality must always be reported separately.

## Prospective saturation gate

For oriented primary metric `m`:

```text
Delta1(m) = M5k(m)  - M1k(m)
Delta2(m) = M10k(m) - M5k(m)
R(m) = abs(Delta2) / max(abs(Delta1), epsilon)
```

`R(m) < 0.25` is diagnostic only. It is not the saturation gate.

The frozen material-improvement thresholds are:

| Endpoint | Material improvement |
|---|---:|
| hard-sibling rank accuracy | 0.020 absolute |
| ontology-OOD rank accuracy | 0.020 absolute |
| world-OOD rank accuracy | 0.020 absolute |
| oriented NLL | 0.020 absolute |
| oriented Brier | 0.010 absolute |
| gold-delta correlation | 0.050 absolute |
| counterfactual locality ratio | 0.10 absolute |

A metric is saturated for a terminal scaling transition `Sa -> Sb` only when both conditions hold:

1. the observed terminal improvement is below its threshold; and
2. the upper bound of its family-cluster bootstrap interval for the improvement is also below that threshold.

Confidence-interval overlap is not evidence of equivalence. Head learning is substantially saturated only when at least four of the seven primary endpoints pass, all three semantic rank endpoints pass, and no declared critical semantic slice has a material improvement on the terminal transition.

The default terminal transition is `5k -> 10k`. If that transition fails because one or more required endpoints improve materially, a single 20k point may be invoked for that backbone. When invoked, the normative terminal transition becomes `10k -> 20k`; the reports retain both transitions, but Gate A is evaluated on the terminal transition only. A 20k point is not permitted for curiosity or hyperparameter search.

The ratio `R` remains diagnostic. It does not decide saturation.

An asymptotic learning-curve fit is diagnostic and cannot override this gate.

## Factorial true OOD design

The OOD evaluation is a four-cell factorial:

| Ontology | World | Meaning |
|---|---|---|
| ID | ID | ordinary transfer control |
| OOD | ID | runtime-schema/topology transfer |
| ID | OOD | causal-world transfer |
| OOD | OOD | interaction stress |

### Held-out ontology families

Training must not contain the held-out ontology family IDs, semantic IDs, surface names, definitions, hierarchy arrangements, local sibling structures, or runtime schema instances. Topology classes must include deep/narrow, shallow/broad, asymmetric branching, multiple local sibling clusters, multi-attribute candidates, ordinal structures, and open-world sets where supported.

### Held-out world families

Training must not contain the held-out causal topology templates. Initial tractable families should include:

```text
collider:              A -> C <- B
mediated chain:        A -> B -> C -> evidence
hidden common cause:   H -> A and H -> B
competing pathways:    A -> C <- B and A -> D <- B
```

World OOD means unseen causal topology, not only new labels, nouns, or probability tables.

Before evaluation, emit an OOD-novelty receipt auditing parent IDs, semantic IDs, ontology-family IDs, topology-template IDs, world-family IDs, generator-template IDs, and definition-template identities. General-language lexical overlap is allowed; runtime family leakage is not.

## Candidate density ladder

Materialize and report separately:

```text
target + D4 only
target + D2
target + one D1
target + multiple D1
target + all local siblings
target + local siblings + unrelated distractors
```

Report by explicit ontology distance, candidate cardinality, local-competitor count, and topology class. Non-monotonic individual cases do not invalidate the ladder; the aggregate curve must remain interpretable.

## Generator-side intervention truth

The world/query compiler must write, for every intervention:

```text
directly affected query IDs
indirectly affected query IDs
provably unaffected query IDs
```

These are derived from exact causal and query dependency structure, not from model movement. Canonical world and target truth remain unchanged.

Report direct movement, indirect movement, unaffected movement, false movement, missed movement, direction agreement, magnitude error, and locality ratio separately.

## Exact expected information gain

For context `C`, candidate observation `E`, and queried variable `Y`:

```text
IG(E;Y | C) = H(Y | C) - sum_e P(e | C) H(Y | C, E=e)
```

Enumerate all finite observation outcomes exactly. This expected quantity is generator-side gold. The previous realized parent-minus-child entropy change remains a separate diagnostic and must not be called expected information gain.

Evaluate model correspondence with Pearson correlation, Spearman correlation, evidence rank agreement, top-k evidence-selection accuracy, and pairwise preference accuracy.

## Frozen readout controls

### Larger compatibility head

Run one larger reasonable head under sufficient optimization budget. Match data, splits, candidate representations, loss semantics, seed policy, convergence checks, and evaluation bank. Capacity evidence requires that the larger head fails to remove the same residual semantic families, not merely that aggregate accuracy is similar.

### Frozen-feature oracle

Run one deliberately high-capacity nonlinear readout with the backbone frozen. Freeze its design prospectively and do not turn it into a hyperparameter search. The oracle asks whether the allegedly missing distinction is recoverable from frozen features at all:

```text
oracle succeeds -> the primary readout remains a plausible bottleneck and Gate C is FAIL
oracle fails on the same decisive families -> `representation_deficit_supported` is PASS and Gate C is PASS
```

### Layer probes

MiniCPM and Qwen use 25%, 50%, 75%, and 100% validated hidden states. K2 remains final-layer-only without a validated internal path. Report hard siblings, ontology transfer, world transfer, intervention direction/magnitude, locality, information-value geometry, and calibration by depth.

### Binding adversaries

Retain `name`, `name_definition`, `opaque_definition`, and `opaque_only`. Add separate contradictory-binding cases where an opaque token is paired with a definition belonging to a different semantic candidate. Do not pool these cases with ordinary opaque-definition accuracy.

## Residual identity and persistence

A decisive failure is keyed by semantic family and case identity, including world family, ontology family, query, candidate set, intervention, and topology where applicable. The same residual family must persist across seeds and at least two validated readout configurations.

For each failure set compute example-level and family-level Jaccard overlap:

```text
J(A,B) = |A intersection B| / |A union B|
```

Report shared failures, model-unique failures, family overlap, and representative IDs. Aggregate residual similarity alone is insufficient.

## Final QLoRA authorization gate

Each gate is independently `PASS`, `FAIL`, or `BLOCKED` in `qlora-final-gate.json`:

```text
A  primary-head saturation
B  capacity saturation
C  frozen-feature recoverability
D  true-OOD persistence
E  representation-level character
F  replication
```

QLoRA is authorized only if all six gates are `PASS` for the same backbone:

- A: the terminal nested transition (`5k -> 10k`, or the single authorized `10k -> 20k` rescue transition) satisfies the normative saturation rule;
- B: the larger reasonable head does not remove decisive residual families;
- C: the frozen-feature oracle does not remove those same failures;
- D: semantic failures persist on a genuine held-out ontology or causal-world family;
- E: residuals are semantic/ranking errors, not calibration-only errors;
- F: the same residual family replicates across seeds and at least two validated readouts.

Evaluate A-F independently for MiniCPM5-1B, Qwen3-0.6B, and K2-Horizon-0.9B. One backbone passing does not authorize adaptation of another. Cross-backbone failure overlap is diagnostic only. If any required gate is `BLOCKED`, that backbone's QLoRA remains unauthorized. Passing the gate authorizes only a new targeted adaptation protocol derived from measured residual geometry; it does not authorize generic fine-tuning.

## Required artifacts

```text
v04-contract.json
ood-novelty-audit.json
learning-saturation.json
seed-stability.json
head-capacity.json
frozen-feature-oracle.json
layer-behavior.json
true-ontology-ood.json
true-world-ood.json
ood-factorial.json
hard-sibling-density.json
gold-query-locality.json
expected-information-gain.json
binding-adversaries.json
failure-overlap.json
representation-complementarity.json
final-frozen-behavior-map.json
qlora-final-gate.json
```

No aggregate hand-written verdict may override a failed or blocked required gate. If the final gate is blocked by a missing novelty receipt, missing oracle, missing replication, or unsupported K2 layer path, the result is `BLOCKED`, not a provisional pass.
