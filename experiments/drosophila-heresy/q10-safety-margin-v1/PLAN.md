# Q10-SM: Safety-Margined Bounded Geometry Qualification

Status: `FROZEN_PRE_QUALIFICATION_CONTRACT`

Q10-SM is a qualification-only engineering identity. It asks how much of the bounded continuous freedom found by Q10-BG survives a hard f32 representability reserve. It does not run sequential-f32 readout matching, ULP repair, behavior, scientific seeds, or DH-08B.

The qualification has two engineering stages. Stage 1A uses one fresh seed to test the complete receipt and integrity machinery. Stage 1B may run only after Stage 1A passes independent review without changing the frozen contract. Together they cover 5,120 engineering states and zero scientific states.

## Frozen Q10-BG lineage

Q10-SM is descended from the completed Q10-BG Stage 1 qualification at `experiments/drosophila-heresy/q10-bounded-geometry-v1`. The following SHA-256 identities are exact file hashes:

| Q10-BG file | SHA-256 |
| --- | --- |
| `CONTRACT.json` | `FDD0DFB924D82A798F5C11B661E0B5683FCF9FFF67D48D9E6F302E61474674CA` |
| `PLAN.md` | `630F11591247AB2446B617039EFEFDB007AA8794A291B9863EB87D1CDC8BA777` |
| `RESULT.md` | `29F640B83256605D145DD3ED32C9FC691EC6CA2604A5E521E0B2470F0FBB97C6` |
| `STATUS.json` | `7C71706C4EF85EA6B74E4F01E9D54CCE18FF52265A03E008370DFB45282A8E7C` |

The required parent status is `Q10_STAGE1_VALID__BOUNDED_FREEDOM_PRESENT`, with Stage 2 `NOT_RUN`. Q10-BG found a narrow path-safe continuous wedge and explicitly deferred f32 commitment because its endpoints had inadequate representational slack.

Q08, Q09, and Q10-BG are immutable lineage. Q10-SM may read their frozen semantics and receipts but may not edit, regenerate, reinterpret, or replace their source, contracts, results, statuses, thresholds, or artifacts.

## Authorization and firewalls

- This document and `CONTRACT.json` are frozen for the qualification-only Stage 1 identity. Source creation/edit, build, and qualification execution are authorized within this contract; scientific seeds, experiment execution, measured behavior, and measured CLI modes remain forbidden.
- Engineering seeds are exactly `9401..9405`. Stage 1A uses `9401`; Stage 1B uses `9402..9405`.
- Scientific seed bundles used: zero.
- Behavior, action, reward, old-map margin, learning trajectory, and future-plasticity outcomes are forbidden.
- Stage 2 sequential-f32 readout evaluation and ULP repair are disabled until all Stage 1A and Stage 1B safety-margin receipts pass independent review under a later explicit authorization.
- No Q10-SM status authorizes DH-08B.
- Future direction-cosine and behavioral gates are unset and may not be selected from behavioral evidence.

## Shared event state

At every reversal event, use committed learner states:

```text
W_B_32 = committed base state
W_T_32 = committed endogenous true endpoint
W_B = exact f64 widening of W_B_32
W_T = exact f64 widening of W_T_32
d_T = W_T - W_B
```

Let `S_t` be the event-local interval-derived permitted support using the unchanged Q09/Q10-BG source-coordinate semantics. Let:

```text
B_t = coordinates where committed W_T_32 is exactly at W_min or W_max
O_t = complement of S_t
F_t = B_t union O_t
I_t = S_t minus B_t
```

For every continuous alternate displacement `d_N`:

```text
d_N[F_t] = d_T[F_t]
```

Coordinates in `B_t` preserve lower and upper boundary membership separately. Coordinates outside support remain exactly frozen. Only coordinates in `I_t` may vary.

## Frozen 32-ULP safety reserve

