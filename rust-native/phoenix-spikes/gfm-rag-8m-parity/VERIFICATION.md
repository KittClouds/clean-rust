# Verification receipt

All commands were executed with `CARGO_TARGET_DIR` set to
`D:\phoenix-target-gfm-rag-8m\cargo`. No Phoenix workspace manifest, graph
persistence crate, or pre-existing research tree was changed.

## Provenance

- checkpoint revision: `4da9e4655d126a783ae2b795ab73b7c7a7c3f4ac`
- upstream source revision: `57e3e28045fffff5411e2454a4323fbe4dff9b91`
- source checkpoint SHA-256: `578b1af29201beda2ef61af7fadbd7261a4964c3fcd1c68a22b90a62f6ff1247`
- converted safetensors SHA-256: `9e4a79d25829c4356bcc58c8bd433a985e02fd52a0885f1745f2560cbc75528b`
- parameters: `8,144,897`
- MPNet revision: `e8c3b32edf5434bc2275fc9bab85f82640a19130`
- MPNet ONNX SHA-256: `74187b16d9c946fea252e120cfd7a12c5779d8b8b86838a2e4c56573c47941bd`

## Core parity

`cargo test --locked --test core_parity -- --nocapture`

| Gate | Maximum absolute error |
| --- | ---: |
| question projection | `0.000002384` |
| relation projection | `0.000004768` |
| first-layer relation projection | `0.000427246` |
| first-layer aggregate | `0.001953125` |
| first-layer hidden state | `0.000002384` |
| six-layer hidden state | `0.000005484` |
| six-layer logits | `0.000009060` |
| AVX2/FMA versus scalar logits | `0.000002861` |

Top-20 membership, reciprocal-frequency document scores, and final document
ordering matched exactly. The fast pass loads the graph through the immutable
mmap CSR view, while both passes load weights from the mmap safetensors view.

## MPNet parity

`cargo test --locked --features mpnet-onnx --test mpnet_parity -- --nocapture`

Three text fixtures matched Python ONNX Runtime with maximum absolute errors
between `0.000000030` and `0.000000045`. Their L2 norms were `2.945133`,
`3.108045`, and `3.040559`, proving normalization is disabled.

## Sparse kernel performance

Release run with 10,000 nodes, 40,000 edges, width 512, seven fast samples:

```text
kernel=Avx2Fma scalar_ms=12.990 fast_median_ms=5.701 speedup=2.279 max_abs=0.000000089
```

This benchmark covers the fused DistMult-plus-sum kernel only. End-to-end
latency will additionally include six dense updates and scoring.
