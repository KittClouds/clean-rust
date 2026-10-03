# Harvest entry — C-G1 (draft; no Harvest location was found in the repo)

**FINDING**
Per-world relative normalisation of a frozen edge score reduces the DEV-to-TEST threshold failure but does not remove it. At the 1% DEV target the pooled TEST edge loss falls from 6.65% (raw logit) to 2.90% (type-pair percentile), but the bounds were 2% pooled / 3% held: held loss is 6.8% and S9 11.1%.
Six of twelve renderers land at about nominal (1.1–1.5%); S3, S5, S7, S8, S10 and S9 do not. No transform advances. A shuffled-score control shows the transforms leak nothing (gain at most 0.5 points).

**ENGINEERING PRINCIPLE**
The runtime sees each world's whole candidate set without labels, so relative statistics are the natural first attack on a geometry shift; they are a zero-training transform of the frozen score. They fix a per-world shift, not a loss of ordering quality — and the boundary they leave is where the representation itself degrades (here, S9).

**RECIPE**
Fix a small transform family and the pass bounds first; keep T0 fixed as its natural zero-edge form; fit one threshold on DEV per transform; apply it unchanged; include a shuffled-score leak control and the raw-score baseline (which must reproduce the earlier failure exactly); then look at per-renderer loss, not just the pooled number.

**KNOWN COST**
Development-grade: TEST shaped both the operation and the transform family. The derating table is exploratory and adaptive on TEST. Percentile thresholds are coarse at very small budgets.

**DO NOT CLAIM**
That the 230M edge observer is unusable (its ranking transports and a derated type-pair-percentile threshold meets the bounds on paper), that any transform passed, or that derating is confirmed.

**PRODUCT CONSEQUENCE**
Do not build the bundle or C0 v2 from C-G1. At a safe operating point the 230M adds only about 5 points of non-edge pruning over the type table (76% to about 81%); that number is FF's bar. A fixed safety factor on type-pair-percentile scores is a design candidate to freeze and confirm once on the sealed fresh split.

Evidence: `results/cg1-census.json`, `RESULTS.md`, plan `PLAN.md`.
