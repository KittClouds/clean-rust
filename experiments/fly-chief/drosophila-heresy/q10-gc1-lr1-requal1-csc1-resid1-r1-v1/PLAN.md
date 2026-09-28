# Q10-RESID1-R1

## Purpose

Read-only residual-authority audit for the 123 residual rows of the current
global-best `R tau4 set3` state.

Inputs are the complete order-1 materialization, the complete order-2 valid
frontier readouts, and the compact exact order-3 semantic materialization.
No replay is performed here.

## Per-row questions

For each residual row, determine:

- whether any valid state through order 3 changes it from the reference;
- whether any valid state reaches the exact target bit value;
- the first order at which target attainment is observed;
- the best mismatch count among states attaining that row's target;
- the minimum damaged-correct-row count among those states.

Classifications are deterministic:

- `NO_EFFECT_AUTHORITY`;
- `MOVABLE_NOT_TARGETABLE`;
- `TARGETABLE_AND_COMPATIBLE` when target attainment occurs at mismatch count
  no greater than the 123-mismatch reference;
- `TARGETABLE_WITH_COLLATERAL_LOCK` otherwise.

## Co-attainment

Build a 123 by 123 co-attainment matrix over all valid states through order 3.
An entry counts states in which both residual rows equal their target bits.

## Integrity

Bind all source execution receipts and materialized payload hashes. Verify all
source files remain unchanged. This identity performs no replay and does not
open order 4, AG1, GC2, behavior, or scientific promotion.
