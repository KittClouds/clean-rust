# F4-SYMMETRY-01 — qualification contract v0.1

**Status:** frozen experimental design; implementation specification is the next artifact.  
**Role:** engineering-only representation diagnosis for F4 calibration.  
**Measured REACH-03 namespace:** none.  
**Source audit:** `F4-SYMMETRY-01-MATH-AUDIT-v0.1.md`.

## 1. Question and claim ceiling

Does an explicit task-relative relational sidecar improve held-out-task-block extraction of reference polarity, and does canonical ordering of that sidecar add benefit?

The experiment tests feature representation under the existing estimator and four qualification blocks. It does not test whether those blocks are exact symmetry transforms, whether the native learner has this information at its update interface, or whether the native learner benefits from using a polarity predictor.

## 2. Frozen provenance and scope

- The exact historical 80D stream is `HIST`, a provenance-only anchor. Its prior result may be cited. It is excluded from all arm contrasts and will not be refit for this study.
- The clean scientific base `A` is the admissible 66-field projection below. It omits the four expected cue-score fields and all ten zero-padding fields.
- `B`, `C`, and `D` each have 90 input fields: the same 66-field base plus 24 sidecar fields. They use the same MLP hidden architecture, initialization policy, optimizer, training order, training budget, fold definitions, normalization rule, and scored rows.
- Qualification only. No measured namespace, REACH-03 filtration result, biological promotion, native-rule change, or PHENO reseal follows from this contract.

## 3. Legacy 80D field admissibility audit

| Legacy indices | Fields | Decision | Reason |
| --- | --- | --- | --- |
| 0–6 | coordinate, edge pre/post IDs, pre/post degrees, edge multiplicity (`edge.count`), anatomical MB sign | Include in A | Frozen coordinate/anatomy source data. |
| 7 | normalized trial index | Include in A | Declared schedule/time metadata. |
| 8–20 | current weight, eligibility, cached probability, postsynaptic activity, baseline, signed post, gain, denominator, bias, scale, decay, work, events | Include in A | Ordinary simulator/native state. The cached probability is the probability for the last sampled pattern only; it is not described as cue-specific. |
| 21–24 | four task-label signs | Include in A | Task definition. Retain absolute cue-slot order. |
| 25–28 | four `expected_score_for` cue scores | Exclude | They reproduce an intermediate used by the reference target operator. |
| 29–32 | four cue-edge incidence indicators | Include in A | Task-pattern structure. Retain absolute cue-slot order. |
| 33–45 | current schedule cue/distractor pattern IDs | Include in A | Frozen schedule metadata. Retain the existing absolute IDs and ordering. |
| 46–52 | reserved zero padding | Exclude | Constant fields carry no information. |
| 53–76 | four fixed signed sketches of coordinate, cue index, pattern edge count, and cue label | Include in A | Deterministic coordinate/task metadata; no reference intermediate. Retain the frozen historical sketch rule. |
| 77–79 | reserved zero padding | Exclude | Constant fields carry no information. |

All state fields in A are collected at the same row time as the prior F4 feature stream: after `begin_trial`, before native `apply_delta`. `proposed_delta_into` is called before feature extraction to establish native proposed support; its reward-derived output is not included in A. This follows the existing collection ordering and must be checked against the frozen row manifest during implementation.

The reference-only exclusions are `expected_score_for` / `expected_score_f64`, reference gradient/vector values, target or target sign, reference loss/logits/coefficient, any function of `g`, and any field computed by calling or reproducing reference-only code.

## 4. Cue-specific forward probability

For coordinate `i` with post `j`, cue `c`, and task pattern edge set `P_c`, define `p_cj` through a standalone forward-state function, not a reference helper:

```
drive_cj = sum_{e in P_c, post(e)=j, active[e]} weight_before[e]
p_cj = sigmoid_f32(2 * (drive_cj / denom[j] - bias[j]))
```

