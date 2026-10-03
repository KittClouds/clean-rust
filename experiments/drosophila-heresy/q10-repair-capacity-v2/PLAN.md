# Q10-RC2: Sequential-f32 ULP Repair-Capacity Audit

Status: `FROZEN_PRE_QUALIFICATION__NOT_EXECUTED`

Q10-RC2 is a disjoint, qualification-only engineering identity. It asks whether
the legal one-ULP moves available around Q10-SM committed safe endpoints have
the local readout vocabulary needed to oppose the observed sequential-f32
cue-by-MBON error. It characterizes capacity only. It does not apply a repair,
combine moves into a committed endpoint, run behavior, use scientific seeds, or
authorize DH-08B.

The qualification uses fresh engineering seeds `9611..9615`. Stage A uses
`9611`; Stage B may use `9612..9615` only after Stage A passes independent
integrity review without changing this contract. The full qualification covers
5,120 event states and zero scientific states.

## Frozen Q10-SM lineage

Q10-RC2 descends from the completed Q10-SM Stage 1 qualification at
`experiments/drosophila-heresy/q10-safety-margin-v1`. These are exact SHA-256
identities read from the frozen parent files:

| Q10-SM file | SHA-256 |
| --- | --- |
| `PLAN.md` | `8A70CFADA7A833AA1110FDE5DBF0CFAFDDD4AFD4297A06AD846B1959439B8B9D` |
| `CONTRACT.json` | `5A7CD7E15724F6260C2D42296BED5FF3667CA32FA1D8D48E5408EFFA2A0F35BF` |
| `STATUS.json` | `D19D051DA550BCDED9C436F9A7164AF0C4322D8BB16C418D7C4CA9E04217A9C4` |
| `RESULT.md` | `68200D7F49B8A4B943150A1C3A5AB4B46DF4ED8EB1EBBE7A3DF45F8BEEBBD337` |
| `Q10-SM-SUMMARY.json` | `2B64FF590E226CD393EBCFF6A5147728BAC931F395D76970567EBD6061EDA113` |

The required parent status is
`Q10_SM_STAGE1_VALID__F32_SAFE_FREEDOM_PRESENT`, with exactly 5,120 audited
engineering states, 5,026 accepted safe nonidentity endpoints, 94
safety-margin-dominated states, zero scientific seed bundles, sequential-f32
readout `NOT_RUN`, and ULP repair `NOT_RUN`.

Q08, Q09, Q10-BG, and Q10-SM are immutable lineage. Q10-RC2 may read their
frozen semantics and reconstruct the Q10-SM constructor on fresh engineering
states, but it may not edit, regenerate in place, replace, or reinterpret any
parent contract, result, status, threshold, source, or receipt.

Q10-RC v1 opened engineering seed `9601` and failed closed because the
dependency's returned SVD left vectors did not reconstruct the retained move
subspace within the frozen integrity tolerance. Q10-RC2 never reuses that seed.
It keeps the same SVD singular values and rank cutoff, then computes the
projector and minimum-norm coefficients by Householder QR of `A * V_r`, the
retained right-subspace image. This correction is frozen before seeds
`9611..9615` are opened.

## Authorization and firewalls

- This turn authorizes exactly this `PLAN.md` and `CONTRACT.json`. Source,
  builds, qualification execution, and experiments remain unauthorized.
- Engineering seeds are exactly `9611..9615`; no top-up or replacement seed is
  allowed under this identity.
- Scientific seeds and behavioral observations are forbidden.
- Actions, rewards, accuracy, old-map margins, learning trajectories, and
  future-plasticity outcomes may not be recorded or inferred.
- Q10-RC2 may measure committed weight states and exact cue-by-MBON readouts
  needed for the engineering audit only.
- No candidate move may be applied to the retained endpoint. Every move is an
  immutable one-step counterfactual evaluated from the same baseline.
- Multi-move evaluation, discrete search, beam search, greedy search, endpoint
  repair, and post-repair testing are forbidden.
- No Q10-RC2 status authorizes Q10-SM Stage 2, causal repair, DH-08B, or behavior.

## Fresh engineering-state staging

Q10-RC2 must reconstruct the frozen Q10-SM Stage 1 constructor on fresh task
streams. It may not reuse the parent seeds `9401..9405` as qualification
observations.

Stage A uses:

