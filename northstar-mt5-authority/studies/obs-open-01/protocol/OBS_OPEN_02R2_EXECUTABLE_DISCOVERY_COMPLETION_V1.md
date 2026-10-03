# OBS-OPEN-02R2 — Executable Discovery Completion and Data Quality

## Boundary

OBS-OPEN-03 preflight root
`2e32be4387d51fb993e61c01d2b72b170fe9226e315d330f9173f0f03f7b9e25`
identified five remaining gaps in the effective OBS-OPEN-02 + 02R1 contract.
R2 repairs exactly those gaps. It does not inspect opening-range behavior,
compute an estimand, produce a candidate, or access confirmation observations.

The observer, source, 326-session universe, 257/69 temporal partition, peer
R01–R30 family, measurement views, session resampling unit, 2,000-resample
bootstrap, seed `20260814`, Holm family, and confirmation firewall remain
unchanged.

## Measurement formulas

The executable contract freezes every descriptive formula. Range geometry uses
M1 bars from 09:30 New York through the exclusive freeze boundary. Interaction
paths use completed M5 candles whose open is at or after freeze and whose close
is no later than 16:00 New York. Boundary equality is `IN_ZONE`.

Sequence duration is measured in eligible completed M5 bars. `outside_duration`
is the maximum frozen grammar outside-run count. Returns are grammar events
4/5/8/9; cross-throughs are events 10/11. The terminal location is the final
eligible candle location.

Path displacement is final close minus first eligible close. Excursions are the
maximum and minimum close displacement from that first close. Path length is
the sum of absolute close changes. Directional efficiency is signed displacement
divided by path length, or zero for a zero-length path. Return distance measures
the gap between the terminal-direction peak excursion and terminal displacement;
when terminal displacement is zero it is the maximum absolute excursion.

Adjacent scale relations compare only the same session at k and k+1. Terminal
classification survival is exact equality. Contiguous persistence is a maximal
uninterrupted k span with the same terminal location. These scale relations are
descriptive; R2 does not enable a scale-region candidate class.

## Formal registry

The 119 estimands remain the four R1 templates. R2 adds explicit population,
session-value, eligible denominator, typed availability, functional, natural
null, representation, and candidate-class fields. No outside close is
`NOT_APPLICABLE_NO_OUTSIDE`, not a zero side. Paths shorter than two eligible
candles are `NOT_EVALUABLE`. Geometry contrasts require both adjacent ranges.

## Temporal construction

Calendar months use civil `YYYY-MM` and require ten eligible sessions. The two
frozen server-offset groups require twenty eligible sessions each.

Leave-one-supported-month-out removes one supported month at a time. The
remaining population requires 129 eligible sessions, three supported months,
and twenty sessions in each offset regime.

Chronological blocks sort eligible sessions by civil date and assign
`floor(4*i/N)`, yielding four contiguous blocks. Each block requires 33 eligible
sessions. Temporal slices are sensitivity evidence, not new formal tests.

`TEMPORALLY_SUPPORTED` requires every required supported slice to have a
nonzero estimate sharing the aggregate sign. Two or more opposite-sign slices
produce `TEMPORALLY_UNSTABLE`. Missing support or an exact-zero required slice
produces `TEMPORAL_SUPPORT_INSUFFICIENT`. Slice-level significance is not
required.

## Rejection transitions and confirmation emitter

R2 freezes an ordered transition table: availability, eligible support,
temporal support, raw evidence, Holm evidence, temporal instability, then the
enabled supported classes. Disabled classes remain disabled for their explicit
R1 reasons.

Every promoted candidate is converted mechanically to a future confirmation
record. The exact estimand, k, adjacent k, representation, session value,
eligibility, null, and observed sign are frozen. Confirmation uses the same
functional and session bootstrap, with no discovery reselection. Its population
and support requirements are frozen in the R2 contract. This is an emitter
contract only; confirmation observations remain unopened.

## Outcome-blind data quality

R2 also qualifies the discovery source before OBS-OPEN-03. The validator reads
only the source prefix ending with 2025-06-30, using outcome-blind row counts
already frozen by universe qualification. It does not request the next row and
cannot cross into the confirmation date range.

Checks include schema, timestamp parse/alignment, monotonicity, duplicates,
finite positive prices, OHLC ordering, nonnegative volume/spread, exact 30 M1
and 79 M5 session windows, and M1-to-M5 OHLC parity. The full authority hash is
consumed from its earlier verification receipt; R2 does not reread confirmation
bytes to recompute it.

M1 beyond the 30-minute opening construction interval is not observer authority.
If such an M1 suffix is absent, the corresponding optional M1-to-M5 parity check
is `PARITY_NOT_EVALUABLE`, while the authoritative M5 candle remains admissible.
Comparable M1-to-M5 candles must match exactly.

## Exit

R2 exits only when the five preflight gaps are executable, the synthetic suite
passes, discovery-source quality passes, confirmation reads remain zero, and
two independent seal builds are byte-identical. R2 then stops. OBS-OPEN-03 is a
separate gate.

Economic authority: `false`.

Trading authority: `false`.
