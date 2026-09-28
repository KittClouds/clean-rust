# AR-00A — Action Granularity

AR-00A freezes the AR-00 MLP, initialization, XOR dataset, backpropagated
gradients, bounds, utility rule, and 3,000 update steps. It changes only the
primitive action vocabulary.

| Arm | Candidate magnitudes |
| --- | --- |
| A0 | `±s` |
| A1 | `±s`, `±s/2` |
| A2 | `±s`, `±s/2`, `±s/4` |
| A3 | `±s`, `±s/2`, `±s/4`, `±s/8`, `±s/16` |
| A4 | AdamW control |

Here `s = 0.02`, the no-op is implicit, and every arm uses the same bounds
`[-3, 3]` and first-order utility `-gradient * delta`.

The experiment records loss curves, selected magnitude, no-ops, bound blocks,
sign reversals, action counts by scale, and final logits/margins. A0 is also
checked against the frozen AR-00 implementation as a parity fixture.

## Run

```powershell
$env:CARGO_TARGET_DIR = 'D:\adaptive-runtime-target'
cargo test --release
cargo run --release
cargo bench --bench ar00a
```

The executable writes `artifacts/ar-00a-report.json` and
`artifacts/ar-00a-curves.csv`. This is engineering-only evidence about action
granularity, not evidence for Drosophila or a general optimizer claim.
