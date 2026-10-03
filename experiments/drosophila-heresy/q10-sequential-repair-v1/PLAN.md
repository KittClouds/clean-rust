# Q10-SR: Sequential-f32 Readout and Discrete ULP Repair Qualification

Status: `FROZEN_PRE_QUALIFICATION__NOT_EXECUTED`

Q10-SR is a qualification-only engineering protocol. It asks whether the
safety-margined alternate endpoints admitted by Q10-SM can be made exactly
indistinguishable from their endogenous endpoints under the learner's actual
sequential binary32 cue-by-MBON readout, using only a conservative bank of
legal representable-weight moves.

This protocol writes no behavioral claim. It uses zero scientific seeds,
does not evaluate actions, rewards, margins, or future learning, and does not
authorize DH-08B. It deliberately separates three questions:

1. What mismatch is created by committing an otherwise valid Q10-SM endpoint?
2. Does the local legal one-ULP move bank have relaxed linear capacity to
   address that mismatch?
3. Can a frozen deterministic discrete search produce a committed endpoint
   that passes every final gate simultaneously?

Success or failure at one layer may not be substituted for another. In
particular, relaxed capacity is not a repaired endpoint, and search exhaustion
is not proof that repair is impossible.

## Frozen Q10-SM lineage

The parent is the completed Q10-SM qualification at
`experiments/drosophila-heresy/q10-safety-margin-v1`. These are exact SHA-256
file identities read from that root:

| Q10-SM file | SHA-256 |
| --- | --- |
| `PLAN.md` | `8A70CFADA7A833AA1110FDE5DBF0CFAFDDD4AFD4297A06AD846B1959439B8B9D` |
| `CONTRACT.json` | `5A7CD7E15724F6260C2D42296BED5FF3667CA32FA1D8D48E5408EFFA2A0F35BF` |
| `RESULT.md` | `68200D7F49B8A4B943150A1C3A5AB4B46DF4ED8EB1EBBE7A3DF45F8BEEBBD337` |
| `STATUS.json` | `D19D051DA550BCDED9C436F9A7164AF0C4322D8BB16C418D7C4CA9E04217A9C4` |

The required parent status is
`Q10_SM_STAGE1_VALID__F32_SAFE_FREEDOM_PRESENT`. The parent must report 5,120
audited engineering states, 5,026 accepted safety-margined nonidentity
endpoints, zero scientific seeds, sequential-f32 readout `NOT_RUN`, ULP repair
`NOT_RUN`, and DH-08B unauthorized.

Q08, Q09, Q10-BG, and Q10-SM are immutable lineage. Q10-SR may read their
frozen semantics and artifacts but may not edit, regenerate, reinterpret, or
replace them.

## Authorization boundary

The user explicitly authorized this qualification lane after the document-only
draft. Source creation, target-drive builds, Stage 1A/1B engineering
qualification execution, receipts, and independent review are authorized
inside this root. Scientific seeds, behavior, experimental execution, and
DH-08B remain unauthorized. The pre-execution seal must identify source,
executable, receipts, reviewer, and implementation details before a fresh-seed
qualification run.

The future qualification, if separately authorized, remains engineering-only:

- fresh engineering seeds are exactly `9501..9505`;
- qualification tranche Stage 1A uses seed `9501`;
- qualification tranche Stage 1B uses seeds `9502..9505` only after Stage 1A
  passes independent review without a protocol change;
- sides are `R` and `L`, taus are `4` and `16`, and each side/tau contributes
  256 reversal events;
- Stage 1A contains 1,024 states, Stage 1B adds 4,096 states, and cumulative
  coverage is 5,120 states;
- no top-up, replacement seed, scientific seed, behavior, or measured CLI is
  allowed.

The names Stage 1A and Stage 1B describe execution tranches within Q10-SR.
The operation they qualify is lineage Stage 2A: committed sequential-readout
diagnosis, repair-capacity diagnosis, and bounded discrete repair.

## Event reconstruction

