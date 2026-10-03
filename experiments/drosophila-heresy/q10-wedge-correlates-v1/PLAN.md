# Q10-WC: Wedge-Width Correlates Descriptive Qualification

Status: `FROZEN_PRE_QUALIFICATION__NOT_EXECUTED`

Document state: `FINAL`

Q10-WC is a disjoint, qualification-only geometry audit. It asks which already-recorded properties of an engineering event are descriptively associated with the width of the local f32-safe alternative-learning wedge produced by the frozen Q10-SM constructor. It makes no behavioral, causal, biological, direction-effect, future-learning-state, or metaplasticity claim.

The user explicitly authorized this qualification lane after the document-only draft. Source creation, target-drive builds, engineering qualification execution, receipts, and independent review are authorized inside this root. Scientific seeds, behavior, causal inference, edits to frozen parent roots, and DH-08B remain unauthorized.

## Frozen Q10-SM lineage

Q10-WC descends from the completed Q10-SM Stage 1 qualification at `experiments/drosophila-heresy/q10-safety-margin-v1`. The following SHA-256 identities were read from the frozen parent files:

| Q10-SM file | SHA-256 |
| --- | --- |
| `CONTRACT.json` | `5A7CD7E15724F6260C2D42296BED5FF3667CA32FA1D8D48E5408EFFA2A0F35BF` |
| `PLAN.md` | `8A70CFADA7A833AA1110FDE5DBF0CFAFDDD4AFD4297A06AD846B1959439B8B9D` |
| `RESULT.md` | `68200D7F49B8A4B943150A1C3A5AB4B46DF4ED8EB1EBBE7A3DF45F8BEEBBD337` |
| `STATUS.json` | `D19D051DA550BCDED9C436F9A7164AF0C4322D8BB16C418D7C4CA9E04217A9C4` |

The required parent status is `Q10_SM_STAGE1_VALID__F32_SAFE_FREEDOM_PRESENT`, with sequential-f32 readout and ULP repair both `NOT_RUN`. The supporting `Q10-SM-SUMMARY.json` identity is `2B64FF590E226CD393EBCFF6A5147728BAC931F395D76970567EBD6061EDA113`.

Q08, Q09, Q10-BG, and Q10-SM are immutable lineage. Q10-WC may reuse Q10-SM event-construction semantics and receipt fields under a future authorization, but it may not edit, regenerate, reinterpret, or replace any frozen parent source, contract, result, status, threshold, seed, or artifact.

## Descriptive question

For valid Q10-SM-style engineering events, how does accepted local wedge width vary with:

- true-endpoint safety slack;
- active-support boundary occupancy;
- active-support size;
- combined nullity;
- endogenous null-energy fraction, when finite parent receipt fields permit it; and
- reversal-event timing?

The question concerns associations among geometry receipts. It does not ask why an association exists, whether changing a predictor would change wedge width, or whether wedge width changes behavior or future learning.

## Fresh engineering population

Only fresh engineering seeds `9701..9705` belong to Q10-WC. Scientific seeds are forbidden.

The frozen event grid is:

```text
seeds: 9701, 9702, 9703, 9704, 9705
sides: R, L
taus: 4, 16
reversal events per side/tau: 256
events per seed: 2 * 2 * 256 = 1024
total engineering events: 5 * 1024 = 5120
scientific seed bundles: 0
```

If later authorized, qualification staging is:

- Stage A: seed `9701`, exactly 1,024 events, to validate receipt parity and the analysis implementation.
- Stage B: seeds `9702..9705`, exactly 4,096 new events, only after Stage A passes without changing this contract.

No top-up, replacement seed, or outcome-dependent extension is allowed. Any change after Stage A requires a new protocol identity and fresh engineering seeds.

## Q10-SM event and receipt reuse

A future Q10-WC implementation must reuse the frozen Q10-SM Stage 1 construction without changing its learner state, task stream, support semantics, linear operator, rank cutoff, 32-ULP reserve, tangent candidate count, constructor key, path-safe search, tolerances, nonidentity rule, f32 commitment, or event-status definitions.

The required parent receipt schema includes at least:

```text
seed, side, tau, trial, status
rotation_angle, residual_cosine
true_minimum_safety_slack
support_count, interior_variable_count, fixed_boundary_count
combined_rank, combined_nullity
true_norm, true_null_norm
candidate_count, degeneracy_count, exhaustion_status
all Q10-SM continuous and committed integrity fields
```

No action, reward, accuracy, probe, margin, decision, behavioral trajectory, sequential-f32 readout, ULP move, or ULP repair field may be emitted or read by this audit.

