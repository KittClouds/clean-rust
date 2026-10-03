# NORTHSTAR_RL_SURFACE_V1

FORGE-RL-01 adds the read-only `northstar-rl-broker` joint wind tunnel. See
[`docs/FORGE_RL_01.md`](docs/FORGE_RL_01.md) for authority boundaries, live
capture commands, offline replay, and the explicit MT5/live-comparison gap.

FORGE-RL-02 adds the inert strategy-experiment control plane: sealed partitions,
train-only transform state, experiment/campaign identities, precommitted
evaluation, policy artifact contracts, and batched Rust/PyO3 environment calls.
See [`docs/FORGE_RL_02.md`](docs/FORGE_RL_02.md). No learner is executed.

FORGE-RL-00 is Northstar's inert deterministic reinforcement-learning laboratory.
It compiles immutable market authority into typed features and episodes, executes
scripted actions in a Rust account machine, exposes a thin Gymnasium adapter, and
seals replay and qualification receipts. It deliberately does **not** execute a
learner.

The project is isolated from Phoenix publication authority and from the live
Northstar Desk. Production inputs must arrive through declared RunRaw manifests;
the included synthetic corpus exists only for hand-computable qualification.

```powershell
$env:CARGO_TARGET_DIR = 'D:\northstar-rl-target'
cargo test --workspace
cargo run --release -p northstar-rl-cli -- qualify artifacts
```

Python qualification is performed in a project-local environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e '.[qualification]'
.\.venv\Scripts\python -m northstar_rl.qualify artifacts\environment_config.json
```

The public CLI surface is:

```text
northstar-rl tape-inspect <runraw.nrr1>
northstar-rl feature-compile <output-dir>
northstar-rl episode-build <output-dir>
northstar-rl env-verify <output-dir>
northstar-rl replay <output-dir>
northstar-rl benchmark <output-dir>
northstar-rl qualify <output-dir>
northstar-rl seal <output-dir>
```
