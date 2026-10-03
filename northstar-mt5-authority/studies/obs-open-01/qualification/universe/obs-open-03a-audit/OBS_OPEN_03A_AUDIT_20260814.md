# OBS-OPEN-03A - Observer Geometry and Inferential Resolution Audit

Parent discovery root: `7300a6cbe7bc29696a6a06b2c3e767c142ceb50abb66bf049b7d7ff05adf1273`

Status: `SEALED_PRODUCTS_ONLY / CONFIRMATION_UNOPENED`

## Estimand geometry

- `OBSERVER_IMPLIED`: 0 formal estimands. The formal values are not completely
  fixed by the observer, although several relations among them are.
- `OBSERVER_CONSTRAINED`: 59 estimands.
- `EMPIRICAL`: 60 estimands.

All 29 adjacent width-delta estimands are observer-constrained: nesting forces
their sign domain to be nonnegative, while zero frequency and magnitude remain
empirical. All 30 signed-displacement estimands are observer-constrained by the
completed-M5 clock. They collapse into six five-scale path-start groups, leaving
24 observer-implied duplicate test instances. The 30 first-outside-side and 30
location-balance estimands remain empirical under their declared eligibility
and bounded-domain contracts.

## Observer invariants

The sealed corpus exactly satisfies the derived nested-range invariants:

- range high is nondecreasing, range low is nonincreasing, and width is
  nondecreasing across k;
- adjacent width delta cannot be negative;
- completed-M5 eligibility aliases k into six path-start groups;
- terminal location can enter the expanding zone at most once and cannot leave
  it or cross to the opposite outside side as k increases;
- absence of an outside close is monotone under expanding nested boundaries and
  shortening observation horizons.

Therefore the previously observed terminal persistence is partly imposed by the
observer. The empirical residue is the split: 190
sessions never changed terminal location and 67
changed once across R01-R30.

## Inferential resolution

For 119 tests at alpha 0.05, the first Holm threshold is
`0.0004201680672268908`. With 2,000 two-sided plus-one bootstrap
resamples, minimum p is `0.0009995002498750624` and cannot
reach that threshold.

`B_min = 4759`
is recorded only as the arithmetic floor required to touch the first Holm
boundary. It is not an operational recommendation or a selected future
resample count. Any later count must be chosen prospectively from an explicit
numerical-precision criterion in a new post-discovery exploratory protocol.

No OBS-OPEN-03 decision was changed. No confirmation claim was created. The 69
confirmation sessions remain `FROZEN_UNOPENED`.
