# Graph Database Model Audit Guardrail

Status: required pre-work note
Date: 2026-06-14

## Why This Exists

Phoenix graph work must not reintroduce the giant JSON snapshot pattern.

The point of the recent OverGraph and compiler work was to stop carrying a large
serialized graph document through every boundary. New graph capabilities must
respect the database/read-model architecture instead of rebuilding a snapshot bus
under a new name.

The regression pattern to avoid:

- Primary snapshot grows into the transport format.
- Durable graph data is duplicated in both a snapshot and a sidecar.
- UI waits for diagnostic or staged packets before receiving usable state.
- Postprocess spends seconds serializing, compressing, storing, reading, and
  decoding data that should already live in the graph database or compact sidecars.
- Fewer rendered edges still perform worse because the system moved too much data
  through the wrong boundary.

Recent bad receipt shape:

- Primary payload around 4.2M compressed chars / 37.8M raw chars.
- Transport around 6.3s.
- Snapshot persist and serialize around 1.7s.
- Staged native scene packet around 2.3s on the critical path.
- Top payload offenders: graph model v2, embedding targets, semantic candidate
  summary, embedding graph postprocess.

That is not Phoenix standard. It means the database model was bypassed.

## Required Rule

Before adding or changing graph/compiler/manifold data, first audit the database
model and read-model boundary.

No new field, sidecar, manifest, canvas packet, or compiler output may become a
large durable JSON payload unless the audit proves it is the correct storage
shape.

## OverGraph Contract To Respect

Reference: https://overgraph.io/api-reference.md

OverGraph already provides the system surfaces we should lean on:

- Node and edge records with labels, properties, weights, validity windows, and
  provenance-friendly property payloads.
- `graph_patch` and explicit write transactions for atomic mutations.
- `batch_upsert_nodes` and `batch_upsert_edges` for normal bulk writes.
- Binary batch ingestion for high-throughput connector paths.
- Schema management for node and edge labels.
- Property indexes and range queries for targeted read models.
- Graph row and graph pipeline queries for shaped UI reads.
- Pagination for large result sets.
- Traversal, neighbors, subgraph extraction, and shortest paths for local graph
  views.
- Vector search for semantic coordinates and retrieval overlays.
- Stats, manifest, sync, flush, compact, and scrub for health and diagnostics.

If a Phoenix feature is graph-shaped, it should usually be graph data in
OverGraph, not a repeatedly transported snapshot object.

## Pre-Work Audit Checklist

Every graph-system change must answer these before implementation:

1. What is the canonical durable home?
   - OverGraph node records?
   - OverGraph edge records?
   - OverGraph vector index?
   - A compact scoped document sidecar?
   - In-memory/read-model only?

2. What is the lifecycle state?
   - proposed
   - accepted
   - rejected
   - muted
   - promoted_to_anchor
   - compiled_to_graph
   - ledger_only

3. Is this topology or read-model data?
   - Topology belongs in graph commits with receipts.
   - Review queues belong in compact ledgers.
   - Renderer geometry belongs in transient scene packets.
   - Diagnostics belong in receipts, not required UI payloads.

4. What is the smallest UI read?
   - Can the UI query rows by label, edge label, property, scope, or page?
   - Can it load a compact scene packet instead of a full snapshot?
   - Can it request details only after selection?

5. What is the mutation route?
   - Use graph patches or write transactions for graph mutations.
   - Use the operator mutation journal for operator-driven review actions.
   - Do not overload scan/postprocess deltas for review mutations.

6. What is the transport budget?
   - Hot UI path should avoid multi-megabyte JSON payloads.
   - Postprocess should publish usable UI state before optional diagnostics.
   - Any staged benchmark must be outside the critical path.

7. What is duplicated?
   - If data is written to an OverGraph sidecar, it should not also live in the
     primary snapshot.
   - If a read model can be rebuilt from compiler output, do not persist both
     unless reload requires it and the size is justified.

8. What are the receipts?
   - Persist counts, timings, IDs, and health summaries.
   - Do not persist full derived rows only to explain counts.
   - Every count shown in the UI must be resolvable through a query or compact
     ledger, not by hauling the whole graph.

