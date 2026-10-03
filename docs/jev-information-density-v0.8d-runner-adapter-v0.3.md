# v0.8D runner adapter v0.3

The v0.2 attempt scanned the frozen training-only metadata index and derived the support/quota objects, then stopped before any output write because the builder looked for generic profile-limit keys that the contract expresses separately for input, root, and marginal checks. The v0.2 external directory contains only its freeze receipt; its unreported in-memory scan is not a scientific result.

This fresh execution identity preserves the v0.8D contract and frozen builder. Its only additional adapter behavior is to expose three generic runtime aliases after asserting that all corresponding frozen contract values are equal: unique-input/root relative error, input/root occurrence-histogram TV, and all marginal TV limits. The contract currently sets each to `0.02`; the adapter verifies equality and value-preserves them. If any differ, it fails closed. It also inherits the v0.2 correction that removes the run-directory locator from the artifact list.

The adapter pins the v0.2 freeze, every inherited source/input hash, and its own source/test/doc hashes. It runs under `common-support-v03`. No scientific threshold, quota, sampling seed, source row, model, or Phoenix scope changes.
