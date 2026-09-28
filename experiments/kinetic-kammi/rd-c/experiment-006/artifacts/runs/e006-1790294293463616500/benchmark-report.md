# R&D-C Experiment 006 — Inspection Under Failure

## Question and contract

This held-out test attacks the E005 domain value table with shifted values, stale second-source replies, self-conflicting candidates, timeouts, transport failures, malformed results, and four unseen domains (8–11). The router sees the public frame before paying; source replies live in a separate fixture and are released only after a paid query. No held-out label or source outcome enters routing.

The four typed outcomes produce explicit proposals. `Confirmed` keeps the active action; a unique, signed, high-confidence `Contradicted` result proposes its alternative; `Unknown` and `Failed` return the compiled runtime to `OBSERVING`. An unresolved proposal never reuses the active task action. No source revision is trusted by authority.

The simulated endpoint honors stable query IDs: after a crash following a paid response but before its result receipt, resume performs one idempotent lookup and records the cached outcome. Query attempts, retries, paid charges, resolver calls, and task action effects are counted separately. This endpoint behavior is a harness contract, not a claim about external tools.

## Paired results

| Lane | Budget | Completed | Δ vs no-inspection | Wrong→right | Right→wrong | Unresolved | Avoided wrong commits | Paid units | Endpoint attempts / retries | Resolver calls | p50 / p95 task ms | p50 / p95 query ms | p50 / p95 resolver μs | Journal B / task | Receipt B / call | Paid units / completion | Replay |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| e005_domain_table | 16 | 167/384 (43.5%) | -7 | 2 | 5 | 9 | 5 | 16 | 16 / 0 | 16 | 33.331 / 39.610 | 3.300 / 6.268 | 0.00 / 0.00 | 11992 | 390.0 | 0.096 | 384/384 |
| e005_domain_table | 32 | 170/384 (44.3%) | -4 | 8 | 8 | 16 | 12 | 32 | 32 / 0 | 32 | 35.171 / 41.774 | 3.545 / 5.382 | 0.00 / 0.20 | 11968 | 390.0 | 0.188 | 384/384 |
| e005_domain_table | 48 | 170/384 (44.3%) | -4 | 14 | 12 | 22 | 16 | 48 | 48 / 0 | 48 | 33.732 / 40.361 | 3.434 / 4.487 | 0.00 / 0.20 | 11927 | 390.0 | 0.282 | 384/384 |
| e005_domain_table | 64 | 168/384 (43.8%) | -6 | 20 | 16 | 28 | 18 | 64 | 64 / 0 | 64 | 32.995 / 39.954 | 3.349 / 4.487 | 0.00 / 0.20 | 11875 | 390.0 | 0.381 | 384/384 |
| smoothed_estimate | 16 | 172/384 (44.8%) | -2 | 4 | 3 | 9 | 6 | 16 | 16 / 0 | 16 | 32.578 / 39.330 | 3.337 / 5.590 | 0.00 / 0.00 | 12025 | 390.0 | 0.093 | 384/384 |
| smoothed_estimate | 32 | 170/384 (44.3%) | -4 | 8 | 8 | 16 | 12 | 32 | 32 / 0 | 32 | 34.308 / 537.883 | 3.291 / 5.304 | 0.00 / 0.10 | 11968 | 390.0 | 0.188 | 384/384 |
| smoothed_estimate | 48 | 169/384 (44.0%) | -5 | 13 | 12 | 23 | 17 | 48 | 48 / 0 | 48 | 33.462 / 42.594 | 3.337 / 4.723 | 0.00 / 0.20 | 11913 | 390.0 | 0.284 | 384/384 |
| smoothed_estimate | 64 | 168/384 (43.8%) | -6 | 20 | 16 | 28 | 18 | 64 | 64 / 0 | 64 | 33.437 / 40.521 | 3.359 / 4.192 | 0.00 / 0.20 | 11874 | 390.0 | 0.381 | 384/384 |
| feature_estimate | 16 | 181/384 (47.1%) | +7 | 7 | 0 | 0 | 0 | 16 | 16 / 0 | 16 | 33.838 / 40.248 | 3.733 / 6.549 | 0.00 / 0.00 | 12146 | 390.0 | 0.088 | 384/384 |
| feature_estimate | 32 | 187/384 (48.7%) | +13 | 13 | 0 | 0 | 0 | 32 | 32 / 0 | 32 | 33.565 / 39.643 | 3.502 / 4.538 | 0.00 / 0.20 | 12188 | 390.0 | 0.171 | 384/384 |
| feature_estimate | 48 | 194/384 (50.5%) | +20 | 20 | 0 | 0 | 0 | 48 | 48 / 0 | 48 | 33.633 / 39.468 | 3.342 / 4.573 | 0.00 / 0.20 | 12233 | 390.0 | 0.247 | 384/384 |
| feature_estimate | 64 | 207/384 (53.9%) | +33 | 33 | 0 | 0 | 0 | 64 | 64 / 0 | 64 | 33.354 / 39.587 | 3.304 / 4.487 | 0.00 / 0.30 | 12319 | 390.0 | 0.309 | 384/384 |
| matched_random | 16 | 172/384 (44.8%) | -2 | 5 | 6 | 5 | 4 | 16 | 16 / 0 | 16 | 32.882 / 39.522 | 3.355 / 8.153 | 0.00 / 0.00 | 12053 | 390.0 | 0.093 | 384/384 |
| matched_random | 32 | 169/384 (44.0%) | -5 | 7 | 11 | 10 | 9 | 32 | 32 / 0 | 32 | 33.310 / 39.264 | 3.213 / 4.429 | 0.00 / 0.20 | 12000 | 390.0 | 0.189 | 384/384 |
| matched_random | 48 | 167/384 (43.5%) | -7 | 9 | 15 | 17 | 16 | 48 | 48 / 0 | 48 | 33.925 / 41.511 | 3.460 / 4.970 | 0.00 / 0.20 | 11941 | 390.0 | 0.287 | 384/384 |
| matched_random | 64 | 164/384 (42.7%) | -10 | 10 | 18 | 23 | 21 | 64 | 64 / 0 | 64 | 33.569 / 40.284 | 3.302 / 4.548 | 0.00 / 0.30 | 11881 | 390.0 | 0.390 | 384/384 |
| no_inspection | 0 | 174/384 (45.3%) | +0 | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 0 | 33.842 / 40.247 | 0.000 / 0.000 | 0.00 / 0.00 | 12103 | 0.0 | 0.000 | 384/384 |

