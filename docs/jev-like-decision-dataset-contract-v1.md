# Jev-like Decision Dataset Contract v1

Status: frozen semantic design; no dataset generation, model training, or
Phoenix production mutation is authorized by this document.

Contract identity:

```text
jev-like-decision-dataset/v1
```

## 1. Scope and non-goals

This contract defines an architecture-neutral dataset for research on
schema-conditioned semantic decisions. It is designed to feed causal language
models, sequence classifiers, compatibility models, and future architectures
without changing the meaning of a target when the model family changes.

The contract does not:

- define Jev's presumed internals;
- declare any open model to be equivalent to Jev;
- create or relabel Phoenix-native truth;
- treat current Phoenix trajectories as labels;
- treat synthetic examples or model outputs as Phoenix-authoritative;
- require a neural normalization function such as softmax or sigmoid;
- require every target to expose a latent probability;
- start model training or benchmark execution.

The Phoenix decision ontology, native decision evaluation protocol, and frozen
trajectory contract remain separate authority domains. A Phoenix receipt may be
referenced by a future adapter only if it independently satisfies the Phoenix
authority contract.

The first exact synthetic-control generator is frozen separately in
[Jev-like Latent Decision World Schema and Generation Grammar v0.1](jev-like-latent-decision-world-schema-v0.1.md).

## 2. Design rationale

The common research object is a compatibility surface:

```text
shared context + runtime schema + candidate semantics
    -> semantic compatibility / decision surface
```

Let `S` be observable state and evidence, `R` a runtime schema, `Q` a query,
and `C` a candidate or candidate set. The contract records the semantic target
`T(S, R, Q, C)` before choosing how a model estimates it.

The views share a candidate-conditioned abstraction but do not share
probability semantics:

| View | Meaning of a probability-like value |
| --- | --- |
| Choice | `P(candidate | state, query, supplied candidate set)` |
| Independent applicability | `P(candidate applies | state, query)` |
| Ordinal / score | A distribution or ordered target on a declared scale |
| Abstain | `P(evidence is insufficient | state, query)` or an explicit abstain action |
| Span/type | `P(type applies to span | state, schema)` |
| Relation | `P(relation holds for arguments | state, schema)` |

The contract therefore stores target semantics, candidate-set scope, and
normalization scope explicitly. A model adapter may emit logits, sigmoid
scores, probabilities, ranks, intervals, or structured predictions, but it may
not silently reinterpret one view as another.

The three initial architecture points occupy different locations in this
space:

- MiniCPM-style causal retrofit: shared context can be cached and runtime
  query/candidate text can be branched; a restricted-token readout is one
  possible adapter, not the canonical target.
- GLiClass-style classifier: state and runtime labels can be jointly encoded
  and scored; independent labels and mutually exclusive choices still require
  different target semantics.
- GLiNER 2.5-style compatibility model: runtime entity/type definitions and
  candidate spans naturally form a span/type surface. The canonical adapter
  target is the `gliner-community/gliner_*‑v2.5` family, with exact model size
  and revision recorded outside the semantic episode.

## 3. Canonical episode model

Every episode has these layers:

```text
Episode
├── identity
├── shared state / evidence
├── runtime schema
├── decision queries
├── candidate definitions
├── gold semantic targets
├── evidence links
├── perturbation family
├── authority / provenance
├── workload metadata
└── evaluation constraints
```

An episode is a semantic unit, not necessarily one training row. It may expose
multiple queries and multiple views over the same state. A model adapter may
split it into rows only after preserving `episode_id`, `query_semantic_id`,
`candidate_semantic_id`, and all sibling links.

## 4. Canonical JSON serialization

The canonical interchange format is UTF-8 JSONL: one complete `Episode` per
line. A binary or columnar representation may be derived later, but its
content identity must be computed from the canonical semantic records after
stable ordering and canonical JSON serialization.

The following top-level shape is normative. Fields marked required must be
present even when their value is an empty array or an explicit `null`.

