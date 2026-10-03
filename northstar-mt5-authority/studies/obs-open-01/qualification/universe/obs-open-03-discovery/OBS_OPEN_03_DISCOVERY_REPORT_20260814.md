# OBS-OPEN-03 — Frozen Discovery Report

Parent discovery root: `7300a6cbe7bc29696a6a06b2c3e767c142ceb50abb66bf049b7d7ff05adf1273`

Status: `DISCOVERY_ONLY_UNCONFIRMED`

## Complete surface

- 257 discovery sessions, 7,710 range objects, 574,395 interaction rows.
- 7,453 adjacent-scale relations and 324 contiguous terminal-location spans.
- 119/119 formal estimands reached an explicit terminal state.
- 0 promoted candidates; 0 future confirmation estimands.
- Confirmation remained `FROZEN_UNOPENED` with zero rows read.

## Formal decision result

The frozen family produced 89 `DESCRIPTIVE_ONLY` and 30
`INSUFFICIENT_SUPPORT` terminal states. No estimand passed Holm correction.

The reason is partly a frozen measurement-resolution boundary: 2,000
plus-one-corrected two-sided bootstrap resamples have minimum raw p
`0.0009995002498750624`, above the first 119-test
Holm threshold `0.0004201680672268908`. This makes formal
promotion impossible under the sealed decision contract. It does not erase the
descriptive census, and it is not evidence that the observed surface is null.

## Descriptive observations

- Median range width increases from `49.2` at R01
  to `164.7` at R30. Adjacent increments are zero
  for roughly `0.206`
  to `0.844`
  of sessions depending on k. This is descriptive scale geometry; nested widths
  are non-decreasing by construction.
- First observed outside-side counts remain mixed across all 30 scales. Raw
  family p-values range from `0.23788105947026486`
  to `0.9505247376311844`; none pass unadjusted
  evidence.
- Location-balance raw p-values range from
  `0.0879560219890055` to
  `0.4737631184407796`. All 30 are temporally unstable
  under the frozen robustness rule and none pass unadjusted evidence.
- Signed-path-displacement raw p-values range from
  `0.09195402298850575` to
  `0.19890054972513743`. All 30 are temporally
  unstable and none pass unadjusted evidence.
- Terminal location is unchanged across all R01–R30 boundaries in
  `190`
  of 257 sessions. Adjacent terminal-location survival ranges from
  `0.957` to
  `1.000`.
  This is a descriptive scale-space relation, not a promoted candidate.

The complete 30-row scale summary is retained beside this report. No mechanism,
economic interpretation, or trading authority is claimed.
