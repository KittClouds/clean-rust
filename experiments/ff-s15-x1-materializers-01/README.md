# ff-s15-x1-materializers-01 — X1: non-oracle graph materialization

X-series (exploratory). Question: does representing uncertain propositions as graph edges create downstream utility that a flat score merger cannot recover? The X0 kernel and controller are frozen (hash-checked against commit `13d87e83`); only the materializer changes.

- Plan, fixed before the first run: [PLAN.md](PLAN.md). Results: [RESULTS.md](RESULTS.md). Receipts: `results/x1-receipt.json` (preregistered analysis), `results/x1-explore.json` (post hoc, labelled), `results/x1-prepare.json`. Harvest draft: [HARVEST-ENTRY.md](HARVEST-ENTRY.md).
- **Outcome: X1 stops.** Graph-aware arbitration never beat calibrated score fusion at matched coverage and harm, and lost at low coverage in two settings. Multi-producer agreement is the only mechanism with a large effect, and a calibrated logistic merger recovers it. X5 (NLI as a producer) is therefore not earned and was not started.
- Honest note: the preregistered coverage levels (0.50/0.70/0.85) were unreachable at the primary setting (mention-miss 0.2), so the preregistered test was degenerate there; the exploratory comparison at reachable levels reaches the same conclusion.

## Run it

```bash
python tools/freeze_x0.py        # once: records and checks the frozen X0 hashes
python run_x1.py prepare         # ~4 min: T0/T1 fit, T2 realignment (19,995 of 20,000 DEV worlds), fold-A calibration of every setting
python run_x1.py evaluate        # ~20 min: fold B through the frozen controller, six settings
python run_x1.py analyze         # preregistered decision rules, bootstrap, controls, attribution
python run_x1.py explore         # post hoc matched comparison at reachable coverage
python tools/make_results.py     # RESULTS.md (guards fail if a prose claim stops matching)
python -m unittest               # 18 tests
```

Depends on C-G0's cached T2 scores (`../ff-s15-cg0-edge-pruning-01/evidence/universe-DEV.npz`; Lexi's run directory is no longer on disk, so the 230M observer itself cannot be re-run). `evidence/` is git-ignored.
