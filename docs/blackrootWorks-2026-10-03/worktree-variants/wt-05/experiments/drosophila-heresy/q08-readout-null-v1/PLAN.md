# Q08-ReadoutNull-v1

Status: `CONSTRUCTOR_QUALIFICATION_ONLY_NO_SCIENTIFIC_SEEDS`

## Purpose

DH-08A remains `INCONCLUSIVE`. This qualification asks whether a bounded f32 learner admits a
decorrelated residual endpoint with matched realized geometry and matched cue-by-MBON input drives.
It produces constructor evidence only, never a behavioral hypothesis test or a measured DH-08B result.

The lineage E arm uses uniform modulation in this synthetic model. This qualification does not
establish anatomical-routing advantage, a biological mechanism, or recoverable latent memory.

## Reserved scope

- Qualification seeds: 9200 through 9205 only.
- Tau: 4 only; sides R and L.
- Ordinary lineage acquisition and 256 reversal events.
- Canonical path always commits the endogenous parallel-off true-perpendicular endpoint.
- Alternative endpoints are disposable shadows.
- No measured mode, seed top-up, or access to future scientific seed bundles.
- Initial smoke: seed 9200 only. Full qualification requires review of its receipts and implementation.

## Constructor

For each immutable event snapshot, use committed common endpoint `W_B`, committed true endpoint
`W_T`, and the predeclared acquisition axis `A`. The permitted intervention support is inherited
from the pre-bound interval-derived update. Preserve true endpoint boundary membership exactly.

Partition weight coordinates by postsynaptic MBON and the 16-bit cue-membership signature. Rotations
within a group preserve the sum of displacement coordinates and therefore every cue-by-MBON drive
in real arithmetic. In four-coordinate groups, rotate in the nullspace of the all-ones vector and
the local acquisition axis, while preserving displacement norm. Start from the feasible true endpoint,
stay within the weight box, and reduce global residual alignment deterministically.

All validation uses stored f32 endpoints. The constructor consumes no simulator RNG and allocates
nothing during the event hot loop. Group indexes and numerical scratch are preallocated.

## Gates frozen before smoke

Every nonzero intervention must pass:

- realized axial absolute error divided by true displacement norm <= `1e-7`;
- relative total displacement norm error <= `1e-7`;
- relative acquisition-orthogonal residual norm error <= `1e-7`;
- absolute true/null residual cosine <= `1e-5`;
- exact boundary membership;
- zero changes outside permitted support;
- realized nonzero-support count relative difference <= `0.01`;
- zero bound violation and zero hot-loop allocations;
- maximum absolute cue-by-MBON normalized input-drive difference <= `1e-7`;
- maximum absolute 16-cue deterministic decision-score difference <= `1e-7`.

The normalized drive is the model's actual sequential f32 sum divided by its frozen MBON denominator.
The decision score is the model's sum of action-signed MBON probabilities, divided by MBON count,
before multiplying by an acquisition label. Audit each cue separately; cancellation in an average
is not accepted. Report probability differences and distractor-drive differences descriptively.

Zero residual cases are recorded separately and must not be falsely counted as decorrelated nonzero
events. Gate failure is a qualification failure. No gates may be loosened after inspecting smoke.

## Feasibility diagnostics

Report the eligible/interior support, signature groups, group sizes, nullspace rank, accepted moves,
and fixed-versus-rotatable displacement energy. Compute an optimistic unbounded residual cross-dot
range under the group constraints. If fixed energy makes the target cosine unattainable even without
bounds, identify structural overconstraint rather than blaming numerical optimization.

Report failures by gate and event/window. Keep every event; do not select a subset that passed.
No task accuracy or reward-based criterion may tune the constructor.

## Future experimental interpretation

Only a qualified constructor can support a separately frozen fresh-seed DH-08B. Its comparison would
be an adaptive policy that preserves cue-by-MBON drive at each current state's intervention while
replacing residual direction. Cumulative doses and later states may diverge between policies.

Matched immediate cue readouts do not imply matched future behavior, distractor responses, or trace
formation. Conversely, failure to find a null here establishes a limitation of this constructor and
contract, not a proof that all readout-matched feasible alternatives are impossible.
