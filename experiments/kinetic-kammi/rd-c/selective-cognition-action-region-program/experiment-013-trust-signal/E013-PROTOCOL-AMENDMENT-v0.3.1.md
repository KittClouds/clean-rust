# R&D-C / Frozen Fabrique — E013 Protocol Amendment v0.3.1

**Effective protocol ID:** `E013-TRUST-SIGNAL-DEVELOPMENT-v0.3.1`  
**Parent:** sealed `E013-TRUST-SIGNAL-DEVELOPMENT-v0.3`, SHA-256 `74910aededa494c49f741a05fa4d632e1f46c8466ae31ac2447f42832f25c70e`  
**State:** `SEALED_PRECONTACT_DESIGN_ONLY`  
**Contact:** E013-D/C unauthorized; the separate E012 positive control remains authorized but awaits the user-built bank.  
**Bank owner:** user. This amendment creates no bank, task, fixture, seed, label, observer run, or model call.

The effective v0.3.1 protocol is the sealed v0.3 protocol plus the clauses below. These clauses supersede only the corresponding v0.3 requirements. All other v0.3 definitions, bank counts, observer identities, signal definitions, authority, and replay rules remain in force. The v0.3 file and lock remain byte-identical. Its filename/title say v0.3 while its internal ID/status/revision lines say v0.2; this is preserved as a historical identity defect, and v0.3.1 supplies the corrected effective identity.

## 1. Bank-builder locks before task-bank freeze

### Visible-evidence principle

Visible screening represents evidence plausibly available to an ordinary contributor before protected evaluation: patch application, normal compilation/type checking, repository linting, and a deliberately exposed subset of ordinary tests. Hidden completion checks cover task-authoritative behavior not exposed to the router. Select and freeze the visible/hidden partition from the task contract before model contact. Never select or strengthen visible tests in response to observer outputs.

Keep visible and hidden fixtures in disjoint roots with separate manifests and label-writer permissions. The public frame may receive only the designated visible results after a paid/receipted screen. Construction telemetry and hidden labels never enter the observer frame.

### Construction-time T1 cost profile

During bank construction, run the full visible sequence (`apply -> compile/type-check -> lint -> visible tests`) on a known reference-valid patch for every task. Receipt per-stage CPU time and wall time, peak memory when available, host and tool versions, and cache/warm-state conditions. This profile is construction telemetry only: do not expose it to observers, reuse it as the T1 result for an offered candidate, pre-screen offered candidates for later free reuse, or alter fixtures after contact. Measure T1 separately on the small observer's proposed candidate during the experiment; charge every screen as incremental routing cost unless the large-only comparator performs those exact screens.

### Pair and empty-valid construction honesty

Retain the v0.3 truth-changing-pair counts. Pair members must have byte-identical offered candidate patches and identical producer order; task/environment semantics must make the valid set change. Do not encode the changed answer in IDs, order, formatting, family labels, or obvious wording artifacts.

Retain the v0.3 empty-valid quotas. These tasks must look like ordinary candidate-selection tasks with four plausible offered patches; only the sealed executable contract check establishes that the valid set is empty. Do not make them identifiable by malformed candidates, unusual candidate counts, special metadata, or conspicuous phrasing.

## 2. Fixed-correct-recall false-accept diagnostic

In E013-D, for every available trust signal, report false-accept rate at 50%, 70%, and 90% recall of correct non-null raw proposals. Use repository-grouped out-of-fold scores for fitted signals. Define:

```text
correct-proposal recall = correct raw proposals accepted / all correct raw proposals
FAR = wrong raw proposals accepted / all wrong raw proposals
```

All wrong raw proposals enter the FAR denominator, including proposals on empty-valid-set tasks. `NO_PROPOSAL` stays separate and cannot be recovered by a trust signal. At each recall target, use the least-permissive whole-tie threshold that reaches or exceeds the target; report achieved recall, accepted-correct count, accepted-wrong count, total wrong-proposal denominator, FAR, and accepted risk. If ties prevent the target, report the nearest attainable whole-tie point and mark the exact target unavailable. These are development diagnostics, not independent admission gates or a substitute for risk-coverage. Confirmation uses only the frozen development-selected route and threshold.

The oracle-trust ceiling remains an evaluation-only outcome: accept exactly correct non-null proposals. It cannot create a proposal when the small observer returns `NO_PROPOSAL`.

## 3. Fallback accuracy by proposal availability

On E013-C, use the already-required large-only lane to report large raw-action correctness and large-only task completion conditional on the small raw outcome: `NO_PROPOSAL`, `RAW_CORRECT_PROPOSAL`, `RAW_WRONG_PROPOSAL`, and non-null aggregate. Give denominators and repository/family strata. This is a post-outcome diagnostic only; hidden labels do not become routing features or task-selection criteria. Never treat the large observer as ground truth.

## 4. Primary resource axis and gate replacement

The primary engineering resource axis is paired mean end-to-end wall-clock milliseconds per task versus large-only. On the same host and loaded model versions, run both lanes without concurrent benchmark work and balance or randomize lane order by task block. The measured interval includes small inference, routing, receipts, every incremental T1 screen, large fallback, retries, and tool work; it excludes one-time model loading and bank construction. Report paired per-task deltas, the pooled mean (primary), median, p50/p95, and repository/family results. Repository/family-cluster resampling is descriptive uncertainty, not a new gate.

Replace v0.3 admission condition 4 with: no lower observed completed-task count than large-only; at least one large call displaced; and a strictly lower paired mean end-to-end wall time per task. A favorable token, inference-cost, or tool-cost result cannot rescue a failed primary wall-time criterion. Report those axes separately with small/large calls, logical evaluations, screen jobs and durations, input/generated tokens, inference cost, environment/tool cost, and peak memory when available. Do not form an unregistered scalar utility. Every visible screen is incremental unless large-only performs the same screen.

The semantic gate is unchanged: `n_min=60` and one-sided exact 95% Clopper–Pearson upper semantic-error bound `<=5%`. The 59-accept number is only the zero-error CP boundary; it does not satisfy the combined E013 gate. One, two, three, and four errors require at least 93, 124, 153, and 181 accepts respectively. No lowering of the risk bound or post-outcome bank expansion is allowed.

## 5. Positive-control and feasibility boundary

The existing `E012-POSITIVE-CONTROL-DESIGN-v1.2` already freezes `n_accept >= 8` and observed precision `>=80%` per cohort, exact intervals, the between-cohort contrast, and raw correct-proposal yield `c`. Call a passing result only coarse recurrence, never recovery of a safety-qualified region. Under v1.2, `c` is lineage-only and cannot update E013 projections, bank composition, task selection, or trust-signal rules. Any future use requires a versioned amendment before the affected bank is sealed.

The 64-task control is 13.5 times smaller than E013-D (864 tasks) and 17.5 times smaller than E013-C (1,120 tasks); do not describe it as exactly a twelve-times scale-up. Its bank is user-built and absent here, so it remains pending.

## 6. Current execution boundary

E013-D has 864 tasks and E013-C has 1,120 tasks under the unchanged v0.3 design. The user owns construction. No bank, task, fixture, seed, T1 screen, observer call, model/API contact, or scoring was performed by this work. E013-D/C contact remains unauthorized. The v0.3 artifacts remain preserved unchanged.
