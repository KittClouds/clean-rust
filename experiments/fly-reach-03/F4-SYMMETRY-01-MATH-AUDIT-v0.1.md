# F4-SYMMETRY-01 — source-grounded math audit v0.1

Status: **draft, qualification-only, pre-implementation**. This is not an execution seal. It creates no measured namespace, classifier fit, or outcome. F4-PRECISION-01 and the REACH-03 authority remain unchanged.

**Supersession note:** the open definitions in this audit were resolved in `F4-SYMMETRY-01-CONTRACT-v0.1.md`. The final admissible base is 66 fields, not the provisional 76-field arithmetic estimate: the field audit also removes ten reserved zero-padding channels. The legacy expected-score fields are provenance-only and excluded from the scientific arms. D is a canonical relational sidecar.

## Question and evidential limit

Does a task-relative representation improve held-out-block extraction of reference polarity, with the estimator, rows, folds, and training budget fixed? A positive result would identify a useful representation choice. It would not prove that independently seeded blocks are exact symmetry transforms of one another, nor that the native rule receives the information.

The previous precision result is a bounded negative for float32 feature quantization as the operative bottleneck in the frozen 80D map: the float64 and quantized-feature float64 arms made identical classifications at reported precision on the pooled and margin-ladder populations. It does not establish sufficiency of the 80D map.

## Source-derived reference relation

At a fixed pre-delivery state, let `i` be a KC-to-MB edge with postsynaptic index `j`, `c` a task cue, `I_ic` its incidence in that cue's pattern, `y_c` its label sign, `a_j` the *action_sign* of post `j`, `d_j` its denominator, `b_j` its bias, and `p_cj = sigmoid(2 (drive_cj/d_j - b_j))`. The cue score is `s_c = sum_j a_j (p_cj - 1/2)`. The reference code computes, before its final float32 cast,

```
g_i = (8 * reference_lr / cue_count) * (a_j / d_j)
      * sum_c I_ic * y_c * sigmoid(-4*y_c*s_c) * p_cj*(1-p_cj).
```

This exposes a legitimate task-relative question: the sign depends on **relations among cue incidence, cue label, action role, and current task state**, plus interactions and cancellation across cues. The equation is an audit of the target, **not permission to supply the reference coefficient, score-gradient terms, `g`, or its sign to a predictor**. Candidate feature fields must be separately classified as allowed task/state inputs under the F4 calibration contract.

## Actual transformation audit

1. A joint permutation of cue patterns and labels, with cue IDs remapped in the schedule, is a relabeling symmetry of the mathematical reference sum at a fixed state. Its character is `chi = +1`: the reference vector is unchanged. Merely permuting labels, patterns, or schedule alone is not this symmetry.
2. Permuting the 32 distractor identities together with every schedule reference is likewise a representation relabeling. Reordering the 12 distractor **events** within a trial is not generally a native-trajectory symmetry because state updates are sequential.
3. Simultaneously replacing every task label sign `y_c` and every `action_sign[j]` by its negative leaves the fixed-state real-arithmetic reference direction invariant (`chi = +1`): cue scores reverse, `y_c*s_c` is preserved, and the two sign changes cancel. Flipping only labels or only action signs has no general `chi = -1` law.
4. A postsynaptic or edge-coordinate permutation would require a consistent permutation of graph connectivity, weights, bias, denominator, action signs, cue patterns, and coordinate identity. No such graph automorphism has been established for the frozen substrates. Do not treat arbitrary coordinate IDs as exchangeable.
5. The four qualification task seeds (303000–303003) generate distinct patterns. Each has two positive and two negative labels, so their label vectors can be permuted into one another. That fact alone does **not** make the complete tasks equivalent. Their schedules are independently generated; none of the six block pairs has an identical same-trial distractor row. Full pattern/schedule/graph isomorphism remains unverified.

These are exact statements over the mathematical state except where noted. The implemented reference accumulates in a specific floating-point order and casts to float32; because many values sit near the `1e-12` target threshold, an algebraically exact relabeling is **not automatically a bit-exact target-label invariant**. Any future synthetic symmetry fixture must check both reference values and thresholded labels under the actual implementation before calling a transformation exact for this target.

## Legacy 80D anchor requires a provenance label

The existing 80D F4 feature map has four cue-indexed labels, four cue-indexed expected scores, four cue-indexed edge-incidence bits, 13 schedule pattern IDs, and 24 sketches whose hash key contains absolute cue index. These channels are not jointly invariant under cue relabeling.

