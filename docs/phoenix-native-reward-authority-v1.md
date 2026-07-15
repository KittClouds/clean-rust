# Phoenix Native Reward Authority v1

## Status

Decision-to-GraphTruthCommit authority linking and the canonical reward producer are implemented.
Reward completion remains fail-closed: human and future-stability evidence still do not complete
the other six reward dimensions.

## Immutable authority seam

The existing `GraphTruthCommitHeader.receipt_ids` collection is the canonical
carrier. A commit linked to an Atlas Control decision must contain both:

```text
native decision receipt ID
durable operator-mutation receipt ID
```

The native link certifier independently loads the decision, chosen application
outcome, and graph-truth commit from the same Overgraph store. It rejects:

- a missing decision, outcome, or commit;
- a mutation receipt absent from the chosen outcome;
- a commit missing either authority receipt;
- a commit before the decision or application;
- a commit later than the claimed link time;
- a zero stability horizon or timestamp overflow.

The returned link is content-addressed and records the first time at which a
future-stability observation may become eligible. It always reports
`rewardComplete: false` because the link alone does not prove temporal
consistency, identity preservation, contradiction reduction, human acceptance,
future stability, or abstention correctness.

## Desktop surface

`link_native_operator_decision_graph_truth_json` exposes the certifier through
the typed desktop bridge. It is intended to be called by a real canonical commit
producer after that producer has written both authority receipt IDs into the
commit. It does not create or modify graph truth. The Overgraph append hook now performs the same
certification automatically for commits carrying the exact two-receipt join and emits the
human-evaluation evidence immediately after durability.

The native decision census now reports `graphTruthLinkedDecisions`. The count
requires the same two-receipt join and therefore cannot rise from timestamp or
target-ID coincidence.

## Observation layer

Per-dimension observations are now implemented by
[Native Reward Observation v1](phoenix-native-reward-observation-v1.md).
Human acceptance and future stability bind the truth-link identity, evidence,
authority, and observation time. Unavailable dimensions remain pending. A
complete `Revise` outcome may be appended only when all eight dimensions are
independently observed.

Unchosen alternatives remain censored unless they receive independent
adjudication or deterministic replay authority. The chosen commit is never
reused as evidence for a counterfactual action.
