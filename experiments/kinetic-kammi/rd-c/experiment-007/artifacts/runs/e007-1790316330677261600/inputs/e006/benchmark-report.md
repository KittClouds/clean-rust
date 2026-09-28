# R&D-C Experiment 006 — Inspection Under Failure

## Question and contract

This held-out test attacks the E005 domain value table with shifted values, stale second-source replies, self-conflicting candidates, timeouts, transport failures, malformed results, and four unseen domains (8–11). The router sees the public frame before paying; source replies live in a separate fixture and are released only after a paid query. No held-out label or source outcome enters routing.

The four typed outcomes produce explicit proposals. `Confirmed` keeps the active action; a unique, signed, high-confidence `Contradicted` result proposes its alternative; `Unknown` and `Failed` return the compiled runtime to `OBSERVING`. An unresolved proposal never reuses the active task action. No source revision is trusted by authority.

The simulated endpoint honors stable query IDs: after a crash following a paid response but before its result receipt, resume performs one idempotent lookup and records the cached outcome. Query attempts, retries, paid charges, resolver calls, and task action effects are counted separately. This endpoint behavior is a harness contract, not a claim about external tools.

## Paired results

| Lane | Budget | Completed | Δ vs no-inspection | Wrong→right | Right→wrong | Unresolved | Avoided wrong commits | Paid units | Endpoint attempts / retries | Resolver calls | p50 / p95 task ms | p50 / p95 query ms | p50 / p95 resolver μs | Journal B / task | Receipt B / call | Paid units / completion | Replay |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| e005_domain_table | 16 | 167/384 (43.5%) | -7 | 2 | 5 | 9 | 5 | 16 | 16 / 0 | 16 | 32.779 / 50.520 | 3.427 / 6.755 | 0.00 / 0.00 | 11991 | 390.0 | 0.096 | 384/384 |
| e005_domain_table | 32 | 170/384 (44.3%) | -4 | 8 | 8 | 16 | 12 | 32 | 32 / 0 | 32 | 32.955 / 38.992 | 3.286 / 5.209 | 0.00 / 0.10 | 11968 | 390.0 | 0.188 | 384/384 |
| e005_domain_table | 48 | 170/384 (44.3%) | -4 | 14 | 12 | 22 | 16 | 48 | 48 / 0 | 48 | 33.188 / 103.875 | 3.275 / 4.489 | 0.00 / 0.20 | 11927 | 390.0 | 0.282 | 384/384 |
| e005_domain_table | 64 | 168/384 (43.8%) | -6 | 20 | 16 | 28 | 18 | 64 | 64 / 0 | 64 | 33.431 / 39.342 | 3.342 / 4.426 | 0.00 / 0.10 | 11872 | 390.0 | 0.381 | 384/384 |
| smoothed_estimate | 16 | 172/384 (44.8%) | -2 | 4 | 3 | 9 | 6 | 16 | 16 / 0 | 16 | 32.315 / 38.405 | 3.448 / 6.715 | 0.00 / 0.00 | 12023 | 390.0 | 0.093 | 384/384 |
| smoothed_estimate | 32 | 170/384 (44.3%) | -4 | 8 | 8 | 16 | 12 | 32 | 32 / 0 | 32 | 32.879 / 40.131 | 3.312 / 5.058 | 0.00 / 0.10 | 11968 | 390.0 | 0.188 | 384/384 |
| smoothed_estimate | 48 | 169/384 (44.0%) | -5 | 13 | 12 | 23 | 17 | 48 | 48 / 0 | 48 | 32.501 / 38.981 | 3.232 / 4.665 | 0.00 / 0.10 | 11914 | 390.0 | 0.284 | 384/384 |
| smoothed_estimate | 64 | 168/384 (43.8%) | -6 | 20 | 16 | 28 | 18 | 64 | 64 / 0 | 64 | 33.277 / 41.272 | 3.402 / 4.461 | 0.00 / 0.10 | 11874 | 390.0 | 0.381 | 384/384 |
| feature_estimate | 16 | 181/384 (47.1%) | +7 | 7 | 0 | 0 | 0 | 16 | 16 / 0 | 16 | 33.170 / 42.489 | 3.712 / 6.039 | 0.00 / 0.00 | 12144 | 390.0 | 0.088 | 384/384 |
| feature_estimate | 32 | 187/384 (48.7%) | +13 | 13 | 0 | 0 | 0 | 32 | 32 / 0 | 32 | 33.475 / 39.785 | 3.368 / 5.325 | 0.00 / 0.20 | 12188 | 390.0 | 0.171 | 384/384 |
| feature_estimate | 48 | 194/384 (50.5%) | +20 | 20 | 0 | 0 | 0 | 48 | 48 / 0 | 48 | 33.911 / 647.139 | 3.422 / 6.117 | 0.00 / 0.20 | 12233 | 390.0 | 0.247 | 384/384 |
| feature_estimate | 64 | 207/384 (53.9%) | +33 | 33 | 0 | 0 | 0 | 64 | 64 / 0 | 64 | 33.837 / 40.681 | 3.221 / 4.284 | 0.00 / 0.20 | 12323 | 390.0 | 0.309 | 384/384 |
| matched_random | 16 | 172/384 (44.8%) | -2 | 5 | 6 | 5 | 4 | 16 | 16 / 0 | 16 | 32.922 / 42.552 | 3.481 / 6.950 | 0.00 / 0.00 | 12053 | 390.0 | 0.093 | 384/384 |
| matched_random | 32 | 169/384 (44.0%) | -5 | 7 | 11 | 10 | 9 | 32 | 32 / 0 | 32 | 32.849 / 39.989 | 3.516 / 5.363 | 0.00 / 0.20 | 12001 | 390.0 | 0.189 | 384/384 |
| matched_random | 48 | 167/384 (43.5%) | -7 | 9 | 15 | 17 | 16 | 48 | 48 / 0 | 48 | 33.035 / 41.726 | 3.368 / 4.819 | 0.00 / 0.20 | 11937 | 390.0 | 0.287 | 384/384 |
| matched_random | 64 | 164/384 (42.7%) | -10 | 10 | 18 | 23 | 21 | 64 | 64 / 0 | 64 | 33.161 / 39.752 | 3.368 / 4.313 | 0.00 / 0.20 | 11879 | 390.0 | 0.390 | 384/384 |
| no_inspection | 0 | 174/384 (45.3%) | +0 | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 0 | 33.579 / 40.665 | 0.000 / 0.000 | 0.00 / 0.00 | 12100 | 0.0 | 0.000 | 384/384 |

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

## Unseen-domain paired comparison at budget 64

| Lane | Paid queries in domains 8–11 | Wrong→right | Right→wrong | Unresolved | Completed | Δ vs unseen no-inspection floor |
|---|---:|---:|---:|---:|---:|---:|
| e005_domain_table | 0 | 0 | 0 | 0 | 44/128 | +0 |
| smoothed_estimate | 0 | 0 | 0 | 0 | 44/128 | +0 |
| feature_estimate | 18 | 12 | 0 | 0 | 56/128 | +12 |
| matched_random | 22 | 5 | 7 | 9 | 42/128 | -2 |
| no_inspection | 0 | 0 | 0 | 0 | 44/128 | +0 |

The unseen slice has 128 episodes. The E005 and E006 smoothed tables assign unseen domain IDs a neutral route score, so their selected calls are determined by deterministic tie-breaking against the other bank items. The feature model uses public frame values and no domain ID. This slice is part of the same held-out bank, and its small per-domain counts limit transfer claims.

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

