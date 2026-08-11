# Phoenix TurboQuant experiment

This standalone crate tests whether TurboQuant-style storage and candidate
generation fit Phoenix's local, immutable embedding pages. It does not depend
on `turbovec`, does not write to a Phoenix store, and is not wired into the app.

The experiment consumes a verified `phoenix-memory-embeddings` `.phxe1` file
and publishes a new, authority-bound `.phxq1` sidecar. The sidecar is opened
read-only with `memmap2`; its header, section layout, authority, quantizer
contract, IDs, scales, padding, and BLAKE3 page hashes are verified before any
borrowed view or search is exposed.

## Implemented slice

- deterministic two-round permutation, sign, and block Walsh-Hadamard rotation;
- clean-room Lloyd-Max codebooks for the high-dimensional normal approximation;
- parallel 2-bit and 4-bit encode with block-of-eight transposed storage;
- one f32 length-renormalization scalar per vector;
- atomic create-new publishing and zero-copy mmap reads;
- independent 2-bit and 4-bit AVX2 nibble-shuffle kernels;
- compact u8 query LUTs, u16 accumulation, and scratch-buffer reuse;
- measured serial/Rayon crossover policy and per-chunk fixed top-64 reduction;
- bounded 1/4/8-query packed-block reuse with separate 2-bit and 4-bit AVX2 kernels;
- exact cache-block top-64 reduction for the qualified single-query latency route;
- phase telemetry for rotation, LUT construction, scan, scale, top-k, and orchestration;
- zero warmed-path heap allocations for serial and Rayon search;
- exact AVX2 reranking over a fixed quantized candidate set with reusable scratch;
- a frozen, hash-bound multi-dataset corpus/query regression gate;
- exact AVX2 f32 baseline, quality checks, Criterion benchmarks, and projections.

This is closest to the paper's MSE TurboQuant path plus practical ideas from
the independent `turbovec` implementation. It is not the paper's
inner-product-optimal `TurboQuant_prod`: that construction spends one bit on a
QJL-encoded residual and stores the residual norm. The per-vector scale here is
the repository's RaBitQ-style correction, not Algorithm 2 from the paper.

The upstream repository still goes materially further with 32-vector blocking
and AVX-512 `vpermb`/VNNI kernels. This spike now has bounded AVX2 multi-query
reuse, but does not claim the upstream layout or AVX-512 machinery.

## Verification

Use a dedicated target directory on `D:`:

```powershell
$env:CARGO_TARGET_DIR = 'D:\phoenix-target-turboquant'
cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo test --release
cargo bench --bench search
cargo build --release --bin proof
cargo build --release --features frozen-gate --bin frozen_gate
```

The proof binary requires a fresh output directory:

```powershell
proof.exe `
  'D:\phoenix-memory-embedding-proof\embeddinggemma-pages-v1.phxe1' `
  'D:\phoenix-turboquant-proof'
```

It measures the real Phoenix rows, creates deterministic cohorts through 100K
in memory, writes only experiment sidecars, and labels 1M values as arithmetic
least-squares projections. See [PROOF-2026-08-10.md](PROOF-2026-08-10.md) and
[OPTIMIZATION-2026-08-10.md](OPTIMIZATION-2026-08-10.md) for the receipts and
limits.

The representative benchmark gate consumes the frozen Phoenix QPS review
bundle, constructs a proper V3 generation and embedding sidecar, embeds its
queries with the same model, scans quantized top-64, exactly reranks top-10,
and records aggregate and per-dataset regressions:

```powershell
frozen_gate.exe `
  'C:\benchmarks\phoenix-qps-v3-20260804\semantic-review-bundles-confirmation-v1-1751.json' `
  'D:\phoenix-turboquant-gate\benchmark-frozen-v1'
```

The embedding qualification harness is deliberately feature-gated so kernel
and profiler builds do not compile ONNX Runtime, tokenizers, or the Phoenix
chunker graph:

```powershell
cargo build --release --features embedding-qualification --bin embed_qualification
```

See [FROZEN-GATE-2026-08-10.md](FROZEN-GATE-2026-08-10.md) for the immutable
artifact hashes, measured recall and latency, thresholds, and remaining gate.
See [EMBEDDING-QUALIFICATION-2026-08-11.md](EMBEDDING-QUALIFICATION-2026-08-11.md)
for the corrected Gemma/Jina runner diagnosis and the qualified length-aware
batching results.
See [PHYSICS-OPTIMIZATION-2026-08-11.md](PHYSICS-OPTIMIZATION-2026-08-11.md)
for the paired-block 4-bit kernel, 2-bit crossover correction, rejected fused
top-k experiment, clean-build reduction, and bounded 1M projections.
See [THROUGHPUT-2026-08-11.md](THROUGHPUT-2026-08-11.md) for the fixed-work
concurrency matrix, repeat-run QPS/tail-latency envelope, and the explicit
latency/balanced/maximum-throughput scheduling policy.
See [PACKED-BATCH-2026-08-11.md](PACKED-BATCH-2026-08-11.md) for the promoted
100K-row packed-block multi-query kernel, the rejected 16K route, and the
repeat-run throughput and allocation gates.
See [BLOCK-LOCAL-TOPK-2026-08-11.md](BLOCK-LOCAL-TOPK-2026-08-11.md) for the
cache-block/local-K sweep, phase attribution, narrow latency-route promotion,
and the rejected batch-4/8 score-slab deletion.

## Current decision

The storage case is already strong. At dimension 768, measured `.phxq1`
artifacts are about 15.05x smaller than raw f32 vectors at 2-bit and 7.75x
smaller at 4-bit while retaining exact top-1 in the quantized top-64 for all
measured projected queries.

The serving case is now performance-positive in the isolated experiment. At
100K x 768, end-to-end auto search measured 1.218 ms at 2-bit and 1.782 ms at
4-bit versus 14.7-17.7 ms for serial exact f32. A worker-matched phase run put
8-worker 2-bit at 0.553 ms versus 10.479 ms exact, and 8-worker 4-bit at
0.966 ms.

The representative reviewed-benchmark lane now passes at 5,037 unique corpus
rows and 1,751 queries across LoCoMo, NFCorpus, and SciFact. Exact reranking of
quantized top-64 retained exact top-1 for every query. Two-bit top-10 recall@64
was 99.9943%; four-bit was 100%. Candidate generation plus exact reranking was
faster than exact full-corpus scan at p95 for both formats.

That is still not authorization to wire Phoenix. The audited Phoenix stores
contain zero production query-log rows and no raw production query trace. The
reviewed workload is benchmark traffic, its Phase 5 readiness receipt is
false, and the frozen gate therefore fails closed with
`blocked_missing_production_query_traffic`. Integration remains gated on a
hash-bound production query trace, the same regression suite over that trace,
and a production-lifetime sidecar policy.

Embedding construction and TurboQuant retrieval are separate gates. The
original 56-minute cold Gemma materialization used unbucketed full benchmark
documents and is not a Phoenix runner-regression baseline. A follow-up
qualification using the real Phoenix 1,840/256 chunker measured 1.50x faster
Gemma document embedding and 1.44x faster Jina document embedding with
length-aware batches while preserving canonical output order.

## References

- [TurboQuant paper](https://arxiv.org/abs/2504.19874)
- [Reviewed turbovec repository](https://github.com/RyanCodrai/turbovec)
- [turbovec search implementation](https://github.com/RyanCodrai/turbovec/blob/main/turbovec/src/search.rs)
