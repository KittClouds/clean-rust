# Canonical Evaluator Throughput v2

## Outcome

Canonical link-prediction validation now evaluates the frozen Temporal R-GCN in a bounded deterministic batch instead of serially scoring and ranking one query at a time.

The real Smallpedia validation workload contains 101,243 unique queries, 162,066 filtered positives, 47,433 candidates per query, and 4,802,259,219 exact candidate scores. Restart-only evaluation fell from 49.763 seconds to a five-run p50 of 9.531 seconds and p95 of 9.577 seconds while reproducing the original score BLAKE3, every ranking metric, and the complete certificate byte-for-byte.

## Preserved authority

The cut does not alter:

- source dataset, task, model, topology, or weight identities;
- candidate order or the scorer's floating-point reduction order;
- raw score bits or their canonical little-endian BLAKE3 stream;
- official time-filter conflicts;
- optimistic/pessimistic average-rank tie semantics;
- per-positive metric accumulation order;
- test locking, one-shot claim, or failure-burn behavior;
- validation certificate construction.

The existing serial evaluator remains available. A parity test evaluates the same multi-query, multi-positive task through both surfaces and requires complete certificate equality.

## Pressure-point trace

The serial path had three independent multipliers:

1. learned scoring traversed all 47,433 candidate embeddings for every query on one thread;
2. each positive independently rescanned the complete score row, producing roughly 7.69 billion ranking comparisons;
3. each query revalidated the same canonical candidate array.

The frozen model is time-invariant and only 21,458 `(source, relation)` identities occur across 101,243 validation queries. Caching every unique 189,732-byte score row would require about 4.07 GB. A bounded 92.6 MB cache for the 512 most frequent identities avoids only 4.55% of score computation, so score-row caching was rejected as a poor memory trade.

## Bounded design

`DEFAULT_LINK_PREDICTION_QUERY_BATCH` is 64.

For each batch the evaluator:

1. materializes a fixed 12,142,848-byte row-major score arena;
2. validates canonical candidate order once;
3. scores independent rows through Rayon while retaining the original `f32x8` dot and sequential lane-sum order;
4. checks all score finiteness in parallel;
5. computes all positive ranks per query in one score-row traversal with reusable exact-sized scratch;
6. overlaps deterministic sequential BLAKE3 updates with parallel ranking;
7. accumulates rank metrics in original query and positive order.

The maximum real query has 404 positives. Optimistic counts, pessimistic counts, and rank outputs therefore require about 621 KB at batch size 64. No unbounded score matrix or cache is created.

The Temporal R-GCN scorer now has a canonical batch surface. It validates the candidate universe once and writes disjoint score rows in parallel. The structural-frequency baseline uses the same evaluator and batching contract.

## Restart-only execution surface

`temporal-rgcn-evaluator` opens only:

- the immutable external dataset manifest/mmap;
- the immutable canonical task manifest/mmap;
- the frozen Temporal R-GCN manifest/mmap weights.

It stages train-only topology, encodes the frozen model, executes validation, requires equality with the manifest's certified validation result, and emits a content-addressed evaluator report. Candle and the trainer are absent from scoring, and no retraining or baseline evaluation occurs.

## Certified performance

Compilation used `D:\phoenix-target-overgraph`; the release executable read and wrote artifacts on C:.

| Gate | Serial v1 | Throughput v2 |
| --- | ---: | ---: |
| Learned validation | 49.763 s | 9.531 s p50 |
| Learned validation p95 | not recorded | 9.577 s |
| Best of five | not recorded | 9.052 s |
| Throughput | 96.5M candidates/s | 503.8M candidates/s |
| Structural baseline | approximately 20.799 s | 6.452 s |
| Score arena | 189.7 KB serial row | 12.143 MB bounded batch |
| Restart evaluator allocation volume | not isolated | 102.479 MB |
| Restart evaluator peak working set | not isolated | 139.956-140.407 MB |

Five independent restart-only runs all produced:

- model ID `b3-261c2935b5b80b6f999f7cb065c9bd53bab6a7f8436e8a8a08bf38e9de2b7e43`;
- weight BLAKE3 `b3-f4d14dc5858e86d590fd39647018c6ee4a40c5f23662f9eb381afd30c61bfae3`;
- score BLAKE3 `b3-47405caa0aabcd06c9445f8e0ab190aac9cd7371cb95ae9029cb283b445e9e7f`;
- validation certificate `b3-84cc094b232ee3b0c645436689dd84fb3fa66c73f6b995438c0b855fa65d8519`;
- exact MRR `0.05817527887231176` and unchanged Hits@1/3/10.

The trainer-integrated final performance certificate is `b3-b4a53d10b446595cec50ea3dd0bd412156026eb83de56f0ee8bb6768eb2d3d86` under `target/graph-research-models/canonical-evaluator-throughput-v2-final`.

## Proof gates

- Serial and batched evaluator certificates are exactly equal.
- Multi-positive filtered average ranks remain exact.
- Same frozen model produces identical results across five cold processes.
- Restart-only evaluation fails on source, task, topology, model, weight, score, or certificate drift.
- Non-finite scores still fail before certificate exposure.
- Locked test claims are unchanged and remain one-shot/fail-closed.
- Fused training retains zero owner-thread epoch allocations even while Rayon workers persist.
- Full graph research and trainer suites, strict clippy, formatting, and diff checks pass.

## Remaining physics limit

The first deeper design is complete in [Exact Parallel BLAKE3 Chunk Compositor v1](exact-parallel-blake3-chunk-compositor-v1.md). It reduces the same cold-process evaluation to a five-run p50 of 5.544 seconds and p95 of 5.616 seconds while preserving the score digest and complete certificate exactly.

The next material evaluator cut is a tiled scorer that reuses candidate embeddings across query rows while proving identical `f32x8` multiplication and sequential lane-reduction order.
