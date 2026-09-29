# ff-s15-cg0-edge-pruning-01 — C-G0: residual edge-pruning census

Lexi's Graph Surface Extraction v2 kept one operation, `edge_existence`. Her 50/50 sampled pairs measure discrimination, not pruning. This census puts her frozen observer (T1) on the **natural ordered-pair universe** of every world and asks whether it extends a deterministic
type-pair table (T0) at matched true-edge loss. No retraining, no new head, no controller.

- Plan (fixed before anything was computed, with one pre-run correction noted in it): [PLAN.md](PLAN.md). Result: [RESULTS.md](RESULTS.md). Receipt: [results/cg0-census.json](results/cg0-census.json). Harvest draft: [HARVEST-ENTRY.md](HARVEST-ENTRY.md).
- **Preregistered gate: PASSED.** Pooled TEST gain over T0 is +11.9 points at ε = 1% and +14.5 at ε = 2% (bar 10 at both), positive on S7/S8/S9 individually, above the shuffled-score noise band.
- **Caveats that matter more than the pass:** T0 alone already prunes 76% of non-edges at zero edge loss (12 of the 15 type pairs never carry an edge). On the held renderers the gain is +7.1 / +9.3 (S9 only +4.3 / +5.2). And T1's **threshold does not transfer**: a 1% budget fitted on DEV loses 6.65% of edges on TEST and 17% on S9.
  Development-grade only: TEST helped select this operation, and no fresh split exists yet.

## Run it

```bash
python run_cg0.py prepare   # ~6 min: hash-bind Lexi's artifacts, reproduce her nine sampled AUCs (worst diff 2e-9), T0 table from TRAIN, score every pair in DEV and TEST
python run_cg0.py census    # ~10 min (200-permutation noise band): frontiers, gate, DEV-fit transfer -> results/cg0-census.json
python tools/make_results.py # RESULTS.md (guards fail if a prose claim stops matching)
python -m unittest           # 11 tests; the frontier is checked against brute force
```

Depends on Lexi's run directory on `D:` (override with `CG0_LEXI_OUT`) and her worktree code for hash checks only (`CG0_LEXI_CODE`); her experiment source is uncommitted, so the hashes in her score receipt are the custody. `evidence/` is git-ignored.
