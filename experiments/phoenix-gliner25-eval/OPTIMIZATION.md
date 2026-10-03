# GLiNER2.5 Rust decoder optimization receipt

Date: 2026-08-26

This pass optimizes the isolated five-feature evaluator. It does not modify the
active Phoenix extraction heads, graph topology, scene publication, saved
models, or running Phoenix processes.

## Accepted implementation

- ORT inputs use borrowed `TensorRef` views over dense Rust slices. Large
  encoder, hidden-state, gathered-state, mask, and scorer inputs are no longer
  cloned into owned ORT tensors.
- Boundary heads use exact 64/128/256/320/384/448/512-word exports and choose
  the smallest fitting graph.
- Explicit span scoring chooses exact 8x32 or 16x64 heads when possible and
  retains the canonical 64x128 head for large inputs and A/B reproduction.
- Feature sessions remain lazy. An unused feature head consumes neither session
  construction time nor its ORT arena.
- `FeatureTrace` retains the padded word mask already built for the boundary
  head, avoiding reconstruction for explicit-span scoring.
- ORT intra-op threads remain at eight. The measured 12- and 16-thread variants
  oversubscribed this 16-logical-processor host and regressed materially.

The hot representation remains contiguous `Vec` storage with borrowed slices at
the inference boundary. Output tensors are copied only when their values must
outlive the ORT call.

## Correctness gates

`receipts/five-surface-parity-dense-buckets.json` records:

- exact Python/Rust structure on all five decoder surfaces;
- maximum probability delta `2.6226043701171875e-6`;
- classification-objective delta `5.245208740234375e-6`;
- zero graph publications.

The crate has eight passing unit tests. New selection tests prove that 270 words
selects the 320-word graph, 385 selects 448, oversize input fails closed, small
explicit workloads select the smallest tier, and the canonical 64x128 scorer
can still be selected for comparison.

## Measured performance

The final rebuilt 7-run, 2-warmup shortrun comparison uses
`receipts/perf-baseline-shortrun-t8.json` and
`receipts/perf-final-shortrun-t8.json`:

| Surface | Baseline p50 | Optimized p50 | Change | Stable outputs |
| --- | ---: | ---: | ---: | ---: |
| Long context | 1577.34 ms | 1402.37 ms | -11.09% | 80 / 80 |
| Wide spans | 397.50 ms | 387.14 ms | -2.61% | 28 / 28 |
| Attributes | 479.20 ms | 451.53 ms | -5.77% | 17 / 17 |
| Classification | 364.69 ms | 335.52 ms | -8.00% | 2 / 2 |
| Joint IE | 521.58 ms | 472.52 ms | -9.41% | 18 / 18 |

This local latency win did not survive the separately launched four-novel
comparison. `receipts/five-surface-performance-dense.json` reports a `3.44%`
slower geometric mean across matched p50 values, with changes in both directions
by feature and document. Process launch, system load, frequency, ORT arena
history, and the short 3-5-run samples remain confounders. No universal latency
claim is accepted from these measurements.

The reproducible resource result is memory: maximum peak working set fell from
1,291,980,800 to 1,222,438,912 bytes (`-5.38%`) against the original four-novel
run. In the final shortrun A/B it fell from 1,284,247,552 to 1,216,335,872 bytes
(`-5.29%`). The explicit tiers alone reduced the attribute/joint tail by roughly
61 MiB in the mirrored A/B receipts.

## Rejected experiments

### Larger caller chunk

A 511-word caller chunk with 64-word overlap appeared `10.84%` faster in one
shortrun measurement, but stable long-context outputs changed from 80 to 51.
Without frozen human judgments, that is a semantic change rather than a valid
optimization. The 384/64 default remains authoritative.

### Dynamic INT8 encoder

The quantized encoder shrank from 701.87 MiB to 513.69 MiB, but every
five-feature structural parity gate failed and the constrained-classification
objective moved by `17.1548`. The INT8 model and code path were deleted. Failure
receipts remain at `receipts/rust-five-surface-int8.json` and
`receipts/five-surface-parity-int8.json` so the rejected path cannot silently
return.

### More ORT threads

Eight intra-op threads won the 4/8/12/16 sweep. Twelve and sixteen were rejected
because oversubscription increased latency.

## Reproduction

```powershell
$env:CARGO_TARGET_DIR='D:\phoenix-target-gliner25-eval'
$env:ORT_DYLIB_PATH='D:\phoenix-upstream\gliner25-eval-20260825\py312\Lib\site-packages\onnxruntime\capi\onnxruntime.dll'

cargo test --all-targets --manifest-path .\experiments\phoenix-gliner25-eval\Cargo.toml
cargo build --release --manifest-path .\experiments\phoenix-gliner25-eval\Cargo.toml

& 'D:\phoenix-target-gliner25-eval\release\five_surface.exe' `
  --model 'D:\phoenix-models\gliner2.5-base-v1-onnx-a639bad' `
  --output .\experiments\phoenix-gliner25-eval\receipts\rust-five-surface-optimized-final.json
```

The next meaningful latency step is profiling and fusing the encoder/gather
boundary or using a provider path with explicit served-provider and I/O-binding
receipts. Window-size changes and lossy precision remain gated on a human gold
set.
