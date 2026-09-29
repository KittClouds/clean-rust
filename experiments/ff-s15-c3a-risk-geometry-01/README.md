# ff-s15-c3a-risk-geometry-01 — selective-risk geometry census

C1 gated the ACT rule on `min(P_decision(ACT), P_action(top))`, one choice among many. This census asks, with zero training and the same vectors, whether any other function of the probability simplexes orders harmful
executions better than that score at matched harm — the cheapest test of whether the controller left information unused.

- Plan (fixed before anything was computed): [PLAN.md](PLAN.md). Result: [RESULTS.md](RESULTS.md). Receipt: [results/c3a-census.json](results/c3a-census.json). Harvest draft: [HARVEST-ENTRY.md](HARVEST-ENTRY.md).
- **Outcome: no score clearly dominates C1's on any surface; C3b is not earned.** At 3–5% harm every alternative is worse on the primary surface (the closest lose 5–6%). At 10% harm `product`, `margin_product` and `rank_mean` beat it on the primary
  surface (one level of the three required), and `product` gains in point estimate on all four surfaces there — a hint at the loose end of the frontier, not a finding.
- CAL only, from C1's verified evidence; no HOLD, no TEST, no training, no policy.

## Run it

```bash
python run_c3a.py            # CAL only -> results/c3a-census.json
python tools/make_results.py # RESULTS.md from the receipt (guards fail if a prose claim stops matching)
python -m unittest           # 10 tests on synthetic data with known answers
```

Depends on C2a's loader (which verifies C1's evidence against C1's tracked freeze), C1 and C0, imported unchanged.
