# E012 bank amendment A10 — construct expected masked frames from baseline

**State:** audit-only repair frozen before rerun. **Model contact remains prohibited.**

Pre-contact audit attempt 02 compared an expected masked frame to the full frame because it applied absence transforms to the actual frame, which was already masked. A direct diff confirmed that `leave_out_E_t` differed from the full frame only in `task_prompt`. No projected artifact changed.

Audit v1.3 starts with the full frame, applies the preregistered absence transforms to that expected copy, and compares the result with the projected frame. It retains A09's corrected reverse-coordinate count predicate and all other checks. The two failed audit attempts and their input hashes remain preserved.
