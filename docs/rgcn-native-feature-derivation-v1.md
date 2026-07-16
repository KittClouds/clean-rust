# R-GCN Native Feature Derivation v1

Status: Cut 4 implemented. Cut 5 launch-locked by the Phase 3 single-task gate.

## Boundary

This cut extends the existing 16-wide Phoenix R-GCN input surface without
changing its hidden width, layer count, propagation rule, or decoder. It does
not introduce a second encoder or a learned preprocessing network.

The source is a frozen native decision trajectory plus one authoritative row
for every candidate action. Each authority row binds:

- decision and candidate identities;
- temporal split and observation cutoff;
- immutable pre-state identity;
- train-fitted topology identity and fit-through time;
- graph authority and source receipts;
- latest time visible to every derived value;
- source node, target node, and relation type;
- raw label-free measurements.

Topology must be fitted from the train split and through a time no later than
the evaluated decision cutoff. Dynamic measurements may use the state knowable
at that decision cutoff; they may not use later evidence, memberships,
revisions, proposals, or outcomes.

## Fixed 16-wide contract

The contract is signed `i16` fixed point with scale 1000. Every transform is
bounded and fit-free. Validation and test therefore cannot inherit learned
normalization statistics.

| Column | Feature | Family | Transform |
| ---: | --- | --- | --- |
| 0 | typed in-degree | typed adjacency | clamp count to 1000 |
| 1 | typed out-degree | typed adjacency | clamp count to 1000 |
| 2 | typed neighbor overlap | typed adjacency | basis points / 10 |
| 3 | qualifier incidence count | qualifier incidence | clamp count |
| 4 | qualifier role diversity | qualifier incidence | clamp count |
| 5 | age of latest visible fact | temporal history | fixed one-year cap ratio |
| 6 | latest-to-prior fact gap | temporal history | fixed one-year cap ratio |
| 7 | evidence-source diversity | evidence | clamp count |
| 8 | evidence count | evidence | clamp count |
| 9 | revision depth | revision structure | clamp count |
| 10 | visible episode memberships | episode membership | clamp count |
| 11 | prior accepted proposals | proposal history | clamp count |
| 12 | prior rejected proposals | proposal history | clamp count |
| 13 | discrepancy state | discrepancy state | closed-enum ratio |
| 14 | authority class | authority/confidence | closed-class ratio |
| 15 | confidence class | authority/confidence | closed-class ratio |

Qualifier role diversity cannot exceed qualifier incidence count. Evidence
source diversity cannot exceed evidence count. Prior fact time cannot exceed
latest fact time. Every fact time must be covered by the authority row's
`available_through`, and `available_through` cannot exceed the decision cutoff.

## Authority tribunal

Installation fails before a derivation identity is issued when:

- a candidate lacks exactly one authority row;
- candidate coverage is not 100 percent;
- a row is duplicated or bound to the wrong decision;
- pre-state, split, cutoff, or candidate identity drifts;
- topology is not train-fitted;
- topology or feature authority extends past the cutoff;
- authority or source receipts are missing;
- raw count invariants are impossible;
- any closed class is out of range.

The snapshot identity binds the trajectory dataset, every topology identity,
policy, all 16 column certificates, leakage audit, row order, graph coordinates,
and exact fixed-point feature bits.

## Ablation suite

Every feature family preserves four interventions:

1. `real`: the certified feature columns.
2. `masked`: only that family's columns become zero.
3. `shuffled`: only that family's column tuples move between candidates.
4. `future-leak sentinel`: a copied authority row is moved one tick beyond its
   cutoff and must be rejected by the normal validator.

Shuffling is deterministic from the certified seed and occurs independently
inside train, validation, and test. No feature tuple crosses a split. The
shuffled multiset is therefore exact while candidate association is destroyed.

The future sentinel is not a usable feature artifact. Its rejection is recorded
as a required boolean in every snapshot audit and ablation suite. A derivation
whose sentinel is accepted cannot receive an identity.

## Cut 5 launch boundary

R-GCN Multi-Task Workhorse v3's identity and promotion tribunal are implemented,
but its trainer and weights are intentionally not implemented in this cut.
Phase 3 established a hard ordering rule: no multi-task trainer starts until
single-task baselines are understood. The native authority audit found zero
usable historical decisions, so the empirical baseline ladder remains unopened.

The content-addressed `NativeRgcnMultitaskLaunchGate` requires:

- a BLAKE3 baseline-ladder identity;
- nonzero authoritative task coverage;
- an explicit certificate that the single-task baselines are understood;
- a fixed important-task regression limit.

The current gate is locked. Changing its fields without recomputing its identity
fails before launch.

The v3 identity already requires the ordered task set, task sampling schedule,
loss reduction, fixed-point loss weights, per-head architecture, feature schema,
topology, seed, optimizer, clipping partition, checkpoint rule, encoder width,
layer count, and exact propagation rule. Certification is impossible while the
launch gate is locked.

The promotion certificate requires every head to beat its strongest baseline
across multiple certified seeds, reproduce weights and certificates, cold-load,
reject future leakage, maintain calibration, improve paired queries, satisfy the
important-task regression bound, and either allocate zero epoch bytes or carry a
non-empty measured deviation explanation.

When authority exists, Cut 5 must compare independent single-task R-GCN models
against one shared fused encoder with these ordered heads:

```text
episode assignment
delta disposition
discrepancy classification
evidence ranking
relation proposal
repair action
```

The contract exists now so none of these axes can be introduced as an informal
trainer default later. Actual head shapes, output widths, sampling ratios, and
loss weights remain unset until the single-task tribunal exposes the real task
shapes and pressure distribution.

## Verification gate

Cut 4 is complete when:

- the output is exactly 16 columns at fixed scale;
- all requested authority families are represented;
- derivation is deterministic;
- every family produces real, masked, and split-local shuffled identities;
- the future sentinel fails closed;
- feature mutation invalidates the snapshot identity;
- the multi-task gate rejects current zero-authority state;
- the full graph-research suite remains green.
