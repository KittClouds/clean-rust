# E013 Precontact Feasibility Receipt v0.3

State: `PRECONTACT_FEASIBILITY_COMPLETE; BANKS_NOT_BUILT; NO_E013_MODEL_CONTACT`  
Date: 2026-09-26  
Purpose: resolve proposal-yield, signal-cost, and admission-gate reachability before task-bank sealing.

## 1. Lab-law access and instruction boundary

Both user-provided files were opened from their exact supplied paths and read:

- `Lab Law.txt` (SHA-256 `a6f85e7a2cc09b9762c17763f03c2eee51b27e099d8faaeeac548452c2c52026`): the System 1.5 Lab charter. For this work its relevant contracts are semantic, decision, measurement, and policy separation; models are replaceable substrates; evidence and calibration are measurement questions; and a model output is not itself authority.
- `lab law grant.txt` (SHA-256 `9380672300b9d8b7c2e21e1fb6a5a4136a159df6c5351f4438aab6c0a09cc600`): a strategic/funding portfolio memo. It explicitly distinguishes the pinned portfolio from the operational experiment ledger. It is not an E013 protocol and does not authorize model contact.

I treated these documents as lab context, not as a replacement for the user's direct request. The controlling task instruction is: **do not build any task bank; the user is building it.** E012 remains immutable. The user separately authorized running the 64-task positive control once its bank is supplied. E013-D/C model contact remains unauthorized pending its own later authorization.

## 2. Sealed E012 raw-yield result

The read-only recount is in `../e012-readonly-anatomy-addendum/E012-RAW-PROPOSAL-YIELD-v1.0.md` and its JSON. It reads, but does not alter, the E012 run.

| E012 outcome | All 48 tasks | 40 candidate tasks | 8 empty-valid-set tasks |
|---|---:|---:|---:|
| Correct raw small proposal | 7 | 7 | 0 |
| Wrong raw small proposal | 11 | 9 | 2 |
| No raw proposal | 30 | 24 | 6 |

Thus the conservative all-task correct-proposal rate is `c = 7/48 = 14.58%`; wrong proposal rate is `11/48 = 22.92%`; and no-proposal rate is `62.50%`. Among non-null raw proposals, precision was `7/18 = 38.89%`. The old v5 rectangle accepted 6 of those 7 correct raw proposals and 10 of 11 wrong raw proposals. Six of ten wrong accepted actions were at producer ordinal 1. These are fixed E012 descriptions, not a new routing rule.

## 3. Gate reachability

The exact one-sided Clopper-Pearson 95% gate requires at least 59 accepted proposals with zero errors (`U=4.9508%`) or 93 with one error (`U=4.9994%`). Two errors require 124 accepted proposals. Support and risk gates remain unchanged.

Using E012's `c=7/48` as a pessimistic iid planning proxy:

| Confirmation size | Oracle expected correct proposals | P(at least 59) | P(at least 93) | Correct proposals expected at 70% recall | P(at least 93 at 70% recall) |
|---:|---:|---:|---:|---:|---:|
| v0.2: 512 | 74.67 | 98.11% | 1.46% | 52.27 | effectively 0% |
| v0.3: 1,120 | 163.33 | ~100% | ~100% | 114.33 | 98.64% |

At 512 tasks, the oracle ceiling barely reaches the zero-error support threshold in expectation and cannot plausibly support the one-error threshold; even 70% recall of correct raw proposals has only an 18.05% chance to reach 59. At 1,120 tasks, 70% recall has a 98.64% planning probability of reaching 93 correct accepted proposals. At 50% recall, the 1,120-task probability of reaching 93 is only 10.80%; the larger bank does not guarantee promotion. These are support calculations only: harmful accepted proposals still count as errors and the exact risk gate still decides admission.

For comparison, the explicit nominal planning scenario uses `p(correct raw)=25%`, `p(wrong raw)=25%`, and `p(no proposal)=50%`. This is an **assumption for sizing only**, not an empirical estimate, a model performance claim, or a bank quota. It gives 280 correct raw proposals in 1,120 confirmation tasks and 196 expected correct proposals retained at 70% recall.

Development T5 requires at least 100 correct and 100 wrong non-null small proposals. Under E012 rates, the old 576-task design expects 84 correct and 132 wrong and has only a 3.59% iid planning chance to reach both minima. The v0.3 864-task design expects 126 correct and 198 wrong and has a 99.57% iid planning chance to reach both. The nominal scenario expects 216 of each and is effectively certain to meet both. The larger development bank makes T5 feasible to attempt; T5 remains unavailable if the sealed bank's observed support misses its threshold. No bank expansion is allowed after observer outcomes are seen.

All probabilities above use independent task-level multinomial/binomial assumptions. Repository/family clustering and fixed bank composition make them planning illustrations, not guarantees or confidence claims.

## 4. Frozen v0.3 bank sizes

To preserve a reasonable chance of reaching the existing support gate under E012-like yield, without lowering the 5% error bar:

