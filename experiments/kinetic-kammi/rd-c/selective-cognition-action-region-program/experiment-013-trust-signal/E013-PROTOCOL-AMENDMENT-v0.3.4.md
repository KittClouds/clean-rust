# R&D-C / Frozen Fabrique — E013 Protocol Amendment v0.3.4

**Effective protocol ID:** `E013-TRUST-SIGNAL-DEVELOPMENT-v0.3.4`  
**Parents:** sealed v0.3.2 protocol package and v0.3.3 feasibility supplement  
**State:** `SEALED_PRECONTACT_DESIGN_ONLY`  
**Contact:** E013-D/C remains unauthorized; E012 positive control remains separately authorized and awaits the user-built bank.  
**Bank owner:** user. This amendment creates no bank, task, fixture, seed, score, or model call.

This version locks the two remaining precontact decisions: uncertainty for the primary wall-time gate and selection of the single development signal passed to confirmation. It also freezes the requested repository and leave-one-repository-out reporting. All prior bank sizes, signal definitions, authority/replay semantics, exact semantic gate, T1 accounting, and contact boundaries remain unchanged unless expressly stated here. Earlier versions remain byte-identical.

## 1. Primary wall-time gate: paired repository-cluster bootstrap

For every confirmation task `i`, define the paired difference:

```text
d_i = routed end-to-end wall-clock milliseconds_i - large-only end-to-end wall-clock milliseconds_i
```

The primary point estimate is the arithmetic mean of `d_i` over all C tasks. To pass the resource gate, the **one-sided 95% upper confidence bound** for this mean must be strictly below zero. A negative point estimate alone does not pass.

Compute that bound with a two-stage paired cluster bootstrap, preserving the repository/family structure and task pairing:

1. Use repositories as the outer resampling unit. In each replicate, sample the four confirmation repositories with replacement, four draws total.
2. For each selected repository draw, sample its eight task-family blocks with replacement, eight draws total. Include all 35 task rows in each selected family block; keep truth-changing pair members together and retain each task's routed/large-only timing pair.
3. Pool the resulting 1,120 paired deltas and calculate their arithmetic mean.
4. Use 100,000 replicates, NumPy `PCG64` with seed `13034`, and the nearest-rank empirical 95th percentile as the one-sided upper bound.

The scoring implementation, NumPy version, exact bootstrap code, and its fixture tests must be hashed before E013-C contact. Do not change the resampling unit, replicate count, seed, quantile convention, or estimator after seeing confirmation timings. The four-repository cluster count is small; report each repository mean and the leave-one-repository-out estimates so readers can see concentration. These are diagnostics and do not create an alternate resource gate.

All timing inclusion/exclusion, same-host conditions, lane-order balancing, and paired measurement rules from v0.3.1 remain in force. Completion must remain no lower than large-only, at least one large call must be displaced, and integrity checks must remain clean. The wall-time upper bound replaces the prior point-estimate-only “strictly lower mean” criterion; no secondary cost axis may rescue it.

## 2. Frozen E013-D signal selection rule

Apply this rule once, using only E013-D and the already-frozen repository-grouped out-of-fold predictions, outcomes, and measured costs. E013-C remains untouched until the selected route and all code/threshold artifacts are frozen.

### Per-signal operating point

For each available individual T1-T5 signal and the one combination permitted by v0.3, use its cross-fitted scores and whole-tie threshold behavior. Select the **highest-coverage** operating point that simultaneously has at least 60 accepted non-null small proposals and an exact one-sided 95% Clopper-Pearson upper semantic-error bound at or below 5%. If no point satisfies both, mark that signal development-ineligible. T6/NONE remains a separate action-space arm and cannot enter this selection.

For each remaining signal, report its operating recall `s_D` (accepted correct raw proposals divided by all correct raw proposals), its empirical FAR at that operating point (accepted wrong raw proposals divided by all wrong raw proposals), and the fixed-recall FAR diagnostics at 50%, 70%, and 90%. `NO_PROPOSAL` is outside all trust-signal denominators and remains its own outcome.

