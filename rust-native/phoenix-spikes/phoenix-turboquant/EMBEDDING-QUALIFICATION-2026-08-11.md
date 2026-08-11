# Embedding runner qualification — 2026-08-11

## Decision

Length-aware batching is qualified for Phoenix's Jina v5 Nano and
EmbeddingGemma configurations. Both model families now select it by default;
generic and MDBR configurations remain unchanged.

The earlier 56-minute frozen-gate document pass was not a model-runner
regression. It was a cold, cache-free workload over long, arbitrarily ordered
documents. Its query control remained consistent with the prior short-input
Gemma proof.

## Bound workload

- Source bundle SHA-256:
  `f2fa50758475d4423db933e7fb291efaa78547441ff15ed5ab10b54453b09bd4`
- Candidate documents: 5,037
- Queries: 1,751
- Actual Phoenix chunks: 6,195
- Chunker: `phoenix_chunker_native::build_chunks`
- Chunk size/overlap: 1,840/256 characters
- Deterministic document sample: 24 rows across the chunk-length distribution
- Deterministic query sample: 32 rows across the query-length distribution
- Batch size: 8
- Execution provider: CPU
- Intra/inter threads: 8/1
- ORT DLL SHA-256:
  `4bc168111012971ae1ffef36c1f29c06b026d17e9063bd17f6390359fbe32a84`

Document sample character distribution was p50 1,154, p95 1,781, maximum
1,834. Each lane was warmed, then run twice in balanced input/bucket order.
The minimum observed time for each order is reported.

## Results

| Model/lane | Input order | Length bucketed | Speedup | Token padding | Attention padding |
| --- | ---: | ---: | ---: | ---: | ---: |
| Gemma Q4 documents | 10,501.58 ms | 6,995.55 ms | 1.50x | 1.80x -> 1.22x | 2.35x -> 1.35x |
| Gemma Q4 queries | 983.25 ms | 806.84 ms | 1.22x | 1.58x -> 1.29x | 2.32x -> 1.70x |
| Jina Q4F16 documents | 8,195.97 ms | 5,681.22 ms | 1.44x | 1.77x -> 1.23x | 2.26x -> 1.36x |
| Jina Q4F16 queries | 610.25 ms | 465.90 ms | 1.31x | 1.91x -> 1.39x | 3.05x -> 1.95x |

All four lanes passed:

- canonical output order restored;
- padded token work did not increase;
- padded attention-shaped work did not increase;
- minimum cosine at least 0.99999;
- maximum absolute component difference at most 0.0001.

Jina output was bit-identical across batch order. Gemma's maximum component
difference was `3.0485331e-5`, with minimum cosine `0.99999917`.

## Exact runners

EmbeddingGemma selected:

```text
D:\phoenix-models\embeddinggemma-300m-ONNX\onnx\model_q4.onnx
```

Jina selected:

```text
D:\phoenix-models\jina-embeddings-v5-text-nano-retrieval\onnx\model_q4f16.onnx
```

The Angular registry now reports those actual Q4 and Q4F16 assets instead of
labeling both as FP16.

## Implementation boundary

The runner creates one stable execution permutation from input byte length,
reuses batch tensor/output scratch, embeds similar-length rows together, and
scatters normalized vectors back into their canonical input positions. Inputs
that fit in one batch bypass permutation and scatter entirely.

Telemetry records useful/padded tokens, useful/padded attention cells, maximum
sequence length, batches, configured order, model path, execution provider,
and thread policy.

## Receipt

```text
D:\phoenix-turboquant-gate-20260811\embedding-qualification-v4-final.json
```

- Bytes: 11,431
- SHA-256:
  `f4248d068dfbfc2ce66031d6a1fdd404f92d43ad5e99a41f81b788be777dad18`

The receipt's four model/lane gates are all `true`.

## Remaining boundaries

- The qualification is CPU-only; DirectML/CUDA are not claimed.
- MDBR and generic configurations remain input-ordered until separately
  qualified.
- The full production embedding cache and incremental sidecar lifecycle still
  need application-level receipts.
- TurboQuant promotion remains blocked on a privacy-reviewed production query
  trace and production-lifetime sidecar policy.
