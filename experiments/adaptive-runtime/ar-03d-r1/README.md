# AR-03D-R1 — Independent 5×5 projected-order replication

Protocol status: preregistered and frozen before collection. This is a replication of AR-03D, not a new optimizer variant. AR-03D remains sealed and is prior evidence only; its data will not be pooled into the R1 primary analysis. R1 outcomes will be recorded separately in `RESULTS.md`.

## Question and decision boundary

Does the unchanged projected-1D verifier partition produce a favorable closed-loop terminal held-out-loss difference versus the unchanged balanced hash-placebo partition when repeated across five new datasets and five new initializations?

AR-03D was favorable on average but heterogeneous. R1 will be interpreted through the full crossed structure: equal-cell mean and median paired loss difference; dataset- and initialization-marginal differences; cell direction count; accuracy as secondary; and harmful/beneficial selection diagnostics as secondary. No brittle win-count threshold is imposed. The R1 conclusion must be written independently before any cross-run synthesis with D.

## Parent and frozen runtime

- Parent is AR-03D results commit `2df36ced17a9d347f49fd64dc08631217c55227a` on `codex/ar-03d-projected1d-vs-hash-20260921`.
- Preserve AR-03D's 8-8-8-3 ReLU MLP, 171 parameters, bounds `[-2,2]`, action grammar `{0, ±0.005, ±0.01, ±0.02}`, P16 proposals, K2 top-2 × top-2 pair verification, rotating coordinate-pair schedule, four sequential replans per evidence round, 4,200 decision slots, and checkpoints at 0/600/2,400/4,200.
- Preserve the exact verifier contrast: projected 27D output-affine gradient through the frozen Rademacher projection (`ORDER_SEED = 0xa3034350524f4a31`, scale `1/sqrt(27)`), sorted into 12 balanced strata and refreshed at slots 0, 100, …, 4,100; versus the same balanced hash-placebo construction. Both draw V48: four examples without replacement from each of 12 strata of eight. The hash ID remains `(cell_index * 3 + stream_within_cell * 4) mod 8`.
- Apart from fresh factor/stream seeds and the larger crossed-factor cardinality, no model, action, sampling, verifier, refresh, selector, schedule, commit, stopping, or shadow behavior changes. Full-training shadow remains outcome-blind and scores only the chosen program; no oracle-best-action search.
- Paired arms use the same proposal stream seed and evidence-round schedule. States, legal candidates, and selected actions may naturally diverge after the intervention.

## Prospective 5×5 factors and fresh seeds

Primary cells are the full crossing of five independently generated training datasets and five model initializations: 25 dataset × initialization cells. Each cell has two paired evidence-stream seeds, retained as nested streams rather than counted as independent dataset/init replications. This yields 50 streams and 100 trajectories.

All seeds are frozen under the R1 identity and are disjoint from AR-03D and from one another:

| Role | Seed construction | Count |
| --- | --- | ---: |
| Training datasets | `0xa303_d1da_0000_0000 | i`, `i=1..5` | 5 |
| Model initializations | `0xa303_d1a7_0000_0000 | i`, `i=1..5` | 5 |
| Reserved development streams | `0xa303_d1de_0000_0000 | i`, `i=1..50` | 50 |
| Paired runtime evidence streams | `0xa303_d1ea_0000_0000 | i`, `i=1..50` | 50 |
| Measurement-only held-out datasets | `0xa303_d1fa_0000_0000 | i`, `i=1..5` | 5 |

The 50 runtime stream seeds are assigned sequentially by dataset-major, then initialization-major cell order, two streams per cell. The existing development-seed role is retained for protocol/helper compatibility and is not used to influence the closed-loop runtime. Held-out data is generated once per training dataset, shared across its five initialization cells, and read only for checkpoint cross-entropy/accuracy; it cannot affect training decisions.

## Arms and measurement

1. `projected_order_1d`: unchanged AR-03D state-derived partition and fixed K=100 refresh.
2. `hash_placebo`: unchanged outcome-independent hash partition, fixed for the trajectory. Across 25 cells, the frozen assignment covers all eight placebo IDs six or seven times; the two streams within a cell receive different IDs.

Primary endpoint: final held-out cross-entropy at slot 4,200. Aggregate first within each cell across its two paired streams, then report equal-weight 25-cell means and median cell difference, all 25 cell differences, five dataset marginals, and five initialization marginals. Report accuracy secondarily. Do not treat 50 streams or 100 trajectories as independent factor replications, and do not pool AR-03D into R1's primary result.

Secondary diagnostics retain the D definitions: full-training utility of only the selected program; beneficial/harmful selected counts and rates; cumulative harmful selected utility relative to no-op (not oracle regret); beneficial utility; harmful tails; train/held-out trajectories; actual legal verifier-program evaluation counts; feature/partition/panel/policy/shadow/wall costs. No panels or decision slots count as replication units.

## Integrity and stop rules

- Freeze source and protocol in a clean commit before collection; build optimized to `D:\adaptive-runtime-targets\ar-03d-r1` and execute from this C: worktree.
- Expected totals: five training and five held-out dataset files; 25 cells; 50 evidence streams; 100 trajectories; 420,000 decision rows; 105,000 panels; 400 checkpoints; 2,100 projected refresh records plus 50 fixed hash partition records; 25 cell summaries; five dataset and five initialization marginal summaries.
- Verify all 115 seed values are unique (`5+5+50+50+5`), generated-data hashes, paired initial parameter fingerprints, paired proposal fingerprints at all evidence rounds, identical pair-schedule offsets, V48 size and 4-per-stratum quota, unique in-range panel indices, exact projected refresh slots, balanced 12×8 partitions, hash-placebo coverage, finite metrics, and all CSV/JSON cardinalities/parseability.
- Keep the shadow observer unable to affect proposal, partition, selection, or commit. Preserve AR-03D and AR-03C artifacts byte-for-byte. CF-01 remains untouched.
- If integrity fails, retain the incomplete/non-promotable output and report it; do not silently repair, alter seeds, or rerun under a changed protocol.
- After integrity-valid collection, report the R1 result independently. If it is near zero, classify D as favorable finite-run variation. If materially reversed, keep H49 as diagnostic-only and close the runtime-benefit claim. If favorable with broad dataset and initialization support, support a replicated controller effect only within this synthetic family; no wider promotion follows automatically.

## Run

Use an absent output directory, e.g. `artifacts/run-20260921-ar03dr1-5x5`. The executable refuses overwrite and records the parent commit, frozen source commit, binary SHA-256, data hashes, and integrity summary.
