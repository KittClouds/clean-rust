# OBS-OPEN-01 Clock Parity Checkpoint — 2026-08-14

## Bounded outcome

The preregistered clock-parity method passes for the only broker session with
admitted M1/M5 coverage: `2026-08-13`.

- inferred broker/server offset: `UTC+03:00`;
- aligned consecutive minute changes: `1,212`;
- Pearson correlation: `0.9978007785985417`;
- nonzero directional agreement: `0.9894829097283085`;
- best-versus-runner-up correlation margin: `0.9012364673709089`;
- bounded outcome: `PASS_BOUNDED_SESSION`.

The result was computed under the thresholds frozen in
`protocol/OBS_OPEN_01_CLOCK_PARITY_V1.md` before external data inspection.
Two evaluator runs emitted byte-identical scan and receipt artifacts.

## Coverage truth

The broker probe requested twelve anchor dates at M1 and M5. Only
`2026-08-13` was available: 1,379 M1 bars and 276 M5 bars. Every older request
returned MT5 error `4401`. Those sessions remain
`NOT_EVALUABLE_SOURCE_COVERAGE`; they were not imputed, downloaded from another
provider, or treated as zero observations.

The external clock fixture contains 98,050 decoded ticks and 1,324 UTC minute
observations from Dukascopy `USA30IDXUSD`. It is used only to align timestamps.
It does not replace the broker source for opening-range geometry.

## Exact limits

This checkpoint supports the mapping for `2026-08-13` only:

`09:30 America/New_York -> 13:30 UTC -> 16:30 broker/server`.

It does not establish winter broker offset behavior or either DST transition.
Those transport claims remain `NOT_EVALUABLE_SOURCE_COVERAGE`. Future sessions
must carry their own clock-map receipts.

Substantive opening-range results remain `FROZEN_UNOPENED`.
