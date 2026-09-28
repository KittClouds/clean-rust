# E012 Read-only Anatomy Addendum v1

State: `E012_READONLY_ANATOMY_COMPLETE`  
Source run: `e012-20260926-frame-decomposition-01`  
Model contact: **none**  
Fitting/threshold search: **none**  
E012 source run tree: verified unchanged after read.

## A. Uniform candidate-choice baseline

Candidate-selection tasks: 40; expected uniform correct choices: 11.00 (27.5% expected precision).
On the small observer's 16 accepted proposals, observed correct: 6 (37.5%); uniform-choice expected precision on those same tasks: 21.9%. Difference: 15.6 percentage points. Under independent uniform choices on those exact tasks, P(at least 6 correct) = 0.112. This is a null-reference diagnostic, not an admission test; the sample is small.

## B. Empty-valid-set split

Candidate-selection tasks: 40; pure-abstention tasks: 8.
| Observer | Accepted on candidate tasks | Correct / wrong accepted | Accepted on pure-abstention tasks | Correct deferrals |
|---|---:|---:|---:|---:|
| small | 14 | 6 / 8 | 2 | 6 |
| large | 33 | 23 / 10 | 0 | 8 |

## C. Accepted-action producer ordinal

Descriptive counts by zero-based producer ordinal; no ordering policy is inferred.

**small:** `{"0": {"accepted": 4, "correct": 1, "sample_ids": ["task-16eda64b__0f3c2599ec96", "task-16eda64b__a9c01e2db6bc", "task-2c0d08b1__5352936600d4", "task-2c0d08b1__683f17375f96"], "wrong": 3}, "1": {"accepted": 9, "correct": 3, "sample_ids": ["task-4c1e6cb6__f2723b8cdedb", "task-569812__1871bde99f3d", "task-6309c722__65c841c7de5a", "task-6309c722__b5fa9c9c197d", "task-a16e1f5c__b90ea9c8621d", "task-e3f5bd9b__063b9f0955fe", "task-e3f5bd9b__b19cb65b944a", "task-eab60ff9__965613286f64", "task-eab60ff9__ab3abfeb2a35"], "wrong": 6}, "2": {"accepted": 2, "correct": 1, "sample_ids": ["task-555bd5d9__347b9728e68f", "task-620950__5cd20b8edf72"], "wrong": 1}, "3": {"accepted": 1, "correct": 1, "sample_ids": ["task-555bd5d9__9de2411ef6e5"], "wrong": 0}}`
**large:** `{"0": {"accepted": 9, "correct": 6, "sample_ids": ["task-17dc5b28__4e39603942aa", "task-6309c722__65c841c7de5a", "task-a16e1f5c__b90ea9c8621d", "task-a16e1f5c__ccf8a004a866", "task-a7e74853__205dea8e45df", "task-a7e74853__bbfbfa81460c", "task-b7f8545e__1aa3172d13f8", "task-bbc69658__9f2f260cd3f9", "task-eab60ff9__7255df8bb721"], "wrong": 3}, "1": {"accepted": 11, "correct": 7, "sample_ids": ["task-17dc5b28__1815bf2d0751", "task-2c0d08b1__5352936600d4", "task-2c0d08b1__683f17375f96", "task-4c1e6cb6__37e1918f8267", "task-4c1e6cb6__f2723b8cdedb", "task-5befee37__d7180233e684", "task-6309c722__b5fa9c9c197d", "task-a7e74853__6c0bea05d1df", "task-a7e74853__6de65b23eefa", "task-b7f8545e__23e4d7ece244", "task-eab60ff9__965613286f64"], "wrong": 4}, "2": {"accepted": 8, "correct": 5, "sample_ids": ["task-555bd5d9__347b9728e68f", "task-8c717407__d5e9bc4ac1e9", "task-8f66a11b__060910fc4857", "task-8f66a11b__44475855fd8d", "task-e8fdd1f4__395ea35614ed", "task-e8fdd1f4__7ab3d64ee684", "task-eab60ff9__ee69aeb31661", "task-f4b5a75d__d42aad4151b6"], "wrong": 3}, "3": {"accepted": 5, "correct": 5, "sample_ids": ["task-555bd5d9__9de2411ef6e5", "task-8c717407__55a28d5cfef8", "task-a1425719__3ab831f8f853", "task-eab60ff9__ab3abfeb2a35", "task-f4b5a75d__22686fd530e9"], "wrong": 0}}`

## D. Pair sensitivity

Eligible fixed-patch-order groups: 14; pairwise truth-changing contrasts: 24.
Each contrast changes the valid patch set while preserving the exact candidate patch sequence. Pair contrasts within a factorial group are dependent; results are descriptive.

- **small:** both correct 1; both wrong 3; exactly one correct 5; one or both abstained 15; changed choice among both-proposed contrasts 1/9.
- **large:** both correct 10; both wrong 3; exactly one correct 11; one or both abstained 0; changed choice among both-proposed contrasts 15/24.

## E. Small/large error overlap

### Accepted proposal correctness

`{"both_correct": 4, "large_correct_only": 19, "neither_accepted_correct": 23, "small_correct_only": 2}`

### Wrong accepted action overlap

`{"both_wrong_accepted": 3, "large_only_wrong_accepted": 7, "large_wrong_accepted": 10, "small_only_wrong_accepted": 7, "small_wrong_accepted": 10}`

### Task completion

`{"completion_matrix_from_sealed_autopsy": {"small_done__large_done": 4, "small_done__large_not_done": 2, "small_not_done__large_done": 19, "small_not_done__large_not_done": 23}, "hybrid_completed": 22, "large_completed": 23, "small_completed": 6, "task_count": 48}`

Proposal correctness and end-to-end task completion are distinct outcomes.

## F. Fresh positive control

**Designed, not run.** See `E012-POSITIVE-CONTROL-DESIGN.md`. Model contact remains unauthorized.

## Source identities

```json
{
  "frozen-input-lock.json": "4bab6fd945248b6209fa33e3a1df10786298ac620342ce167251411c6a258cd8",
  "inputs/full-frame-lock.json": "e4d9c2e0c668bfa60445ac476ad1f1b695fe8f1bfc9fd07b5746c7b31dbbeb0b",
  "reports/full-frame-baseline-autopsy-v1.json": "17dfc2e69a146e569d895500e3cc43f8852c60d1e274f48f28dc4745a87ea694",
  "reports/full-frame-baseline-report.json": "2155e62daf0650da8e44fb3c44704deb8c4bd2aff615e859ec215aabd6e1a6ed",
  "vault/evaluation-labels.json": "e9e81f71e46e167b077d4123a84d918b7d2f4afb791a009700f5390f61106caa"
}
```

## Boundaries

- This is post-outcome descriptive analysis of E012 only; no fitting, threshold selection, subgroup admission, or new capability claim.
- Candidate-choice chance assumes uniform choice over offered candidates and does not model an abstention strategy.
- Task completion and semantic proposal correctness are reported separately.
- Pair contrasts are not independent inferential units.
