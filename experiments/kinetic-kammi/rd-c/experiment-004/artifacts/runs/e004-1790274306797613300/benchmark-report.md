# R&D-C Experiment 004 — Information Boundary and Routing Test

## Decision boundary

The Experiment 002 runtime authority owns workflow state and recovery count. Its contract has no trusted task/world revision input. Experiment 003 encoded the revision inside observation evidence, so that was not an independent authority signal. E004 therefore keeps truth revision and correct-action labels in a separate evaluation file; neither observer nor resolver receives them. No deterministic stale-revision guard can be compiled until the production runtime contract supplies a trusted revision.

The public frame contains goal, source recommendations, source-reported revisions, age buckets, and warning bits. Both frozen observers and the resolver receive the same frame. The resolver's only tools are `inspect_evidence(1)` and `inspect_evidence(2)`, which return the corresponding recorded recommendation, reported revision, age, warning, and content marker. The resolver chooses the least-warned/youngest source, with source 1 as the final tie-break. When evidence appears fresh, it applies the public goal/revision contract; when sources report age or warning signals, it requests a refresh. It does not see either observer proposal or evaluation label.

The witness emits only `NoSignal` or `InspectEvidence(source_id, reason)`. It flags agreement on the same cited source when its visible age is nonzero, it carries a warning, or its recommendation conflicts with the public goal/reported-revision contract. It cannot name an action or state.

## Frozen workload and methods

- Fresh held-out bank: 128 episodes, 8 strata × 16, seed `0xE40420260924`.
- Four fixed resolver-call budgets: 16, 32, 48, 64. Every policy receives the identical selected episode IDs per budget; random uses a BLAKE3-ranked fixed ordering.
- Policies: disagreement, confidence need, combined (witness first, then disagreement, then confidence need), and matched random. Call plans use only public episode features and are frozen before labels are scored.
- Same Experiment 002 compiled authority, action simulator, journal format, and replay procedure in every lane.
- Observers are deterministic frozen proxies; the resolver is deterministic local code. This measures the routing harness, not an LLM deliberator. Model calls, model tokens, and external inference cost are zero by construction.


## Paired results

| Policy | Calls / budget | Completion | Wrong legal actions | Illegal commits | Rejections | Duplicate / missing actions | Replay identity | p50 / p95 task ms | Observer μs / task | Resolver μs / call | Tools / task | Tokens / task | Mean journal bytes | External cost |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| disagreement | 16 / 128 | 83/128 (64.8%) | 45 | 0 | 0 | 0 / 0 | 128/128 | 35.216 / 41.787 | 0.00 | 0.00 | 0.25 | 0.00 | 98.2 | $0.0000 |
| disagreement | 32 / 128 | 87/128 (68.0%) | 41 | 0 | 0 | 0 / 0 | 128/128 | 35.772 / 41.722 | 0.00 | 0.00 | 0.50 | 0.00 | 98.8 | $0.0000 |
| disagreement | 48 / 128 | 91/128 (71.1%) | 37 | 0 | 0 | 0 / 0 | 128/128 | 35.353 / 40.988 | 0.01 | 0.00 | 0.75 | 0.00 | 99.4 | $0.0000 |
| disagreement | 64 / 128 | 96/128 (75.0%) | 32 | 0 | 0 | 0 / 0 | 128/128 | 34.776 / 41.513 | 0.00 | 0.00 | 1.00 | 0.00 | 100.2 | $0.0000 |
| confidence | 16 / 128 | 80/128 (62.5%) | 48 | 0 | 0 | 0 / 0 | 128/128 | 34.785 / 41.646 | 0.01 | 0.00 | 0.25 | 0.00 | 97.7 | $0.0000 |
| confidence | 32 / 128 | 80/128 (62.5%) | 48 | 0 | 0 | 0 / 0 | 128/128 | 35.029 / 41.426 | 0.00 | 0.00 | 0.50 | 0.00 | 97.7 | $0.0000 |
| confidence | 48 / 128 | 84/128 (65.6%) | 44 | 0 | 0 | 0 / 0 | 128/128 | 34.721 / 40.949 | 0.01 | 0.00 | 0.75 | 0.00 | 98.3 | $0.0000 |
| confidence | 64 / 128 | 91/128 (71.1%) | 37 | 0 | 0 | 0 / 0 | 128/128 | 34.636 / 40.172 | 0.00 | 0.00 | 1.00 | 0.00 | 99.4 | $0.0000 |
| combined | 16 / 128 | 80/128 (62.5%) | 48 | 0 | 0 | 0 / 0 | 128/128 | 35.195 / 42.295 | 0.01 | 0.00 | 0.25 | 0.00 | 97.7 | $0.0000 |
| combined | 32 / 128 | 96/128 (75.0%) | 32 | 0 | 0 | 0 / 0 | 128/128 | 36.305 / 44.947 | 0.01 | 0.00 | 0.50 | 0.00 | 100.2 | $0.0000 |
| combined | 48 / 128 | 96/128 (75.0%) | 32 | 0 | 0 | 0 / 0 | 128/128 | 35.762 / 43.350 | 0.00 | 0.00 | 0.75 | 0.00 | 100.2 | $0.0000 |
| combined | 64 / 128 | 102/128 (79.7%) | 26 | 0 | 0 | 0 / 0 | 128/128 | 35.218 / 43.083 | 0.00 | 0.00 | 1.00 | 0.00 | 101.1 | $0.0000 |
| random_matched | 16 / 128 | 83/128 (64.8%) | 45 | 0 | 0 | 0 / 0 | 128/128 | 35.285 / 40.389 | 0.00 | 0.00 | 0.25 | 0.00 | 98.2 | $0.0000 |
| random_matched | 32 / 128 | 86/128 (67.2%) | 42 | 0 | 0 | 0 / 0 | 128/128 | 34.671 / 44.899 | 0.00 | 0.00 | 0.50 | 0.00 | 98.6 | $0.0000 |
| random_matched | 48 / 128 | 91/128 (71.1%) | 37 | 0 | 0 | 0 / 0 | 128/128 | 36.652 / 45.071 | 0.01 | 0.00 | 0.75 | 0.00 | 99.4 | $0.0000 |
| random_matched | 64 / 128 | 99/128 (77.3%) | 29 | 0 | 0 | 0 / 0 | 128/128 | 35.768 / 43.613 | 0.00 | 0.00 | 1.00 | 0.00 | 100.7 | $0.0000 |

