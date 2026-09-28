# R&D-C Program State

This file tracks the bounded engineering results relevant to the small-observer switchboard. Experiment reports remain the source for detailed receipts, inputs, and per-task scores.

## Current evidence

| Experiment | Status | Bounded result |
| --- | --- | --- |
| E009 — real semantic observer | Useful within-repository fast lane | On the frozen same-repository pilot, the hybrid retained completion while replacing 3 of 8 large calls with successful small actions. It reduced measured time and increased tokens by 49%; this is a latency and large-call trade, not a token-saving result. |
| E010 — cross-repository transfer | Passed the preregistered switchboard gate on two Rust repositories | With the same frozen E009 v5 bundles, thresholds, and routing rule, small coverage was 13/16 at 13/13 direct precision. The hybrid completed 16/16 and displaced 13 large calls. By repository: ripgrep 8/8 hybrid vs 8/8 always-large; turbovec 8/8 vs 5/8. The bank has four task families per repository and two variants per family. |
| E011 — causal evidence dependence | Completed as a same-bank diagnostic | Evidence masking reduced small coverage; evidence swapping changed proposals; removing direct repository identity left useful coverage. These interventions do not isolate internal mechanism because prompts, code, tests, and candidates retain overlapping task information. Candidate permutation produced wrong accepted actions in both repositories. |
| E011-R1 — patch-hash canonicalization | Rejected repair | Sorting by patch digest made paired frames invariant, but small precision on turbovec fell to 2/8 and hybrid completion to 2/8. An arbitrary canonical order is not a safe fix. |
| E011-R2 — ID/order factorial | Completed; localized the bank failure to ordering | Changing IDs alone retained 12/12 direct precision and 16/16 hybrid completion. Changing order alone produced 3 wrong accepted small actions; hybrid completion was ripgrep 7/8 and turbovec 5/8. This is a frozen-bank input sensitivity result, not a broad mechanism claim. |
| E011-R3 — order-robust prompt | Rejected repair | Explicitly telling the small observer to ignore IDs and order reduced direct coverage and still left two wrong accepted actions in the permuted lane. It reduced that lane's hybrid completion to 11/16, and original-order hybrid completion to 13/16. |
| Producer-order restoration | Useful deterministic repair seam | Assigning ordinals when candidates are created and restoring that order reconstructed the entire original E010 frame for 16/16 R2 permutations. This repairs input instability when candidates move in transport; it does not prove the observer is order-invariant. |
| E011 producer-order integration qualification | Passed on a fresh, bounded live-path bank | With frozen E009 v5 bundles, prompt, normalization, routing, and 850/150 thresholds, producer order was restored before serialization and bound through observer request, response, authority, and replay. On two fresh task families (two variants each), small and hybrid completed 4/4 with 4/4 direct precision; always-large also completed 4/4. Hybrid displaced all four large calls. All 12 lane receipts replayed identically; illegal commits and duplicate effects were zero. This qualifies the integration path on these fixtures, not new transfer breadth. |

## Reusable runtime repair

`rdc-runtime-contracts-v1` now includes producer-ordinal ordering, a versioned candidate-presentation receipt, and an authority-facing proposal resolver. It binds task identity, action IDs, patch digests, and their exact sequence. A caller can restore the producer's sequence before observer contact, then validate the persisted receipt before resolving a proposal to an action and during replay. A changed sequence is rejected. Receipt validation and order restoration are in-place and allocate no heap memory. The caller must assign ordinals when candidates are created; the receipt guards downstream drift and does not prove that a proposal is correct.

Verification: release tests passed (14 integration tests), strict Clippy passed, and the candidate-presentation test binary built to `D:\cargo-targets\rdc-runtime-contracts-v1` and passed again from `C:\rd-c\rdc-runtime-contracts-v1\artifacts\linked-tests`. Criterion estimates were 478 ns to validate four options and 66.3 μs at the 256-option cap; producer-order restoration was 34 ns and 13.2 μs respectively.

The E011 live integration adapter is in `experiment-011/repairs/producer-order-v1/runtime-integration`. It restores producer ordinals before observer serialization, binds request and response envelopes to a versioned receipt without changing the frozen v5 prompt, validates that binding before action authorization, and revalidates the presentation during replay. Four focused integration tests passed from a copied executable in `C:\rd-c\experiment-011\repairs\producer-order-v1\artifacts\linked-tests`; strict Clippy and package-local formatting checks passed. The fresh qualification uses four held-out-to-the-observer frames over only two underlying task families, so it verifies wiring and preserves the fast lane on this bank without increasing the breadth claim.

## Active hypotheses

- **High-precision accessibility region:** supported on the E009/E010 frozen candidate presentations; candidate order can move or damage that region.
- **Stable producer coordinates are a runtime precondition:** supported by E011-R2 and the fresh live integration qualification. This is an interface requirement, not observer permutation invariance.
- **Task-evidence transfer:** plausible, but not isolated. E011 only shows sensitivity to particular frame edits.
- **Abstention quality:** a useful part of E010's hybrid result; the candidate-order lane shows that high coverage without stable selection can be harmful.
- **Call efficiency differs from token efficiency:** directly observed in E009 and E010.
- **Deterministic authority enables selective cognition:** supported for legal state/action authority and replay. It does not catch a semantically wrong but legal candidate by itself.

## Next engineering seam

The isolated live switchboard integration seam is closed: the observer call, authority decision, task completion check, and replay now use the same receipt-bound producer ordering. If this switchboard moves into a product runtime, carry producer ordinals on that runtime's candidate type and reuse `rdc-runtime-contracts-v1` at its serialization and resume boundaries. Keep E009/E010/E011 source artifacts unchanged, do not tune the frozen observer, and do not use hash order as the candidate policy.