The analysis must independently verify the exact parent lineage hashes and the complete Q10-SM integrity gates before using any event. A lineage or integrity mismatch invalidates Q10-WC; it is not repaired or silently excluded.

## Analysis populations

Two populations are frozen and must not be conflated.

1. **All analysis-eligible engineering events**: all 5,120 events whose Q10-SM-style construction and receipt integrity pass and whose event status is exactly `Q10_SM_STAGE1_VALID__F32_SAFE_FREEDOM_PRESENT` or `Q10_SM_STAGE1_VALID__SAFETY_MARGIN_DOMINATED`. This population is used only for coverage, status counts, and the accepted-versus-dominated selection audit.
2. **Accepted nonidentity events**: events with parent status `Q10_SM_STAGE1_VALID__F32_SAFE_FREEDOM_PRESENT`, exhaustion status `ACCEPTED`, and `abs(residual_cosine) < 1 - 1e-8`. This population is used for wedge-width association summaries.

Safety-margin-dominated events are not assigned an artificial zero angle for the association analysis. Their exclusion is visible through the separate selection audit.

Any `Q10_SM_STAGE1_INVALID` event invalidates Q10-WC. Any `Q10_SM_STAGE1_VALID__NUMERICALLY_AMBIGUOUS` event stops descriptive interpretation and yields `Q10_WC_NOT_INTERPRETABLE__NUMERICALLY_AMBIGUOUS`; it is not silently removed. Exact coverage means one and only one receipt for every `seed x side x tau x trial` key.

## Canonical width outcome

The canonical width outcome is the accepted path-safe rotation angle:

```text
theta = rotation_angle, with 0 < theta <= pi/2
```

Larger `theta` means a wider locally reachable wedge within the frozen Q10-SM constructor family.

The recorded residual cosine is the paired mirror:

```text
c = abs(residual_cosine)
```

For every accepted event, the audit must verify:

```text
abs(cos(theta) - c) <= 2e-10
```

`theta` is used for all canonical associations because `c` is numerically compressed near one. Associations with `c` and with `1 - c` are reported only as redundant sensitivity diagnostics; they are not additional outcomes or hypothesis tests.

## Frozen descriptive variables

For every event, derive only the following variables from Q10-SM receipt fields.

### True-endpoint slack

```text
s_true = true_minimum_safety_slack
x_slack = log10(s_true)
```

Accepted-event use requires finite `s_true > 0`. No offset is added and no value is imputed.

### Active-support boundary occupancy

Because Q10-SM defines `interior_variable_count` as active support excluding true-boundary coordinates:

```text
n_boundary_active = support_count - interior_variable_count
f_boundary_active = n_boundary_active / support_count
```

The audit must verify `support_count > 0` and `0 <= interior_variable_count <= support_count`. `f_boundary_active` is the canonical boundary-occupancy variable. Raw `fixed_boundary_count` is reported separately as a whole-state diagnostic and must not be substituted for active-support occupancy.

### Active support

```text
n_support = support_count
f_interior_support = interior_variable_count / support_count
```

`n_support` is canonical. `f_interior_support` is redundant with `f_boundary_active` and is reported only as an integrity mirror.

### Null geometry

```text
n_null = combined_nullity
f_null_energy = (true_null_norm / true_norm)^2
```

`n_null` is always required. `f_null_energy` is analyzed only when `true_norm` and `true_null_norm` are present and finite and `true_norm > 0`. Availability and missingness counts must be reported. Missing values are never imputed. `combined_rank` and raw `true_null_norm` are supporting diagnostics.

### Reversal timing

```text
t = trial, restricted to integers 1..256
t_norm = (trial - 1) / 255
```

The fixed descriptive timing windows are:

```text
early-1: 1..16
early-2: 17..32
middle-1: 33..64
middle-2: 65..128
late: 129..256
```

Trial is an engineering event ordinal. It is not a behavioral response or a claim about learning phase.

## Explicit wedge-correlates rules

The following rules define the audit and take precedence over informal descriptions:

1. Wedge width means only the accepted Q10-SM path-safe rotation `theta`; it does not mean global feasible-manifold width.
2. `theta` is canonical. Residual cosine and `1 - cosine` are deterministic mirrors used for consistency and sensitivity reporting, never separate discoveries.
3. The only canonical correlates are `x_slack`, `f_boundary_active`, `n_support`, `n_null`, available `f_null_energy`, and `t`. No additional correlate may be promoted after inspecting results.
4. Associations are conditional on Q10-SM acceptance. Dominated events remain visible only through the frozen selection audit and never receive synthetic width values.
5. Event receipts are nested repeated geometry observations. The pooled event count is not an independent-replicate count.
6. Missing, nonfinite, ambiguous, or zero-variance inputs are handled by the explicit rules below; no imputation, jitter, continuity correction, winsorization, or silent row deletion is allowed.
7. Association magnitude is not variable importance, constraint, mechanism, or cause. Correlated predictors may describe the same geometry.
8. No result may select a future cosine, rotation, correlation, repair, constructor, scientific, or behavioral gate.

