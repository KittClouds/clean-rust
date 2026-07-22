# Verification record

Verified on 2026-07-15 on an AMD Ryzen 7 5800X3D (8 cores / 16 logical
processors). Source is on `C:` and every Cargo artifact is under
`D:\phoenix-target-g-reasoner-34m\cargo`.

## Provenance

- G-reasoner checkpoint revision:
  `a3a4ed2c62281e1c3e0551bd42f2072d9204674f`
- pinned upstream revision:
  `57e3e28045fffff5411e2454a4323fbe4dff9b91`
- source checkpoint SHA-256:
  `2f2a1a2d2f5725133428941b785f3898255666b06041b58420f75e60599d387d`
- converted safetensors SHA-256:
  `b62cc4a9bd186ea9f7549814d9641e3aebe7c849c510892c3b83aaee3ef8fa73`
- converted checkpoint: 34,640,897 parameters in 62 tensors
- Qwen revision: `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`
- Qwen safetensors SHA-256:
  `0437e45c94563b09e13cb7a64478fc406947a93cb34a7e05870fc8dcd48e23fd`

Both checkpoint loaders validate compiled provenance and full-file SHA-256
before inference. Checkpoint files are read-only mmaps. CSR sections are
borrowed directly from their read-only mmap without deserialization copies.

## Graph-core parity

The scalar reference run was compared with deterministic PyTorch fixtures:

| Boundary | Maximum absolute error |
| --- | ---: |
| question projection | 0.000000194 |
| relation projection | 0.000000447 |
| node projection | 0.000000447 |
| start boundary | 0.000000194 |
| early fusion | 0.000003338 |
| layer-0 relation projection | 0.000011444 |
| layer-0 aggregate | 0.000076294 |
| layer-0 hidden state | 0.000005722 |
| six-layer hidden state | 0.000006676 |
| final logits | 0.000019073 |

The mmap-backed AVX2/FMA + Rayon result differed from the scalar logits by at
most `0.000003815`. Document-typed top-20 membership and the complete ordering
of all 26 document nodes matched exactly.

G-reasoner directly ranks nodes of the requested type. Reciprocal-frequency
entity-to-document scoring belongs to GFM-RAG-8M and is intentionally absent
from this proof.

## Native Qwen parity

The exact upstream query instruction produced 27 matching token IDs. Rust
last-token pooling returned 1,024 normalized dimensions with:

- maximum absolute error: `0.000000303`
- cosine similarity: `0.999999821`
- reference norm: `1.0`
- runtime for the parity test: `72.58 s`

Candle's portable CPU matmul rejects BF16, so the immutable BF16 weights are
widened to FP32 for CPU compute. The measured test working set was about 2.45
GB. This is isolated behind the optional `qwen` feature and does not change the
frozen graph model.

## Performance and quality gates

The release sparse benchmark used 5,000 nodes, 20,000 edges, width 1,024, and
four Rayon workers:

| Kernel | Median time |
| --- | ---: |
| deterministic scalar | 11.436 ms |
| AVX2/FMA + Rayon | 5.437 ms |

Speedup was `2.103x`; maximum absolute error was `0.000000089`.

Quality gates:

- 7 Rust unit tests passed.
- graph-core parity integration test passed.
- native Qwen parity integration test passed.
- all-target, all-feature Clippy passed with warnings denied.
- release checkpoint smoke passed.
- all authored text source files are below 800 lines.
- Cargo metadata reports this crate itself as the workspace root and the
  dedicated D: directory as its target.

## FP32 ONNX encoder cut — 2026-07-16

The pinned Qwen embedding envelope was exported at opset 18 and consolidated
into a two-file immutable bundle:

- `model.onnx`: `b6c87649f0856e31ceca18cacf31ff26b43080022af620591909327e29e861bb`
- `model.onnx.data`: `2611cd936457a18786d4e0ffc7d21a5029f64df4cfc2fb69f87d9392108fa2f5`
- bundle BLAKE3: `0d82159172ff1c7085b9291c340bff35d7314b004dcee9e5c3556e2b43972104`

The FP32 export matched the PyTorch reference with maximum absolute error
`0.000000290` and cosine similarity `0.999999999996`. Native Rust parity against
the Candle implementation covered a query, a short passage, and a longer
passage; all three reported cosine `1.0`, with maximum absolute errors from
`0.000000149` to `0.000000343`.

Generic dynamic INT8 was measured and rejected: cosine similarity fell to
`0.171761`, so no INT8 artifact is accepted by the Rust runtime.

The native ONNX query calls measured 124–165 ms in the backend-parity run,
versus 2.10–3.65 s for Candle FP32. The production Phase 6 runner keeps the
validated ONNX session process-resident and retains Candle only as an explicit,
never automatic, fallback backend.

The combined `qwen,qwen-onnx` verification passed 9 unit tests, graph-core
parity, all-target strict Clippy, and the three-case native backend parity run.
