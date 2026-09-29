# ff-s15-c4a-action-safety-01 — action-conditional safety census

C1 used one ACT threshold for every action, which assumes `P(harm | confidence, action)` is the same for all actions. This census asks how much *perfect* action-specific thresholds could buy over C1's single threshold at matched harm
(exact dynamic-programming oracle, with a shuffled-action noise band), before anything is built. CAL only, no policy, no training, no HOLD.

- Plan (fixed before any per-action safety was computed): [PLAN.md](PLAN.md). Result: [RESULTS.md](RESULTS.md). Receipt: [results/c4a-census.json](results/c4a-census.json). Harvest draft: [HARVEST-ENTRY.md](HARVEST-ENTRY.md).
- **Outcome: gate not passed on any surface; C4b not earned; C4 stops.** Primary surface: oracle gain +7.3% at 3% harm and +7.6% at 5% (bar 10% at both, above noise); it reaches +30% only at 10% harm.
- **The finding that matters:** the cheap tier is a **NOOP executor**. C1's frozen rule executes 735 NOOP, 31 MOVE and 2 ACTIVATE on the primary surface; it correctly executes 0.9% of the truth MOVE and ACTIVATE rows against 25.9% of the truth NOOP rows.
  At the same threshold harm is 3.8% for NOOP, 22.7% for MOVE and 67% for ACTIVATE, and MOVE and ACTIVATE are never safe at any confidence (top-25 harm at least 20%). One confidence threshold already draws that boundary, so a per-action rule adds nothing.

## Run it

```bash
python run_c4a.py            # CAL only -> results/c4a-census.json
python tools/make_results.py # RESULTS.md from the receipt (guards fail if a prose claim stops matching)
python -m unittest           # 11 tests: the DP oracle is checked against brute force
```

Depends on C3a (frontier code), C2a (CAL loader, which verifies C1's evidence against C1's freeze), C1 and C0, imported unchanged.
