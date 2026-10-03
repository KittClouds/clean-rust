# Q10-CSC1-ORDER-FRONTIER1

## Purpose

Read-only comparison of the reachable valid frontier at interaction orders 1,
2, and 3 using only fresh current-lineage receipts. This identity performs no
replay and does not modify any parent artifact.

## Frozen parents

- Fresh singleton execution and its eight immutable singleton shards.
- Complete order-2 frontier execution and its eight immutable frontier shards.
- Complete order-3 frontier execution and its independent audit receipt.
- Order-3 range files named and hashed by the independent audit receipt.

Historical LR1, SALL1, MAT1, VR1, and other stale branches are excluded.

## Definitions

For each order and context, report:

- structural/evaluated population represented by the source receipts;
- final-geometry-valid population;
- valid states strictly better than fresh `V`;
- zero-mismatch readouts;
- explicitly confirmed distinct exact endpoints when the source schema supports
  the target-weight distinction;
- the best valid lexicographic score key
  `(mismatch_count, total_ulp_distance, residual_l2, maximum_absolute_residual)`.

Order 1 uses the fresh singleton records with `final_geometry_pass=true`.
Order 2 uses every record in the complete order-2 frontier. Order 3 uses every
record in the independently audited order-3 valid frontier.

The order-frontier comparison does not infer that a lower order is a subset of
a higher-order frontier. It compares the best recorded valid state per context
and the size of each measured valid frontier.

## Integrity gates

1. Every bound parent file exists and its SHA-256 is recorded.
2. Every expected source shard is present.
3. Order-2 shard hashes and counts match its execution receipt.
4. Order-3 range hashes and counts match the independent FRONT2 audit receipt.
5. Every parsed record has the expected context and a complete score key.
6. No duplicate source record identity is observed within an order.
7. No source file changes during the comparison.
8. The derived output tree contains only this comparison's declared files.

## Promotion

This is an engineering comparison only. It does not open GC2, AG1, behavior,
or any scientific seed bundle. The exact distinct-endpoint milestone remains
the sole gate for those branches.
