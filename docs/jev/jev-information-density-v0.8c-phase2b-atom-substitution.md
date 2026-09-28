# Jev Information-Density v0.8C: Equivalent Atom Substitution

**Status:** prospective substage frozen before candidate materialization. It does not reopen the interrupted Phase 2 run or change the sealed Phase 2B contract.

This substage constructs only `CM100` and `RM100` by replacing groups within the exact atom-count vector of the existing `R100` and `C100` profile witnesses. An atom is the tuple of model-input digest, root ID, exact six-part joint cell, complete topology-feature tuple, and intervention family. Matching atom counts preserves every declared Phase 2 profile contribution exactly, including the input/root occurrence histograms and topology/intervention marginals.

Within each atom, the constructor selects the highest frozen Phase 2 priority ranks needed to meet the witness count. Because the objective is additive and all hard-constraint contributions are identical inside an atom, this is an exact optimum **conditional on the witness atom-count vector**. It says nothing about global optimality over other feasible atom-count vectors.

The separate raw-record validator reconstructs eligibility, held-out exclusion, profiles, atom counts, objective ranks, and objective bounds. Final ID-only manifests are emitted only if both candidates are non-identical, satisfy every frozen hard constraint, preserve their witness atom-count vectors, and beat their identity objective by at least one integer priority unit. That unit is a policy-separation check, not a downstream effect-size claim.

All candidate artifacts remain outside the repository. No model features or weights are touched, no Phoenix data is accessed, and no training is materialized. A passing construction ends this substage; model contact requires a separate explicit authorization.
