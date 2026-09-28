# E007 protocol and stop boundary

## Question

Does a feature-based estimate of expected inspection value transfer across independently generated worlds better than a domain lookup, a smoothed domain lookup, or matched random routing?

## Frozen design

- Fit all three learned routing models only on eight development worlds (2,048 episodes total). Freeze model parameters before constructing or opening held-out labels and source replies.
- Generate sixteen held-out worlds (384 episodes each) from independent seeds. Four strata of four worlds stress familiar domain IDs, new IDs, reliability shifts, and high/inverted source staleness.
- Preserve the public feature schema. The feature router receives no world or domain identifier. Public query cost is available to all routers.
- Compare exact call budgets 16, 32, and 64 within every world for the development domain table, smoothed table, feature router, and matched random. Include a zero-call floor.
- Keep labels and source replies in separate, sealed files until every route plan is durably written. The evaluation-only oracle then ranks realized counterfactual task deltas and reports a ceiling; it cannot produce a runtime proposal.
- Record wrong-to-right, right-to-wrong, unresolved, avoided wrong commits, completed tasks, marginal completion gain per paid call, paid cost units, query and resolver latency, journal bytes, exact-budget compliance, and replay identity.
- Route every inspection through `rdc-runtime-contracts-v1`: durable intent, stable request ID, endpoint response, durable outcome receipt. Unknown and Failed inspection results reobserve without task action authority.

## Generators

Development and held-out world recipes are deterministic from the frozen seed schedule and are written before scoring. The four held-out strata and parameter ranges are declared in `src/domain.rs`; episode randomness is an independent SplitMix64 stream per world. Each held-out bank has four familiar domain IDs and eight new IDs, with 32 episodes per domain.

## Stop boundary

Working standalone runtime, passing tests, completed exact-budget benchmark, crash/recovery tests for the extracted paid-action contract, independently checked source/artifact hashes, and a paired transfer report with a bank-specific ceiling. No LLM, scratchpad, adaptive budget, or production inspector is included.
