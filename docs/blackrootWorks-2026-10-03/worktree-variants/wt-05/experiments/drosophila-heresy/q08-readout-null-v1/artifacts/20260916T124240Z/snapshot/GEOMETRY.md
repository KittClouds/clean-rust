# Constructor geometry and interpretation

For each coordinate group, let `d` be the true displacement and let `L` contain the local
all-ones row and acquisition-axis row. Write `d = c + u`, with `c` in the row space of `L`
and `u` in its nullspace. Holding `c` fixed and rotating `u` preserves the group sum, axis dot,
and squared norm because the two spaces are orthogonal.

A four-coordinate block normally has two nullspace dimensions, so its fixed-norm surface is a
circle. If the acquisition row is proportional to the ones row, the nullspace has three dimensions.
If a block has fewer than four available coordinates, its continuous freedom can be smaller or
absent. A constructor must distinguish numerical rank from group size.

Grouping by both MBON and cue-membership signature ensures each cue includes either all group
coordinates or none. Preserving each group sum therefore preserves all 16 cue-by-MBON drive sums
in real arithmetic. It does not guarantee identical sequential f32 sums: f32 rounding and sum order
are additional constraints, checked on committed bytes by the frozen drive and score gates.

## An optimistic decorrelation bound

Across independently rotatable groups, let `F` be fixed-component squared energy and `V` be
rotatable nullspace squared energy. Include frozen boundary and inactive coordinates in `F`.
Let `p` be the true global acquisition-axis projection and `R2 = F + V - p*p` the global
acquisition-orthogonal residual energy.

Ignoring bounds and discrete low-rank restrictions, the true/null residual cross-dot lies inside:

`[F - V - p*p, F + V - p*p]`.

Consequently, if `F - V - p*p > 0`, the optimistic absolute residual cosine floor is:

`(F - V - p*p) / R2`.

Otherwise this optimistic floor is zero. A zero floor is not a guarantee of a feasible solution:
weight bounds, boundary membership, partial block coverage, and f32 storage may restrict it further.
A positive floor above the frozen gate is a certificate of overconstraint for that exact grouping
and fixed-component contract, not for all possible nonlinear readout-matching constructions.

## Scientific limit

Preserved cue drives constrain the immediate per-MBON Bernoulli probabilities more strongly than
preserved aggregate cue margins. Later distractor responses and synapse-specific eligibility can
still differ. In a future closed-loop study, any effect is the effect of an adaptive endpoint
replacement policy with these local invariants. Its cumulative doses are outcomes, not matched
constants. Qualification success alone establishes no behavioral benefit or forgetting mechanism.
