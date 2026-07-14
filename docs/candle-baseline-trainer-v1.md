# Candle Baseline Trainer v1

## Purpose

`phoenix-candle-baseline-trainer/v1` is the first deterministic learned-model
producer for Phoenix graph research. It trains one MLP-16 seed per invocation and
emits only `phoenix-frozen-model/v1`; Candle does not own a parallel checkpoint
format.

The trainer remains an isolated spike crate. `phoenix-graph-research` stays
framework-neutral, and its default `graph-build` feature preserves every existing
Phoenix caller. The trainer disables that feature because immutable artifacts and
evaluators do not require the graph compiler.

## Authoritative inputs

One execution opens and validates all four authorities before materializing a row:

1. Frozen Graph Research Snapshot manifest and mmap binary;
2. Frozen Tensorization manifest and mmap binary;
3. Research Evaluation Protocol JSON and content identity;
4. Train-Topology Feature Derivation manifest and mmap binary.

Dataset, checkpoint, tensor, protocol, derivation, split-policy, and topology
identities must form one exact chain. The topology audit must certify train-only,
asserted-edge-only, resolved-incidence-only, leave-one-positive-out derivation.

Test rows are skipped before feature materialization. Only training and validation
link rows enter memory.

## Deterministic training contract

- framework: Candle `0.11.0`;
- reference backend: CPU;
- architecture: `[N,16] -> Linear(16,16) -> ReLU -> Linear(16,1)`;
- loss: binary cross-entropy with logits plus L2 on weight tensors;
- optimizer: Candle stateless SGD without momentum;
- initialization and Fisher-Yates order: Phoenix SplitMix64 from the selected
  certified seed;
- one selected repeat and one training execution per model artifact;
- fixed export order: `hidden.weight`, `hidden.bias`, `output.weight`,
  `output.bias`.

The optimizer-state BLAKE3 binds the stateless SGD schema, learning-rate bits, and
completed step count. Epochs, batch size, L2, source identities, and seed receipt
are independently bound by the frozen model identity.

## Scoring authority

Candle's forward pass is a parity witness, not the certificate authority. After
training, the exported tensors are scored by the shared two-lane `f32x8` Phoenix
scorer. The same canonical score stream produces two validation certificates:
binary average precision/Brier metrics under `phoenix-research-evaluation/v1` for
model selection, and ranking MRR/Hits metrics under
`phoenix-ranking-evaluation/v1` for structural comparison.

Candle and canonical scores must remain within `1e-4`. The frozen artifact is then
written, reopened through mmap, and rescored. Restart scores and both stored score
certificates must match exactly without another training execution.

## Performance evidence

Release smoke on the local Ryzen 7 5800X3D, Windows MSVC, using
`D:\phoenix-target-candle-trainer`:

| Work | Result |
|---|---:|
| Training examples | 1,024 |
| Validation examples | 256 |
| Epochs / optimizer steps | 4 / 64 |
| Candle training | 7.340 ms |
| Mmap reopen plus restart scoring | 1.167 ms |
| End-to-end test wall time | 20.844 ms |

The warm debug integration gate completed the same training path in 96.738 ms and
the complete trainer test suite in 0.12 seconds.

## Failure shields

Training fails closed on source-chain drift, altered protocol identity or filename,
invalid seed selection, non-BLAKE3 research identities, unsafe topology audit
flags, unknown split values, non-finite features or weights, empty train or
validation splits, non-rankable validation groups, Candle/SIMD score drift,
artifact corruption, and restart certificate drift.

## GPU boundary

CPU is the deterministic reference backend, not a permanent performance ceiling.
A CUDA trainer may be added without changing the artifact or evaluator. It must use
a distinct runtime identity, consume the same authority chain, export the same
ordered tensor contract, and pass the canonical SIMD score/metric and cold-restart
gates. Backend-specific floating-point behavior may not redefine research truth.
