# REQUAL1-SMOKE: eight-context current-lineage replay gate

This engineering-only smoke identity is downstream of the sealed
`q10-gc1-lr1-requal1-domain-r2-v1` domain closure. It selects one deterministic
nonzero candidate from the first current group in each of the eight contexts,
reconstructs its committed f32 bytes from the current closure, and performs one
exact learner-order sequential replay per context.

The smoke gate validates loader, canonical mapping, committed-byte hashing,
readout replay, geometry recomputation, and atomic receipt writing. It does not
open the 3,696-record singleton campaign, pair replay, behavioral probes, or
scientific promotion. Candidate scores are newly computed by this smoke run;
historical score fields are not imported as measurements.
