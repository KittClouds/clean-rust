# C4a — action-conditional safety census (plan, written before any per-action safety is computed)

Written 2026-09-29. C1 used one ACT threshold for every action. That implicitly assumes `P(harm | confidence, action) ≈ P(harm | confidence)` for all actions, which has never been checked. If some predicted actions are intrinsically safer or more dangerous
at the same confidence, the cheap tier has an **applicability boundary** — "execute this kind of action cheaply, always escalate that one" — which would be a different kind of finding from a better confidence formula.
This census asks how much *perfect* action-specific threshold selection could buy over C1's single threshold, at matched harm, before anything is built. Census only: no policy, no learned router, no training, no HOLD.

## Data and discipline

BANK-v1 DEV, **CAL half only**, C1's evidence verified against C1's freeze and masked to CAL on load; no HOLD or TEST row is used. Each surface's own vectors. Candidate rows and safety exactly as in C3a: candidates are rows where the decision head's top class is ACT;
a candidate is **safe** if the truth is ACT and the action head's top action is the truth action, otherwise **harmful**. The score is C1's `min(P_decision(ACT), P_action(top))`. The **predicted action** is the action head's top class.
Before this plan was written I looked at *support* only (how many candidates each predicted action has) and at which actions are ever a true ACT action in TRAIN — never at per-action harm or safety.
Support on CAL: NOOP, MOVE, ACTIVATE have roughly 1,000–3,500 candidates each on every surface; REQUEST has 84–168; DEACTIVATE appears once. In TRAIN, truth ACT actions are only NOOP, MOVE and ACTIVATE.

## Groups and support (fixed now)

An action is **eligible** for its own threshold iff it has **≥ 300 candidates and ≥ 100 safe candidates** on the surface. All other predicted actions are **excluded from the comparison in both arms** (the global baseline and the per-action oracle are both computed on eligible-action
candidates only), so any gain comes from eligible actions with real support. The excluded rows are counted and reported.

## What is measured

1. **The global C1 frontier** on the eligible candidates: correct executions at harm ≤ H for H ∈ {3%, 5%, 7%, 10%} (largest set, ≥ 100 executions, threshold chosen in-sample on CAL; the same rule as C3a).
2. **The per-action oracle:** the exact maximum of total correct executions over *one threshold per eligible action* subject to overall harm ≤ H (and ≥ 100 executions), solved by dynamic programming (not a heuristic). It contains the global threshold as a special case, so it can never be below it.
   The **oracle gain** is `oracle / global − 1`. It is optimistic (in-sample, several free thresholds), so:
3. **The noise band:** the same oracle with the predicted-action labels shuffled among the eligible candidates (100 permutations, fixed seed, group sizes preserved) — what optimising several thresholds finds by chance.
4. **Conditional harm** (descriptive): at the global threshold for each H, the executions, harmful executions and harm rate *per action* — does one action carry the harm?
5. **Coherence** (descriptive, kept separate from the oracle): candidates whose predicted action can never be a correct ACT execution (REQUEST) — how many, and how many of the harmful executions at C1's frozen α = 0.05 thresholds they account for.
   This is a fact about BANK's label space, not a fitted threshold; it is a statement about how broad C1's granted-action set was.

## Gate (fixed now)

The per-action route is **earned (C4b)** on a surface iff the oracle gain is **≥ 10%** (the bar for a change that adds no observer, as in C3a) **at both H = 3% and H = 5%** — the operating region, not merely 10% — **and** exceeds the noise band's 95th percentile at both levels.
Support is enforced by the eligibility rule. **Earned overall** iff the primary surface `middle_plus_final` passes; **robust** iff at least 3 of the 4 surfaces pass. If the primary fails, **C4 stops** and the door is closed.
A pass would earn a preregistered per-action applicability rule tested on fresh data; it would not show that one works.

## Not done here

No per-action policy, no learned router, no HOLD, no rescue of C1's verdict. The coherence observation is reported, not acted on.
