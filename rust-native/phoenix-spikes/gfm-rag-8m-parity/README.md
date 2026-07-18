# GFM-RAG-8M parity spike

Standalone Rust inference and parity lane for the pinned GFM-RAG-8M checkpoint.
It is intentionally not a Phoenix workspace member and has no dependency on
Phoenix graph mutation or persistence crates.

Pinned inputs:

- checkpoint repository revision: `4da9e4655d126a783ae2b795ab73b7c7a7c3f4ac`
- upstream source revision: `57e3e28045fffff5411e2454a4323fbe4dff9b91`
- MPNet revision: `e8c3b32edf5434bc2275fc9bab85f82640a19130`

All Cargo commands must set:

```powershell
$env:CARGO_TARGET_DIR = 'D:\phoenix-target-gfm-rag-8m'
```

The trusted Python converter refuses to overwrite an existing safetensors
checkpoint. Generated weights and ONNX assets live under the dedicated target;
small deterministic parity fixtures remain with this crate.
