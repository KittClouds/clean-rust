# E012 Raw Proposal Yield v1.0

State: `READ_ONLY_DESCRIPTIVE_RECOUNT`  
Source: `e012-20260926-frame-decomposition-01`  
Model contact: **none**  
Fitting or threshold search: **none**  
Source run modified: **no**

This addendum reads the sealed small-observer authorization inputs and the post-inference evaluation labels to separate raw proposal yield from legacy runtime acceptance. It does not edit or supersede the E012 run, E012 anatomy v1.1, or any E012 result.

## Raw small-proposal outcomes

| E012 task stratum | Tasks | Correct raw proposal | Wrong raw proposal | No raw proposal | v5 accepted | Accepted correct / wrong |
|---|---:|---:|---:|---:|---:|---:|
| All tasks | 48 | 7 | 11 | 30 | 16 | 6 / 10 |
| Candidate-selection tasks | 40 | 7 | 9 | 24 | 14 | 6 / 8 |
| Empty-valid-set tasks | 8 | 0 | 2 | 6 | 2 | 0 / 2 |

Across all 48 tasks, raw correct-proposal yield is `c = 7/48 = 14.58%`; raw wrong-proposal yield is `11/48 = 22.92%`; no-proposal rate is `30/48 = 62.50%`. Conditional raw precision among the 18 non-null proposals is `7/18 = 38.89%`.

The old v5 rectangle accepted 16 of the 18 non-null proposals: it rejected one correct proposal and one wrong proposal. The accepted-action position breakdown remains descriptive: 6 of the 10 wrong accepted small actions used producer ordinal 1. No position rule is inferred.

The empty-valid-set cases are kept separate: two of eight received a raw candidate proposal, and both were wrong because no offered action was valid. A null action choice is recorded as `NO_PROPOSAL`; it is not counted as a wrong proposal and cannot be rescued by a downstream trust signal.

## Reproduction and integrity

Run `analyze_e012_raw_proposal_yield.py` to regenerate the JSON recount. The script asserts 48 sealed task labels and 48 small authorization inputs, verifies every chosen action belongs to its receipt-bound presentation, hashes every read authorization input, and writes only `E012-RAW-PROPOSAL-YIELD-v1.0.json` in this addendum directory.

The JSON binds the frozen E012 input lock, baseline report, evaluation labels, and each small authorization input by SHA-256. No model or API was contacted.