```text
seed: 9611
sides: R, L
taus: 4, 16
reversal events per side/tau: 256
event states: 1 * 2 * 2 * 256 = 1024
```

Stage B may begin only after Stage A's lineage, source identity, executable
identity, endpoint receipts, move enumeration, sequential-f32 arithmetic,
matrix audit, and independent replay pass without changing this contract. It
uses:

```text
seeds: 9612, 9613, 9614, 9615
sides: R, L
taus: 4, 16
reversal events per side/tau: 256
new event states: 4 * 2 * 2 * 256 = 4096
cumulative event states: 5120
```

For each event, rerun the frozen Q10-SM constructor exactly. Capacity is audited
only when that constructor produces an endpoint satisfying every continuous and
committed 32-ULP Q10-SM gate. A safety-margin-dominated event remains in the
coverage denominator and is recorded as `NOT_APPLICABLE__NO_SAFE_ENDPOINT`; it
is never replaced. No minimum accepted-endpoint count is a success gate for
Q10-RC2.

## Authoritative committed states

For an accepted event, define:

```text
W_B_32 = committed base state
W_T_32 = committed endogenous true endpoint
W_N_32 = committed Q10-SM safe alternate endpoint
```

`W_N_32` must retain the parent's exact support, lower/upper boundary,
no-clipping, finite-value, and 32-ULP safety receipts before it can enter this
audit. `S_t`, `B_t`, `O_t`, `F_t`, and `I_t` retain their Q10-SM meanings. Only
coordinates in `I_t` are eligible for the move bank.

The complete baseline error vector is formed from committed bytes:

```text
g_N = g_seq32(W_N_32)
g_T = g_seq32(W_T_32)
e_k = f64(g_N[k]) - f64(g_T[k])
```

The vector contains every one of the `q = 16 * post_len` cue-by-MBON drives in
cue-major, MBON-minor order. Aggregate cue scores, action scores, reduced
signatures, and f64 linear-operator substitutes are inadmissible.

## Frozen sequential-f32 arithmetic

`g_seq32` must reproduce the learner's real scalar accumulation:

1. select the exact `Task.patterns[cue].edges[offsets[j]..offsets[j + 1]]`
   source-coordinate slice;
2. initialize the row accumulator to positive `0.0f32`;
3. add each committed binary32 weight in stored source order with one binary32
   rounding after every addition;
4. perform no reassociation, SIMD reduction, FMA, f64 accumulation, sorting,
   parallel reduction, or algebraic substitution.

Parallelism is allowed across independent events or candidate moves, never
inside a row's accumulation order. An incidence index may avoid recomputing
unchanged rows, but each affected row must be recomputed from its first source
coordinate in the exact learner order. Stage A must establish bitwise agreement
between any optimized evaluator and an independent scalar reference.

Readout equality and move effects use f32 bit patterns. Analysis differences
are exact f64 widenings of the resulting f32 values. Signed-zero bit patterns
must be reported separately even when their numerical difference is zero.

## Complete legal one-ULP move bank

For every coordinate `i` in `I_t`, evaluate both candidates independently:

```text
w_i^- = nextafter32(W_N_32[i], -infinity)
w_i^+ = nextafter32(W_N_32[i], +infinity)
```

A candidate is legal only when all of the following hold:

- it is exactly one adjacent binary32 value from `W_N_32[i]` in the named
  direction and has a distinct bit pattern;
- it is finite, inside the frozen weight bounds, and strictly interior;
- it changes no coordinate outside `I_t`;
- it preserves exact lower-versus-upper boundary membership and creates no new
  boundary member;
- after the move, at least 31 legal `nextafter32` steps remain before boundary
  contact in each direction;
- no clipping, saturation, stochastic rounding, or model RNG is used.

The 31-step post-move rule consumes at most one step of Q10-SM's frozen 32-ULP
reserve. It is an engineering legality rule, not a future repair budget.

Enumeration is exhaustive: ascending source-coordinate index, minus direction
then plus direction. The per-event candidate budget is exactly `2 * |I_t|`.
There is no sampling, truncation, top-k filter, or outcome-dependent cap. If
complete enumeration cannot be performed, the event or run is incomplete and
may not be summarized from a subset.

For legal move `j`, create a temporary state differing from `W_N_32` at exactly
one coordinate, recompute the actual sequential-f32 readout, then discard it:

```text
v_j[k] = f64(g_seq32(W_N_32 with move j)[k]) - f64(g_N[k])
```

