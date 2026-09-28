# Q10-LR1-VR1-R1: Cross-State Validator-Reuse Audit

This is a corrective child of `q10-gc1-cancel1-vr1-v1`. The first VR1 audit
included the case in its component identity, making its distinct-case count
structurally one. This revision pools identities by `(group, candidate)` and
retains case-specific validity counts, which is the intended cross-state reuse
question. The source MAT1-R1 library and all pair observations remain
unchanged.

This is a derived, read-only audit of the authoritative 201-pair library
from `q10-gc1-cancel1-mat1-r1-v1`. It performs no new replay, search,
palette construction, global assembly, behavior, or scientific promotion.

The audit asks whether the same case/group/replacement identity recurs across
successful LR1 pairs, and whether recurrence is associated with the component
being individually geometry-invalid, individually valid, or the better
singleton by the frozen lexicographic score. These are associative labels;
they do not establish that a component causally validates its partner.

For every MAT1-R1 pair the audit preserves:

- the two canonical component identities;
- singleton validity and score for each component;
- pair validity and geometry class;
- best-single comparison with stable ties;
- whether the pair is invalid+invalid, one-invalid, or valid+valid;
- partner identity and case context.

For every repeated component identity it reports successful-pair count,
distinct partner count, case count, singleton validity counts, best-single
counts, and geometry-class counts. The source MAT1-R1 record hash is bound in
the contract and rechecked before any output is written.

The result is an engineering reuse map only. A repeated component is not a
validator primitive, and a component's association with a successful pair is
not a causal allocation of the pair's validity.
