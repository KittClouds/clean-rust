# Q10-GC0: Global Candidate Palette Qualification

Q10-GC0 is an engineering-only qualification of a bounded, endpoint-local
candidate palette built from the qualified Q10-PF6-RH1-F2 runtime and its
sealed authority inputs. It does not change the RH1-F2 runtime, any parent
artifact, the learning protocol, or scientific interpretation.

The first execution is deliberately a fixed qualification sample because the
full 55-group library would require a large exact replay surface. The sealed
sample contains the first four endpoint keys in the RH1-F2 canonical endpoint
order, with every RH1-F2 primary or secondary group belonging to those keys:

```text
seed9731-L-tau16.json / sets 0,1,2,3
seed9731-L-tau4.json  / sets 0,1,2,3
seed9731-R-tau16.json / sets 1,3
seed9731-R-tau4.json  / sets 0,1,2,3
```

The sample and all cutoffs are part of the sealed contract. Each selected
group uses the authority ranking from RH1-F2 and horizon
`min(32, coordinate_count)`. Candidate replay is exact sequential binary32
readout: each row starts at binary32 `-0.0` and adds the committed binary32
weight for each coordinate in row order, rounding after every addition.

For each group, zero is retained explicitly and the runner attempts eight
distinct nonzero candidates. The bounded deterministic frontier evaluates at
most 512 unique prefix states per group, with a frontier width of 32 and a
fixed expansion order. Every retained candidate is re-materialized from its
committed f32 bits before scoring. Reported candidates are never additive
surrogates.

Candidate identity is the SHA-256 of the canonical coordinate-id to prefix
map sorted by coordinate id. Visitation order, authority rank position, beam
lane, and exploration order are excluded from identity. Palette roles are
selected in this fixed order: best D, best P, lowest collateral, lowest axis
debt, lowest norm debt, lowest linear-drive debt, distinct active-coordinate
support, and distinct prefix-scale profile. Duplicate identities are merged
with all applicable roles; remaining slots are filled by the complete
lexicographic key.

The global support gate compares the union of physical rows touched by
retained nonzero candidates with the baseline global mismatch set in the
sample. `SUPPORT_INCOMPLETE_DIAGNOSTIC_ONLY` is the only permitted incomplete
classification. It never becomes a global infeasibility claim and never
authorizes GC1 global coalition assembly. Coordinate/readout conflict
topology is emitted as diagnostics only.

No behavioral seeds, accuracy, reward, action, scientific promotion, or GC1
assembly are in scope. Parent drift, malformed input, non-finite arithmetic,
illegal prefixes, candidate identity drift, or a missing required receipt
fails closed.
