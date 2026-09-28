# E012 Phase 3 — Frozen Full-Frame Baseline

## Question

Does the unchanged E009 v5 switchboard still show a bounded direct-action region on E012's fresh, precontact-audited coding tasks?

This run is admission for frame decomposition. It is not an intervention result and does not identify which frame channel supports a decision.

## Frozen components

Keep the candidate producer, producer ordinals, presentation receipts, small and large observer bundles, prompts, chat templates, output schema, percent-to-milli normalization, 850/150 thresholds, E011 presentation binding, and E002 authority fixed. No prompt edits, model changes, threshold fitting, channel masking, channel swapping, candidate sorting, or task selection based on observer outputs.

Both observers receive the same 48 full-frame observations. The bank has 20 pair groups: 16 groups contain two tasks and four factorial groups contain four tasks. Paired task variants may share a public task ID; the frame digest is part of the sample identity. Do not collapse a pair group by public task ID.

## Paired lanes

1. **Small only:** accept the small observer proposal only when its output compiles against the offered actions and passes the frozen thresholds.
2. **Large only:** apply the same contract and thresholds to the large observer.
3. **Small then large on abstention:** replay the small output first; use the large output only when the small output is invalid, ineligible, or abstains. If the large observer also abstains, the task does not complete.

The harness queries both observers on every full-frame sample to preserve paired comparisons. Report physical queries separately from the hybrid route's counterfactual large-call count, tokens, and elapsed time.

## Outcomes and authority

The hidden completion label comes from the frozen candidate executable checks. A selected patch completes only if it passes the task's frozen checks. Any offered candidate is a legal proposal at the presentation boundary; a legal proposal can still be semantically wrong and fail completion.

Bind each proposal to the full-frame digest, stable request ID, ordered candidate IDs and patch digests, and presentation receipt. Run the accepted proposal through the E011 producer-order resolver and E002 deterministic authority. An abstention or invalid response authorizes no task action. Receipts and action ledgers are replayed by the validator.

## Measures

For each lane, report completion, accepted coverage, precision among accepted direct actions, wrong legal actions, abstentions/rejections, calls by model, prompt and generated tokens, summed route time, p50/p95 request time, per-repository and per-family breakdowns, authority rejections, illegal commits, action effects, duplicate effects, presentation verification, and replay identity.

Repository is a transfer stratum. Show each repository independently before pooled descriptive totals. Preserve task and family slices so a favorable pooled average cannot hide a failed stratum.

## Admission rule for frame interventions

The frozen small observer demonstrates an action region on this bank only if it accepts at least one direct action and every accepted direct action completes the task. This is a zero-error gate for the accepted small-model region; no tolerance is fitted on this bank. If the gate fails, preserve the baseline and diagnose before running channel interventions.

Passing this gate admits a subsequent prospective frame-decomposition experiment. It does not establish evidence dependence, a mechanism, broad repository transfer, or a product claim.
