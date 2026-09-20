# AR-00C — Finite-Effect Utility

AR-00C keeps the AR-00 MLP, initialization, XOR data, gradients, bounds,
multiscale action vocabulary, and 3,000 update steps fixed. It changes only
how a candidate action is scored.

The frozen multiscale vocabulary is:

```text
±0.02, ±0.01, ±0.005, ±0.0025, ±0.00125
```

Arms:

| Arm | Utility |
| --- | --- |
| C0 | `-g*delta` linear control |
| C1 | `-g*delta - 0.002*abs(delta)` |
| C2 | `-g*delta - 0.5*1.0*delta^2` |
| C3 | exact single-action full-batch loss improvement |

C3 is a diagnostic oracle, not an intended production optimizer. For each
parameter/action it evaluates the actual finite loss change, then commits the
best individually selected actions simultaneously.

Every step records predicted utility, realized full-batch utility, composition
error, selected scale, sign reversals, and final logits/margins. The report also
compares C0–C2 action choices against C3.

## Run

```powershell
$env:CARGO_TARGET_DIR = 'D:\adaptive-runtime-target'
cargo test --release
cargo run --release
cargo bench --bench ar00c
```

This is engineering-only evidence. It does not establish a general optimizer
claim or any biological correspondence.
