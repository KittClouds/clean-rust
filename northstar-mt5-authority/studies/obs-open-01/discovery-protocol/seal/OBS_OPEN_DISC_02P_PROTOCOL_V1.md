# OBS-OPEN-DISC-02P - Discovery and Confirmation Protocol Freeze

Authority class: protocol only. Substantive MEAS-02 discovery execution is forbidden.

## Bound authorities

- Measurement authority: `CAUSAL_SESSION_PROCESS_MEASUREMENT_V1`
- MEAS-02 root: `f7abf12d1473a5e1eddc8a7efb84ff7224811eda83ad62ba4fe300a7648ce5ea`
- M1 observer instance: `CAUSAL_RANGE_EXTREME_M1_V1`
- Instrument root: `5930c7d4f5b2de4549bfedacbd2c3b9df7da78f68c7d765b9c0669d08a17490f`
- Clock/universe root: `6b0ca197a394b085707d03dfe06f1569eb0fafbddb2d583817e88647df6f6235`
- Population: 257 MEAS-02 discovery sessions and 69 untouched confirmation sessions.

The 257 sessions are `MEAS02_DISCOVERY_UNOPENED`: they were previously observed through another observer generation, but no full-corpus MEAS-02 surface has been opened. The 69 sessions remain `FROZEN_UNOPENED`.

## Scientific scope

Exactly two question families are admitted.

### Family A - running-extreme process

Observe each strict upper or lower candidate after its causal birth knowledge time until supersession or session termination. Preserve candidate lifetime, same-direction extension, opposite displacement, path length, terminal displacement, and retrospective terminal status.

The post-birth path begins with the first completed M1 bar after candidate establishment. A superseding bar is included because supersession becomes known at its commit. Session termination right-censors time to supersession. Terminal-survivor classification is retrospective and never enters birth-time state.

Candidate observations are first balanced within session. A session with many candidates does not receive greater inferential weight merely because its chain is longer.

### Family B - fixed-range x session process

Observe the post-freeze session process for every peer range `R01..R30` in raw and range-relative coordinates. Treat `(k, tau)` as an ordered support-aware surface, never as thirty independent experiments. Physical time after causal freeze is authoritative. Unsupported suffixes remain masked; no padding, extrapolation, or stretched time is permitted.

## Formal and descriptive boundaries

The complete descriptive surfaces are preserved. Only three preregistered, two-sided, natural-null surface contrasts may generate formal candidates:

1. upper-versus-mirrored-lower same-direction extension;
2. upper-versus-mirrored-lower opposite displacement;
3. signed range-relative close about the frozen midpoint.

Candidate lifetime, path length, terminal displacement, terminal-status strata, scale curvature, and raw-price surfaces are descriptive in this generation. Failure to reject is not evidence for a null. No equivalence margin is admitted.

## Dependence and inference

The entire session is the resampling unit. Both sides, every candidate, all thirty ranges, and every supported time coordinate move together.

Each formal contrast uses a studentized maximum-absolute statistic over its complete eligible surface. The null generator is deterministic session-level sign reflection. This tests the explicitly declared joint reflection/exchangeability null; it does not claim a mechanism.

There are exactly three family-level formal tests. Holm-Bonferroni controls familywise error at two-sided alpha `0.05` across those three tests. Within-surface localization uses the same maximum-statistic reference distribution and cannot create additional unadjusted tests.

Monte Carlo randomizations are fixed at `9,999`, seed `20260814`. With plus-one correction, `p_min = 0.0001`, more than tenfold below the strictest first-step Holm threshold divided by ten. A 99% Wilson interval around the exceedance rate governs numerical decisions: if it straddles the applicable threshold, the result is `NUMERICAL_DECISION_UNRESOLVED` and cannot promote.

## Support

Formal cells require at least 129 paired eligible sessions, at least four supported calendar months with ten sessions each, both admitted server-offset regimes with twenty sessions each, and four chronological blocks with twenty sessions each. Leave-one-supported-month-out checks require 103 remaining sessions, three supported months, and fifteen sessions from each offset regime.

Support depends only on availability, coverage, and the frozen measurement contract. Values may not influence admission.

## Robustness and localization

If a family passes the omnibus and Holm gates, its deterministic anchor is the canonically first cell among those tied for maximum absolute studentized magnitude. The anchor is a localization receipt, not a privileged opening-range duration. Promotion requires its sign to remain nonzero and unchanged in every supported month, both offset regimes, every leave-one-supported-month-out view, and all four chronological blocks.

## Confirmation

The 69-session population is a prospective one-shot confirmation candidate. DISC-02P does not open it. DISC-02E may mechanically emit exact confirmation contracts only for promoted candidates. Such contracts freeze family, representation, surface domain, localized cell set, direction, null, support, resampling, multiplicity, and decision rules. No later return to discovery may select them.

## Explicit exclusions

No grammar-dependent substantive claim, volume, volatility conditioning, weekday conditioning, preferred `k`, clustering, prediction, economic interpretation, or trading authority is admitted.

## Stop rule

Seal the protocol, executable inference contract, typed insufficiency vocabulary, confirmation contract, synthetic/adversarial qualification, read audit, and two byte-identical builds. Stop with all 257 MEAS-02 discovery values and all 69 confirmation observations unopened.

