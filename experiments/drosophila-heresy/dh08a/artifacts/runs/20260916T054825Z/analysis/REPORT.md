# DH-08A Analysis Report

Status: `INCONCLUSIVE`

## Primary result

The sole inferential unit was the computational seed bundle (n=32). Each seed value is the mean
`true_margin - null_margin` over R/L, tau 4/16, and 256 events. Events, sides, and taus were not
treated as independent samples.

| Quantity | Value |
| --- | ---: |
| Mean | 3.88707743319e-06 |
| Sample SD | 1.1070631257e-05 |
| Standard error | 1.95702960845e-06 |
| Paired t 95% interval | [-1.04310768247e-07, 7.87846563463e-06] |
| Seed bootstrap 95% interval | [2.71169155018e-07, 7.80276022402e-06] |

Event-local endpoint sensitivity was unresolved; the cumulative DH-07R result remains compatible with path-mediated dynamics.

## Integrity

- Validated 128 bundles, 256 cells, and 32,768 ordered E-arm shadow events.
- Every Q07 committed-geometry gate passed; E shadow status was `PASSED` in every cell.
- Every Z cell had zero events and zero changed weights.
- All canonical acquisition hashes were structurally validated. No repeated-condition acquisition
  hash parity comparison exists in this one-condition design, so no unavailable parity was inferred.
- Secondary windows, side, tau, and endpoint-versus-base summaries use seed-level aggregation.

## Scope

This is an event-local effect conditional on states visited by the endogenous true policy in one
synthetic specimen. Q07 matches permitted support and support size within 1%; it does not force
identical realized nonzero coordinates. This therefore tests the Q07-matched endpoint substitution,
not a mathematically pure residual rotation and not a decomposition of the cumulative DH-07R effect.
