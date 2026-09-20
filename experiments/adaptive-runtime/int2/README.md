# INT2 — Interaction Topology

INT2 quantifies the AR-00C-INT1 pair map instead of relying on visual
inspection. It reports harmful and synergistic rates, absolute interaction
magnitudes, quantiles, maxima, and epoch dependence for overlapping structural
views:

- same hidden unit;
- different hidden units;
- `W1` to `b1` within one hidden unit;
- `W1` to `W1` within one hidden unit;
- cross-layer (`W1`/`b1` to `W2`/`b2`);
- other pairs.

The parameter-label permutation control keeps the measured interaction values
fixed and shuffles the functional labels with a deterministic seed. It tests
whether category-level interaction magnitude exceeds a label-free null.

This is engineering-only evidence. It does not establish a general optimizer
claim or any biological correspondence.

## Run

```powershell
$env:CARGO_TARGET_DIR = 'D:\adaptive-runtime-target'
cargo test --release
cargo run --release
cargo bench --bench int2
```
