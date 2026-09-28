# Q10-BG: Bounded Geometry and Committed-f32 Repair Qualification

Status: `DRAFT_ONLY__NOT_EXECUTED`

Q10 is a qualification-only engineering study. It asks how much of the linear freedom established by Q09 survives the learner's weight box and, only after that question succeeds, whether a continuously matched endpoint can be repaired after f32 commitment to match the learner's actual sequential-f32 cue-by-MBON readout.

Q10 does not run measured scientific seeds, inspect behavior as an outcome, establish a direction effect, or authorize DH-08B. Its outputs may qualify a later protocol design; they are not scientific findings.

## Frozen lineage and firewalls

- Q08 remains permanently `BLOCKED_PRESEAL_CONSTRUCTOR_QUALIFICATION`. Q10 may read its sealed lineage identifiers but may not edit or regenerate Q08 source, thresholds, receipts, identity, archive, or outputs.
- Q09 remains `LINEAR_AUDIT_VALID__FREEDOM_PRESENT`. Q10 may consume the Q09 operator and factorization semantics but may not edit or reinterpret Q09 source, contract, results, status, or qualification outputs.
- Q10 uses fresh engineering seeds `9301..9305` only. Scientific seed count is zero.
- No task accuracy, old-map margin, reward, action, or other behavioral endpoint may be calculated or inspected for inference.
- No measured CLI mode is permitted.
- Q10 execution is not authorized by this draft. Constructor budgets, numerical tolerances, and implementation identity must be frozen in a reviewed execution contract before any qualification run.

## Shared event state

At each reversal event, begin from the same committed f32 states used by the learner and widen stored values to f64 for continuous geometry:

```text
d_T = W_T - W_B
```

`W_B` is the committed base endpoint and `W_T` is the committed endogenous true endpoint. Weight limits are `W_min` and `W_max`.

Define the permitted interval-derived support `S_t` using the same source-coordinate semantics as Q09. Partition coordinates as follows:

- `B_t`: coordinates whose true endpoint is exactly at `W_min` or `W_max` in committed f32 storage;
- `O_t`: coordinates outside `S_t`;
- `F_t = B_t union O_t`: frozen coordinates;
- `I_t = S_t \\ B_t`: permitted, true-endpoint-interior coordinates.

For every alternate endpoint:

```text
d_N[F_t] = d_T[F_t]
```

Every coordinate in `B_t` must retain the same lower-bound or upper-bound membership as `W_T`. Every coordinate in `I_t` must remain strictly interior:

```text
W_min[i] < W_B[i] + d_N[i] < W_max[i]
```

This is the exact frozen-boundary-membership and no-new-boundary contract. Q10 may not relax it by clipping after construction.

## Frozen linear constraints

Q10 inherits Q09's exact event-local operator. For each event, construct all 16 cue rows for every MBON drive from the learner's actual source-coordinate semantics and append one global acquisition-axis row:

```text
L = [H_t; A_I^T]
```

where `H_t` has `16 * post_len` rows and `A = W_A - W_0`. Aggregate cue scores, per-group substitutes, and reduced signatures are inadmissible.

Rows are scaled by their f64 Euclidean norms. Rank uses the unchanged Q09 cutoff:

```text
sigma_i > sigma_max * max(rows, cols) * f64::EPSILON * 1000
```

With retained right singular vectors `V_r`, define:

```text
x_star = V_r V_r^T x_T
d_star = d_F + E_I x_star
z_T = x_T - x_star
P_N(r) = r - V_r V_r^T r
```

`z_T` is the endogenous residual in the nullspace of the exact cue-by-MBON plus global-axis operator. All continuous candidates must preserve:

```text
L d_N = L d_T
||d_N||_2 = ||d_T||_2
```

in ideal arithmetic, subject only to predeclared numerical integrity tolerances during implementation.

## Stage 1: continuous bounded geometry

Stage 1 measures how much Q09's unbounded linear freedom survives support, frozen boundary membership, and the weight box. It does not commit the alternate endpoint to f32 and does not evaluate sequential-f32 readout equality.

