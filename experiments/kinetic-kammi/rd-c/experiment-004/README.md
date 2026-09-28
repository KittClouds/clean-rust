# R&D-C Experiment 004 — Information Boundary and Routing Test

E004 compares four frozen resolver-routing rules at identical call budgets over one fresh, paired task bank. Every lane uses the Experiment 002 compiled authority, action simulator, durable journals, and contract-aware replay.

## Information boundary

The source audit found that the Experiment 002 authority owns workflow state and recovery count, but does not accept or store the task's authoritative world revision. Experiment 003 put `world_revision` inside observation evidence, which made it visible to the resolver and did not create an independent runtime authority signal. E004 keeps the truth revision and correct action in a separate evaluator label file. Observers, witness, and resolver see only the public observation frame and the two fixed read-only evidence queries.

E004 does not claim deterministic stale-revision rejection. That needs a production contract change that supplies a trusted revision to authority. The evidence witness can still use visible source age, warning, and consistency with the public goal/reported-revision rule to propose `InspectEvidence`; it has no action or state field.

## Reproduce

From PowerShell:

```powershell
cargo test --manifest-path C:\rd-c\experiment-004\Cargo.toml --target-dir D:\cargo-targets\rd-c-experiment-004
cargo run --release --manifest-path C:\rd-c\experiment-004\Cargo.toml --target-dir D:\cargo-targets\rd-c-experiment-004 --bin rdc004-bench
```

Source and evaluation artifacts are under `C:\rd-c\experiment-004`; Cargo output is directed to `D:\cargo-targets\rd-c-experiment-004`. Each run gets an immutable folder under `artifacts\runs\e004-*`, with public episodes, separate hidden labels, precomputed routing plans, per-task E002 journals/action ledgers, a row-level run trace, report, and BLAKE3 manifest. The latest report is copied to `artifacts\benchmark-report.md`.

## Frozen design

- 128 fresh held-out episodes in eight 16-episode strata; seed `0xE40420260924`.
- Budgets: 16, 32, 48, and 64 resolver calls per 128 episodes.
- Policies: disagreement, confidence need, combined witness/disagreement/confidence, and BLAKE3-ranked matched random.
- Plan construction accepts episodes only; it has no label input. The harness writes the public bank and exact policy/budget plans before the separate evaluation module generates the hidden labels. Every plan selects exactly its budget count.
- Both observers receive the same observation. Resolver queries, when routed, inspect source IDs 1 and 2 only.
- Observer and resolver implementations are deterministic local proxies. No LLM calls or external inference costs are represented.
- Results include task completion, wrong legal action, illegal commits, action duplication/missing actions, replay identity, p50/p95 task time, observer/resolver/tool time, calls, tokens, and journal bytes.

The report is a synthetic engineering result. It does not estimate natural task error rates or support a mechanistic claim.
