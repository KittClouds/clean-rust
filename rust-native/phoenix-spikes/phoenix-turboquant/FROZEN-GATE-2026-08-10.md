# Frozen representative benchmark gate — 2026-08-10

## Decision

The reviewed multi-dataset benchmark lane passes for both 2-bit and 4-bit
TurboQuant artifacts. Promotion is blocked because no production query traffic
exists in the audited Phoenix stores.

Receipt disposition:

```text
blocked_missing_production_query_traffic
```

This is intentionally fail-closed. The queries are real reviewed benchmark
queries, not synthetic projections, but they are not production user traffic.

## Frozen inputs

- Review bundle: `semantic-review-bundles-confirmation-v1-1751.json`
- Bundle SHA-256: `f2fa50758475d4423db933e7fb291efaa78547441ff15ed5ab10b54453b09bd4`
- Queries: 1,751
- Unique candidate rows: 5,037
- Dimension: 768
- Datasets: LoCoMo 537, NFCorpus train 775, SciFact 439
- Model: `onnx-community/embeddinggemma-300m-ONNX`, CPU execution provider
- Source Phase 5 readiness: false
- Audited production query-log rows: 0

The gate deduplicates reviewed candidate IDs, builds a proper immutable V3
graph generation, embeds every candidate and query, writes the Phoenix `.phxe1`
sidecar, writes authority-bound `.phxq1` artifacts, and evaluates every query
against an exact full-corpus f32 reference.

## Fixed thresholds

Both lanes require at least 5,000 rows, 1,000 queries, and three datasets. Both
also require deterministic repeated output and p95 candidate-plus-rerank
latency below p95 exact full-corpus latency.

The quality/storage thresholds are:

| Lane | Aggregate top-1 | Aggregate top-10 recall@64 | Every dataset top-1 | Maximum storage ratio |
| --- | ---: | ---: | ---: | ---: |
| 2-bit | 99.0% | 99.0% | 98.0% | 7.5% of f32 |
| 4-bit | 99.9% | 99.9% | 99.5% | 14.0% of f32 |

## Results

| Metric | Exact f32 | 2-bit + exact rerank | 4-bit + exact rerank |
| --- | ---: | ---: | ---: |
| Exact top-1 in top-64 | — | 100% | 100% |
| Exact top-10 recall@64 | — | 99.9943% | 100% |
| Exact top-1 after rerank | 100% | 100% | 100% |
| Exact ordered top-10 match | 100% | 99.9429% | 100% |
| Search p50 | 0.3477 ms | 0.2186 ms | 0.2465 ms |
| Search p95 | 0.4493 ms | 0.3119 ms | 0.3388 ms |
| Search p99 | 0.5012 ms | 0.4048 ms | 0.3951 ms |
| Payload bytes | 15,473,664 | 1,028,672 | 1,996,352 |
| Storage ratio | 100% | 6.6479% | 12.9016% |

The 2-bit p95 path is 1.44x faster than exact f32; the 4-bit path is 1.33x
faster. Storage is 15.04x smaller at 2-bit and 7.75x smaller at 4-bit.

Every per-dataset exact-top-1-after-rerank rate is 100%. The only 2-bit
candidate miss is one item among 17,510 exact top-10 positions: NFCorpus top-10
recall@64 is 99.9871%. Exact reranking restores the correct top-1 for all 1,751
queries.

Repeated evaluation produced identical output hashes:

- 2-bit: `5c2a9e72fcdcf67e0d64daa5b2fd16f579a20c41a69c0710fd5e41e6bf0215d4`
- 4-bit: `e84e453d1f0c1adf5930f68508699f1f0a19bfd010e216685b1026d6c85c7462`

## End-to-end phase timing

| Phase | Time |
| --- | ---: |
| Generation build | 232.94 ms |
| Model asset hashing | 2.238 s |
| Document model load | 2.255 s |
| Document embedding | 3,397.125 s |
| `.phxe1` write | 587.75 ms |
| Query model load | 2.167 s |
| Query embedding | 59.403 s |
| 2-bit encode + write | 24.62 ms |
| 4-bit encode + write | 111.82 ms |
| Full retrieval evaluation | 2.414 s |

The 3,397-second document timing is retained as historical end-to-end evidence,
but it is not a Phoenix runner-regression baseline. That run embedded complete
benchmark candidates as rows, used arbitrary identity order with batch-longest
padding, bypassed the application embedding cache, and performed a cold full
recompute. Its short-query control remained aligned with the earlier Gemma
proof at roughly 30-34 ms per row.

The corrected qualification uses the real Phoenix 1,840-character chunker with
256-character overlap and length-aware batching. See
[EMBEDDING-QUALIFICATION-2026-08-11.md](EMBEDDING-QUALIFICATION-2026-08-11.md).
Resumable shard publication remains useful for reliability, but it is separate
from runner throughput.

## Artifact receipts

Output root:

```text
D:\phoenix-turboquant-gate-20260810\benchmark-frozen-v1
```

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `frozen-gate-receipt.json` | 7,791 | `a339c7834b3aac235411abd461a92793057eb94a2e3319ddbe085b1e6a62bff2` |
| `reviewed-candidates.phxgg3` | 7,099,776 | `95f65212f2c2f57820f9ebf748c41ec136f897a4f4483d9ff229d1f4ab0ed9dc` |
| `reviewed-candidates.phxe1` | 15,957,632 | `145bc3da5d70943063e89d1426292082635dfce1ec3e9241e3fb428ae377539c` |
| `reviewed-candidates-2bit.phxq1` | 1,028,672 | `9f38daad99edcb09b0fa7ed0a07f1aa59a39f5f6c4646bcf2695cc4aee6664c0` |
| `reviewed-candidates-4bit.phxq1` | 1,996,352 | `3f476f9f58d621c545a81bfd1f9c971d22359b7959dc55e26020abd516e738ba` |

The semantic artifact hashes recorded inside the mmap headers differ from the
whole-file SHA-256 values above by design.

## Remaining promotion gate

1. Capture a consented, privacy-reviewed, hash-bound production query trace.
2. Freeze the matching production embedding corpus and exact f32 reference.
3. Run this same top-64 plus exact-top-10 rerank regression suite.
4. Require aggregate and cohort-level quality thresholds, deterministic output,
   and latency/storage budgets to pass.
5. Define sidecar generation, invalidation, crash recovery, and lifetime policy
   before any Phoenix wiring.

Until those conditions are met, `promotionAllowed` remains false.
