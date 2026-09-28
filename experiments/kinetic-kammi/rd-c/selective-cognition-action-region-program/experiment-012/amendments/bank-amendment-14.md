# E012 Bank Amendment A14 — Disambiguate Map-Order Checks

**State:** downstream task-check repair; no observer or model contact.

## Finding

A13's executable checks showed that `case-02` used two keys, `z` then `a`. Reverse lexical order for that input is also insertion order, so both `reverse_native` and `preserve_order_only` passed the preserve-order task. The four map-order tasks therefore had five valid candidate instances, making the preregistered exact action-ID and position balance impossible. No A13 final labels were written; the complete A13 candidate results and failed finalization record are preserved.

## Repair

A14 changes only the case-02 test input to three keys in insertion order: `b, a, c`. The required output remains insertion order. Reverse lexical order is `c, b, a`, so it now fails; the feature-specific insertion-order candidate remains valid. Other map-order cases, task prompts, evidence channels, candidate patches, producer coordinates, thresholds, observer bundles, and authority contracts are unchanged.

The modified harness is a new immutable snapshot at `bank/construction-01/task-harnesses-a14`. A14 reruns the full candidate and base check matrix. It may reuse only content-addressed Cargo build artifacts whose cache keys include the full source and test overlay hashes.
