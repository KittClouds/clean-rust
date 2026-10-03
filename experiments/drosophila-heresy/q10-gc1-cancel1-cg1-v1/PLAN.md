# Q10-LR1-CG1: Constraint-Geometry Complementarity Audit

This is a derived, read-only audit of the 61 MAT1-R1 pairs in which both
singleton substitutions are individually geometry-invalid while the joint
pair is valid. It performs no new replay, search, palette construction,
global assembly, behavior, or scientific promotion.

For each pair, the audit reconstructs the signed constraint vector already
materialized by MAT1-R1:

```text
[axis debt, norm debt, full linear-drive debt vector]
```

It records each singleton displacement from the fixed invalid state `S`, the
joint displacement, the additive residual, gate-excess distances, failed-gate
signatures, and descriptive direction measures toward the admissible region.
The exact MAT1-R1 interaction fields remain authoritative; this audit only
re-expresses them in constraint-space terms.

The output distinguishes same-face and cross-face geometry cases. It reports
which singleton moves reduce each violated scalar gate and whether the joint
state crosses the gate. The linear-drive block is retained as a vector; its
scalar gate is reported separately.

All direction and face labels are descriptive. They do not allocate causal
credit to either component and do not establish a reusable validator
primitive.