For fixed-recall FAR diagnostics, preserve the v0.3.1 whole-tie rule: never split equal scores. Use the least-permissive whole-tie threshold that reaches or exceeds each target; report achieved recall and the exact accepted counts. If the target is not attainable exactly, mark that fact and report the achieved whole-tie point. For the selected operating threshold, use the concatenated repository-grouped out-of-fold score values and outcomes. If a signal is refit on all E013-D, apply the frozen numeric threshold unchanged; no full-D or E013-C recalibration is allowed. Any score-scale shift is evaluated only on untouched E013-C.

### Economic eligibility

On E013-D, measure mean full small-call latency `C_small`, mean full large-call latency `C_large`, correct raw proposal fraction `c_D`, and non-null proposal fraction `p_D`. For signal `j`, compute its mean incremental wall-clock trust cost per non-null proposal `T_j` from all measured work attributable to that signal; allocate any fixed per-task signal overhead across the D bank's non-null proposals. Include actual T1 screens and all signal-specific inference/processing; do not substitute full-call proxies for measured teacher-forced or batched costs.

At the signal's development operating recall `s_D`, compute:

```text
T_max(s_D) = (c_D * s_D * C_large - C_small) / p_D
```

The signal is economically eligible only when `T_max(s_D) > 0` and `T_j < T_max(s_D)`. A signal at or above break-even does not proceed to C, even if its semantic risk-coverage curve is better. These D measurements are a selection screen; C must still pass the independently locked paired wall-time confidence-bound gate.

For planning reference only, E012's measured means were `C_small=242.110 ms` and `C_large=3076.582 ms`:

| Scenario | Free-trust break-even recall | `T_max` at 70% recall | at 90% | at 100% |
|---|---:|---:|---:|---:|
| E012 pooled (`c=7/48`, `p=18/48`) | 54.0% | 191.9 ms | 431.2 ms | 550.8 ms |
| Nominal (`c=25%`, `p=50%`) | 31.5% | 592.6 ms | 900.2 ms | 1054.1 ms |

The planning rows are not observed E013 performance. The per-signal D decision uses measured E013-D values in the formula above.

### One signal moves to C

Among signals that pass both the development semantic operating-point condition and the economic eligibility condition, select the signal with the **lowest development FAR at its selected operating point**. This deliberately selects specificity after each candidate has independently selected its highest-coverage point under the same risk/support rule. If FAR is exactly tied, choose lower measured `T_j`; if still tied, use this frozen identifier order: `T1`, `T2`, `T3`, `T4`, `T5`, `COMBINATION`.

Freeze the selected signal, cross-fit/refit artifacts, operating threshold, achieved development recall, cost calculation, fallback, and scorer hashes before any C task outcomes are opened. Run only that one selected signal as the primary E013-C route. If none qualify, select no router and do not substitute another signal after looking at C.

## 3. Repository and leave-one-out reporting

For E013-C, report accepted direct-action count `n`, wrong accepted count `x`, and correct accepted count `n-x` separately for each repository, alongside the pooled counts. Also report completion, large calls displaced, and mean paired wall-time difference by repository.

Add a descriptive leave-one-repository-out table: omit each repository in turn and recalculate pooled `n`, `x`, observed risk, exact one-sided 95% Clopper-Pearson upper error bound, completion difference, and mean paired wall-time difference on the remaining tasks. This is a concentration diagnostic only. It does not replace or modify the full-bank admission rule, enable threshold changes, or support a per-repository portability claim. Preserve the already-locked repository harmful-stratum guard and the exact pooled semantic gate unchanged.

## 4. Admission gate and authorization boundary

The full-bank E013-C semantic gate remains `n >= 60` plus one-sided exact 95% Clopper-Pearson upper semantic-error bound `<=5%`, including wrong proposals on empty-valid-set tasks. The pre-existing repository guard, completion condition, at-least-one-displaced-large-call condition, presentation/authority/replay invariants, and duplicate-effect checks remain unchanged. The resource condition is now the one-sided 95% upper bound above being `<0`.

This amendment is protocol-only. E013-D/C model contact is still unauthorized until separate explicit authorization after the user-built banks, adapters, scoring implementation, manifests, and precontact checks are sealed. It authorizes no task construction, screen, model call, scoring, bank resizing, or experiment run.
