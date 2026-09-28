# AR-00C-INT1 — Pairwise Action Interaction Map

This diagnostic freezes the XOR MLP, the AR-00 C0 snapshot trajectory, and the
AR-00C multiscale action vocabulary. At deterministic snapshots it selects the
best finite-effect singleton action independently for every parameter, then
measures every parameter pair:

```text
interaction(i,j)
  = pair_loss_change - (singleton_i_loss_change + singleton_j_loss_change)
```

Positive interaction is harmful interference. Negative interaction is
synergy. A zero action is retained for parameters whose best singleton action
has no positive finite effect, so every snapshot has the complete 17-choose-2
map (136 pairs).

This is engineering-only evidence. It does not establish a general optimizer
claim or any biological correspondence.

## Run

```powershell
$env:CARGO_TARGET_DIR = 'D:\adaptive-runtime-target'
cargo test --release
cargo run --release
cargo bench --bench ar00c_int1
```
