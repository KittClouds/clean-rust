# Q10-GC0-LR1-PAL1: Cancellation-Augmented Motif Palette Audit

This is a derived engineering child of MAT1-R1. It builds a per-case library
of the 201 already materialized successful LR1 pair motifs and audits their
readout support, physical support, geometry signatures, and compatibility
hypergraph. It performs no new candidate replay, search, global assembly,
behavior, or scientific promotion.

The eight LR1 contexts remain separate. A motif is identified by its case,
two consumed group choices, and its canonical coordinate-to-prefix map. The
library does not assume that a motif transfers between cases.

For each motif the audit preserves the exact MAT1-R1 pair state, both
component identities, full changed-coordinate map, readout hash, score,
geometry, repaired/damaged target rows, and the union of the two groups'
physical support rows. Per case it reports residual rows outside the motif
support, changed-row coverage, group-conflict edges, coordinate-conflict
edges, and a descriptive rank of component constraint-action vectors.

This is a support and compatibility audit only. It does not claim that the
motif library can be globally assembled, and it does not treat a support
union as proof of realizable global coverage.
