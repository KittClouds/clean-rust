# OBS-OPEN-01 universe qualification protocol v1

## Authority boundary

This gate qualifies source coverage, clock transport, calendar identity, session admission, and a temporally ordered discovery/confirmation partition. It does not inspect substantive output from `OpeningRangeGrammar_v1_02_FullState`.

The prior one-session qualification root remains:

`b5a55b74770cbdb9364cdb3087570c33c4b3b41af7004c9ee4b73b5e8078a040`

No bounded claim from that checkpoint is silently promoted. This gate adds independent multi-session transport and coverage evidence.

## Source and clock contract

- Scientific boundary: 09:30 `America/New_York`.
- Source: `MetaQuotes-Demo / US30`.
- Bar authority: completed M1 and M5 bars emitted by the frozen outcome-blind source collector.
- External clock witness: Dukascopy `USA30IDXUSD`; it is never geometry authority.
- Server-offset model: the offset produced by `Europe/Helsinki`, admitted only after external alignment at preregistered standard, daylight, U.S.-DST, and European-DST boundary anchors.
- 2024-10-27 through 2024-12-31 is excluded as `NOT_EVALUABLE_CLOCK_TRANSPORT`; failed external transport is not extrapolated through.

## Coverage admission

A normal NYSE session is admitted only when the source contains exactly one copy of:

- all 30 M1 opens from 09:30 through 09:59 New York time; and
- all 79 M5 opens from 09:30 through 16:00 New York time, including the deterministic post-horizon finalization trigger.

NYSE holidays, early closes, weekends, unresolved clock intervals, missing bars, and duplicate bars remain explicit exclusion states. No price, range, event, excursion, direction, or observer-state value participates in admission.

## Frozen temporal partition

- Discovery: admitted sessions dated 2024-01-02 through 2025-06-30.
- Confirmation: admitted sessions dated 2025-07-01 through 2025-12-31.
- Seed: none.
- Assignment is chronological and outcome-independent.
- Confirmation state: `FROZEN_UNOPENED`.

Qualification requires at least 200 discovery sessions, 60 confirmation sessions, four supported calendar months per partition with at least ten sessions per supported month, and both server-offset regimes in each partition.

## Determinism

Acquisition reproducibility is distinct from derivation determinism. Raw authority remains local on `D:`. From the same frozen bytes, two clean derivations must reproduce byte-identical clock, provenance, census, admission, exclusion, partition, and qualification artifacts.

## Stop condition

The gate stops at either `QUALIFIED` or `NOT_EVALUABLE_SOURCE_COVERAGE`. It does not authorize substantive discovery, financial interpretation, or trading authority.
