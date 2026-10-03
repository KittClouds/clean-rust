# Q10-FRONT-DIV1-R1

Read-only mismatch-mask topology audit for the `R tau4 set3` order-3 valid frontier.

The near-frontier band is frozen before analysis as `mismatch_count <= 128`, because
the sealed order-frontier comparison recorded a best mismatch count of 123. This
identity performs no replay and does not alter any parent artifact.

It measures exact mismatch-mask diversity, residual-row frequencies, residual
co-error, mask Hamming distance, and connected components under one-bit mask
adjacency. Row/mask counts, residual co-error, and one-bit adjacency are exact.
If the unique-mask pair domain is too large for a quadratic pass, Hamming
summary statistics use a fixed deterministic index-pair sample declared by the
script; this is a descriptive distance audit, not a filter or a stopping rule.
The order-3 semantic materialization is the authoritative compact source for
masks and changed-from-reference bits.

This is engineering evidence only. It does not open order 4, GC2, AG1, behavior,
or scientific promotion.
