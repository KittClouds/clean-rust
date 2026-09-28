# R&D-C Experiment 006 — Inspection Under Failure

E006 attacks the E005 domain-value result with imperfect and shifted inspection sources. Five routing lanes share a held-out bank and exact call budgets: the frozen E005 domain table, a smoothed development estimate, a small feature model, matched random, and a no-inspection floor.

The source fixtures are written and closed before scoring. Public frames omit fixture outcomes. The four held-out domains 8–11 are absent from development. Inspection results are typed as `Confirmed`, `Contradicted`, `Unknown`, or `Failed`; ambiguous, unavailable, or invalid results propose a guarded transition back to `OBSERVING` and cannot authorize the original task action.

## Run

```powershell
cargo test --manifest-path C:\rd-c\experiment-006\Cargo.toml --target-dir C:\rd-c\experiment-006\target
cargo clippy --manifest-path C:\rd-c\experiment-006\Cargo.toml --target-dir C:\rd-c\experiment-006\target --all-targets -- -D warnings
cargo run --release --manifest-path C:\rd-c\experiment-006\Cargo.toml --target-dir C:\rd-c\experiment-006\target --bin rdc006-bench
```

The `target` junction stores build output under `D:\cargo-targets\rd-c-experiment-006`. Each benchmark run writes a new immutable directory under `artifacts/runs/e006-<timestamp>`.

## Query crash contract

The harness persists a query intent and attempt receipt before calling the simulated inspection endpoint. The endpoint caches its paid response by stable query ID in a separate durable ledger. If the process stops after the endpoint has charged and returned but before the local result receipt is durable, recovery retries the same ID, reads the endpoint's cached response, records the retry and outcome, and pays no second charge. A non-idempotent live endpoint would need a separate contract; the local result does not claim exactly-once behavior for such a service.

Query charge units, endpoint attempts, retries, resolver calls, and task action effects are reported separately. Query budgets count distinct paid query IDs. Unknown and failed outcomes do not execute task actions.
