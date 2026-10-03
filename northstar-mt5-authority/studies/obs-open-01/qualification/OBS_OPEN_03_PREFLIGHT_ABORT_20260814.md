# OBS-OPEN-03 — Fail-Closed Preflight Abort

Status: `ABORTED_PREEXECUTION_PROTOCOL_INCOMPLETE`

OBS-OPEN-03 was restarted under the sealed universe, OBS-OPEN-02, and
OBS-OPEN-02R1 authorities. The authority preflight stopped execution before a
discovery census, formal estimand, aggregate, plot, candidate, or robustness
result was produced.

## Blocking contract gaps

The frozen artifacts still lack five executable definitions required by their
own stop conditions:

- several descriptive measurement names have no exact formulas;
- formal estimand templates lack explicit population, eligibility denominator,
  availability, and future-confirmation fields;
- chronological-block construction, leave-one-month-out construction, and
  per-view slice support are not defined;
- confirmation-estimand completeness is declared as a Boolean without an
  executable schema or constructor;
- rejection reason codes exist without an exhaustive transition table.

These are protocol semantics, not market findings. Filling them inside
OBS-OPEN-03 would mutate the eyepiece after discovery access was authorized.
The constitutional rule therefore requires a separately versioned repair.

## Access accounting

No confirmation observation was read. Confirmation remains
`FROZEN_UNOPENED`.

A source-schema sanity command materialized the header and two source rows from
2024-01-02. Both rows were outside the admitted opening-range and interaction
window; no observer value or preregistered measurement was computed from them.
This access is recorded explicitly rather than silently omitted.

Produced scientific outputs:

- discovery census rows: 0;
- formal estimands evaluated: 0;
- candidates produced: 0;
- confirmation observations read: 0.

The machine receipt is
`qualification/universe/obs-open-03-preflight/obs_open_03_preflight_receipt.json`.
OBS-OPEN-03 must not proceed until a separately sealed protocol repair resolves
these exact gaps without consulting discovery or confirmation values.

Economic authority: `false`.

Trading authority: `false`.
