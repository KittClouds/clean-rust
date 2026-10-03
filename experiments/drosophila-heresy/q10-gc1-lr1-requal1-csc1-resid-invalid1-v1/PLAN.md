# Q10-RESID-INVALID1

## Purpose

Determine whether the exact target value for the 57 dependency-supported but non-targetable residual rows exists anywhere in the current structural order-1/2/3 action domain, including geometry-invalid states.

## Scope

- Context: `seed9731-R-tau4.json`, set `3`.
- Rows: `SUPPORTED_SINGLETON_SILENT` (20), `AUTHORITY_PRESENT_OUTSIDE_VALID_FRONTIER` (8), and `MOVABLE_NOT_TARGETABLE` (29).
- Domain: all current structurally compatible singleton, two-action, and three-action programs containing at least one action whose dependency footprint reaches one of those 57 rows.
- Functional evaluation: exact row-local sequential-f32 evaluation before geometry classification.
- Geometry: fast exact-composition evaluator with the sealed boundary fallback and no geometry prefilter.

## Frozen questions

For every supported residual row:

1. Does any current structural state change the row?
2. Does any state reach the exact target bits?
3. If the target is reached, is the state geometry-valid or geometry-invalid?
4. What is the closest observed ULP distance and the first interaction order producing it?

## Domain accounting

The runner must enumerate the ordered singleton, pair, and triple domains deterministically. It must seal per-order counts and domain hashes before reporting results. It must not select states using geometry, readout score, or target hits.

## Evidence boundary

This is an engineering reachability audit. It does not promote a scientific hypothesis, open order 4, or authorize GC2, AG1, behavior, or biological interpretation.