The safety reserve is coordinate-local, asymmetric, and defined from binary32 spacing at the committed true endpoint. For each `i` in `I_t`, define with IEEE-754 binary32 `nextafter`:

```text
w_i       = f64(W_T_32[i])
w_i_down  = f64(nextafter32(W_T_32[i], -infinity))
w_i_up    = f64(nextafter32(W_T_32[i], +infinity))
ulp_i_down = w_i - w_i_down
ulp_i_up   = w_i_up - w_i
m_i_down   = 32 * ulp_i_down
m_i_up     = 32 * ulp_i_up
safe_low_i  = f64(W_min[i]) + m_i_down
safe_high_i = f64(W_max[i]) - m_i_up
```

All values and spacings must be finite, and both spacings must be strictly positive. An empty interval where `safe_low_i > safe_high_i` is fail-closed and must be reported as safety-margin dominated.

Every accepted continuous endpoint must satisfy:

```text
safe_low_i <= W_B[i] + d_N[i] <= safe_high_i
```

for every `i` in `I_t`. The reserve is a hard constraint. No objective may trade away any part of it for greater directional separation. Post-construction clipping is forbidden.

The fixed boundary coordinates in `B_t` are exempt from the interior reserve because their exact lower or upper membership is deliberately frozen. They remain immutable.

## Frozen scientific linear contract

Q10-SM inherits the exact Q09/Q10-BG event-local operator:

```text
L = [H_t; A_I^T]
```

`H_t` contains all `16 * post_len` exact cue-by-MBON drive rows in learner source-coordinate order. `A = W_A - W_0` is the global acquisition vector. Aggregate cue scores, reduced signatures, and group substitutes are inadmissible.

Rows use f64 Euclidean scaling. Rank uses the unchanged cutoff:

```text
sigma_i > sigma_max * max(rows, cols) * f64::EPSILON * 1000
```

With retained right singular vectors `V_r`:

```text
x_star = V_r V_r^T x_T
d_star = d_F + E_I x_star
z_T = x_T - x_star
P_N(r) = r - V_r V_r^T r
```

Every accepted continuous endpoint must preserve, in ideal f64 arithmetic:

```text
L d_N = L d_T
||d_N||_2 = ||d_T||_2
```

This means exact cue-by-MBON linear drives, exact global acquisition-axis displacement, and fixed total f64 displacement norm. An execution contract must freeze normalized numerical tolerances before Stage 1A. No tolerance may be selected after observing qualification outputs.

## Stage 1 constructor question

Stage 1 measures the bounded directional freedom remaining after the 32-ULP safety box is imposed. It may use Q10-BG's implicit-null equal-energy sphere construction:

```text
v_0 = P_N(r)
v_1 = v_0 - ((v_0 dot z_T) / (z_T dot z_T)) z_T
v = v_1 * (||z_T||_2 / ||v_1||_2)
z(theta) = z_T cos(theta) + v sin(theta)
d(theta) = d_star + E_I z(theta)
```

The implementation may rank deterministic tangent candidates by available safety-box slack. It may not materialize a full null basis unless a reviewed implementation requires it. Simulation RNG consumption and learner-state mutation are forbidden.

The frozen constructor uses 8 deterministic tangent candidates and both signs, for 16 candidate paths per event. Its key is `seed xor tau.to_bits xor trial xor candidate * 0xa0761d6478bd642f xor sign_index`; it uses 32 bisections on the path-safe prefix of `[0, pi/2]`. The true endpoint at angle zero must already satisfy the continuous and committed 32-ULP safety gates; otherwise the event is fail-closed as safety-margin dominated. The accepted candidate maximizes the path rotation angle, with `abs(cos(theta)) < 1 - 1e-8` required for nonidentity. Tangent degeneracy, zero null energy, insufficient nullity, empty safe intervals, nonfinite spacing, and exhausted safe candidates are recorded as dominated or invalid under the event receipt. The normalized linear, norm, null-annihilation, reconstruction, and finite-value tolerance is `2e-10`; the zero-null squared-norm floor is `1e-24`. Q10-BG's implementation budgets do not transfer implicitly.

