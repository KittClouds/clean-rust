# GFM wgpu kernels

An isolated, inference-only proof for the incoming-CSR DistMult aggregation and
a fully resident graph-layer chain shared by GFM-RAG-8M and G-reasoner-34M.

The crate has no Phoenix store or mutation dependencies. It does not replace
either established CPU kernel. Their AVX2/FMA implementations are independent
parity oracles for this experiment.

## Sparse kernel contract

- One workgroup owns one destination row.
- Workgroup lanes stride across embedding dimensions.
- Incoming CSR edge order is preserved.
- Node, relation, boundary, output, and topology buffers remain resident.
- More than 65,535 nodes use a bounded two-dimensional dispatch.
- Every allocation is rejected before device access when it exceeds the
  configured or adapter-reported limit.
- Backend selection is explicit. The GPU runtime contains no implicit CPU
  fallback and cannot write graph truth.

## Resident chain contract

The resident path starts at the first hidden state produced by the model's
question/relation/entity projections. One upload prepares immutable CSR,
weights, projected relation tensors, boundary state, and scorer tensors. A
single submitted command chain performs:

```text
CSR DistMult aggregation
  -> tiled dense update
  -> layer normalization
  -> ReLU + residual
  -> next graph layer
  -> scorer
  -> deterministic top-k reduction
```

The normal API returns only packed `(score, dense_node_id)` records. Hidden
states and logits remain device-resident. Full hidden/logit readback is exposed
only by the explicitly named trace API and is checked against the residency
budget before allocation.

The chain supports the two current model contracts without coupling them:

- GFM-RAG-8M-like execution omits the optional entity scorer term.
- G-reasoner-34M-like execution includes it.

This crate is not wired into either model. Production integration still
requires checkpoint tensor conversion, full-model golden parity, and a measured
backend decision for the dense stages.

## Verification

```powershell
$env:CARGO_TARGET_DIR='D:\phoenix-target-gfm-wgpu'
cargo test -- --nocapture
cargo bench --bench distmult_gpu
cargo bench --bench resident_chain
cargo clippy --all-targets -- -D warnings
```

See `VERIFICATION.md` for the measured crossover and interpretation.