The implementation uses the ordinary simulator's float32 operation order and clamp `[-30, 30]`. Inputs are graph/task pattern edges, pre-delivery weights, active mask, denominator, and bias. It must not read task labels, reference values, reference scores, target values, or reference coefficients. For each sampled row, probabilities for all four task cues are recomputed at the same frozen pre-delivery state. The simulator's cached `probabilities[j]` is not substituted because it corresponds to the last sampled event.

## 5. Arms and exact sidecars

Let the clean base row be `x in R^66`, formed by concatenating indices `0–24`, `29–45`, and `53–76` in their original order. This removes four expected-score fields and ten reserved zero-padding fields. Normalize each base field using per-fold training means and standard deviations (standard deviation below `1e-6` becomes `1`); apply the fitted values unchanged to held-out rows.

- **A — clean absolute base:** `x`, 66 fields.
- **B — dimension control:** `x` plus 24 frozen signed random projections of the normalized `x`. For projection `r` and input `k`, take bit 0 of `SHA256(UTF8("F4-SYMMETRY-01-B-PROJ-v1") || LE32(r) || LE32(k))`; bit 0 maps to `+1`, bit 1 to `-1`. Coefficients are float32 `sign * f32(1/sqrt(66))`. Accumulate products in ascending `k` order using float32. No label, target, row ID, or block ID enters the key. The 24 outputs receive training-fold-only mean/standard-deviation normalization. B adds dimensions but no information beyond A.
- **C — absolute-order relation sidecar:** `x` plus six fields for each of four cues, concatenated in absolute cue order. For each of the three floating tuple components, compute one mean and standard deviation per fold from training rows pooled across all four cue positions; use that same component statistic for every cue slot. Apply the fitted values unchanged to held-out rows.
- **D — canonical-order relation sidecar:** use the same raw four six-field tuples, sorted canonically without cue identity. Apply the **same pooled per-component training statistics as C** to the three floating components, then encode. D and C contain the same normalized tuples; only tuple order differs. Do not estimate rank-position-specific statistics.

For cue `c`, coordinate `i` at post `j`, let `I_ic` indicate whether its KC-to-MB edge occurs in cue pattern `c`; `y_c` is the task-label sign; `a_j` is `sim.action_sign[j]`; and `r_c=y_c*a_j`. The tuple is:

```
(I_ic: u8, r_c: i8, I_ic*r_c: i8, p_cj - 0.5: f32,
 I_ic*(p_cj - 0.5): f32, r_c*(p_cj - 0.5): f32)
```

These are task/state relations, not a reconstructed reference gradient. They contain no `s_c`, reference sigmoid coefficient, derivative term, `g`, or `Y`. Any implementation that would need one of those values to produce a tuple violates this contract.

### D ordering semantics

For the canonical sort key, compare `(I_ic, r_c, I_ic*r_c)` as exact discrete values, then fields 4–6 with IEEE-754 `totalOrder` over finite float32 values after normalizing either signed zero to positive zero. Reject every nonfinite value. No cue ID, pattern ID, or original tuple position breaks ties. Equal tuples are interchangeable. After sorting, encode the first three fields as float32 model inputs and encode every field little-endian. The resulting 24-field D model-input sidecar must be byte-identical after any joint cue permutation that preserves the underlying cue-pattern/label association.

## 6. Estimator, rows, folds, and scoring

