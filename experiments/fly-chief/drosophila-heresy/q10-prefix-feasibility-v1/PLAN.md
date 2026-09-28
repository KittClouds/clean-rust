# Q10-PF1 Prefix-Constrained Multi-ULP Repair Feasibility

## Question

Q10-DN3 showed that committed multi-ULP endpoint effects expand the sequential
f32 readout span, but its SVD treated every endpoint effect as an independently
selectable column. Q10-PF1 tests the next constraint: each coordinate may take
one final endpoint only, so its legal effects are a single choice from the
zero/down-prefix/up-prefix hull.

This is a qualification-only engineering audit. It does not run a repair,
apply any candidate to a learner, inspect behavior, or authorize DH-08B.

## Frozen sample and method

Fresh engineering seeds are `9651` and `9652`. Each seed is run on both sides
(`R`, `L`) and both taus (`4`, `16`) at trial `128`, yielding eight events.
The parent Q10-SM construction and all task/simulation randomness remain
frozen. The parent event supplies a safety-margined committed alternate state;
the PF audit measures whether its sequential cue-by-MBON readout mismatch can
be cancelled by a relaxed product of per-coordinate endpoint hulls.

For each eligible coordinate, the endpoint set is exactly:

- zero movement;
- each legal committed down-prefix through 16 ULP steps;
- each legal committed up-prefix through 16 ULP steps.

Each endpoint is evaluated with the actual sequential f32 readout order. The
relaxation permits a convex coefficient over one endpoint hull per coordinate,
which is deliberately weaker than the real prefix-discrete problem. A
deterministic block Frank-Wolfe relaxation runs for 12 passes and records its
residual curve.

## Interpretation frozen before execution

- A finite-pass residual ratio at or below `1e-6` is a **relaxed fit** only;
  it authorizes a future exact prefix-search qualification, not scientific
  inference.
- A partial relaxed fit does not prove that the exact prefix problem is
  outside the convex hull, because the fixed relaxation may simply need more
  passes or a different solver.
- Any nonfinite value, nonmonotone residual curve, duplicate/missing event,
  stale source manifest, or firewall violation invalidates this run.
- No result from this protocol can authorize DH-08B or open scientific seeds.

## Firewall and lineage

The Q10-SM hashes are checked at seal and execution. The output contains only
engineering fields: readout mismatch norms, endpoint counts, relaxed residuals,
and pass curves. It contains no accuracy, reward, action, old-map, or behavior
field. The independent reviewer verifies the eight-event coverage, manifest,
finite metrics, monotone relaxation curves, and firewall.
