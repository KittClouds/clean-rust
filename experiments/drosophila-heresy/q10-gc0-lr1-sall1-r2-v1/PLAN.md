# Q10-GC0-LR1-SALL1: Complete Singleton Materialization

SALL1 exact-replays every one of the 3,696 singleton records in the frozen LR1 domain. It creates a new materialized library without changing LR1, PAL2, MAT1-R1, or any scientific seed.

Each source record is reconstructed from the frozen endpoint, group palette, canonical replacement, and exact LR1 oracle. The receipt stores the committed f32 state mapping, exact sequential-f32 readout, geometry, full row-level changes relative to the invalid LR1 search state, signed constraint vector/action, legality, distinctness, and source/reconstruction hashes.

The run is checkpointed by immutable 32-record chunks and per-case completion markers. Partial execution is not promoted to coverage. No pair expansion, global assembly, behavior, or scientific interpretation is performed.
