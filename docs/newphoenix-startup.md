# NewPhoenix Startup Notes

This branch is the slim native-first Phoenix workspace. It keeps the Angular frontend, Tauri shell, native Rust Phoenix crates, local model assets, and `docs/` corpus/docs. Legacy GoKitt/WASM build paths and reference targets are intentionally removed from this branch.

## What To Run

### Frontend Dev Server

```powershell
npm install
npm start
```

The Angular dev server listens at `http://localhost:4200`.

### Tauri Native Shell

Run this in a second terminal while `npm start` is still running:

```powershell
npm run desktop:dev
```

Equivalent direct command:

```powershell
$env:CARGO_TARGET_DIR='D:\cargo-targets\Angular-build\tauri-dev'
cargo run --manifest-path "src-tauri\Cargo.toml"
```

### Production Build Smoke

```powershell
npm run desktop:build
```

The checked-in desktop commands use these fixed target families:

- `desktop:dev`, `desktop:check`, `desktop:test`, and `desktop:contract` use `D:\cargo-targets\Angular-build\tauri-dev`.
- `desktop:build` uses `D:\cargo-targets\Angular-build\tauri-release`.
- `desktop:contract` regenerates TauRPC bindings through the real IPC handler and fails if the committed TypeScript contract is stale.

## Native Rust Workspace

Current native post-ingest, Dynamic NER, Semantic Atlas, graph, and store work lives under:

```text
rust-native/phoenix
```

Use `CARGO_TARGET_DIR` on `D:` to avoid polluting the repo and to keep build artifacts out of the branch:

```powershell
$env:CARGO_TARGET_DIR='D:\cargo-targets\Angular-build\tauri-dev'
cargo check --manifest-path "rust-native\phoenix\Cargo.toml" -p phoenix-embed -p phoenix-dynamic-ner -p phoenix-graph-post -p phoenix-store-overgraph
```

The older `rust/phoenix` tree is kept only because `src-tauri` currently depends on its native `phoenix-native` host. Its WASM/reference crates were removed from the workspace. Do not add new work there unless it is explicitly part of the Tauri compatibility shim.

## Model Assets

Required local model directory for Dynamic NER:

```text
D:\hf-models\gliner-bi-base-v2.0-onnx\
```

Important files in that directory:

```text
model_label_embeds_quantized.onnx
model_label_embeds.onnx
labels_embeddings.json
labels_tokenizer/
tokenizer.json
gliner_config.json
```

The GLiNER-BI runner prefers `model_label_embeds_quantized.onnx` by default so it uses precomputed label embeddings. The current base-v2 bundle was exported from `knowledgator/gliner-bi-base-v2.0` with `scripts/export_gliner_bi_label_embeds.py`; keep it on `D:` on the new PC.

MDBR leaf embeddings are resolved from the Transformers cache used by the frontend/Rust probe:

```text
node_modules/@huggingface/transformers/.cache/MongoDB/mdbr-leaf-ir/
```

If that cache is missing, initialize the frontend model path once before running the Rust MDBR probe.

## Benchmarks

### Dynamic NER Regression Check

```powershell
$env:CARGO_TARGET_DIR='D:\cargo-targets\Angular-build\tauri-release'
$env:PHOENIX_DYN_NER_THRESHOLD='0.34'
$env:PHOENIX_DYN_NER_OVERLAP_POLICY='highest-score'
$env:PHOENIX_DYN_NER_MAX_LABELS='14'
$env:PHOENIX_DYN_NER_SUMMARY_ONLY='1'
cargo run --release -p phoenix-dynamic-ner --example drag_race -- "..\..\docs\shortrun.md" 1 "D:\hf-models\gliner-bi-base-v2.0-onnx"
```

Expected warm run on this machine: roughly `0.75s-1.0s`.

### Semantic Atlas Rust Probe

```powershell
$env:CARGO_TARGET_DIR='D:\cargo-targets\Angular-build\tauri-release'
$env:MAX_ENTITIES='70'
cargo run --release -p phoenix-embed --bin phoenix-mdbr-atlas-flat-probe -- "..\..\docs\shortrun.md"
```

Expected native Rust Semantic Atlas graph build is dominated by MDBR embedding. Graph construction itself should stay around single-digit milliseconds in release.

## Branch Rules

- Do not run or reintroduce GoKitt build scripts.
- Do not add WASM build scripts or WASM runtime crates back to the active workspace.
- Do not compile old `rust/phoenix` as a general workspace target; use it only through `src-tauri` until the native host is fully moved to `rust-native/phoenix`.
- Keep new native work in `rust-native/phoenix`.
- Keep docs and benchmark source documents under `docs/`.
- Keep build artifacts out of git; use `D:\cargo-targets\Angular-build\...` for Rust targets on the new PC.
