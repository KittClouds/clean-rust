# AR-03B — Gradient-proxy and partition-refresh efficiency frontier

Status: frozen, diagnostic-only. This run reuses the AR-03A-R2 synthetic task family, crossed dataset/initialization cells, evaluation-stream seeds, K2 trajectory, and held-out action split. It does not let a proxy affect training, proposal selection, or verifier sampling decisions. No end-to-end training comparison is authorized by this protocol.

## Frozen question

How much of the full current-state 171D per-example-gradient partition's held-out verifier benefit can cheaper representations retain, what is their feature/partition construction cost, and how does a partition's verifier quality change when reused as the model state moves?

The replication units remain the nine dataset×initialization cells. Evaluation streams, checkpoint states, panel repetitions, and refresh ages are nested observations, not independent replications.

## Frozen source and substrate

- The AR-03A-R2 source, dependencies, action grammar, model, data generator, runtime, proposal/verifier streams, state/action split, hash-placebo procedure, balanced-k-means implementation, and K-means initialization are reused without modification. The frozen R2 baseline is parent commit `564613ffe1e0f80ea09021093c574f6e0ae51a83`. AR-03B contains an isolated copy of the R2 replay protocol; its only behavioral change is to capture additional diagnostic states. AR-03A-R2 files and artifacts remain read-only.
- Use the exact three R2 dataset seeds, three initialization seeds, and 18 R2 evaluation stream seeds. No new task, model, initialization, or evidence seed is introduced.
- Replay each evaluation stream through commit 4,200. At the frozen R2 checkpoints 600, 2,400, and 4,200, verify parameter fingerprints and evaluation-candidate counts against the R2 receipt before accepting any analysis. Extra capture steps are 625, 650, 700 and 2,425, 2,450, 2,500. Capturing is observational only and cannot alter replay decisions.
- At each captured state, rebuild the held-out evaluation-action universe by the unchanged R2 rule from the next P16 proposal batch. Candidate consequences are evaluated over the same 96 empirical training examples, solely as an offline measurement target.
- Action scale remains α=1. No Taylor/action-scale sweep is included.

## Frozen proxy ladder

Each proxy creates one raw, unnormalized feature vector per training example. Apply the unchanged R2 balanced K-means algorithm with exactly 12 strata of 8 examples and the R2 initialization seed. No candidate utility, held-out action consequence, or response-oracle feature may enter a proxy partition.

1. **Full gradient:** all 171 raw parameter-gradient coordinates.
2. **Output layer:** output affine weights and biases only, 27 coordinates (`W3[144..168]`, `B3[168..171]`).
3. **Last hidden layer:** second hidden affine weights and biases only, 72 coordinates (`W2[72..136]`, `B2[136..144]`).
4. **Fixed random projection:** full gradient projected to 32 dimensions by a fixed Rademacher matrix, each entry ±1/√32. Frozen projection seed: `a303425200000001`. The matrix is generated once and reused for every state/cell.
5. **Sign gradient:** coordinatewise sign of the full gradient, encoded as -1, 0, or +1 in 171 dimensions.
6. **Hash placebo:** the unchanged eight balanced hash partitions; report their equal-weight mean and between-placebo range.

Layer-local gradients are computed directly from the forward activations and required backpropagated errors, without materializing the full gradient. Projection and sign representations necessarily acquire the full gradient first. Raw feature magnitudes are retained; there is no row normalization, whitening, learned transform, or action-aware metric.

## Verifier evidence-size frontier

For every eligible held-out candidate program, evaluate the exact same response matrix on all 96 examples for diagnostic truth. Compute the analytic finite-population RMSE frontier for `n ∈ {1, 2, 3, 4, 6, 8}` examples per stratum; total verifier sizes are 12, 24, 36, 48, 72, and 96. At 96 examples, estimation error is exactly zero. Separately, draw 64 deterministic, without-replacement panels at V48 (four examples per stratum); the panel seed derivation is frozen in source and shared across methods. Empirical panel RMSE, sign error, cross-block regret, selected-program regret, and false authorization are measured at V48 only.

