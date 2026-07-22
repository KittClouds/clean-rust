# Frozen Tensorization v1

## Purpose

`phoenix-frozen-tensorization/v1` converts exactly one Frozen Graph Research Snapshot into deterministic, framework-neutral tensor tables. It does not read mutable application state and cannot mutate graph truth.

The source dataset id is embedded in the tensor manifest and participates in the tensor BLAKE3 identity.

## Tensor surfaces

V1 emits:

- deterministic node-type ids and vocabulary;
- typed COO source, target, relation, authority, split, availability, and weight arrays;
- CSR row offsets, columns, and COO-edge backreferences;
- n-ary incidence hyperedge, participant, role-type, split, and resolution arrays;
- flattened fixed-width proposal features;
- proposal outcome, censor mask, split, observation time, label-availability time, and feature-schema ids;
- deterministic constrained corruption samples for link-prediction objectives.

Node ordinals are identical to the source research snapshot. The tensor manifest references its source dataset rather than duplicating the node string arena.

## Feature certificates

The 16 proposal feature positions are policy-specific. Semantic proposals and graph-projection proposals do not assign the same meaning to every position.

Frozen Graph Research Snapshot v1 therefore preserves a feature schema id composed from compiler id/version and policy id/version. Tensorization interns those schemas and emits 16 column certificates per schema.

V1 names the columns `policy_feature_0` through `policy_feature_15`; a consumer must resolve their meaning from the certified compiler policy. Each column is stored as `i16`, normalized by division by 1000, and certified as available at proposal observation time without using the later outcome label.

Mixing proposal rows with different feature-schema ids into one feature matrix without schema-aware handling violates the contract.

## Censoring and labels

`uncommitted` is not a negative outcome. Proposal labels therefore have a separate `proposal_label_observed` mask. Trainers must exclude unobserved labels from supervised loss unless they implement an explicit survival/censoring objective.

The proposal split was already assigned using the later of observation and label-availability time by the frozen research layer. Tensorization preserves that split exactly.

## Constrained corruptions

V1 creates tail corruptions for asserted positive edges only. These are contrastive samples, not claims that the relation is false.

A corruption candidate must:

- have the same node type as the positive target;
- be an asserted node;
- exist no later than the positive edge;
- differ from both positive endpoints;
- not exist as any asserted or candidate edge with the same source and relation.

All existing edges are excluded regardless of their later timestamp. This conservative rule avoids manufacturing a negative that becomes known positive in a later split.

Selection is deterministic. BLAKE3 chooses a start and coprime modular step within each target-type bucket, producing a complete permutation without allocating or sorting an O(N) candidate list per edge. Runtime approaches O(E times requested negatives), with bounded scans when constraints reject candidates.

## Artifact layout

Each tensorization produces:

- `<tensor-id>.tensor-manifest.json`
- `<tensor-id>.fgt`

The manifest contains source dataset identity, tensor policy, exact counts, vocabularies, feature certificates, binary byte length, and binary BLAKE3 digest.

The binary contains 27 fixed-width little-endian sections. Every section records its offset, count, and element width. A read-only `memmap2` loader validates the digest, version, section count, byte ranges, widths, and cross-table cardinalities before exposing borrowed `zerocopy` slices.

No CSR or vocabulary reconstruction occurs when opening the tensor artifact.

## Entry points

Low-level callers use `tensorize_frozen_graph` and `FrozenTensorBundle::write`.

Production callers use `GraphStageApi::freeze_research_tensors`. It loads one checkpoint, commit history, and proposal history; constructs the research snapshot and tensors in memory; then writes both immutable artifacts.

## Deliberate exclusions

V1 does not choose a learning framework, batch format, model, loss, optimizer, device, or evaluation metric. It also does not export embeddings or manifold coordinates. Those features require derivation-time certificates proving they were computed without validation/test topology.
