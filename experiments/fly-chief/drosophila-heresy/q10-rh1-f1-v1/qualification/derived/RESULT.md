# RH1-F1 derived execution report

Raw execution: `RH1_F1_ENGINEERING_FACTORIAL_COMPLETE`; 55 groups and 220 arm receipts.

This is an engineering-only derivative. No behavioral or scientific promotion is authorized.

## Integrity

Interpretation status: `ENGINEERING_DESCRIPTIVE_ONLY_AUTHORITY_FACTOR_GATED`.

Structural receipt issues: `0`; all raw final geometry checks were required to pass before this report was generated.

The authority factor is gated because the sealed contract names `declared_support_count_desc`, while the AC2 feature table and runner use `declared_row_count`. The run also lacks preexecution bindings for the RH1 runner and PF5 contract hashes.

## Primary cohort

The primary cohort contains 32 groups. The D-domain results are the search objective; P and G are diagnostics.

- `residual__h16`: exact 0/32, mean D mismatches 3.625, mean D L2 2.153e-06.
- `residual__h32`: exact 0/32, mean D mismatches 2.938, mean D L2 1.955e-06.
- `authority__h16`: exact 1/32, mean D mismatches 2.969, mean D L2 1.907e-06.
- `authority__h32`: exact 6/32, mean D mismatches 2.094, mean D L2 1.349e-06.

Lexicographic D-domain paired comparisons:

- `horizon_residual`: left wins 0, right wins 13, ties 19; mean right-minus-left mismatches -0.688.
- `horizon_authority`: left wins 0, right wins 16, ties 16; mean right-minus-left mismatches -0.875.
- `ranking_h16`: left wins 11, right wins 18, ties 3; mean right-minus-left mismatches -0.656.
- `ranking_h32`: left wins 9, right wins 22, ties 1; mean right-minus-left mismatches -0.844.

## Secondary cohort

The 23 secondary groups are summarized separately with each long arm ending at its available coordinate horizon.

- `authority__h16`: exact 10/23, mean D mismatches 0.913.
- `residual__h16`: exact 5/23, mean D mismatches 1.609.

The immutable execution and all derived JSON remain the source of numerical detail; this report does not convert any engineering result into a scientific finding.