```json
{
  "contract": "jev-like-decision-dataset/v1",
  "episode_id": "ep-000001",
  "identity": {
    "world_family_id": "wf-credential-001",
    "world_instance_id": "wi-000001",
    "surface_renderer_id": "render-prose-v1",
    "paraphrase_family_id": "pf-none",
    "perturbation_family_id": "perturb-none",
    "schema_family_id": "schema-security-routing-v1",
    "task_family_ids": ["binary-proposition"],
    "domain_family_id": "security-support",
    "semantic_fingerprint": "sha256:..."
  },
  "state": {
    "representation": "prose",
    "observable": {
      "content": "The login token was used from a new device.",
      "items": ["ev-1"]
    },
    "latent": null,
    "variables": {
      "observed": [],
      "missing": [],
      "hidden": []
    }
  },
  "evidence_items": [
    {
      "evidence_id": "ev-1",
      "kind": "text",
      "content": "The login token was used from a new device.",
      "source_ref": "synthetic:finite-bayes-v1",
      "available_at": 0,
      "character_span": [0, 47]
    }
  ],
  "runtime_schema": {
    "schema_id": "rs-000001",
    "schema_family_id": "schema-security-routing-v1",
    "candidates": [],
    "candidate_sets": [],
    "constraints": [],
    "presentation_profiles": []
  },
  "queries": [],
  "gold_targets": [],
  "evidence_links": [],
  "perturbation": null,
  "authority": {
    "episode_authority_class": "synthetic_control",
    "authority_record_ids": [],
    "phoenix_authority_domain": false
  },
  "authority_records": [],
  "workload": {},
  "evaluation_constraints": {}
}
```

### 4.1 Identity

Required identity fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `episode_id` | string | Globally unique record identity |
| `world_family_id` | string | Shared latent-world family; split key |
| `world_instance_id` | string | One latent world instance; split key |
| `surface_renderer_id` | string | Prose, JSON, table, log, key-value, or dialogue renderer |
| `paraphrase_family_id` | string | Meaning-preserving surface family |
| `perturbation_family_id` | string | Sibling group for a controlled change |
| `schema_family_id` | string | Semantic schema family; split key |
| `task_family_ids` | array[string] | Views exposed by the episode |
| `domain_family_id` | string | Domain grouping; split key |
| `semantic_fingerprint` | string | Hash of semantic content, not presentation order |

`episode_id` and every family identity must be stable. Presentation changes
must not change `world_instance_id` when the underlying world is unchanged.

The top-level `authority` summary is required even when every detailed
authority record is listed in `authority_records`. `phoenix_authority_domain`
must be `false` for this research track. A future Phoenix-linked record needs a
separate authority review; it cannot be created by changing this boolean.

### 4.2 State and evidence

`state.representation` is one of `prose`, `json`, `table`, `event_stream`,
`key_value`, or `dialogue`.

`state.observable` contains only information exposed to the model adapter.
`state.latent` is optional and may be populated for synthetic-control records.
`state.variables` separates observed, missing, and hidden variables. Missing is
not the same as false; hidden is not the same as unavailable to the world.

Each `evidence_item` has:

- stable `evidence_id`;
- kind and surface content;
- source/provenance reference;
- availability time when temporal leakage matters;
- optional character or structured-field location;
- optional synthetic likelihood metadata held outside the model-facing view.

Evidence strength is represented as a semantic field only when its authority
defines it. A generator's likelihood is not automatically a human confidence
label.

### 4.3 Candidate definitions and candidate sets

Each candidate definition has this shape:

```json
{
  "candidate_id": "A17",
  "candidate_semantic_id": "credential_compromise",
  "kind": "label",
  "surface": {
    "name": "credential_compromise",
    "description": "Evidence indicates unauthorized access using valid credentials.",
    "aliases": ["stolen_credentials"]
  },
  "opaque_id": "A17",
  "parent_candidate_semantic_id": null,
  "group_ids": ["independent-labels"],
  "order_rank": null,
  "mutually_exclusive_group_id": null,
  "independent_allowed": true
}
```

Required fields are `candidate_id`, `candidate_semantic_id`, `kind`,
`opaque_id`, `group_ids`, `mutually_exclusive_group_id`, and
`independent_allowed`. Human-readable names, descriptions, aliases, hierarchy,
and order are optional but must be present when that representation is part of
the experiment.

`candidate_semantic_id` survives renaming and opaque-ID remapping. It is the
alignment key for perturbation evaluation; `candidate_id` is only local to the
episode.

