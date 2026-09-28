# Phoenix manifold ANN V2

This crate owns Phoenix's metric-aware HNSW. It supports the Poincare, Lorentz,
hypersphere, hybrid-interior, and Euclidean tangent lanes already used by the
manifold system.

## Serving shape

```text
deterministic mutable builder
  -> compact FrozenHnsw
  -> immutable PHXANN2 archive
  -> verified read-only mmap slices
  -> caller-owned reusable SearchScratch
```

The hot graph uses dense `u32` slots, but identity is a separate nonzero
`StableVectorId(u64)`. Vectors are one contiguous `f32` page. The base graph is
one CSR offsets page plus one neighbors page. Upper layers use compact row
descriptors and one neighbors page. Tags and tombstones live in the fixed-size
node page.

The mmap reader validates before exposing the graph:

- magic, version, endian marker, flags, and declared file length;
- bounded counts and dimensions;
- page alignment, section element sizes, ranges, and non-overlap;
- per-section BLAKE3 hashes and the root hash;
- metric kind, metric parameters, and implementation identity;
- stable-ID uniqueness;
- finite vectors;
- canonical upper-row ownership;
- degree bounds;
- neighbor bounds, duplicates, and self-links;
- entry point and maximum-level consistency.

There is no vector reconstruction on V2 open. Search borrows typed slices from
the mmap and reuses caller-owned visited epochs, heaps, query storage, and hit
storage.

## Search features

- deterministic seeded level assignment;
- explicit stable IDs and dense slot IDs;
- deterministic batch insertion by stable ID;
- tombstone deletion;
- mutable tag masks before freeze;
- strict in-graph filters and post-filters;
- exact metric reranking after monotone traversal;
- allocation-reusable query scratch;
- compact immutable archives;
- fail-closed metric and corruption checks.

## DiskANN boundary

The V2 archive is deliberately **DiskANN-ready**, not falsely described as a
complete DiskANN implementation.

Already present:

- page-aligned immutable sections;
- stable external IDs;
- full-precision vector pages;
- one base-layer CSR graph suitable for graph-page conversion;
- filter tags and tombstones;
- deterministic, hash-bound generation.

Still required for an actual DiskANN serving lane:

- Vamana construction and robust prune;
- product-quantized or binary-quantized in-memory navigation codes;
- fixed-size SSD graph pages;
- asynchronous beam I/O and a bounded page cache;
- recall/latency qualification against exact search.

`DiskAnnReadiness` reports those latter capabilities as false.
`DiskAnnSourceView` exposes the verified full-precision vector page, stable
identity and filter metadata, tombstones, and base CSR without allocating or
copying. A later Vamana builder can consume that view and publish a versioned
DiskANN archive or sidecar without changing the manifold metric contract. It
must not relabel the HNSW base CSR as a Vamana graph.

## Legacy boundary

`PackedHnswGraph` remains only for the existing Overgraph cache adapter.
`HyperbolicDiskHnsw::open` accepts V2 only. The host-sized V1 format requires
the explicitly named `open_legacy` path and is converted to an owned validated
graph; it can never silently become production mmap authority.
