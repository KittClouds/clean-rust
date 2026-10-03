# OBS-OPEN-MEAS-02 — Causal Session-Process Measurement Surface

Authority class: scientific measurement and admitted-instrument consumption only.

This gate constructs a deterministic M1 measurement representation. It does not define estimands, inspect full-corpus behavior, open confirmation, or create economic/trading authority.

## Parent authorities

- Instrument: `CAUSAL_RANGE_EXTREME_INSTRUMENT_V1`
- INST-01 root: `5930c7d4f5b2de4549bfedacbd2c3b9df7da78f68c7d765b9c0669d08a17490f`
- SRC-01 root: `32e1207717afc29533e8a8fb0a7e0f329f9e092f58f3fb3c58d5661c5b7dd0fa`
- V2.10 source: `a133ef773531a1599d1cef1e5124fcacc24b037f84cca777205c67ee0a785c61`
- Runtime EX5: `a9e25979dc85a760b15499a13552216f19646e43274c93c4d032adc671f415dd`
- Clock/universe root: `6b0ca197a394b085707d03dfe06f1569eb0fafbddb2d583817e88647df6f6235`

Instrument and clock/universe are sibling authorities. Neither silently inherits the claims of the other.

## Observer instance

`CAUSAL_RANGE_EXTREME_M1_V1` is the sole admitted observer instance. M5 is reserved for a later transport/observer-geometry study.

Scientific ranges are half-open peers:

`Rk = [09:30, 09:30+k), k=1..30`, America/New_York.

The admitted legacy instrument names the final included M1 bar. Therefore the exact adapter is:

- scientific configured end: `09:30+k`;
- instrument inclusive end-bar open: `09:30+k-1 minute`;
- causal freeze commit: `09:30+k`.

The session observation interval is `[09:30,16:00)`. The terminal label becomes available at the 16:00 boundary, after the final admitted 15:59 bar commit in causal ordering.

## Storage and causality

Raw bars are stored once. Range objects, candidates, and typed relations reference stable IDs. Candidate paths are reconstructed lazily from a candidate anchor and the session tape; no candidate-by-future-bar expansion is authoritative.

Raw OHLC fields remain distinct from observer-derived state. Final range geometry is unavailable before freeze. Candidate supersession is available at the committing bar close. Terminal survival is unavailable until session termination. Missing path coverage invalidates complete-chain claims without interpolation.

## Qualification boundary

Synthetic/adversarial fixtures qualify object, relation, availability, and coverage semantics. A fixed discovery session (`OBSOPEN_US30_20240102`) qualifies source parsing, New York/source-clock composition, 30 peer ranges, the full M1 session tape, and extreme-chain reconstruction. Frozen INST-01 fixture evidence qualifies the downstream adapter against admitted V2.10 buffer semantics. No full discovery census is produced.

The 69 confirmation sessions remain `FROZEN_UNOPENED`; zero confirmation observations may be read.

Maximum authority after all typed claims pass: `CAUSAL_SESSION_PROCESS_MEASUREMENT_V1`.

