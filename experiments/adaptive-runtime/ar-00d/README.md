# AR-00D — Commit Granularity

AR-00D uses the same action vocabulary and exact singleton finite-effect
utility definition as C3, and changes only how many independently evaluated
actions may commit before utility is recomputed.

The D0 implementation deliberately evaluates every candidate against one
unchanged model snapshot and commits the selected actions simultaneously. This
is the literal simultaneous-commit control. It is not expected to reproduce an
implementation whose candidate loop mutates the model while it is still
selecting actions; that distinction is part of the commit-granularity audit.

| Policy | Commit schedule |
| --- | --- |
| D0 | all selected actions simultaneously |
| D1 | fixed-order batches of 8 |
| D2 | fixed-order batches of 4 |
| D3 | fixed-order batches of 2 |
| D4 | fixed-order singleton actions |
| D5 | globally best singleton action, recomputed each microstep |

Each outer epoch gives a policy at most 17 committed actions, preserving the
AR-00 parameter-scale budget. The report records predicted singleton utility,
realized utility, composition error, refresh count, and terminal metrics.

## Run

```powershell
$env:CARGO_TARGET_DIR = 'D:\adaptive-runtime-target'
cargo test --release
cargo run --release
cargo bench --bench ar00d
```

This is engineering-only evidence. It does not establish a general optimizer
claim or any biological correspondence.
