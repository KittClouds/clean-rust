# Q10-RESID-VALUE1

Read-only reachable-value audit for the 29 `MOVABLE_NOT_TARGETABLE` residual
rows identified by RESID1-R1 in `R tau4 set3`.

The primary domain is the valid order-1, order-2, and order-3 frontiers only.
For each residual row, this identity records exact f32 output bits reached at
each order, first order of appearance, ULP distance to target, and deterministic
directional descriptors. It does not infer values for unmaterialized invalid
compound states.

Fixed descriptive patterns are:

- `TOWARD_ONLY_NO_HIT`
- `AWAY_ONLY`
- `MIXED_DISTANCE`
- `DISTANCE_PLATEAU`
- `TWO_SIDED_NUMERIC`
- `ONE_SIDED_NUMERIC`
- `NUMERIC_SIDE_UNDEFINED`

The pattern labels are descriptive and do not promote a mechanism. No replay is
performed; order 1 uses the complete materialized singleton readouts, order 2
uses the complete valid frontier readouts, and order 3 uses the exact residual
value sidecars.
