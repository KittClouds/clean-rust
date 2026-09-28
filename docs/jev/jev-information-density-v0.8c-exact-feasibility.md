# Jev Information-Density v0.8C: Exact Feasibility and Matched-Bank Construction

**Status:** frozen feasibility protocol. v0.8, v0.8B, and their receipts remain immutable. No model, feature cache, or evaluation output may be read. Phoenix remains out of scope.

## Purpose and phase boundary

v0.8B demonstrated that its deterministic heuristic constructor could not realize the target profiles. It did not establish that the profiles are infeasible. v0.8C tests feasibility against the declared acceptance constraints using an exact integer model.

Phase 1 has no curation or random-priority objective. It answers feasibility separately for the R100 and C100 composition profiles. A solver result of `UNKNOWN`, a timeout, memory exhaustion, or invalid-model status is not an infeasibility proof and does not trigger the fallback.

Important witness observation: the candidate pool includes the existing R100 and C100 groups, and each target profile is defined from that same bank. Therefore R100 is already a direct feasible witness for the R100 profile, and C100 is a direct feasible witness for the C100 profile: every exact marginal matches itself and every bounded distance is zero. Phase 1 is consequently `FEASIBLE` for both profiles without a CP-SAT search. An exact feasibility solver cannot prove either profile infeasible unless an additional requirement excludes or materially limits overlap with the source bank. v0.8C does not silently invent that requirement. CP-SAT is reserved for Phase 2 optimization under the existing constraints.

Only after a target profile is proven feasible may a later frozen phase optimize CM100 or RM100. No LFM/model contact is authorized until all required bank construction and integrity audits pass.

## Frozen inputs

The exact v0.8B contract and source identities are pinned in `experiments/jev-information-density-v08c/v08c-contract.json`. The candidate universe is the 416,672-group eligible training pool derived from the pinned 500k universe after excluding the pinned NewTight-Eval families. R100, C100, NewTight-Eval, and all earlier artifacts remain read-only.

The v0.8B contract JSON also records exact per-joint-cell input histograms and exact root multiplicities as choices made by its failed constructor. v0.8C follows the declared bank-acceptance bounds in the v0.8B selection design: global input/root occurrence-histogram TV ≤0.02 and unique-count ranges ±2%. The old constructor's stricter per-cell/exact-root requirements are not additional acceptance criteria in v0.8C. This precedence is explicit here; no v0.8B artifact or result is rewritten.

## Phase 1 feasibility model

For each eligible group `g`, conceptually define `x_g ∈ {0,1}`. An exact aggregation may combine groups only when they are interchangeable on every constrained dimension: input signature, root ID, exact joint cell, topology feature multiset, and intervention class. The aggregate integer variable is bounded by the number of distinct source groups in that atom; after a feasible solution, distinct group IDs can be selected from the atom without replacement. This aggregation must be shown equivalent to the group-level model.

For each target profile, enforce:

- Exactly 100,000 selected groups.
- Exact counts in every v0.8B joint cell: `(world_family, split_family_bundle_id, query_view_type, candidate_cardinality_bin, posterior_entropy_quintile, gold_entropy_band)`. These imply the exact query-view, cardinality, bundle, and entropy-stratum margins.
- Unique model-input and unique-root counts within the frozen ±2% outward-rounded intervals.
- Input-occurrence and root-occurrence histogram TV no greater than 0.02.
- Ontology-topology and intervention-class marginal TV no greater than 0.02.
- Selection only from the eligible training pool; no evaluation or protected-family groups.

For occurrence histograms `H_s(k)` and a fixed reference histogram `H_r(k)`, with totals `N_s` and `N_r`, the exact integer constraint is:

`25 × Σ_k |N_r H_s(k) − N_s H_r(k)| ≤ N_s N_r`.

This is algebraically equivalent to `TV(H_s,H_r) ≤ 0.02`; no floating-point tolerance is used. Topology marginals use the same normalized-count formula. Intervention counts have fixed total 100,000, so their TV limit is `Σ_j |I_s(j) − I_r(j)| ≤ 4,000`.

The model must encode the full range of selected multiplicities allowed by source capacities, not only the multiplicities observed in the target bank. No exact root histogram or per-cell input histogram may be imposed unless it is an explicit contract constraint; neither is required by the v0.8B acceptance bounds.

## Solver and result semantics

Use the pinned OR-Tools CP-SAT implementation recorded in the environment receipt. Phase 1 has no objective. Use one worker and a frozen seed for reproducibility. Each profile has a 30-minute wall-clock limit; record the exact solver status, wall time, conflicts, branches, model dimensions, and version.

Status mapping:

- `FEASIBLE` / `OPTIMAL`: a witness exists. Save a hash of the selected atom counts and, if the protocol advances, the expanded group-ID manifest.
- `INFEASIBLE`: the solver proved infeasibility for the encoded model. Use assumption groups for joint-cell, input, root, topology, and intervention constraints; report the returned sufficient unsat core as sufficient, not necessarily minimal.
- `UNKNOWN`: no feasibility conclusion. Do not invoke the fallback or contact a model.
- `MODEL_INVALID` or input/hash mismatch: stop; repair only under a separately recorded engineering correction before solving.

Feasibility applies to the exact encoded constraints and their tested input hashes. It is not a proof about every conceivable representation of the science contract.

## Predeclared common-support fallback

The fallback is invoked only if either original profile returns a proven `INFEASIBLE`. It does not change, pad, or relabel R100, C100, or StrictNovel93.

Derive a common joint-cell profile `P*` solely from eligible-pool counts, without models or evaluation outcomes:

1. Allocate 100,000 joint-cell quotas proportional to eligible support using deterministic largest-remainder apportionment.
2. Preserve at least 10,000 groups for each of choice, independent applicability, and ordinal views. If the eligible support cannot satisfy these floors while retaining the proportional allocation, record fallback infeasibility rather than lowering the floors.
3. Require every selected cell to have at least 2.5 eligible source groups per quota group. If this support ratio cannot be met, record fallback infeasibility.
4. Freeze the resulting `P*` counts and hash before constructing either bank.

Construct a random-priority R100* and a curation-priority C100* against the same exact `P*` cell quotas. The same v0.8B bounded matching constraints apply to each bank and to their matched profiles. First test feasibility with no objective. Optimize only in a later, separately frozen phase. If `P*` or either matched bank is infeasible, stop without relaxing criteria.

The support-centered fallback is a distinct estimand and must not be described as reproducing the historical R100/C100 composition factorial.

## Required receipts and stop condition

Store all solver inputs, model-size receipts, solver logs/statuses, witnesses or sufficient unsat cores, hash receipts, and a constraint-by-constraint verification independent of the solver model. No bank IDs are emitted from partial or unknown solutions.

v0.8C stops before model contact unless a later optimization phase has produced the required complete matched banks and all lineage/leakage audits pass.