A candidate set records conditioning:

```json
{
  "candidate_set_id": "cs-ab",
  "candidate_ids": ["A", "B"],
  "set_role": "choice-alternatives",
  "declared_semantics": "choice_conditional",
  "ordered": false,
  "parent_candidate_set_id": null
}
```

`declared_semantics` is descriptive metadata, not an instruction to an
adapter. It must be one of:

```text
choice_conditional
independent_applicability
ordinal_scale
span_type_pairs
relation_pairs
unnormalized_compatibility
unknown
```

The same state may have `{A,B}`, `{A,B,C}`, and `{A,C}` candidate sets. The
contract preserves each set and does not assume that a candidate score is
globally comparable across sets.

### 4.4 Queries

Each query has:

```json
{
  "query_id": "q-1",
  "query_semantic_id": "credential-compromise-question",
  "view": "independent_applicability",
  "instruction": "Does the evidence support credential compromise?",
  "candidate_set_id": "cs-single",
  "argument_scope": null,
  "abstention_policy": "explicit_target",
  "exposed_fields": ["name", "description"]
}
```

`view` is required and must be one of:

```text
choice
independent_applicability
ordinal_score
abstain
span_type
relation
```

`argument_scope` is required for span and relation queries and otherwise must
be `null`. `exposed_fields` is an adapter-facing presentation request; it does
not erase canonical candidate definitions.

### 4.5 Gold targets

Every target binds exactly one `query_id` and one `authority_record_id`.
`score_semantics` is mandatory and must agree with the query view:

```text
choice_conditional
independent_applicability
ordinal_distribution
abstention_probability
span_type_compatibility
relation_compatibility
hard_label_only
unknown
```

The target is a tagged union. The canonical forms are:

```json
{
  "query_id": "q-choice",
  "authority_record_id": "auth-1",
  "score_semantics": "choice_conditional",
  "candidate_set_id": "cs-ab",
  "target": {
    "selected_candidate_semantic_id": "billing",
    "distribution": [
      {"candidate_semantic_id": "access", "probability": 0.125},
      {"candidate_semantic_id": "billing", "probability": 0.875}
    ],
    "abstain_allowed": false
  }
}
```

Independent applicability uses one entry per candidate and does not require
the probabilities to sum to one:

```json
{
  "query_id": "q-labels",
  "authority_record_id": "auth-1",
  "score_semantics": "independent_applicability",
  "candidate_set_id": "cs-labels",
  "target": {
    "candidates": [
      {"candidate_semantic_id": "pii", "applies": true, "probability": 0.94},
      {"candidate_semantic_id": "urgent", "applies": false, "probability": 0.12}
    ]
  }
}
```

Ordinal targets declare an ordered scale and may provide a distribution, a
point, an interval, or all three:

```json
{
  "query_id": "q-quality",
  "authority_record_id": "auth-1",
  "score_semantics": "ordinal_distribution",
  "candidate_set_id": "scale-quality-1-5",
  "target": {
    "scale_id": "quality-1-5",
    "ordered_values": [1, 2, 3, 4, 5],
    "distribution": [0.02, 0.08, 0.25, 0.45, 0.20],
    "expected_value": 3.73,
    "interval": [3, 5]
  }
}
```

Abstention targets preserve both the semantic status and the legal output:

```json
{
  "query_id": "q-abstain",
  "authority_record_id": "auth-1",
  "score_semantics": "abstention_probability",
  "candidate_set_id": "cs-actions-with-abstain",
  "target": {
    "evidence_status": "insufficient",
    "abstain": true,
    "reason": "missing_required_evidence",
    "distribution": [
      {"candidate_semantic_id": "escalate", "probability": 0.07},
      {"candidate_semantic_id": "abstain", "probability": 0.82}
    ]
  }
}
```

Span/type targets use canonical character offsets and semantic type IDs:

```json
{
  "query_id": "q-span-types",
  "authority_record_id": "auth-1",
  "score_semantics": "span_type_compatibility",
  "candidate_set_id": "cs-entity-types",
  "target": {
    "spans": [
      {
        "span_id": "span-mara",
        "start": 0,
        "end": 4,
        "type_targets": [
          {"candidate_semantic_id": "person", "applies": true, "probability": 0.96}
        ]
      }
    ]
  }
}
```

