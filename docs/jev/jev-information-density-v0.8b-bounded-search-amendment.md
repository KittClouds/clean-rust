# v0.8B Bounded Search Amendment

**Status:** frozen before the next construction attempt; no model contact, feature extraction, or training has occurred.

## Preserved v0.2 failure

The first root-degree b-matching attempt reached flow 72,935 of 100,000 for CM100 and emitted no IDs. This shows the first greedy assignment of input/root identities was incompatible; it does not prove the marginal target profiles are globally infeasible.

## Frozen bounded solver search

The matching thresholds and targets in `v08b-contract.json` do not change. Permit at most 16 deterministic candidate assignments per bank:

- Each attempt ranks eligible input signatures and root identities using the same frozen capacity-first ordering; curated mode retains the v0.8 static rarity score as its primary within-capacity ranking, while random mode uses the frozen hash seed.
- Attempt index selects the next deterministic ranked window when the preceding assignment is infeasible. Group-row choices use the corresponding attempt-scoped stable hash tie-break.
- A candidate is accepted only if the full input-root b-matching flow is reached and every frozen exact and bounded composition constraint passes.
- Stop at the first passing candidate. If all 16 fail, close the bank construction with no manifest and no tolerance relaxation.

The search selects only against frozen training-side metadata and reference-bank composition profiles. It never observes model results, protected evaluation outcomes, or text. Each attempt's aggregate flow and constraint status will be retained; no candidate IDs are emitted for a failed attempt.
