# Q10-CSC1-UPAIR1: fresh unscreened pair replay

UPAIR1 is the first pair replay after UVD0 domain construction and ALG1
prediction sealing. It consumes exactly the 17,712-pair deterministic sample
sealed by `q10-gc1-lr1-requal1-csc1-upair1-domain-v1` and the prospective
predictions sealed by ALG1. It does not expand, reorder, or outcome-filter the
domain.

For each sampled pair it reconstructs the common S state, applies both
disjoint canonical singleton maps to produce the committed AB state, and runs
the exact current sequential-f32 readout once for AB. Singleton A/B states and
their complete readout vectors are inherited from ALG1's fresh descriptor
materialization and are checked by hash. The output records the full AB
readout vector, committed mapping and hash, score, geometry, validity, and
interaction summaries.

UPAIR1 compares realized results with both ALG1 predictions:

* structural committed-state composition from the disjoint maps;
* the literal componentwise `f32(f32(A+B)-S)` arithmetic formula.

This is an engineering qualification only. It opens no global assembly, GC2,
adaptive-geometry comparison, behavior, or scientific seed.