Relation targets use span/entity endpoints, direction, relation semantic ID,
and polarity:

```json
{
  "query_id": "q-relations",
  "authority_record_id": "auth-1",
  "score_semantics": "relation_compatibility",
  "candidate_set_id": "cs-relations",
  "target": {
    "relations": [
      {
        "head_span_id": "span-mara",
        "tail_span_id": "span-orion",
        "candidate_semantic_id": "transferred_to",
        "direction": "directed",
        "holds": true,
        "probability": 0.94
      }
    ]
  }
}
```

Probabilities are optional unless the authority class and generator actually
provide them. A hard label must never be silently converted to a probability.

### 4.6 Evidence links

Evidence links are optional per target but mandatory in structure:

```json
{
  "evidence_link_id": "link-1",
  "target_ref": "q-1",
  "evidence_item_ids": ["ev-1"],
  "role": "support",
  "locations": [{"evidence_id": "ev-1", "start": 0, "end": 47}],
  "required_for_target": false
}
```

`role` is one of `support`, `contradict`, `relevant`, `irrelevant`, or
`argument_endpoint`. Evidence attribution is not required for pure
classification, but preserving it allows span-capable adapters to expose
additional diagnostics.

## 5. Synthetic-control semantics

Synthetic-control records must be generated in this order:

```text
latent world and prior
    -> observable evidence and renderer
    -> exact target or posterior calculation
    -> model-facing episode
```

The generator receipt must identify:

```json
{
  "generator_id": "finite-bayes-v1",
  "generator_revision": "git:...",
  "seed": 41,
  "prior_identity": "prior-credential-v1",
  "likelihood_identity": "likelihood-credential-v1",
  "renderer_identity": "render-prose-v1",
  "posterior_method": "exact-enumeration",
  "posterior_identity": "sha256:..."
}
```

Synthetic latent fields may contain:

- latent variables and domains;
- observable variables;
- hidden variables;
- missing variables;
- evidence likelihoods;
- conflicting evidence;
- irrelevant evidence;
- exact posterior distributions;
- deterministic target constraints.

The generator must not call a language model to invent confidence values and
then label those values as exact posterior truth. A language model may render
surface text, but the semantic target must come from the frozen generator or a
separate adjudication authority.

## 6. Worked synthetic-control episodes

The following records are compact worked examples, not a generated dataset.
All use `authority_class = synthetic_control` and
`generator_id = finite-bayes-v1` unless stated otherwise.

### 6.1 Binary proposition

```json
{
  "episode_id": "sc-binary-001",
  "identity": {
    "world_family_id": "wf-credential-001",
    "world_instance_id": "wi-001",
    "surface_renderer_id": "render-prose-v1",
    "paraphrase_family_id": "pf-binary-001",
    "perturbation_family_id": "pf-binary-paraphrase-001",
    "schema_family_id": "schema-binary-v1",
    "task_family_ids": ["binary-proposition"],
    "domain_family_id": "security",
    "semantic_fingerprint": "sha256:sc-binary-001"
  },
  "state": {
    "representation": "prose",
    "observable": {"content": "A valid login token was used from a new device."},
    "latent": {"credential_compromise": true},
    "variables": {"observed": ["new_device", "valid_token"], "missing": [], "hidden": []}
  },
  "runtime_schema": {
    "candidates": [{
      "candidate_id": "A17",
      "candidate_semantic_id": "credential_compromise",
      "kind": "label",
      "surface": {"name": "credential_compromise", "description": "Unauthorized access using valid credentials."},
      "opaque_id": "A17",
      "group_ids": ["binary"],
      "mutually_exclusive_group_id": null,
      "independent_allowed": true
    }],
    "candidate_sets": [{"candidate_set_id": "cs-single", "candidate_ids": ["A17"], "set_role": "binary", "declared_semantics": "independent_applicability", "ordered": false}]
  },
  "queries": [{"query_id": "q-1", "query_semantic_id": "credential-compromise", "view": "independent_applicability", "instruction": "Does the evidence support credential compromise?", "candidate_set_id": "cs-single", "argument_scope": null, "abstention_policy": "explicit_target", "exposed_fields": ["name", "description"]}],
  "gold_targets": [{"query_id": "q-1", "authority_record_id": "auth-sc-binary-001", "score_semantics": "independent_applicability", "candidate_set_id": "cs-single", "target": {"candidates": [{"candidate_semantic_id": "credential_compromise", "applies": true, "probability": 0.875}]}}],
  "perturbation": null,
  "workload": {"state_length_tokens": 11, "schema_length_tokens": 8, "candidate_cardinality": 1, "branch_width": 1}
}
```

