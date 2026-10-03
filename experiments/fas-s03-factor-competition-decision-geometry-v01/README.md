# FAS-S03: Factor Competition / Decision Composition

S03 is a read-only, descriptive analysis of the paired FAS-00 `mean_full` and S02 `final_position` decision surfaces on the original sealed test events. It reads existing feature caches and probe states, recomputes pre-update logits, and records margins, subgroup distributions, paired changes, and decision-normal geometry.

No model is loaded. No feature is extracted. No probe is fitted. No adaptive mechanism is run. S03 cannot revise FAS-00 or authorize a later phase.

The analysis is descriptive. Because the two probes were fitted separately, cross-view logit changes combine the representation view with the corresponding fitted weights, intercepts, and standardization. Conditioning on original-corpus factors is not a randomized intervention and does not establish causal factor effects.
