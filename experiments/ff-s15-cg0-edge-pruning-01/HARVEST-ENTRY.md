# Harvest entry — C-G0 (draft; no Harvest location was found in the repo)

**FINDING**
On the natural pair universe (10.1% edges), a deterministic type-pair table prunes 76% of non-edges at zero edge loss (12 of 15 type pairs never carry an edge). The frozen 230M pair observer adds +11.9 points at a 1% edge-loss budget and +14.5 at 2% on pooled TEST — enough to pass the preregistered gate (10 points at both, positive on S7/S8/S9, above the noise band).
But the gain is +7.1 / +9.3 on the held renderers and only +4.3 / +5.2 on S9, where T1 alone (63%) is worse than the type table (77%). And T1's threshold does not transfer: a 1% budget fitted on DEV loses 6.65% of edges on TEST and 17% on S9, because DEV edges are easier than TEST edges (1st-percentile edge score −0.70 vs −2.5 to −5.1).

**ENGINEERING PRINCIPLE**
Sampled discrimination is not pruning utility: balance the classes naturally before asking what a cheap tier is worth, and put the deterministic table in as a real tier, not a baseline column. Ranking transfers across renderers; calibrated thresholds do not, and the runtime guarantee lives in the threshold.

**RECIPE**
Enumerate the full pair universe; build the type table from TRAIN's natural counts; compare matched frontiers on every split for T0, T0+T1 and T1 alone with the parameters optimised identically; add a shuffled-score noise band; then apply DEV-fitted thresholds unchanged to held renderers and read the achieved loss.

**KNOWN COST**
TEST helped select this operation, so every TEST number is development-grade. DEV is easier than TEST, so DEV-fitted numbers are optimistic. Types are given by the entity id, not inferred from text.

**DO NOT CLAIM**
That T1 is a robust runtime tier (it passed the gate as written; the held-renderer gain and threshold transfer are the open problems), that the 230M is needed (FF has not tested a token/from-scratch encoder on the residual), or anything about natural-language graphs.

**PRODUCT CONSEQUENCE**
Keep T0 as a tier regardless. Advance to a contract (C-G1) only with calibration under renderer shift as the first problem. Hand FF the residual frontier inside the three edge-carrying type pairs as the bar a replacement encoder must match.

Evidence: `results/cg0-census.json`, `RESULTS.md`, plan `PLAN.md`.