## Frozen numerical conventions

- Decimal receipt values are parsed as IEEE-754 binary64. Nonfinite values are forbidden.
- Exact event identity is the tuple `(seed, side, tau_bits, trial)`, where `tau_bits` is the binary64 bit pattern of the frozen tau.
- Sorting is stable and ascending. Ties are values with identical binary64 bit patterns after the frozen transformation and receive their average one-based rank.
- Spearman correlation is Pearson correlation of the average-rank vectors. The common divisor is immaterial, but the implementation must use one convention consistently and independent review must reproduce it.
- A correlation is undefined when fewer than the required pairwise-complete rows remain or either rank vector has zero sum of squared deviations.
- Quartiles use Hyndman-Fan type 7 on ascending finite values: index `h = (n - 1)q`, linearly interpolating between `floor(h)` and `ceil(h)` for `q in {0.25, 0.5, 0.75}`.
- `log10` is the correctly rounded implementation supplied by the pinned analysis runtime. It is applied only to finite positive slack.
- Plain-language direction is frozen as positive, negative, or zero from the sign of the reported coefficient; no magnitude adjectives such as weak or strong are assigned.
- All displayed decimal rounding occurs after computation and may not feed another calculation.

## Frozen descriptive analysis

No null-hypothesis test, p-value, significance label, inferential confidence interval, causal model, outcome-selected subgroup, or outcome-selected transformation is permitted.

### Coverage and selection audit

Across all valid events, report:

- exact counts by seed, side, tau, timing window, and parent event status;
- accepted fraction in each fixed stratum;
- median and interquartile range of each available predictor separately for accepted and safety-margin-dominated events; and
- missingness and finite-value counts for every derived variable.

This table exposes constructor selection. It is descriptive and must not be described as a model of acceptance.

### Pairwise accepted-event associations

For accepted events, compute average-rank Spearman correlation between `theta` and each canonical predictor:

```text
x_slack
f_boundary_active
n_support
n_null
f_null_energy, when available
t
```

For each pair, report the signed correlation, absolute correlation, pairwise-complete count, tie counts, and direction in plain language. Report the corresponding correlations with `c` and `1 - c` as sensitivity diagnostics.

The event-level pooled correlation is a geometry description, not an estimate from 5,120 independent experimental replicates.

### Dependence-aware descriptive summaries

For each canonical predictor, also report:

- the 20 within-trajectory Spearman correlations for each `seed x side x tau` trajectory when at least 16 pairwise-complete accepted events and nonzero rank variance exist;
- valid-trajectory count plus median, minimum, and maximum of those correlations;
- five leave-one-seed-out pooled correlations; and
- the median and interquartile range of `theta` and `c` in each frozen timing window, stratified by side and tau.

Undefined correlations are reported as undefined with their reason; they are not replaced by zero. These summaries expose dependence and heterogeneity but remain non-inferential.

### Fixed multivariable descriptive summaries

As secondary descriptions, fit exactly two prespecified ordinary least-squares models on accepted events. Continuous variables are average-rank transformed over each model's frozen row set, then centered and scaled using the population standard deviation. Categorical references are seed `9701`, side `R`, and tau `4`.

The core model uses every accepted event with complete admitted core variables:

```text
M_core:
rank(theta) ~ rank(x_slack)
            + rank(f_boundary_active)
            + rank(n_support)
            + rank(n_null)
            + rank(t)
            + seed indicators
            + side indicator
            + tau indicator
```

The extended model is fit only when `f_null_energy` is available for every row admitted to `M_core`:

```text
M_null:
rank(theta) ~ rank(x_slack)
            + rank(f_boundary_active)
            + rank(n_support)
            + rank(n_null)
            + rank(f_null_energy)
            + rank(t)
            + seed indicators
            + side indicator
            + tau indicator
```

If null energy is unavailable for any core row, `M_null` is reported as unavailable; no complete-case subset model replaces it. Both models include an intercept. Solve by deterministic singular-value decomposition with rank cutoff `sigma_max * max(rows, columns) * f64::EPSILON * 1000`. Condition number is `sigma_max / sigma_min_retained`. Report standardized continuous coefficients, categorical coefficients relative to the frozen references, model row count, matrix rank, condition number, and descriptive R-squared `1 - SSE/SST`. If `SST = 0`, rank is deficient, or condition number exceeds `1e10`, label the model numerically unstable and do not interpret coefficients.

