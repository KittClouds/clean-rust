# BANK-v1 Graph-Capability Appendix

Engineering-only readout experiment over the cached LFM2.5-230M BANK-v1 row vectors. It performs no backbone extraction, fine-tuning, retrieval, or authority update. BANK-v1 remains evaluation data for the specialty readouts; it is not used to train or modify the backbone.

The cache stores one vector per rendered world row, not vectors for individual nodes or edges. Accordingly, all outputs here are **world-level graph summaries**. The appendix does not claim node classification, edge prediction, neighbor lookup, or graph neural computation.

## Targets and models

Four cached surfaces are used: `middle_plus_final`, `final_plus_mean`, `layer_m4_final`, and `full_mean`. Canonical BANK world files provide these targets:

- `entity_type_presence`: entity types present anywhere in the world.
- `relation_type_presence`: predicates present in the initial graph.
- `state_value_presence`: ACTIVE/INACTIVE values present in initial STATE facts.
- `goal_path_distance`: for an object with one initial AT location and an AT goal, shortest undirected CONNECTED-path distance, bucketed as already-at-goal, one hop, multi-hop, or disconnected.

Each surface gets the same multi-output linear readout and a shared 256-unit MLP comparator. Readouts are trained on the 120,000 canonical TRAIN worlds with a train-only scaler and fixed eight-epoch AdamW schedule. The 20,000 DEV and 40,000 TEST worlds are scored without threshold or epoch selection. Paired renderer duplicates are excluded from fitting and primary scoring.

## Reproduce

From the repository root, using the cached surface extraction and BANK release paths:

```powershell
python -m unittest discover -s experiments/bank-v1-graph-capability-appendix-20260929/tests -v
python experiments/bank-v1-graph-capability-appendix-20260929/run_appendix.py `
  --bank-root 'C:\code land\clean-rust\experiments\ff-s15-bank-01\releases\BANK-v1' `
  --feature-dir 'D:\phoenix-target-overgraph\bank-v1-surface-extremes-20260929\features' `
  --output 'D:\phoenix-target-overgraph\bank-v1-graph-capability-appendix-20260929'
```

The runner verifies the upstream extraction seal and hashes for every used primitive, joins only primary cached rows to canonical worlds, and writes `graph-capability-results.json` and readout weights to the output directory.

## Limits

The BANK-v1 test truth was already opened by the preceding surface sweep. Scores are a useful engineering readout comparison on the same synthetic task family, not fresh qualification or evidence of natural-language graph reasoning. `goal_path_distance` is the sole compositional graph target; its disconnected class is rare. See [RESULTS.md](RESULTS.md) for the observed scores and report hash.