The conceptual repair dictionary is:

```text
R = [v_1, v_2, ..., v_m] in R^(q x m)
```

Zero-effect legal moves remain in enumeration receipts but are excluded from
the active numerical factorization. The report must give both counts. Sparse
storage is allowed; the conceptual matrix and column order are fixed.

No candidate state becomes the next candidate's baseline. No combination of
moves is evaluated or committed.

## Move-bank rank and error projection

Use a deterministic f64 thin SVD of the active conceptual matrix `R`. The
frozen numerical rank threshold is:

```text
tau_rank = sigma_max * max(q, m_active) * f64::EPSILON * 1000
rank(R) = count(sigma_i > tau_rank)
```

If `m_active = 0` or `sigma_max = 0`, rank is zero. SVD convergence tolerance is
`1e-14` with at most `100000` iterations. A mathematically equivalent symmetric
Gram implementation is admissible only if Stage A independent replay agrees on
rank, retained subspace projection, and singular values within the integrity
tolerance below.

With retained left singular vectors `U_r`, define:

```text
e_reachable   = U_r U_r^T e
e_unreachable = e - e_reachable
rho_2         = ||e_unreachable||_2 / ||e||_2
rho_inf       = ||e_unreachable||_inf / ||e||_inf
```

When `g_N` and `g_T` are bitwise equal in every row, the event is
`ALREADY_EQUAL`, both ratios are defined as zero, and no correction budget is
estimated. Otherwise the denominators are nonzero because `e` is constructed
from exact widened f32 results.

Report rank, row dimension, legal and active column counts, rank fraction,
`||e||_2`, `||e||_inf`, reachable and unreachable norms, `rho_2`, `rho_inf`,
and the maximum absolute inner product between a retained bank column and
`e_unreachable`.

The normalized factorization, projection reconstruction, and orthogonality
integrity tolerance is `2e-10`. This is an engineering arithmetic tolerance,
not a capacity-success gate. No rank fraction or projection-residual threshold
is frozen as evidence of repairability.

## Frozen relaxed correction budget

For nonzero error, compute the unique minimum-Euclidean-norm unconstrained
relaxed coefficient vector using the same retained SVD:

```text
x_dagger = -R^+ e
R x_dagger = -e_reachable
```

Report:

- `||x_dagger||_1`, `||x_dagger||_2`, and `||x_dagger||_inf`;
- the number and fraction of coefficients above `1e-12` in absolute value;
- `ceil(||x_dagger||_1)` as a clearly labelled one-ULP-equivalent scale;
- reconstructed residual norms for `R x_dagger + e`;
- singular-value condition diagnostics.

The pseudoinverse uses only singular values above `tau_rank`. Coefficients are
real, may be fractional or negative, do not obey per-coordinate direction
exclusivity, and do not model sequential-f32 interactions among multiple
moves. Therefore these quantities are relaxed local authority diagnostics,
not a move count, feasible repair, upper bound, or lower bound on a discrete
repair unless separately proved later. No budget threshold is a Q10-RC2 success
gate.

## Bottleneck-row audit

For every cue-by-MBON row `k`, report:

- cue index, MBON index, source-coordinate count, and permitted-coordinate
  count;
- legal minus and plus move counts;
- nonzero-effect minus and plus move counts;
- positive, negative, and bitwise-zero effect counts;
- counts whose one-step effect locally reduces or increases `|e_k|`;
- maximum absolute single-move effect;
- summed positive and absolute negative one-step authority, labelled as
  non-composable diagnostics;
- `zero_capacity`, `one_sided_capacity`, and `no_helpful_move_for_error` flags;
- best single-move reduction divided by `|e_k|` when `e_k != 0`.

Rows are sorted for reporting by `no_helpful_move_for_error`, then
`zero_capacity`, then ascending best-single-move fraction. All rows remain in
the machine-readable receipt. No bottleneck count or fraction is a future
repair gate.

For each legal move, also record its committed acquisition-axis and total
displacement-norm deltas as collateral diagnostics. Those quantities are not
included in `R`, and Q10-RC2 does not claim simultaneous controllability of
readout, axis, norm, direction, support, or boundary constraints.

## Required event and aggregate receipts

Each event receipt must include:

