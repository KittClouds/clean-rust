# Jev Information-Density v0.8C — Matched-Bank Optimization

**Status:** phase-specific optimizer sealed before model execution. v0.8B, the v0.8C Phase 1 contract, and all reference banks remain immutable. This phase is metadata-only; it authorizes no model access, feature extraction, training, or Phoenix access.

## Phase 1 result and interpretation

The Phase 1 target-profile feasibility question is already answered for both profiles by direct identity witnesses:

- R100 contains 100,000 eligible groups and exactly reproduces its own target profile.
- C100 contains 100,000 eligible groups and exactly reproduces its own target profile.
- Exact-cell mismatch is zero; input/root unique-count relative error and input/root multiplicity TV are zero; topology and intervention TV are zero.

Therefore the profile-feasibility result is `FEASIBLE` for R100 and C100. CP-SAT was not needed to establish non-emptiness. This is **not** a claim that CM100 or RM100 has been constructed, and it is not evidence that curation helps. The identity witness is a feasibility proof for the profile only.

The fallback P* is not triggered: neither profile is proven infeasible. No hidden no-overlap restriction is added. Overlap between each newly selected bank and its reference profile is measured and reported, not prohibited.

## Frozen Phase 2 construction

The two new manifests are selected from the same 416,672-group eligible universe:

- CM100 targets R100's exact joint-cell counts and maximizes the sum of global frozen-v0.8 curated priority ranks.
- RM100 targets C100's exact joint-cell counts and maximizes the sum of seeded SHA-256 random-priority ranks.

The curation ordering reproduces the frozen v0.8 static rarity-weighted coverage score, followed by the v0.8B CM100 seed digest and unique group ID. Random ordering uses the v0.8B RM100 seed digest and unique group ID. Priority ranks are integers, highest-priority group first; objective is the sum of selected ranks. No model output, feature embedding, observable text, or protected evaluation result is used.

Both optimizations use the exact joint-cell quotas and the v0.8C bounded constraints: unique-input and unique-root counts within outward-rounded ±2%; input/root occurrence-histogram TV ≤0.02; topology and intervention marginal TV ≤0.02. There is no exact root histogram or exact per-cell input histogram. Solver optimality is not required: an `OPTIMAL` or `FEASIBLE` incumbent may be emitted only after the independent bank audit passes. Status, objective value, best bound, and optimality gap are retained.

## Stop rules

- A solver infeasibility result contradicting the direct identity witness is treated as a model defect; stop and diagnose, do not invoke P*.
- `UNKNOWN`, timeout without an audited incumbent, invalid model, hash mismatch, or independent-audit failure emits no bank manifest.
- If either bank lacks a passing manifest, no LFM/model contact is authorized.
- Passing manifests remain ID-only external artifacts. Training banks are not materialized here.

## Receipts

The repository contract and solver implementation are in `experiments/jev-information-density-v08c/`. Run outputs belong only under `D:\\codex-runs\\jev-information-density-v08c\\`. The optimizer records hashes for the Phase 1 receipt, source inputs, contracts, and code; independently rechecks all frozen constraints; and records overlap with the matching reference bank.