- Use the existing frozen MLP hidden topology `128-GELU-64-GELU-1`, with input width 66 for A and width 90 for B/C/D. Hidden layers, activation, optimizer, epochs, batch size, training order, loss, and normalization policy match the frozen F4 encoder spec. Initialize B/C/D from one identical 90-input model tensor set per fold, so their first-layer weights, biases, and all later tensors are bit-identical before training. Use one separately seeded, deterministic 66-input initialization for A; A is descriptive and not used in the two primary contrasts. Freeze the keyed initialization algorithm and seed derivation in the implementation contract before any fit.
- Use the same frozen qualification-v2 U* row set, inclusion probabilities, target threshold, nonzero-target/native-support eligibility, and four leave-one-block-out folds (303000–303003). Do not change rows or replace blocks. Any implementation discrepancy in row identity stops the branch.
- Fit one model per arm per held-out block under the same frozen initialization and order policy. No model selection across arms.
- For scored row `j`, set `q_j=1/p_inclusion_j`. Pooled out-of-fold balanced error is exactly `epsilon_bal = 0.5 * sum_{Y=+1}(q_j*err_j)/sum_{Y=+1}q_j + 0.5 * sum_{Y=-1}(q_j*err_j)/sum_{Y=-1}q_j`. Report unclipped `1-2*epsilon_bal` and clipped `max(0,1-2*epsilon_bal)`.
- The two predeclared contrasts are **C minus B** (relational sidecar utility over a no-new-information width control) and **D minus C** (canonical ordering utility). Report error differences in the natural direction, `error_C - error_B` and `error_D - error_C`; negative favors C or D, respectively.
- Report blockwise signed margin `E_q[Y * logit]`, calculated as the half-sum of the two class-conditional q-weighted means when both target classes occur. For class-degenerate block 303003, report the q-weighted mean `Y*logit` as a descriptive one-class diagnostic and mark balanced error/observability undefined. Do not apply a denominator floor to call it balanced evidence.
- Secondary only: A and B-A descriptive comparison, native-sign/predictor/reference-sign `Psi`, and delivery alignment under the existing REACH-03 definitions. These do not change the primary interpretation.

Readout order: HIST provenance; A clean baseline; B-A dimension-control behavior; C-B relational benefit; D-C canonical-ordering benefit; then secondary metrics. No prediction flipping, fold replacement, model enlargement, extra epochs, feature edits, or seed replacement after any arm outcome is opened.

## 7. Separate representation and target symmetry fixtures

Before estimator fitting, run deterministic fixtures on frozen input states. A fixture result is an implementation audit, not scientific evidence.

1. **Cue relabeling:** apply nontrivial permutations from S4 to cue patterns and labels and remap schedule cue IDs consistently. Verify that C tuples are permuted and the D sidecar is byte-identical. Separately recompute the implemented reference vector and report maximum absolute `g` difference, sign changes, and target-channel changes at the frozen threshold. Do not require bitwise identity of `g`.
2. **Joint label/action inversion:** invert every `y_c` and every `a_j` at a fixed state. Verify that each relation tuple is unchanged and D sidecar bytes match. Separately recompute actual `g` and report the same numerical target-invariance diagnostics.
3. No cue-slot polarity-reversal law is assumed. No graph-coordinate permutation is included absent a separately proven graph automorphism.

Representation invariance and target invariance receive separate receipt fields. If roundoff changes target labels near threshold, retain all rows and record the change as a target-implementation symmetry limitation. No rows may be dropped because the symmetry check is inconvenient.

## 8. Qualification interpretation and stop rules

- `B < A` in error is generic benefit from the frozen expansion/projection under this estimator; it is not relation evidence.
- `C < B` supports utility from the declared absolute-order relational sidecar.
- `D < C` supports utility from canonical ordering of that sidecar under this estimator and these qualification blocks. It does not establish full-representation invariance, task isomorphism, native-interface availability, or a general task-symmetry law.
- A null or negative contrast is bounded to these features, estimator, rows, and four qualification blocks.
- Stop before fitting if the forward probability routine cannot be independently reconciled with the ordinary simulator forward calculation, any excluded reference intermediate enters A/B/C/D, the cue-permutation fixture fails D sidecar invariance, or the arm rows/folds differ.

The 80D HIST reproduction remains provenance only. The scientific contrasts use A–D. Qualification success or failure does not authorize measured REACH-03 execution, biological promotion, or PHENO reopening.
