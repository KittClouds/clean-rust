# REQUAL1-SREPLACE-PAIRS: exact fresh S-replacement pair replay

This engineering-only identity replays the sealed geometry-screened pair
domain with the real learner-order sequential f32 readout. Both replacements
are applied simultaneously to the same fresh invalid `S` state. The runner
independently reconstructs and records `S_A`, `S_B`, and `S_AB`; it never
forms `S_AB` by mutating `S_A`.

Every context is written as an immutable shard and the final receipt is
atomic. Exact target parity, valid improvement over fresh `V`, pair validity,
and pair interaction are engineering diagnostics only. No behavior or
scientific seed is opened.
