# Q10-READ-INC1: exact incremental readout audit

This read-only engineering audit consumes the fresh UPAIR1 singleton and pair
receipts. For each of the 17,712 realized disjoint pairs it reconstructs the
final committed weight state, copies the fixed-state readout for unaffected
rows, and executes the original sequential-f32 readout only for rows whose
support intersects a changed coordinate.

The incremental vector must match the authoritative full pair readout bit for
bit. No additive readout surrogate is used. This does not open order-3
construction, global assembly, GC2, AG1, behavior, or scientific seeds.
