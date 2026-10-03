# ff-s15-x0-graph-sandbox-01 — X0/X2/X4: the smallest graph-native System 1.5 sandbox

**X-series (exploratory lane).** Loose ceremony, cheap experiments, allowed to fail fast; it shares nothing with the C-series confirmation path and uses no sealed split. Something that survives twice here graduates to a C-series experiment with a real contract.

Question: if the runtime's world is a typed weighted graph instead of a flat policy class, which capabilities become structural readouts, which stay hard, and what new ones appear? Plan (fixed before any result): [PLAN.md](PLAN.md). Results: [RESULTS.md](RESULTS.md). Harvest draft: [HARVEST-ENTRY.md](HARVEST-ENTRY.md).

## What is here

- `xg/graph.py` — **X0 kernel.** Typed nodes (ENTITY, STATE, ACTION, GOAL, EVIDENCE, REQUIREMENT), typed directed weighted edges (REQUIRES, SUPPORTS, CONTRADICTS, APPLICABLE_TO, CAUSES, ACHIEVES) with provenance, source and KEEP/DROP/DEFER disposition, and a canonical digest.
- `xg/build.py` — **X2.** BANK record to graph. Schema rules give each action's REQUIRES / CAUSES / ACHIEVES edges; a fact producer (oracle or noisy) gives SUPPORTS / CONTRADICTS edges with weights; slots and alias collisions are edges too.
- `xg/control.py` — **X2/X4 controller.** Delete-relaxed reachability (hmax for reachability and the depth cap, hadd to pick the first action), conflict / unknown / out-of-closure / ambiguity checks, single-fact repair search, slot completeness, KEEP/DEFER thresholds. No training.
- `xg/flat.py` — flat and flat+ decision-tree baselines. `xg/bank.py` — read-only BANK access (TRAIN and DEV only; the simulator is used for scoring).
- `run_x0.py clean|noise` writes `results/x0-clean.json` and `results/x0-noise.json`; `tools/make_results.py` writes RESULTS.md and fails if a prose claim stops matching the data.

## Headline (exploratory, DEV, oracle edges)

The zero-training graph reads ACT and its first action off structure (4,791 of 4,791 valid) and ASK off schema-slot completeness (recall 89.6% against 30.4% for flat+), and reaches 84.2% 3-way decision accuracy against 77.0% for flat+. The rest is floor: 8% of worlds carry no signature, ASK versus ABSTAIN is a 60/40 label coin flip, and IMPOSSIBLE labels follow a generator artifact (a doubled BLOCKED pair) that flat+ picks up and physics does not. Under a noisy producer the gain over a symmetric threshold comes from asymmetric caution about weak negatives, not from DEFER; ASK's value is recovery.

## Run it

```bash
python run_x0.py clean         # ~30 s (full DEV + flat baselines trained on TRAIN)
python run_x0.py noise 5000    # ~50 s (seeded subsample)
python tools/make_results.py
python -m unittest             # 15 tests
```
