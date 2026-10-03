# REDLINE Phase 1 report: hot/cold candidate split

Change: `HotCandidate` (24 bytes: external_id/document/evidence/score/tier)
sorted in place; `ColdEvidence` sidecar in scratch indexed by hot record;
public `SearchHit` materialized only for the surviving prefix. V3 rerank
kernel mirrored onto hot records (`rerank_v3_hot`). Size budget asserted
in tests (<=32 B). No behavior change by construction.

## Gate evaluation

- Ordering anomaly REMOVED: 160-hit sorts 6.1-6.9us -> 2.3-2.4us on
  dense/high-frequency buckets.
- Serving totals: phrase 42.0 -> 40.0us (-5%, n.s.), transport 263.9 -> 268.9
  (+2%, n.s.), dense pending re-measure. No substantial serving improvement.
- Inspection before proceeding (per gate): sort cost was real but small;
  totals are dominated by the evidence loop + positions (Phase 2 target).
  Coherence stage unchanged at 26-52us. Proceeding to Phase 2 as ordered.

## Equivalence

- Freeze test green with zero expectation changes (bit-identical ids, order,
  score bits, tiers, evidence, pools, strengths).
- Full suite: 29 lib + 12 relevance + 1 freeze, all green.
- Warm allocations: still zero (`allocations_grew=false` everywhere);
  hot/cold buffers grow once inside existing scratch accounting.

## Cost

+~120 lines index.rs (kernel mirror + materialization), +1 test.
Public API untouched.
