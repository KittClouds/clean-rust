# Candle vs Burn Graph Runtime Spike v1

This isolated crate compares Candle 0.11 CPU with Burn 0.21 Flex CPU over the exact
`phoenix-train-topology-features/v1` mmap artifact and the authoritative Phoenix
ranking evaluator. Neither runtime enters the Phoenix production workspace.

The model is deliberately narrow and identical on both sides:

```text
[rows, 16] x [16, 16] -> ReLU -> x [16, 1] -> [rows]
```

Weights, input rows, warmups, iteration count, scalar reference, BLAKE3 score
certificate, and ranking evaluation are shared. The mapped fixed-width records are
validated without copying. Their interleaved metadata means the 16 feature columns
must be materialized once into a dense tensor; the adapters consume that allocation
without cloning it.

## Build on the fast target drive

```powershell
$env:CARGO_TARGET_DIR='D:\phoenix-candle-spike-release-v1'
cargo build --release --manifest-path rust-native/phoenix-spikes/candle-burn-graph-runtime/Cargo.toml --locked --no-default-features --features candle-runtime --bin candle-graph-spike

$env:CARGO_TARGET_DIR='D:\phoenix-burn-spike-release-v1'
cargo build --release --manifest-path rust-native/phoenix-spikes/candle-burn-graph-runtime/Cargo.toml --locked --no-default-features --features burn-runtime --bin burn-graph-spike
```

## Run

Arguments are `queries warmups iterations`; each query produces one positive and one
negative candidate row.

```powershell
D:\phoenix-candle-spike-release-v1\release\candle-graph-spike.exe 20000 10 100
D:\phoenix-burn-spike-release-v1\release\burn-graph-spike.exe 20000 10 100
```

The executable fails closed on output-shape drift, scalar error above `1e-4`, corrupt
artifact identity, or an unevaluable ranking batch.

See [the decision record](../../../docs/candle-vs-burn-graph-runtime-spike-v1.md)
and [the benchmark certificate](results/cpu-5800x3d-v1.json).
