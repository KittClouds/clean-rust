# OBS-OPEN-01 — Opening-Range Observatory

OBS-OPEN-01 is a bounded observational study of US30 around the New York cash
open. It has no economic or trading authority.

The study begins with qualification. No substantive result may be admitted
until the observer, clock mapping, source coverage, and deterministic replay
contracts pass their gates.

## Authority layers

1. `instrument/` archives the exact MQL5 source and compiled candidates.
2. `protocol/` freezes the observational and clock contracts.
3. `qualification/` contains machine receipts and the qualification matrix.
4. Future raw observations live outside Git on `D:` and are referenced by
   logical and physical hashes. Git contains manifests, schemas, and compact
   receipts only.

## Governing constraints

- The opening family is the complete peer set `R01` through `R30`.
- M1 bars author opening-range geometry.
- Completed candles of the admitted interaction timeframe author interaction
  grammar.
- No final geometry is available before its range freeze time.
- New York civil time is mapped to source time by a sealed, session-specific
  clock receipt. Ambiguous sessions are `NOT_EVALUABLE`.
- Typed absence, censoring, unavailable observation, and continuity failures
  never become ordinary zero or false values.
- Nested ranges and repeated observations within a session are dependent.
- No financial, account, order, position, execution, or profitability data is
  admitted.

Current status: **DISCOVERY EXECUTED — CONFIRMATION UNOPENED**.

The live clock receipt and independently timestamped bounded parity fixture agree
that 09:30 New York mapped to 16:30 source time for 2026-08-13/14. This is not
winter or DST-transition authority. Frozen-observer black-box parity passes
against the independent oracle for all R01-R30 buffers (8,280 rows, 140,760
cells, zero mismatches), and the repeated tester run is byte-identical.

The source- and clock-qualified universe contains 326 admitted sessions: 257 in
the discovery block and 69 in the untouched confirmation block. The confirmation
block remains `FROZEN_UNOPENED`; no opening-range behavior was inspected during
qualification. Large source artifacts remain local on `D:`. See
`qualification/OBS_OPEN_01_UNIVERSE_QUALIFICATION_CHECKPOINT_20260814.md` and
`qualification/universe/seal/universe_qualification_root_receipt.json`.

OBS-OPEN-02 has now frozen the discovery measurement protocol, representation
views, session-level uncertainty contract, multiplicity rules, candidate schema,
and confirmation firewall. Its protocol root is recorded at
`qualification/universe/obs-open-02-seal/obs_open_02_protocol_root_receipt.json`.
The 257-session discovery population remains unopened until OBS-OPEN-03.

OBS-OPEN-03 was then halted cleanly before substantive execution because the
named familywise discovery rule had no executable semantics. OBS-OPEN-02R1 is a
narrow protocol repair: it freezes 119 formal estimands, one Holm–Bonferroni
family at alpha 0.05, session-block bootstrap semantics, pre-data support floors,
temporal-status rules, candidate precedence, and exhaustive rejection codes.
R1 uses synthetic/adversarial fixtures only; discovery and confirmation remain
`FROZEN_UNOPENED`. Its repair root is recorded at
`qualification/universe/obs-open-02r1-seal/obs_open_02r1_repair_root_receipt.json`.
OBS-OPEN-03 has not been re-executed.

The subsequent OBS-OPEN-03 authority preflight stopped again before producing
any census or formal result. It found five remaining executable-semantics gaps:
descriptive formulas, complete estimand eligibility records, exact temporal-view
construction, a confirmation-estimand emitter, and exhaustive rejection
transitions. Confirmation remains `FROZEN_UNOPENED`; the machine receipt is at
`qualification/universe/obs-open-03-preflight/obs_open_03_preflight_receipt.json`.

OBS-OPEN-02R2 closes those five gaps without opening substantive discovery. It
also adds an outcome-blind discovery-source quality census: all 257 discovery
sessions pass authoritative M1 opening and M5 interaction-horizon coverage,
timestamp/order/price invariants pass, and 20,275 available M1-to-M5 OHLC
reconciliations have zero mismatches. The 28 unavailable parity comparisons are
retained explicitly as `PARITY_NOT_EVALUABLE_NONAUTHORITATIVE_M1_SUFFIX` rather
than converted into failures or zeros. The bounded reader requested zero
confirmation rows. Two independent R2 seal builds are byte-identical. The R2
root is recorded at
`qualification/universe/obs-open-02r2-seal/obs_open_02r2_root_receipt.json`.
At the R2 checkpoint, OBS-OPEN-03 had not yet been re-executed after the
preflight abort.

OBS-OPEN-03 has now been restarted under the R2 authority and executed twice
over exactly the frozen 257-session discovery population. Both complete builds
are byte-identical. The sealed discovery contains 7,710 range objects, 574,395
interaction rows, 7,453 adjacent-scale relations, 324 contiguous terminal
spans, and explicit terminal states for all 119 formal estimands.

The frozen decision contract promoted zero candidates: 89 estimands are
`DESCRIPTIVE_ONLY` and 30 are `INSUFFICIENT_SUPPORT`. This is not a supported
null result. With 2,000 plus-one-corrected two-sided bootstrap resamples, the
minimum attainable p-value is larger than the first Holm threshold across 119
tests, so the frozen protocol cannot promote a candidate. That limitation is
preserved rather than repaired after observation.

The 69-session confirmation population remains `FROZEN_UNOPENED`; zero
confirmation rows were read and no confirmation estimand was authorized. Large
discovery ledgers remain local on `D:`. Compact receipts and the complete
30-scale descriptive summary are under
`qualification/universe/obs-open-03-discovery/`. The discovery root is
`7300a6cbe7bc29696a6a06b2c3e767c142ceb50abb66bf049b7d7ff05adf1273`.

## OBS-OPEN-03A observer-geometry audit

OBS-OPEN-03A audits the sealed discovery products without reading raw source
observations or confirmation. It classifies all 119 formal estimands by the
degrees of freedom left by the observer: 59 are `OBSERVER_CONSTRAINED` and 60
are `EMPIRICAL`; no formal numerical value is completely
`OBSERVER_IMPLIED`. Observer-implied relations are recorded separately.

The nested-range and completed-M5 clock invariants pass exactly. In particular,
the 30 signed-displacement estimands occupy six five-scale path-start alias
groups, leaving 24 observer-implied duplicate test instances. The original
119-test multiplicity family and all OBS-OPEN-03 decisions remain unchanged.

The arithmetic value `B_min = 4759` is sealed only as the minimum two-sided
plus-one bootstrap count capable of touching the first Holm boundary. It is
not a selected future resample count. Any later exploratory inference contract
must choose numerical resolution prospectively from an explicit precision
criterion. Confirmation remains `FROZEN_UNOPENED`. The OBS-OPEN-03A root is
`db9ffaf084b7ed6604599f0f4c1f47520646e213f9145272d41d851d73def5fc`.