### 6.2 Binary paraphrase sibling

`sc-binary-002` has the same `world_instance_id`, `schema_family_id`, and gold
target as `sc-binary-001`, but uses the surface
`The authentication credential succeeded on a device never seen before.`
Its `perturbation_family_id` is `pf-binary-paraphrase-001`, with operation
`criterion_paraphrase` and expected relation `strict_invariant`.

### 6.3 Mutually exclusive choice and candidate-set dependence

The state is: `The customer cannot sign in after a password reset; there is no
billing complaint.` The latent posterior over queue is:

```text
access = 0.10, billing = 0.70, security = 0.20
```

The episode contains two candidate sets and two choice queries:

```json
{
  "candidate_sets": [
    {"candidate_set_id": "cs-abs", "candidate_ids": ["access", "billing", "security"], "declared_semantics": "choice_conditional"},
    {"candidate_set_id": "cs-ab", "candidate_ids": ["access", "billing"], "declared_semantics": "choice_conditional", "parent_candidate_set_id": "cs-abs"}
  ],
  "gold_targets": [
    {"query_id": "q-full", "score_semantics": "choice_conditional", "candidate_set_id": "cs-abs", "target": {"selected_candidate_semantic_id": "billing", "distribution": [{"candidate_semantic_id": "access", "probability": 0.10}, {"candidate_semantic_id": "billing", "probability": 0.70}, {"candidate_semantic_id": "security", "probability": 0.20}]}},
    {"query_id": "q-subset", "score_semantics": "choice_conditional", "candidate_set_id": "cs-ab", "target": {"selected_candidate_semantic_id": "billing", "distribution": [{"candidate_semantic_id": "access", "probability": 0.125}, {"candidate_semantic_id": "billing", "probability": 0.875}]}}
  ]
}
```

The subset distribution is conditional on the supplied subset. It must not be
compared as though it were an absolute probability for billing.

### 6.4 Independent multi-label

The state contains a payment receipt with an account number and an explicit
request for a human review. The candidate labels are independent:

```text
pii             applies=true,  probability=0.94
financial_data  applies=true,  probability=0.88
human_review    applies=true,  probability=0.91
urgent          applies=false, probability=0.18
```

The probabilities do not sum to one. The episode is a sibling of a
`candidate_rename` variant in which `pii` is presented only as opaque ID `L3`
with the same `candidate_semantic_id`.

### 6.5 Ordinal score

The state contains three mutually consistent evidence items and one weakly
relevant item. The query asks for evidence quality on an ordered 1–5 scale:

```text
P(1..5) = [0.02, 0.08, 0.25, 0.45, 0.20]
expected_value = 3.73
interval = [3, 5]
```

This is an ordinal distribution, not five independent applicability labels and
not a choice probability over arbitrary candidates.

### 6.6 Abstention under missing evidence

The state contains a suspicious login and a password reset, but no reliable
authentication log and no actor identity. The legal actions are `escalate`,
`reset_credentials`, `lock_account`, and explicit `abstain`:

```text
evidence_status = insufficient
missing_variables = [authentication_log, actor_identity]
P(escalate) = 0.07
P(reset_credentials) = 0.06
P(lock_account) = 0.05
P(abstain) = 0.82
```

The gold target records both the explicit abstain candidate and the reason
`missing_required_evidence`. A model that emits no action is not equivalent to
selecting the abstain candidate.

### 6.7 Span/type and relation compatibility

The prose state is:

```text
Mara transferred the audit key to Orion after the failed login.
```

Canonical spans are `Mara [0,4]`, `audit key [22,31]`, and `Orion [36,41]`.
The schema defines types `person`, `credential`, and `system`, plus the
directed relation `transferred_to`.

