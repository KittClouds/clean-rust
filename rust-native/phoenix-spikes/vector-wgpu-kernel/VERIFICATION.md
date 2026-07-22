# Verification receipt

Date: 2026-07-21
Target: `D:\phoenix-target-vector-wgpu`
Adapter: NVIDIA GeForce RTX 3080 / vendor-neutral `wgpu` 30

## Correctness

- Unit and integration tests: 13 passed; two hardware qualifications are ignored
  by default and passed explicitly on the RTX 3080.
- Exact scoring returns only ANN-supplied candidate identities.
- Candidate rows fail closed above 512 entries, on duplicates, or on an
  identity outside the resident corpus.
- Repeated GPU scoring is byte-identical on the tested adapter.
- Multi-query GPU top-k identities match the fused CPU oracle.
- Equal scores use lexical rank and then stable numeric identity.
- GPU normalization is within `2e-6` of the CPU oracle.
- Packed int8 quantization is within one level of the CPU oracle.
- The dispatch policy retains CPU authority below every crossover gate.
- The V2 receipt uses exact production f64 scores after guarded GPU selection.
- A dimension-bound f32 error certificate guards the omitted-candidate boundary.
- Ambiguous or capacity-limited rows fail closed to the authoritative CPU row.

## Release performance

Bounded rerank shape:

```text
rows=20000 dim=256 queries=2048 candidates/query=128 top_k=16
pairs=262144 scalar_fma_ops=67108864
prevalidated_resident_cpu_ms=136.685 gpu_p50_ms=5.536 speedup=24.7x
gpu_dispatch_us=1904 compact_readback_us=178
top_k_overlap=1.000000 max_score_drift=0.000000000
```

Normalization and quantization shape:

```text
rows=20000 dim=256
cpu_ms=25.488 gpu_p50_ms=31.240
gpu_dispatch_us=471 full_readback_us=19028
normalized=19.53 MiB quantized=4.88 MiB
max_normalized_drift=0.000000022 max_quantized_drift=1
```

## Production decision

The exact bounded rerank kernel qualifies as a strong backend candidate at the
measured 67M-FMA shape. It is wired only as a feature-gated, environment-opted
production shadow. ANN generation and AVX2/f64 response authority are unchanged.

Production-shadow qualification receipt:

```text
queries=2048 pairs=262144 returned_top_k=32768
certified_queries=2048 row_fallbacks=0
identity_mismatches=0 score_mismatches=0 max_quantized_delta=0
analytical_error_bound=0.000032308 observed_max_error=0.000000841
runtime_reused=true corpus_reused=true upload_us=0
dispatch_us=2447 compact_readback_us=524 warm_wall_p50_us=23267
disposition=Certified adapter=NVIDIA GeForce RTX 3080
```

Generation-bound residency qualification:

```text
corpus_bytes=2105344 cold_us=586425 identical_lease_us=0
generation_replace_us=932 digest_replace_us=1015
retained_cache_entries=1 runtime_reused_after_cold=true
```

The previous one-unit f32 receipt drift is removed from the authority surface:
GPU values select only a guarded shortlist, while the current production
AVX2/f64 scorer emits the exact millionth-quantized receipts. The boundary is
accepted only when a conservative error interval proves every omitted candidate
cannot cross it. Generation-bound runtime, corpus reuse, and score receipts now
qualify in shadow. Authority promotion still waits for live application p95,
fallback-rate, and memory receipts.

The preprocessing kernel does not qualify when its full tensors return to CPU
memory. Production use requires a resident chain:

```text
normalize / quantize -> centroid assignment or exact rerank -> compact top-k
```

Only compact identities, scores, and an optional trace may cross back. ANN
candidate generation remains authoritative and CPU/native.
