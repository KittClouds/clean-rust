# DH-07 protocol status: blocked before seal

DH-07 was intended to test whether the DH-06 off-axis update has direction-specific behavioral effects. The planned study had eight conditions: immediate, quiet, neither, parallel only, true perpendicular, null perpendicular, both true, and parallel plus null. Its single scientific primary was the right-slice learning-arm, trial-256 old-map-margin contrast between true and matched-null directions, averaged across parallel-absent and parallel-present contexts with a paired 95% interval.

No DH-07 scientific protocol was sealed and no measured seed was run. Constructor-first qualification blocked the study.

## Strict control contract

For each causal event, the prototype preserves the DH-06 true endpoint, defines the bounded realized true displacement `P = W_T - W_B`, and attempts to construct a null on the same active support that:

- has the same committed-f32 L2 norm as `P`;
- is orthogonal to the masked acquisition axis;
- is orthogonal to `P`;
- stays within `[0, 2]` without final clipping;
- uses at most 64 deterministic candidates and no simulation RNG.

The provisional committed-f32 numerical gates were `5e-6` for relative L2 mismatch and both null cosines. The same `5e-6` threshold was applied to realized true-axis cosine because true and null cannot be described as differing only in off-axis direction if the bounded true endpoint carries a larger acquisition-axis component. These thresholds were set before the non-measured real fixture. They were not promoted to a final preregistration.

## Constructor-first qualification

The declared fixture was right slice, tau 4, seed 9000, outside the planned measured seeds `7000..7031`. Both true endpoints exactly reproduced their DH-06 counterparts in final weights, learning curve, and acquisition-state hash.

Qualification then failed at reversal event 1 in both null contexts:

| Context | Result |
|---|---|
| no parallel | realized true-axis cosine `-0.0008165776`; failed before null search |
| parallel enabled | true-axis cosine `-4.7245e-9`; all 64 candidates violated bounds |

The full receipt contains active support indices and committed `W_B`, `W_T`, and masked-axis values for independent recomputation. Its SHA-256 is `B0807C8BCF6A3A0595570AC7215890276A5E7A21A74F79D6AFEA6E265796CFAA`.

The independent parent audit recovered the saved f32 values, reproduced both true displacement cosines and norms within `1e-12`, and replayed all 64 candidates. Every candidate violated bounds on 175 to 228 coordinates while ideal null cosines remained at most `5.44e-18`. This confirms the recorded sampled-direction failures came from bounds rather than numerical orthogonality. It still does not prove that every possible constrained null is infeasible.

## Decision

Status is `BLOCKED_PRESEAL_QUALIFICATION`. No measured execution, inference, analysis pipeline, plot, seal, or DH-08 work is part of this prototype. `scripts/seal_run.py` is a fail-closed guard.

The DH-06 behavioral arm differences remain measured results. This audit narrows their interpretation: DH-06 projected before final clipping and did not measure delivered axis leakage, so a pure axis-free mechanism was stronger than the recorded intervention justified.

## Prototype limitations

- The dedicated null stream key includes seed, tau, and side, but the current prototype omitted reversal event index from the counter key. The first-event qualification remains exactly reproducible, but the implementation does not satisfy the planned event-indexed stream contract for a full run.
- Realized rewards are action-dependent. Only simulation RNG and exogenous schedules can be paired once interventions diverge.
- Matching is conditional on each arm's current state; it is not a claim of equal cumulative exposure across diverging trajectories.
- The exact receipt-producing test executable was overwritten by later test-only compilation before its SHA-256 was captured. The receipt, saved snapshots, command, timestamps, and unchanged scientific core are preserved, but binary provenance is incomplete.
- The current source is a blocked constructor prototype. Analysis and launcher logic for the planned scientific study were deliberately not completed.

A future study would need a separately preregistered bounded control that matches both delivered acquisition-axis component and perturbation magnitude, or a redesigned intervention whose true and null endpoints inhabit the same feasible tangent geometry. That would be a new protocol, not a silent repair of DH-07.
