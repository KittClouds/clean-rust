# Packed-block multi-query cut — 2026-08-11

## Decision

Promote the packed-block batch kernel inside a narrow measured envelope:

- rows >= 100,000;
- at least 16 logical CPU threads;
- batch 1 for lowest latency, batch 4 for balanced service, and batch 8 for
  maximum throughput;
- retain independent-query scheduling below that boundary.

This is an isolated kernel and scheduling decision, not Phoenix integration
authorization. Production still requires the frozen query-traffic and sidecar
lifecycle gates.

## What changed physically

The previous service geometry gave each query an independent corpus traversal.
The new path rotates and quantizes each query once, then processes an immutable
packed artifact block as:

```text
load 8 packed candidate bytes once
  -> extract low/high packed codes once
  -> shuffle each prepared query LUT
  -> update independent fixed accumulators
  -> apply the row scale
  -> write row-major interleaved scores
```

The 2-bit and 4-bit AVX2 loops are separate monomorphic kernels. Batch counts
1 through 8 dispatch to const-specialized implementations. A 100K-row batch-8
scan uses a 3.2 MB interleaved `f32` score slab, after which top-64 reduction is
parallel across queries. The verified mmap, codes, IDs, scales, and quantizer
contract remain unchanged.

Every lane owns its heap and output. `BatchSearchScratch` owns and reuses the
rotated-query buffer, rotation scratch, compact LUTs, score slab, and heaps.
The warmed batch path performs zero heap allocations.

## Fixed-work experiment

`batch_profile` executes 512 searches per configuration using the same 16
deterministic query variants, 768 dimensions, top-64, verified projected mmap
artifacts, and order-independent result digest as the independent-query
throughput profiler. One persistent 16-worker Rayon pool is created and warmed
outside the measured interval. Query embedding, queue wait, and exact reranking
are excluded.

Three independent runs tested batch sizes 1, 2, 4, and 8 at 16,384 and 100,000
rows for both formats.

## 100K repeat envelope

| Format / batch | QPS range | Median QPS | p95 batch-service range | Median p95 |
| --- | ---: | ---: | ---: | ---: |
| 2-bit / 1 | 1,387.1–1,478.3 | 1,466.8 | 0.832–1.093 ms | 0.860 ms |
| 2-bit / 4 | 2,390.8–2,460.1 | 2,454.4 | 1.792–1.932 ms | 1.804 ms |
| 2-bit / 8 | 2,601.4–2,650.8 | 2,634.8 | 3.288–3.585 ms | 3.405 ms |
| 4-bit / 1 | 946.0–982.6 | 968.1 | 1.211–1.301 ms | 1.235 ms |
| 4-bit / 4 | 1,430.8–1,496.2 | 1,439.3 | 2.990–3.190 ms | 3.175 ms |
| 4-bit / 8 | 1,499.1–1,540.7 | 1,529.8 | 5.533–5.847 ms | 5.764 ms |

Against the prior three-run scheduling medians:

| Objective | Prior geometry | Packed geometry | QPS change | p95 change |
| --- | ---: | ---: | ---: | ---: |
| 2-bit balanced | 4 x 4 independent | batch 4 x 16 workers | +17.9% | -28.2% |
| 2-bit maximum | 16 x 1 independent | batch 8 x 16 workers | +5.4% | -59.8% |
| 4-bit balanced | 4 x 4 independent | batch 4 x 16 workers | +9.4% | -25.2% |
| 4-bit maximum | 8 x 2 independent | batch 8 x 16 workers | +9.9% | -27.1% |

Batch-1 also exposes a useful 2-bit improvement: fusing row-scale application
into block output raised the lowest-latency median by about 19% versus the old
1 x 16 path. Four-bit was essentially neutral because its previous parallel
kernel already fused scale application.

## Rejected route

Packed batching is not selected at 16K rows. Batch-8 median throughput was
8,675 QPS at 2-bit and 5,544 QPS at 4-bit. The prior independent-query medians
were 12,730 and 7,020 QPS respectively, making batching about 32% and 21%
slower. The smaller corpus does not provide enough avoided memory traffic to
pay for the extra LUT loads, accumulator pressure, and interleaved reduction.

The recommendation therefore fails closed to independent scheduling below
100K rather than extrapolating an unmeasured crossover.

## Correctness and gates

- all batch sizes produced identical top-64 results to independent AVX2 search;
- all three batch receipts and all three earlier independent receipts share one
  digest per row-count/bit-width cohort;
- invalid empty, oversized, and output-mismatched batches fail closed;
- tail blocks with a non-multiple-of-eight row count have parity coverage;
- warmed 2-bit and 4-bit batch paths allocate zero heap objects;
- `cargo fmt --check` passed;
- `cargo clippy --all-targets -- -D warnings` passed;
- `cargo test --release` passed 18 tests, 0 failed.

Receipts under `D:\phoenix-turboquant-gate-20260811`:

| Receipt | SHA-256 |
| --- | --- |
| `batch-candidate-v1.json` | `4F561772933D675E4316274A87742CD99A8A5C7339A682AECF64FFD2F6E9337B` |
| `batch-candidate-v2.json` | `48186156C271045F861FFE8A4001937F9D1D85160050C31183C884D9F4A1E9A8` |
| `batch-candidate-v3.json` | `3B1CDD636315EA27554F9EDB7FAFF11CD32779C8A47D5EE8E6E74709A89BB587` |

The final profiler was compiled under
`D:\phoenix-target-turboquant-batch-final-20260811`, copied byte-identical to
`C:\phoenix-turboquant-batch-test-bin-20260811\batch_profile.exe`, and has
SHA-256 `461DC4D165D5AC1955FE030FBC1677F0A3CC9DAA61E288CFFCEE76BDBCFB60C3`.

## Remaining throughput frontier

The block-local top-k experiment has now been completed; see
`BLOCK-LOCAL-TOPK-2026-08-11.md`. It earned the single-query latency route but
was rejected for batch-4/8, where repeated selection cost more than the deleted
score-slab traffic. The remaining credible frontiers are lower-cost selection
and an AVX-512/VNNI layout on a qualified host.
