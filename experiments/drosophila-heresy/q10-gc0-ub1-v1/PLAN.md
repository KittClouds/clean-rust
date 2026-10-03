# Q10-GC0-UB1: Raw-Group Physical-Support Upper-Bound Audit

Q10-GC0-UB1 is an engineering-only, support-only audit. It asks whether the
union of physical rows touched by every raw PF5 group in the sealed Q10-GC0
endpoint/set sample could cover the sample's global baseline mismatch set.

The sample is sealed to the 14 endpoint/set keys in Q10-GC0. The runner loads
those states through the RH1-F2 runtime loader, which delegates state and raw
group construction to the sealed PF5 runtime. Every raw group returned for a
loaded state is included, ordered by the runtime group index. No frozen RH1
primary/secondary selection is used as the UB1 raw-group population.

For every state, baseline readout bits are recomputed with the PF5 sequential
binary32 readout from the loaded baseline weights and compared bit-for-bit with
the loaded target bits. Physical support is the union of rows in
`state.support_counts[coordinate]` for every coordinate in the raw group or
raw-group population. Covered and uncovered mismatch identities retain the
endpoint, set, row, baseline u32 bits, and target u32 bits.

The audit reports raw group counts, exact group-size distributions, union
physical support, mismatch counts, covered and uncovered mismatch identities,
coverage fractions, fixed size strata, and a comparison to the 55-group RH1
library projected onto the same sample. The RH1 comparison is diagnostic only.

This audit constructs no candidate palette, performs no candidate replay, and
does not run GC1. A complete raw physical-support result means only that the
raw support upper bound reaches every baseline mismatch row in this sealed
sample. An incomplete result is classified as a constructor partition
bottleneck diagnostic; it is not a global infeasibility claim.

All parent inputs are read-only. Parent hash drift, local seal drift, sample
selection drift, malformed raw groups, invalid support rows, or readout-bit
verification failure fails closed before the result is sealed.
