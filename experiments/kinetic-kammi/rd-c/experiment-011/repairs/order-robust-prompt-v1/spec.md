# E011-R3 — Candidate Order Prompt Repair

This is a downstream repair diagnostic on the already-open E010 bank. E011 and E011-R1/R2 remain sealed and unchanged.

## Change

Keep the E009 v5 small-model weights, output schema, normalization, runtime mode, and 850/150 thresholds. Give the small observer a new prompt that explicitly treats candidate order and numeric IDs as arbitrary labels, compares candidates by their summaries and diffs, and abstains when it cannot identify a content-supported choice. This creates a new observer wrapper identity.

## Paired inputs

- `full-frame`: the exact E010 held-out observer frame.
- `order-only`: the exact E011-R2 shuffled option order with original E010 IDs restored.

Only the small observer is rerun. For fallback scoring, reuse the frozen large observer outputs for those exact frames: E010's full-frame large outputs and E011-R2's order-only large outputs. Reuse E010 labels only as already-opened engineering diagnostic truth.

## Measures

Per repository and condition: small coverage, direct precision, wrong accepted actions, hybrid completion, large calls, tokens, and model time. Compare the new prompt against the frozen v5 small outputs and identical large fallbacks.

## Boundary

No labels are used to change the prompt after scoring. No threshold fitting, training, action execution, or upstream transfer claim. This can identify a practical prompt repair on this bank; it cannot establish general order invariance.
