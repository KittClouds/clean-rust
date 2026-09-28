# E005 baseline and authority contract

Experiment 005 is isolated under `C:\rd-c\experiment-005`. It depends on the frozen E001/E002 runtime and the E004 route planner by local path. It does not edit E001, E002, E003, E004, Phoenix, Northstar, or research branches.

## Authority boundary

The E002 compiled authority still owns workflow state and legal transitions. The E005 public observation adds a context bucket for development-set routing, while source recommendations, source-reported revisions, age, warning bits, and confidence remain visible as in E004. The inspection result is a separate typed value loaded from a pre-run source-state fixture. The resolver can use its recommendation but cannot name a state or bypass the decision compiler.

The inspection result has no correct-action label and no revision. The label writer is a separate module. The runtime schema contains no trusted task revision, and no revision guard is added. This experiment therefore makes no claim that an inspected action is authoritative or that the state machine rejects stale evidence.

## Frozen comparisons

All four lanes receive the same 256 held-out episodes, observer pair, workflow, action simulator, journal policy, and budgets `16, 32, 48, 64`. Each routed episode receives exactly one inspection query and one resolver call. The E004 lane preserves the E004 combined selection rule and its public-frame resolver; it discards the new result after receipt so that it remains a routing baseline.

The development value model is fitted only on a disjoint development set and uses only the public inspection-domain key at routing time. The offline oracle is constructed after held-out labels are written. Its selection plan is retained under `evaluation/` and is an upper bound, not an executable policy.

## Provenance and replay

The two public banks and the two source-state fixtures are written before runtime scoring. Held-out route plans are persisted before held-out labels are generated. Each inspection result is stored in a durable, versioned, hash-chained receipt journal. A post-run mmap replay validates every receipt hash and checks each returned payload against the pre-run source fixture. Each task is separately replayed through E002 and compared by state, transition-receipt hashes, and replay identity.
