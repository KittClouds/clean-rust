# Exact block-local top-k cut — 2026-08-11

## Decision

Promote exact block-local reduction only for the qualified lowest-latency route:

- 100K or more rows and at least 16 logical threads;
- 2-bit: batch 1, 1,024-row score block, local-K 64;
- 4-bit: batch 1, 2,048-row score block, local-K 64.

Keep the existing corpus-score-slab batch kernel for `Balanced` and
`MaximumThroughput`. Keep the independent path below 100K rows. The artifact
format and persisted bytes are unchanged.

## Exactness argument and implementation

For global top-64, every globally retained row must be in its block's local
top-64. If 64 rows in the same block rank above it, it cannot be global top-64.
The implementation therefore remains exact:

```text
packed artifact blocks
  -> branch-poor SIMD decode/accumulate
  -> 4-8 KB cache-block score scratch
  -> fixed [candidate; 128] selector outside the SIMD loop
  -> compact local candidates
  -> deterministic fixed global top-64 merge
```

The SIMD inner loops were not fused with selection. Candidate comparison uses
score total ordering followed by canonical lower corpus row, matching the
existing search contract. `BlockHit` is eight bytes (`f32` score plus `u32`
row). All score, selector, merge, and output memory is reused after warm-up.

## Sweep

The fixed-work profiler covered:

- 256, 512, 1,024, 2,048, and 4,096 score rows;
- local-K 64, 72, 96, and 128;
- batch sizes 1, 4, and 8;
- 16,384 and 100,000 rows;
- independent 2-bit and 4-bit artifacts;
- 512 queries per configuration, 16 deterministic variants, top-64;
- QPS and batch-service p50/p95/p99;
- modeled score-slab, hot-scratch, and local-publication bytes;
- separately instrumented preparation, decode work, selection work, parallel
  wall time, and global merge/materialization.

Local-K 64 was the stable winner. Larger local sets remain exact but usually
increase selector work and candidate publication. Occasional isolated wins at
72 did not repeat; 96 and 128 were consistently unattractive.

## Promoted 100K latency routes

Every paired 2-bit run at 1,024/64 beat its same-run slab baseline in both QPS
and p95. Across five runs, paired QPS improvement ranged from 1.6% to 9.2%
(median 2.3%) and p95 changed from -0.3% to -11.3% (median -5.3%).

The 4-bit 2,048/64 route improved p95 in all four paired runs by 6.4% to 23.7%
(median 8.8%). QPS was effectively neutral to modestly positive: one -0.6%
run and three gains, with a paired median near +3.0%. Lowest-latency policy
therefore promotes it for its repeatable tail result, not a throughput claim.

Instrumented representative calls:

| Format/config | Hot score scratch | Local publication | Prep | Parallel score+select wall | Summed decode work | Summed selection work | Merge/materialize | Total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2-bit 1024/64 | 4 KB | 49 KB | 0.044 ms | 0.546 ms | 4.604 ms | 1.694 ms | 0.048 ms | 0.641 ms |
| 4-bit 2048/64 | 8 KB | 24.5 KB | 0.101 ms | 0.861 ms | 8.731 ms | 1.295 ms | 0.036 ms | 1.001 ms |

Decode and selection work are sums across parallel chunks; wall and total are
critical-path measurements.

## Rejected batch-4/8 route

The 3.2 MB batch-8 corpus score slab was not the dominant villain. At 100K,
1,024/64 replaces it with 32 KB of hot score scratch and about 392 KB of compact
local-candidate publication, yet 2-bit batch-8 was 17-23% slower in three paired
runs. Four-bit was unstable and had a negative paired median, so it also fails
promotion.

The phase specimen explains the loss:

| Batch-8 format | Decode work | Local selection work | Global merge | Total block-local call |
| --- | ---: | ---: | ---: | ---: |
| 2-bit | 30.055 ms | 13.539 ms | 0.294 ms | 3.735 ms |
| 4-bit | 59.438 ms | 13.235 ms | 0.295 ms | 5.890 ms |

Every cache block must refill eight local top-64 selectors. The repeated
selection and publication outweigh eliminated slab traffic. Increasing the
block to 2,048/4,096 reduces refills but also reduces parallel granularity and
enlarges the working scratch; neither crossed the existing batch path.

At 16K, dispatch remains unchanged even where single-query block-local QPS was
occasionally positive. The existing independent path consumes fewer workers,
and the block-local p95 result was not uniformly better. This preserves the
small-cohort fail-closed policy.

## Promotion gates

- quantized candidate ordering and scores exactly match corpus-slab batching;
- exact rerank output exactly matches over those candidates;
- scalar, AVX2, corpus-batch, and block-local paths have parity;
- deterministic all-tie corpus returns canonical rows 0 through 63;
- partial tail blocks are covered at 257 rows;
- empty, oversized, and malformed batch/config shapes fail closed;
- warmed 2-bit and 4-bit block-local paths allocate zero heap objects;
- `cargo fmt --check` passed;
- `cargo clippy --all-targets -- -D warnings` passed;
- `cargo test --release` passed 20 tests, 0 failed.

Receipts under `D:\phoenix-turboquant-gate-20260811`:

| Receipt | SHA-256 |
| --- | --- |
| `block-topk-sweep-v1.json` | `89DBE3AFAE81DB4CAC6C50CBE7221B8742FDB80AD89C7C3302880D1C797DCF05` |
| `block-topk-extended-v2.json` | `E50E271FB5467FEC916F64E34A370ACE39B212017CBC24D1435CFCFC9C5AABAA` |
| `block-topk-focused-v3.json` | `67C912BC6686BD97E31F7BA285D04ED0505A8816D7DFBA429886E405209D0494` |
| `block-topk-focused-v4.json` | `FD5A3F18BA53E96B2ACCEB887F76C31D18D4C35567CF0F410B9DC92C2C754BA6` |
| `block-topk-phased-v5.json` | `D6EC0E1F3878451004B01593CE422B8EB99DF9808FBF169A5A8B9F4773271472` |
| `block-topk-batch8-phased-v6.json` | `0CE20E77F805B214510ABA0EDDF5C4ADA95AF187F699C1D1677FE5A1744069D5` |

The exhaustive profiler was compiled under
`D:\phoenix-target-turboquant-blocktopk-final-20260811`, copied byte-identical
to `C:\phoenix-turboquant-blocktopk-test-bin-20260811\block_topk_profile.exe`,
and has SHA-256
`C3A553A6FD23FFA3604A12F1FFEE467F70FB1D16EB8D862C52B35F4AB98AF328`.

## Next frontier

Do not alter the artifact format from this result. The next meaningful
execution experiment would replace heap-style local insertion with a cheaper
selection network or thresholded partial partition while keeping selection
outside SIMD. It must first beat the existing slab path for batch-4/8; otherwise
the current three-way dispatch is the end of this branch.
