# Q07-BoundedNull-v1 — constructor qualification only

No DH07R behavioral study is authorized by this qualification artifact. DH07
remains BLOCKED_PRESEAL_QUALIFICATION and immutable. No seed 7000..7031 is used.

Development seeds: 9000..9003. Holdout qualification seeds: 9004..9005.
Both sides R/L, taus 4/16, parallel absent/present. Use the inherited DH06 true
endpoints, 256 acquisition and 256 reversal trials. Capture event states at
1,16,32,64,128,256 and first maximum/minimum true boundary occupancy per
trajectory. These are observational states, not a new behavioral hypothesis.
No null is committed to the learner during state collection. Qualification
therefore does not establish robustness on a future null-policy trajectory.

Allowed support: edges where the pre-bound interval contribution
`f64(step)*(f64(interval_eligibility)-f64(cue_eligibility)) != 0`.
This is a permissible coordinate set, not an equality of realized nonzero sets.
The true endpoints retain DH06's realized-support decomposition exactly.
The acquisition axis used for diagnostics is `f64(WA)-f64(W0)`.

Constructor starts at the feasible true displacement and rotates triples of
supported coordinates. Each circle preserves the triple's dot with the
restricted acquisition vector and its squared norm. Feasible angular intervals
are solved from box intersections, rather than clipping candidates. Each move
reduces absolute global residual correlation when possible. Eight deterministic
shuffled sweeps; budget is fixed before development results. No claim of global
minimum decorrelation: report best found within this search budget.

The RNG key includes protocol salt, seed, tau bits, side, reversal trial, event
ordinal (one reward event per trial), and sweep; excludes scientific condition.
It consumes no simulator RNG. Final f32 states are reconstructed and inspected.
Axial error uses absolute units and error divided by total true norm as well as
relative-to-axial magnitude: a nearly zero axial target must not create an
ill-conditioned sole acceptance criterion. Record total and residual norm
errors, full-axis and support-residual cosines, realized supports, boundary
counts and memberships. No numerical or separation thresholds are promoted
until development qualification is analyzed. Freeze proposed thresholds and
source before holdout qualification. A failed holdout is not repaired or topped
up in this version.

Global-axis residuals may have fixed coordinates outside allowed support.
Search uses the restricted axis; reporting uses the full-axis definition too.
The outside-support residual is not falsely treated as freely rotatable.

Separate DH06 post hoc clamp audit replays original seeds6000..6031 both sides,
taus and four causal E conditions, with behavior parity against archived
outputs. No confidence intervals, new samples, or retroactive hypothesis.
Report clamp correction separately from f32 arithmetic/special both endpoint
rounding. Archive the diagnostic executable and hashes BEFORE either replay.

Constructor failures remain qualification observations. They do not authorize
weaker nulls or modified DH06 dynamics. Preserve all development results and
version provenance; do not overwrite sealed ancestors.
