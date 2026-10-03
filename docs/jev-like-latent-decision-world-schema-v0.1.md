# Jev-like Latent Decision World Schema and Generation Grammar v0.1

Status: frozen first-generation semantic substrate. This document authorizes
schema and verifier work only. It does not authorize model training, Phoenix
production-dataset mutation, or claims that synthetic-control records are
Phoenix truth.

The architecture-neutral dataset contract is defined in
[jev-like-decision-dataset-contract-v1.md](jev-like-decision-dataset-contract-v1.md).
This companion document freezes the first exact synthetic-control world
generator that can populate that contract.

## 1. Fundamental invariant

Every generated episode preserves four distinct objects:

```text
WORLD TRUTH
    ↓ generative mechanisms
OBSERVABLE EVIDENCE
    ↓ visibility, noise, and missingness
DECISION STATE
    ↓ query and runtime-schema semantics
GOLD DISTRIBUTION
```

The sampled world is ontological truth inside the synthetic universe. The gold
target is what is justified by the evidence exposed to the decision-maker.
They must not be substituted for one another:

```text
sampled truth != gold probability
```

The initial world family is a small finite Bayesian network or factor graph.
The graph is discrete, acyclic, and small enough for exact enumeration. A
future solver may use variable elimination or another exact method, but the
v0 reference implementation is exact enumeration.

## 2. Canonical latent-world layers

The generator operates on these semantic records before a renderer produces
model-facing text:

```text
WorldTemplate
  → SampledWorld
  → EvidenceState
  → QuerySet
  → ExactGoldTargets
  → RenderingSet
  → PerturbationSiblings
```

The canonical interchange form remains UTF-8 JSONL. Model prompt templates,
chat roles, special tokens, loss functions, and adapter-specific layouts are
not part of this grammar.

### 2.1 World template

```json
{
  "family_id": "system_diagnosis",
  "template_id": "system_diagnosis_v1",
  "version": 1,
  "variables": [
    {
      "id": "root_cause",
      "role": "latent",
      "kind": "categorical",
      "domain": ["compromise", "maintenance", "hardware", "benign"],
      "ordered": false
    }
  ],
  "mechanisms": [
    {
      "target": "root_cause",
      "parents": [],
      "table": [0.15, 0.25, 0.25, 0.35]
    }
  ],
  "constraints": [],
  "observation_channels": [],
  "derived_variables": []
}
```

Variable roles are semantic and may be `latent`, `observable`, `derived`,
`nuisance`, `context`, or `decision_relevant`. The v0 variable kinds are
`boolean`, `categorical`, `ordinal`, and `integer_bounded`.

Each variable has exactly one mechanism in v0. A mechanism table stores one
normalized target distribution per parent assignment. Parent values use the
declared domain order. The factorization is:

```text
P(X1, ..., Xn) = product_i P(Xi | Parents(Xi))
```

The verifier rejects empty domains, duplicate variables, malformed rows,
non-normalized mechanisms, unknown parents, and cycles.

### 2.2 Sampled world

One actual assignment is sampled from the template. It is retained for
counterfactual generation, descendant regeneration, debugging, and evidence
alignment. It is not automatically exposed in a model-facing rendering.

```json
{
  "root_cause": "credential_compromise",
  "unseen_device": true,
  "change_ticket": false,
  "auth_failure_burst": true
}
```

An intervention `do(X=x)` replaces the mechanism for `X` during sampling and
regenerates descendants according to the graph. It is not a textual minimal
pair.

### 2.3 Evidence state

Each observation fact keeps the underlying value separate from what was
visible and what was measured:

```json
{
  "fact_id": "ev_12",
  "source_variable": "unseen_device",
  "true_value": true,
  "visibility": "visible",
  "observed_value": true,
  "channel_id": "unseen_device_sensor"
}
```

Hidden facts have no observed value. A visible fact is passed through its
observation channel, whose likelihood table can represent false positives and
false negatives. Missing, noisy, ambiguous, and intrinsically random evidence
are separate causes of uncertainty and must not be flattened into one
confidence label.

The posterior is conditioned only on visible observed values:

```text
P(query | visible evidence)
```

Hidden true values remain generator-side metadata and are never valid
conditioning evidence.

## 3. Query and gold semantics

Every query declares its semantic primitive. The shared compatibility surface
does not imply shared normalization or probability meaning.

### 3.1 Proposition

For `X = x`, the target is `P(X=x | E)`, with an explicit complementary
probability. This is a binary proposition view.

### 3.2 Independent applicability

For each candidate or proposition `A_i`, the target is independently
`P(A_i applies | E)`. Values do not sum to one and are not a choice posterior.

### 3.3 Closed-world choice

For supplied candidate set `C`, exactly one candidate is assumed valid within
that set. The target is:

```text
P(C_i | E, supplied candidate set C)
```

The reference solver renormalizes posterior mass over `C`, and records the
choice as `closed_world`.

### 3.4 Open-world choice

Candidates are not assumed exhaustive. Explicit candidates retain their
unconditional posterior mass and the residual is recorded as `other`. No
adapter may silently renormalize an open-world target.

### 3.5 Ordinal distribution

An ordinal query stores a full distribution over the declared ordered domain,
plus expected value and entropy. An adapter may later predict cumulative
probabilities, a scalar expectation, logits, or another compatible form, but
the distribution remains the canonical gold object.

### 3.6 Abstention

Abstention is not a universal confidence threshold. The episode stores the
posterior, entropy, an answerability summary, and an optional synthetic policy
threshold used only to derive an example action. Operational abstention is a
utility decision and must remain separable from epistemic answerability.

