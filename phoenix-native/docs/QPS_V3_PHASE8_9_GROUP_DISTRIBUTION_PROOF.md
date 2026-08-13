# QPS V3 Phase 8.9 Group-Distribution Proof

Date: 2026-08-13

Status: diagnostic complete; no schema migration; no retraining; **V2 active**.

## Decision

`GROUP_DISTRIBUTION_HYPOTHESIS_REJECTED`

Generic lower-tail and balance summaries of the selected per-query-group
lexical contribution do not explain the remaining Phase 8 errors. The best of
the tested primitives, weakest matched-group strength, is oriented correctly
on only 48.9% of distinguishable development residuals. It is worse on the 28
monotonic-impossible errors and fails both external transfer cohorts.

QPS must not migrate any of these primitives into `RankEvidenceV3`. The next
evidence hypothesis is source/temporal alignment for conversational and
multi-session retrieval, not another group-distribution scalar.

## Frozen experiment

The experiment reads only the 194 development pairs that the canonical Phase
7 model ranks incorrectly. Blind labels are not read during primitive design.
The independent graded suite and the already-used LongMemEval release cohort
are transfer vetoes, not fresh architecture-search holdouts.

The raw group strength for group `j` is reconstructed from evidence already
selected inside QPS:

```text
raw_j = selected_expansion_quality
        * sum_field_bm25f_impact(selected_posting)

s_j = raw_j / (1 + raw_j)
```

Unmatched groups remain explicit zero. They are excluded from matched-tail
statistics because canonical coverage already encodes group absence. No
learned function is involved.

The tested order was frozen before execution:

1. weakest matched-group strength;
2. Q25 using `floor(0.25 * (n - 1))` over sorted matched strengths;
3. Q33 using `floor((n - 1) / 3)`;
4. normalized effective group count
   `1 / (n * sum((s_j / sum(s))^2))`.

Evaluation stops at the first primitive that clears the preregistered
development and transfer gates. None cleared them, so all four were evaluated.

## Integrity proof

- Phase 4, Phase 6, and Phase 3 inputs are verified.
- The regenerated independent ledger is byte-identical to v9:
  `a28f906d13446e4c5c0b627bc6400e5112a48d413105d229fe053fefc92b35d8`.
- The regenerated graded suite is byte-identical to v9:
  `d9be32daca38e0b4cefd2680447ebeb5e8e6f5021c8f789917e468f9704af02b`.
- The regenerated review packet is byte-identical to v9:
  `8a99383fbbffc6a6d1c9252bf4a27a2781748c82565c471b46a927ca59173320`.
- Release capture matches Phase 3 candidate identity/order, V2 score bits,
  canonical evidence, and tier for every mixed-suite and LongMemEval row.
- Every strength is finite and in `[0, 1]`; profile lengths equal canonical
  query-group counts.
- The projected cohort reproduces Phase 8.8 exactly: 194 errors, including 28
  monotonic-impossible errors.
- `RankEvidenceV3`, the ledger, the canonical model, tiers, and serving order
  remain unchanged.

## Result

Orientation accuracy is `preferred_higher / distinguishable`.

| Primitive | Development | Impossible subset | Independent transfer | LongMemEval transfer |
|---|---:|---:|---:|---:|
| Weakest | 91/186 = 0.489 | 4/26 = 0.154 | 85/277 = 0.307 | 38/77 = 0.494 |
| Q25 | 70/186 = 0.376 | 4/26 = 0.154 | 96/281 = 0.342 | 39/78 = 0.500 |
| Q33 | 70/185 = 0.378 | 6/26 = 0.231 | 89/278 = 0.320 | 27/78 = 0.346 |
| Balance | 73/187 = 0.390 | 5/25 = 0.200 | 131/309 = 0.424 | 25/78 = 0.321 |

The migration threshold was 0.70 on at least 20 distinguishable development
pairs, with support in at least two development sources and no rejection by
the external cohorts. Every primitive fails the primary 0.70 gate. Weakest is
the only primitive near chance overall; the other three are consistently
oriented in the wrong direction.

### Target classes under weakest strength

| Class | Correct / distinguishable | Accuracy |
|---|---:|---:|
| Partial-match saturation | 16/33 | 0.485 |
| Phrase/order failure | 24/45 | 0.533 |
| Common-term dominance | 11/21 | 0.524 |
| Length-prior failure | 3/5 | 0.600 |
| Wrong-concept proximity | 9/31 | 0.290 |
| Document/conversation confusion | 6/16 | 0.375 |

Weakest strength reaches only 0.514 on the `g8+` development bucket and 0.387
on LoCoMo/multi-session rows. On LongMemEval it reaches 0.478 for the
multi-session shape and 0.560 for temporal reasoning. The proposed effect is
therefore neither strong nor cohort-independent.

Balance is also substantially redundant with existing evidence: its residual
pair delta has absolute correlation `0.762` with
`mean_matched_term_rarity`. Adding it would expand the schema without opening
a useful new direction.

## Artifacts

- Proof receipt:
  `C:\benchmarks\phoenix-qps-v3-20260804\phase8_9-group-distribution-proof-v1\phase8_9-group-distribution-proof-v3-final.json`
  (`009385e73df06b5709808cc1ba555ff47f0ca9a9b478ac8e78dbf418fc51dd08`)
- Independent raw sidecar:
  `C:\benchmarks\phoenix-qps-v3-20260804\phase8_9-group-distribution-proof-v1\independent-group-distribution-sidecar-v1.json`
  (`fc66b97c2f2138ca17a5adfa991b01f9606b96d01b59a7f1d2b9c37c0a20707a`)
- Release raw sidecar:
  `C:\benchmarks\phoenix-qps-v3-20260804\phase8_9-group-distribution-proof-v1\release-group-distribution-sidecar-v1.json`
  (`41f380781e6debaabd37d688d75aab6fcf6d252d0f0480091db8ed467c7ea112`)

The proof receipt contains every residual identity and both raw group vectors,
the exact cohort/primitive definitions, per-class/source/shape tables,
transfer tables, redundancy measurements, hashes, gates, and the final
conclusion. A second create-only run from the same final binary produced the
same 125,868 bytes and SHA-256, proving deterministic reproduction.

## Next falsification target

Move one layer deeper to source/temporal alignment, particularly:

- LoCoMo and other multi-session retrieval;
- temporal-reasoning and knowledge-update query shapes;
- document-versus-conversation confusion;
- wrong-concept proximity where lexical group strength is actively
  anti-predictive.

That next preflight should again expose raw existing evidence first and test
pair direction before changing the canonical schema. No additional objective
tuning or generic group-distribution scalar is justified by Phase 8.9.
