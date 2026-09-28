# E013 Precontact Feasibility Receipt v0.3.2

State: `PRECONTACT_FEASIBILITY_COMPLETE; USER_BANKS_PENDING; NO_E013_MODEL_CONTACT`  
Date: 2026-09-26  
Purpose: reconcile proposal yield, exact-gate specificity, trust-signal compute, T1 costs, fallback reporting, and the primary resource axis before bank freeze.

## Lab Law and ownership boundary

The exact supplied `Lab Law.txt` and `lab law grant.txt` files were read and their hashes are bound by this lock. The former is the System 1.5 Lab charter; the latter is strategic/funding guidance, not the E013 protocol. The user owns E013 bank construction. No bank or model contact occurred.

## E012 yield and bank-composition sensitivity

E012 pooled: 7 correct, 11 wrong, 30 `NO_PROPOSAL` of 48. By stratum: candidate-selection 7/9/24 of 40; empty-valid 0/2/6 of 8. The pooled rate is retained as the conservative planning proxy. Reweighting the E012 strata to the fixed E013 quotas yields:

| Bank | Candidate-selection + empty tasks | Expected correct / wrong / no-proposal |
|---|---:|---:|
| D, 864 | 816 + 48 | 142.8 / 195.6 / 525.6 |
| C, 1,120 | 1,056 + 64 | 184.8 / 253.6 / 681.6 |

The stratum-weighted values are a sensitivity, not an E013 yield claim. They assume E012 within-stratum rates transfer. E012 old-rectangle acceptance was 6/7 correct and 10/11 wrong; that failed contract is not reused.

## Exact support and false-accept specificity

The combined gate is `n>=60` plus exact one-sided 95% upper error bound `<=5%`. Zero errors alone reaches the CP boundary at 59, so 59 is CP-only. One through four errors require 93, 124, 153, and 181 accepts.

At C=1,120 under pooled E012 rates, expected correct/wrong raw proposals are 163.3/256.7. At rounded expected correct support, the exact gate permits:

| Correct-proposal recall | Expected correct accepts | Max wrong accepts at expected support | FAR of wrong raw pool |
|---:|---:|---:|---:|
| 50% | 81.7 | 0 | 0.00% |
| 70% | 114.3 | 1 | 0.39% |
| 90% | 147.0 | 2 | 0.78% |

For comparison, the asymptotic 5% risk ceilings at 50/70/90% recall are 1.67%/2.34%/3.01%. The finite exact gate at expected support is stricter. Under nominal 25/25/50 rates, finite-gate FAR illustrations are 0.71%/1.43%/2.14%; under stratum sensitivity they are 0.39%/0.79%/1.18%. These fractional-mean calculations are planning illustrations; actual admission uses realized integer counts.

E013-D will report empirical FAR at 50/70/90% correct-proposal recall for every available signal, using repository-grouped out-of-fold scores and whole ties. `NO_PROPOSAL` remains separate; a trust signal cannot manufacture proposals.

## Signal workload and economic headroom

For each non-null four-candidate proposal, v0.3 charges T1 four screen jobs, T2 three extra small evaluations, T3 four teacher-forced candidate scores, and T4 twelve pairwise evaluations. T5 is zero additional model calls only if an inline hook passes the no-hook identity check; hook wall time still must be measured. T1 runtime cost and actual T3 teacher-forced latency are unmeasured.

Projected logical evaluations and rough full-small-call-equivalent time (using E012's small-call mean) are:

| Bank / scenario | T1 jobs | T2 evals / proxy | T3 evals / proxy* | T4 evals / proxy |
|---|---:|---:|---:|---:|
| D864 / pooled | 1296 | 972 / 3.92 min | 1296 / 5.23 min* | 3888 / 15.69 min |
| D864 / nominal | 1728 | 1296 / 5.23 min | 1728 / 6.97 min* | 5184 / 20.92 min |
| D864 / stratum sensitivity | 1354 | 1015 / 4.10 min | 1354 / 5.46 min* | 4061 / 16.39 min |
| C1120 / pooled | 1680 | 1260 / 5.08 min | 1680 / 6.78 min* | 5040 / 20.34 min |
| C1120 / nominal | 2240 | 1680 / 6.78 min | 2240 / 9.04 min* | 6720 / 27.12 min |
| C1120 / stratum sensitivity | 1754 | 1315 / 5.31 min | 1754 / 7.08 min* | 5261 / 21.23 min |

*T3's full-call proxy is not its measured teacher-forced cost. Batch execution may reduce request overhead but does not remove logical evaluations. T1 screen CPU/wall cost remains unmeasured until the user bank builder profiles it.

E012 mean full calls: 242.11 ms small, 3076.58 ms large. Under pooled E012 yield and zero false accepts, the large-call saving minus the always-paid small call leaves -17.8 ms/task/72.0 ms/task/161.7 ms/task at 50/70/90% correct-proposal recall. At 70%, that is only 191.9 ms per non-null proposal at E012's 37.5% non-null rate.

Full-small-call proxies at that non-null rate are 272.4 ms/task/363.2 ms/task/1089.5 ms/task for T2/T3/T4 respectively. These proxy costs show the headroom risk; they do not substitute for measured end-to-end lane time.

## Frozen engineering comparison

Primary resource gate: paired mean end-to-end wall-clock ms/task versus large-only, with small inference, routing, receipts, incremental T1 screens, fallback, retries, and tool work included; one-time model load and bank construction excluded. Same host and loaded models, no concurrent benchmark work, balanced/randomized lane order by task blocks. The route must strictly reduce this primary mean while preserving completion, displacing a large call, and passing the exact semantic gate. Tokens, inference/tool cost, screen work, calls, and memory remain separate reports; no secondary axis can rescue a failed wall-time gate.

All candidate-specific T1 screens are incremental unless large-only performs those exact screens. Bank construction separately times the full screen sequence on a known reference-valid patch per task; construction telemetry is not a reusable/cached T1 result.

## Positive control and status

The already-locked 64-task E012 positive control has `>=8` accepts and `>=80%` observed precision as its coarse recurrence criterion, plus exact intervals and a cohort contrast. Its `c` values remain lineage-only and do not update E013 projections. The 64-task control is 13.5x smaller than D864 and 17.5x smaller than C1120. Its user-built bank is pending.

No bank, seed, fixture, screen, observer call, or model/API contact was produced by this work. E013-D/C model contact remains unauthorized. v0.3 and its lock are unchanged.

## Versioned arithmetic correction

The asymptotic FAR formula is corrected under `E013-PRECONTACT-CORRECTION-v0.3.2.md`. The v0.3.1 finite exact-gate FAR table is unchanged. The corrected asymptotic ceilings at 50/70/90% recall are E012 pooled 1.67%/2.34%/3.01%, nominal 2.63%/3.68%/4.74%, and E012 stratum sensitivity 1.92%/2.69%/3.45%. The underlying error is an inverted `epsilon/(1-epsilon)` factor; no bank or model boundary changed.
