# Canonical Episode Assignment Inbox v1

Status: implemented.

## Purpose

Atlas Control now exposes a real chronological decision inbox for Canonical Episode Assignment.
It does not auto-accept the continuity compiler. The operator must explicitly choose one frozen
action from the decision-time candidate universe.

## Choices

For every candidate-only continuity event, the inbox offers:

1. Attach to any active compatible same-note episode.
2. Create a deterministic canonical episode rooted at the event.
3. Abstain because the available evidence is insufficient.

The compiler proposal is marked, not pre-applied. Selecting a different compatible episode is a
first-class override. `create_episode` asserts the new episode, event, and membership in one
GraphTruthCommit. `abstain` appends the immutable decision and no-change outcome but deliberately
creates no graph commit or invented future-stability label.

## Identity and failure shields

- Decision identity binds the immutable pre-state, event, scope, and operator, not the selected
  answer.
- A second answer for the same decision identity fails closed.
- Every candidate action is frozen before the chosen ordinal is written.
- Candidate-only topology cannot enter asserted truth without the operator outcome.
- Conflicting active event membership fails before a second behavior label is appended.
- Repeated clicks are locally suppressed; cold retries remain native-idempotent.
- No history is backfilled and no abstention is disguised as a graph mutation.

## Maturity dashboard

The Atlas header reconciles the canonical reward observer before reading its two censuses. It shows:

```text
episode decisions
attach / create / abstain counts
fully mature lineages
positive / revised future stability
pending 24-hour horizons
next eligible horizon
10 / 100 / 1000 count gates
```

The count gates are necessary but insufficient. Chronological span, action-family support,
candidate coverage, lineage grouping, and leakage certification remain dataset-installation gates.

The app does not need to remain open for 24 hours. The observer schedules the next live deadline and
reconciles missed deadlines on the next native boot or dashboard refresh.

## Accumulation protocol

1. Produce or edit real notes and build their graph snapshots.
2. Open Atlas Control, select Continuity, then Assignment inbox.
3. Inspect source evidence and explicitly choose the authoritative action.
4. Allow normal later corrections to become genuine negative future-stability outcomes.
5. Refresh the census after horizons mature.

Do not mass-accept, synthesize decisions, or optimize action balance by choosing incorrect answers.
Action imbalance is evidence about the live task and must remain visible.
