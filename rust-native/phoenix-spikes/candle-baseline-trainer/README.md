# Phoenix Candle Baseline Trainer

This isolated Candle 0.11 trainer consumes frozen Phoenix research artifacts and
emits `phoenix-frozen-model/v1`.

The hyper-relational lane also provides the immutable paired CompGCN/StarE trainer
and the eight-arm `qualifier-signal-matrix` isolation experiment. Its frozen
intervention and replay contract is documented in
`docs/qualifier-signal-isolation-matrix-v1.md`.

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

The command prints a JSON training/performance report with training and scoring
latency, allocation volume, Windows peak working set, exact source/weight mmap bytes,
and exact-sized dense staging bytes. The output directory receives the immutable
model manifest and mmap weight blob. Default training parameters are 24 epochs,
batch size 32, learning rate 0.025, and L2 0.0005.

The topology-aware rung uses the same authority plus the finalized baseline ledger
and its selected validation manifest:

```powershell
cargo run --release --bin candle-rgcn-trainer -- `
  <graph-manifest> <tensor-manifest> <evaluation-protocol> `
  <topology-manifest> <output-directory> <selected-repeat> `
  <baseline-selection-ledger> <selected-baseline-manifest>
```

It stages asserted train COO edges and resolved train incidences once, trains the
fixed R-GCN-16, requires an AP/Brier win over the ledger-selected MLP, and certifies
scores with the trainer-independent SIMD evaluator.

Run verification with:

```powershell
$env:CARGO_TARGET_DIR = 'D:\phoenix-target-overgraph'
cargo test --locked --all-targets
cargo clippy --locked --all-targets --no-deps -- -D warnings
```

See `docs/candle-baseline-trainer-v1.md` and
`docs/candle-trainer-performance-reproducibility-gate-v1.md` for the frozen contract
and evidence. See `docs/candle-rgcn-v1.md` for the first learned graph rung.
