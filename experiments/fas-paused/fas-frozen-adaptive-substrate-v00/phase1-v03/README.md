# FAS-00 Phase 1 v03: world qualification

This is a versioned sidecar to the sealed first pass. It supersedes the partial diagnostic-only v02 tree `af42320abe28885d20a07c2c936ac130da707bf6347dd5bfe24644b06978bf21`, correcting the serialized readback path after v02 failed closed. The v02 tree records the earlier v01 audit corrections: context contrast at phase A, a 1% label-balance tolerance, and rendered-string leakage checks. It depends only on the sibling `fas00` crate whose pre-model seal is referenced in the corpus manifest. Do not edit the sealed root `src/`, `tests/`, contracts, or pre-model seal. Any generator change belongs in a new versioned artifact with an explicit supersession record.

The qualification-only materialization contains 8 world families × 2 task structures × 2 feedback conditions × 32 seeds = 1,024 worlds, each with 32 events. It is not authorized for Phase 5. Each event stores its latent state, rendered identities, candidate order, target, reveal step, and post-score visible feedback IDs. Per-world latent and rendered hashes are in the world manifest; each rendered event also has a content hash.

Run from the FAS root using the isolated D: target:

```powershell
$env:CARGO_TARGET_DIR='D:\codex-runs\fas-frozen-adaptive-substrate-v00\target'
cargo run --release --manifest-path .\phase1-v03\Cargo.toml -- qualify 'D:\codex-runs\fas-frozen-adaptive-substrate-v00\phase1-v03\corpus'
```

The output path must be empty. The builder performs two complete deterministic builds and fails closed on a mismatch. It performs no model contact. `seal-phase1.ps1` then hashes source, contracts, and qualification outputs and writes the final gate disposition; it refuses overwrite.
