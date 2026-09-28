# E012 Bank Amendment A13 — Unified-Diff Encoding Repair

**State:** engineering correction to the unscored A12 retry; no observer or model contact.

## Finding

Scored-check attempt 01 stopped before writing candidate results. The `map-order-feature-contract/canonical_sort` repair rewrote a unified-diff context line in place, so the runner correctly rejected the patch against the frozen source. The recorded failure is retained at `bank/construction-01/scored-bank-a12/attempts/scored-check-attempt-01.json`; the A12 source, design lock, runner lock, scripts, and partial D: build cache remain unchanged.

## Correction

A13 preserves the planned candidate behavior: the canonical-sort distractor omits the first map key. Its patch now encodes that edit as one removed line and one added line, with matching unified-diff hunk counts. The help-color repair, task bank, labels, assignment rule, and runtime contract are unchanged. This repairs patch representation only; it does not reinterpret any scored outcome because attempt 01 produced none.

## Execution boundary

Create a new precheck source, design lock, runner, and scored-check lock. Validate every candidate patch against its frozen source before running checks. Preserve A12 artifacts and attempt 01. Model contact remains prohibited pending the complete E012 precontact audit and a new model-contact lock.
