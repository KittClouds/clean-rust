# Harvest entry — C3a (draft; no Harvest location was found in the repo)

**FINDING**
Thirteen zero-training risk scores over the existing decision and action probability vectors — margins, entropies, joint probability, P(ABSTAIN), P(ASK), and combinations — do not clearly beat C1's `min(P_decision, P_action)` on any surface at matched harm.
Primary surface: at 3% and 5% harm every alternative is worse (closest, `product` and `min_margins`, lose 5–6%); at 10% harm `product` (+15%), `margin_product` (+11%) and `rank_mean` (+21%) win, passing one of the three required levels.

**ENGINEERING PRINCIPLE**
Before building a smarter routing rule, read the risk-coverage frontier of the simple one against the alternatives at matched harm. Frontiers can cross: a score can lose in the operating range and win where harm is already loose, and only the operating range counts.

**RECIPE**
Fix the score list and the pass rule first (levels, relative bar, bootstrap guard for picking the best of K); include a random control; compare correct executions at matched harm, not at one threshold.

**KNOWN COST**
Thresholds are chosen in-sample on CAL for every score alike, so counts are optimistic though the comparison is fair. Thirteen scores, guarded by the bootstrap 1st percentile, not a formal correction.

**DO NOT CLAIM**
That no better routing rule exists for other information, or that the far-end crossing is real: `product` gains on all four surfaces at 10% harm, but only the primary clears the guard. Not confirmatory.

**PRODUCT CONSEQUENCE**
Keep `min(P_decision, P_action)`. Do not build C3b. The remaining lever is different information, not a smarter score over the same vectors.

Evidence: `results/c3a-census.json`, `RESULTS.md`, plan `PLAN.md`.
