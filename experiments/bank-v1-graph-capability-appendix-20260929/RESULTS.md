# Results: Cached BANK-v1 Graph Readouts

**Disposition:** completed engineering appendix. No new backbone pass, fine-tuning, retrieval, or authority update. BANK-v1 TEST was previously opened by the surface sweep, so this is not fresh qualification.

## Result

The cached row-level surfaces support useful prediction of graph-wide entity/relation/state sets and a compositional object-to-goal route-distance target. The MLP improved route-distance readout over linear on every surface, while the best representation still depended on the graph task and renderer.

| Surface | Route distance, linear: all TEST acc / macro-F1 | Route distance, MLP: all TEST acc / macro-F1 | TEST-COMPOSITION acc (linear / MLP) |
|---|---:|---:|---:|
| Midpoint + final | 0.643 / 0.478 | 0.653 / 0.513 | 0.704 / 0.737 |
| Final + mean | 0.627 / 0.465 | **0.661** / 0.496 | 0.663 / 0.706 |
| Layer −4 final | 0.632 / 0.446 | 0.654 / 0.492 | 0.679 / 0.723 |
| Full mean | 0.377 / 0.268 | 0.500 / 0.333 | 0.468 / 0.491 |

All TEST route scores use 24,467 applicable canonical worlds pooled across the eight existing TEST partitions. TEST-COMPOSITION contains 3,275 applicable rows out of 5,000 worlds, with class counts: 1,062 already at goal, 1,335 one-hop, 857 multi-hop, and 21 disconnected. Thus the disconnected-class scores are especially noisy.

For the pooled renderer challenge, route-distance accuracy on S7/S8/S9 was:

| Surface | Linear S7 / S8 / S9 | MLP S7 / S8 / S9 |
|---|---:|---:|
| Midpoint + final | 0.660 / 0.635 / 0.065 | 0.630 / 0.635 / 0.049 |
| Final + mean | 0.590 / 0.600 / 0.270 | 0.616 / 0.610 / 0.361 |
| Layer −4 final | 0.671 / 0.613 / 0.051 | 0.676 / 0.570 / 0.010 |
| Full mean | 0.268 / 0.290 / 0.006 | 0.484 / 0.508 / 0.393 |

The large S9 spread is a strong warning against treating a pooled route score as renderer-robust graph ability. Midpoint + final's MLP was strongest on the TEST-COMPOSITION split; final + mean's MLP had the strongest pooled route accuracy; full mean was substantially weaker for this target.

Graph-wide entity/relation/state set readouts are also strong on the existing synthetic test distribution. Pooled over the eight TEST partitions, linear micro-F1 was:

| Surface | Entity types | Relation types | State values |
|---|---:|---:|---:|
| Midpoint + final | 0.950 | 0.918 | 0.814 |
| Final + mean | 0.930 | 0.877 | 0.809 |
| Layer −4 final | 0.970 | 0.908 | 0.807 |
| Full mean | 0.948 | 0.904 | 0.820 |

The shared MLP raised those graph-set micro-F1 scores, but that comparison is a readout-capacity result on BANK's generated worlds, not evidence of node-local extraction.

## What this establishes

- A whole-row text surface can feed a small readout that predicts graph-level entity, predicate, and state-value summaries.
- It can also support a nontrivial graph-composition target: shortest connectivity distance from an object's current location to its goal location.
- The MLP improves route-distance macro-F1 over linear on all four surfaces; the gain is largest for full mean (0.333 vs. 0.268 pooled macro-F1) and midpoint + final (0.513 vs. 0.478).
- Surface rankings move across the overall route task, TEST-COMPOSITION, and the S7/S8/S9 renderer split.

## Limits and run identity

Cached features are one vector per complete rendered row. There are no separate node, relation-instance, edge-candidate, or subgraph vectors, so node-type-per-node, edge-existence, 1-hop membership, and 2-hop candidate ranking were not attempted. The test set was already scored in the parent surface sweep. Treat these as engineering diagnostics over BANK-v1 only.

- Primary canonical worlds: 120,000 TRAIN; 20,000 DEV; 40,000 TEST.
- Four cached surfaces; linear and 256-hidden-unit MLP; 8 AdamW epochs; seed 20260929.
- CUDA: NVIDIA GeForce RTX 3080; PyTorch 2.11.0+cu128.
- End-to-end runtime: 148.4 s; summed readout-fit time: 34.0 s.
- Results artifact: `D:\phoenix-target-overgraph\bank-v1-graph-capability-appendix-20260929\graph-capability-results.json`.
- Results SHA-256: `872dcd286046e4855539ccd057979f3dbb91ae879591735106b69106c5d44abf`.
- Tests: 5 target-derivation unit tests passed; `py_compile` passed for the runner and target module.
