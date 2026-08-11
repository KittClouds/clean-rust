# TurboQuant saturated-throughput pass — 2026-08-11

## Outcome

The kernel had more aggregate capacity than the single-query benchmark exposed.
On the 16-logical-thread Ryzen 7 5800X3D, scheduling independent queries across
the same fixed CPU budget raised median 100K-row candidate-generation throughput:

- 2-bit: 1,231.7 QPS at the lowest-latency geometry to 2,499.1 QPS at maximum
  throughput, a 2.03x increase;
- 4-bit: 961.5 QPS to 1,392.6 QPS, a 1.45x increase.

This is a scheduling gain, not a new approximation and not a changed result set.
Every configuration in all three runs produced the same result digest for each
row-count/bit-width cohort.

## Fixed-work contract

`throughput_profile` executes 512 searches for every configuration. The work is
held constant:

- 16 deterministic normalized query variants;
- query rotation, LUT construction, full mmap artifact traversal, packed decode,
  scale correction, and fixed top-64 maintenance;
- 16,384 and 100,000 rows at 768 dimensions;
- independent 2-bit and 4-bit artifacts;
- shared verified read-only mmap index;
- one reusable `SearchScratch` and output allocation per query lane;
- persistent Rayon worker pools created and warmed before timing;
- no embedding and no exact rerank in the measured interval.

The matrix covers 15 team geometries from one serial lane through 16 serial
lanes while keeping active search workers at or below 16. Latency is measured
inside each admitted lane, so it does not include production queue wait.

## Repeat envelope at 100K rows

The table reports the minimum and maximum across three independent 512-query
runs. The median values in the outcome above are taken from the same receipts.

| Format / objective | Geometry | QPS range | p95 service latency range |
| --- | ---: | ---: | ---: |
| 2-bit lowest latency | 1 query x 16 workers | 1,224.1–1,249.5 | 0.994–1.006 ms |
| 2-bit balanced | 4 x 4 | 2,010.1–2,161.8 | 2.328–2.703 ms |
| 2-bit maximum throughput | 16 x 1 | 2,344.2–2,595.4 | 7.590–10.187 ms |
| 4-bit lowest latency | 1 x 16 | 946.0–1,032.8 | 1.160–1.266 ms |
| 4-bit balanced | 4 x 4 | 1,235.2–1,375.4 | 3.674–4.510 ms |
| 4-bit maximum-throughput median | 8 x 2 | 1,175.3–1,481.8 | 6.930–10.547 ms |

Four-bit's strict winner varied: 16 serial lanes won run 1, while eight
two-worker lanes won runs 2 and 3. The 8 x 2 recommendation therefore encodes
the highest observed median, not a universal CPU law. At 16K rows, single-query
parallelism saturates earlier: 2-bit prefers four workers and 4-bit prefers
roughly eight. Throwing 16 workers at the 16K 2-bit scan is a regression.

## Implemented scheduling contract

The library now exports:

```rust
recommend_search_throughput(bits, rows, logical_threads, mode)
```

with three explicit modes:

- `LowestLatency`: one query lane with the measured useful scan team;
- `Balanced`: up to four lanes sharing the CPU budget evenly;
- `MaximumThroughput`: serial query lanes for 2-bit and two-worker lanes for
  4-bit.

The returned `SearchThroughputPlan` is intentionally policy only. It does not
silently create pools, queues, threads, scratch buffers, or allocations. A host
runner should build persistent teams once, bound admission to
`concurrent_queries`, and give every admitted lane exclusive scratch/output.
The caller can override the plan, and production must re-freeze it against its
own CPU and real traffic distribution.

## Verification

The post-change release gate passed:

- `cargo fmt --check`;
- `cargo clippy --all-targets -- -D warnings`;
- `cargo test --release`: 15 passed, 0 failed;
- warmed serial and Rayon search remain zero-allocation;
- scalar/AVX2 and serial/Rayon top-64 parity remain green;
- all 60 configurations per receipt were order-independent digest identical;
- all three receipts were digest identical across runs for all four cohorts.

Immutable evidence:

| Receipt | SHA-256 |
| --- | --- |
| `throughput-baseline-v1.json` | `61664519A4894A087655CB8E44A1648C0BF1402D7570E2B7477399551B55922E` |
| `throughput-baseline-v2.json` | `BA53BF99BD73CD69FDA53861B7114A4961C73F5BDD4971706AC56479314540A5` |
| `throughput-final-v3.json` | `2E53704B8275324CB8F5BB114839A7A135F1626FDEC184DF3C0FA2058A1EF011` |

The receipts live under `D:\phoenix-turboquant-gate-20260811`. The measured
artifacts are the hash-bound projected sidecars from
`D:\phoenix-turboquant-proof-20260810-optimized-topk`.

The final release profiler was compiled under
`D:\phoenix-target-turboquant-throughput-final-20260811`, copied byte-identical
to `C:\phoenix-turboquant-throughput-test-bin-20260811\throughput_profile.exe`,
and has SHA-256
`80DD0CF2B9B09BA730CA69DFB2E11ED582C51FA7C887B9A27B600A217F8F52D2`.

## What the physics says to try next

The scheduling pass is close to the limit of independent-query orchestration.
The next material kernel experiment is true multi-query reuse: transpose a
small query batch, traverse each packed corpus block once, decode once, and
update several independent accumulators. This can amortize mmap/cache-line
traffic and packed extraction across queries. It is only worth promoting if it
beats the current 4 x 4 and 16 x 1 envelopes without degrading result parity or
creating an unacceptable queueing floor.

After that, the next gates are architecture-specific AVX-512/VNNI kernels and
PGO trained on the frozen production trace. Neither should be generalized from
this AVX2 host. Phoenix integration remains separately blocked on the existing
hash-bound production-query-traffic and lifecycle gates.
