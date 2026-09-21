# AR-03C results — partition-construction frontier

Status: completed, diagnostic-only. No partition influenced proposal generation, verifier-panel selection, or training. No end-to-end optimizer comparison was run.

## Integrity and provenance

- Frozen source: `8d03df54315ff403d928e8f0abc33bcbcfd3de46`; parent AR-03B result: `6649f12424efcdd3edbff251ecc354e361f11804`.
- Release build used `D:\adaptive-runtime-targets\ar-03c`; execution ran from the C: workspace against the existing R2 and AR-03B artifact directories. Runtime: 183.21 seconds.
- Replayed 18 unchanged evaluation streams; captured 234 states. All 54 R2 checkpoint validations, 162 AR-03B snapshot matches, and nine crossed dataset×initialization cells passed.
- R2 model-state hash and all three dataset hashes matched the frozen receipt. Every partition was finite and exactly 12×8 balanced; all captured losses and candidate responses were finite.
- Output validation passed: both JSON files parsed; all nine CSVs parsed with consistent row widths and finite numeric values. Counts: 3,672 quality rows, 235,008 panel rows, 1,080 partition-cost rows, 216 verifier-cost rows, and 900 cost-frontier rows.
- At the eight shared AR-03B quality readouts (steps 600/625/650/700 and 2,400/2,425/2,450/2,500), the fresh/stale output-layer balanced-k-means summaries matched the AR-03B output-layer summaries for predicted and observed RMSE, sign error, cross-block regret, and selected-program regret within `1e-12`.
- **Provenance-label correction:** the frozen executable was built from the source commit above, but the build-time `AR03C_SOURCE_COMMIT` value was mistyped as `8d03df54b2749dbb1ad87256b0b33114557b0940`. That value is not a Git object, so the raw `report.json` and `integrity.json` contain an invalid source label. The raw files are preserved unchanged; [`provenance-correction.json`](artifacts/run-20260921-ar03c1/provenance-correction.json) records the actual frozen HEAD and executable SHA-256. This correction changes no protocol, measurement, or result data.

The complete state-, panel-, cost-, and cell-level tables are retained in [`artifacts/run-20260921-ar03c1`](artifacts/run-20260921-ar03c1). The compact equal-cell summaries are `quality-equal-cell-summary.csv` and `cost-equal-cell-summary.csv`.

## Quality and reuse

Across both anchors and every tested age `K ∈ {1, 10, 25, 50, 100}`, all four state-derived partitions—balanced k-means, warm-start k-means, one-dimensional projected ordering, and nearest-centroid quota repair—had lower analytically predicted V48 RMSE than the hash-placebo mean in all nine dataset×initialization cells. This is a strong estimator-quality result on the frozen crossed cells, not evidence of a training improvement.

At age 100, the stale balanced-k-means output-gradient partition's *predicted* RMSE was only 0.32% above a freshly rebuilt partition at anchor 600 and 0.30% above fresh at anchor 2,400. The corresponding realized 64-panel RMSE gaps were 1.66% and 1.17%. This resolves the apparent mismatch with AR-03B's “within about 0.3%” summary: that figure describes the analytic predicted RMSE; the finite 64-panel realization moves more. The shared-readout parity check confirms this is consistent with AR-03B, not replay drift.

Equal-cell mean predicted RMSE and projected component cost at `K=100`:

| Anchor | Method | Predicted V48 RMSE | Projected total (µs) |
| ---: | --- | ---: | ---: |
| 600 | Balanced k-means | 2.750e-4 | 553.0 |
| 600 | Warm-start balanced k-means | 2.750e-4 | 553.1 |
| 600 | Projected 1D ordering | 3.100e-4 | 532.6 |
| 600 | Nearest-centroid quota repair | 2.750e-4 | 554.1 |
| 600 | Hash placebo mean | 3.747e-4 | 532.5 |
| 2,400 | Balanced k-means | 5.823e-4 | 579.7 |
| 2,400 | Warm-start balanced k-means | 5.817e-4 | 572.8 |
| 2,400 | Projected 1D ordering | 6.192e-4 | 551.2 |
| 2,400 | Nearest-centroid quota repair | 5.941e-4 | 551.8 |
| 2,400 | Hash placebo mean | 6.639e-4 | 551.0 |

The one-dimensional projection is the clearest cheap construction: at `K=100` it improved predicted RMSE over hash by 17.3% at the 600 anchor and 6.7% at 2,400, while projected total cost was within about 0.1% of the hash comparison. Nearest-centroid quota repair at the 2,400 anchor retained more of the k-means quality (10.5% lower predicted RMSE than hash) at a projected total cost about 0.15% above hash. Those tiny cost differences are below what should be treated as a stable performance claim; the useful observation is the quality/cost frontier, not a sub-percent timing win.

## Construction cost

Mean measured output-feature acquisition was 12.1 µs at anchor 600 and 11.5 µs at 2,400. Mean partition construction at the same anchors was:

| Method | Anchor 600 (µs) | Anchor 2,400 (µs) |
| --- | ---: | ---: |
| Balanced k-means | 2,056.7 | 2,861.3 |
| Warm-start balanced k-means | 2,065.7 | 2,177.8 |
| Projected 1D ordering | 13.4 | 13.5 |
| Nearest-centroid quota repair | 2,162.2 | 72.1 |
| Hash placebo construction (one-time) | 14.2 | 14.2 recorded reference |

The warm-start and quota-repair cold-start fallback at anchor 600 is the exact partitioner because no prior centroids exist at the beginning of the captured trajectory. At anchor 2,400 they can use preceding captured-state centroids. Thus the late-anchor cost advantage is not a cold-start result. Feature acquisition and partition times use three optimized-build repetitions; local timings are component measurements, not portable wall-clock guarantees.

Cost projections amortize one anchor construction over `K` commits, then add measured V48 verification. Hash placebo is state-independent: its one-time construction is amortized in the first period and has zero incremental construction cost in the later period. The projections exclude unmeasured orchestration, memory, and refresh overhead and must not be called an end-to-end runtime speedup.

## Interpretation and hypothesis update

- The output-gradient response partition remains useful through 100 commits on these frozen paths; analytically predicted RMSE degradation relative to fresh reconstruction stays below 0.4% at age 100.
- The partition-construction bottleneck is separable from feature acquisition. A fixed scalar projection is roughly two orders of magnitude cheaper than balanced k-means construction and retains a consistent, smaller estimator benefit over hash placebo.
- Warm-start k-means reduces late-anchor construction time by about 24% while keeping quality close to exact balanced k-means. Nearest-centroid quota repair is especially cheap at the late anchor, but its quality is modestly below k-means and its early anchor uses the exact fallback.
- RMSE improvement did not imply uniform improvement in every downstream panel metric or every cell. Selected-program regret and false authorization were favorable in most, but not all, cells; retain those measures separately.
- AR-03C does not authorize runtime use. The results nominate projected ordering and late-state quota repair as candidates for a separately authorized compute-matched runtime test; they do not show that either improves training trajectories.

Strongest alternatives/limitations: only nine crossed cells from one synthetic task/model family were reused; states and panels are nested; measured timing uses three repetitions; cost projections omit runtime overhead; and proxy partitions were never allowed to change which evidence or actions the runtime chose. No general optimizer claim follows.
