# Phoenix bounded vector WebGPU kernel

This isolated crate proves vendor-neutral GPU acceleration for exact scoring
after an ANN index has already selected candidates. It does not implement
HNSW, LSH, graph traversal, candidate discovery, or topology mutation.

## Authority boundary

The caller owns the immutable vector corpus and ANN index. A request supplies:

- a resident, unit-normalized corpus and stable numeric row identities;
- one or more unit-normalized query vectors;
- CSR-style candidate offsets and candidate row identities from ANN;
- at most 512 unique candidates per query;
- a top-k bound no greater than 64;
- lexical ranks for deterministic score-tie ordering.

The GPU may score only the supplied identities. There is no API that can
materialize an all-pairs query-by-corpus matrix. Small batches remain on the
existing CPU/SIMD path through an explicit crossover policy.

## Implemented kernels

- Exact multi-query cosine scoring over bounded ANN candidates.
- Deterministic top-k using score, lexical rank, then numeric identity.
- Compact readback of counts plus fixed top-k records, never all pair scores.
- Row normalization and packed symmetric int8 quantization for preparation.
- CPU oracles for scoring, normalization, and quantization.

The normalization/quantization API is an explicit trace path today. Its full
readback is intentionally measured and is not eligible for production
dispatch. It becomes useful when normalized and quantized buffers remain on
the GPU for centroid assignment, index training, or subsequent reranking.

## Measured RTX 3080 receipt

Release benchmark, 20,000 corpus rows, dimension 256, 2,048 queries, 128 ANN
candidates/query, top-k 16:

- 262,144 exact candidate pairs / 67,108,864 scalar FMA operations.
- Prevalidated resident CPU oracle: 136.685 ms.
- GPU end to end p50: 5.536 ms (24.7x faster).
- GPU dispatch: 1.904 ms.
- Compact readback: 0.178 ms / 32,768 records.
- CPU/GPU top-k overlap: 1.000000.
- Maximum matched score drift: 0.000000000.

Preparation benchmark, 20,000 rows x 256:

- CPU normalize + int8 quantize: 25.488 ms.
- GPU compute: 0.471 ms.
- GPU full-readback end to end: 31.240 ms.
- Full readback: 19.028 ms for 19.53 MiB normalized + 4.88 MiB quantized.

The preparation result is a deliberate negative crossover receipt: do not use
the full-readback path for production acceleration. Keep those buffers resident
before enabling it.

## Production shadow adapter

The packed native LSH index can compile this crate behind the optional
`vector-wgpu-shadow` feature. Runtime execution additionally requires
`PHOENIX_VECTOR_WGPU_SHADOW=1`. The adapter replays the exact bounded candidate
rows produced by LSH in 4,096-query chunks, but the existing AVX2/f64
neighborhoods remain the only encoded response.

The feature lane owns one process-lifetime GPU runtime and one cached corpus.
Corpus residency is keyed by generation, row count, dimensions, and a digest of
the lexical-rank and vector pages. An identical key reuses the exact GPU
buffers. Generation, shape, rank, or vector drift uploads one replacement
corpus while retaining the device and pipelines. The ordinary CPU build does
not compute this additional digest.

The V2 reconciliation contract treats WebGPU f32 scores as provisional. Each
row returns `k + 8` guarded identities plus one boundary witness when capacity
permits. Only that shortlist is rescored by the exact production AVX2/f64
scorer. A conservative dimension-bound f32 error interval proves that no
omitted identity can cross the final exact kth score or eligibility threshold.
Ambiguous rows fail closed to the existing full CPU result.

Hardware qualification over 2,048 queries and 262,144 pairs certified every
row with zero fallbacks, identity mismatches, score mismatches, or quantized
score drift. The reconciled warm p50 was 23.267 ms, including exact CPU
shortlist rescoring, versus 136.685 ms for the prevalidated full CPU oracle.
This is still shadow-only; live-corpus fallback rate and application p95 remain
promotion gates.

Residency qualification for a 2.01 MiB corpus measured 567-629 ms for cold
device creation plus first upload, below timer resolution for an identical
lease, and roughly 0.9-1.4 ms for generation or digest replacement. Five
repeated full reconciled shadow verifications measured 23.267 ms p50 wall time
with zero upload.

## Verification

```powershell
$env:CARGO_TARGET_DIR='D:\phoenix-target-vector-wgpu'
cargo test --manifest-path rust-native/phoenix-spikes/vector-wgpu-kernel/Cargo.toml
cargo test --release --manifest-path rust-native/phoenix-spikes/vector-wgpu-kernel/Cargo.toml
cargo test --release --manifest-path rust-native/phoenix-spikes/vector-wgpu-kernel/Cargo.toml shadow::tests::gpu_shadow_replays_bounded_candidates_without_identity_drift -- --ignored --nocapture
cargo test --release --manifest-path rust-native/phoenix-spikes/vector-wgpu-kernel/Cargo.toml residency::tests::same_generation_reuses_and_drift_replaces_one_resident_corpus -- --ignored --nocapture
cargo clippy --manifest-path rust-native/phoenix-spikes/vector-wgpu-kernel/Cargo.toml --all-targets --all-features -- -D warnings
cargo bench --manifest-path rust-native/phoenix-spikes/vector-wgpu-kernel/Cargo.toml --bench bounded_rerank
cargo bench --manifest-path rust-native/phoenix-spikes/vector-wgpu-kernel/Cargo.toml --bench preprocess
```

No renderer, graph-rebuild, GFM, or default retrieval path depends on this
crate. The production vector index sees it only under the two explicit shadow
gates above, and shadow results cannot alter response bytes.