Start from the feasible endogenous residual `z_T`. Generate deterministic candidate vectors `r` without consuming simulation RNG, project them implicitly into the nullspace, and remove the radial component:

```text
v_0 = P_N(r)
v_1 = v_0 - ((v_0 dot z_T) / (z_T dot z_T)) z_T
v = v_1 * (||z_T||_2 / ||v_1||_2)
```

Degenerate events with zero residual energy or numerically zero tangent energy must be reported under frozen fallback rules; they may not be silently dropped.

For a valid tangent, search the equal-energy null sphere:

```text
z(theta) = z_T cos(theta) + v sin(theta)
d(theta) = d_star + E_I z(theta)
```

This preserves residual norm, total displacement norm, all cue-by-MBON drives, and global acquisition-axis displacement in ideal arithmetic. The bounded constructor may search multiple deterministic tangent directions and both signs. It must never use behavioral results.

Candidate generation should prefer tangent directions that use available interior slack. For true-endpoint interior coordinate `i`, define:

```text
s_i_minus = W_T[i] - W_min[i]
s_i_plus  = W_max[i] - W_T[i]
```

A permitted direction-ranking diagnostic is:

```text
sum_i (
  max(-v_i, 0) / (s_i_minus + epsilon)
  + max(v_i, 0) / (s_i_plus + epsilon)
)^2
```

Lower scores indicate directions that can rotate farther before reaching the box. Slack ranking may order candidates; it may not alter the frozen support, linear operator, boundary membership, norm, or RNG stream.

For each event, report:

- maximum feasible rotation angle and the selected candidate key;
- `c_box = |cos(z_N, z_T)|` for every accepted candidate and the event minimum;
- endpoint minimum interior slack and limiting coordinates;
- exact lower/upper boundary-membership comparisons;
- support violations and new-boundary counts;
- normalized cue-drive, global-axis, total-norm, null-annihilation, and reconstruction errors;
- candidate count, degeneracy count, and constructor exhaustion status.

The distribution of `c_box` is a qualification result. This draft deliberately sets no future DH-08B cosine gate. Any later gate must be frozen from engineering qualification evidence before scientific execution and must not use behavior.

Stage 1 succeeds only as an engineering stage when all integrity checks are valid and the frozen constructor demonstrates directionally non-identity feasible endpoints beyond numerical resolution. The report must show coverage and the full `c_box` distribution; it may not turn that distribution into a scientific effect claim.

## Stage 2: committed-f32 endpoint and readout repair

Stage 2 is conditionally enabled only after Stage 1 receives `Q10_STAGE1_VALID__BOUNDED_FREEDOM_PRESENT` under a reviewed frozen execution contract. Otherwise Stage 2 is `NOT_RUN_STAGE1_GATE`.

Before attempting repair, perform a readout-repair capacity audit for every exact cue-by-MBON row. Record:

- number of permitted coordinates contributing to the sequential sum;
- number remaining interior after Stage 1 construction;
- number allowing legal `-1`, `+1`, and multi-ULP f32 moves without changing frozen boundary membership;
- actual sequential-f32 drive delta produced by each tested legal ULP move;
- rows with no movable coordinate, one-sided capacity, or cancellation-only capacity.

Commit the selected continuous endpoint exactly as the learner would:

```text
W_N_32 = f32(W_B + d_N)
W_T_32 = committed endogenous true endpoint
```

Evaluate the learner's actual sequential-f32 readout in its source iteration order:

```text
e = g_seq32(W_N_32) - g_seq32(W_T_32)
```

Record bitwise equality and ULP error for every one of the `16 * post_len` cue-by-MBON drives. Aggregate cue scores cannot substitute for this check.

If mismatches remain, a deterministic local repair may search legal f32 ULP moves on a reserved subset of high-slack coordinates. The repair is a discrete engineering search, not a smooth optimizer. Every accepted move must be evaluated through the actual sequential-f32 accumulation and must recheck:

- exact permitted support;
- exact frozen lower/upper boundary memberships;
- no new boundary membership;
- weight bounds without clipping;
- committed-state global acquisition displacement;
- committed-state total displacement norm;
- exact cue-by-MBON sequential-f32 equality;
- residual direction cosine relative to the endogenous residual.

