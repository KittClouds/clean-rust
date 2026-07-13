# Candle vs Burn Graph Runtime Spike v1

## Decision

Adopt **Candle 0.11** for the first Phoenix graph-research runtime slice.

This is a narrow decision for CPU inference over Frozen Tensorization / Train-Topology
Feature Derivation artifacts. It is not a claim that Candle wins future GPU training,
autodiff, distributed training, or heterogeneous deployment. Those require separate
spikes against their actual workloads.

## Frozen comparison contract

Both binaries consume the same immutable `phoenix-train-topology-features/v1` file
through `TrainTopologyFeatureMapped`. Opening the artifact verifies its byte length,
BLAKE3 identity, header, offsets, and fixed-width row counts before any runtime sees a
feature.

The runtime contract is identical:

- CPU backend: Candle CPU versus Burn Flex CPU.
- Model: `[N,16] × [16,16] → ReLU → × [16,1]`.
- Deterministic input rows and weight bytes.
- One preallocated dense feature materialization from the mmap records; no adapter
  clone when the framework tensor takes ownership.
- 10 warmups, alternating framework order, seven independent process runs per size.
- Scalar reference parity must remain within `1e-4`.
- Scores return to the authoritative `phoenix-ranking-evaluation/v1` evaluator.
- Score bytes receive a BLAKE3 certificate.

The artifact is zero-copy through identity validation and typed row access. It is not
a dense matrix on disk: metadata and 16 features are interleaved per record. Neither
framework accepts borrowed, strided mmap storage for this operation, so exactly one
dense staging allocation remains. Changing the artifact to favor either runtime was
explicitly out of scope.

## Release results

Host: AMD Ryzen 7 5800X3D, 8 cores / 16 logical processors, Windows MSVC, Rust
1.96.0, LLVM 22.1.2. Times are median microseconds per forward pass.

| Candidate rows | Iterations/run | Candle CPU | Burn Flex CPU | Candle advantage |
|---:|---:|---:|---:|---:|
| 4,000 | 500 | 104 µs | 227 µs | 54.2% lower latency |
| 40,000 | 100 | 1,133 µs | 1,748 µs | 35.2% lower latency |
| 400,000 | 20 | 10,696 µs | 16,304 µs | 34.4% lower latency |

At the representative 40,000-row gate:

- Artifact: 3,200,056 bytes,
  `b3-4f5bdf924156bfbe9d2cdfd59440b890e41a17a8689d18b5215c041c8b5098ce`.
- Both score streams:
  `b3-e8cc29b168eff3475999b3577f596e5e049ab11e801e99c672a8347f9a1a526c`.
- Maximum scalar error: `2.9802322e-8` for both.
- Phoenix metrics: filtered MRR `1.0`, Hits@1 `1.0` for both.
- Median working set: Candle 12,136,448 bytes; Burn 10,629,120 bytes.
- Stripped binary: Candle 1,011,200 bytes; Burn 1,415,680 bytes.

Burn saves about 1.5 MB of resident memory at 40,000 rows. Candle is 1.54× faster,
copies output substantially faster, and produces a binary about 404 KB smaller. The
memory difference is real but not large enough to outweigh the stable latency lead
for the current graph-ranking workload.

## Pressure point exposed by the spike

At 40,000 rows Candle inference is 1.133 ms, but mmap open plus dense staging is about
7.81 ms. For one-shot evaluation, framework choice is no longer the largest cost.
For training or repeated evaluation the staged tensor is reused, so the inference win
compounds across epochs.

The next tensor-runtime ticket should therefore preserve this artifact as authority
while adding a separately certified, content-addressed dense feature sidecar only if
one-shot latency matters. That proposal must prove identical row order, dtype,
feature schema, and BLAKE3 source identity; it must not mutate the current artifact.

## Scope guard

Candle is intentionally integrated as an isolated spike crate, not as a Phoenix
workspace dependency. Promotion requires a model artifact contract and a training
spike. Burn remains a credible candidate for that later ticket because its backend
abstraction and autodiff surface are broader; this benchmark only establishes that
the abstraction does not buy us performance on the present CPU inference path.

Primary framework references: [Candle repository](https://github.com/huggingface/candle),
[Burn 0.21 release](https://github.com/tracel-ai/burn/releases/tag/v0.21.0), and
[Burn backend model](https://burn.dev/books/burn/basic-workflow/backend.html).

Machine-readable evidence is frozen in
[`cpu-5800x3d-v1.json`](../rust-native/phoenix-spikes/candle-burn-graph-runtime/results/cpu-5800x3d-v1.json).
