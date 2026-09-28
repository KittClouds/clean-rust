# FAS-R1 Stage1 stress worlds V05

This is a separate deterministic generator. It depends on the frozen Stage0 `r1-world` crate by path and does not alter Stage0, V04, or any existing run bundle.

## Roster and pairing

The roster is a balanced 2×2 factorial: base/dense graph density crossed with an independent random initial assignment / an explicit witness-derived module-1 role-swap trap. It generates 24 underlying graph seeds and four task variants per seed. All four variants share one `paired_world_id` and split; the 16/4/4 underlying-seed split yields 64/16/16 task rows. Task and family IDs remain unique per variant.

All tasks are `n=20`, `k=3`, role-anonymous, and use only `Different` clauses. Full exact enumeration must produce 54 raw assignments and 9 classes under six role automorphisms. The dense overlay adds ten edges between modules 0 and 2 implied by their existing relative-color lock.

## Declared search starts

`public-search-starts-v05.jsonl` is a separate public planner input keyed by `task_id`; the `InferenceTask` schema remains unchanged. It contains one explicit assignment and `start_kind` for every task. The independent random assignment is drawn uniformly from the three roles using SplitMix64 seeded by `world_seed XOR initial_state_seed_tag`; the same assignment is reused in the base and dense variants of a paired world. The runner should pass these exact sidecar bytes to every arm while action-stream RNG salts remain arm-specific. The sidecar is declared search state and is excluded from sensor extraction.

The swap-trap assignment applies the configured role-0/role-1 permutation to module 1 of the planted witness. It has exactly two bridge conflicts, and restoring either changed anchor alone leaves two conflicts. This is an intentionally witness-derived warm-start basin diagnostic exposed as the planner's initial state. It is not a hidden oracle and this stress cell is not no-leakage generalization. The private planted witness, anchor mapping, and conflict-clause indices remain in `private-diagnostics.jsonl`.

The V05.1 support-manifest repair keeps `split_counts` to exactly `train`, `validation`, and `qualification` for extractor compatibility; `paired_world_count` is a separate top-level field. Its distinct schema is `R1_STAGE1_STRESS_SENSOR_SUPPORT_V05_1`, emitted as `stress-support-manifest-v05-1.json`. The private receipt is versioned `R1_STAGE1_STRESS_GENERATION_V05_1` and binds the repaired manifest, public task projection, public search-start sidecar, config, and source hashes. V04 proposal/refit consumers pin V04 schemas and hashes; this bundle is not an input to those consumers. Generation alone does not run a sensor, train, evaluate a model, or run a pilot.

## Commands

```powershell
$root = 'C:\Users\shuga\.codex\worktrees\fas-r1-stage0-20260925\clean-rust\experiments\fas-r1-semantic-particle-reachability-v00\stage1-v01'
$env:CARGO_TARGET_DIR = 'G:\cargo-targets\fas-r1-stage1-stress-worlds-v05'
cargo fmt --manifest-path "$root\stress-worlds-v05\Cargo.toml" --check
cargo test --manifest-path "$root\stress-worlds-v05\Cargo.toml" --release
cargo clippy --manifest-path "$root\stress-worlds-v05\Cargo.toml" --release --all-targets -- -D warnings
cargo build --manifest-path "$root\stress-worlds-v05\Cargo.toml" --release
cargo run --manifest-path "$root\stress-worlds-v05\Cargo.toml" --release -- --config "$root\stress-worlds-v05\configs\stress-config-v05.json" --output 'D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-vXXX-stress-worlds-v05-1-v01'
```

The generator requires a new output directory and refuses to overwrite one. The generation command writes private task/diagnostic files, the public task projection, public search-start sidecar, config copy, support manifest, and source/output-hash receipt.
