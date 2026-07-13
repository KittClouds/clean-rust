# Phoenix Candle Baseline Trainer

This isolated Candle 0.11 trainer consumes frozen Phoenix research artifacts and
emits `phoenix-frozen-model/v1`.

```powershell
$env:CARGO_TARGET_DIR = 'D:\phoenix-target-candle-trainer'
cargo run --release --manifest-path .\Cargo.toml -- `
  <graph-manifest> `
  <tensor-manifest> `
  <evaluation-protocol> `
  <topology-manifest> `
  <output-directory> `
  <selected-repeat>
```

The command prints a JSON training/performance report. The output directory receives
the immutable model manifest and mmap weight blob. Default training parameters are
24 epochs, batch size 32, learning rate 0.025, and L2 0.0005.

Run verification with:

```powershell
$env:CARGO_TARGET_DIR = 'D:\phoenix-target-overgraph'
cargo test --locked --all-targets
cargo clippy --locked --all-targets --no-deps -- -D warnings
```

See `docs/candle-baseline-trainer-v1.md` for the frozen contract and evidence.
