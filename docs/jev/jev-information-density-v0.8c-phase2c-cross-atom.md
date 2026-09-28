# Jev Information-Density v0.8C Phase 2C: Cross-Atom Selection

**Status:** prospective metadata-only phase frozen before training-signature audit. Phase 2B and every earlier contract/result remain immutable. No model contact, training, or Phoenix access is authorized.

## Why this phase exists

Phase 2B showed that row-ID turnover can occur without changing the learner's supervision. Its `CM100_atom` candidate replaced 19,031 rows yet preserved the witness atom-count vector; its `RM100_atom` candidate was the identity. Neither fact alone establishes a useful training-data intervention. Phase 2C first defines what the frozen v0.5 compatibility trainer actually consumes, then measures signature-multiset distance before attempting cross-atom allocation changes.

The selector's `model_input` digest is not treated as the complete training signature. The v0.5 adapter also places `query_semantic_id` in the actual state prompt, encodes candidates from the `name_definition` surface, aligns candidate strings with float32 gold targets, and applies source-typed losses plus a bounded directed invariance-pair term.

## Training signature

The canonical signature hashes the exact adapter state string, the candidate surface/target pairs, choice-versus-independent loss semantics, query view, open-world flag, probability source, derived Brier applicability and weight, and the v0.5 invariance-pair context actually used for a bank. Targets are represented as IEEE-754 float32 bits, matching the trainer tensor. Row, episode, root, curation, and generator bookkeeping are excluded unless consumed by the adapter.

Each bank projection must materialize exactly the listed `group_id` records. It must not expand a selected `episode_id` to unselected query groups or perturbation siblings from that episode. The frozen split is recomputed from the v0.8 family-bundle holdout implementation; training entropy quintiles are recomputed over eligible train groups with the pinned selector implementation.

Choice candidate pairs are canonicalized as aligned pairs for the primary loss signature because the compatibility head and its softmax loss are permutation-equivariant. A separate ordered signature reports the stricter presentation difference. Raw text is never copied into receipts; they contain hashes, counts, and distances only.

Equivalence is exact at the adapter-text/loss-input level. Distinct text hashes are conservatively counted as distinct even if tokenizer or backbone behavior could collapse them; this phase reads no tokenizer, model weights, feature cache, or model outputs and makes no feature-level equivalence claim.

The selected invariance pairs reproduce v0.5 exactly: training groups are sorted by `group_id`; groups are bucketed by invariant key in first-seen order; each bucket chooses the first base and first `surfaceinvariance` sibling; the trainer consumes the first 16 directed base-to-sibling pairs. The pair event hashes ordered endpoint state/candidate inputs and adapter kind; gold is excluded from this regularizer signature because the v0.5 pair loss does not consume it.

For banks of size `N=100,000`, the primary training distance is:

`D_train = 0.5/N * sum_t |count_A(t) - count_B(t)|`.

Model-contact eligibility requires `D_train >= 0.10`, a positive frozen-policy objective delta, and a full independent profile audit. This threshold is a predeclared treatment-strength gate, not a quality claim. The separate directed invariance-pair distance is reported so changes to the regularizer are visible.

## Search boundary

The existing R100/C100 witnesses remain the only initial profiles. Search order is RM100 from C100 first, then CM100 from R100 only if RM100 clears all readiness gates. Search changes atom allocations while preserving all inherited Phase 2 constraints and retains a full-profile-valid witness incumbent. A child search receipt must freeze the concrete deterministic neighborhood schedule after the metadata-only support-mobility census and before candidate optimization. Bounded-search exhaustion means `UNKNOWN_BOUNDED_SEARCH`, never infeasibility.

Even `FACTORIAL_READY` does not authorize training. A separate explicit model-contact authorization is required after both banks independently pass profile, model-signature, policy-separation, and treatment-strength checks.
