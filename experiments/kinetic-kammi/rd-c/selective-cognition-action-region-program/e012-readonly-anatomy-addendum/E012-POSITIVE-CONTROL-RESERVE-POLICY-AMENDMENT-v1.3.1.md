# E012 Positive-Control Bank Reserve Policy Amendment v1.3.1

**Amends:** `E012-POSITIVE-CONTROL-BANK-CONSTRUCTION-SPEC-v1.3.md` and its lock only for reserve handling.  
**State:** `PREAUTHORING_AMENDMENT_SEALED; BANK_NOT_BUILT`  
**Bank owner:** user

The sealed v1.3 specification permits use of a “predeclared outcome-blind reserve” but does not freeze the reserve count, ordering, identifiers, consumption trigger, or exhaustion behavior. This amendment closes that construction seam before authoring begins. It does not change the 64-task layout, rubric targets, task labels, analysis rules, positive-control contact authorization, or E013-D/C contact status. The v1.3 files remain byte-for-byte unchanged.

## Locked reserve policy

- Create exactly **one reserve task per repository × cohort × family cell**: 16 reserves total. A reserve is additional construction material, not an additional member of the 64-task bank.
- In each cell, the reserve is preassigned to replace only primary task slot `0`. This target is fixed for every cell before task authoring; no curator chooses a target after seeing a rejection.
- Assign reserve rank `0` in each cell. Traverse cells in repository index ascending, cohort order `PC` then `difficulty`, and family index ascending. Use `Generator(PCG64(opaque_ids_child))`; draw 16 bytes per ID and render as lowercase hex. Draw core IDs first in cell order, then task slot ascending, task ID followed by candidate IDs in producer-ordinal order. Draw reserve IDs afterward in cell/rank order, reserve task ID followed by candidate IDs in producer-ordinal order. On collision, consume the next 16-byte draw. Record the exact NumPy version and complete ID map before label access. IDs must not encode reserve status, cell, candidate role, slot, or validity.
- Before any labels are opened, the reserve must match its target slot's repository/cohort/family cell, empty-valid status, six-dimension independent-rater rubric vector, and preassigned valid-anchor ordinal when the target is nonempty. Thus substitution preserves the locked empty quota, difficulty marginals, and ordinal totals.
- Validate each reserve through the full v1.3 pipeline, including execution-only labels, leakage review, two-clean-worktree determinism, and the T1 construction-time ceiling. A reserve is eligible only after it passes every check.
- Consume it only if its mapped primary slot `0` fails a task-local check before observer contact: reference/candidate execution, determinism, leakage, or the per-task T1 runtime ceiling. Replace that slot with its already-validated reserve; do not alter any other task, ordinal, label, or analysis rule. A bank-level quota failure is not replaceable because the matched reserve preserves the original rubric vector.
- A failure in primary slot `1`, `2`, or `3` fails bank construction. A failed reserve or a second rejection in a cell after its reserve is consumed also fails bank construction. Do not borrow from another cell, create a new reserve, or choose among replacements after inspecting observer outputs. Preserve every failure artifact and reason.
- Seal an unused reserve as `UNUSED_RESERVE` in the construction archive. Exclude it from the 64-task run manifest and all task-level run analyses. If consumed, the accepted reserve occupies the original slot and the rejected primary remains in the failure ledger.

## Authorization boundary

This is a construction-only amendment. It does not build any task or bank and does not authorize or perform model contact. The user remains the bank builder. The already-authorized positive-control run can proceed only after the user-built 64-task bank, reserve disposition, and synthetic dry run are sealed. E013-D/C contact remains unauthorized.
