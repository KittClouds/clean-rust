# Phoenix Graph Decision Ontology v1

## Status

Implemented as a closed contract in `phoenix-types` on 2026-07-14.

This cut defines the decision language and reward representation only. It does
not construct a dataset, train a policy, execute graph mutations, or infer
historical labels. The later decision-receipt executor must prove every external
precondition against an immutable pre-decision state before applying an action.

## Contract boundary

The authoritative Rust surfaces are:

- `graph_decision_contract.rs`: the closed action vocabulary and the contract
  metadata for every action;
- `graph_decision.rs`: typed wire payloads, intrinsic validation, authority,
  approval, evidence-time validation, and the reward vector;
- `graph_decision_tests.rs`: fail-closed correctness gates.

The ontology lives in `phoenix-types`, above storage and below graph-kernel,
dataset, evaluator, trainer, or policy code. Those systems may consume this
contract. They may not redefine it locally.

## Closed action vocabulary

The wire discriminator is `kind`. It accepts exactly these snake-case values:

```text
accept_delta
reject_delta
defer_delta
merge_delta
attach_to_episode
create_episode
link_evidence
classify_discrepancy
propose_relation
repair_graph_region
abstain
```

There is no `other`, `custom`, `unknown`, free-text action kind, or generic
fallback payload. Each variant has its own `deny_unknown_fields` parameter
type. Unknown action kinds, unknown fields, missing required fields, invalid
authority, missing mandatory approval, missing required evidence, duplicated
inputs, and future evidence all fail before execution.

Every action carries the common header:

```text
schema version
decision ID
pre-state identity
decision timestamp
authority identity, kind, policy identity, and issuance timestamp
optional human approval identity, approver, and timestamp
```

Evidence references retain evidence identity, evidence authority, and the time
the evidence became available. `availableAt > decidedAt` is illegal. Authority
or approval issued after the decision is also illegal. This is the first
executable guard against training on information that was not knowable then.

## Action matrix

“Reversible” means the ontology deliberately leaves the target eligible for a
later terminal action. It never means mutating or deleting the original receipt.
All receipts are append-only. A correction to a terminal action requires a new,
explicitly authorized compensating graph decision in a later contract.

| Action | Required action parameters | Evidence | Allowed authority | Human approval | Reversible | Deterministic postcondition |
|---|---|---|---|---|---:|---|
| accept delta | delta ID | required | operator, authoritative committer | mandatory | no | proposal accepted; graph-truth commit required |
| reject delta | delta ID, closed rejection reason | optional | operator, authoritative committer | mandatory | no | proposal rejected |
| defer delta | delta ID, closed deferral reason; optional resume time | optional | policy, operator, authoritative committer | no | yes | proposal remains durable and deferred |
| merge delta | at least two unique delta IDs, new merged-delta ID | required | operator, authoritative committer | mandatory | no | inputs resolved into one pending merged delta |
| attach to episode | event ID, existing episode ID, candidate-set ID | required | operator, authoritative committer | mandatory | no | event attached to the selected canonical episode |
| create episode | event ID, new episode ID, candidate-set ID | required | operator, authoritative committer | mandatory | no | episode created and event attached |
| link evidence | claim ID | required | compiler, evidence curator, operator, authoritative committer | no | no | evidence lineage attached to the claim |
| classify discrepancy | discrepancy ID, at least two unique assertion IDs, closed class | required | operator, authoritative committer | mandatory | no | discrepancy receives one authoritative class |
| propose relation | proposal ID, source ID, relation type, distinct target ID | required | compiler, policy, operator, authoritative committer | no | yes | candidate-only relation proposal created; graph truth unchanged |
| repair graph region | region ID, repair-delta ID | required | operator, authoritative committer | mandatory | no | repair accepted; graph-truth commit required |
| abstain | task ID, closed abstention reason; optional candidate-set ID | optional | any authenticated ontology authority | no | yes | abstention recorded; graph truth unchanged |

## Closed subordinate vocabularies

Delta rejection reasons:

```text
unsupported_by_evidence
contradicts_authoritative_state
duplicate
stale_pre_state
invalid_scope
invariant_violation
```

