# E012 Positive-Control Action-ID Schema Amendment v1.3.2

**Amends:** only the identifier encoding in `E012-POSITIVE-CONTROL-RESERVE-POLICY-AMENDMENT-v1.3.1.md`.  
**State:** `PREAUTHORING_SCHEMA_CORRECTION_SEALED; BANK_NOT_BUILT`  
**Bank owner:** user

The v1.3.1 reserve policy described candidate IDs as 16-byte hex strings. That conflicts with the frozen E009 v5 output schema, whose `action_choice` accepts only integers from 0 through 65,535 or `null`. Correct the identifier encoding before assigning any task or candidate IDs. All other v1.3/v1.3.1 rules remain unchanged.

## Locked ID encoding and draw order

- Task IDs are 128-bit opaque lowercase hexadecimal strings generated with `Generator(PCG64(opaque_ids_child)).bytes(16).hex()`. They must be unique across the 80 core/reserve task records; retry a duplicate by consuming the next draw.
- Candidate/action IDs are unsigned 16-bit integers in `[0, 65535]`, matching `observer-output.v2.json`. They must be unique among the four candidates within each task. A duplicate within that task consumes the next integer draw; uniqueness across different tasks is not required.
- Construct the generator from the fifth child returned by the single frozen `SeedSequence(13064).spawn(5)` call. Use the NumPy version recorded in the environment lock. Do not seed a second RNG or mix in task content.
- Draw core IDs first in canonical cell order (repository index ascending; cohort order `PC`, then `difficulty`; family index ascending), then task slot ascending. For each task draw its task ID, then four candidate/action IDs in producer-ordinal order. After all 64 core tasks, draw reserve IDs in the same canonical cell order and reserve-rank order; for each reserve draw its task ID, then its four candidate/action IDs in producer-ordinal order.
- Draw order is independent of candidate role and validity. The ID stream is not reseeded per cell. Record the complete task/action ID map and its hash before label access; preserve the stream version and collision retries in the receipt.

This corrects representation only. It does not alter task/candidate order, the v1.3.1 reserve mapping, task counts, rubric requirements, or authority semantics. No bank is built and no model is contacted by this amendment.
