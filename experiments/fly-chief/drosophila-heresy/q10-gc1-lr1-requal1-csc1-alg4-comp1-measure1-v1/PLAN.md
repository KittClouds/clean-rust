# Q10-ALG4-COMP1 measurement plan

This identity is the measurement successor to the sealed `q10-gc1-lr1-requal1-csc1-alg4-comp1-v1` preflight. It binds that preflight and the current R2/ALG1 lineage. The runner evaluates the shared order-4 canonical domain once, then emits separate COMP1A and COMP1B immutable receipts with the same domain identity. COMP1A applies the sealed A3 footprint exclusion; COMP1B applies group and coordinate compatibility only.

The default runner refuses measurement. A long run requires `--measure` and `Q10_ALLOW_LONG_MEASURE=1`. Every selected action prefix is resolved against frozen baseline bits and the candidate starts from frozen S. Target-row functional values are computed before geometry. Fast f64 geometry is used first with a 1e-12 boundary fallback; every geometry-valid candidate and every target-row hit receives full canonical replay. Non-hit parity samples are selected deterministically and capped at 4096 strata. Chunks are created with exclusive file creation and receipts bind chunk hashes.

This is engineering-only (`scientific_promotion=false`). No parent identity is modified.
