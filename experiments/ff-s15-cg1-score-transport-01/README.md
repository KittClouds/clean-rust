# ff-s15-cg1-score-transport-01 — C-G1: score transport and calibration under shift

C-G0 found that the frozen T1 edge ranking is useful but its DEV-fitted threshold does not transfer (a 1% budget lost 6.65% of edges on TEST, 17% on S9). C-G1 asks one narrow question: can the ranking be turned into a pruning threshold whose loss budget transfers, using only runtime-observable information?
Four zero-training transforms of the frozen score (raw, per-world percentile, per-world-and-type-pair percentile, robust per-world z), one DEV threshold each, applied unchanged to TEST. No C0 v2, no bundle, no new capability.

- Plan and gate (fixed before any transform was computed): [PLAN.md](PLAN.md). Result: [RESULTS.md](RESULTS.md). Receipt: [results/cg1-census.json](results/cg1-census.json). Harvest draft: [HARVEST-ENTRY.md](HARVEST-ENTRY.md). Sealed-split request (drafted, not sent): [CONFIRM-GRAPH-SPLIT-REQUEST.md](CONFIRM-GRAPH-SPLIT-REQUEST.md).
- **Outcome: no transform advances; C-G1 stops with the boundary result** — T1 supplies robust ranking but not a transportable selective-execution score under the tested shift. Per-world normalisation cuts the 1% target's pooled loss from 6.65% to 2.9% and fixes six of twelve renderers to about nominal, but S9 stays at 11%.
- **Exploratory (not preregistered, found after seeing TEST):** `typepair_percentile` fitted at a derated DEV budget (0.2% for a 1% target, 0.5% for 2%) meets every gate bound on paper, with only about +5 points of pruning gain left over the type table. A candidate for the fresh split, not a pass.

## Run it

```bash
python run_cg1.py             # ~1 min: reads C-G0's evidence (hash-checked) -> results/cg1-census.json
python tools/make_results.py  # RESULTS.md (guards fail if a prose claim stops matching)
python -m unittest            # 8 tests, incl. brute-force checks and the per-world-shift invariance property
```

Depends on `../ff-s15-cg0-edge-pruning-01/evidence/` (regenerate with its `run_cg0.py prepare`). `evidence/` here is unused; results are the tracked receipts.