Each event is reconstructed from the same learner state and exogenous stream
semantics used by Q10-SM, but with fresh engineering seeds. Q10-SR must run the
frozen Q10-SM constructor without adapting its candidate count, key, path,
reserve, tolerances, or endpoint-selection rule.

For every event:

```text
W_B_32 = committed base state
W_T_32 = committed endogenous true endpoint
W_B    = exact f64 widening of W_B_32
W_T    = exact f64 widening of W_T_32
d_T    = W_T - W_B
```

The Q10-SM constructor produces a continuous alternate endpoint, commits it
without clipping, and yields:

```text
W_N_32^0 = initial committed safety-margined alternate endpoint
d_N^0    = f64(W_N_32^0) - f64(W_B_32)
```

An event that does not produce a valid Q10-SM safety-margined nonidentity
endpoint is recorded as `PARENT_CONSTRUCTOR_INELIGIBLE`. It remains part of
coverage but is excluded from mismatch, capacity, and repair denominators. It
may not be replaced or topped up.

The inherited sets are:

```text
S_t = event-local interval-derived permitted support
B_t = true committed lower/upper boundary coordinates
O_t = complement of S_t
F_t = B_t union O_t
I_t = S_t minus B_t
```

Only coordinates in `I_t` may be repair coordinates. Coordinates in `F_t`
remain bitwise frozen to `W_N_32^0`, which is already required to match the
Q10-SM frozen-coordinate contract.

## Authoritative sequential binary32 readout

The readout is the learner's production cue-by-MBON kernel, invoked through a
pure observer or a byte-identical instrumented copy whose source identity is
frozen before Stage 1A. The output vector contains all `16 * post_len`
cue-by-MBON drive values in the learner's exact cue, MBON, and source-coordinate
order.

The observer must preserve:

- binary32 multiplication and addition semantics;
- the learner's exact accumulation order;
- the learner's actual handling of zero, subnormal, and signed-zero values;
- the learner's actual fused-versus-unfused operation semantics;
- bitwise output storage.

No f64 accumulation, reassociation, SIMD lane reordering, pairwise reduction,
sorting, aggregate cue score, or reduced signature is admissible unless it is
already the learner's frozen production behavior. Observer invocation must
consume no simulation RNG and mutate no learner state, trace, counter, or
weight.

Define:

```text
g_T = g_seq32(W_T_32)
g_N = g_seq32(W_N_32^0)
e   = exact componentwise comparison of g_N against g_T
```

The mismatch layer reports, before any repair:

- bitwise mismatch count;
- ordered-binary32 ULP distance per output;
- maximum and sum of ULP distances;
- f64-widened absolute and squared error;
- finite, NaN, infinity, and signed-zero classifications;
- mismatch counts by cue and MBON.

`READOUT_ALREADY_EQUAL` is a valid diagnostic category. Such an event receives
no repair moves and passes to final simultaneous-gate audit unchanged.

## Stage 2A.1: legal one-ULP move bank

For each coordinate `i` in `I_t`, enumerate at most two starting-state moves:

```text
move(i, down) = nextafter32(W_N_32^0[i], -infinity)
move(i, up)   = nextafter32(W_N_32^0[i], +infinity)
```

A starting-state move is legal only if it:

- changes exactly one committed binary32 weight by exactly one representable
  step in the named direction;
- remains finite and within the ordinary weight bounds without clipping;
- remains in `I_t` and changes no coordinate in `F_t`;
- creates no lower or upper boundary membership;
- leaves at least 16 further legal `nextafter32` steps toward each ordinary
  bound after the move;
- preserves the frozen support and separate lower/upper boundary sets.

The 32-step Q10-SM reserve is the starting reserve. Q10-SR may spend at most 16
representable steps on any coordinate and must retain a hard final reserve of
at least 16 steps in both directions.

For every legal starting-state move `j`, calculate its actual output effect by
full authoritative sequential replay:

```text
v_j = f64(g_seq32(W_N_32^0 + move_j)) - f64(g_seq32(W_N_32^0))
```