The constructor objective is lexicographic:

1. preserve lineage, support, and exact lower/upper boundary membership;
2. satisfy the complete cue-by-MBON plus global-axis linear contract;
3. preserve total f64 displacement norm;
4. satisfy the complete 32-ULP continuous safety box without clipping;
5. maximize residual directional separation only among candidates satisfying items 1 through 4.

The safety reserve is never an optimization penalty. It is an admission gate.

For each event, Stage 1 must report at least:

- rank, nullity, endogenous null energy, and factorization integrity;
- constructor key, candidate count, degeneracy count, and exhaustion status;
- accepted rotation angle and `c_sm = abs(cos(z_N, z_T))`;
- continuous minimum lower and upper safety surplus in both f64 distance and true-endpoint ULP units;
- all limiting coordinates and whether any safe interval is empty;
- support violations, lower-bound membership differences, upper-bound membership differences, and new-boundary count;
- normalized cue-drive, global-axis, total-norm, null-annihilation, and reconstruction errors;
- confirmation that no clipping, simulation RNG consumption, learner mutation, scientific seed, or behavioral observation occurred.

The full `c_sm` distribution is descriptive engineering evidence. No future cosine threshold is set by this plan.

## Stage 1 diagnostic f32 commitment

After a continuous candidate passes every continuous gate, Stage 1 must perform a diagnostic commitment using the learner's real storage conversion and no clipping:

```text
W_N_32 = f32(W_B + d_N)
d_N_32 = f64(W_N_32) - f64(W_B_32)
```

The committed bytes are authoritative for the following diagnostics:

- exact preservation of frozen outside-support coordinates;
- exact lower and upper boundary memberships relative to `W_T_32`;
- no new boundary membership in `I_t`;
- finite in-range values and confirmation that no clipping occurred;
- for every variable coordinate, the number of legal binary32 `nextafter` steps toward each bound before boundary contact;
- whether at least 32 successive legal downward steps and 32 successive legal upward steps remain strictly interior;
- committed minimum safety capacity in each direction;
- committed f64 cue-drive, global-axis, total-norm, reconstruction, and residual-cosine drift relative to the continuous endpoint.

A Stage 1 safety-margin receipt passes only when all continuous gates pass and every variable committed coordinate retains at least 32 legal `nextafter` steps in both directions while preserving support and boundary rules. A conversion that clips, creates a boundary membership, changes a frozen coordinate, or consumes the reserve fails closed.

Stage 1 does not evaluate `g_seq32`, bitwise cue-readout equality, ULP readout error, repair capacity, or repair moves. Those belong exclusively to disabled Stage 2.

## Engineering staging

Stage 1A uses:

```text
seed: 9401
sides: R, L
taus: 4, 16
reversal events per side/tau: 256
states: 1 * 2 * 2 * 256 = 1024
```

Stage 1B may begin only after Stage 1A's source identity, executable identity, complete receipts, independent replay, safety diagnostics, and all fail-closed gates pass review. It uses:

```text
seeds: 9402, 9403, 9404, 9405
sides: R, L
taus: 4, 16
reversal events per side/tau: 256
new states: 4 * 2 * 2 * 256 = 4096
cumulative states: 5120
```

Any constructor, reserve, tolerance, receipt, or implementation change after Stage 1A requires a new protocol identity and fresh engineering seeds. No top-up is allowed.

## Stage 1 interpretation statuses