More importantly, `qualification.rs::expected_score_for` and `precision.rs::expected_score_f64` implement the same cue-score formula used by `collector.rs::expected_score` inside `reference_delta_into`. The historical encoder spec calls the map reference-blind and forbids reference logits. The score channel is derived from task and state without reading `g`, but it is mathematically a reference-operator intermediate. **A contract amendment must explicitly decide whether this channel is allowed for the F4 calibration comparison.** Until then, call the existing 80D stream a *legacy qualification anchor*, not a proven reference-blind baseline. Do not silently remove or retain the score channel in a newly sealed arm.

## A clean prospective comparison

Hold the original qualification rows, inclusion probabilities, leave-one-block-out splits, estimator architecture, optimizer, training order, and training budget fixed. Do not repair the class-degenerate 303003 fold. Report pooled IPW-balanced error only where both target classes exist and mark every degenerate fold explicitly; preserve blockwise signed margins including the degenerate fold as descriptive orientation telemetry.

Proposed arm roles, contingent on resolving the score-channel authority above:

| Arm | Role | Controlled interpretation |
| --- | --- | --- |
| A | Reproduce the historical 80D qualification stream exactly. | Provenance anchor, with its existing cue-indexed fields. |
| B | Same controlled base plus `d` frozen deterministic transforms of that base, adding no new task/state information. | Width/parameter and extra-feature control. Avoid row-identity or target-conditioned nuisance keys. |
| C | Same controlled base plus `d` cue-slot relational fields in absolute cue order. | Explicit relation benefit relative to B. |
| D | Same controlled base plus the identical cue relational tuples sorted/canonicalized using **task/state metadata only**. | Effect of a task-relative ordering relative to C. |

For a four-cue task, one candidate six-field tuple per cue and coordinate is `(I_ic, y_c*a_j, I_ic*y_c*a_j, p_cj-1/2, I_ic*(p_cj-1/2), (y_c*a_j)*(p_cj-1/2))`, giving `d = 24`. This is a **candidate schema, not a frozen feature contract**. `p_cj` is the cue-specific local post probability already used in the earlier scalar probe; products encode relations the scalar probe did not expose. Every field must be vetted against the F4 reference-intermediate prohibition. The raw arm concatenates tuples in absolute cue order. A canonical sidecar can sort complete tuples lexicographically by their values; equal tuples are interchangeable, so this operation is invariant to a joint cue relabeling without consulting `g` or `Y`.

**Claim limit:** if all arms retain the legacy 80D fields, D only canonicalizes the *added sidecar*. A D-over-C gain supports a useful canonical relational sidecar, not full invariance of the total representation. A fully canonical replacement of legacy cue-indexed labels, scores, incidence, schedule IDs, and cue-index-dependent sketches needs its own explicitly matched comparison. Do not describe an additive D arm as a fully task-canonical encoder.

## Scoring and interpretation

Use the same scored coordinate-time rows and the same per-row inclusion weights in every arm. Score raw balanced error and unclipped `1-2*error` alongside clipped extractable observability. Keep capability-weighted polarity `Psi` and delivery-aware alignment as diagnostic quantities under their existing definitions. Use held-out block signed margin `E_q[Y * logit]`, with a stated IPW denominator, to test whether orientation becomes consistent; a positive margin in a one-class block remains a one-class diagnostic, not balanced generalization.

Read contrasts in this order: A reproduction; B versus A for width-control behavior; C versus B for explicit relations; D versus C for canonical ordering. No prediction flipping, fold replacement, model enlargement, extra epochs, or post-result feature edits. Even if D succeeds, attribution is to the frozen feature map under this estimator and four qualification blocks. No measured REACH-03 claim follows automatically.

## Pre-seal gates

Before code or a seal, resolve the expected-score admissibility and whether D means a canonical **sidecar** or a canonical **total representation**. Then freeze exact byte-level feature fields, normalization, `d`, nuisance transforms, tie handling, float precision, row set, score formulas, independent code and input hashes, and a synthetic cue-permutation/label-action-inversion audit. The latter must verify implemented `g` and thresholded `Y`, not just symbolic algebra. If the transformed target is unstable near the frozen threshold, report that as a target-symmetry limitation rather than discarding inconvenient rows.

No measured namespace, new estimator fit, biological promotion, native-rule change, PHENO reseal, or REACH-03 filtration result is authorized by this draft.
