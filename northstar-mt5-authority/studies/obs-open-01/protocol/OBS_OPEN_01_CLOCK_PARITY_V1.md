# OBS-OPEN-01 Clock Parity Protocol v1

## Purpose

This qualification experiment asks only whether a broker/server timestamp can
be mapped to UTC for a bounded session by comparison with an independently
timestamped external market series. It does not inspect opening-range behavior
and grants no scientific, economic, or trading authority beyond the clock map.

## Frozen sources

- Broker series: `US30` M1 completed bars exported by
  `OBS_OPEN_BrokerBarsProbe_v1`.
- External series: Dukascopy `USA30IDXUSD` hourly BI5 tick files, interpreted on
  their UTC file-hour axis.
- Admitted qualification session: `2026-08-13` only.
- Older requested broker anchors returning MT5 error `4401` remain
  `NOT_EVALUABLE_SOURCE_COVERAGE`.

The external series is used only for timestamp alignment. It is not substituted
for the broker series and does not author opening-range geometry.

## Deterministic comparison

1. Decode each external tick as its UTC hour plus millisecond offset.
2. Aggregate the last observed integer mid-price in each UTC minute.
3. Use broker M1 close observations in their recorded server-clock minute.
4. For each candidate server offset in `[-12:00,+14:00]` at 15-minute steps,
   map `broker_utc = broker_server_time - candidate_offset`.
5. Join exact minute timestamps and compare consecutive one-minute price
   changes. Absolute price scales and provider price-level offsets are not used.
6. Compute Pearson correlation and nonzero directional sign agreement.
7. Rank by Pearson correlation, then overlap, then the numerically smaller
   offset. Tie breaking is deterministic.

## Acceptance thresholds frozen before inspection

A bounded session qualifies only when all are true:

- at least 300 aligned return pairs;
- best Pearson correlation is at least 0.80;
- nonzero directional sign agreement is at least 0.70;
- best-minus-runner-up Pearson margin is at least 0.30;
- all source files and decoded records reconcile with their manifests;
- a repeated rebuild produces byte-identical logical artifacts.

Failure is reported as a typed qualification outcome. Thresholds are not
relaxed after inspecting results.

## Scope of a passing result

A pass qualifies the inferred source offset only for the admitted session. It
does not prove winter behavior, DST transitions, other broker servers, other
symbols, or future sessions. Each observational session still requires an exact
clock receipt. Winter and transition transport remain blocked until source
coverage supplies appropriate specimens.
