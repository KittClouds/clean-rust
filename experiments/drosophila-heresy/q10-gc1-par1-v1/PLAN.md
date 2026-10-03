# Q10-GC1-PAR1: Global Coalition Assembly

PAR1 assembles the qualified local PAR2 palettes into endpoint-wide candidate
states. It runs one fixed endpoint/set state per worker, combining one ZERO or
nonzero palette entry per raw group with a deterministic 48-state group beam.
Every combination is materialized from the frozen baseline bytes and replayed
through the exact sequential-f32 readout. Same-coordinate conflicts are hard
errors; ZERO is always allowed. Physical-support overlap is an annotation, not
an independence assumption.

The primary objective is whole-endpoint lexicographic readout quality. Final
geometry gates are hard; intermediate debt is recorded under a fixed widened
guard. PAR1 is engineering-only: it does not probe behavior, promote science,
or use the resulting endpoint in the scientific lineage.
