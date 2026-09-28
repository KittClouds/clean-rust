# Phoenix Native Workspace

This is the active native Rust workspace.

- Use `rust-native/phoenix` for the active overgraph-first ingest, graph, kernel, retrieval, and sidecar work.
- The old mixed workspace remains in `rust/phoenix` as legacy/wasm history and compatibility reference.
- Shared crates that native still depends on were copied here on purpose so active work can stay isolated from the old tree.

Current native entrypoints:

- `crates/phoenix-api`
- `crates/phoenix-ingest-overgraph`
- `crates/phoenix-store-overgraph`
- `crates/phoenix-graph-post`
- `crates/phoenix-graph-kernel`

Rule of thumb:

- Native changes go here first.
- Only touch `rust/phoenix` when explicitly working on wasm or old compatibility surfaces.
- Legacy runtime- and LMDB-era crates were removed from this workspace to keep the active surface clean.
