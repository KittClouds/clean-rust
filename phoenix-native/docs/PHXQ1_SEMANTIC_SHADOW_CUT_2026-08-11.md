# PHXQ1 semantic shadow cut — 2026-08-11

## Outcome

Phoenix now has a fail-closed, non-authoritative semantic shadow lane for a
generation-bound `.phxe1` embedding artifact and `.phxq1` TurboQuant sidecar.
The feature is disabled by default and cannot alter authoritative recall.

This cut proves the runtime boundary and comparison machinery. It does not
activate a production Gemma/Jina query embedder, publish production query
traffic, or promote semantic results into `ContextPacket.items`.

## Runtime contract

`ResidentSemanticIndex` retains both verified memory maps:

```text
verified .phxe1 exact embedding pages
              +
verified .phxq1 TurboQuant sidecar
              |
              v
generation- and authority-bound resident index
```

Installation rejects a sidecar when its generation, artifact authority,
dimension, row count, or ordered subject identities do not match the embedding
artifact. A publication change makes the prior resident pair stale. Missing,
building, stale, invalid, unqualified, queue-full, and failed states are
explicit and never change authoritative results.

Semantic comparison identity is derived from `EmbeddingRowV1` provenance:
`source_id`, source range, ordinal, and `content_hash`. It does not assume that
the embedding `subject_id` equals lexical `content_id`.

## Critical-path boundary

The coordinator sends the authoritative recall reply before it hashes or
submits semantic work. Semantic work runs on one bounded worker with reusable
query, search, exact-reference, and result scratch. Queue saturation drops
shadow work instead of applying backpressure.

The immediate packet receipt is `Deferred`; the runtime snapshot records the
actual submission and completed-evaluation receipts. Query and embedding
identifiers are keyed hashes, and debug output redacts the privacy key.

## Measured authoritative latency

An initial implementation submitted the shadow job before returning recall and
regressed the 2,000-call profile from 4.6 us to 19.5 us p50. That implementation
was rejected.

After moving submission behind the authoritative reply, five counterbalanced
2,000-call release profiles produced:

| Run | Disabled p50/p95/p99 us | Enabled p50/p95/p99 us | Shadow result |
| --- | --- | --- |
| 1 | 4.1 / 21.9 / 29.0 | 3.8 / 14.8 / 22.3 | complete, zero drops |
| 2 | 4.2 / 15.6 / 24.0 | 3.9 / 12.5 / 21.6 | complete, zero drops |
| 3 | 4.1 / 19.6 / 26.5 | 3.7 / 5.0 / 19.7 | complete, zero drops |
| 4 | 4.2 / 17.8 / 23.8 | 3.9 / 12.1 / 23.8 | complete, zero drops |
| 5 | 4.0 / 20.1 / 26.7 | 3.7 / 4.0 / 14.9 | complete, zero drops |

These short scheduler-sensitive profiles establish no measured authoritative
latency regression. They are not evidence that enabling shadow work improves
authoritative latency.

A final contention-free verification after all release builds measured 4.1 /
13.1 / 21.7 us disabled and 3.8 / 11.3 / 22.6 us enabled at p50 / p95 / p99.
All 2,128 submitted jobs completed, zero were dropped, and queue high-water was
12.

## Frozen receipt geometry

The first PHXQ1 production receipt contract is deliberately fixed at:

```text
quantized candidates: top 64
exact rerank:          top 10
```

Changing this geometry requires a new receipt contract so historical metrics
cannot silently change meaning.

## Verification gates

The release suite covers:

- exact preservation of authoritative items and candidates;
- exact-reference, PHXQ1-candidate, and exact-rerank receipt agreement;
- generation-bound install and stale transition;
- corrupt and mismatched sidecar rejection;
- bounded queue overload without recall backpressure;
- keyed-query privacy separation and redacted configuration diagnostics;
- zero semantic work under the default-disabled configuration.

The existing 100K TurboQuant performance receipts remain the kernel baseline.
This cut does not claim a new integrated 100K measurement because the frozen
100K projection retained `.phxq1` artifacts but not the corresponding expanded
`.phxe1` exact slab. Phoenix does not generate a redundant ~307 MB artifact just
to manufacture that number.

## Activation gate

Production activation still requires all of the following:

1. an optimized Phoenix Gemma/Jina `SemanticQueryEmbedder` adapter;
2. crash-safe generation and publication of the paired sidecars;
3. privacy approval for sampled production-query receipts;
4. a frozen representative corpus and real query traffic;
5. exact-rerank recall, regression, p50, p95, p99, allocation, and queue-drop
   thresholds;
6. explicit promotion approval. Until then, authoritative QPS remains unchanged.
