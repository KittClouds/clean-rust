# OBS-OPEN-SRC-01 — recovered legacy observer authority

## Scope

SRC-01 is a source-authority recovery gate for the historical `BreakOut`
observer and its two translations. It is a new observer generation:
`LEGACY_BREAKOUT_OBSERVER_V1`. It does not rewrite the earlier OBS-OPEN-01,
OBS-OPEN-03, or OBS-OPEN-03A products. Those products remain preserved under
`RECONSTRUCTED_OBSERVER_V1` and are not silently reinterpreted.

The 69-session confirmation population remains `FROZEN_UNOPENED` until this
authority and a future claim protocol are separately sealed.

## Authority layers

The following are distinct and must not be conflated:

1. **Legacy source oracle** — original `BreakOut.mq5` buffers 0..3.
2. **Translated source** — `BreakOut2.mq5`, compared cell-for-cell with the
   original oracle.
3. **V2 compatibility buffers** — buffers 17..20 of
   `OpeningRangeGrammar_v2_00_LegacyStateMachine.mq5`.
4. **Causal grammar** — V2 lifecycle/geometry/eligibility/location/event
   buffers. These are qualified independently and are never inferred from a
   repainting legacy buffer.

Legacy buffers are historical/repainting observations unless a separate
causal receipt proves otherwise. A buffer parity result therefore proves
implementation equivalence, not causal knowledge time.

## Boundary contract

The recovered legacy range uses inclusive endpoint semantics for the period and
area boundaries. The synthetic fixture suite includes controlled endpoint bars
whose high or low is created late in the endpoint candle. These fixtures are
not market observations; they prevent an accidental half-open or close-only
implementation from passing naturally occurring data.

The capture matrix covers M1 and M5 at 09:29, 09:30, 09:34, 09:35, 09:39,
and 09:40. M5 minutes without a candle identity are explicitly
`NOT_APPLICABLE_TIMEFRAME_BOUNDARY`. Online snapshots, historical reloads, and
post-reload captures are separate evidence classes.

## Clock authority

SRC-01 freezes the source-clock inputs `09:30`, `09:35`, and `09:40` and audits
their observed M1/M5 boundary behavior. It does not independently requalify the
mapping from source-clock wall time to `America/New_York`; that transport
authority belongs to the separately preserved OBS-OPEN universe qualification.

## SRC-01 claims

Only the following claims may be earned:

- source/compiler/runtime identity is frozen;
- legacy oracle values were captured;
- source translations are cell-for-cell equivalent for admitted captures;
- V2 compatibility buffers are cell-for-cell equivalent for admitted captures;
- online, historical, and reload behavior agrees or is explicitly classified;
- causal knowledge time and grammar handoff are separately qualified;
- reconstruction is deterministic.

No claim about market behavior, opening-range regularity, prediction, or
economic value is granted by SRC-01.

## Stop rule

SRC-01 stops with a sealed receipt after authority, capture, boundary, parity,
causal, grammar, and reconstruction checks. Missing MT5 captures remain
`NOT_EVALUABLE_CAPTURE_MISSING`; they are never replaced by synthetic fixtures
or inferred from source code.
