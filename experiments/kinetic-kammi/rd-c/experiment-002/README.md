# R&D-C / Experiment 002 — Observer Switchboard

Standalone paired-task runtime built on a fingerprinted Experiment 001 source snapshot.

The observer boundary records protocol version, implementation ID, input/output schema IDs, and normalization contract. The active and shadow observers receive the same recorded observation. Only the active proposal reaches deterministic authority. Observer swaps are recorded as registry epochs.

Actions follow a durable intent → simulated effect ledger → completion protocol. Action IDs are deterministic and the simulated action ledger deduplicates retries after crashes. Resume replays recorded proposals and receipts, then completes any pending idempotent action before accepting new observations.

## Run

From this directory:

- cargo test --target-dir D:\cargo-targets\rd-c-experiment-002
- cargo run --release --target-dir D:\cargo-targets\rd-c-experiment-002 --bin rdc002-demo
- cargo run --release --target-dir D:\cargo-targets\rd-c-experiment-002 --bin rdc002-bench

The benchmark runs paired complete tasks for the compiled runtime and hand-written controller with the same observers, observations, durable action simulator, and journal policy. It writes a Markdown report under artifacts.

The report separates workflow-level recoveries from process resumes after injected crashes.

The simulator's effect ledger represents an idempotent external action endpoint. Exactly-once effects depend on that endpoint honoring the action ID. A general non-idempotent external side effect cannot be made exactly once by a local journal alone.
