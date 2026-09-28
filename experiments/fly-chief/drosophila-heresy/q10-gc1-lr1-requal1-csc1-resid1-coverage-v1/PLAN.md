# Q10-RESID1-COVERAGE

## Purpose

Read-only audit of whether the sealed order-1, order-2, and order-3 frontier
receipts contain the row-level readout vectors required for residual-authority
and mismatch-mask analysis.

This identity performs no replay, no reconstruction, and no outcome
interpretation. It exists to prevent aggregate scores or readout hashes from
being treated as row-level evidence.

## Required evidence for RESID1

For every candidate state whose residual rows are to be audited, the receipt
must contain either the complete committed readout vector or an immutable,
content-addressed sidecar containing that vector. A readout hash alone is not
sufficient to determine which rows are wrong, which rows were repaired, or
whether two near-frontier states have different mismatch masks.

## Bound parents

- Fresh singleton execution and eight singleton shards.
- Complete order-2 frontier execution and eight order-2 frontier shards.
- Complete order-3 frontier execution, its result ranges, and independent
  FRONT2 audit receipt.

Historical branches are excluded.

## Promotion rule

The coverage result is promoted only as a measurement-substrate finding. It
does not classify residual rows and does not update scientific hypotheses.

If order-3 row vectors are absent, RESID1 and FRONT-DIV1 remain blocked for
order-3 comparisons until a separately sealed materialization/replay identity
produces them.
