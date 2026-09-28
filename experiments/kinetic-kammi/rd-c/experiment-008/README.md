# R&D-C Experiment 008: Source Offer

Tests whether a versioned pre-query source offer helps a frozen router choose paid inspections across independently seeded worlds. The offer contains source availability, source-local age, provenance family, independence, historical reliability bucket, quote price, and expiry. It contains no task answer or authoritative revision.

Authority remains the E002 deterministic state machine, with the E006 paid-query receipt protocol. `Unknown` and `Failed` return to observation without reusing the active action. A paid request uses a stable request ID; exactly-once charging is guaranteed only by the idempotent simulated endpoint.

The route budget is a maximum. Positive estimated completion value is required before ranking candidates; a lane can select zero. The run compares a no-inspection floor, frozen E007 eight-feature positive-stop model, simple offer rule, fitted offer model, shuffled offers, matched random, and evaluation-only oracle. Held-out plans are frozen before held-out labels and replies are written.

The experiment is synthetic engineering evidence. It does not validate upstream scientific claims or establish transfer beyond the generated worlds.