## 4. Exact gold solving

The v0 solver enumerates all valid assignments, multiplies mechanism factors,
multiplies visible observation likelihoods, and normalizes:

```text
P(X | E) = sum over assignments consistent with X of P(assignment) P(E | assignment)
           -----------------------------------------------------------------------
                         sum over all assignments P(assignment) P(E | assignment)
```

Each gold target records a solver receipt containing the template identity,
conditioning evidence IDs, exact-method marker, and seed. Approximate solvers
are outside this first implementation; when introduced they must record
sample count, uncertainty, interval, and seed so Monte Carlo noise is not
mistaken for model error.

## 5. Generation grammar

```text
EPISODE
  ::= TEMPLATE WORLD_SAMPLE OBSERVATION_SAMPLE QUERY_SET GOLD_SOLVE
      RENDER_SET PERTURBATION_FAMILY

TEMPLATE
  ::= VARIABLE_SET MECHANISM_SET CONSTRAINT_SET OBSERVATION_MODEL

WORLD_SAMPLE
  ::= SAMPLE_LATENTS SAMPLE_DEPENDENTS APPLY_CONSTRAINTS DERIVE_FACTS

OBSERVATION_SAMPLE
  ::= SELECT_VISIBLE_FACTS APPLY_SENSOR_NOISE APPLY_MISSINGNESS
      ADD_NUISANCE_FACTS

QUERY_SET
  ::= PROPOSITION* APPLICABILITY* CHOICE* ORDINAL* ABSTAIN*

GOLD_SOLVE
  ::= CONDITION_ON_VISIBLE_EVIDENCE COMPUTE_EXACT_POSTERIOR
      PROJECT_TO_QUERY_SEMANTICS

RENDER_SET
  ::= PROSE_RENDER JSON_RENDER LOG_RENDER

PERTURBATION_FAMILY
  ::= SURFACE_INVARIANCE* OBSERVATION_INTERVENTION*
      WORLD_INTERVENTION* CANDIDATE_SET_INTERVENTION*
```

## 6. Perturbation classes

Perturbations are first-class sibling records. They are not untracked text
augmentations. Each child links to its parent and declares the expected
relation.

### 6.1 Surface invariance

World and evidence are identical. Only presentation changes: prose/JSON/log,
field order, candidate order, or a meaning-preserving paraphrase.

Strict invariant:

```text
gold_before == gold_after
```

### 6.2 Observation intervention

The sampled world is identical, but visibility or measurement changes. Examples
include hiding supporting evidence, revealing a missing fact, or adding a
contradictory observation. The gold target is always recomputed from the new
visible evidence. A directional expectation such as “removing support should
increase abstention” is a statistical hypothesis, not an exact per-row rule.

### 6.3 World intervention

An underlying variable is changed with `do(X=x')`; descendants are regenerated
by the world graph, observations are resampled under the declared visibility
policy, and affected gold targets are recomputed. This is the source of causal
counterfactual families.

### 6.4 Candidate-set intervention

Candidate manipulation is independent of world and evidence manipulation. The
same state may expose `{A,B}`, `{A,B,C}`, and `{A,C}` as separate queries. The
query records whether each is closed-world or open-world.

## 7. Renderers and nuisance variables

Renderers consume canonical facts; they do not invent or repair truth. The v0
implementation provides prose, JSON, and log/event renderings. Table, key-value,
and dialogue renderers are reserved for a later representation expansion.

Nuisance variables are generated separately from decision-relevant variables.
When a nuisance variable is independent by construction, its addition or
removal gives a provable irrelevant-context control rather than a guessed
distractor. Evidence links and source fact IDs remain canonical.

## 8. Initial world families

The first generator contains three small families with different label names
and likelihood patterns:

```text
system_diagnosis
support_routing
network_incident
```

Each varies root priors, conditional evidence strengths, ordinal severity or
impact, nuisance fields, missingness, and sensor noise. They deliberately do
not claim to represent Phoenix workflows or any real operational domain.

Future families must vary causal topology, not only nouns. Candidate cardinality,
prior entropy, evidence conflict, redundancy, observation noise, context length,
and representation should be sampled independently where possible.

## 9. Reproducibility and verifier obligations

The generator records independent seeds for world sampling, observation
sampling, and rendering, plus a semantic fingerprint. `verify(episode)` is a
dataset component, not a convenience test. It checks:

- template domains, mechanisms, channels, and acyclicity;
- sampled values and evidence values are in domain;
- hidden evidence has no observed-value leak;
- visible and missing ID lists exactly match fact visibility;
- query values, candidate sets, and ordinal declarations are valid;
- gold distributions normalize under their declared semantics;
- gold targets match the exact reference solver;
- renderings reference only visible facts;
- perturbation siblings obey strict invariants or carry recomputed targets;
- deterministic seeds reproduce the same semantic record.

The first pilot generated 10,000 records from these three families and
validated every record. Its artifacts are run outputs, not repository or
Phoenix production data.

## 10. Implementation boundary

The first implementation exposes:

```text
discrete variables
DAG mechanisms
exact enumeration
boolean/categorical observations
closed/open choice
proposition
independent applicability
ordinal distributions
controlled missingness and sensor noise
nuisance variables
prose/JSON/log renderers
surface, observation, and world perturbation families
```

It does not begin with LLM-authored worlds, continuous probabilistic programs,
massive graphs, freeform explanations, market data, or Phoenix truth. Those are
separate research expansions that must preserve this contract.
