# Jev Information-Density v0.8C Phase 2B

**Status:** prospective amendment frozen before any Phase 2B candidate search. The prior Phase 2 run remains `INTERRUPTED_UNKNOWN`; this amendment neither reopens nor rewrites it. It authorizes metadata-only witness validation and instrumentation work. It does not authorize model contact or Phoenix access.

## Purpose

Phase 1's R100 and C100 identity witnesses prove that their respective reference profiles are non-empty. They do not prove that a distinct CM100 or RM100 satisfying the complete acceptance rules exists, nor that either construction can achieve a material treatment effect.

Phase 2's 77-minute run returned no solver status and emitted no banks. That is a runtime/observability failure, not infeasibility and not evidence of low policy headroom. The original contracts, inputs, outputs, and failed run remain immutable.

Phase 2B preserves the candidate universe, profile definitions, hard constraints, policy objectives, seeds, and model-feedback prohibition. It prospectively amends only the construction procedure, status semantics, and candidate acceptance rules as recorded in `experiments/jev-information-density-v08c/v08c-phase2b-contract.json`.

## Feasibility and counterfactual status are separate

Each witness receives `PROFILE_FEASIBLE` only after an independent audit verifies source membership, eligibility, the full recomputed profile, and original selector reproducibility. Identity is not accepted as a counterfactual candidate because the new candidate must differ from its witness by at least one group ID.

The bank may overlap its witness otherwise; no overlap ceiling is introduced. Exact overlap counts and Jaccard similarity are reported. The statuses are separate dimensions:

| Dimension | Status meaning |
|---|---|
| Profile | `PROFILE_FEASIBLE` means an identity witness establishes the target profile. |
| Counterfactual | `COUNTERFACTUAL_FEASIBLE` means a non-identical candidate passes every hard constraint and independent audit. |
| Policy separation | `SEPARATED` means that candidate also beats its identity witness by at least one integer unit of its frozen maximization objective. |
| Optimality | `OPTIMAL` is reported only with a certified proof; `FEASIBLE_NOT_PROVEN` is acceptable under the inherited Phase 2 rule. |
| Search | `SEARCH_EXHAUSTED` means only that the declared budget ended. It never means infeasible or no remaining headroom. |

The one-unit separation threshold is the smallest strictly positive difference representable by the frozen integer-sum objective. It is a construction-level policy-score check, **not** a claim that the intervention is materially different for a model. Raw objective change, bank overlap, constituent score changes, and certified headroom are reported; no `0.70` or other headroom-ratio gate is used. A downstream effect-size threshold is not invented in this amendment.

For a maximization objective, report headroom recovery as the candidate-minus-identity objective gain divided by the valid upper bound minus the identity objective. The bound is the sum of the best frozen priority ranks needed within each exact joint cell, ignoring remaining constraints. It is therefore valid but potentially loose. A zero/non-positive denominator is handled explicitly. The ratio is diagnostic, never evidence by itself that little or much treatment is achievable.

## Frozen source and acceptance rules

The amendment pins the Phase 2 contract, raw group-record universe, R100/C100/Eval manifests, Phase 1 receipt, and source contracts. The complete hard-constraint list is inherited unchanged: 100,000 groups; exact joint-cell counts; outward-rounded ±2% unique-input and unique-root bounds; input/root multiplicity histogram TV ≤0.02; topology/intervention marginal TV ≤0.02; exclusion of held-out/protected families; and no extra exact root or per-cell input histogram.

The original Phase 2 objectives and their arithmetic remain frozen. The random objective is deterministic seeded random-priority optimization (equivalently minimizing the frozen rank cost), **not** uniform sampling from all feasible banks. All objective and tie-break details are in the machine-readable contract.

## Independent witness audit

`experiments/jev-information-density-v08c/validate_phase2b_witnesses.py` does not import the selector, bank builder, or feasibility solver. It streams the pinned raw metadata, reconstructs the family-bundle holdout and training-only entropy quintiles, recomputes the witness profiles, and reproduces the original R100/C100 selector manifests exactly. It also computes identity objective values and valid cell-relaxed bounds under the Phase 2 objectives. The receipt is written externally; raw corpus text is neither exported nor copied.

Passing this audit establishes `PROFILE_FEASIBLE` only. If any pin, membership, selector, or profile check fails, Phase 2B stops before search.

## Instrumented execution and bounded construction

Before replacing the old pipeline, one baseline is measured with a 15-minute cap starting after source loading. The event stream records source load/indexing, feature/rank construction, constraint/model build, finalization, presolve/search, incumbent validation, and output serialization. Search receipts include elapsed time, best available objective, certified bound where available, and time since the last validated improvement. A phase start is flushed before work begins, so a terminated stage remains identifiable.

If that baseline does not finish in budget, its status is `SEARCH_EXHAUSTED` or `INTERRUPTED`, never infeasible. The witness-seeded replacement has per-bank budgets of 45 minutes for constructive/local moves plus 15 minutes for compressed/neighborhood refinement, one worker, the frozen seed, and append-only progress receipts at least once per minute and on each independently validated improvement. No extension is authorized here.

Constraint-incidence must be measured before any decomposition or compression claim. Compression is legal only when every relevant constraint contribution is identical, the objective is additive over the equivalence class, and no residual constraint distinguishes members. Every emitted candidate is expanded and checked by the independent full validator.

## Search decision table

| Result | Interpretation |
|---|---|
| Valid non-identical bank passes policy separation | Construction gate passes; independent audit and a separate explicit model-contact authorization are still required. |
| Valid bank misses separation and a certified bound excludes the one-unit gate | The frozen objective/profile cannot meet this minimal policy-score criterion; this is not a global infeasibility claim. |
| Valid bank misses separation but the bound does not exclude it, or no bound is available | Construction result is inconclusive. |
| Witness audit fails | Stop before optimization; resolve the provenance or contract discrepancy. |
| Search budget ends | Retain the best audited candidate, label `SEARCH_EXHAUSTED`, and make no infeasibility/headroom inference. |

P* remains governed solely by its original source-support infeasibility conditions. Search difficulty, timeout, or poor incumbent quality cannot trigger it.

## Research boundary

This amendment authorizes no model feature extraction, training, benchmarking, or Phoenix data access. A passing construction receipt is not an LFM release condition by itself. The eventual bank manifests, full independent audit, status vector, and a separate explicit run manifest are required before model contact.
