# AR-03D — Projected-order versus hash verifier control

Status: frozen, paired end-to-end diagnostic. Only the verifier-panel partition differs between the two arms. No adaptive refresh rule, other partition family, action change, optimizer change, or CF-01 work is included.

## Question

Does the low-cost, one-dimensional ordering of current-state output-layer gradients improve the actual learning trajectory when it controls V48 verifier evidence, compared with balanced hash-placebo strata, at the same proposal stream, candidate policy, verifier sample count, and decision-slot budget?

This is a runtime intervention, not another offline estimator-RMSE comparison. The primary endpoint is final loss on a prospectively generated, independent 96-example evaluation set. AR-03A-R2 contains no validation split; this added set is measurement-only and is never read by the runtime.

## Frozen parent and substrate

- Parent is the pushed AR-03C result commit `f850f537e15e28024cca163b43ad6e4052b2b535` on `codex/ar-03c-partition-frontier-20260921`.
- Reuse AR-03A-R2's nine dataset × initialization cells, three training datasets, three model initializations, and 18 evaluation-stream seeds. No training seed or training example changes. The nine cells are the replication units; two paired evidence streams per cell are nested.
- Each stream is run under both arms from the identical initial model. The policy uses 4,200 decision/commit slots, with readouts at slots 0, 600, 2,400, and 4,200. A slot with no selected positive program is recorded as a no-op; both no-op and accepted-update counts are reported.
- Preserve the R2 runtime unchanged: 8-8-8-3 ReLU MLP, 171 parameters, bounds `[-2,2]`, action grammar `{0, ±0.005, ±0.01, ±0.02}`, P16 proposal minibatches, top-2 × top-2 pair verification, rotating coordinate-pair schedule, and four sequential replans per proposal/evidence round. The 16-example proposal minibatch and its seed-derived contents are identical between paired arms.
- Training datasets use the unchanged R2 seeds `a303dada00000001`–`a303dada00000003`; initialization seeds are `a3031a1700000001`–`a3031a1700000003`; evaluation-stream seeds are `a303ea0000000001`–`a303ea0000000012` in the frozen R2 cell ordering.
- For the primary held-out endpoint only, generate one independent 96-example evaluation set per training dataset with seeds `a303fa0000000001`, `a303fa0000000002`, and `a303fa0000000003`. These seeds are distinct from all frozen training, initialization, and stream seeds. Evaluation samples are only used at slots 0, 600, 2,400, and 4,200 to measure cross-entropy and accuracy; they cannot affect proposals, partitions, panel draws, selection, or commits.

## Arms

Both arms use exactly 12 strata of 8 training examples and draw 4 examples without replacement from each stratum for a V48 verifier panel. The same deterministic panel RNG and proposal batch are used at each evidence round in a paired stream. A panel is held for the same four decision slots as in R2. Panel quotas, uniqueness, and panel/proposal fingerprints are recorded.

1. **`projected_order_1d`** — At initial state and then every 100 decision/commit slots, compute each training example's raw 27D output-affine-layer gradient. Apply the frozen AR-03C Rademacher sign projection (`ORDER_SEED = 0xa3034350524f4a31`, with the same `1/sqrt(27)` scaling), sort by projected scalar with original sample index as the deterministic tie-break, and cut consecutive groups of eight. A partition is used for the next 100 slots. Refresh is fixed at slots 0, 100, …, 4,100; no drift-trigger or adaptive refresh is allowed.
2. **`hash_placebo`** — Use the unchanged R2 balanced hash partition. Assign the partition ID prospectively as `(cell_index * 3 + stream_within_cell * 4) mod 8`; this covers all eight placebos, gives the two streams in each cell different partitions, and is independent of outcomes. The state-independent partition is fixed for the full stream; its one-time construction is recorded. The 100-slot projected refresh clock does not cause pointless hash recomputation.

Apart from panel membership, the policy is identical: the same selector schedule, top-2 × top-2 rule, action grammar, proposal inputs, V48 evidence size, and decision-slot budget. Because trajectories may diverge, bounds can leave different numbers of legal candidate programs in each arm; the actual number of verifier evaluations is recorded per slot rather than assumed equal. “Compute matched” therefore means matched policy/evidence budgets, not guaranteed equal candidate-evaluation counts or wall-clock time. Treatment-specific partition construction and all component runtimes are measured in the total-cost result.

Because the states diverge after treatment starts, candidate values and selected programs may diverge naturally. The candidate-generation rule, action grammar, proposal data, evidence-round schedule, coordinate-pair schedule, decision budget, and no-op rule remain frozen; the experiment does not force post-divergence candidate identities to match.

## Outcome-blind full-reference observer

Immediately after each arm selects a program and before applying it, score only that selected program on all 96 training examples. This exact full-training-objective utility is logged and then discarded; it cannot affect selection, partition construction, or commits. No best-action search is done in the shadow path. Consequently, the study reports selected utility, harmful selected utility relative to the no-op, false authorizations, and harmful-commit tails—not regret to an uncomputed full-reference oracle winner.

## Measures and aggregation

Primary: held-out cross-entropy at slot 4,200, paired `projected_order_1d − hash_placebo` differences by stream, equal-weight cell means, and direction across the nine dataset × initialization cells. Report held-out loss trajectories at all four readouts. Accuracy is secondary; full-training loss is a diagnostic, not a generalization metric.

Secondary: per-slot shadow full-training utility for chosen programs; beneficial/harmful accepted-update counts; false-authorization rate; cumulative beneficial utility; cumulative harmful utility magnitude (the no-op-relative selected-program regret); p90/p95/p99 and maximum harmful utility; actual accepted updates and no-op slots; final/checkpoint train loss; held-out accuracy; partition feature/build, panel, policy, shadow, and total elapsed times. No panels or decision slots are counted as independent replications.

The full-reference observer cannot measure regret against the best unselected action without evaluating all candidate programs on all 96 examples. That substantially changes shadow compute and is explicitly excluded; the output will not label no-op-relative harmful utility as oracle regret.

## Integrity gates and stop rule

- Before collection: format, unit/protocol tests, strict Clippy, and optimized release build. Build under `D:\adaptive-runtime-targets\ar-03d` and execute from this C: worktree. Freeze source/protocol in a commit before running.
- Exactly 9 cells × 2 evaluation streams × 2 arms = 36 trajectories; 4,200 decision slots each; 1,050 paired-evidence panels per trajectory; projected refreshes at the 42 declared epochs per evaluation stream; one fixed hash partition per hash stream.
- Validate the 3 training and 3 evaluation dataset hashes; all seed disjointness; exact R2 proposal-batch identity between paired arms; same coordinate-pair schedule; panel size 48, unique indices, 4-per-stratum balance; exact 12×8 projected/hash partitions; correct K=100 refresh boundaries; finite utilities/losses; checkpoint fingerprints; and all CSV/JSON counts and parseability.
- Verify that shadow observer outputs never enter policy selection or partition code by module/API boundary and tests. Shadow computations are equal-scope diagnostics after selection only.
- Keep the AR-03C raw artifacts, including `provenance-correction.json`, byte-for-byte unchanged. CF-01 remains unstarted and untouched.
- No extra partition method, refresh tuning, new training seed, or post-result parameter change is authorized by this run. If integrity fails, preserve the run as non-promotable and report the failure; do not silently repair or rerun under changed seeds.

## Run

Use a new, absent output directory. The executable refuses to overwrite. The binary records its SHA-256 and the frozen source commit in the integrity receipt.