Stage 2 reports pre-repair and post-repair mismatch distributions, repair moves and ULP distances, coordinate reuse, axis and norm drift, boundary integrity, and post-repair decorrelation. It performs no behavioral simulation or inference.

## Engineering-seed staging

- Stage 1A uses seed `9301`, both right/left slices, taus `4,16`, and all 256 reversal events per slice/tau: 1,024 engineering states.
- After integrity review and without changing the constructor contract, Stage 1B may use seeds `9302..9305` over the same slices, taus, and events: 4,096 new states and 5,120 cumulative Stage 1 states.
- Stage 2, if enabled, audits the accepted Stage 1 endpoints from the same 5,120 engineering states. It introduces no new seeds and no behavioral observations.
- Any constructor or repair change after Stage 1A requires a new protocol identity and restarts qualification with fresh engineering seeds.

## Status vocabulary

Draft state:

- `DRAFT_ONLY__NOT_EXECUTED`

Stage 1 terminal states:

- `Q10_STAGE1_VALID__BOUNDED_FREEDOM_PRESENT`: all frozen integrity gates pass and non-identity box-feasible residual rotations are demonstrated beyond numerical resolution;
- `Q10_STAGE1_VALID__BOX_CONSTRAINT_DOMINATED`: integrity gates pass but the frozen search finds no directionally distinct feasible residual endpoint;
- `Q10_STAGE1_VALID__NUMERICALLY_AMBIGUOUS`: integrity is not disproven, but rank, residual, or directional separation cannot be resolved reliably;
- `Q10_STAGE1_INVALID`: any lineage, operator, support, boundary, bounds, norm, axis, reconstruction, mutation, RNG, or receipt gate fails.

Stage 2 terminal states:

- `Q10_STAGE2_VALID__SEQ32_REPAIR_PRESENT`: Stage 1 passed, all manipulation-integrity gates pass, and the frozen local repair reaches exact sequential-f32 cue-by-MBON equality;
- `Q10_STAGE2_VALID__SEQ32_ALREADY_EQUAL`: Stage 1 passed and committed endpoints are already sequential-f32 equal without repair;
- `Q10_STAGE2_VALID__SEQ32_REPAIR_ABSENT`: Stage 1 passed and diagnostics are valid, but the frozen repair search cannot reach exact sequential-f32 equality;
- `Q10_STAGE2_VALID__NUMERICALLY_AMBIGUOUS`: Stage 1 passed, but committed-state axis, norm, or residual-direction integrity cannot be resolved under frozen tolerances;
- `Q10_STAGE2_INVALID`: any lineage, support, boundary, bounds, readout-order, mutation, RNG, repair, or receipt gate fails;
- `NOT_RUN_STAGE1_GATE`: Stage 2 was correctly not entered because Stage 1 did not establish bounded freedom.

No Q10 status authorizes DH-08B. A later measured protocol requires a new preregistered identity, a cosine gate selected only from engineering evidence, independent review, and explicit authorization.

## Required qualification controls

Before any execution, the implementation must prove:

- Q08 and Q09 identity hashes are unchanged;
- the exact Q09 operator, source-coordinate order, row scaling, rank cutoff, and global-axis semantics are preserved;
- implicit null projection agrees with an independent dense fixture;
- rotation preserves null annihilation and norm on analytic fixtures;
- exact boundary membership and no-new-boundary checks fail closed;
- support and bounds checks fail closed and no clipping is used;
- candidate construction and repair consume no simulation RNG and mutate no learner state;
- sequential-f32 evaluation matches the learner's actual order and arithmetic;
- ULP moves are deterministic and reversible on fixtures;
- observer on/off outputs are identical;
- all values are finite and all expected events have receipts;
- scientific seeds and measured CLI modes are rejected.

## Explicitly deferred

Q10 does not establish that alternate endpoints are scientifically exchangeable, that residual direction affects future learning, or that any future cosine gate is appropriate. It does not run task behavior, DH-08B, or scientific seeds. Those questions remain behind a separate preregistration and authorization boundary.
