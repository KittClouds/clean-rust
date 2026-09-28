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

| Policy | Calls / budget | Completion | Wrong legal actions | Illegal commits | Rejections | Duplicate / missing actions | Replay identity | p50 / p95 task ms | Observer ns / task | Resolver ns / call | Tools / task | Tool ns / call | Tokens / task | Journal bytes / task | Cost / completed task |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| disagreement | 16 / 128 | 83/128 (64.8%) | 45 | 0 | 0 | 0 / 0 | 128/128 | 38.314 / 43.415 | 5.0 | 4.7 | 0.25 | 0.4 | 0.00 | 98.1 | $0.000000 |
| disagreement | 32 / 128 | 87/128 (68.0%) | 41 | 0 | 0 | 0 / 0 | 128/128 | 37.625 / 43.355 | 5.3 | 4.7 | 0.50 | 0.3 | 0.00 | 98.8 | $0.000000 |
| disagreement | 48 / 128 | 91/128 (71.1%) | 37 | 0 | 0 | 0 / 0 | 128/128 | 39.155 / 57.726 | 5.6 | 5.0 | 0.75 | 0.4 | 0.00 | 99.4 | $0.000000 |
| disagreement | 64 / 128 | 96/128 (75.0%) | 32 | 0 | 0 | 0 / 0 | 128/128 | 40.242 / 46.349 | 5.3 | 4.5 | 1.00 | 0.3 | 0.00 | 100.2 | $0.000000 |
| confidence | 16 / 128 | 80/128 (62.5%) | 48 | 0 | 0 | 0 / 0 | 128/128 | 38.626 / 44.404 | 5.5 | 5.0 | 0.25 | 0.2 | 0.00 | 97.7 | $0.000000 |
| confidence | 32 / 128 | 80/128 (62.5%) | 48 | 0 | 0 | 0 / 0 | 128/128 | 38.140 / 45.880 | 5.2 | 4.7 | 0.50 | 0.4 | 0.00 | 97.7 | $0.000000 |
| confidence | 48 / 128 | 84/128 (65.6%) | 44 | 0 | 0 | 0 / 0 | 128/128 | 38.079 / 44.770 | 5.0 | 4.8 | 0.75 | 0.3 | 0.00 | 98.3 | $0.000000 |
| confidence | 64 / 128 | 91/128 (71.1%) | 37 | 0 | 0 | 0 / 0 | 128/128 | 39.034 / 45.834 | 5.2 | 4.8 | 1.00 | 0.3 | 0.00 | 99.4 | $0.000000 |
| combined | 16 / 128 | 80/128 (62.5%) | 48 | 0 | 0 | 0 / 0 | 128/128 | 37.719 / 45.147 | 5.1 | 5.1 | 0.25 | 0.2 | 0.00 | 97.8 | $0.000000 |
| combined | 32 / 128 | 96/128 (75.0%) | 32 | 0 | 0 | 0 / 0 | 128/128 | 39.114 / 45.046 | 5.0 | 4.9 | 0.50 | 0.4 | 0.00 | 100.2 | $0.000000 |
| combined | 48 / 128 | 96/128 (75.0%) | 32 | 0 | 0 | 0 / 0 | 128/128 | 39.712 / 46.830 | 5.2 | 4.7 | 0.75 | 0.3 | 0.00 | 100.1 | $0.000000 |
| combined | 64 / 128 | 102/128 (79.7%) | 26 | 0 | 0 | 0 / 0 | 128/128 | 38.756 / 45.444 | 7.7 | 4.6 | 1.00 | 0.3 | 0.00 | 101.1 | $0.000000 |
| random_matched | 16 / 128 | 83/128 (64.8%) | 45 | 0 | 0 | 0 / 0 | 128/128 | 37.724 / 45.662 | 5.1 | 4.7 | 0.25 | 0.4 | 0.00 | 98.2 | $0.000000 |
| random_matched | 32 / 128 | 86/128 (67.2%) | 42 | 0 | 0 | 0 / 0 | 128/128 | 38.353 / 45.166 | 5.1 | 4.8 | 0.50 | 0.3 | 0.00 | 98.7 | $0.000000 |
| random_matched | 48 / 128 | 91/128 (71.1%) | 37 | 0 | 0 | 0 / 0 | 128/128 | 44.405 / 976.506 | 5.3 | 5.0 | 0.75 | 0.3 | 0.00 | 99.4 | $0.000000 |
| random_matched | 64 / 128 | 99/128 (77.3%) | 29 | 0 | 0 | 0 / 0 | 128/128 | 38.838 / 578.383 | 16.0 | 4.6 | 1.00 | 0.3 | 0.00 | 100.7 | $0.000000 |

Observer, resolver, and tool times are instrumented local nanosecond intervals and will be noisy at this scale. Task p50/p95 include durable journaling and contract-aware replay. Resolver tool calls are local reads; the cost column divides external inference cost by completed tasks (zero here because no model is called).

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

On this bank, the frozen observers agreed on the same wrong action in 32 episodes. The witness requested evidence inspection for 32 of those and missed 0; it emitted 32 inspection proposals in total, including 0 on episodes without a shared wrong action. It can catch fresh misleading recommendations when they conflict with the visible goal/reported-revision contract, but it cannot identify a fresh source that lies consistently about its revision and recommendation.

## Gate checks

- Exact call budgets in every lane: **PASS**
- Illegal commits: **0**
- Duplicate actions: **0**
- Replay identity failures: **0**
- Missing actions: **0**

## Limits and promotion boundary

This is a synthetic routing benchmark over 128 procedurally generated episodes and hand-coded observers/resolver. It can compare routing rules and verify the authority/replay contract; it cannot estimate production observer quality, real model token cost, or whether disagreement predicts errors in naturally occurring tasks. The resolver does not receive a truth revision. Because the current authority lacks that field, E004 does not claim deterministic stale-revision rejection. The witness is a routing proposal, not authority. Promotion requires the reported paired result plus an external runtime contract that explicitly supplies authoritative revision before adding a stale guard.

