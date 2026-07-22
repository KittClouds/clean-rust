# StarE / CompGCN Hyper-Encoder v1

## Contract

This cut installs one shared 16-wide hyper-relational runtime with two causal arms:

- `CompgcnTriple` consumes the frozen train-only primary graph and masks all qualifier state.
- `StareQualifiers` consumes the same graph, weights, normalization, inverse facts, decoder,
  candidate universe, candidate-lane SIMD scorer, and exact frozen evaluator, while merging
  qualifier relation/entity compositions into both message passing and query decoding.

This is an encoder/evaluator cut. Its deterministic seed initializes the paired weights; it does
not claim a trained result or a winning architecture. Training and model selection must retain the
same intervention boundary and must not access the locked test partition.

## Qualifier authority

The task keeps original qualifier order for exact StarE filtering and certificate identity. The
encoder builds one `u32` reference lane per source qualifier and canonicalizes each statement by
`(relation, entity, source index)`. Payload records stay borrowed from the source mmap. Therefore:

- filter identity is unchanged;
- aggregation is bit-exact under qualifier permutation;
- qualifier payload copy bytes are zero;
- inverse messages reuse the same qualifier range;
- no dense qualifier tensor sidecar exists.

## Runtime

The encoder constructs one train-only, relation-batched adjacency with exact-sized arrays. Candidate
embeddings are transposed once into 16 feature planes padded to eight lanes. The evaluator scores
eight candidates per SIMD instruction while preserving the sequential feature accumulation order
for each candidate. It rejects non-canonical candidate arrays rather than silently changing score
order.

## Gates

- Same source, task, seed, and arm reproduce model IDs, score bits, score digests, metrics, and
  certificates.
- The paired arms share one initialized weight set and differ only by qualifier-state masking.
- Source/task identity drift and malformed qualifier ranges fail before encoding.
- Staging records zero qualifier payload copy bytes and train-only topology.
- Validation uses the canonical frozen evaluator. Test remains locked and unclaimed.
