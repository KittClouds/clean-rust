# RG2 lifecycle semantics audit

Scope: **Phase 9 exit gate, before Phase 10**

Verdict: **RG2_ADMISSIBLE_FOR_PHASE10_ATTEMPT_LEVEL_ANALYSIS_ONLY**

Reason: behavioral attempts are usable, but NODE_RETIRED is a first-absence administrative termination and episode.resolution is not a whole-episode outcome.

## Authoritative code semantics

- A stable node retires after three unmatched structural rebuilds.
- An active attempt becomes `NODE_RETIRED` as soon as its exact stable node ID is absent from the current candidate array, before the tracker retirement gate.
- An attempt becomes `TIMEOUT` only when closed-bar span is greater than 24; RG2 receipts should therefore close at 25 bars.
- An episode closes after the 12-bar gap and retains the resolution of its last completed attempt.

## NODE_RETIRED trace

- Resolved `NODE_RETIRED` attempts: 889
- Episode chains containing one: 879
- Episodes whose terminal receipt is `NODE_RETIRED`: 853
- Chains later closed by another outcome or censor: 26
- Explicit merge/split lineage during the three-miss grace: 21
- Tracker-compatible node created during the grace: 6
- Either continuity receipt: 27 (3.2%)
- Tracker retirement receipt eventually present: 852 (99.9%)
- Attempt ended before tracker retirement: 787 (92.3%)
- Same stable ID reappeared after attempt termination: 6 (0.7%)
- Median last-seen to retirement: 68 seconds
- Median attempt-start to retirement: 594 seconds
- Median attempt-end to tracker-retirement receipt: 18 seconds

The compatible-node test reproduces the tracker geometry and family-mask gates. Its ATR is recovered from the retirement rebuild snapshot; it is an audit reconstruction, while merge/split rows are authoritative lineage receipts.

## TIMEOUT trace

- Resolved timeout attempts: 553
- Episodes terminated by attempt timeout: 383
- Episodes terminated by transit timeout: 12
- Every timeout attempt ended at exactly 25 bars: True
- Every timeout transit ended at exactly 49 bars: True
- Median timeout-attempt duration: 7404 seconds
- Median attempts in terminal timeout episodes: 6

Terminal phases:

- APPROACH_NO_CONTACT: 331
- BROKEN_NO_ACCEPTANCE: 4
- PENETRATED_NO_RESOLUTION: 48

## Episode-label finding

- Episodes ending in `NODE_RETIRED` or `TIMEOUT`: 1248
- Those containing an earlier behavioral attempt: 719 (57.6%)

`episode.resolution` is therefore a terminal attempt-or-transit label. It must not be interpreted as a summary of the complete attempt chain.

## Phase 10 gate

RG2 can enter Phase 10 for attempt-level behavioral analysis. `NODE_RETIRED` must be treated as structural administrative censoring, attempt and transit timeouts must stay separate, and episode resolution cannot serve as a whole-episode target. Changing runtime semantics would start a new research generation; this audit does not require that change before descriptive work begins.
