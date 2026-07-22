# Phoenix Native Decision/Outcome Receipt v1

## Status

The authority types, content identities, append-only Overgraph persistence,
mmap restart index, Graph API surface, outcome-lineage resolver, direct
Counterfactual Candidate Groups bridge, and the first live decision producer
are implemented.

Atlas Control operator review is the first producer. Every new native review
action now freezes its exact pre-choice row and candidate menu before applying
the journal mutation, then appends an execution observation after the durable
application receipt. No historical row was backfilled, inferred, or promoted
from the operator journal or story-continuity candidate overlay.

## Authority boundary

This cut introduces two different immutable facts.

### Decision receipt

The decision receipt is appended after candidate generation and selection but
before graph mutation. It freezes:

```text
decision and task family
scope and lineage IDs
observation and label-availability timestamps
exact pre-state snapshot identity
ordered candidate-set identity
candidate actions and semantic dispositions
chosen candidate ordinal
generator identity, input, invalid count, latency, and allocations
operator/compiler authority class
evidence available at decision time
source-to-research authority bridge
```

Every candidate action is grammar validated and must bind the same decision,
pre-state, timestamp, and authority. Approval is stripped from candidate
identity. Exactly one candidate is `chosen`; explicit no-action behavior uses a
chosen `abstain` action rather than a missing label.

### Outcome receipt

An outcome receipt is appended only after a candidate effect can be observed.
It binds:

```text
decision receipt and candidate action identity
observe, revise, or retract operation
outcome timestamp and authority
complete eight-dimensional reward vector, when it has become observable
content-addressed hard-constraint receipt
no-change or graph-mutation effect
predecessor outcome receipt
timestamped evidence anchors
```

Compiler inference is forbidden as outcome authority. Operator preference and
authoritative graph outcomes remain distinct classes. An execution observation
may be durably censored with no reward vector, but cannot enter a complete
research outcome until a later immutable revision supplies every reward
dimension. Partial vectors are never silently converted into labels.

## Explicit store bridge

Each decision receipt contains a `NativeDecisionAuthorityBridge`:

```text
source_authority_id
research_authority_id
source_state_receipt_id
bridged_at
```

This resolves the Phase 0 ambiguity where the primary desktop runtime and the
native graph research store could see different typed universes. The bridge is
mandatory even when both authority IDs name the same deployment. Its source
state receipt is content-addressed, and its timestamp cannot precede the
decision observation.

## Durable write protocol

The native graph store uses one append-only log:

```text
native-decision-receipts-v1.bin
```

Each record contains a fixed zerocopy header, record kind, exact byte lengths,
MessagePack payload, and full BLAKE3 payload digest. Append ordering is:

```text
validate semantic and content identity
verify immutable predecessor and decision bindings
truncate any incomplete crash tail
append one complete frame
sync_data
extend the in-memory index by remapping only the durable tail
```

The index retains receipt ID, decision ID, decision order, and outcome locations
per decision. Restart scans the log through mmap. A short terminal frame is
treated as an interrupted append and ignored until the next append truncates
it. Invalid magic, length, schema, payload digest, semantic content identity,
or duplicate IDs fail before any receipt is returned.

Appending the same receipt is idempotent. Reusing a receipt or decision ID for
different content fails closed.

## Outcome lineage

The first candidate outcome must be `observe`. Every later `revise` or
`retract` receipt must:

- name the current immutable terminal receipt;
- have a strictly later observation timestamp;
- bind the same decision and candidate action.

Forks, missing predecessors, parallel roots, and time reversal are rejected at
append. Dataset resolution selects the terminal receipt no later than
`frozen_at`. A terminal retraction or a candidate without an outcome keeps the
decision censored and blocks Counterfactual Candidate Groups installation.

## Graph API sequence

Decision producers use the graph-stage API in this order:

1. Persist or identify the exact decision-time source-state receipt.
2. Generate and order the complete candidate set.
3. Certify and call `record_native_decision` before applying mutation.
4. Apply the selected action through its existing authority path.
5. Persist any resulting graph-truth commit.
6. Observe candidate outcomes without using them as decision-time features.
7. Certify and call `record_native_decision_outcome` for each candidate.
8. Append later revisions or retractions as new receipts.

A decision receipt with no later effect remains evidence of recorded behavior,
not proof of graph truth. A graph commit with no decision receipt remains graph
truth, but cannot reconstruct a candidate-choice training example.

## First live producer: Atlas Control review

The desktop review path is now:

```text
read exact review row and available actions
build candidate identity without the selected label
begin_native_operator_decision_json
bind native IDs into the operator intent and application receipt
persist the mutated snapshot and journal
complete_native_operator_decision_json
```

The decision ID is deterministic, so retries cannot duplicate behavior labels.
If the process stops after application but before outcome append, snapshot load
finds the native IDs in the durable operator receipt and completes the missing
observation idempotently. Canonical GraphTruthCommit projection merges with the
operator journal; it cannot overwrite those recovery links.

The application observation records operator preference and a no-change graph
effect with a censored reward. This is deliberate: applying a UI disposition is
real behavior, but it is not fabricated evidence of future stability, temporal
correctness, or world truth.

The native census RPC reports behavior labels, operator labels, execution
outcomes, reward-complete and reward-censored outcomes, and counterfactual-ready
decisions. It is an audit surface, not a writer.

Decision-to-truth authority linking is specified in
[`phoenix-native-reward-authority-v1.md`](phoenix-native-reward-authority-v1.md).
The census additionally reports commits that carry both the native decision
receipt and its durable operator-mutation receipt. A link is necessary for
canonical outcome evidence but never sufficient for reward completion.

## Research bridge

`freeze_counterfactual_groups_from_native_receipts` joins receipts to Frozen
Graph Decision Trajectories by exact:

```text
decision ID
observation cutoff
pre-state snapshot identity
chosen candidate identity
recorded counterfactual role
```

It then resolves all seven candidate outcome lineages at the freeze cutoff and
passes their original reward and hard-constraint receipts directly into Cut 6.
The synthetic equivalence gate proves this route produces the exact same
content-addressed counterfactual dataset as the direct builder.

## No-fabrication rules

- Existing operator-journal rows are not backfilled as decisions.
- Story-continuity candidates remain compiler inference.
- Proposal receipts are not choices unless a decision receipt records them.
- Graph commits are not candidate sets.
- Unobserved alternatives remain censored.
- Later evidence may label an outcome but can never enter the pre-state.
- Retraction removes export eligibility; it does not delete history.

## Definition of complete

The receipt layer and its first real producer are infrastructure-complete when
their focused, desktop-contract, restart, and production-build tests pass.
Phoenix-native data readiness still requires live receipt accumulation followed
by a new decision-surface audit. Canonical Episode Assignment opens only after
enough complete seven-candidate decisions have all candidate outcomes, exact
pre-states, authoritative labels, and a passing temporal leakage certificate.