The f64 subtraction describes committed binary32 output changes; it does not
replace the discrete readout. Zero-effect moves remain counted and identified.
Duplicate effect vectors may be indexed compactly only if multiplicity and
coordinate/direction provenance remain recoverable.

Required move-bank diagnostics include:

- legal and rejected move counts by direction and rejection reason;
- movable, interior, and high-slack coordinate counts for every readout row;
- positive, negative, and zero one-move effects for every readout row;
- row and column coverage, zero-effect fraction, duplicate-effect fraction,
  and exact move provenance;
- the distribution of one-move output ULP effects;
- the distribution of remaining coordinate reserve after one move.

## Stage 2A.2: relaxed repair-capacity diagnostic

Stack the widened committed effects into:

```text
R = [v_1, v_2, ..., v_m]
e_64 = f64(g_N) - f64(g_T)
```

This layer is diagnostic only. It asks whether the local first-step effect
dictionary contains the observed error direction under a continuous relaxed
model. It does not assert that a sequence of discrete moves exists, because
sequential binary32 effects can change after each move.

Use deterministic f64 SVD with the frozen cutoff:

```text
sigma_i > sigma_max * max(rows, cols) * f64::EPSILON * 1000
```

Report:

```text
rank(R)
e_reachable   = P_col(R) e_64
e_unreachable = e_64 - e_reachable
```

Also report the minimum-L2 relaxed solution to `R x = -e_reachable`, including
its L1, L2, and L-infinity norms, nonzero coefficient count under the frozen
numeric resolution, and ratios to the discrete move budgets. No rounding of
that solution may be presented as an actual repair.

Capacity statuses are independent of repair statuses:

- `CAPACITY_EXACT_WITHIN_TOLERANCE`;
- `CAPACITY_PARTIAL`;
- `CAPACITY_ZERO_OR_EMPTY_BANK`;
- `CAPACITY_NUMERICALLY_AMBIGUOUS`.

The normalized relaxed projection tolerance is `2e-10`, inherited as an
engineering arithmetic tolerance rather than a scientific threshold.

## Stage 2A.3: bounded deterministic discrete repair

Actual repair begins from `W_N_32^0`. The search operates only on committed
binary32 byte states and re-evaluates the complete authoritative sequential
readout after every candidate move.

The frozen conservative search envelope is:

```text
beam width:                 64 unique committed states
maximum sequential moves:  64
branch shortlist:           64 legal one-ULP successors per beam state
maximum moves per coordinate: 16 total from W_N_32^0
minimum final reserve:      16 legal steps toward each bound
coordinate reuse:           allowed within the per-coordinate limit
immediate inverse move:     forbidden
clipping:                   forbidden
simulation RNG:             forbidden
```

At each beam state, enumerate currently legal one-ULP successors. Rank moves by
the exact successor objective, retain the best 64 per parent, deduplicate by
the complete committed weight bytes, then retain the best 64 states globally.
Ties are resolved by lower source-coordinate index, then downward before
upward, then lexicographic committed bytes. A state seen at an equal or lower
depth is not revisited.

The search objective is lexicographic:

1. fewer bitwise-mismatched sequential readout elements;
2. smaller maximum ordered-binary32 ULP output distance;
3. smaller sum of ordered-binary32 ULP output distances;
4. smaller f64-widened squared readout error;
5. fewer moves;
6. smaller maximum per-coordinate displacement from `W_N_32^0`;
7. deterministic bytewise tie-break.

No axis, norm, geometry, behavior, or future-learning value may influence the
search ranking. They are independent final gates and diagnostics. This avoids
silently trading scientific geometry for easier readout repair.

The search stops successfully only when every sequential readout element is
bitwise equal to `g_T`. It may stop unsuccessfully at the frozen depth or beam
budget. Budget exhaustion means only that this constructor did not find a
repair.

## Final simultaneous committed-state gates