Budgets are exact distinct paid-query counts for the four router lanes. `Δ vs no-inspection` is the measured completion change after each lane has paid those calls; cost is also shown as paid units per completion. No conversion between query units and task completion is assumed. The no-inspection floor performs zero queries.

## Outcome handling

| Inspection result | Queries | Proposed reobserve | Actionable proposals | Wrong→right | Right→wrong | Active-wrong commits avoided |
|---|---:|---:|---:|---:|---:|---:|
| confirmed | 111 | 0 | 111 | 0 | 0 | 0 |
| contradicted | 323 | 0 | 323 | 193 | 130 | 0 |
| unknown | 78 | 78 | 0 | 0 | 0 | 78 |
| failed | 128 | 128 | 0 | 0 | 0 | 76 |

An unresolved result leaves the task at `OBSERVING`; it adds no task action effect. Active-wrong cases in that group count as avoided wrong commits, while active-right cases lose a completion opportunity and remain incomplete.

## Domain shift and unseen domains

| Domain | Bank | E005 table score | Smoothed mean | Uncertainty | Conservative score | Feature mean score | Budget-64 queries | Budget-64 Δ outcomes | Budget-64 completions |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | seen | 0.000 | 0.000 | 0.071 | -0.035 | 0.188 | 0 | +0/-0 | 32/32 |
| 1 | seen | 0.750 | 0.500 | 0.127 | 0.436 | 0.219 | 32 | +12/-8 | 12/32 |
| 2 | seen | 0.500 | 0.200 | 0.138 | 0.131 | 0.219 | 0 | +0/-0 | 12/32 |
| 3 | seen | 1.000 | 0.725 | 0.106 | 0.672 | 0.219 | 32 | +8/-8 | 8/32 |
| 4 | seen | 0.000 | 0.000 | 0.071 | -0.035 | 0.188 | 0 | +0/-0 | 32/32 |
| 5 | seen | -1.000 | -0.750 | 0.098 | -0.799 | 0.219 | 0 | +0/-0 | 16/32 |
| 6 | seen | 0.000 | 0.100 | 0.111 | 0.045 | 0.219 | 0 | +0/-0 | 0/32 |
| 7 | seen | 0.000 | -0.100 | 0.131 | -0.166 | 0.219 | 0 | +0/-0 | 12/32 |
| 8 | unseen | 0.000 | 0.000 | 0.000 | 0.000 | 0.219 | 0 | +0/-0 | 4/32 |
| 9 | unseen | 0.000 | 0.000 | 0.000 | 0.000 | 0.198 | 0 | +0/-0 | 28/32 |
| 10 | unseen | 0.000 | 0.000 | 0.000 | 0.000 | -0.006 | 0 | +0/-0 | 0/32 |
| 11 | unseen | 0.000 | 0.000 | 0.000 | 0.000 | 0.219 | 0 | +0/-0 | 12/32 |

