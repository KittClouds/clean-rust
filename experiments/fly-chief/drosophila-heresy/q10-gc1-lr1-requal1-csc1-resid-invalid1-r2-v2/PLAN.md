# Q10-RESID-INVALID1-R2-V2

## Purpose

Freshly repeat the fixed 57-row, order-1/2/3 invalid-frontier audit after reconciliation localized the prior false-positive mechanism. This identity tests whether exact target row values occur anywhere in the frozen candidate domain, including geometry-invalid states.

This is a fresh identity. The earlier contaminated rerun and the unexecuted R2-v1 preparation are immutable lineage artifacts, not inputs to the measured result.

## Frozen scope

- Context: `seed9731-R-tau4.json`, set 3.
- Residual rows: the 57 rows already bound by RESID-SUPPORT1.
- Candidate domain and ordering: identical to RESID-INVALID1-RERUN1, with the expected domain identity hash bound before scanning.
- Candidate function: affected-row sequential-f32 outputs, computed before geometry classification.
- Geometry: existing fast evaluator with the fixed `1e-12` boundary fallback; no geometry prefilter.
- Bounded-memory policy: full replay results are discarded after each verification; at most 4,096 deterministic parity strata may be retained. Exceeding that ceiling fails closed before promotion.

## Correct action semantics

Every action prefix is resolved against the frozen baseline weight bits, exactly as in `ALG1.apply_mapping`. The candidate starts from the frozen invalid state `S`; the canonical action mapping overwrites its coordinates with baseline-relative committed values. No prefix is interpreted relative to the current candidate or invalid state.

The action groups must be coordinate-disjoint. Canonical candidate maps reject duplicate coordinate assignments. A premeasurement regression test reproduces the row-36 pair `[15,409]` and row-695 triple `[292,357,428]`: the legacy evaluator returns the previously mistaken target bits, while the corrected row-local evaluator equals full canonical replay.

## Verification gates

1. Run the semantic regression test before scanning.
2. Freeze parent, implementation, target-row, domain-count, and ordered-domain hashes in `CONTRACT.json` and `PREEXECUTION.json`.
3. Full-replay every row-local target-equality candidate. Report only full-replay-confirmed witnesses, retaining the first witness per row and geometry class.
4. Full-replay the first deterministic candidate in each observed stratum defined by order, geometry validity, target distance (`<=8` or `>8` ULP), support-class signature, and maximum prefix-scale bucket. Require bitwise equality on every affected row.
5. Require exact domain coverage/hash, unchanged parents, and the declared write allowlist.
6. Require the canonical mapping property test and the two contaminated-witness regression fixtures to pass before preexecution sealing.

## Evidence boundary

This is engineering-only. It does not open order 4, GC2, AG1, behavior, scientific promotion, or biological interpretation. The contaminated predecessor remains non-promotable; its two witnesses are bound only as regression fixtures.
