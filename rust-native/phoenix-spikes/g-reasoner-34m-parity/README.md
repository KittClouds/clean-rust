# G-reasoner-34M parity spike

Standalone, inference-only Rust lane for the pinned G-reasoner-34M checkpoint.
It is not a Phoenix workspace member and cannot write Phoenix graph state.

Pinned inputs:

- checkpoint revision: `a3a4ed2c62281e1c3e0551bd42f2072d9204674f`
- upstream revision: `57e3e28045fffff5411e2454a4323fbe4dff9b91`
- text encoder: `Qwen/Qwen3-Embedding-0.6B` at
  `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`

All Cargo commands must set:

```powershell
$env:CARGO_TARGET_DIR = 'D:\phoenix-target-g-reasoner-34m\cargo'
```

The trusted Python converter refuses to overwrite an existing safetensors
checkpoint. Large weights and generated Qwen assets remain under the dedicated
D: target; deterministic parity fixtures live with this crate.

## Frozen graph boundary

The crate accepts an immutable asserted-graph snapshot and never imports a
Phoenix persistence or mutation crate. Relation-aware incoming CSR is packed in
a read-only mmap artifact. Dense updates split their concatenated weight matrix
by columns and operate in node tiles, so no `N x 2048` update or `N x 3072`
scoring tensor is created.

G-reasoner ranks nodes of the requested type directly. Unlike GFM-RAG-8M, this
checkpoint has no reciprocal-frequency entity-to-document projection. The
parity proof therefore checks exact typed-node top-20 membership and final
ordering instead of inventing an incompatible document-scoring stage.

## Verification

```powershell
$crate = 'C:\code land\clean-rust\rust-native\phoenix-spikes\g-reasoner-34m-parity'
$env:CARGO_TARGET_DIR = 'D:\phoenix-target-g-reasoner-34m\cargo'
cargo test --locked --manifest-path "$crate\Cargo.toml"
cargo test --locked --features qwen --manifest-path "$crate\Cargo.toml" --test qwen_parity -- --ignored --nocapture
cargo run --locked --release --manifest-path "$crate\Cargo.toml" --bin g-reasoner-perf
```

The Qwen feature preserves the checkpoint's exact query instruction, performs
last-token pooling, and L2-normalizes to 1024 dimensions. It is optional and was
added only after the graph-core parity gate passed.
