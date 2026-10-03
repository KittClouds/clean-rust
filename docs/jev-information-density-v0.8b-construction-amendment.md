# v0.8B Construction Amendment: Root-Profile Matching

**Status:** frozen before the v0.8B constrained-flow attempt; no model contact or training has occurred.

## Trigger and preserved failed attempt

The first deterministic within-cell selector matched all exact joint-cell quotas and matched the input-occurrence histogram exactly, but its row choices concentrated too heavily in fewer roots. CM100 reached 22,087 unique roots versus the R100 target 25,700, with root-multiplicity TV 0.2183. RM100 reached 23,499 versus the C100 target 25,190, with TV 0.1702. The `selection-v08b-v01` report is preserved; it emitted no manifests.

## Frozen construction change

Keep all v0.8B bank profiles, joint-cell quotas, input multiplicities, tolerances, seeds, and objectives unchanged. Replace independent within-input row selection with one deterministic bipartite b-matching per bank:

- Left nodes are selected `(joint cell, model-input signature)` pairs with exact group-demand degrees from the reference input-occurrence profile.
- Right nodes are eligible roots assigned the exact root-degree multiset from the reference bank.
- Edges represent eligible source groups connecting an input-cell node to a root; parallel groups are edge capacity.
- Curated choices use the frozen v0.8 static rarity score for deterministic ties; random choices use the v0.8B frozen hash seed.
- Run exactly one max-flow attempt per bank. If full flow is not reached, or any final frozen tolerance fails, emit no CM100/RM100 IDs and do not retry with altered rules.

The solver uses only training-pool metadata and exact target metadata. It does not read text, model outputs, embeddings, protected labels, or Phoenix. Exact root-multiplicity matching is stronger than the frozen 0.02 TV tolerance; all other gates remain in force.
