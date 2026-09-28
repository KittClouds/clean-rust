# E012 Fresh Positive-Control Design v1.2 — Authorized, Awaiting User Bank

**Control ID:** `E012-PC-01-v1.2`  
**Status:** `MODEL_CONTACT_AUTHORIZED; BANK_NOT_SUPPLIED; NOT_RUN`  
**Purpose:** test recurrence of the frozen E009/E010-style small-action region and compare it with a prospectively difficulty-matched cohort. This is a diagnostic and pipeline shakedown, not a trust-signal selection set, E013-D data, or confirmation bank.

## Bank design — user-owned

Use 64 new local-commit tasks on two fresh frozen Rust repository snapshots. The user is building this bank; this design does not create tasks, snapshots, candidate patches, labels, fixtures, or a substitute bank. No E009, E010, E011, or E012 task instance is reused.

Each repository contributes four task families to each of two predeclared cohorts, with four tasks per repository-family-cohort cell:

| Cohort | Design | Tasks |
|---|---|---:|
| E009/E010-regime positive control | Clear, short local-commit coding tasks with explicit requested behavior and a useful offered candidate | 32 |
| E012-construction-difficulty-matched contrast | Fresh tasks matched on outcome-blind construction difficulty dimensions | 32 |

Match the cohort distributions before model contact using only construction metadata and a blinded rubric: number of operative constraints, ambiguity of task wording, similarity of plausible candidate patches, evidence conflict, reasoning depth, distractor plausibility, repository/family cell, and candidate count. Do not use E012 observer outputs, accepted/wrong labels, or post-outcome performance to select, match, or replace tasks. Freeze source commits, candidates and producer order, prompts, visible and hidden fixtures, executable checks, independent valid-set labels, IDs, and hashes.

## Frozen run

Use the exact E012-locked v5 small and large bundles, prompt, output schema, normalization, 850/150 thresholds, runtime mode, output cap, producer-order presentation receipt, authority, and replay policy. Verify all frozen identities against E012 before contact. Run small-only, large-only, and the existing small-to-large-on-abstention hybrid on the same sealed tasks. Do not tune thresholds, prompts, observer bundles, or routing. Use executable completion checks and independent valid-action labels as outcome authority; the large observer is not truth.

Report per repository and cohort: raw correct proposal yield `c`, raw wrong proposals, no-proposal count, small coverage, accepted-action precision, false accepts, large calls avoided, each lane's task completion, latency, tokens, and integrity counts. Keep raw proposal yield distinct from threshold acceptance and from end-to-end completion.

## Numeric interpretation locked before contact

For each cohort, define `n_accept` as the number of non-null small proposals accepted by the frozen v5 rectangle. Define accepted precision as correct accepted proposals divided by `n_accept`; report `UNDEFINED` if no proposal is accepted. A cohort **meets the positive-control recurrence criterion** only if:

1. `n_accept >= 8` (a nonzero, minimally sized action region for this 32-task diagnostic), and
2. observed accepted precision is at least `80%`.

This is a descriptive recurrence criterion, not a deployment or safety gate. Report a two-sided exact Clopper-Pearson 95% interval for precision in each cohort and every repository stratum, with the denominator shown.

The predeclared between-cohort contrast is `Delta = precision(positive-control cohort) - precision(difficulty-matched cohort)`. Report Delta and a conservative two-sided 95% exact interval: calculate separate two-sided 97.5% Clopper-Pearson intervals for the two conditional precisions and form `[L_positive - U_matched, U_positive - L_matched]`. By Bonferroni this interval has at least 95% coverage under independent task-level Bernoulli sampling conditional on the accepted counts; it is conservative and does not account for repository/family clustering. Also report the exact two-sided Fisher test as a descriptive check. If the interval includes zero, classify the contrast as `INDETERMINATE`, even if point estimates differ. With roughly a dozen accepts per cohort, a very large gap such as approximately 90% versus 40% may be visible, while small differences will remain unresolved.

Report `c = correct raw small proposals / 32` for each cohort, plus wrong raw proposals and null outcomes. This is lineage information only: it must not select E013 features, thresholds, or task replacements. Independently report task completion and per-repository outcomes. No capability claim is promoted from this 64-task control.

## Pipeline shakedown

Before scoring, verify the same path E013 will need: repository snapshot hashes, candidate identity and producer-order receipts, independent label-writer separation, visible/hidden fixture hash separation, executable completion checks, scorer input schema, replay, and report aggregation. Run a precontact parser/replay dry run that does not invoke either observer. Any construction or code defect is repaired by a versioned amendment before observer contact; never repair a result after seeing it.

## Stop boundary

The user has authorized positive-control model contact. The 64-task bank and its labels are not supplied in this work state, so the authorized run is pending. Do not build replacement tasks or contact a model until the user-built bank is present and its snapshots, labels, fixtures, executable checks, and hashes are sealed. This control does not authorize E013-D/C model contact. Keep the original v1.1 design and its hashes unchanged.
