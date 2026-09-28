# FAS-00 — Frozen Adaptive Substrate Baseline

> **New information ≠ new representation.**  
> **Δθ_LFM = 0.**

Identity: `fas-frozen-adaptive-substrate-v00`. This directory is an independent experiment. The pinned backbone is a future sensor, never the learner. FAS-00 first tests what bounded external state, memory, and readouts can achieve without backbone writes.

Current authority: **pre-model-contact construction only**. `FAS00_MODEL_CONTACT_AUTHORIZED = false`.

The first pass contains the frozen protocol, exact-world generator, independent validator, feature/resource/metric contracts, mechanism interfaces, scheduler, local tests, and pre-model-contact seal. It contains no LFM features, heads, checkpoints, or evaluation results.

Run local smoke and tests with the isolated D: target:

```powershell
$env:CARGO_TARGET_DIR='D:\codex-runs\fas-frozen-adaptive-substrate-v00\target'
cargo test --release
cargo run --release -- smoke
```

`target` is a local junction to this project's D: target directory. No other project is a dependency.

