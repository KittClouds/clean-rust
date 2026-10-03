# DH-07 independent supervisory review

This review is separate from Sol's DH-07 implementation. It uses archived DH-06
source and outputs, not new DH-07 measured seeds. `parent_audit.json` records the
independent checks. Ancestors are unchanged.

## Verified lineage

All six archived studies passed SHA-256 verification of their seals, 197 frozen
files, and 69 output files. In all 128 DH-06 seed/tau/slice bundles, acquisition
hashes matched between conditions within arm, recorded Z behavioral summaries
matched, binary probe margins were complementary, and hot allocation counts
were zero. DH-06 did not persist full trial-action hashes or delivered component
vectors, so these checks do not establish those stronger invariants.

## Findings that affect the next experiment

1. **Bounds can change the delivered axis component.** DH-06's geometric reward
   code projects before its final clamp. It records reconstruction error, but
   does not measure the axis component introduced by that clamp. The independent
   two-coordinate counterexample in `parent_audit.json` demonstrates this
   possibility; it does not establish its magnitude in the measured DH-06 run.
   DH-07 needs both true and null *delivered* geometry diagnostics.
2. **Null feasibility needs evidence.** The attachment's high-dimensional
   argument does not guarantee feasibility inside weight bounds. A null with
   both positive and negative entries may be rejected at many boundary
   coordinates. At a lower-bound corner with strictly positive acquisition
   axis, every feasible axis-orthogonal null is zero. Reaching 64 rejected
   candidates establishes failure of the specified constructor, not proof that
   every conceivable constrained constructor would fail.
3. **Storage arithmetic is part of the intervention.** DH-06 stores f32 weights.
   A perfectly orthogonal f64 scratch vector can lose orthogonality and norm
   equality when added and committed as f32. Gates must inspect committed
   displacement, with numerical tolerances qualified before measured trials.
   DH-06 also forms its first-pass difference as `(retained-w)-(suppressed-w)`
   and its second-pass difference as `retained-suppressed`; preserving lineage
   means documenting rather than silently changing this rounding convention.
4. **Pair exogenous randomness, not realized rewards.** DH-06 calculates reward
   from the chosen action's correctness. Different actions can produce different
   rewards even under identical RNG streams. Its protocol's claim of shared
   reward outcomes is stronger than the implementation. DH-07 should preserve
   the task and reward rule, and state the actual pairing accurately.
5. **Matching is conditional on current state.** Each arm's counterfactual true
   and null updates can match at one state while total update exposure differs
   between diverging arms. Audit both; do not draw an overlapping cumulative
   true/null plot by confusing counterfactual targets with another arm's actual
   updates. The primary estimates the effect of an adaptive intervention policy.
6. **Interpretation stays within the synthetic model.** E uses uniform gain, so
   success would not establish anatomically routed neuromodulatory advantage.
   An acquisition-axis coordinate does not establish recoverable stored memory.
   The readout computes cue-conditioned weighted sums and sigmoids; behavioral
   change alone does not demonstrate an attractor or a basin transition.
7. **Units need explicit labels.** DH-06's `reversal_perpendicular_norm` is
   divided by acquisition-vector norm, while `reversal_parallel_projection` is
   raw. Their displayed magnitudes are not directly comparable. Update energy
   fractions are squared-norm fractions, not fractions of behavioral effect.
   Most energy being perpendicular to one axis is also unsurprising in a
   high-dimensional space: an isotropic vector has expected aligned energy
   fraction 1/d in d dimensions. That reference is mathematical, not a fitted
   null for this model's heterogeneous, changing support.

## Decisions communicated before qualification

- Follow the full attachment: eight conditions; one scientific primary with a
  paired 95% interval; null orthogonal to both A and the true delivered update.
- Qualify constructor feasibility and true-cell compatibility before building
  the full measured pipeline or exposing the 32 fresh seeds.
- Preserve the 64-attempt hard failure and existing weight dynamics. Do not
  clip a null, scale it down, relax gates after results, or swap failed seeds.
- Stop at an integrity failure with an auditable receipt. A blocked control is
  not a negative result on direction specificity.
- Parent reviews qualification before internal release to sealing/execution.
  This is coordination between agents, not a request for user approval.

## Qualification evidence and decision

Sol's non-measured real-anatomy qualification used seed 9000, right slice, tau 4.
The saved receipt is
`../../dh07/qualification/constructor-first-real-seed9000.json`.
The two true conditions exactly matched DH-06 final weights, behavior curves,
and acquisition hashes on this bundle. Both null conditions stopped at reversal
event 1:

| Condition | True delivered axis cosine | Failure |
|---|---:|---|
| Null perpendicular | -0.000816577617 | Exceeds the strict numerical axis gate, 0.000005 |
| Parallel + null | -0.00000000472448 | All 64 null candidates violate weight bounds |

`audit_snapshots.py` independently recovered stored f32 values from the JSON,
recomputed displacement norms and cosines with Python's standard library, and
replayed the 64 null candidates. `snapshot_audit.json` records agreement and
the original receipt hash. Every candidate violated bounds at 175–228
coordinates, despite ideal joint-orthogonality cosines below 5.5e-18. This is
not merely a floating-point tolerance problem.

**Decision: do not seal or execute the DH-07 measured study under this control.**
The 32 fresh measured bundles remain unused. No behavioral hypothesis test was
performed. These qualification failures neither support nor refute direction
specificity. They establish that the declared control is not qualified for
this learner.

The parent review also found that the prototype counter-stream key does not
include the event ordinal. This is another unmet pre-launch requirement, but
cannot explain the reported first-event geometric failures. Preserve the
qualification version's provenance rather than rewriting the receipt after
correcting that omission.

Next design work should treat the feasible weight region explicitly and decide
how to match *realized* axial movement between true and null interventions.
That requires a separately declared control; silently clipping a null,
weakening it, or loosening these gates would change the present experiment.
The DH-06 behavior contrasts remain observed, while their interpretation as
effects of exactly axis-free delivered plasticity needs correction. The size
of clipping's contribution to those behavior contrasts is not yet measured.
