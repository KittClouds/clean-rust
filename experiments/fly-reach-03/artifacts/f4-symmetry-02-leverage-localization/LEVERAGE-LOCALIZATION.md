# F4-SYMMETRY-02 Leverage Localization

**Disposition:** exploratory, post-outcome, analysis-only qualification diagnostic on the locked F4-SYMMETRY-01 RUN4 prediction streams. No fits were run.

- Rows: 13420
- Psi C: 0.049689887
- Psi D: 0.446927541
- Delta Psi D-C: 0.397237655
- C/D disagreement rows: 2404 (17.914%)
- Leverage mass on disagreement rows: 20.960%
- D correct on disagreement leverage: 97.381%

Every `delta_psi_global_contribution` below is the subgroup's additive share of pooled D-C DeltaPsi. `delta_psi_local` renormalizes within that subgroup. The row contributions sum to pooled DeltaPsi and are zero outside the C/D disagreement set.

## By block

| Block | Rows | Leverage share | Local DeltaPsi | Pooled contribution | Disagreement leverage | D correct when disagreeing |
|---:|---:|---:|---:|---:|---:|---:|
| 303000 | 3729 | 33.546% | 1.122533 | 0.376569 | 56.133% | 0.9999391928924062 |
| 303001 | 2815 | 7.755% | 0.032224 | 0.002499 | 1.611% | 1.0 |
| 303002 | 5009 | 39.750% | -0.013548 | -0.005385 | 2.075% | 0.3367980339719202 |
| 303003 | 1867 | 18.948% | 0.124316 | 0.023555 | 6.223% | 0.9994311963046231 |

## By pooled quintile and cue-incidence pattern

See `LEVERAGE-LOCALIZATION.csv` for each subgroup's row count, leverage mass, local and pooled DeltaPsi, and C/D disagreement statistics.

## Scope

The bins and decompositions describe these qualification rows only. They do not establish that canonicalization caused a general symmetry effect, that the predictor is usable as a controller, or that a local DeltaPsi improvement changes multi-step trajectory outcomes. No uncertainty interval is computed.
