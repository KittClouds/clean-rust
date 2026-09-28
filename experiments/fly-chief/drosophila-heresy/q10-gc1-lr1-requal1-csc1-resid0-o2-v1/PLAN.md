# Q10-RESID0-O2

## Purpose

Read-only residual audit of the complete order-2 valid frontier for
`seed9731-R-tau4.json / set 3`, the context owning the current global best
score of 123 mismatches.

The order-2 frontier receipts contain full `readout_bits`. The current fresh
state loader supplies the target readout bits. No candidate replay or state
reconstruction is performed.

## Frozen reference

The reference is the lexicographically best order-2 valid frontier record in
the selected context, with `frontier_pair_index` as the deterministic tie
break. Its target-mismatch set is the residual reference set `R*`.

## Measurements

For every valid order-2 record, compute:

- exact target mismatch mask;
- residual rows repaired relative to `R*`;
- residual rows changed from the reference;
- previously correct rows damaged;
- net mismatch change;
- mismatch-mask identity and mask diversity.

For every row in `R*`, report whether the order-2 frontier ever changes it,
ever reaches the target bit value, and how often those events occur.

## Integrity gates

1. Fresh current-lineage target bits load successfully.
2. The selected order-2 context contains exactly 1,438 records.
3. Every record contains a complete readout bit vector.
4. Every readout vector has the target length.
5. No duplicate frontier index is observed.
6. Source hashes are unchanged during the audit.
7. No replay is executed.

This identity is engineering-only and does not open order 3, order 4, AG1,
GC2, behavior, or scientific promotion.
