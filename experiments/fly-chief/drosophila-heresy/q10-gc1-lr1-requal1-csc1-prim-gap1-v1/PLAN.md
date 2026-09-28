# Q10-PRIM-GAP1

## Purpose

Read-only decomposition of the 33 `NO_PRIMITIVE_DEPENDENCY_SUPPORT` residual rows from the fresh `R tau4 set3` lineage. This identity maps dependency-closure coordinates against the current singleton action grammar. It performs no readout replay, no new candidate generation, and no scientific promotion.

## Questions

For each unsupported residual row:

1. Which coordinates are in the exact dependency closure?
2. Which closure coordinates are represented by an existing nonzero singleton action?
3. Which closure coordinates admit a legal nonzero prefix under the current runtime but have no action representation?
4. Which closure coordinates have no legal nonzero prefix under the current prefix domain?

The audit must fail closed if an unsupported row has a mapped nonzero action coordinate inside its closure while its action-row closure remains empty.

## Frozen scope

- Context: `seed9731-R-tau4.json`, set `3`.
- Residual source: fresh `RESID-SUPPORT1` row classifications.
- Runtime: fresh current-lineage `ALG1 v2` and `FRONT2 v3` context construction.
- No historical LR1/SALL1/MAT1/VR1 artifacts are evidence.

## Outputs

The sealed output records the exact parent bindings, ordered unsupported-row domain hash, per-row coordinate partitions, aggregate classifications, and no-replay status.

## Gates

`PRIM-GAP1` does not open `RESID-INVALID1`, order 4, GC2, AG1, behavior, or scientific promotion. A later identity must decide how to measure supported-but-invalid functional values.

