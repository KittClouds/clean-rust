# Jev v0.8D common-support capacity gate

## Purpose and boundary

v0.8C is sealed as a treatment-strength failure for its bounded historical-profile search. v0.8D is a new metadata-only experiment. It does not modify the v0.8/v0.8C banks, contracts, receipts, or conclusions; it does not access models, tokenizers, feature caches, Phoenix, or training runtimes.

The initial v0.8D stage asks whether a broad common-support profile can support substantial learner-visible movement before random and curated policies are selected. It uses the sealed training-signature index and generator metadata only.

## Common support and P*

The source support is the v0.8 eligible training universe, excluding the already-held-out family bundles. A profile stratum is the exact six-field joint cell (world, family bundle, query view, candidate-cardinality bin, training entropy quintile, entropy band), crossed with the sorted topology tuple and intervention family. Groups in strata with fewer than four eligible members are outside S*. All major source categories must remain represented after this admission rule.

Topology is extracted from the `structural_coverage` array nested inside `coverage_features_json`; missing topology or required family metadata is an input-integrity error, not an empty topology. The v0.8c SQLite signature index is training-only (416,672 rows); the held-out 83,328 IDs are held in a separate manifest and must be disjoint. The run freeze also pins the v0.8 zero-collision preselection/source-overlap audits, input-to-target consistency report, v0.8c signature-reconstruction audit, and firewall registry hashes. Thus `held_out=0` is not treated as the sole evidence of training eligibility.

For each admitted stratum with capacity N, P* assigns an integer quota q with `1 <= q <= floor(N/4)` and `sum(q)=100,000`. Quotas are allocated proportionally to capacity using deterministic capped largest-remainder water filling. This makes the profile interior by construction: every selected stratum has at least four quota-sized realizations in S*.

P* fixes exact per-stratum counts. It also records the anchor bank's unique model-input/root counts and occurrence histograms. A second bank matches those with at most 2% relative error and 0.02 total-variation distance. Extra family-axis, task-kind, candidate-count, open-world, and probability-source marginals must remain within 0.02 TV. No metric depends on model outcomes.

## Capacity witnesses

For each of 32 prospectively fixed seeds, groups are hash-ranked independently within each P* stratum. The first q form witness A and the next q form witness B, so they are disjoint within every stratum. Both banks must retain all required core and sufficiently populated family categories. The pair is checked against all profile constraints, then exact training-signature distance is recomputed with the frozen capped invariance-pair context (maximum 16 directed pairs per bank).

The capacity gate passes only if a pair has `D_train >= 0.20`. The best passing pair among the 32 declared attempts is a witnessed lower bound on attainable treatment capacity, not a global maximum. Witness manifests are not training banks. R100*/C100* are a later, separately frozen policy-construction stage and must independently pass profile and `D_train >= 0.10` gates before any model contact.

## Failure semantics

- `SUPPORT_CAPACITY_FAIL`: fourfold support cannot realize 100k groups.
- `CORE_COVERAGE_FAIL`: admission drops a required broad category.
- `PROFILE_WITNESS_FAIL`: no tested pair matches P*'s metadata profile.
- `TREATMENT_CAPACITY_UNPROVEN`: no tested profile-matched pair reaches exact D_train 0.20. This is not an infeasibility proof.
- `CAPACITY_WITNESS_PASS`: a reproducible profile-matched pair reaches the gate; this authorizes only a new policy-arm freeze, not model contact.

Expected feasibility failures are written as sealed reports and integrity receipts. Source-hash, lineage, or parser-integrity failures abort before any scientific output is sealed.

All outputs are external ID/hash/aggregate-metadata artifacts. Raw text is never emitted. The support census, P* profile, witness report, optional witness ID manifests, and final integrity receipt are separate outputs. Witness manifests are never promoted to policy arms.