- `Q10_SM_STAGE1_VALID__F32_SAFE_FREEDOM_PRESENT`: all continuous and committed safety receipts pass and the frozen constructor finds nonidentity safety-margined endpoints under the predeclared numerical rule.
- `Q10_SM_STAGE1_VALID__SAFETY_MARGIN_DOMINATED`: all integrity machinery is valid, but the frozen constructor cannot produce qualifying nonidentity endpoints with the complete 32-ULP reserve.
- `Q10_SM_STAGE1_VALID__NUMERICALLY_AMBIGUOUS`: lineage and machinery are not disproven, but factorization, equality, commitment, or nonidentity cannot be resolved under frozen tolerances.
- `Q10_SM_STAGE1_INVALID`: any lineage, support, boundary, bounds, reserve, norm, axis, cue-drive, mutation, RNG, seed, or receipt gate fails.

No minimum scientific direction cosine is part of these statuses. The qualification must report separately:

1. whether any valid committed alternate endpoint exists; and
2. the amount of directional separation achieved.

The first may not be presented as evidence for the second.

## Stage 2 remains disabled

Stage 2 consists of actual learner-order sequential-f32 cue-by-MBON comparison, event-local legal ULP move-bank construction, repair-capacity analysis, and discrete repair. Every part is `NOT_RUN_STAGE1_GATE` in this draft.

Stage 2 may be designed or enabled only after both Stage 1A and Stage 1B receipts pass independent review. Enabling it requires a reviewed frozen amendment or a new protocol identity that sets repair-coordinate rules, ULP radius, candidate budget, beam or search policy, move budget, exact final simultaneous gates, and independent replay. No behavioral execution follows automatically.

## Required pre-execution freeze

The following execution identity is frozen before Q10-SM Stage 1A:

- implementation source identity and executable hash;
- exact binary32 `nextafter` implementation, signed-zero handling, and bound comparison semantics;
- 16 candidates per event, the deterministic key schema above, and zero simulation-RNG consumption;
- endpoint search by the path-safe prefix of `[0, pi/2]`; path feasibility is a required constructor gate for this identity;
- tangent degeneracy and residual zero-energy rules above;
- continuous and committed numerical tolerance `2e-10`, zero-null squared-norm floor `1e-24`, and nonidentity epsilon `1e-8`;
- nonidentity resolution `abs(cos(theta)) < 1 - 1e-8`; coverage is the exact 1,024 Stage 1A and 4,096 Stage 1B event counts;
- the complete event receipt schema and independent replay implementation;
- observer invariance, finite-value, no-allocation hot-loop, and fail-closed tests;
- explicit rejection of scientific seeds, measured CLI modes, sequential-f32 readout, ULP repair, and behavior.

## Assumptions

1. Model weights and bounds are finite IEEE-754 binary32 values; NaN and infinity fail closed.
2. `nextafter32` means the adjacent representable binary32 value in the named direction. Directional spacing is measured once at `W_T_32` and widened exactly to f64.
3. The 32-ULP continuous reserve uses separate downward and upward local spacings because binary32 spacing may be asymmetric at exponent transitions and around signed zero.
4. Post-commit safety is stronger than the continuous distance proxy: each committed variable coordinate must demonstrate 32 actual successive legal representable moves in both directions.
5. Exact boundary membership is lower-versus-upper membership in committed storage, with bitwise comparison where signed zero could distinguish stored values.
6. The permitted support and source-coordinate order are inherited unchanged from Q09 and Q10-BG.
7. Fixed total norm means the f64 Euclidean norm of the complete displacement, including frozen coordinates.
8. Only endpoint feasibility is scientifically relevant to this identity because the learner commits the endpoint update; path feasibility may be recorded but is not assumed unless the later execution contract explicitly freezes it as a gate.
9. Q10-SM remains a local equal-energy null-sphere qualification. It does not claim to solve the global box-constrained endpoint problem or search disconnected feasible regions.
10. Diagnostic f32 commitment in Stage 1 is authorized only when a future execution is explicitly approved; it does not include learner-order sequential-f32 readout evaluation.
11. A 32-ULP reserve is an engineering choice for representability and future repair capacity. It is not selected from behavior and makes no biological claim.
12. Future cosine, behavioral, exchangeability, direction-effect, future-learning-state, and metaplasticity gates or claims remain unset.