Domain 6 is the fresh-looking shared-error attack: both observers agree, age is zero, warnings are clear, and the inspected source echoes the wrong proposal. Domains 3 and 5 invert or flatten E005's previously near-certain values. Domains 8–11 have no development examples and test transfer without a domain lookup. The table's last columns show smoothed-router selection and outcomes; the paired-results table compares all routers at each equal budget.

## Router definitions

- **E005 domain table:** frozen E005 development model; unseen domain IDs receive neutral score zero.
- **Smoothed estimate:** E006 development mean shrunk toward zero with eight prior-equivalent observations; selection score is posterior mean minus half its estimated standard error.
- **Feature estimate:** ridge-regularized linear model trained on eight public features only; domain ID is not a feature. Its eight weights are recorded in `development/feature-model.csv`.
- **Matched random:** deterministic BLAKE3 ranking over the same episode IDs and exact query budgets.
- **No-inspection:** execute only the active proposal and make no inspection call.

## Runtime and receipt gates

- Routed episodes: 640
- Illegal commits: 0
- Rejected proposals: 0
- Duplicate action effects: 0
- Missing action effects: 0
- Task replay failures: 0
- Unknown/failed fallback-to-active violations: 0
- Query receipt budgets and hash chains: **PASS**

## Interpretation limits

All data and inspection services are synthetic, deterministic proxies. The held-out bank has 384 episodes, including only 32 examples per domain and 128 total in unseen domains. The result tests routing, explicit abstention, receipt recovery, and replay contracts; it does not estimate a production inspector's error rates or financial cost. The paired score must be treated as bank-specific evidence until repeated on independently constructed domains and sources.

## Crash injection and resume

| Crash boundary | Query intents | Endpoint attempts | Retries | Paid charges | Result receipts | Task action effects | Duplicate effects | Replay |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| after-intent-before-query | 1 | 1 | 0 | 1 | 1 | 1 | 0 | PASS |
| after-paid-response-before-outcome-receipt | 1 | 2 | 1 | 1 | 1 | 1 | 0 | PASS |
| after-durable-outcome-receipt | 1 | 1 | 0 | 1 | 1 | 1 | 0 | PASS |

- Crash recovery gate: **PASS**
- Endpoint result cache and local receipt were replayed independently; paid query units and task action effects stayed separate.

