# Q10-RESID-SUPPORT1

Read-only decomposition of residual-row authority for the `R tau4 set3` global
reference. The audit covers the 123 residual rows and separately reports the 61
rows classified as `NO_EFFECT_AUTHORITY` by RESID1-R1.

The hierarchy is frozen before reading aggregate outcomes:

1. `NO_PRIMITIVE_DEPENDENCY_SUPPORT`: no singleton action dependency closure
   contains the row.
2. `SUPPORTED_SINGLETON_SILENT`: dependency support exists, but no materialized
   singleton readout changes the row relative to the reference.
3. `AUTHORITY_PRESENT_OUTSIDE_VALID_FRONTIER`: an invalid singleton changes the
   row, but no valid order-1 through order-3 state in the audited frontiers does.
4. `VALID_FRONTIER_AUTHORITY_OBSERVED`: a valid frontier state changes the row.

This identity performs no replay. It cannot distinguish geometry-excluded
authority from higher-order authority beyond order 3 when only invalid singleton
evidence is present; those cases remain explicitly unresolved.

Engineering evidence only. Order 4, GC2, AG1, behavior, and scientific promotion
remain closed.
