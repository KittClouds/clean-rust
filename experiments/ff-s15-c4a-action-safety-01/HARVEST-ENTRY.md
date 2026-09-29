# Harvest entry — C4a (draft; no Harvest location was found in the repo)

**FINDING**
The cheap tier's applicability boundary is real, sharp, and already implicit: it executes NOOP and essentially nothing else. On the primary surface C1's frozen rule executes 735 NOOP, 31 MOVE and 2 ACTIVATE, correctly executing 25.9% of truth-NOOP rows and 0.9% of truth MOVE/ACTIVATE rows.
At the same threshold harm is 3.8% (NOOP), 22.7% (MOVE), 67% (ACTIVATE); NOOP's top-200 candidates are 0% harmful, MOVE's and ACTIVATE's top-25 are at least 20% harmful on every surface. Perfect per-action thresholds would add only +7.3% (3% harm) and +7.6% (5%), under the 10% bar and inside the noise band; they add +30% only at 10% harm.

**ENGINEERING PRINCIPLE**
A finding that the unconditional assumption is false (harm differs by action) is not the same as a finding that acting on it helps. Ask what the existing rule already does: a single confidence threshold had already excluded the dangerous actions, leaving nothing to reallocate.
Also: read a coverage number by *what* it covers. "Correct executions" that are 96% "do nothing" is a different capability from acting.

**RECIPE**
Break every coverage/harm figure down by the type of action; take the exact oracle for group-specific thresholds (dynamic programming, brute-force-verified) with a shuffled-label noise band; look at each group's top-k harm to see whether any confidence is safe.

**KNOWN COST**
CAL only and in-sample, which favours the oracle and so strengthens the null. The post-hoc tables were added after the conditional-harm table was read.

**DO NOT CLAIM**
That MOVE and ACTIVATE could not be made safe by a different observer (only that these observers cannot separate safe from unsafe among them), or anything confirmatory.

**PRODUCT CONSEQUENCE**
Do not build C4b. Re-read C1's coverage as a NOOP detector. For the economics rung: every real action (about half of ACT rows) escalates at any harm target near 5%; the larger tier must handle all of them, and the cheap tier saves only the "do nothing" decisions.
The missing capability is upstream: an observer that can tell safe from unsafe MOVE/ACTIVATE proposals.

Evidence: `results/c4a-census.json`, `RESULTS.md`, plan `PLAN.md`.