Report per proxy and evidence size: within-stratum utility variance and analytic finite-population predicted RMSE. At V48 only, also report observed panel RMSE, sign error, cross-block regret, selected-program regret, and false authorization. Aggregate the 64 panels within state, then states within stream, streams within dataset×initialization cell, and finally equal-weight the nine cells. Also publish cell and stream-level results. Do not treat panels, states, or ages as independent dataset-level replication units.

## Feature, partition, and verifier cost

Measure feature-acquisition time and balanced-partition construction time separately, using the same optimized executable and evaluation states. Report both per 96-example state and per example. The eight hash placebos are timed separately as a floor. Time exact candidate-verifier forward evaluation separately at each evidence size using the same candidate universe; also report its deterministic operation count (`candidate programs × examples evaluated`).

Report raw component costs first. An optional amortized scenario shows proxy refresh cost divided by reuse ages 1, 25, 50, or 100, added to the measured verifier cost at the selected evidence size. Keep refresh and verifier measurements matched to anchor step 600 or 2,400, and pair the projection with the analytic RMSE estimate at that exact reuse age; the sampled decision-error panel is available only at V48. Label this as a cost projection—not a measured controller/runtime. Do not infer a training speedup or include unmeasured system overhead as zero.

## Partition freshness sidecar

For each of the 18 evaluation streams, construct partitions at commit 600 and reuse them at 625, 650, and 700; separately construct at 2,400 and reuse at 2,425, 2,450, and 2,500. At every target state, compare:

- the **stale** partition created at its designated anchor state;
- a **fresh** partition rebuilt from the same proxy at the target state.

Evaluate both against the target state's held-out candidate responses with the same evidence-size/panel protocol. Age is exactly 0, 25, 50, or 100 commits. The additional snapshots are from exact R2 evaluation trajectories and do not extend beyond commit 4,200. Report equal-cell summaries and all nine cell summaries at every age. Fresh/stale quality is not a causal runtime comparison; it is a diagnostic of partition drift under the fixed R2 trajectory.

## Primary interpretations and stopping rules

- The main proxy comparison is each cheaper method versus full gradient and hash placebo, at matched evidence size, within each of the nine cells.
- A proxy is practically promising only if it retains a substantial share of the full-gradient estimator/decision benefit across cells and its measured feature+partition cost can be offset by verifier savings under an explicit reuse-age/evidence-size point. This is a review criterion, not permission to change runtime behavior.
- If reduced features lose quality, report that result without adding proxy families. If stale partitions decay, report the measured age curve; do not invent adaptive refresh policies.
- No learned proxy, Fisher/Hessian feature, action-aware gradient metric, feature zoo, controller use, AR-03C training comparison, extra seeds, or new substrate is authorized here.

## Integrity gates

- Freeze this protocol and source commit before running. Preserve R2 byte-for-byte.
- Run tests, strict Clippy, formatting check, and release build before collection. Build outputs go to `D:\adaptive-runtime-targets\ar-03b`; execute the binary from the C: workspace against the read-only R2 artifacts.
- Verify replay fingerprints and candidate counts at all 54 R2 evaluation snapshots. Verify the three R2 dataset hashes and model-state hash/source receipt.
- Verify all captured state/action outputs are finite; all partitions are exactly 12×8; all action IDs match the R2 held-out split; the analytic frontier contains all six declared evidence sizes; V48 panels use four examples per stratum across 64 repeats; timed verifier sizes use their declared per-stratum counts; all outputs parse; and summaries preserve the nine-cell aggregation order.
- Output to a new, non-existing run directory. Refuse overwrite. A failed integrity gate makes the run non-promotable; do not repair frozen inputs or silently rerun with changed seeds.