Gold compatibility targets include:

```text
(Mara, person)       applies=true, probability=0.96
(audit key, credential) applies=true, probability=0.99
(Orion, system)      applies=true, probability=0.91
(Mara, Orion, transferred_to) holds=true, probability=0.94
```

The relation target references span IDs, not surface strings. A representation
change to a JSON event record preserves the same semantic IDs and is a strict
invariance sibling.

## 7. Perturbation specification

Perturbations are immutable sibling objects, not untracked augmentations. Each
variant records:

```json
{
  "perturbation_family_id": "pf-001",
  "parent_episode_id": "ep-001",
  "variant_episode_ids": ["ep-001", "ep-002"],
  "operations": [
    {
      "type": "candidate_reorder",
      "parameters": {"permutation": [2, 0, 1]},
      "affected_query_ids": ["q-1"],
      "expected_relation": "strict_invariant"
    }
  ],
  "alignment": {"by": "candidate_semantic_id"}
}
```

Required operation types and expectation policy:

| Operation | Default expectation |
| --- | --- |
| `candidate_reorder` | Strict invariant after semantic-ID alignment |
| `candidate_subset` | Retained semantic labels invariant; conditional scores may change |
| `candidate_superset` | Existing labels retain meaning; conditional scores may change |
| `candidate_rename` | Strict invariant if semantic identity is preserved |
| `opaque_label_mapping` | Strict invariant if definitions are exposed equivalently |
| `criterion_paraphrase` | Strict invariant |
| `criterion_rephrase_with_same_semantics` | Strict invariant |
| `context_reorder` | Strict invariant when temporal/order meaning is not changed |
| `irrelevant_context_addition` | Strict invariant only when irrelevance is certified |
| `irrelevant_context_removal` | Strict invariant only when irrelevance is certified |
| `supporting_evidence_removal` | Directional confidence decrease or abstention increase; not a guaranteed label flip |
| `contradictory_evidence_addition` | Directional movement toward contradiction or abstention |
| `contradictory_evidence_removal` | Directional movement away from contradiction |
| `minimal_semantic_flip` | Affected targets change; unaffected targets invariant |
| `counterfactual_state_change` | Declared targets change according to generator semantics |
| `representation_change` | Strict invariant after canonical alignment |

Strict invariants are pass/fail comparisons. Directional expectations are
statistical tests over a family and must not be scored as exact equality.

For every sibling family, the contract must identify affected and expected
unaffected query semantic IDs. Perturbations must not be applied to labels,
spans, relations, or evidence without preserving their semantic alignment
metadata.

## 8. Gold-authority policy

Authority is mandatory at both episode level and gold-target level. The target
authority wins when an episode contains mixed sources.

| Class | Meaning | Creator | Training | Calibration | Benchmark claims | Mixing policy |
| --- | --- | --- | --- | --- | --- | --- |
| `authoritative` | Domain authority or immutable operational receipt | Named authority with durable identity | Yes | Yes | Yes, within authority scope | Never silently merged with another truth domain |
| `externally_annotated` | Released human/expert or benchmark annotation | Source dataset owner | Yes | Yes if version and protocol are known | Yes with source/license disclosure | Preserve source and annotation version |
| `adjudicated` | Independent annotations resolved by a declared adjudication protocol | Named adjudication process | Yes | Yes | Yes with adjudication metadata | May mix with external labels only by target and source |
| `weak` | Heuristic, distant, programmatic, or model-assisted label | Declared heuristic/model/pipeline | Auxiliary or weak-only training | No primary calibration | No primary benchmark claim | Never promote by majority vote alone |
| `synthetic_control` | Generator-produced world with frozen exact semantics | Versioned generator | Yes for controlled training studies | Yes only on synthetic-control slices | Only synthetic-control claims | May mix as a separate source; never relabel as authoritative |
| `unverified` | Provenance or semantic correctness is unresolved | Unknown or incomplete | No | No | No | Quarantine; no aggregation with scored data |

Every authority record must include:

```text
authority_record_id
authority_class
authority_scope
creator_or_system
source_identity
source_revision_or_snapshot
annotation_or_generator_protocol
created_at / available_at when relevant
license or access basis when external
parent_authority_ids
quality limitations
```

