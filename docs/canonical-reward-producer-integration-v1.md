# Canonical Reward Producer Integration v1

Status: implemented.

## Contract

The Overgraph `GraphTruthCommit` append is the authority boundary. A commit becomes eligible for
reward production only when its immutable header carries both:

```text
native decision receipt ID
operator-mutation receipt ID bound to the chosen outcome
```

Commits without that exact two-receipt join remain ordinary graph truth and pay only a constant
receipt-count check. The producer does not infer labels from target IDs, timestamps, review state,
operator journals, or current graph contents.

After the graph-truth append is durable, and before optional checkpoint work, the store:

1. reloads the decision and latest chosen outcome;
2. verifies that the commit carries the outcome's operator-mutation evidence;
3. derives the exact BLAKE3 decision-to-truth link;
4. appends a content-addressed human-evaluation evidence receipt;
5. appends the `human_acceptance = +1_000_000` reward observation referencing that evidence.

Identical retries are no-ops. A crash after graph truth but before either derived receipt is repaired
by the boot reconciler from the same immutable inputs.

## Durable evidence

Reward evidence is record kind 4 in the mmap-backed native decision log. Each record freezes:

- decision, chosen action, truth-link, and graph-truth identities;
- reward dimension and fixed-point score;
- observation and stability-cutoff times;
- authority class, authority identity, and producer policy;
- graph lineage generation;
- exact source receipt identities.

The record header contains a BLAKE3 payload checksum. Restart decoding revalidates both the payload
contract and content identity before the evidence can be used.

## Future-stability observer

The v1 policy horizon is exactly 24 hours and is part of the evidence identity. At native runtime
boot, the observer repairs incomplete human production, scans pending links, and schedules the next
eligible cutoff. When no horizon is pending, the desktop performs a five-minute discovery poll so a
new canonical decision can install its exact wakeup without a long-lived native store lock.

The observer evaluates a frozen graph-truth lineage containing only commits whose `committedAt` is
at or before the stability cutoff:

```text
linked commit has no supersede, retract, or revert resolver at cutoff -> +1_000_000
linked commit has a resolver at cutoff                                -> -1_000_000
```

The evidence and observation are timestamped at the exact cutoff, not the later wake time. Delayed
wakeups therefore reproduce the same IDs, score, and certificate. A positive result proves semantic
survival in canonical lineage; it is not a durable-file-presence test.

## Failure shields

- A recognized decision receipt without the operator receipt fails after the canonical commit and
  is repaired or rejected visibly on retry; it never manufactures reward.
- Evidence is durable before its observation. The observer repairs either half of an interrupted
  append without duplication.
- Only `operator_preference` can produce human acceptance.
- Only `authoritative_graph_outcome` can produce future stability.
- Unsupported reward dimensions remain censored.
- No historical operator journals or graph commits are backfilled unless they already contain the
  exact native decision and operator-mutation receipt join.

## Verification gates

The integration tests prove:

- canonical append immediately emits one human evidence receipt and one observation;
- mmap restart retains and revalidates both;
- an unreversed commit scores stable at the frozen horizon;
- a pre-horizon retract scores unstable and names the resolving commit;
- observer retry and cold restart append no duplicates;
- commits without the two-receipt authority join do not enter the producer path.
