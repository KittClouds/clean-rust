# R&D-C / Experiment 009 — Real Semantic Observer

E009 asks whether one frozen small semantic observer can improve coding-workflow decisions on repository snapshots with executable completion checks.

The authority base is the E002 switchboard and deterministic state machine. Observer outputs are typed action proposals with separate action-choice, applicability, and abstention fields. The model cannot write workflow state or bypass deterministic authority. E008 remains sealed; its held-out collision is preserved in the E008 report.

Paid inspection routing is disabled in `RuntimePolicy::default()`. Enabling it requires an explicit policy value. Typed outcomes and the stable-ID receipt contract remain available as reusable infrastructure.

## Lanes

1. Hand-written workflow policy.
2. Frozen small observer.
3. Frozen small observer with a larger reasoner only after observer abstention.
4. Always-large reasoning.

All lanes use the same frozen tasks, snapshots, tool/action schemas, deterministic authority, and receipt policy. Shadow replay precedes isolated execution. Held-out repositories or task families stay outside threshold fitting.

## Current status

The two-task local pilot is frozen before model contact. Task and candidate hashes, held-out labels, input-leak audit, small and large observer bundles, prompts, schema, and authority preflight are recorded under `artifacts/runs/e009-20260925-pilot-01`.

| Task family | Frozen base |
| --- | --- |
| Asynchronous GPU picking | `1344f4710148679f7cf0301f57c25b15b23188d4` |
| Embedding length-batched execution | `0263e3884d5370f7a9bd2c2217527f4fd87ab33d` |

The label-side audit confirms that the passing option position varies by task; the observer receives no labels. The bank has one task per family and no development tasks, so it is an exploratory pilot only.

MiniCPM5-2B-Q8_0 is recorded as `qualified_for_live_trial`. Ternary-Bonsai-2-27B-PTQ1_0 is recorded as `experimental_runtime_only`; that limit remains visible in the report. The JSON output fields are constrained generated fields with fixed deterministic thresholds, not separately trained heads.

E008 remains sealed. Paid inspection is disabled by default. See `E008_CLOSEOUT.md` for the carried-forward result and [SPEC.md](SPEC.md) for the frozen E009 contract.

Run package checks with `cargo test --manifest-path Cargo.toml --all-targets` and `cargo clippy --manifest-path Cargo.toml --all-targets -- -D warnings`. Cargo output is directed to `D:\cargo-targets\rdc-e009`; source and experiment artifacts stay under `C:\rd-c\experiment-009`.
