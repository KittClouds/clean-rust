# Phase 2C bounded cross-atom search

The metadata-only mobility census found no alternate atom sharing the exact `(model input, root, joint cell)` core. This does not establish that the inherited profile is globally locked: the profile permits bounded deviations in input/root uniqueness and occurrence histograms. The frozen search therefore moves atom counts only within an identical exact joint cell and independently checks every inherited profile constraint before accepting each unit transfer.

RM100 is searched first from the C100 witness. CM100 is searched only if RM100 clears the treatment and objective gates, and starts from the atom-preserving CM100 candidate. In either arm, the member list for an atom is a deterministic prefix under the frozen global policy priority. The bounded neighborhood, ordering, seed, limits, stop proxy, and checkpoints are frozen in `v08c-phase2c-search-contract.json` before search.

During search, unique input/root counts use a strict fractional relative-error check of at most 0.02. This is a conservative subset of the parent validator's outward integer rounding when the 2% endpoint is fractional; it avoids accepting a move that the simpler fractional form would reject.

This is a bounded construction attempt, not an optimality proof. A timeout or exhausted neighborhood is reported as unknown, not infeasible. Every emitted provisional bank requires an independent raw-record validator. No model contact or training is authorized by this search contract.
