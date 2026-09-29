# Harvest entry — ASK rung (draft; no Harvest location was found in the repo)

**FINDING**
A dedicated SHOULD_ASK head, linear or a one-hidden-layer MLP, trained on the locked 230M surfaces does not materially beat the existing Rung 0 decision head's P(ASK) as an ASK detector.
Primary surface, HOLD: AP 0.236 (linear) and 0.279 (MLP) against 0.247 for the existing head; recall at matched precision 0.5 is 15.6% / 22.1% against 17.3%. The MLP's +13% AP misses the preregistered 1.25× bar.
The existing head is not blind: AUROC about 0.8, roughly 50% precision at 15–20% recall. Nothing reaches 60% precision.

**ENGINEERING PRINCIPLE**
When the information is only weakly exposed by the representation, a bigger or dedicated readout does not create it. Also: the precision target belongs to the action — a wrong ask costs a human question, a wrong execution costs harm —
so C1's ≥ 80% bar was the wrong lens for ASK.

**RECIPE**
Before training a specialist head, score the existing head's relevant class probability as a ranker (AP, AUROC, recall at matched precision) and make the specialist beat it at matched precision.
For a rare-positive binary head, initialise the output bias at the prior logit: at lr 1e-3 and about 570 Adam steps it cannot reach a 4.8% prior from zero (the first run stalled at loss 0.49 against a constant predictor's 0.19).

**KNOWN COST**
Adding the ASK rule in front of the C1 controller is free: correct executions unchanged (685 → 685), harm 5.1% → 5.0%, 202 asks of which 107 were needed. It just adds little (18% of ASK rows caught at 53% precision).

**DO NOT CLAIM**
That ASK is unsolvable; that NER or NLI will solve it (untested); or anything confirmatory (DEV only, HOLD reused).

**PRODUCT CONSEQUENCE**
The cheap tier can ask at about 50% precision for free; higher-precision asking needs different evidence. In BANK, ASK is exactly one missing, requestable fact — a negative-evidence problem — so the candidates are capabilities that compare the goal
against the facts present (unresolved entities, NLI UNKNOWN). Before building anything on them, run the oracle-headroom census on the existing NLI head's P(UNKNOWN).

Evidence: `results/ask-report-linear.json`, `results/ask-report-mlp.json`, `RESULTS.md`, plan `PREREGISTRATION.md`.
