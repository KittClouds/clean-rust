# E012 task construction specification v1.2

**State:** paired construction repair frozen before candidate-check rerun. **Model contact is prohibited.**

This specification applies A12 to the 48-task E012 bank. See `bank-construction-plan-v1.4.md` and `amendments/bank-amendment-12.md`.

## Candidate checks and labels

Run every candidate against every case listed in that task's preregistered test suite. The check runner consumes the exact patch bytes embedded in the frozen precheck fixture. Candidate truth is the set of stable action IDs whose candidate patch passes every check in that task's locked suite. Candidate-content twins use identical test-case lists and test overlay hashes. The paired assignment finalizer uses rerun results by candidate role, not prior v1 action-ID labels.

Two v1 distractor patches change under A12: help-color's narrow-width candidate returns `Auto`, and map-order's redundant canonical sort drops one key. The rest of the selected patches and test predicates remain unchanged.

## Pair assignments

For `E_t`, `E_x`, and `E_r` twins, keep the action-ID-to-patch mapping and exact action-ID order identical. For `E_c.content` twins, keep the ID order fixed while changing the patch attached to IDs; request, pre-action output, context, and test suite remain identical. The 2×2 joint families hold all candidate content, IDs, context, and order constant across cells.

The solver chooses one mapping/order per paired block and checks the full family totals before writing labels. Valid and invalid candidate counts must balance exactly across action IDs and positions; the prefix family balances 2 valid and 2 invalid options per row. If there is no exact assignment, it fails before projection and requires another bank repair.

Each twin shares an opaque observer-facing `task_id` and `task_variant`. Internal truth records keep unique task IDs, and each frame receipt binds the shared presentation ID plus the complete frame digest and candidate sequence. Abstention examples keep distinct presentation IDs and have zero valid candidates.

## New outputs

The A12 scored bank is separate from the preserved v1 bank. New source, candidate-check, final-label, projection, audit, and model-run artifacts use the `scored-bank-a12` root. No v1 output is overwritten.
