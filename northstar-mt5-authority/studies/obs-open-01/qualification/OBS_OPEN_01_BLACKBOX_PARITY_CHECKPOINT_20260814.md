# OBS-OPEN-01 Black-Box Parity Checkpoint - 2026-08-14

## Bounded outcome

The frozen `OpeningRangeGrammar_v1_02_FullState` observer and the independent
Python oracle agree exactly for the admitted `US30` session on `2026-08-13`.

- peer intervals: `R01` through `R30`;
- admitted M5 rows: `8,280`;
- compared observer cells: `140,760`;
- missing actual keys: `0`;
- unexpected actual keys: `0`;
- mismatched cells: `0`;
- collector copy failures: `0`;
- explicit cutoff-finalized rows: `30`.

The compact machine receipt is
`qualification/parity/blackbox_parity_receipt.json`, logical SHA-256
`71bee2f6ceaa96de16c26dcbda94cc6c5bf87ceecac64388d0b969250fbbf3ea`.
The two complete raw run directories remain local-only on `D:` and are bound by
`qualification/coverage/local_raw_artifact_manifest.json`.

## Replay determinism

The same bounded headless Strategy Tester run was executed twice. These four
artifacts were byte-identical between runs:

- raw 17-buffer ledger;
- terminal run receipt;
- mismatch ledger;
- parity comparison receipt.

The raw buffer ledger SHA-256 is
`72af5bf7ee1a5ff2d3aafe1b48d06678f628b5a8a9313fdeac96d8c6d1e5d327`.

## MT5 runtime ABI finding

An isolated diagnostic proved that this MT5 runtime includes each MQL5
`input group` heading as a string slot in the custom-indicator parameter ABI.
The observer therefore has 23 runtime slots: 20 visible settings plus three
group-string slots in source order. Omitting those slots shifts later values;
supplying only the 20 visible settings fails with MT5 error `4002`.

The production observer was not modified. The black-box collector was repaired
to supply the exact grouped ABI explicitly. A second collector-only correction
uses a shift-1 `CopyBuffer` readiness probe because subordinate indicators are
evaluated lazily in the tester. A deterministic cutoff finalizes the last fully
bounded M5 bar without admitting a future bar.

## Exact limits

This checkpoint establishes implementation parity and replay determinism for
one bounded session only. It does not establish:

- clock transport to winter or DST-transition sessions;
- coverage outside `2026-08-13`;
- a frozen multi-session discovery/confirmation universe;
- any substantive regularity in opening-range behavior;
- any economic or trading authority.

Substantive results remain `FROZEN_UNOPENED`. Qualification gate Q13 is
`NOT_EVALUABLE_SOURCE_COVERAGE` because the available broker history is not yet
sufficient to freeze a multi-session universe and untouched confirmation blocks.
