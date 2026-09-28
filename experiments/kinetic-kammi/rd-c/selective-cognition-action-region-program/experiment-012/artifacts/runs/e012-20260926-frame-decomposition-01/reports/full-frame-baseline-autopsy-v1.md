# E012 full-frame baseline autopsy

## Result

- Samples: 48 across 20 pair groups, 12 families, and 3 repositories.
- Small observer: 16/48 accepted; 6/48 completed; 10 wrong legal actions.
- Large only: 23/48 completed.
- Hybrid replay: 22/48 completed with 32 large fallbacks.
- Admission gate: **FAIL** (requires nonzero small coverage and zero wrong accepted small actions).

## Paired lanes by repository

| Repository | Small accepted | Small completed | Small wrong | Large completion | Hybrid completion | Hybrid large calls |
|---|---:|---:|---:|---:|---:|---:|
| repo-01 | 7/16 | 4/16 | 3 | 10/16 | 10/16 | 9 |
| repo-02 | 7/16 | 1/16 | 6 | 6/16 | 6/16 | 9 |
| repo-03 | 2/16 | 1/16 | 1 | 7/16 | 6/16 | 14 |

## Error checks

- Sealed valid-action sets versus executable candidate checks: 0 mismatches across 48 samples.
- Small and large output normalization errors: 0 and 0.
- Receipt/replay checks clean on all lane executions: 48/48 sample triplets and 48/48.
- Authority recorded zero illegal commits and zero duplicate effects in 144 lane replays.

The scoring path is internally consistent. All ten wrong small actions selected offered candidates whose sealed expected-valid set and executable checks both reject them.

## Observable decision shape

All 16 accepted small actions had applicability 1000/1000 and abstention 0/1000. Within the accepted region, those scores did not separate correct from wrong actions: 6 completed and 10 failed. The 32 other small outputs were rejected or abstained; see the task-level JSON for their decision reasons.

Among 48 samples, small and large both completed 4; small alone completed 2; large alone completed 19; neither completed 23. The hybrid therefore completed 22, one fewer than large only. Small direct errors and accepted coverage are reported per family and stratum in the JSON.

## Decision

The frozen v5 small observer does not earn admission to E012 channel interventions on this bank. The failure is not a receipt, normalization, authority, or label-mapping defect. Preserve this baseline; do not fit thresholds or carve a post-hoc subgroup from these same outputs. Any next experiment needs a separate preregistered question or a prospectively repaired observer/task interface.

This remains a 48-sample paired synthetic coding bank with three repositories. It does not establish why v5 failed here or make a broad claim about coding workflows.

Detailed task, family, stratum, score, position, pairing, and invariant data are in full-frame-baseline-autopsy-v1.json.
