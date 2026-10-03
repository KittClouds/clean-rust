# Q10-GC0-GP1-PF0: Full-Palette Workload Preflight

PF0 is a sealed engineering preflight for the next full raw-group candidate
palette. It loads the complete RA1 sample and the AC3-complete authority table,
checks that all 801 raw groups and 27,075 contextual coordinate records are
available, computes the exact inherited replay ceiling, and benchmarks a small
fixed set of real sequential-f32 candidate evaluations.

It does not generate a palette, write candidate records, run GC1, probe
behavior, or promote science. A later GP1 identity may use this gate to run the
full authority-aware palette only after the workload and authority inputs are
sealed.
