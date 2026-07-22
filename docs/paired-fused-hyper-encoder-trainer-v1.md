# Paired Fused Hyper-Encoder Trainer v1

## Outcome

The trainer fits the StarE qualifier-aware arm and CompGCN triple-only control from one certified
initialization and one deterministic train-only example schedule. Both arms use the same primary
and inverse topology, negatives, optimizer, epochs, normalization, decoder, candidate universe,
SIMD scorer, and frozen validation evaluator. The only causal intervention is qualifier state.

The first WD50K configuration is a certified negative result: StarE does not beat CompGCN overall.
It is preserved as an immutable research result and is not promoted as a winning configuration.

## Fused end-to-end backward pass

One fixed arena owns encoded nodes, encoded relations, their gradients, and every parameter
gradient. Loss propagates through:

- filtered deterministic positive/negative link examples;
- the DistMult decoder and bias;
- query qualifier composition and projection;
- relation projection;
- ReLU;
- primary, inverse, and self message aggregation;
- direction matrices and degree normalization;
- message qualifier composition;
- entity and relation embeddings.

The epoch body performs no allocation. Qualifier payload records remain borrowed from the source
mmap; only the canonical `u32` reference lane is staged.

## Immutable artifacts

Each arm writes a raw fixed-order little-endian weight blob followed by an immutable JSON manifest.
The manifest binds source, task, pair, trainer, initialization, topology, example schedule,
optimizer state, configuration, validation certificate, weight digest, and exact tensor shape.
Manifest identity is composed from exact binary fields and certificate identities rather than
round-tripped floating-point JSON.

The pair manifest binds both model and validation certificate identities. Model-manifest IDs are
resolved after the pair identity to avoid a cyclic content-address dependency.

Cold restart opens only the source/task/model artifacts, validates BLAKE3 identities, reconstructs
the encoded scene from mmap weights, and reproduces validation scores without the trainer.

## Frozen WD50K gate

- Seed: `0x51a7e001`
- Epochs: 4
- Training examples: 665,740
- CompGCN training: 627.907 ms
- StarE training: 1,812.915 ms
- Peak working set: 78.984 MiB
- Epoch allocations: zero
- Model weight blobs: 3,095,352 bytes each
- CompGCN validation MRR: 0.0017855040477948328
- StarE validation MRR: 0.0017832634641920342
- StarE minus CompGCN: -0.0000022405836027986
- Qualifier-present MRR: 0.0016541088196426188 control, 0.001655978209242202 StarE
- Independent replay: exact pair, initialization, schedule, model, score, and certificate identities
- Cold restart: exact for both arms
- Test access: none

The low MRR is expected for this first four-epoch configuration. Validation was used to measure the
declared configuration, not to search configurations. The locked test partition remains untouched.
