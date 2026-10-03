# Q10-O3-MASKMAT1

## Purpose

Materialize compact exact row semantics for the complete order-3 valid
frontier in `seed9731-R-tau4.json / set 3`, the context containing the current
global best score.

The run uses the already qualified order-3 localized sequential-f32 path. It
does not persist full readout vectors. For every state it persists:

- exact target-mismatch bitset;
- exact changed-from-reference bitset;
- exact raw output bits for the frozen 123 residual rows;
- score and reconstruction metadata.

## Frozen reference

The reference readout is order-2 frontier record 0 in the same context. Its
score is `(123, 162, 1.866006202952065e-05, 7.62939453125e-06)`. The run
requires that its readout hash equal the FRONT2 order-3 best-state hash.

## Exactness gates

1. O3-LOCQUAL1 is complete.
2. Every order-3 source result record has a matching EXH1 source record.
3. Localized readout reproduces every FRONT2 result readout hash and score.
4. Every target comparison uses exact output bits, including signed zero.
5. Every semantic record has fixed binary layout and an indexed JSON metadata
   record.
6. The complete 225,429-record context is materialized.
7. All bound sources remain unchanged during execution.

This is engineering-only. It does not open order 4, AG1, GC2, behavior, or
scientific promotion.
