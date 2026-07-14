# Exact Parallel BLAKE3 Chunk Compositor v1

## Outcome

The canonical link-prediction evaluator now hashes its certified score stream through BLAKE3's parallel tree implementation while preserving the original digest exactly.

On the real Smallpedia validation workload, five cold restart-only processes reduced evaluation from the Canonical Evaluator Throughput v2 p50 of 9.531 seconds to 5.544 seconds. The p95 is 5.616 seconds and throughput is 866.3 million candidates per second. The score BLAKE3, every rank and metric, and the complete validation certificate are unchanged.

## Exact stream contract

For every query in canonical order, the certified byte stream remains:

`observed_at:i64-le || source:u32-le || relation:u32-le || candidate_scores:[f32-le]`

The real task has 47,433 candidates, so each query contributes 189,748 bytes: a 16-byte prefix followed by 189,732 score bytes. A 64-query batch contributes exactly 12,143,872 bytes. The complete validation stream contains 19,210,656,764 bytes.

This layout is intentionally hostile to naive tree splitting. A query record ends 308 bytes past a 1,024-byte BLAKE3 chunk boundary, and a 64-query batch ends 256 bytes into a chunk. Query boundaries realign with BLAKE3 chunks only every 256 queries.

The compositor therefore does not finalize independent batch hashes or invent a custom CV merge rule. It:

1. writes each query prefix and its already-computed score row into a disjoint exact-sized arena slot in parallel;
2. emits score bits as little-endian bytes on every target;
3. rejects non-finite scores before exposing a certificate;
4. calls `Hasher::update_rayon` on each active batch;
5. retains the same incremental `Hasher` across batches so partial chunks and the global chunk counter carry forward exactly;
6. finalizes once after the final partial batch.

`update_rayon` uses BLAKE3's supported parallel tree implementation behind the ordinary incremental hasher state. The evaluator does not duplicate cryptographic tree logic or depend on unstable internal chaining-value layout.

## Bounded memory

The 12,143,872-byte hash arena is allocated once, reused for every batch, and truncated logically for the final batch. It is exact-sized from the candidate universe and query-batch contract.

Compared with v2:

- allocation count increases by one;
- allocation volume increases by exactly 12,143,872 bytes, from 102,478,852 to 114,622,724 bytes;
- five-run peak working set remains 139,964,416 to 139,976,704 bytes;
- no score cache, all-query materialization, temporary file, or mmap write is introduced.

The report schemas are advanced to `phoenix-canonical-evaluator-restart-report/v3` and `phoenix-canonical-evaluator-throughput-report/v3`. Both expose the hash arena independently from the score arena.

## Certified performance

Compilation used `D:\phoenix-target-overgraph`; the release executable consumed immutable artifacts and emitted reports on C:.

| Gate | Evaluator v2 | Compositor v1 |
| --- | ---: | ---: |
| Evaluation p50 | 9.531292 s | 5.543666 s |
| Evaluation p95 | 9.576625 s | 5.615697 s |
| Best of five | 9.052275 s | 5.436755 s |
| Candidate throughput | 503.8M/s | 866.3M/s |
| Reusable score arena | 12,142,848 bytes | 12,142,848 bytes |
| Reusable hash arena | 0 bytes | 12,143,872 bytes |
| Allocation volume | 102,478,852 bytes | 114,622,724 bytes |
| Peak working set | 139.956-140.407 MB | 139.964-139.977 MB |

The p50 cut is 41.84%, saving 3.988 seconds per complete validation.

All five runs reproduced:

- model ID `b3-261c2935b5b80b6f999f7cb065c9bd53bab6a7f8436e8a8a08bf38e9de2b7e43`;
- weight BLAKE3 `b3-f4d14dc5858e86d590fd39647018c6ee4a40c5f23662f9eb381afd30c61bfae3`;
- score BLAKE3 `b3-47405caa0aabcd06c9445f8e0ab190aac9cd7371cb95ae9029cb283b445e9e7f`;
- validation certificate `b3-84cc094b232ee3b0c645436689dd84fb3fa66c73f6b995438c0b855fa65d8519`;
- MRR `0.05817527887231176` and identical Hits@1/3/10.

The p50 restart report is `b3-5a69c74d37d6004cf3d77fef6ae4b65ca116caaeb67f39f4bc840737e586c544` under `target/graph-research-models/exact-parallel-blake3-compositor-v1-gate-2`.

## Proof gates

- The serial evaluator and compositor produce complete certificate equality.
- A hostile-boundary test uses 1,044-byte query records and batch sizes 1, 2, 3, 7, 16, and 64; every digest and certificate matches the serial authority.
- Existing multi-positive tie, filter, locked-test, fail-closed, corruption, and non-finite-score behavior remains intact.
- All 44 graph-research tests and all 8 trainer tests pass.
- Strict Clippy passes for the changed research library and every trainer target; Rust formatting, file-size, and diff checks pass.
- The real test partition remains unclaimed and unevaluated.

## Remaining physics limit

The next cut is complete in [Exact Tiled Query/Candidate Scorer v1](exact-tiled-query-candidate-scorer-v1.md). The same validation now runs at a five-run p50 of 4.916 seconds and p95 of 4.999 seconds while preserving every score bit and the complete certificate.

Further work requires stage-level cycle accounting across scoring, ranking, stream composition, and hashing. GPU execution remains gated on exact score and certificate parity, not approximate metric parity.
