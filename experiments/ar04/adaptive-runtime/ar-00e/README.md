# AR-00E — Structural Action Groups

AR-00E keeps the XOR MLP and exact finite-effect action evaluation, then
compares four schedulers under the AR-00D primitive-action budget of 17 per
outer epoch:

| Arm | Scheduler |
| --- | --- |
| E0 | AR-00D D5 global singleton-greedy parity control |
| E1 | global singleton-or-pair scheduler |
| E2 | structural groups: four hidden-unit groups of size 3 plus five output singletons |
| E3 | deterministic randomized groups with the same sizes as E2 |

E1 uses the best exact singleton action for each parameter and exact pair
effects for those candidate actions. E2 and E3 enumerate the full finite action
vocabulary for each group. A group program consumes its group size from the
17-primitive budget, and utility is recomputed after every committed program.

E3 is the size-matched label-permutation control for E2. No coalition result is
fed back into Drosophila science.

## Run

```powershell
$env:CARGO_TARGET_DIR = 'D:\adaptive-runtime-target'
cargo test --release
cargo run --release
cargo bench --bench ar00e
```