- **E013-D:** 864 tasks = 6 repositories × 8 families × 18 tasks per cell. One empty-valid-set task per repo-family cell. One truth-changing candidate pair per cell is included inside the fixed count (96 paired task instances total).
- **E013-C:** 1,120 tasks = 4 fresh repositories × 8 families × 35 tasks per cell. Two empty-valid-set tasks and one truth-changing candidate pair per repo-family cell are included inside the fixed count (64 empty-valid instances and 64 paired instances total).

The bank owner may construct and seal those task instances. This receipt creates no tasks, labels, fixtures, or repository snapshots.

## 5. Per-signal workload projection

Projection is for four-candidate tasks. T1 screens each non-null base proposal with four separately receipted stages (apply, compile/type-check, lint, visible-test summary). T2 uses three shadow permutations per non-null base proposal. T3 scores four candidate IDs. T4 uses six unordered pairs in both orientations: 12 observer evaluations per non-null base proposal. The separately versioned T6 `NONE` action-space arm adds one small-observer evaluation on each task; it is not a trust signal or part of the admission gate. A no-proposal outcome stays `NO_PROPOSAL`; it is not rescued by a trust signal. T5 captures a read-only state during the base pass if possible; otherwise its separate pass is charged. The combined signal pays the sum of its component workloads.

| Bank / scenario | Expected raw proposals | T1 screen jobs | T2 extra small evals | T3 candidate score evals | T4 pairwise evals | T6 extra schema evals |
|---|---:|---:|---:|---:|---:|---:|
| D864 / E012 pessimistic | 324 | 1,296 | 972 | 1,296 | 3,888 | 864 |
| D864 / nominal assumption | 432 | 1,728 | 1,296 | 1,728 | 5,184 | 864 |
| C1120 / E012 pessimistic | 420 | 1,680 | 1,260 | 1,680 | 5,040 | 1,120 |
| C1120 / nominal assumption | 560 | 2,240 | 1,680 | 2,240 | 6,720 | 1,120 |

The exact workload rules and projections are reproduced by `project_e013_feasibility.py`. E012 measured mean full-call times were 242.11 ms for small and 3,076.58 ms for large. Scaling the small full-call mean gives the following rough observer-evaluation time proxies; teacher-forced scoring and execution screens have different, currently unmeasured costs:

| Bank / scenario | T2 proxy | T3 proxy | T4 proxy | T6 separate schema proxy |
|---|---:|---:|---:|---:|
| D864 / E012 pessimistic | 3.9 min | 5.2 min | 15.7 min | 3.5 min |
| D864 / nominal assumption | 5.2 min | 7.0 min | 20.9 min | 3.5 min |
| C1120 / E012 pessimistic | 5.1 min | 6.8 min | 20.3 min | 4.5 min |
| C1120 / nominal assumption | 6.8 min | 9.0 min | 27.1 min | 4.5 min |

The base routed lane also requires exactly one small-observer call per task (864 D / 1,120 C). Large fallback calls depend on the accepted count: at the E012 oracle ceiling they would be about 738 for D and 957 for C; at the nominal oracle ceiling they would be 648 and 840. The oracle numbers are cost illustrations, not routing policies.

These are not promised wall times. Batch execution can reduce overhead but does not remove the logical forward-evaluation count. T1's four external screens are counted as jobs; their CPU/wall cost must be measured on the sealed bank. T5's one representation capture per task is zero additional model calls only if it is captured during the already-required small forward pass and passes the precontact hook/no-hook identity check. The separate T6 `NONE` schema arm has one additional small-observer evaluation per task; it is not part of T1–T5 or the primary trust gate.

## 6. E013 interpretation locked before contact

- Report the **oracle-trust ceiling** on every bank: accept exactly correct non-null small proposals. This evaluation-only ceiling has no false accepts and cannot rescue a `NO_PROPOSAL`; report its task coverage and proposal-conditional precision separately.
- Keep `NO_PROPOSAL`, correct raw proposal, and wrong raw proposal as three separate outcomes before reporting any signal curve.
- Under current evidence, T1 is the only signal expected to have a plausible path to the zero/one-error acceptance range because it adds independent execution evidence. This is a prior expectation, not a privileged claim or exclusion rule. T2–T5 may still deliver meaningful risk-coverage improvements without clearing admission.
- A signal that improves held-out risk-coverage but misses support, exact risk, or fallback-relative value is an informative diagnostic result, not a null and not a promoted router.
- E013-C remains closed to contact until the user's bank is sealed and a separate contact authorization is provided. Do not resize, replace, or filter bank tasks after seeing observer outputs.

## 7. Input and code identities

The v0.2 E013 protocol and lock remain preserved. The v0.3 lock binds this receipt, the v0.3 protocol, E012 raw-yield recount, E012 source lock/report/labels, both user-supplied Lab Law documents, and the revised positive-control design. The two new calculation scripts use no model/API and create no bank.