Let `W_R_32` be the unchanged already-equal endpoint or the first exact-readout
state returned by the deterministic search. Reconstruct all final quantities
from its committed bytes. A `REPAIR_VALID` event requires every gate below at
once:

1. `g_seq32(W_R_32)` is bitwise equal to `g_seq32(W_T_32)` for every
   cue-by-MBON element under independent replay.
2. Every coordinate outside `S_t` is bitwise unchanged from `W_N_32^0`.
3. True lower and upper boundary memberships are preserved separately; no new
   boundary membership exists.
4. Every changed coordinate lies in `I_t`, all weights are finite and in
   bounds, and no clipping occurred.
5. Every variable coordinate retains at least 16 successive legal binary32
   steps toward each bound.
6. No coordinate moved more than 16 representable steps from `W_N_32^0`, and
   total sequential moves are at most 64.
7. The normalized f64 cue-by-MBON linear-contract error relative to `d_T` is at
   most `2e-6`.
8. The normalized global acquisition-axis displacement error relative to
   `d_T` is at most `2e-6`.
9. The normalized total f64 displacement-norm error relative to `d_T` is at
   most `2e-7`.
10. Constructor lineage, event identity, RNG nonconsumption, observer purity,
    and receipt completeness all pass.

The normalization denominator for a vector or scalar target is
`max(abs(target), 1e-12)` componentwise for scalar checks and
`max(norm2(target), 1e-12)` for vector checks. The final report must include
absolute errors as well. These are frozen engineering admission tolerances for
this qualification and do not authorize later science.

Residual direction, cosine to the endogenous residual, rotation angle, move
count, and reserve consumption are reported descriptively from `W_R_32`. No
directional-separation threshold is set. A repaired endpoint may be
engineering-valid while remaining directionally trivial.

## Event and aggregate statuses

Each eligible event receives one mismatch status, one capacity status, and one
repair status. Repair statuses are:

- `READOUT_ALREADY_EQUAL__FINAL_GATES_PASS`;
- `REPAIR_VALID`;
- `EXACT_READOUT_FOUND__FINAL_GATE_FAILURE`;
- `SEARCH_EXHAUSTED__CAPACITY_PRESENT`;
- `SEARCH_EXHAUSTED__CAPACITY_ABSENT_OR_PARTIAL`;
- `SEARCH_NUMERICALLY_AMBIGUOUS`;
- `PARENT_CONSTRUCTOR_INELIGIBLE`;
- `INTEGRITY_INVALID`.

Protocol-level statuses are:

- `Q10_SR_STAGE2A_VALID__REPAIR_FOUND` when all integrity and coverage gates
  pass and at least one eligible mismatched event obtains `REPAIR_VALID`;
- `Q10_SR_STAGE2A_VALID__NO_REPAIR_WITHIN_FROZEN_SEARCH` when all integrity and
  coverage gates pass but no eligible mismatched event is repaired within the
  frozen search;
- `Q10_SR_STAGE2A_VALID__READOUTS_ALREADY_EQUAL` when every eligible endpoint
  is already bitwise equal and all final gates pass;
- `Q10_SR_STAGE2A_VALID__MIXED_DIAGNOSTIC_OUTCOME` for other integrity-valid
  mixtures that do not satisfy a stronger status;
- `Q10_SR_STAGE2A_NUMERICALLY_AMBIGUOUS` when arithmetic cannot be resolved
  under frozen rules;
- `Q10_SR_STAGE2A_INVALID` for lineage, coverage, purity, support, boundary,
  reserve, bounds, clipping, receipt, or replay failure.

No valid status means the repair is scientifically exchangeable, meaningfully
directionally separated, behaviorally equivalent, or suitable for DH-08B.

## Staged qualification and review

Stage 1A, if later authorized, uses seed `9501` and exactly 1,024 events. It
must produce complete per-event mismatch, move-bank, capacity, search, and
final-gate receipts plus at least one independently replayable event from each
side/tau combination.