Observer/resolver times are instrumented local wall-clock intervals and will be noisy at this scale. Task p50/p95 include durable journaling and contract-aware replay. Resolver tool calls are local reads; external model cost is zero.

## Equal-budget paired deltas vs matched random

| Budget | Policy | Completion delta | Paired wins / losses / ties | Wrong-action delta |
|---:|---|---:|---:|---:|
| 16 | disagreement | +0 | 2 / 2 / 124 | +0 |
| 16 | confidence | -3 | 0 / 3 / 125 | +3 |
| 16 | combined | -3 | 0 / 3 / 125 | +3 |
| 32 | disagreement | +1 | 5 / 4 / 119 | -1 |
| 32 | confidence | -6 | 0 / 6 / 122 | +6 |
| 32 | combined | +10 | 13 / 3 / 112 | -10 |
| 48 | disagreement | +0 | 7 / 7 / 114 | +0 |
| 48 | confidence | -7 | 2 / 9 / 117 | +7 |
| 48 | combined | +5 | 11 / 6 / 111 | -5 |
| 64 | disagreement | -3 | 4 / 7 / 117 | +3 |
| 64 | confidence | -8 | 3 / 11 / 114 | +8 |
| 64 | combined | +3 | 11 / 8 / 109 | -3 |

## Shared-error pocket

On this bank, the frozen observers agreed on the same wrong action in 32 episodes. The witness requested evidence inspection in 32 and missed 0. Its signal is deliberately limited to visible age/warning metadata: a fresh misleading source can still fool both observers without triggering it.

## Gate checks

- Exact call budgets in every lane: **PASS**
- Illegal commits: **0**
- Duplicate actions: **0**
- Replay identity failures: **0**
- Missing actions: **0**

## Limits and promotion boundary

This is a synthetic routing benchmark over 128 procedurally generated episodes and hand-coded observers/resolver. It can compare routing rules and verify the authority/replay contract; it cannot estimate production observer quality, real model token cost, or whether disagreement predicts errors in naturally occurring tasks. The resolver does not receive a truth revision. Because the current authority lacks that field, E004 does not claim deterministic stale-revision rejection. The witness is a routing proposal, not authority. Promotion requires the reported paired result plus an external runtime contract that explicitly supplies authoritative revision before adding a stale guard.