Synthetic-control records may establish a known mathematical target, but they
remain synthetic-control. They cannot become Phoenix-authoritative because
their surface resembles Phoenix data.

## 9. Split and leakage policy

Random row splits are prohibited. The split manifest must bind disjoint sets of
the following identities:

```text
world_family_id
world_instance_id
surface_renderer_id
paraphrase_family_id
perturbation_family_id
schema_family_id
task_family_id
domain_family_id
```

Default split regimes are separate named evaluations:

| Regime | Held-out factor |
| --- | --- |
| `surface_ood` | New renderer, paraphrase, and representation surface |
| `schema_ood` | New schema family and candidate descriptions |
| `candidate_ood` | New candidate names and opaque mappings with known semantics |
| `cardinality_ood` | New candidate counts and branch widths |
| `world_ood` | New latent world families and instances |
| `domain_ood` | New domain families |
| `composition_ood` | Unseen combinations of individually known perturbations |

Leakage failures include:

- a world instance or semantic fingerprint crossing partitions;
- a perturbation sibling split across train and evaluation;
- a renderer revealing a held-out surface template;
- candidate descriptions copied from evaluation into training;
- latent variables or posterior values exposed in the model-facing state;
- evidence created after the declared observation cutoff;
- model-generated labels used as evaluation gold;
- an authoritative outcome used as an input feature;
- candidate-set membership derived from the selected answer;
- a weak label promoted through post-hoc agreement with a model.

The split manifest, identity hashes, and leakage audit are part of the dataset
identity. A row may not be moved between partitions without a new contract
revision and a new dataset identity.

## 10. Workload metadata

Workload metadata records observed values, not fixed benchmark assumptions:

```json
{
  "state_length_tokens": 512,
  "schema_length_tokens": 96,
  "number_of_queries": 12,
  "candidate_cardinality": 16,
  "candidate_token_length_mean": 5,
  "candidate_description_length_mean": 18,
  "branch_width": 12,
  "label_density": 0.25,
  "relevant_evidence_count": 3,
  "distractor_count": 8,
  "contradiction_count": 1,
  "span_count": 7,
  "relation_count": 2,
  "measurement_method": "tokenizer-independent-estimate-v1"
}
```

The dataset contract does not hardcode target sizes. Later benchmark manifests
may define ranges or quantile buckets over these dimensions for latency,
quality, calibration, prefill, marginal-query, and schema-scaling surfaces.

## 11. Architecture adapter sketches

Adapters translate the same canonical episode into model-specific inputs and
back into the canonical target semantics. They must record model identity,
adapter revision, presentation profile, and any output conversion. They may not
modify gold targets.

### 11.1 MiniCPM / causal LM retrofit

Possible projection:

```text
state/evidence -> cached prefix
query + schema + candidate definitions -> branch suffix
candidate surface -> restricted token positions or compatibility head
output -> canonical choice / applicability / ordinal adapter
```

Choice may use a candidate-set conditional readout. Independent applicability
must not be forced into one softmax over labels; it needs one-vs-rest or a
declared independent compatibility readout. Span and relation queries may be
rendered as explicit candidate arguments, but the adapter must mark evidence
localization as unavailable unless separately produced.

The adapter must retain both fresh-state and shared-prefix execution modes so
cache reuse, branch width, and numerical drift can be measured later.

### 11.2 GLiClass-style sequence classifier

Possible projection:

```text
state/evidence + task instruction + runtime label descriptions
    -> joint sequence encoder
    -> per-label compatibility scores
    -> view-specific conversion
```

Independent applicability consumes one score per candidate. Choice consumes the
same candidate scores but applies a conditional normalization only in the
adapter and only for a choice target. Ordinal views expose ordered scale
labels and preserve their order. Span/relation views can be represented as
candidate statements, but the adapter must not claim native span localization.

### 11.3 GLiNER 2.5-style compatibility model

The primary target line is the versioned
`gliner-community/gliner_*‑v2.5` family. The direct projection is:

```text
observable text -> text encoder
runtime type definitions -> schema/type representations
candidate spans x type definitions -> compatibility matrix
```

