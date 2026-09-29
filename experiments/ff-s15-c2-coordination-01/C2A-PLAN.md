# C2a — complementarity census (plan, written before the census is run)

Written 2026-09-29. C1 showed that one surface with one thresholded observer is a good *risk gate* and a poor *acting tier*: at a 5% harm target the
primary surface correctly executes about 12% of true-ACT rows. C2 asks whether coordinating the four locked surfaces can raise that without giving up the
bounded-harm property. **C2a is the cheapest question first: do the four surfaces find different safe actions?** No policy is trained or scored here.

## Data and discipline

- Rows: BANK-v1 DEV, **CAL half only** (11,890 rows). The C1 arrays are masked to CAL the moment they are loaded; no HOLD row is selected, used or reported by any C2a code. HOLD was already scored once, for C1, so it is not virgin for C2;
  C2 results on it are development evidence, and the confirmation is the fresh sealed split (requested separately).
- Inputs: the C1 evidence arrays (integer ppm per surface and head), the C1 truth arrays and the C1 frozen thresholds, each verified by SHA-256 against
  C1's tracked `results/freeze.json` before use. Nothing is re-fitted.
- Operating point: each surface's C1 frozen thresholds at **α = 0.05**. Looser and tighter α are reported as sensitivity only.

## Definitions (per surface s, on CAL)

- **Qualifies** (`Q_s`): C1's ACT rule fires — `dec.top == ACT`, `dec.top_ppm ≥ T_act` and `act.top_ppm ≥ T_act`. A surface with no ACT rule never qualifies.
  It then executes `a_s = act.top`.
- **Safely correct** (`C_s`): qualifies, truth is ACT, and `a_s` equals the truth action. **Harmful** (`Hm_s`): qualifies and not safely correct.
- **Raw level** (no thresholds): `dec.top == ACT` with action `act.top`; same definitions of correct and harmful.
- Denominator for coverage figures: CAL rows whose truth is ACT, so numbers compare with C1's "12.2% of true-ACT rows".

## What is measured

For every pair (A, B) of the four surfaces, at the qualified level: both qualify; both qualify with the same action; both safely correct; both harmful; correct only on A;
correct only on B; harmful only on A; harmful only on B; Jaccard of `C_A` and `C_B`. At the raw level: both say ACT; same action; both correct; both harmful;
A says ACT / B says ABSTAIN; A says ACT / B says ASK; A says ACT / B says ACT with another action.

For the group: union and intersection of `C_s` over all four surfaces (and over the three routers without `full_mean`); the primary's `C`; the **oracle headroom**
`|∪C| / |C_primary| − 1`; the union's harmful rows and the pessimistic union harm rate `|rows where some surface qualifies harmfully| / |∪Q|`.
Also the **veto census**: among the primary's qualified rows, how many correct and how many harmful executions each other surface's frozen ABSTAIN rule
(`dec.top == ABSTAIN`, `dec.top_ppm ≥ its C1 T_abstain`) would have blocked, singly and together — this is the cost/benefit of an ABSTAIN veto before any policy exists.
And the headroom per surface family, so it is visible whether any gain is confined to one family.

## Rule for going on to C2b (fixed now)

Proceed to a preregistered C2b (deterministic coordination policies) **iff** the oracle headroom on CAL at α = 0.05 is **≥ 25%**, i.e. `|∪C| ≥ 1.25 × |C_primary|`.
This is a *necessary* condition — an oracle that picks the right surface per row — not evidence that any real policy captures it. If the headroom is below 25% the
extra machinery is not earned: C2 stops here and the result is reported as such. No threshold is changed after seeing the census.

## Not done here

No learned controller, no new thresholds, no ASK treatment (ASK gets its own rung), no HOLD.
