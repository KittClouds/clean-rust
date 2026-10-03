# Phoenix GLiNER2.5 Base shadow evaluation

This workspace evaluates `fastino/gliner2.5-base-v1` without modifying Phoenix's
authoritative extraction pipeline, graph topology, active scene publication, or
running processes. Every neural output is a candidate receipt; promotion count
is fixed at zero.

## Frozen inputs (2026-08-25)

- Phoenix source: `cbf349be8ee0dd878549242966d61b75fefe853f`
- GLiNER2 Python: `3c913c7369301133d3b7699252074c4303ada50e` (`v2.0.0`)
- GLiNER2.5 Rust: `a639bad1ee744a7884deea2bd01512fddd886b8d` (`0.2.1`)
- Base model: `72ac19b486cd4557424c8d61114e7530c243e9b0`
- Rust ORT binding: exact `2.0.0-rc.13`, isolated from Phoenix's `rc.9`
- Build target: `D:\phoenix-target-gliner25-eval`
- Source model: `D:\phoenix-models\gliner2.5-base-v1-source-72ac19b`
- ONNX export: `D:\phoenix-models\gliner2.5-base-v1-onnx-a639bad`

The Python reference and native Rust decoder are tested for the complete public
five-feature surface: long context, wide explicit spans, span attributes,
constrained classification, and joint entity-relation IE. Rust owns the
orchestration and decoding; ONNX Runtime evaluates the frozen encoder and
feature-head graphs. Record decoding remains outside this five-feature cut.

The optimized export adds exact 320/384/448-word boundary buckets and
8x32/16x64 explicit-span tiers beside the canonical 64/128/256/512-word and
64x128 surfaces. The decoder selects the smallest fitting graph, passes tensor
views into ORT without cloning inputs, lazily loads feature sessions, and reuses
the trace's padded word mask. See [OPTIMIZATION.md](./OPTIMIZATION.md) for the
accepted changes, rejected experiments, receipts, and measured limits.

## Gates

1. Model config must declare `architecture=boundary`, `enable_relations=true`,
   `enable_records=true`, candidate pool 192, and half-open source spans.
2. Every returned span must satisfy `source[start..end] == text`.
3. FP32 Python/Rust structures must agree exactly across all five features;
   maximum probability delta is `1e-5` and classification-objective delta is
   `1e-4`.
4. A repeated census must produce the same BLAKE3 row-stream hash.
5. No command in this workspace writes Phoenix graph or scene authority.
6. Benchmarks report engine load, warm p50/p95/p99, stable output counts, and
   process working set. No quality F1 is claimed without a frozen human gold
   set.

## Commands

Set `ORT_DYLIB_PATH` to the isolated Python ONNX Runtime DLL and compile on D:

```powershell
$env:CARGO_TARGET_DIR='D:\phoenix-target-gliner25-eval'
$env:ORT_DYLIB_PATH='D:\phoenix-upstream\gliner25-eval-20260825\py312\Lib\site-packages\onnxruntime\capi\onnxruntime.dll'
cargo test --all-targets --manifest-path .\experiments\phoenix-gliner25-eval\Cargo.toml
cargo build --release --manifest-path .\experiments\phoenix-gliner25-eval\Cargo.toml
```

The DLL pin is mandatory for every evaluator invocation, not only compilation.
Without it, Windows may load Phoenix's older rc.9 runtime, which rejects the
exported IR 10 fragments before inference.

Reference feature probe:

```powershell
& 'D:\phoenix-upstream\gliner25-eval-20260825\py312\Scripts\python.exe' `
  .\experiments\phoenix-gliner25-eval\python\reference_probe.py `
  --model 'D:\phoenix-models\gliner2.5-base-v1-source-72ac19b' `
  --output .\experiments\phoenix-gliner25-eval\receipts\reference-features.json
```

Rust smoke:

```powershell
& 'D:\phoenix-target-gliner25-eval\release\phoenix-gliner25-eval.exe' `
  --model 'D:\phoenix-models\gliner2.5-base-v1-onnx-a639bad' `
  --schema .\experiments\phoenix-gliner25-eval\schemas\story-v1.json `
  --precision fp32 probe `
  --text 'Sam Altman works at OpenAI in San Francisco.'
```

Full Rust five-feature probe and Python parity gate:

```powershell
& 'D:\phoenix-target-gliner25-eval\release\five_surface.exe' `
  --model 'D:\phoenix-models\gliner2.5-base-v1-onnx-a639bad' `
  --output .\experiments\phoenix-gliner25-eval\receipts\rust-five-surface.json

& 'D:\phoenix-upstream\gliner25-eval-20260825\py312\Scripts\python.exe' `
  .\experiments\phoenix-gliner25-eval\python\compare_five_surface.py `
  --python .\experiments\phoenix-gliner25-eval\receipts\reference-features-rerun.json `
  --rust .\experiments\phoenix-gliner25-eval\receipts\rust-five-surface.json `
  --manifest 'D:\phoenix-models\gliner2.5-base-v1-onnx-a639bad\boundary_manifest.json' `
  --output .\experiments\phoenix-gliner25-eval\receipts\five-surface-parity.json
```

Novel-window benchmark:

```powershell
& 'D:\phoenix-target-gliner25-eval\release\five_surface_bench.exe' `
  --model 'D:\phoenix-models\gliner2.5-base-v1-onnx-a639bad' `
  --document .\docs\shortrun.md --threads 8 --window-words 270 `
  --warmup 1 --runs 3 `
  --output .\experiments\phoenix-gliner25-eval\receipts\bench-five-shortrun.json
```

The census uses memory-mapped UTF-8 input, chapter-bounded 384-word windows,
64-word overlap, exact global byte offsets, overlap deduplication, buffered
JSONL, and a companion receipt. Use `--max-chunks` for a bounded qualification
run before the full four-novel pass.
