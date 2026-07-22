# GFM wgpu sparse-kernel verification

Date: 2026-07-20

## Hardware receipt

- Adapter: NVIDIA GeForce RTX 3080
- Backend: Vulkan through wgpu 30.0.0
- Device type: discrete GPU
- Maximum buffer: 4,094 MiB
- Maximum storage binding: 2,048 MiB
- Runtime and pipeline initialization: 563.382 ms

Initialization is a process-level cost and must not occur per inference.

## Release results

All values are medians except preparation and the first cold dispatch. CPU is
the existing AVX2/FMA plus Rayon GFM implementation. GPU dispatch excludes
readback; readback is reported separately.

| Shape | CPU | GPU warm | Speedup | Readback | GPU bytes | Max abs |
|---|---:|---:|---:|---:|---:|---:|
| 5K nodes / 20K edges / D1024 | 5.650 ms | 0.234 ms | 24.10x | 5.443 ms | 78.36 MiB | 0 |
| 10K nodes / 40K edges / D512 | 5.509 ms | 0.231 ms | 23.82x | 4.361 ms | 78.50 MiB | 0 |
| 25K nodes / 250K edges / D256 | 7.254 ms | 0.365 ms | 19.90x | 5.525 ms | 99.68 MiB | 0 |
| 50K nodes / 1M edges / D128 | 10.212 ms | 0.575 ms | 17.77x | 6.137 ms | 105.49 MiB | 0 |

Preparation after process-level pipeline creation was 6.453-9.763 ms. The
first dispatch, which includes deferred device upload, was 0.765-4.958 ms.

## Interpretation

The sparse kernel itself is decisively faster once buffers are resident. A
full output readback costs more than the compute dispatch and erases the small
shape advantage. Cold, one-shot GPU execution is slower than AVX2 for every
measured case.

The production opportunity therefore requires a resident graph-model chain:

```text
CSR aggregation -> dense update -> normalization/activation -> next layer
```

Only final logits, top-k identities, or an explicitly requested trace should
cross back to the CPU. Integrating this sparse kernel alone would be a design
regression despite its high isolated speedup.

## Gates

- Five tests pass, including both-model parity and repeated byte identity.
- Candidate edges and Phoenix topology are outside the crate dependency graph.
- Residency is hard-bounded before allocation.
- Dispatch beyond one-dimensional WebGPU limits is explicitly tiled in two
  dimensions.
- The conservative dispatch policy keeps sub-250K-edge and sub-64M-FMA work on
  CPU until a resident dense chain exists.

## Fully resident chain

The follow-up cut keeps every hidden tensor on the device through six graph
layers and the final scorer. Normal execution reads back only deterministic
top-k scores and dense identities. Full hidden/logit tensors are available only
through an explicit trace call.

The implementation covers both established shapes at the graph-layer seam:

- 512-wide GFM-RAG-8M-like state with no entity scorer contribution.
- 1024-wide G-reasoner-34M-like state with the entity scorer contribution.

It deliberately begins after each model's question, relation, and entity
projection. Those front ends remain model-specific and unchanged.

### Release results

Adapter: NVIDIA GeForce RTX 3080, Vulkan through wgpu 30.0.0. Each case runs six
resident graph layers and returns top 20. Warm dispatch includes aggregation,
dense update, normalization, residual activation, scoring, and recursive top-k;
it excludes compact readback, which is reported separately.

| Shape | Prepare | Cold compact | Warm chain | Compact read | Trace read | Compact bytes | Trace bytes | Resident |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 5K nodes / 20K edges / D512 | 5.593 ms | 39.729 ms | 33.172 ms | 0.224 ms | 2.707 ms | 160 B | 10,260,000 B | 81.71 MiB |
| 2K nodes / 20K edges / D1024 | 15.624 ms | 102.183 ms | 45.723 ms | 0.126 ms | 2.398 ms | 160 B | 8,200,000 B | 107.14 MiB |
| 50K nodes / 1M edges / D128 | 11.914 ms | 29.223 ms | 23.228 ms | 0.134 ms | 7.589 ms | 160 B | 25,800,000 B | 180.01 MiB |

These measurements prove that full readback is no longer on the normal path:
160 bytes take 0.126-0.224 ms, while explicitly tracing 8.2-25.8 MB takes
2.398-7.589 ms. They do not prove a full-model speedup over either production
CPU model because checkpoint conversion and a full-model CPU/GPU benchmark are
outside this isolated cut.

The new dominant cost is the dense update, not sparse aggregation or compact
readback. A 32x32 shader experiment with four outputs per thread increased warm
times to 40.071-90.482 ms because of register pressure and was reverted. The
retained 16x16 tiled shader is the faster measured implementation. Production
integration should next compare a specialized tiled implementation against a
resident DirectML/ONNX Runtime dense backend while keeping Phoenix-specific
sparse aggregation and top-k in wgpu.

### Correctness and failure gates

- Independent CPU-oracle parity covers entity-disabled and entity-enabled
  contracts across three layers, 777 nodes, and recursive top-k reduction.
- Top-k identities are exact; scores, logits, and hidden state are checked
  within floating-point tolerance.
- Compact output is cross-checked against the GPU trace logits.
- Repeated compact execution is byte-identical.
- The mutable ping-pong state cannot overwrite the immutable initial hidden
  state; the parity suite caught and prevented that repeated-inference bug.
- Dimensions, CSR extents, identities, top-k bounds, u32 limits, and resident
  bytes fail closed before device allocation.
- Trace staging is transient and charged against the configured byte budget.
- No candidate-edge, Phoenix store, graph-truth mutation, or model-crate
  dependency exists.
- Every Rust and WGSL source file remains below the repository's 800-line gate.

### Integration decision

Do not wire this crate into either model yet. The resident architecture and
compact-readback boundary are validated, but the dense backend and complete
checkpoint parity remain open. The safe next gate is full-model golden parity
with persistent process-level residency, followed by an evidence-based backend
selection for dense operations. There is no implicit CPU fallback in this
experiment.
