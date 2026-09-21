# AR-03C — Partition-construction frontier

Status: frozen diagnostic protocol. No partition is used to select a verifier panel, affect proposals, or alter a trajectory. This experiment measures candidate-response geometry and partition-construction cost only; it is not an end-to-end optimizer comparison.

## Question

Can deterministic, cheaper partition construction retain the V48 verifier-quality benefit of rebuilding balanced k-means over the 27-dimensional output-layer-gradient proxy, and how does each fixed partition's quality change as its source model state ages?

The experimental units remain the nine dataset × initialization cells from AR-03A-R2. The 18 evaluation streams, their captured states, candidate actions, and 64 verifier panels are nested measurements—not independent replications.

## Frozen inputs and boundaries

- Parent source state: AR-03B result commit `6649f12424efcdd3edbff251ecc354e361f11804`; R2 baseline source remains `564613ffe1e0f80ea09021093c574f6e0ae51a83`.
- Reuse the exact three R2 dataset seeds, three initialization seeds, and 18 R2 evaluation stream seeds. Do not create training trajectories or seeds.
- Reuse the R2 action grammar, K2 replay, evidence streams, held-out action split, 27D output-layer-gradient feature, response metrics, and V48 panel construction without behavioral changes.
- Replay only to capture four additional observational states, at commits 601, 610, 2,401, and 2,410. These add reuse ages 1 and 10 to AR-03B's ages 25, 50, and 100. Captures do not affect replay decisions.
- Validate fingerprints, train-loss receipts, and candidate counts against the R2 receipt at commits 600, 2,400, and 4,200. Also match all nine AR-03B snapshot-index checkpoints for each of the 18 streams.
- Preserve the R2 source and artifacts byte-for-byte. Write results only to a new, absent AR-03C run directory.

## Partition methods

Every partition has exactly 12 strata of 8 examples. No candidate utility or held-out response may enter feature construction or partition assignment.

1. **`balanced_kmeans`** — current-state 27D output-layer-gradient features, using the R2 balanced k-means implementation and initialization seed. This is the fresh-partition reference.
2. **`warm_start_balanced_kmeans`** — the same balanced k-means iterations initialized from the preceding captured state's centroids; at the first capture, fall back to the exact method. Centroids are carried forward separately for each evaluation stream.
3. **`projected_order_1d`** — deterministic fixed-seed Rademacher projection from 27D to one scalar; sorting by that value and cutting contiguous buckets of eight provides exact quotas.
4. **`nearest_centroid_quota_repair`** — assign to preceding-state centroids, then move the least-cost eligible points from overfull to underfull strata until each quota is eight. At the first capture, fall back to the exact method.
5. **`hash_placebo_mean`** — equal-weight mean over the same eight deterministic, exactly balanced hash partitions used by R2.

For each non-placebo method, report both a fresh partition constructed at the readout state and the stale partition retained from its designated anchor. For hash placebo, report the fixed placebo mean. Fresh and stale quality are diagnostics on the same frozen trajectory, not a causal runtime comparison.

## State ages and evidence measurements

Use anchors 600 and 2,400, with readout ages `K ∈ {1, 10, 25, 50, 100}`: steps 601/610/625/650/700 and 2,401/2,410/2,425/2,450/2,500. Anchor-state partitions are age 0 and are retained for the respective readouts. Step 4,200 is an integrity checkpoint, not a quality readout.

At each readout, evaluate the exact same held-out candidate-response matrix. Primary quality outputs are within-stratum utility variance, finite-population predicted V48 RMSE, and observed RMSE over 64 panels. Also report sign error, cross-block opportunity regret, selected-program regret, and false authorization. The panel draw seed and candidate universe are shared across methods at a state.

Report per-stream, per-cell, and equal-weight nine-cell summaries. Do not treat panels, states, or reuse ages as independent replications. Preserve all per-state and per-panel rows.

## Construction and cost-quality frontier

Measure output-feature acquisition and each fresh partition-construction method separately using three optimized-build repetitions and the median duration. Time the eight hash-placebo construction separately. Measure V48 candidate verification at each readout state using the same held-out candidate universe.

For each anchor/method/readout age, publish the diagnostic projection:

`(feature acquisition + partition construction at anchor) / K + measured V48 verifier time at readout`.

Pair the projection with the stale partition's quality at exactly that age. Hash placebo is state-independent: its one-time construction cost is amortized in the first (600-anchor) period and its incremental construction cost at the later (2,400) anchor is zero. The measured hash construction time remains separately reported. This is a component-cost projection, not an observed controller runtime; it excludes unmeasured system overhead. Keep raw acquisition, partition, and verifier timings available so the projection can be audited. No method is allowed to change the verifier sample or training policy.

## Integrity and stopping rules

- Run formatting, unit tests, strict Clippy, and optimized release build before collection. Build under `D:\adaptive-runtime-targets\ar-03c`; execute the binary from the C: workspace.
- Require 18 evaluation streams × 13 captured states, 54 R2 checkpoint validations, 162 AR-03B checkpoint matches, 18 × 12 quality readouts × 17 quality rows per readout, and 900 cost-frontier rows.
- Require finite features, losses, and candidate responses; exact 12×8 balance for every partition; correct held-out candidate identity; and exact readout ages.
- Validate output JSON and every CSV's row width/count before interpretation.
- If a cheaper method loses quality or a stale partition decays, report it without adding another partition family, changing seeds, or tuning methods. No learned proxy, runtime/controller use, or end-to-end training experiment is authorized by this protocol.

## Run

From this directory, build with `CARGO_TARGET_DIR=D:\adaptive-runtime-targets\ar-03c` and run the optimized executable from the repository workspace, passing the output, R2 artifact, and AR-03B artifact directories explicitly. The executable refuses to overwrite an existing output directory.
