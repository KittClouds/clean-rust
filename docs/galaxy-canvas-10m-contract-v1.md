# Galaxy Canvas 10M Contract V1

Status: frozen architecture target. This document does not claim that the current renderer is compliant.

Implementation progress: the browser now has a bounded, device-class residency manager with generation cancellation, frustum/SSE planning, progressive LOD requests, double-buffer transition ownership, GPU lifecycle ports, and explicit cardinality counters. The current renderer remains connected through one full-scene compatibility tile until native spatial page transport is wired.

The target is a graph containing up to 10,000,000 authoritative nodes and 10,000,000 authoritative edges. Smooth rendering means that this corpus can be loaded, navigated, refined, and inspected through a bounded resident scene. It does not mean that every corpus element is expanded into an individual JavaScript or GPU primitive at the same time.

The executable companion is `graph-galaxy-capacity-contract.ts`. Any implementation claiming admission to the 10M lane must satisfy that contract and the verification gates below.

## Cardinalities

- **Corpus**: every authoritative graph identity available to native storage and queries.
- **Resident**: compact pages currently held by the browser or GPU.
- **Visible**: resident elements surviving viewport and screen-space selection.
- **Detail**: visible or explicitly selected identities requiring labels, descriptions, provenance, or rich metadata.

Corpus cardinality may influence native storage, indexing, offline packing, and background page construction. It must not directly determine interactive main-thread, GPU, picking, focus, or camera work.

## Frozen invariants

### G10M-1: Capacity

The architecture must admit at least 10,000,000 nodes and 10,000,000 edges in the authoritative corpus. A smaller test fixture or device residency budget does not weaken this logical capacity.

### G10M-2: Bounded interactive work

Main-thread, GPU, and interaction work must be bounded by resident or visible cardinality. Hover, selection, focus, camera movement, manifold switching, and picking must not scan the complete corpus.

Background native work may scan a corpus when building an immutable generation or index. That work is not permitted on the interactive frame path.

### G10M-3: Reversible aggregation

Every aggregate, supernode, density cell, or bundled edge must resolve to exact authoritative identities. Approximate visual placement is allowed; approximate identity ownership is not.

Aggregation receipts must include the graph generation and enough page or membership identity to reproduce the exact member set.

### G10M-4: Shared manifold substrate

Manifold switching must reuse identity and topology pages. A manifold may provide different coordinates, spatial indexes, LOD summaries, or visual attributes, but it must not clone or redefine graph identity and topology.

### G10M-5: No corpus scans during interaction

Hover, selection, camera movement, focus, lasso, and path inspection must operate on visible/resident GPU data or bounded native queries. An unchanged viewport must not become slower merely because the corpus grows.

### G10M-6: Detail on demand

Labels, descriptions, source excerpts, provenance chains, and other rich metadata may be fetched only for visible detail or explicit selection. Bulk numeric scene pages must not carry corpus-wide rich strings.

### G10M-7: LOD is presentation only

LOD may cluster, bundle, cull, quantize, or progressively refine presentation. It may not add, delete, accept, reject, promote, or otherwise mutate committed graph topology or authority.

Only the graph compilation and persistence authority may commit topology. The canvas consumes that truth and emits bounded interaction intents.

## Admission certificate

An implementation may enter the 10M lane only when it can issue a `phoenix-galaxy-capacity-contract/v1` certificate with:

- Node and edge capacity at or above 10,000,000 each.
- Main-thread, GPU, and interaction basis set to `resident-or-visible`.
- Full-corpus interactive scans prohibited.
- Exact reversible aggregate membership.
- Shared identity and topology pages across manifolds.
- Detail fetch scope limited to visible detail or selection.
- LOD authority limited to presentation with no topology commit capability.

The target constant is not itself an implementation certificate. Runtime and native boundaries must eventually publish independently measured evidence.

## Required verification gates

1. Contract unit tests reject every weakened invariant independently.
2. Static ownership tests prove that identity/topology pages are shared across manifold views.
3. Interaction tests prove that camera, hover, focus, selection, lasso, and picking touch no corpus collection.
4. Aggregate round-trip tests resolve every sampled aggregate to exact authoritative identities and the correct graph generation.
5. Authority tests prove that LOD and canvas operations produce no topology writes.
6. Detail tests prove that bulk scene pages contain no labels, descriptions, or source payloads.
7. Scaling tests increase corpus cardinality while holding the viewport constant and verify bounded browser/GPU memory and interaction work.

The 10M fixture itself is not required. Record-size accounting, complexity gates, modest geometric scaling runs, and invariant instrumentation provide the proof until a full-scale run becomes practical.

## Explicitly rejected designs

- Raising the existing native packet limit while preserving whole-scene materialization.
- Shipping bulk geometry through JSON or base64.
- Retaining one JavaScript object, string label, map entry, or adjacency array per corpus element.
- Rebuilding screen-picking bins by scanning the complete corpus.
- CPU tessellation of every corpus edge.
- A separate complete identity/topology scene for each manifold.
- LOD summaries that become committed graph truth.

## Change control

V1 may be strengthened without changing its schema. Weakening capacity, exact identity, shared topology, bounded interaction, detail-on-demand, or presentation-only LOD requires a new schema version and an explicit architecture review.
