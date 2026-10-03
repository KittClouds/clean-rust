# OBS-OPEN-02R1 — Familywise Discovery Rule Completion

## Repair boundary

OBS-OPEN-03 stopped before substantive execution because OBS-OPEN-02 named `FROZEN_FAMILYWISE_DISCOVERY_RULE_V1` without defining its executable semantics. This gate repairs only that omission.

Parent universe root:

`6b0ca197a394b085707d03dfe06f1569eb0fafbddb2d583817e88647df6f6235`

Parent OBS-OPEN-02 protocol root:

`141344869c5e6aba6bc7346594872efdc196cb246c834f8d510a0aad90831bb5`

Parent commit:

`1b0f00f24bcc253f741d26e4472b40fc6bab3f9d`

The previous protocol remains historical authority and is not rewritten. The observer, source, universe, range family, measurement views, session dependence, bootstrap settings, temporal views, and confirmation firewall remain unchanged.

No discovery or confirmation observation is read in this repair gate.

## Formal estimands

Only four already-frozen measurement families may generate formal candidates:

- `WIDTH_DELTA_ADJACENT`: session width at `k+1` minus width at `k`, for `k=1..29`, with natural null zero;
- `FIRST_OUTSIDE_SIDE_BALANCE`: signed first outside side, for `k=1..30`, with natural symmetry null zero;
- `LOCATION_BALANCE`: per-session above-minus-below eligible-candle proportion, for `k=1..30`, with natural symmetry null zero;
- `SIGNED_PATH_DISPLACEMENT`: last observed close minus first observed close, for `k=1..30`, with natural null zero.

This expands to 119 predeclared tests. Positive-only quantities without a defensible natural null remain descriptive only. No column becomes a hypothesis merely because it exists.

## Natural-null and near-null rules

Formal testing requires a natural null defined before observation: a signed quantity equal to zero, a paired contrast equal to zero, or an exact symmetry implied by the measurement. If no such null exists, the result is `FORMAL_NULL_NOT_DEFINED` and remains descriptive.

R1 declares no equivalence band independently of the data. Therefore `SUPPORTED_NULL_OR_NEAR_NULL` is disabled and the correct state is `NEAR_NULL_NOT_EVALUABLE`. Failure to reject a null is never promoted as support for a null.

## Multiplicity

The complete 119-test formal family uses two-sided Holm-Bonferroni control at `alpha=0.05`. Nested-range dependence does not create convenient subfamilies. Temporal robustness views are robustness evidence, not new opportunities to manufacture candidates.

The formal decision is recorded separately from the raw bootstrap tail quantity. A bootstrap interval excluding zero is not silently treated as a familywise-qualified result.

## Bootstrap and support

The inherited session-block bootstrap remains 2,000 resamples with seed `20260814` and percentile 95% intervals. The frozen two-sided bootstrap tail probability uses plus-one correction. Each candidate carries point estimate, interval, raw tail quantity, and Holm decision.

Support floors are pre-data and design-relative:

- at least 129 eligible discovery sessions;
- at least four supported calendar months, with at least ten eligible sessions per month;
- both qualified server-offset regimes, with at least twenty eligible sessions per regime;
- conditional estimands require at least thirty eligible sessions in each conditional cell.

Unavailable and censored observations do not become negative outcomes. They remain outside the eligible denominator with explicit counts.

## Temporal stability

The predeclared temporal views are calendar month, server-offset regime, leave-one-supported-month-out, and chronological block. A formally supported candidate requires the aggregate familywise decision and nonzero same-sign effects in every supported slice across all four views. Slice significance is not required, but every required slice must meet its pre-data support floor. Leave-one-month-out and chronological-block views are sensitivity checks, not new multiplicity families. A candidate is `TEMPORALLY_UNSTABLE` when the aggregate formal decision passes but at least two supported slices across any predeclared view have opposite nonzero signs. Missing slice support is `TEMPORAL_SUPPORT_INSUFFICIENT`.

## Candidate classes and precedence

R1 enables `RECURRING_STRUCTURE`, `SCALE_DEPENDENT_STRUCTURE`, and `TEMPORALLY_UNSTABLE_STRUCTURE` for the formal estimands above. `SCALE_STABLE_STRUCTURE`, `REPRESENTATION_SENSITIVE_STRUCTURE`, `CONDITIONAL_STRUCTURE`, and `SUPPORTED_NULL_OR_NEAR_NULL` remain descriptive-only because no pre-data region, cross-view null, conditional estimand, or equivalence band was frozen.

Classification precedence is: `NOT_EVALUABLE`, `INSUFFICIENT_SUPPORT`, `DESCRIPTIVE_ONLY`, `TEMPORALLY_UNSTABLE_STRUCTURE`, `SCALE_DEPENDENT_STRUCTURE`, then `RECURRING_STRUCTURE`.

## Scale-space rule

R1 permits formal adjacent-scale candidates only for the predeclared `WIDTH_DELTA_ADJACENT` estimands. No region boundary is optimized after observation. Contiguous scale regions and isolated-duration claims remain descriptive because no pre-data region estimand was frozen.

## Candidate rejection ledger

Every evaluated candidate receives a machine reason when not promoted. The frozen vocabulary includes `DESCRIPTIVE_ONLY_NO_FORMAL_NULL`, `INSUFFICIENT_ELIGIBLE_SUPPORT`, `INSUFFICIENT_TEMPORAL_SUPPORT`, `FAILS_UNADJUSTED_EVIDENCE`, `FAILS_FAMILYWISE_CORRECTION`, `TEMPORALLY_UNSTABLE`, `REPRESENTATION_CONFLICT`, `NEAR_NULL_NOT_EVALUABLE`, `NOT_EVALUABLE`, `CENSORED_OR_UNAVAILABLE`, `NO_PREDECLARED_REGION_RULE`, and `NO_PREDECLARED_CONDITIONAL_RULE`.

## Future confirmation

A promoted candidate carries its exact estimand ID, range domain, representation, direction, support definition, temporal rule, and null into the future confirmation estimand. No later choice of scale, sign, threshold, representation, subgroup, or equivalence margin is permitted.

## Synthetic-only validation

R1 is tested only with complete-null fixtures, an injected effect, weak false-looking effects, correlated nested scales, sparse support, temporal sign reversal, representation disagreement, isolated extrema, and no-natural-null cases. Real discovery and confirmation authority remain unread.

## Exit condition

R1 closes only when the estimand registry, support floors, Holm family, bootstrap semantics, null handling, temporal rules, class precedence, rejection ledger, future estimand contract, firewall, synthetic tests, and two-build byte identity are sealed. OBS-OPEN-03 is not executed in this gate.
