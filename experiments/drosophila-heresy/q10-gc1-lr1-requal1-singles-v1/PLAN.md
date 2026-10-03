# REQUAL1-SINGLES: fresh current-lineage singleton materialization

This engineering-only campaign is authorized by the sealed
`q10-gc1-lr1-requal1-domain-r2-v1` domain and
`q10-gc1-lr1-requal1-smoke-v1` smoke gate. It replays exactly the 3,696
nonzero singleton candidates from the current closure: eight contexts, 462
raw groups, and eight nonzero candidates per group.

Each candidate is reconstructed from its canonical coordinate-to-prefix map,
committed to f32 bytes, replayed with the exact learner-order accumulator, and
audited for score, geometry, bounds, and byte hashes. One immutable JSONL shard
is written per context. ZERO is a validated control in the domain closure but
is not part of this intervention domain.

No pair replay, global assembly, behavioral probe, scientific seed, or
promotion is permitted. Interruption or any shard mismatch fails closed.
