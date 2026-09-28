# E011-R1 — Candidate Canonicalization Repair

## Trigger

The E011 candidate-permutation lane changed two small-observer proposals from correct to wrong accepted actions. In both cases the observer selected displayed position two before and after the combined order-and-ID perturbation. E011 did not distinguish order from numeric IDs.

## Repair

Before observer contact, sort action options by their stable patch SHA-256 digest and assign canonical IDs 1 through N. Keep a receipt mapping each canonical ID and patch digest to the original runtime action ID. The observer sees only the canonical frame. The deterministic runtime maps the typed proposal through that receipt and then validates the original action ID as usual.

This wrapper receives a distinct adapter identity, candidate-canonicalization-v1. The E009 v5 weights, prompt, output schema, normalization contract, and 850/150 thresholds remain frozen. This is a repair test, not a replacement or rewrite of E011.

## Test

- Rust unit tests verify invariance to action order and incoming IDs, mapping restoration, and rejection of ambiguous duplicate patch digests.
- On the E010 bank, canonicalize both the original frame and E011's permuted frame. Their model-visible canonical frames must be byte-equivalent for all 16 paired tasks.
- Run each frozen observer once per canonical task, shadow-only, and map every accepted proposal back to the original E010 authority action ID.
- Report per repository: direct coverage/precision, hybrid and always-large counterfactual completion, large calls avoided, model time, tokens, and mapped-action validity.

The labels were already opened in E010. Results on this bank can validate the adapter and diagnose restored behavior; they cannot establish independent generalization.
