# AR-00G — Temporal Coverage

G freezes exact compound group scoring and varies only the temporary planning
relationship sequence:

- G0: dynamic-random parity control;
- G1: deterministic round-robin coverage schedule;
- G2: low-coverage dynamic schedule using a recurring partition pool;
- G3: no-repeat schedule that greedily chooses uncovered pair relationships;
- G4: dynamic schedule that forbids the strongest frozen INT1 pairs;
- G5: current-state topology refresh every 100 outer epochs.

Every arm uses the same four size-3 groups plus five singleton groups and the
same 17-primitive budget per outer epoch. Coverage telemetry counts pairs that
were jointly evaluated in a planning block, not only pairs ultimately chosen.

This is engineering-only evidence. It does not establish a general optimizer
claim or any biological correspondence.
