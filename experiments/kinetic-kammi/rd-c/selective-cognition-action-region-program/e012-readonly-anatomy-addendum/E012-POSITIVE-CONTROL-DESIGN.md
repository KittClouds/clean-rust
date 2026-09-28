# E012 Fresh Positive-Control Design — Not Run

**Control ID:** `E012-PC-01`  
**Status:** `DESIGN_FROZEN_MODEL_CONTACT_NOT_AUTHORIZED`  
**Purpose:** test whether the E009/E010-style high-precision direct-action region is reproducible on fresh tasks from the same broad coding-workflow regime. This is a diagnostic control, not a threshold repair, E013 confirmation, or capability promotion.

## Bank design

- 32 new tasks, not reused from E009, E010, E011, or E012.
- Two fresh frozen Rust repository snapshots; four task families per repository; four independently authored tasks per family.
- Tasks have explicit, executable completion checks and producer-created candidate sequences. Keep the same four-option coding-workflow shape used in the prior switchboard runs, including realistic but legal distractors.
- Task authors select tasks from a fixed task-generation rule before observer contact. An independent engineer freezes valid-action sets from executable checks; the large observer is never used as label authority.
- Before model contact, record repository/task-family IDs, commit and fixture hashes, candidate patch identities and producer order, visible evidence, hidden completion checks, and an outcome-blind difficulty rubric. No task is replaced based on observer output.
- All task families are authored before model contact; repository names are new. This is intended to match the E009/E010 task *regime*, not their specific tasks, repositories, or outputs.

## Frozen runtime and observers

Use the exact E012-locked v5 identities and settings: small `minicpm5-2b-q8-local-v5`, large `ternary-bonsai-2-27b-ptq1-local-v5`, reasoning off, 1024 output-token cap, current prompt/schema/normalization, `850/150` thresholds, producer-order presentation contract, authority, receipts, and replay. Hash-check every component against the E012 identity record before any later authorized run. No tuning, prompt changes, new routing rule, or candidate reordering.

Run small-only, large-only, and the existing small-to-large-on-abstention hybrid on the same tasks and snapshots. Preserve raw outputs and completion receipts. Report per repository: small coverage, direct precision, large calls avoided, small-only completion, large-only completion, hybrid completion, and integrity counts; pool only as a descriptive supplement.

## Interpretation fixed before contact

- If the frozen small model again shows a nonzero high-precision region on this matched regime, E012's result is more consistent with bank shift and/or difficulty than with total instability of the earlier region. The difficulty rubric and outcome distribution may help distinguish those possibilities, but do not prove a mechanism.
- If it does not, the E009/E010 operating region is less stable than previously believed or the local runtime/model identity has drifted; first verify hashes and run conditions. Do not tune on this control.
- A successful control does not repair E012, validate the self-reported confidence contract as portable, or establish a general coding capability.
- This control is not used to select E013 features or thresholds.

## Stop boundary

This file specifies the control only. It has not been banked or run. The current work authorizes no model contact; E013 also remains unauthorized for contact. If later authorized, build and seal task fixtures, labels, analysis code, runtime hashes, and acceptance boundaries first, then run once.
