# OBS-OPEN-01 — coverage, clock transport, and universe qualification checkpoint

Status: `QUALIFIED`

Substantive observer results: `FROZEN_UNOPENED`

## What was qualified

- The outcome-blind MT5 collector emitted 650,380 M1 rows and 130,206 M5 rows for the requested 2024–2025 interval.
- The bar authority is 93,138,485 bytes with SHA-256 `125b768ad87ba578c5498deffe50462909a6a1be422953a0f7488f036aac9d5b`.
- Fifteen required external clock anchors passed the frozen alignment thresholds and matched the preregistered server-offset model.
- Both 2024 and 2025 spring transitions were observed at UTC+02:00 before the European switch and UTC+03:00 after it.
- The 2025 autumn transition was observed at UTC+03:00 before the European switch and UTC+02:00 after it.
- The unresolved 2024 autumn/post-autumn interval was excluded rather than inferred.

## Outcome-blind universe result

| Item | Count |
|---|---:|
| Candidate civil dates | 730 |
| Admitted sessions | 326 |
| Discovery sessions | 257 |
| Untouched confirmation sessions | 69 |
| Supported discovery months | 16 |
| Supported confirmation months | 4 |

Both partitions contain both qualified server-offset regimes.

Exclusion counts are preserved in the machine census:

- 208 weekends;
- 20 exchange closures;
- 6 early-close horizons;
- 43 unresolved-clock dates;
- 48 primary M1 coverage failures;
- 79 primary M5 coverage failures.

The complete census retains both M1 and M5 missing/duplicate counts even when only one primary exclusion reason is displayed.

## Reconstruction proof

Two independent derivations from the same frozen local authority produced byte-identical:

- clock transport matrix and receipt;
- local raw authority manifest and verification receipt;
- source acquisition excerpt and receipt;
- session coverage census;
- admitted and excluded session ledgers;
- frozen partition manifest;
- universe qualification receipt.

Large source artifacts and external BI5 fixtures remain on `D:` and are not admitted to Git.

## Epistemic limit

This checkpoint establishes a causally timed, source-qualified, multi-session study universe and an untouched confirmation drawer. It says nothing about opening-range widths, locations, events, persistence, excursions, directions, scale relations, trajectories, regularities, or economic consequences.

The telescope is qualified. The drawer exists. It remains closed.
