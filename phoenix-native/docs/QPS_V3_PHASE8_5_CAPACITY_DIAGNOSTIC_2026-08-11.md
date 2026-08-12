# QPS V3 Phase 8.5 Capacity Diagnostic — 2026-08-11

## Outcome

Phase 8.5 produced **Outcome B**: query-shape-conditioned linear capacity is not a sufficient explanation for the remaining Phase 8 failures. The next cut is one new primitive, not a tree and not more undirected labeling.

The diagnostic is non-promotable. The canonical Phase 7 model, failed Phase 8 receipt, frozen V2 retrieval substrate, and active engine state were not changed. **V2 remains active.**

Immutable receipt:

`C:\benchmarks\phoenix-qps-v3-20260804\review-checkpoints\865b45f8e732-6295b016f13f\phase8_5-shape-diagnostic-v1.json`

SHA-256:

`9a567989ff55fd63d27e2006c3478850ddc9337ed90dd32952cb5e344c76d91a`

## Feature-visibility proof

Across all 5,080 active training judgments:

| Feature | Maximum same-query pair delta | Status |
|---|---:|---|
| `query_group_count` | `0.0` | gradient-dead in the current linear ranker |
| `single_group_flag` | `0.0` | gradient-dead in the current linear ranker |
| `long_query_flag` | `0.0` | gradient-dead in the current linear ranker |
| `expansion_query_flag` | `1.0` | candidate-varying in 32 pairs; not actually query-only |

`matched_group_fraction` and `missing_group_absence` are numerically equivalent to floating-point precision. Their maximum observed absolute difference is `5.9604645e-8`.

Therefore the current 30-slot vector has an upper bound of 26 independent candidate-ordering coordinates before considering any further correlations.

## Tier cartography

The constitutional tiers are not the principal blocker:

| Evaluation | Failure queries | Blocking candidates | Same-tier | Cross-tier |
|---|---:|---:|---:|---:|
| LongMemEval | 78 | 272 | 272 | 0 |
| Independent graded MRR | 324 | 5,398 | 5,331 | 67 |

The independent graded suite also contains 59,328 grade inversions: 55,704 same-tier and 3,624 cross-tier. Most residual ranking errors are legally repairable within the constitutional ordering.

## Shape-conditioned diagnostic

The challenger learned signed slope modulations from the three proven query constants. Effective candidate weights were clamped non-negative, so monotonicity remained intact. Query-only coordinates were excluded from the per-candidate dot product. Development selected 8 epochs, learning rate `0.01`, and L2 `0.0001` from 16 deterministic candidates.

| Metric | Linear V3 | Shape-conditioned diagnostic | Gate |
|---|---:|---:|---:|
| Development pairwise | 0.769870 | 0.773428 | diagnostic only |
| Blind pairwise | 0.785377 | 0.790094 | ≥ 0.80 |
| Held-out top-1 improvement | +4.184 points | +5.021 points | ≥ +2 points |
| LongMemEval hit@10 | 0.984 | 0.982 | ≥ 0.984 |
| LongMemEval MRR | 0.898899 | 0.895440 | ≥ 0.910 |
| Independent stretch MRR | 0.543202 | 0.546078 | ≥ 0.920 |
| Graded NDCG@10 delta | -0.014278 | -0.013667 | ≥ +0.020 |
| Worst-shape MRR regression | 0.016345 | 0.015850 | ≤ 0.005 |
| Mixed suite | 1.000 | 1.000 | remain 1.000 |

The challenger made small blind and graded gains but regressed LongMemEval hit@10 and MRR. Conditional slopes do not supply the missing distinction.

## Measured primitive gap

Every baseline blind failure in the three largest relevant positional classes had both existing span features fixed at zero:

| Failure class | Blind failures | Both complete-span and ordered-span qualities zero |
|---|---:|---:|
| Phrase/order failure | 48 | 48 |
| Partial-match saturation | 26 | 26 |
| Document/conversation confusion | 30 | 30 |
| Wrong-concept proximity | 21 | 21 |
| Common-term dominance | 17 | 17 |
| Length-prior failure | 10 | 10 |
| Scattered terms | 5 | 5 |

The implementation computes a minimum covering span for the groups matched in a field, even for partial coverage, but `RankEvidenceV3` discards it unless all query groups are complete. This is the missing-evidence seam.

## Authorized next primitive

Add one bounded primitive: **matched-group locality**.

For `m` distinct matched groups in a field and their minimum covering span `s`:

```text
matched_group_locality = 0                                  when m < 2
matched_group_locality = 1 / (1 + max(0, s - m))           otherwise
```

Take the best locality across fields. It is finite, normalized, deterministic, monotonic positive evidence, computed from the existing allocation-free position walk, and meaningful for partial as well as complete coverage.

Use the redundant `missing_group_absence` slot to keep the serving vector at 30 floats. This must be a new evidence-schema identity/version; old artifacts must never be silently reinterpreted.

## Required migration sequence

1. Add `matched_group_locality` to field and primitive coherence evidence.
2. Replace only the redundant slot and bump the evidence schema identity/version.
3. Regenerate frozen candidate evidence and the independent graded suite without changing candidate pools or tiers.
4. Rematerialize reviewed ledger rows by keyed query/document pair identity, preserving each review through explicit supersession lineage.
5. Re-run Phase 4 → 5 → 6 → 7 → 8.
6. Revisit a tree only after the new linear residual proves repeatable interactions and the formal Phase 11 prerequisites are met.