Delta deferral reasons:

```text
insufficient_evidence
awaiting_human_approval
awaiting_source
temporal_ambiguity
conflicting_authority
```

Discrepancy classes:

```text
contradiction
temporal_revision
contextual_difference
source_disagreement
duplicate_evidence
```

Abstention reasons:

```text
insufficient_evidence
no_legal_action
ambiguous_candidates
authority_unavailable
future_information_required
invariant_risk
```

Free text may accompany a future receipt as non-authoritative explanation. It
must never replace these semantic labels.

## Legal preconditions

Intrinsic preconditions are enforced by `GraphDecisionAction::validate`:

- exact schema version;
- non-empty stable identities;
- action-specific authority;
- mandatory approval where required;
- evidence presence where required;
- evidence and authority available no later than the decision;
- unique multi-input IDs;
- at least two inputs for merge and discrepancy classification;
- future-only defer time;
- distinct relation endpoints.

External preconditions are enumerated in each `GraphDecisionActionContract` and
must be certified by the later executor against the identified pre-state:

- pre-state and targets exist;
- proposals or discrepancies remain open;
- graph invariants survive the proposed delta;
- candidate sets contain the selected target and no future facts;
- episode scope is compatible;
- canonical IDs are available;
- relation is not already active;
- repair-region revision still matches;
- actor authority is current.

An executor must not infer success from missing proof. Missing precondition proof
is rejection, not `false`, `null`, best effort, or fallback behavior.

## Graph invariants

Every contract carries an explicit subset of these stable invariants:

```text
pre-state immutable
decision append-only
evidence lineage preserved
no future information
stable canonical IDs
no orphan edges
no duplicate active relation
unique episode membership at decision time
truth changes require GraphTruthCommit
candidate set immutable
reward vector not scalarized
```

`propose_relation` is candidate-only. It cannot become committed truth without a
separate accepted delta and graph-truth commit. This preserves the existing
candidate-versus-authority boundary.

## Rejection contract

Each action exposes universal decode/authority failures plus action-specific
semantic failures. Universal failures include unsupported schema, malformed or
missing parameters, invalid time, absent pre-state, insufficient authority, and
invalid or missing mandatory approval. Action-specific reasons cover evidence,
proposal disposition, candidate membership, episode scope, canonical identity,
discrepancy state, active-relation duplication, region revision, graph
invariants, and unjustified abstention.

The validator maps every intrinsic validation error to a stable
`GraphDecisionRejectionReason`. The later executor must use the same vocabulary
for external-precondition failure. It must not invent local strings.

## Reward vector contract

Reward remains exactly eight named dimensions:

```text
evidence support
temporal consistency
canonical identity preservation
contradiction reduction
minimal edit cost
human acceptance
future stability
abstention correctness
```

Every dimension is independently either:

```text
pending
observed(score_micros, observed_at, evidence[])
```

Observed scores use signed fixed-point millionths in the closed range
`[-1_000_000, +1_000_000]`. Positive `minimal_edit_cost` means the action used a
smaller valid edit; it is not raw cost. Fixed point avoids float identity drift.
Delayed outcomes such as future stability remain pending until authoritative
evidence exists.

There is deliberately no scalar, total, weighting field, aggregation method, or
implicit missing-value substitution. Dataset construction serializes all eight
components. Any later scalarization must name and content-address a separate
policy identity containing weights, normalization, missing-value behavior, and
version.

## Correctness gates

The focused unit suite proves:

1. exactly eleven action contracts exist and each is complete;
2. unknown action kinds fail closed;
3. unknown payload fields fail closed;
4. accept requires evidence and human approval;
5. future evidence fails before execution;
6. authority is action-specific;
7. a valid action round-trips with its semantic kind intact;
8. reward remains an exact eight-component vector with no scalar fields;
9. reward scores are bounded deterministic fixed point.

The next cut may build an immutable decision receipt around this ontology. It
must not begin dataset construction until precondition proofs, candidate-set
identity, post-state/delta identity, and authoritative disposition are durable.
