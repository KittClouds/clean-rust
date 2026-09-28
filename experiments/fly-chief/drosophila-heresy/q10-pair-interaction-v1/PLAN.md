# Q10-PI1: Target-blind pair interaction mapping

Q10-PI1 is an engineering-only map of sequential binary32 pair interactions
around the committed alternate produced by Q10-SM. It owns the fresh engineering
seeds `9721` and `9722`, sides `R` and `L`, tau values `4` and `16`, and trial
`128`, for eight declared events. It does not own a behavioral endpoint,
scientific seed bundle, DH08B, or a repair policy.

For each event the mapper freezes 64 unique shared pairs and 32 unique disjoint
pairs. Pair selection is target-blind and uses one coordinate-to-row incidence
build, stable hash ordering, round-robin row anchors for shared pairs, and
bounded offset pairing for disjoint controls. It never enumerates the full
eligible pair universe. Occurrence positions, duplicate coordinate occurrences,
row order, and position distance are retained only for the selected pairs.

Each selected pair records all 100 combinations of the signed endpoint
vocabulary `[-1,+1,-2,+2,-4,+4,-8,+8,-16,+16]` ULPs from the initial committed
f32 weight. Every combination retains its replacement bits, sparse joint
readout bits, sparse interaction vector `I = joint - single_a - single_b +
baseline`, raw L2 norm, and normalization by the target-independent baseline
readout L2 with floor `1e-12`. Empty sparse interaction is a valid result.

The mapper writes a target-blind replay fixture and then a create-new pair-map
file. The map is flushed and SHA-256 hashed before any overlay target is read.
The overlay fixture is separate and contains target committed/readout bits only.
It reports `cos(I, -error)`, additive error norm, actual joint error norm,
bitwise mismatch count, and Pareto improvement versus the committed-alternate
baseline. A representative selected pair from each category is checked against
the full sequential oracle before the receipt is accepted.

If Q10-SM is unavailable or an event lacks the frozen structural capacity, the
event is recorded as an explicit failure with its denominator and reason. The
runner does not resample, substitute seeds, or silently drop an event. No sample
runner or seal is executed in this pre-review state.

Scientific seed bundles: `0`.

Behavioral inference: `false`.

DH08B authorization: `false`.
