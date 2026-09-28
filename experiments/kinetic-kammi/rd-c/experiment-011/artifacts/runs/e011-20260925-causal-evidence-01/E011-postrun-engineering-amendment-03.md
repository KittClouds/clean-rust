# E011 Postrun Engineering Amendment 03

- Parent run: `e011-20260925-causal-evidence-01`.
- Classification: downstream runtime integration and bounded fresh-bank qualification.
- The sealed E011, E011-R1, E011-R2, and E011-R3 inputs, outputs, and reports were not edited. This amendment does not change their scientific or transfer claims.
- Frozen E009 v5 model bundles, prompt, output schema, normalization, routing rule, and 850/150 thresholds were reused without fitting or modification.

## Producer-order integration

The isolated live switchboard adapter is implemented in [the runtime integration crate](../../repairs/producer-order-v1/runtime-integration). Candidate options carry producer ordinals assigned at frame construction. The runtime restores ascending producer order before serialization and creates a versioned candidate-presentation receipt binding the task digest, action IDs, patch identities, and exact sequence.

The request and response envelopes carry the request ID and receipt digest out of band, leaving the frozen observer prompt and output schema unchanged. Authority checks both bindings and the current ordered candidates before resolving the observer proposal. It also checks the binding on replay. Presentation mutation or a response replayed against a different presentation is rejected before action resolution and uses `ABSTAIN_AND_ABORT_ACTION`.

## Integration cases

All four cases passed through the Rust adapter and authority test path. The fresh qualification also sent every restored frame to the live local observer endpoints:

1. Normal producer order was accepted, authorized, and replayed identically.
2. A transport shuffle was restored before serialization; all four prepared observer frames matched their original bytes.
3. Reordering after receipt creation was rejected; the fallback ran and produced zero action effects.
4. Replaying an otherwise valid response against a different presentation was rejected; the fallback ran and produced zero action effects.

The four release integration tests passed. The test binary was built under `D:\cargo-targets\rdc-e011-runtime-integration`, copied to the C: artifact directory, and run there. Its SHA-256 is `39550eea99328e1e954c6c745df1c49a0bf82eb9bc60658dd411078e148f6307`. Release Clippy with `-D warnings` and package-local `cargo fmt -- --check` passed. No local observer server remained running after the run.

## Fresh integration qualification

Run: [integration qualification report](../../repairs/producer-order-v1/artifacts/runs/e011-producer-order-integration-qual-01/integration-qualification-report.md). Four new-to-the-observer frames were drawn from two task families in the same two locked Rust repositories used for E010. Each task family had two variants. Every frame was transport-permuted, restored to producer order, and receipt-bound before observer contact.

| Repository | Small coverage / precision | Small completion | Hybrid completion | Always-large completion | Hybrid large calls avoided | Wrong legal actions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ripgrep | 2/2 / 2/2 | 2/2 | 2/2 | 2/2 | 2 | 0 |
| turbovec | 2/2 / 2/2 | 2/2 | 2/2 | 2/2 | 2 | 0 |

Across the four tasks, the hybrid completed 4/4 and used zero large calls, compared with four large calls in the always-large lane. All 12 scored lane receipts were presentation-verified and replay-identical. There were zero illegal commits and zero duplicate action effects. Both repositories passed their separate gates.

Small-observer model time was 2.73 seconds pooled; always-large model time was 141.03 seconds. These are local observer timings, not paired end-to-end task latency, and are descriptive only. No speed or token-cost promotion claim is made.

## Integrity and limits

[The artifact verifier](../../repairs/producer-order-v1/scripts/verify_integration_artifacts.py) confirmed the frozen bank, prompt, schema, bundle, threshold, prepared-frame, and runtime source hashes; all eight observer RPC request/response bindings; all 12 authority receipts; and all four integration cases. The score-replay lock also matches the recorded observer-output and live completion-test trees.

This qualifies receipt enforcement and preservation of the known fast lane on four fixtures. It adds no new repository transfer evidence: there are only two underlying task families, both in the same two Rust repositories used by E010. It does not establish observer permutation invariance, semantic correctness from a receipt, a mechanism for the order effect, or broad transfer. If the switchboard enters a separate product runtime, that runtime's candidate producer still needs to carry ordinals and use this receipt at serialization and resume boundaries.
