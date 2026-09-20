# AR-00F — Grouping Causality

AR-00F tests which property of groupwise planning matters under the same XOR
MLP and exact finite-effect action vocabulary.

- F0: E0 global singleton control.
- F1: sixteen fixed random partitions with E2 group sizes.
- F2: deterministic local-search anti-topology partition minimizing frozen INT1 interaction mass.
- F3: deterministic local-search topology-max partition maximizing frozen INT1 interaction mass.
- F4: fresh random partition at every planning cycle.
- F5: structural group schedule with independent singleton scoring.
- F6: structural group schedule with exact compound scoring.
- W1-W4: matched random planning-width sweep for group sizes 1 through 4.

All group programs use the same 17-primitive budget per outer epoch. F5 and F6
share structural groups, commit cost, and refresh cadence; only utility scoring
differs. The width sweep is intentionally capped at four dimensions to keep
the tiny sandbox bounded while retaining the expensive exact enumeration.

This is engineering-only evidence. It does not establish a general optimizer
claim or any biological correspondence.
