# Frozen Graph Decision Trajectories v1

## Status

Implemented on 2026-07-14 as the Phase 2 native training-data boundary.

This cut installs the artifact, deterministic candidate generators, candidate
and leakage certificates, mmap restart loader, and fail-closed correctness
gates. It does not manufacture examples from current Phoenix state. The Phase 0
audit found no durable native decision receipts, so a production dataset remains
locked until authoritative histories exist.

## Boundary

The implementation lives in `phoenix-graph-research` and consumes the closed
Graph Decision Ontology v1 from `phoenix-types`.

- `decision_trajectory_model.rs` owns the frozen schema and certificates.
- `decision_candidate_generator.rs` owns deterministic, label-free generation.
- `decision_trajectory_artifact.rs` validates, flattens, and installs trajectories.
- `decision_trajectory_binary.rs` owns the binary, mmap, and immutable writes.
- `decision_trajectory_tests.rs` owns the correctness gates.

The artifact cannot mutate graph truth. It references pre-state, post-state, and
delta identities already owned by authoritative Phoenix stores.

## Immutable example contract

Every source example binds:

```text
decision_id
observation_cutoff
pre_state_snapshot_id
candidate_group_id
candidate actions
selected action
evidence references
before/after delta identities
post_state_snapshot_id
eight-component reward vector
decision authority
temporal split
provenance and leakage witness
```

The selected action must be a valid executable Graph Decision Ontology action.
Every candidate is validated through the same typed grammar, except that
execution-only human approval is deliberately absent. This prevents future
winning approval from leaking into candidate generation.

Candidate and selected actions share decision identity, pre-state identity,
observation cutoff, action-specific authority, and cutoff-visible evidence.
Candidate semantic identity canonicalizes the action with `approval = null`.
The selected action must match exactly one candidate under that identity. Zero
matches is a dataset-system failure. Multiple matches is corruption.

## Ten immutable sections

The content-addressed `.fgdt` binary contains one fixed header and exactly ten
contiguous sections:

1. Decision records.
2. Pre-state and post-state identities.
3. Candidate-group offsets and generator receipts.
4. Candidate action payloads.
5. Selected-action labels.
6. Evidence references.
7. Reward vectors.
8. Before/after graph-delta references.
9. Temporal split index.
10. Provenance, candidate certificate, and leakage certificate.

The binary header stores the exact byte offset and length of every section. The
manifest repeats those ranges and adds a BLAKE3 identity per section. Cold open
requires:

```text
schema identity
binary byte length
whole-binary BLAKE3
dataset identity
section order and contiguous coverage
section offsets, lengths, and BLAKE3 identities
cross-section cardinality
every exact logical range
selected-label range membership
reward and selected-action validity
passing leakage certificate
```

The loader mmaps the binary read-only and exposes borrowed section bytes. Rich
control records are decoded only when requested. Large graph topology, state,
evidence payloads, and deltas are never embedded; only their existing content
identities are stored.

Every variable collection is flattened and addressed through `ExactRange`:

```text
offset: u64
length: u64
```

There are no sentinels, implicit tails, null-terminated scans, or guessed group
boundaries.

## Content identity and crash safety

The dataset identity is the BLAKE3 identity of the complete semantic binary.
Examples are sorted by observation cutoff and decision ID before flattening, so
input iteration order does not affect identity.

Installation order is:

```text
content-addressed binary
independent performance receipt
immutable manifest
```

Each write uses create-new temporary files, `sync_all`, and atomic rename.
Existing identical content is reused. Different bytes may never overwrite a
content-addressed path.

Candidate wall-clock latency is excluded from dataset identity. Scheduling noise
therefore cannot manufacture a different training dataset. Latency is preserved
in a separate content-addressed performance receipt bound to the semantic
dataset ID and candidate identities.

## Candidate Action Generator v1

Candidate generation receives no selected action or held-out label.

### Episode assignment generator

The episode generator accepts only episode facts available by the cutoff. It
sorts by stable episode ID, rejects duplicates and invalid or future episodes,
and emits:

```text
all active scope-compatible episodes
temporal-plausibility tags
same-entity tags
related-entity tags
difficult near-neighbor tags
one explicit create-episode action
one explicit abstain action
```

A candidate can retain multiple source tags. A difficult same-entity episode is
therefore counted in both relevant hard-negative classes.

### General graph-decision generator

The general generator covers the other ontology tasks. Its input contains typed
alternatives and one or more closed source classes:

```text
same-relation hard negative
evidence-confusable alternative
temporally plausible incorrect action
structurally valid semantic negative
minimal-edit repair alternative
```

It validates candidate shape, rejects invalid alternatives, canonicalizes and
sorts by action identity, removes duplicates, and hashes the ordered result. Its
request type has no selected-label field.

### Candidate certificate

The semantic certificate preserves:

```text
generator identity and version
generator input identity
candidate identity
candidate count distribution: min, p50, p95, max
hard-negative composition
invalid candidates rejected
deterministic materialization allocation volume
all candidate-group identities
correct-action coverage
```

Percentiles use nearest-rank semantics. Correct-action coverage must be exactly
10,000 basis points for installation. The separate performance certificate
preserves measured generation latency without contaminating dataset identity.

## Leakage tribunal

Installation fails if any example or aggregate certificate reports:

```text
evidence created after observation cutoff
pre-state facts newer than observation cutoff
post-decision edges in pre-state topology
identical decision fingerprints across splits
future episode membership exposed through features
validation or test facts in training topology
outcomes used as inputs
candidate generation influenced by held-out labels
missing correct action from its candidate group
```

The temporal split index is not merely a label column. Installation requires all
three partitions and strict non-overlap:

```text
max(train cutoff) < min(validation cutoff)
max(validation cutoff) < min(test cutoff)
```

Decision IDs and candidate-group IDs must be globally unique. Decision
fingerprints may not repeat within a split and may never cross splits.

## Reward handling

The artifact embeds the exact Graph Decision Reward Vector v1. It never adds a
scalar, weighting, total, missing-value substitution, or training-time
normalization. Delayed outcomes may remain pending. Any future scalar policy
must be a separate, content-addressed policy identity.

## Verification gates

The focused suite proves:

1. Episode generation is deterministic and includes attach, create, and abstain.
2. Invalid future episode candidates are rejected and counted.
3. General candidates are grammar-validated, deduplicated, and sorted.
4. Input example order does not affect semantic dataset identity.
5. All ten sections reopen from mmap with exact ranges and identities.
6. Correct-action coverage is exact.
7. Timing changes only the performance receipt, not the dataset.
8. Every leakage class fails installation.
9. Cross-split fingerprints fail installation.
10. Missing correct candidates fail as data-system errors.
11. Binary corruption fails before section access.

The next authority-facing cut should produce immutable Phoenix Native Decision
Receipts that can populate this artifact without inferred labels. Dataset
construction remains locked until those receipts bind pre-state, candidate-set
identity, selected action, post-state delta, and authority.