## Forbidden Patterns

- Adding a large array to `GraphRebuildSnapshot` because it is convenient.
- Persisting the same graph data in both primary snapshot and sidecar.
- Making the UI wait for a diagnostic scene packet before signal commit.
- Treating JSON compression as a solution to the wrong data boundary.
- Rebuilding all model vectors or all scene geometry when only a small inventory
  slice changed.
- Using compatibility snapshots as the production graph transport.
- Runtime A/B selection between competing graph inventories, vector stores,
  manifold geometries, or renderers.
- Bypassing registry IDs with compiler-local entity or anchor identities.

## Preferred Patterns

- Durable graph facts: OverGraph nodes/edges with labels, properties, provenance,
  and receipts.
- Registered entities: the entity registry remains the only entity identity and
  anchor authority. Compiler mentions resolve into registry IDs; they never
  create a parallel anchor namespace.
- Reviewable machine output: compact ledger sidecars keyed by stable IDs.
- Manifold inventory: extend the existing `embeddingTargets` contract with new
  accepted semantic object kinds. Do not create a second projection manifest.
- Vectors: use the established model-vector path and cache for admitted embedding
  targets. Do not add a second vector store or canvas-only coordinate cache.
- Canvas: paged or compact scene packets generated from graph/read-model queries.
- Details: lazy query after selection.
- Diagnostics: receipts and optional benchmarks, never critical path.

## Single-Authority Map

Phoenix has one path for each concern:

- Entity identity and user anchors: registry plus accepted anchor records.
- Document structure and review state: document sidecar and operator journal.
- Semantic compilation: Rust compiler/read model, with TypeScript limited to
  planning and compatibility decoding.
- Durable topology: OverGraph transactions and reversible receipts.
- Manifold membership: admitted `embeddingTargets`.
- Manifold coordinates: the established Hybrid, Hopf, Caps, Product, and
  Siegel/Finsler adapters.
- Rendering: the standard packed node and edge buffers.
- Scene packets: transient transport and benchmarking only.

New semantic situations and role incidences must enter those contracts as normal
targets, nodes, and typed edges. They must not introduce another inventory,
coordinate generator, renderer, or fallback selection path.

## Consolidation Completed

The June 2026 split-brain projection experiment was removed rather than retained
as an alternate path.

Deleted or unwired:

- The parallel `GraphProjectionManifest` inventory.
- The second projection vector cache.
- Generic constrained geometry that bypassed manifold adapters.
- Standalone hypergraph scene, projection, and renderer modules.
- Runtime preference and fallback selection between old and new graph systems.

Retained and extended:

- Registry-backed entity and anchor identity.
- The existing `embeddingTargets` manifold inventory.
- Native model-vector records and caches.
- Existing Hybrid, Hopf, Caps, Product, and Siegel/Finsler geometry.
- Standard packed node and edge rendering.
- Rust semantic facts, situations, roles, evidence, and stable IDs.
- Operator mutation journal replay before semantic compilation.

This is a replacement rule, not an A/B rule: future graph work upgrades these
authorities in place.

## First Audit Targets After This Regression

1. Remove `graphModelV2` duplication from the primary snapshot once reload can
   hydrate it from the OverGraph sidecar or compiler output.
2. Move staged native scene packet benchmarking off the blocking postprocess
   path.
3. Re-check `embeddingTargets`, `semanticCandidateSummary`, and
   `embeddingGraphPostProcess` as durable payload offenders.
4. Ensure production manifolds use compact graph/vector read models, not
   snapshot-owned bulk data.
5. Add payload-budget tests around postprocess persistence and transport.

## Success Criteria

A graph change is acceptable only when:

- It identifies the canonical storage model before implementation.
- It keeps primary snapshots compact.
- It has a small UI read path.
- It has a queryable detail path.
- It does not duplicate large derived data across snapshot and sidecar.
- It improves or preserves postprocess latency.
- It improves or preserves graph rendering latency.

The system can be beautiful, but the database model is the skeleton. Do not
break the skeleton to hang new lights.
