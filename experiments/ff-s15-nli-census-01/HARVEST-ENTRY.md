# Harvest entry — NLI-UNKNOWN census (draft; no Harvest location was found in the repo)

**FINDING**
BANK's frozen NLI head is not usable evidence for ASK, and neither would be a perfect one. Perfect-NLI ceiling on CAL: recall at precision 0.5 rises from 18.1% to 19.3% (+6.7%, bar +25%).
The real heads score AP 0.054–0.072 for ASK against 4.9% prevalence; the best NLI-conjunction headroom is 0% (noise p95 0%); the size-matched NLI set recovers 10 of 475 ASK misses (2.1%).
The reason is the label itself: NLI == UNKNOWN for 83% of ASK rows but also 42% of ACT and 69% of ABSTAIN rows (a perfect UNKNOWN flag would be right 7.1% of the time for ASK, lift 1.5×), and 87 of the 105 false positives of P(ASK) are ABSTAIN rows.

**ENGINEERING PRINCIPLE**
Independence is worth something only if the second signal is informative. An observer can be independent of another's errors simply because it knows nothing about the target. Compute the *perfect-signal ceiling* first: if the true label of the second task cannot lift the first task enough, no head trained on it can.

**RECIPE**
For a proposed second observer: (1) ceiling with the true labels of its task as a veto/union over the existing detector; (2) crosstab of its label against the target decision; (3) the real head against a shuffled-score noise band. Stop at (1) if the ceiling is under the bar.

**KNOWN COST**
None to the acting tier (nothing was built). The census is in-sample on CAL, so every headroom is an upper bound; a null is therefore strong.

**DO NOT CLAIM**
That NLI is useless in general (it stays a differentiated Rung 0 capability), that the NER route is dead (untested), or that ASK is unsolvable. Not confirmatory.

**PRODUCT CONSEQUENCE**
Do not build an NLI-conditioned ASK rule. The missing capability is goal-conditioned: "is every fact this goal's plan requires present?" (in TRAIN every ASK row has exactly one missing, requestable fact). That is a hypothesis for the representation ladder, untested here.

Evidence: `results/census.json`, `RESULTS.md`, plan `PLAN.md`.
