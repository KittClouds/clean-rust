# Q07-BoundedNull-v1 qualification report

Status: `CONSTRUCTOR_QUALIFIED_FOR_PROTOCOL_DESIGN`.

This was a constructor qualification, not a behavioral experiment. Seeds
7000..7031 remain untouched. It used designated development seeds 9000..9003
and holdout seeds 9004..9005 across both slices, taus, and parallel contexts.

## What is now controlled

At each current f32 state, the constructor starts from the feasible committed
true displacement. It rotates triples of permitted interior coordinates on
circles that preserve acquisition-axis projection and L2 norm, while remaining
inside the weight box. It keeps every true boundary membership fixed. The
stored f32 null is then independently remeasured.

The null policy therefore matches the realized true update on:

- acquisition-axis displacement;
- total and residual L2 magnitude;
- permissible intervention support;
- exact lower/upper-bound membership;
- timing and current state.

It changes residual direction. The result is an adaptive direction-replacement
policy because later matching occurs in the state produced by earlier nulls.

## Qualification results

The snapshot holdout included 128 recorded slots (118 unique states after
duplicate extrema). Every check passed. Maximum committed-f32 values were:

| Quantity | Maximum |
|---|---:|
| absolute residual cosine | 8.49e-9 |
| axial error / true update norm | 1.23e-8 |
| total-norm relative error | 9.48e-9 |
| residual-norm relative error | 9.48e-9 |
| boundary membership differences | 0 |

The stronger closed-loop qualification applied the null at all 256 reversal
events on 48 trajectories: six qualification seeds, two slices, two taus, and
two parallel contexts. All 12,288 interventions passed the predeclared gates;
4,096 belonged to holdout seeds. Maximum residual cosine was 2.40e-8 and
maximum axial error divided by true norm was 3.08e-8. No hot-loop allocation,
bound violation, outside-support change, boundary-membership change, or support
count gate failure occurred.

Independent NumPy recomputation checked all 384 saved closed-loop witness slots
against committed f32 vectors. No behavioral outcome was analyzed.

## Development history preserved

Revision 1 produced strong decorrelation but reduced true boundary occupancy by
16–48% (median 33%). Before holdout inspection, revision 2 promoted exact
boundary membership into the constructor contract. Development artifacts from
both revisions remain archived. The holdout gates were frozen before seeds
9004–9005 were collected.

## What this does not establish

Qualification does not establish a behavioral direction effect, a biological
mechanism, a global optimum of the constrained rotation problem, or robustness
outside these states. It authorizes writing a frozen DH-07R protocol using this
exact constructor. It does not authorize changing thresholds after measured
execution.

Evidence is under `artifacts/20260915T215102Z` and
`artifacts/20260915T215754Z`. The diagnostic executable and source were archived
before every qualification execution.
