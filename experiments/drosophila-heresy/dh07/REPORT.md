# DH-07: control failed qualification before measured execution

The planned direction-specificity experiment did not run. Constructor-first
qualification exposed two different failures at the first reversal update on
non-measured seed 9000 (right slice, tau 4):

| Context | Observation | Consequence |
|---|---|---|
| Parallel absent | True delivered update had acquisition-axis cosine -0.00081658, exceeding the provisional 0.000005 gate | True and strictly orthogonal null would not differ only in off-axis direction |
| Parallel present | All 64 null candidates violated weight bounds | No valid null could be delivered by the specified constructor |

The true conditions reproduced DH-06 final weights, learning curves, and
acquisition hashes exactly on this qualification bundle. An independent Python
recomputation from saved f32 states reproduced both geometry measurements and
all 64 bound failures. Each candidate violated bounds at 175–228 coordinates;
its ideal joint-orthogonality cosine remained below 5.5e-18.

**Decision: BLOCKED_PRESEAL_QUALIFICATION.** The 32 planned measured seed bundles
remain unused. This is neither support for nor evidence against direction
specificity. It does not prove that every constrained null is impossible.

DH-06's behavioral differences remain observed. Its stronger interpretation as
an effect of exactly axis-free delivered plasticity needs correction: final
clipping can introduce axial movement. How much this contributes to behavior
has not been measured.

The next design should first qualify a bounded control that matches realized
axial movement and perturbation magnitude. That changes the control contract
and needs a new preregistration; clipping or weakening the present null would
not repair this experiment.

## Verification and limits

Sol high implemented the prototype; the parent reviewed it during development,
identified missing geometric checks, independently verified all six ancestor
archives, and replayed the failed vectors. Final release tests passed 48/48
with eight explicitly ignored tests; Clippy passed. These verify prototype
software behavior, not scientific launch readiness. Both launch entry points
are disabled.

The original receipt-producing executable was overwritten before its hash was
captured. Saved vectors and their independent replay support the reported
failure, but binary provenance for that qualification is incomplete. The
prototype also lacks event-indexed null randomness and the full scientific
analysis/qualification pipeline. Current-source fingerprints are recorded
separately and must not be mistaken for a pre-execution scientific seal.

Evidence: `qualification/constructor-first-real-seed9000.json`,
`../supervision/dh07/snapshot_audit.json`, and
`../supervision/dh07/REVIEW.md`.
