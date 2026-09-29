# BANK-v1 LFM2.5-230M Capability Atlas — Rung 0

**Status:** LOCKED ENGINEERING BASELINE
**Lock date:** 2026-09-29
**Scope:** the completed ten-surface BANK-v1 sweep and its cached-vector graph-capability appendix.

Rung 0 is the reference atlas for later specialization work. It records capability allocation across a small fixed surface set; it does not identify one universal best embedding.

## Carry-forward surface set

- middle_plus_final — midpoint + final token; primary decision/router reference.
- final_plus_mean — final token + full token mean; complementary decision/abstention reference.
- layer_m4_final — layer minus four, final token; intermediate-layer NLI reference.
- full_mean — full token mean; ABSTAIN-specialist reference.
- first_token — retained only as a **dead negative control**. Its near-constant vectors and weak task behavior make its perfect renderer invariance uninformative.

The other sweep surfaces remain archived in the original report. Do not launch another broad surface sweep unless a later rung names a specific capability hypothesis and the additional surface before scoring.

## Frozen task definitions

The surface atlas task contract is bound to the exact source enums in bank-v1-surface-extremes-20260929/common.py:

- Decision: ACT, ASK, ABSTAIN.
- Action type: the 14 BANK action labels.
- Abstention reason: the 11 BANK reason labels.
- NLI: ENTAILED, CONTRADICTED, UNKNOWN.
- Typed set outputs: entity types, relation predicates, transition/state predicates, and evidence predicates.

The graph appendix has four fixed world-level targets: entity-type presence, initial relation-predicate presence, initial ACTIVE/INACTIVE state-value presence, and shortest undirected CONNECTED path from an object's unique initial AT location to its AT goal, bucketed as already-at-goal, one hop, multi-hop, or disconnected.

Graph readouts consume one vector for an entire rendered world. Rung 0 makes no node classification, edge prediction, neighbor lookup, or GNN-equivalence claim.

## Gate and verification

The reproducibility gate is **PASS_HASH_BOUND_CACHED_SCORES_AND_FIXED_TASKS**. The machine-readable lock binds:

- BANK-v1 release identity, rowmap, model revision and extracted primitive hashes;
- surface prediction seal and scored result;
- graph appendix results and readout weights;
- source/task-definition files and graph-target tests.

Run the quick receipt/source check from the repository root:

    python experiments/bank-v1-rung0-atlas-20260929/verify_rung0_lock.py

To hash every selected cached primitive (large files; several GB total):

    python experiments/bank-v1-rung0-atlas-20260929/verify_rung0_lock.py --verify-primitives

The lock verifies the exact cached baseline and its task contract. It is not a fresh rerun, a natural-language qualification, a retrieval result, or a claim that whole-row vectors encode node-local graph structure. The full run commands and limits remain in the linked surface-sweep and graph-appendix READMEs.

## Frozen receipts

See rung0-lock.json for exact file paths, hashes, model/BANK identities, task labels, and the source revision. A detached SHA-256 receipt is stored alongside it in rung0-lock.sha256.