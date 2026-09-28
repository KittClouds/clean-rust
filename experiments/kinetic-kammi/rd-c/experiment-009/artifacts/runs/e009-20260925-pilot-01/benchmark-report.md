# R&D-C / Experiment 009 — Benchmark Report

Run: `e009-20260925-pilot-01`. Status: **exploratory only**; two task families, one task per family, no development bank.

Non-abstaining lane choices were compiled through E002 authority and checked against the selected candidate's frozen executable completion tests. Abstentions produced no actions. Shadow calls did not authorize actions. Local inference used no billed API; energy and hardware-dollar costs were not measured.

## Paired lane results

| Lane | Complete | Wrong legal | Abstain | Small / large calls | Tokens | p50 / p95 total ms | Illegal / duplicate | Replay |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| always-large | 2/2 | 0 | 0 | 0 / 2 | 2175 | 2429.908 / 2534.813 | 0 / 0 | True |
| hand-written | 0/2 | 0 | 2 | 0 / 0 | 0 | 194.825 / 3327.968 | 0 / 0 | True |
| small | 0/2 | 0 | 2 | 2 / 0 | 1889 | 420.511 / 628.657 | 0 / 0 | True |
| small-then-large-on-abstention | 2/2 | 0 | 0 | 2 / 2 | 4064 | 5518.422 / 7401.004 | 0 / 0 | True |

The small observer abstained on both tasks. Small-plus-large fallback matched always-large completion (2/2) but added 1,889 tokens and 3,714 ms of observer time across the pair. This pilot shows no completion-cost advantage for the hybrid lane.

The initial 128-token and reasoning-enabled 1024-token shadow responses are preserved and excluded. Runtime logs showed all 1024 generated tokens were reasoning output with empty final content. Disabling template reasoning produced complete typed proposals in 23 small-model tokens and 39 large-model tokens per shadow task; the prompt, schema, and task frames were unchanged.

Token cost per completed task is recorded in `benchmark-summary.json`; it is undefined for lanes with no completions. Receipt JSON bytes and action-ledger bytes are also recorded there.

## Confident shared errors

Small observer confident wrong choices (applicability ≥850 and abstention ≤150): 0 task(s): none.
Small and large observers confidently agreeing on the same wrong action: 0 task(s): none.

## Limits and decision

This bank supports a harness check and a local observer pilot only. One task per family does not establish generalization across repositories or task families. The large Ternary-Bonsai runtime is experimental-runtime-only. The output fields are constrained JSON plus fixed thresholds, not trained action/applicability/abstention heads. Treat any lane difference as a candidate result for a larger, independently split bank.

E008 remains sealed and paid inspection routing remains disabled by default.
