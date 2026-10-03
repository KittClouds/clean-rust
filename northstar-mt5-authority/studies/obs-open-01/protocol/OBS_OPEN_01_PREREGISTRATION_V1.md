# OBS-OPEN-01 Preregistration v1

## 1. Scientific question

Determine whether reproducible observational structure exists in US30 price
behavior around and after the New York cash opening interval. If structure is
observed, characterize only what the admitted measurements support. Null,
mixed, conditional, scale-dependent, unstable, and insufficient-evidence
results are all admissible.

## 2. Forbidden authority

This protocol grants no economic or trading authority. Account state, orders,
positions, fills, proposals, profit and loss, execution, and downstream fund
results are outside the study boundary. They cannot rename, merge, split,
repair, or optimize an observational object.

## 3. Observer candidate

The candidate primitive is `OpeningRangeGrammar_v1_02_FullState`.

The archived source authority has SHA-256:

`d2c1f0614ba27289a87172dc9fa79f3b018cace73ebd5829afaf100aed406034`

The pre-existing compiled candidate observed with that source has SHA-256:

`5505e033d487037a9cc5863788b067123fbf5bc3e48d4c40ddfa0fbe721ac290`

The source is self-contained and has no include dependency closure. Source and
compiled identities remain separate. A successful source compile does not
prove byte-identical reconstruction of the pre-existing binary.

## 4. Frozen semantic distinctions

Lifecycle:

`NOT_EVALUABLE`, `WAITING`, `COLLECTING`, `FROZEN`, `COMPLETE`.

Completed-candle location:

`NOT_AVAILABLE`, `IN_ZONE`, `ABOVE`, `BELOW`.

Interaction events:

`NONE`, `IN_ZONE`, `FIRST_CLOSE_ABOVE`, `PERSIST_ABOVE`, `FAILED_ABOVE`,
`RETURN_FROM_ABOVE`, `FIRST_CLOSE_BELOW`, `PERSIST_BELOW`, `FAILED_BELOW`,
`RETURN_FROM_BELOW`, `CROSS_ABOVE_TO_BELOW`, `CROSS_BELOW_TO_ABOVE`,
`RESUME_IN_ZONE`, `RESUME_ABOVE`, `RESUME_BELOW`.

The source definition of these states is authoritative. Boundary closes are
`IN_ZONE`. A failed outside observation is exactly one observed outside close
followed by an in-zone close. A return follows an outside run of at least two
observed closes. A continuity gap emits a resume state rather than inventing an
unseen transition.

## 5. Opening interval family

For each admitted New York session, construct:

`Rk = [09:30, 09:30+k) America/New_York`, for every integer `k` from 1 to 30.

All 30 intervals are peers. No downstream behavior may select, privilege, or
remove an interval. Every range retains exact source-bar provenance.

## 6. Initial observational configuration

- Canonical instrument: `US30`.
- Source symbol: `US30` on the admitted MetaQuotes-Demo source.
- Geometry timeframe: `M1`.
- Initial interaction timeframe: `M5`.
- Civil observation start: `09:30 America/New_York`.
- Civil observation horizon: through `16:00 America/New_York`.
- Range family: `R01` through `R30` inclusive.
- Required M1 geometry coverage: every expected minute present.
- Required interaction continuity: explicit and gap-aware.

M5 is a frozen configuration coordinate for this first study, not a claim that
M5 is universally privileged. Any later interaction timeframe is a separately
identified observational configuration.

## 7. Clock authority

The instrument consumes broker/server chart timestamps and performs no timezone
inference. Therefore each session requires a causal clock-map receipt containing:

- New York civil session date and IANA timezone identity;
- applicable New York UTC offset and DST state;
- source/broker server identity;
- source offset from UTC covering the relevant observation horizon;
- mapped server start, each range freeze, and server horizon end;
- source and method of every offset claim;
- ambiguity and discontinuity flags;
- receipt identity and knowledge time.

Mapping is computed through UTC, never by a fixed assumed offset:

`New York civil -> UTC -> source/server timestamp`.

The live clock probe qualifies only the instant it observes. It does not prove
historical broker-offset behavior. Strategy Tester clock functions use simulated
server/data time and do not independently recover historical server timezone.
Any session lacking independently supportable source-offset authority is
`NOT_EVALUABLE_CLOCK` and cannot enter the corpus.

## 8. Coverage and causal availability

For `Rk`, geometry is unavailable before its exact freeze time. Geometry is
evaluable only when all `k` expected M1 source bars exist inside the half-open
interval. Interaction observations use completed admitted-timeframe candles
whose causal close times occur after freeze and no later than the observation
horizon.

Absence states are typed. At minimum:

- `NOT_EVALUABLE_CLOCK`
- `NOT_EVALUABLE_SOURCE_COVERAGE`
- `NOT_EVALUABLE_CONTINUITY`
- `CENSORED_HORIZON`
- `CENSORED_DATA_END`
- `CENSORED_SHUTDOWN`
- `COMPLETE`

No typed state is encoded as a blank, numeric zero, false, omitted row, or
imputed ordinary observation.

## 9. Normalized storage

Source M1 and interaction bars are stored once per session. The 30 nested range
objects reference immutable source observation IDs; source bars are not copied
30 times. Lifecycle transitions, completed-candle interactions, and event
receipts reference session and range IDs.

Authoritative coordinates include raw timestamps, prices, OHLC observations,
range geometry, state codes, event sequence, coverage, and causal knowledge
times. Normalization, resampling, distance, clustering, graph projection, and
visualization are derived sidecars with separate identities.

Large raw artifacts remain on `D:`. Git receives only source, schemas, manifests,
compact receipts, logical hashes, and physical artifact metadata.

## 10. Dependence and multiplicity

`R01` through `R30` from one session are nested and not independent. Candles,
events, and ranges within a session are repeated observations. Analysis must use
session/run/time blocks and report support by independent session, period, and
source coverage. Thirty peer intervals do not authorize 30 uncorrected claims.

## 11. Qualification gates

Substantive results remain unopened until all required gates pass:

1. exact source and compiled candidate archived;
2. semantic source audit complete;
3. current source clock probe received;
4. historical/session clock-map method qualified;
5. US30 source metadata and data coverage qualified;
6. R01-R30 construction and causal freeze golden suite passes;
7. interaction grammar golden suite passes;
8. bounded replay is byte/logically deterministic;
9. run receipts and schema invariants pass;
10. observational session universe and untouched confirmation blocks are frozen.

Compile success, binary reconstruction, runtime parity, empirical coverage,
replay determinism, transport, and scientific findings are separate claims.

## 12. First permitted conclusion

Qualification may conclude only whether the observer and data are fit to begin
collection. It may not inspect or report substantive opening-range behavior.
