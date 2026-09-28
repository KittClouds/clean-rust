# E012 Bank Amendment A12 — Paired Counterfactual Repair

**State:** construction repair; no observer or model contact.

## Finding

`E012-BANK-A11` showed that the v1 bank did not isolate its declared channels. In every action-support family, paired tasks had different producer-order coordinates. The candidate-only families also had the same executable passing-role set in both members of each pair. The original action maps could change across other channel twins as well.

## Repair contract

1. In a declared single-channel pair, hold all observer-visible fields other than the named channel fixed. This includes the exact action-ID sequence, action-ID-to-patch binding, opaque observer task ID, and task variant.
2. In the two joint `E_t × E_x` families, use a complete 2×2 design. Hold candidate identities and producer order fixed across all four frames. Each single-factor pair must change the executable valid-action set.
3. For `E_c.content` pairs, keep `E_t`, `E_x`, `E_r`, action-ID sequence, observer task ID, task variant, and tests fixed. Change the patch bound to stable action IDs, and require the executable valid-action-ID set to change. The frame's producer coordinates remain unchanged.
4. Keep all observer-visible task IDs and variants identical within each counterfactual block. The sealed truth index retains unique internal task IDs and records the corresponding presentation ID.
5. Make each action-support family exact-balance its valid/invalid labels by action ID and producer position. The prefix family has two valid options per row and balances both classes; other action families have one valid option per row. Abstention controls have no valid candidates.
6. Make the `help-color-capability` narrow-width distractor return the wrong color mode. Make `map-order-feature-contract`'s redundant sort distractor omit one key. These candidate mutations remove two behaviorally equivalent extra passes while leaving the selected task contracts intact.
7. Freeze the repaired task source, candidate patches, paired assignment solver, runner, and harness inputs before rerunning executable candidate checks. Derive final labels from that rerun, then project and audit frames and receipts. Preserve every v1 artifact and failure.

## Boundary

This amendment changes only the downstream R&D task bank and candidate fixtures. It does not change E009 observer bundles, prompts, normalization, thresholds, E002 authority, E011 receipt semantics, or any upstream research record. Model contact remains prohibited until a new `FROZEN_BEFORE_MODEL_CONTACT` lock covers the repaired bank and audits.
