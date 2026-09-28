# AR-00B — Sign-Only Equivalence

AR-00B replaces AR-00 candidate enumeration and utility ranking with the
direct rule:

```text
g > 0  -> -s
g < 0  -> +s
g = 0  -> no-op
```

It keeps the AR-00 MLP, initialization, dataset, gradients, bounds, action
step, and 3,000 updates unchanged. The purpose is semantic qualification: does
AR-00 reduce to bounded fixed-step sign descent?

## Run

```powershell
$env:CARGO_TARGET_DIR = 'D:\adaptive-runtime-target'
cargo test --release
cargo run --release
cargo bench --bench ar00b
```

This is engineering-only evidence. It does not establish a general optimizer
claim or any biological correspondence.
