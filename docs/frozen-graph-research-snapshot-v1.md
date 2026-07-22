# Frozen Graph Research Snapshot v1

## Purpose

`phoenix-frozen-graph-research/v1` is the immutable boundary between Phoenix graph truth and graph-learning experiments. It freezes exactly what was knowable at a declared time without making Atlas projections, unresolved candidates, or future outcomes authoritative.

The contract is a dataset/export layer, not a trainer and not a graph mutation path.

## Authority inputs

The store-backed export entrypoint loads:

- one native kernel checkpoint;
- the graph-truth commit lineage;
- durable graph proposal receipts and their projected outcomes;
- optionally, the document compiler hyperedge summary and its observation time.

Atlas packets are intentionally excluded as training authority. They remain rendering and inspection projections.

Kernel asserted edges remain asserted. Kernel candidate edges remain candidate. Vertices explicitly classified as candidates remain candidate. Document compiler hyperedges and synthetic targets always enter the research artifact as candidate incidence, regardless of review state.

## Temporal leakage contract

Every exported node and edge carries `availableAtMs`. Every proposal carries both `observedAtMs` and `labelAvailableAtMs`.

V1 supports chronological train, validation, and test boundaries only. It does not implement random edge splitting.

A proposal is assigned using the later of observation time and label-availability time. Consequently, a proposal observed in the training window but committed, retracted, or still censored after that window cannot leak its later label into training.

`uncommitted` is a distinct censored outcome. It is not serialized as a negative label.

Any graph row timestamped after the requested freeze time fails the entire export. Missing checkpoints, invalid split boundaries, unknown edge endpoints, duplicate identifiers, and invalid proposal histories also fail closed.

## Hypergraph representation

N-ary situations are represented as incidence, not pairwise clique expansion:

- one candidate hyperedge node;
- one incidence record per typed semantic role;
- the participant node ordinal;
- role name, resolution state, and chronological split.

Missing or unresolved participants become candidate target nodes. Freezing cannot create asserted graph truth.

## Artifact layout

Each dataset produces two immutable files:

- `<dataset-id>.manifest.json`
- `<dataset-id>.fgr`

The dataset id is BLAKE3-addressed over canonical ordered content. The manifest records the binary BLAKE3 digest, checkpoint identity and generation, freeze time, split policy, byte length, and exact table counts.

The `.fgr` artifact contains fixed-width, little-endian tables for:

- nodes;
- typed edges;
- hyperedge incidence;
- proposal features and outcomes;
- one deduplicated UTF-8 string arena.

Records use byte-aligned integer fields and are exposed as borrowed `zerocopy` slices over one read-only `memmap2` mapping. Opening validates the manifest, byte length, BLAKE3 digest, binary version, table bounds, and table counts before returning a view.

Writes use create-new temporary files, `sync_all`, and rename. Existing content-addressed artifacts are never overwritten.

## Research use

V1 is sufficient for deterministic tensorization and baseline construction. A downstream experiment must still record:

- which node and edge kinds were selected;
- feature provenance and model identities;
- type-constrained negative sampling policy;
- seed and training configuration;
- metrics and calibration;
- the exact dataset id.

Manifold coordinates or embeddings computed using validation/test topology must not be introduced as training features. That protection belongs in the next tensorization ticket, where each feature column will require its own availability and derivation certificate.

## Native entrypoints

Low-level callers use `freeze_graph_research_snapshot` followed by `FrozenGraphResearchBundle::write`.

Production callers should use `GraphStageApi::freeze_research_snapshot`, which loads checkpoint, commit, and proposal history from one store before freezing. This avoids mixing generations assembled by unrelated callers.
