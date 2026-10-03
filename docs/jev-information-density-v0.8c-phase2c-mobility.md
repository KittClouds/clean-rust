# Phase 2C support-mobility census

This is a narrow, metadata-only continuation of the frozen v0.8C Phase 2C contract. It follows the training-signature audit and precedes any cross-atom candidate search.

The census reads the sealed SQLite metadata index and four 100k ID manifests in read-only mode. It rechecks their frozen hashes, reconstructs atom identity from input digest, root, exact joint cell, topology tuple, and intervention family, and reports atom capacity/occupancy/slack. Outputs contain hashes and categorical metadata only; no model-visible text is emitted.

The census distinguishes three things:

1. Within-atom slack permits row replacement without changing the atom allocation.
2. Cell-only transfer potential ignores input, root, topology, and intervention coupling; it is a support diagnostic, not feasibility.
3. A same-core cross-atom one-unit swap preserves exact input/root identities and joint-cell counts. The census recomputes topology/intervention marginal TV against the appropriate frozen reference to identify individually profile-valid swap edges. Such an edge is a local witness only: competing edges are not jointly feasible by implication.

The Phase 2B candidate vectors are independently checked against R100/C100. Supervised-signature changes are reported as a possibility across a one-swap edge; they do not include the v0.5 capped invariance-pair context and are not the bank-level `D_train` measure.

No optimizer, model, tokenizer, feature cache, training materialization, or Phoenix source is accessed. A separate child search contract and freeze receipt are required before any cross-atom optimization. Model contact still requires separate explicit authorization even if search yields strong candidates.
