# Q10-SR2 result

Status: `Q10_SR2_STAGE2A_INVALID`

The producer completed all 1,024 Stage 1A engineering events for fresh seed
`9511`. It audited 1,010 parent-eligible mismatched events and 14
parent-ineligible events. Every eligible event was `CAPACITY_PARTIAL`, so the
capacity gate entered zero discrete searches; the producer wrote no repair
claim and no scientific output.

The independent standard-library reviewer failed closed on the first replay.
The first differing output was an empty authoritative row: the Rust
production `Iterator::sum::<f32>()` committed `-0.0` (`0x80000000`), while the
reviewer initialized its emulation with `+0.0` (`0x00000000`). This is a
reviewer arithmetic defect. The Stage 1A identity is invalid and seed `9511`
is spent; the reviewer source may not be patched and reused under this
identity. The complete producer directory is preserved for audit.

The corrected empty-row rule requires a new protocol identity and fresh
engineering seeds. Stage 1B seeds `9512..9515` remain unopened. Scientific
seeds, behavior, and DH-08B were not authorized or evaluated.