- complete lineage, engineering seed, side, tau, trial, and endpoint status;
- hashes of the immutable base, true, alternate, support, and row-order data;
- Q10-SM continuous and committed safety receipts;
- baseline sequential-f32 values, bit patterns, `e`, and per-row ULP distance;
- candidate, legal, illegal-by-reason, zero-effect, and active move counts;
- a deterministic digest of every move's coordinate, direction, resulting
  f32 bits, touched rows, and exact f32 effect bits;
- rank, threshold, singular-value diagnostics, projection metrics, relaxed
  budget metrics, and every bottleneck-row metric;
- confirmation of no learner mutation, no model RNG consumption, no repair,
  no multi-move evaluation, no scientific seed, and no behavior.

Aggregate output must preserve the full distributions and counts by stage,
seed, side, tau, reversal window, endpoint status, and cue/MBON row. It may not
drop dominated or already-equal events. Any post hoc grouping must be labelled
descriptive and may not alter the frozen audit.

## Integrity and fail-closed rules

Before any future execution, freeze the implementation source manifest,
executable hash, compiler and target identity, binary32 `nextafter` behavior,
scalar readout reference, move-incidence index, matrix factorization backend,
and receipt schema. Required tests include:

1. Q10-SM constructor and committed endpoint compatibility on frozen fixtures.
2. Exact one-bit-adjacent `nextafter32` behavior, including signed zero,
   subnormal, exponent-transition, and near-bound values.
3. Exact support, boundary, 31-step remaining-reserve, and no-clipping gates.
4. Bitwise equality between optimized and scalar-reference `g_seq32`.
5. Every candidate evaluated from the immutable `W_N_32` baseline.
6. Sparse conceptual `R` agrees with a dense fixture matrix.
7. Rank and projection agree with an independent factorization on fixtures.
8. Pseudoinverse reconstruction and orthogonality satisfy `2e-10` normalized
   integrity tolerance.
9. Observer on/off leaves all scientific and engineering values unchanged.
10. No simulation RNG consumption, learner mutation, repair application,
    behavior, scientific seed, NaN, infinity, or silent truncation.

Any lineage mismatch, incomplete enumeration, readout-order mismatch,
nonconverged factorization, receipt omission, mutation, or forbidden
observation makes the affected stage `Q10_RC_INVALID`. There is no rescue seed,
top-up, tolerance relaxation, or alternate factorization selected after seeing
results.

## Interpretation statuses

- `Q10_RC_VALID__CAPACITY_CHARACTERIZED`: every applicable event has complete,
  independently reviewed move-bank, projection, bottleneck, and relaxed-budget
  receipts under the frozen rules.
- `Q10_RC_VALID__NO_APPLICABLE_SAFE_ENDPOINTS`: integrity is valid but the
  frozen Q10-SM constructor yields no accepted endpoint on the fresh states.
- `Q10_RC_VALID__NUMERICALLY_AMBIGUOUS`: lineage is intact, but a predeclared
  numerical degeneracy prevents reliable characterization and is fully
  receipted.
- `Q10_RC_INVALID`: any lineage, coverage, move-legality, readout, numerical,
  mutation, seed, or firewall gate fails.

`Q10_RC_VALID__CAPACITY_CHARACTERIZED` says only that the capacity measurements
are valid. It does not mean the error is spanned, the relaxed budget is small,
or a discrete repair exists.

## Capacity is not causal repair

Q10-RC2 evaluates a local dictionary of isolated one-step counterfactuals around
one committed endpoint. Column-space reachability assumes additive real-valued
combinations. Actual sequential-f32 readout is discrete and path-dependent;
combined moves can interact, repeated moves can have different effects, and a
combination that fixes readout can violate axis, norm, direction, reserve, or
other endpoint gates.

Consequently Q10-RC2 cannot establish:

- that any multi-move repair exists;
- that a relaxed coefficient vector can be rounded into legal moves;
- that exact sequential-f32 equality is reachable;
- that all final committed geometry gates can pass simultaneously;
- that an alternate endpoint is scientifically exchangeable;
- any direction, behavioral, future-learning-state, or metaplasticity effect.

All future rank, projection-residual, relaxed-budget, bottleneck, discrete
repair, cosine, exchangeability, and behavioral gates remain unset. A later
causal-repair identity must freeze its own fresh seeds, discrete policy,
multi-move budget, coordinate reuse, re-evaluation schedule, exact final-state
gates, and independent replay before execution. It may use Q10-RC2 only as
qualification evidence.
