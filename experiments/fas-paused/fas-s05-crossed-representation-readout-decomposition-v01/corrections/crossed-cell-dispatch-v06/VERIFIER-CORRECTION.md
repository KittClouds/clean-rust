# S05 Crossed Cell Dispatch Correction v06

The v05 preflight passed and sealed its 512-event original population and
4,933-quartet S01 population. The first v05 analysis call stopped at its first
FAS-00 cell lookup, before producing logits or writing scientific result
files. The execution table used descriptive representation labels
(`mean_full`, `final_position`) to index internal arrays keyed by `M` and `F`.

This correction adds a fixed internal cell-to-array-key map while preserving
the descriptive cell definitions in the output. A unit test checks both
representations of the mapping. No population, probe, scaler, calculation,
metric, or scientific decision rule changes. The v06 run uses a distinct
output directory and repeats the full parent and population preflight.

No model contact, feature extraction, probe fitting, or adaptive mechanism is
authorized or performed by this correction.
