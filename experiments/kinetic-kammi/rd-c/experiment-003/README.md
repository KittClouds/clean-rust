# R&D-C / Experiment 003 — Disagreement Gate

Standalone paired evaluation of four routing policies over a fixed, held-out synthetic workflow bank. Every lane uses Experiment 002's versioned observer boundary, compiled authority, hash-chained task journal, action ledger, and replay path. Experiment 002 source is a path dependency and its input fingerprints are recorded in `BASELINE.md`.

## Run

```powershell
cargo test --manifest-path C:\rd-c\experiment-003\Cargo.toml --target-dir D:\cargo-targets\rd-c-experiment-003
cargo run --release --manifest-path C:\rd-c\experiment-003\Cargo.toml --target-dir D:\cargo-targets\rd-c-experiment-003 --bin rdc003-bench
```

The benchmark compares `never`, `disagreement`, `confidence_threshold`, and `random_matched` on the same episode IDs. The random schedule is generated from the observer disagreement count and a fixed BLAKE3 seed before labels are scored. It escalates exactly as often as the disagreement lane.

The observer inputs and independent workflow labels are written to separate CSV files. Held-out labels come from the task contract `(goal, authoritative world revision) -> correct next action`; the label value is not passed to either observer, the router, or the resolver. Frozen observer IDs are `tool-follow/v1` and `audit-filter/v1`. Resolver ID is `workflow-contract-resolver/v1`.

The synthetic action choices map to Experiment 002's typed actions: `Execute` = `use_primary`, `Verify` = `verify_record`, and `Observe` = `refresh_snapshot`. The experiment-specific compiled schema makes all three legal at the focal decision state. A wrong legal choice produces a failed task outcome; authority illegality is measured separately against that schema.

The deterministic contract resolver uses no language model, so its token and API cost are zero. The report measures local wall time, observer time, resolver time, durable journal bytes, call count, wrong legal actions, completion, and replay identity. This is a controlled routing test, not an estimate of learned observers or large-model economics.

Each run is preserved under `artifacts/runs/` with input and label banks, route plan, per-task Experiment 002 journals/action ledgers, decision traces, a run manifest, and report. The most recent report is copied to `artifacts/benchmark-report.md`.