The models report no p-values, standard errors, confidence intervals, variable-selection result, importance ranking, or causal interpretation. No interaction, spline, nonlinear transform, subgroup, predictor deletion, or alternate model may be chosen after observing outcomes.

No interaction, spline, nonlinear transform, subgroup, predictor deletion, or alternate model may be chosen after observing outcomes.

## Integrity and independent review

Before any descriptive output is accepted, a future implementation must establish:

- exact hashes of all frozen Q10-SM lineage files;
- exact seed, side, tau, and trial coverage with no duplicate event keys;
- Q10-SM receipt parity and all continuous/f32 safety gates;
- exact event-status and nonidentity classification;
- `cos(theta)` consistency with recorded residual cosine;
- exact derived-variable formulas and average-rank tie handling;
- deterministic output independent of event file order;
- no scientific seeds, behavior fields, sequential-f32 readout, ULP moves, repair, or simulation-RNG changes;
- independent recomputation of all aggregate tables and correlations from immutable event receipts; and
- source, executable, configuration, receipt-manifest, and reviewer hashes if execution is later authorized.

Stage A must pass independent review before Stage B. Any change to receipt semantics, derived variables, transformations, association metrics, strata, timing windows, numerical rules, or output schema requires a new identity and fresh engineering seeds.

## Required outputs if later authorized

A completed Q10-WC qualification would produce:

- immutable event receipts for seeds `9701..9705` under the frozen Q10-SM construction;
- a manifest proving exact 5,120-event coverage and lineage identity;
- coverage and accepted-versus-dominated selection tables;
- canonical pooled, within-trajectory, and leave-one-seed-out association tables;
- fixed timing-window summaries;
- the fixed core and conditional null-energy multivariable summaries, explicit unavailability, or declared numerical-instability results;
- an independent reviewer receipt; and
- `RESULT.md` and `STATUS.json` that retain the descriptive-only firewall.

No future cosine threshold, repair budget, constructor gate, scientific endpoint, or behavioral gate may be selected from these outputs. Any later protocol may cite Q10-WC as descriptive engineering evidence only and must set its own gates independently of Q10-WC outcomes.

## Status vocabulary

- `FROZEN_DESCRIPTIVE_QUALIFICATION_CONTRACT__NOT_EXECUTED`: these two documents are frozen; no implementation or execution has occurred.
- `Q10_WC_VALID__DESCRIPTIVE_ASSOCIATIONS_REPORTED`: all lineage, coverage, receipt, derivation, and independent-review gates pass and the prespecified descriptive outputs are complete.
- `Q10_WC_VALID__INSUFFICIENT_VARIATION`: integrity passes, but one or more prespecified associations are undefined because accepted count or rank variation is insufficient; the missing analyses are reported without replacement.
- `Q10_WC_NOT_INTERPRETABLE__NUMERICALLY_AMBIGUOUS`: lineage and receipt integrity are intact, but at least one Q10-SM-style event is numerically ambiguous, so no wedge-correlates result is interpreted.
- `Q10_WC_INVALID`: any lineage, coverage, receipt, seed, behavior-firewall, derivation, determinism, or independent-review gate fails.

None of these statuses authorizes Q10 repair, DH-08B, a scientific run, or a behavioral claim.

## Assumptions and limits

1. Q10-SM event construction and receipt semantics remain frozen and reproducible for fresh engineering seeds.
2. The local wedge is the best path-safe endpoint found by the frozen 16-candidate Q10-SM constructor, not the global box-constrained feasible manifold.
3. `theta` and `c` describe the same accepted geodesic rotation; `theta` is canonical solely for numerical readability.
4. Boundary occupancy means occupancy within active support, derived from `support_count - interior_variable_count`; whole-state `fixed_boundary_count` is not interchangeable with it.
5. Reversal trial is a deterministic event index and may share strong temporal dependence with learner geometry.
6. Event-level observations within a seed/side/tau trajectory are not independent replicates. The audit therefore reports trajectory and leave-one-seed-out summaries and makes no inferential claim.
7. Association does not establish that a predictor constrains, causes, or controls wedge width. Correlated predictors may describe the same underlying geometry.
8. Accepted-event associations are conditional on Q10-SM constructor acceptance. The separate selection table is required so this conditioning remains visible.
9. No descriptive result may be used to retroactively reinterpret Q10-SM or to choose a future threshold, gate, hypothesis, seed, subgroup, or model.
10. No biological or connectome-specific claim follows from this synthetic engineering audit.
