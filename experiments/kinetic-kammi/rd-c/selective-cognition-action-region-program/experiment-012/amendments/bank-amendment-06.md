# E012 bank amendment A06 — empty no-op patch handling

**State:** runner repair frozen; scored candidate checks remain in progress. **Model contact remains prohibited.**

Scored-check attempt 01 stopped in the harness applier before producing any candidate result file. It encountered an empty candidate patch and rejected it during header validation. The empty file is a declared no-op in the frozen feasibility bank, so the runner must treat it as an unchanged source overlay.

The failed attempt is preserved at `bank/construction-01/scored-bank-v1/attempts/scored-check-attempt-01.json`, including the lock and fixture hashes. No task outcome or candidate label was recorded, and no source fixture was selected or changed because of the failure.

Runner v1.1 recognizes an empty patch before checking unified-diff headers. Nonempty patches retain the same target-path and hunk validation. The executable test predicate, expected action sets, candidate order, tests, and bank membership are unchanged. The corrected runner receives its own scored-check lock and writes the same planned `candidate-check-results.json` only after all isolated checks finish.
