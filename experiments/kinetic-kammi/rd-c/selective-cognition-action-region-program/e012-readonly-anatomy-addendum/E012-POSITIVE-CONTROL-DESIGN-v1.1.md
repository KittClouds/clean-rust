# E012 Fresh Positive-Control Design v1.1 — Not Run

**Control ID:** `E012-PC-01-v1.1`  
**Status:** `DESIGN_ONLY_MODEL_CONTACT_NOT_AUTHORIZED`  
**Purpose:** check whether a fresh E009/E010-style action region recurs, while adding a difficulty-matched contrast that can help distinguish a regime shift from task difficulty. This remains a diagnostic; it cannot repair E012 or select E013 features.

## Bank design

Use 64 new tasks on two fresh frozen Rust repository snapshots. No E009, E010, E011, or E012 task instance is reused. Each repository contributes four task families to each of two predeclared task-regime cohorts, with four tasks per family:

| Cohort | Design | Tasks |
|---|---|---:|
| E009/E010-regime positive control | Clear, short local-commit coding tasks with explicit requested behavior and a useful offered candidate | 32 |
| E012-difficulty-matched contrast | Fresh local-commit tasks matched to the E012 construction profile on outcome-blind difficulty dimensions | 32 |

The difficulty match is specified before model contact using only construction metadata and a blinded rubric: number of operative constraints, ambiguity of task wording, similarity of plausible candidate patches, evidence conflict, reasoning depth, and distractor plausibility. Match the cohort distribution across fixed low/medium/high bins, repository, and candidate count. Do not use E012 model outputs, accepted/wrong labels, or post-outcome performance to select, match, or replace tasks. The task banks remain fresh; matching a construction profile does not reuse E012 answers.

Each task has frozen repository commit/snapshot hashes, candidate patch identities and producer order, and executable completion checks. An independent label writer freezes valid-action sets. No task is replaced because an observer abstains or errs. Per-repository reporting is mandatory.

## Frozen runtime

Use the exact E012-locked v5 small and large bundles, prompt, output schema, normalization, 850/150 thresholds, reasoning mode, output cap, producer-order presentation receipt, authority, and replay policy. Hash-check these against the recorded E012 identities before any later separately authorized run. Run small-only, large-only, and the existing small-to-large-on-abstention hybrid on the same tasks. No tuning, prompt changes, new trust signals, or action reordering.

Report by repository and cohort: small coverage, direct precision, false accepted actions, large calls avoided, small-only/large-only/hybrid completion, latency, tokens, and integrity counts. Pooled figures are descriptive only.

## Interpretation fixed before contact

- If E009/E010-regime tasks recover a high-precision small region while the difficulty-matched cohort does not, task difficulty is a plausible contributor to E012's failure. This does not prove difficulty is the cause.
- If both cohorts recover, E012 may reflect a bank-specific shift or finite-sample variation; the control does not separate those explanations by itself.
- If neither recovers, the earlier region is less stable than believed or a runtime/model identity drift exists; first verify hashes and execution conditions.
- This is a recurrence/difficulty diagnostic, not a trust-signal selection set, E013-D data, or confirmation bank. No capability claim is promoted from 64 tasks.

## Stop boundary

Design only. No tasks were built/scored and no models were contacted. If later authorized, seal both cohorts, labels, hashes, rubric, and analysis code before contact. Keep E013 contact unauthorized unless separately authorized.
