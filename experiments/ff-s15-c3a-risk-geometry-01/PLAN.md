# C3a — selective-risk geometry census (plan, written before anything is computed)

Written 2026-09-29. C1 gated the ACT rule on `min(P_decision(ACT), P_action(top))`. That was one choice of risk score among many, made without looking at alternatives. The probability simplexes are already in hand
for every row, so the cheapest question about the controller itself is: **does any other zero-training function of those same vectors order harmful executions better than C1's score, at matched harm?**
If none clearly does, C1 left no routing signal on the table and the idea is dead. If one clearly does, a deterministic routing rule (C3b) is earned — not built here.
Same observers, same vectors, no training, no new capability. This is the controller's own information, which is why it does not reopen the closed doors.

## Data and discipline

BANK-v1 DEV, **CAL half only**, from C1's verified evidence (masked to CAL on load; no HOLD or TEST row is selected, used or reported). HOLD has served C1 and the ASK rung and is not used here. Each surface's own vectors only (no cross-surface combination).
Candidate rows: those where the decision head's top class is ACT (exactly C1's gating), so every score is compared on the same rows. A candidate is **safe** if the truth is ACT and the action head's top action equals the truth action; otherwise **harmful**
(the same harm as C1: an executed action that is not the truth action).

## The scores (13; all zero-training; higher = safer to execute; fixed now)

`P_d(·)` = the decision head, `P_a(·)` = the action head, over the row's integer-ppm vectors read as probabilities.

1. **c1_min** = `min(P_d(ACT), P_a(top))` — C1's score, the baseline.
2. `p_act` = `P_d(ACT)`.  3. `p_action` = `P_a(top)`.  4. `product` = `P_d(ACT) · P_a(top)` (the joint probability of the pair; its log is the same ordering, so it is not listed separately).
5. `dec_margin` = `P_d(ACT) − max(P_d(ASK), P_d(ABSTAIN))`.  6. `act_margin` = `P_a(top) − P_a(second)`.
7. `neg_dec_entropy` = −entropy of `P_d`.  8. `neg_act_entropy` = −entropy of `P_a`.
9. `neg_p_abstain` = −`P_d(ABSTAIN)`.  10. `neg_p_ask` = −`P_d(ASK)`.
11. `min_margins` = `min(dec_margin, act_margin)`.  12. `margin_product` = `dec_margin · act_margin`.  13. `rank_mean` = the mean of the within-candidate ranks of `dec_margin` and `act_margin`.
Plus a **random control** (a fixed-seed uniform score), to show what "no information" looks like on this frontier.

## Comparison: matched harm, never a single point

For each score, sort the candidates from safest to least safe and read the risk-coverage frontier. At each harm level **H ∈ {0.03, 0.05, 0.07, 0.10}** take the largest set with harm rate ≤ H and at least 100 executions (threshold chosen in-sample on CAL, equally for every score
including C1, so the comparison is fair though optimistic), and count its **correct executions**. Report them as a share of all truth-ACT rows on CAL.

A score **clearly dominates C1** iff, at **≥ 3 of the 4** harm levels, (a) its correct executions are ≥ **1.10×** C1's, and (b) the paired-bootstrap difference (score − C1, 500 resamples of the candidate rows, fixed seed) has its **1st percentile above 0**
(the 1st, not the 5th, as a guard against picking the best of 13 scores). The 10% bar is lower than C2a's 25% because a different scalar score costs nothing to adopt, unlike a second observer.

## Rule (fixed now)

- **C3b earned** iff at least one score clearly dominates C1 on the **primary surface `middle_plus_final`**. **Robust** iff a single score clearly dominates on **at least 3 of the 4 surfaces**.
- Otherwise the idea is **dead**: C1's `min(P_decision, P_action)` is as good as anything else these vectors offer, and the result says so.
- A pass earns a deterministic routing rule and a preregistered test on fresh data; it does not establish that the rule works.

## Not done here

No training, no new thresholds for deployment, no HOLD, no policy, no C3b. Not a rescue of C1's verdict.