Canonical character offsets remain authoritative; tokenizer wordpieces and
maximum span width belong only to the adapter. Span/type outputs map directly
to `span_type_compatibility`. Relation queries use endpoint span IDs and
relation definitions; whether they are implemented by a relation-capable
GLiNER adapter or a separate compatible model is recorded as adapter metadata,
not changed in the canonical target.

Opaque-label experiments must preserve the semantic ID while changing the
model-facing surface. If the adapter requires a description to operate, that
requirement is logged as a presentation constraint rather than hidden in the
gold schema.

## 12. Initial evaluation contract

The dataset must retain enough information to compute, by view:

```text
accuracy
macro/micro F1
span and relation exact match / partial match
negative log likelihood where a valid distribution exists
Brier score
ECE or a declared alternative calibration error
risk-coverage
abstention precision, recall, and selective risk
candidate-order stability
candidate-set sensitivity
paraphrase stability
counterfactual sensitivity
irrelevant-context robustness
OOD calibration
evidence-removal response
workflow-level downstream correctness
```

Choice reports must align candidates by `candidate_semantic_id` before scoring.
Independent applicability must not use multiclass accuracy as its primary
metric. Ordinal targets require ordinal-aware metrics in addition to point
accuracy. Span and relation metrics must preserve exact endpoint and direction
semantics.

Every quality result should be joinable to workload metadata for:

```text
wall latency
throughput
memory peak
prefill cost
marginal query cost
branch width
schema cardinality scaling
```

No model benchmark is part of this contract pass.

## 13. Unresolved questions requiring experiments

The following are deliberately not decided by specification:

1. Whether exact synthetic posteriors transfer usefully to natural-language
   decision calibration, or mainly test representation and normalization.
2. Whether choice targets should be generated by posterior conditioning,
   utility-maximizing choice, or both as separate task families.
3. How much candidate description text is needed before opaque-ID tests become
   an artificial language-understanding task rather than a semantic test.
4. Whether descriptions should be independently encoded, jointly encoded, or
   both in the first fair adapter comparison.
5. How to score probability movement under evidence removal when the hard label
   remains unchanged but evidence remains sufficient.
6. How nested, overlapping, and discontinuous spans should be represented for
   the first GLiNER 2.5 slice.
7. Whether relation absence should be explicit negative evidence, unknown, or
   unobserved for each domain.
8. What annotation agreement threshold is sufficient for a benchmark claim on
   ambiguous abstention cases.
9. How authority classes should be mixed during training without allowing weak
   labels to dominate calibration.
10. Whether shared-prefix branching changes semantic outputs enough to require
    a separate numerical-equivalence gate.
11. Which workload axes dominate marginal query cost for each architecture.
12. Whether one common episode should expose all six views during training or
    whether view-balanced curricula are required.
13. How to compare evidence localization from GLiNER-like adapters with
    classification-only adapters without penalizing a model for an optional
    capability.
14. What minimum external gold set is needed before any claim about a
    purpose-built architecture beating a retrofit is credible.

## 14. Decision criterion

The contract is internally coherent if one latent episode can be projected into
MiniCPM, GLiClass, GLiNER 2.5, and future adapters while preserving:

```text
the same state meaning
the same candidate semantic identities
the same view-specific probability meaning
the same abstention meaning
the same evidence alignment
the same perturbation expectations
the same authority and split boundary
```

If an adapter cannot represent one view without changing its semantics, the
adapter is incomplete or the view must be marked unsupported. The canonical
dataset must not be weakened to make an architecture appear compatible.

## 15. Research anchors

The GLiNER 2.5 adapter target is pinned conceptually to the official
`gliner-community/gliner_*‑v2.5` model family and its GLiNER interface. The
contract's shared-state and direct-decision framing is informed by public
behavioral experiments, but no external model result is treated as gold.

- [GLiNER v2.5 model family](https://huggingface.co/gliner-community)
- [GLiNER small v2.5 model card](https://huggingface.co/gliner-community/gliner_small-v2.5)
- [GLiNER architecture](https://urchade.github.io/GLiNER/architectures.html)
- [GLiClass architecture paper](https://arxiv.org/html/2508.07662)
- [SemIf method and claim boundaries](https://github.com/TheoLeeCJ/SemIf/blob/master/docs/METHOD.md)
