# Jev Information-Density v0.8B: Selection × Composition Factorial

**Status:** prospective pretraining protocol. The existing v0.8 banks and reports are immutable references. This amendment authorizes metadata-only feasibility analysis and construction of two additional ID manifests; it does not authorize model contact or training.

## Question

Separate selection quality from the composition/repetition policy induced by the existing static C100 selector.

| Composition target | Random selection | Curated selection |
|---|---|---|
| R100 profile | R100 (existing) | CM100 (new) |
| C100 profile | RM100 (new) | C100 (existing) |

The estimands are computed per metric, never as one aggregate score:

- Selection under the R100 profile: `CM100 - R100`.
- Selection under the C100 profile: `C100 - RM100`.
- Composition under random selection: `RM100 - R100`.
- Composition under curated selection: `C100 - CM100`.
- Interaction: `(C100 - RM100) - (CM100 - R100)`.

## Immutable inputs

Use the existing 500k universe, family split, R100, and C100 without modification. Their sealed identity is recorded in `experiments/jev-information-density-v08b/v08b-contract.json`. StrictNovel93 remains outside this factorial and unchanged.

Eligible candidates come only from the existing 416,672-group training pool. NewTight-Eval and all protected families remain excluded. No model outputs, features, embeddings, Phoenix data, or protected labels may be read.

## Frozen matching rules

Each new bank has exactly 100,000 groups. Match its reference bank at these levels:

### Tier 1 — exact

- Group count.
- Query-view counts.
- Candidate-cardinality-bin counts.
- Counts in every joint cell keyed by `(world_family, split_family_bundle_id, query_view_type, candidate_cardinality_bin, posterior_entropy_quintile, gold_entropy_band)`.
- Zero membership in NewTight-Eval or any protected family.

The exact joint cells preserve the query, cardinality, entropy, world, and family-bundle composition simultaneously, not only their separate marginals.

### Tier 2 — bounded distribution matching

- Unique model-input count within ±2% of the reference bank.
- Total-variation distance (TV) ≤0.02 for the histogram of selected group occurrences per distinct model-input signature.
- Unique-root count within ±2% of the reference.
- TV ≤0.02 for the histogram of selected groups per root.
- TV ≤0.02 for ontology-topology and intervention-class marginals.

TV is `0.5 * sum(abs(p_i - q_i))`, with absent categories treated as zero. Scalar tolerances are relative to the reference, with the integer acceptance interval rounded outward.

All limits are frozen before CM100/RM100 selection. If either bank cannot meet every limit, report infeasibility and emit no passing bank; do not loosen thresholds after observing a failed attempt.

## Selection procedures

- **CM100:** use R100's exact joint-cell quotas. Within each quota, prioritize the frozen v0.8 static rarity-weighted coverage score and deterministic tie-break. Enforce the Tier 2 limits through a deterministic constrained selection procedure.
- **RM100:** use C100's exact joint-cell quotas. Select randomly within the same constraints using a new frozen seed; do not use rarity, difficulty, or model behavior to rank examples.
- Both use the same eligible universe and count budget. Existing R100/C100 remain unchanged.

The preflight must establish candidate support for the exact joint cells and report capacity bounds for input/root multiplicity targets. Manifest generation is allowed only after the v0.8B contract hash is recorded and the preflight reports the solver can attempt the frozen limits. A failed construction is a failed v0.8B run, not permission for an undocumented retry policy.

## Required receipts

- Frozen v0.8B contract and hash.
- Count-only support/feasibility audit.
- CM100 and RM100 ID manifests and hashes, if feasible.
- Four-bank joint-cell and marginal comparison.
- Input- and root-multiplicity diagnostics.
- Leakage/conflicting-gold verification for all four banks.
- Integrity receipt confirming v0.8, StrictNovel93, protected sources, models, and Phoenix were untouched.

Training banks are not materialized in this slice. LFM feature extraction/training requires a separate explicit start after the factorial receipts pass.
