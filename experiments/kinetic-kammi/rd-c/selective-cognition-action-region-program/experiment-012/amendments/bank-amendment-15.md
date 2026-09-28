# E012 Audit Amendment A15 — Match the Audit to the Frozen Channels

**State:** audit-only correction over the A14 bank; no task, label, model, or runtime changes.

## Finding

The A14 paired audit reported one failing 2×2 family and producer-order mismatches in coordinate-control frames. Direct inspection confirmed the bank has all four distinct `E_t × E_x` visible combinations, every single-factor contrast changes the executable valid-action IDs, and all 1,248 receipt sequences exactly match their frames. The audit had interpreted two legacy hidden bit names as channel names even though their visible effects are reversed, and had compared intentional `E_p` control/donor conditions to the baseline producer order.

## Correction

A15 derives factorial cells from the actual request and execution evidence values. For each frame it checks the hidden internal task ID maps to the public presentation ID, verifies the receipt binds the exact ordered action IDs, and checks the producer sequence except in the two declared `E_p` conditions. Those conditions are checked against their locked control or isomorphic-donor sequence. The A14 audit result remains preserved as a failed diagnostic artifact.

No task source, candidate patch, test result, frame, receipt, observer, threshold, or authority input changes. A15 only repairs audit interpretation.