Stage 1B may begin only if Stage 1A's source identity, executable identity,
coverage, observer purity, complete receipts, independent committed-byte
replay, and all fail-closed gates pass without changing this contract. It uses
seeds `9502..9505`, adds exactly 4,096 events, and produces 5,120 cumulative
events.

Any change to lineage, endpoint reconstruction, sequential arithmetic, move
legality, reserve, budgets, ranking, tolerances, receipt schema, or reviewer
after Stage 1A requires a new protocol identity and fresh engineering seeds.
No top-up is permitted.

The independent reviewer must reconstruct selected move effects and final
states from committed bytes without trusting cached readouts. It must verify
the parent hashes, seed firewall, exact event count, deterministic replay,
search budgets, final reserve, support, boundaries, axis, norm, complete
readout equality, and absence of behavioral fields.

## Required pre-execution freeze

Before any source, build, or run is authorized, a reviewed freeze must add:

- source manifest and source SHA-256 identities;
- executable SHA-256 and D: target-build receipt;
- production sequential-readout source identity and arithmetic audit;
- exact binary32 ordered-key, ULP-distance, `nextafter32`, signed-zero,
  subnormal, NaN, infinity, and bound semantics;
- storage format and hashes for event snapshots and receipts;
- SVD implementation identity and deterministic arithmetic policy;
- memory and allocation bounds for move-bank construction and beam search;
- observer-on/off invariance, RNG nonconsumption, no-mutation, finite-value,
  determinism, smoke, unit, and performance tests;
- independent reviewer identity and replay schema;
- explicit rejection of scientific seeds, measured CLI, behavior, and DH-08B.

Until that freeze exists, this protocol remains documentation only.

## Assumptions

1. Q10-SM's exact endpoint constructor can be replayed on fresh engineering
   states without altering its frozen semantics.
2. Model weights, bounds, products, accumulators, and stored drive outputs use
   finite IEEE-754 binary32 where the production learner does so; any nonfinite
   value fails closed.
3. The production learner's operation order, including fused or unfused
   arithmetic, is part of the scientific object and must not be optimized or
   reassociated by the observer.
4. Ordered-binary32 ULP distance uses a frozen total ordering that distinguishes
   signs and signed zero; NaN and infinity are invalid rather than assigned a
   convenient distance.
5. A legal ULP move is an actual adjacent binary32 storage value, not addition
   of an estimated decimal epsilon.
6. One-move effects measured at the initial endpoint are a local capacity
   diagnostic. They need not remain additive after another move.
7. SVD capacity analysis is continuous and relaxed. It neither proves nor
   disproves discrete repairability.
8. The bounded beam search is a constructor with finite coverage, not a proof
   procedure. Search exhaustion is not impossibility.
9. Exact sequential readout equality is necessary for a repaired endpoint but
   insufficient without all geometry, support, boundary, reserve, and integrity
   gates passing simultaneously.
10. The 16-step final reserve, 16-step per-coordinate spend, 64-move total
    budget, beam width 64, and branch width 64 are conservative engineering
    choices fixed without behavioral evidence.
11. The f64 cue, axis, and norm tolerances are engineering qualification gates.
    They are not biological, behavioral, or exchangeability thresholds.
12. An already-equal endpoint is informative about storage mismatch frequency
    but supplies no evidence that a nontrivial repair exists.
13. Parent-constructor-ineligible events remain in coverage and cannot be
    replaced, while repair rates use a separately reported eligible denominator.
14. No outcome may change the repair budgets, tolerances, seeds, status rules,
    or future direction and behavior gates.
15. Future behavioral, direction-effect, exchangeability, hidden-learning-state,
    future-plasticity, and metaplasticity claims remain unset.

## Explicitly forbidden claims

Q10-SR cannot establish or authorize:

- Q08 vindication or reinterpretation of Q09, Q10-BG, or Q10-SM;
- global box-constrained freedom;
- a scientifically meaningful amount of directional separation;
- scientific exchangeability of true and repaired endpoints;
- a direction effect, behavior effect, or future-learning effect;
- hidden learning state or metaplasticity;
- DH-08B.
