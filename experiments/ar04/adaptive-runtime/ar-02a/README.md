# AR-02A — Verification portability on anisotropic Gaussian cells

Status: execution experiment. Engineering-only, toy-scale; no biological correspondence and no general optimizer claim.

## Question

On a non-spiral stochastic classification task, does coverage-aware verification improve the frozen AR-00 K2 pair runtime over same-size random verification? This is the first portability test for AR-01's evidence-composition result. AR-02B source crossover and AR-02C activation change are explicitly out of scope pending review of AR-02A.

## Frozen protocol

- Dataset: deterministic 12-cell anisotropic Gaussian mixture; 96 training samples and 48 validation samples, with 8/4 samples per latent cell. Three classes are assigned by `(row + column) mod 3`, yielding 32/16 examples per class in train/validation. Cell centers are `x=-0.9+0.9*column`, `y=-0.9+0.6*row`; each cell uses rotated Gaussian axes `sigma_major=0.225`, `sigma_minor=0.095`, and angle `0.23+0.37*cell_id` radians. Dataset generation seed is `a20209206c656c6c`.
- Model: the copied AR-01Q core's unchanged `2-8-8-3` ReLU MLP and deterministic initialization.
- Runtime: unchanged K2 logic: pair schedule/partition, top-2 singleton proposal on each coordinate, exact 2-by-2 compound evaluation on the verifier sample, global comparison of verified block utilities, bounds, action grammar, and four commits per evidence round. Total runtime commits: 4,800.
- Evidence: a 16-example proposal batch is shared by all four runtime arms for a given seed/evidence round. The verifier is also exactly 16 examples in every arm:
  - `same_batch_random`: the proposal sample reused as verifier;
  - `independent_random`: 16 independent uniform training draws with replacement;
  - `class_balanced`: quotas `[5, 5, 6]`, sampled within class with replacement;
  - `latent_stratified`: one draw from each of the 12 cells plus four predeclared repeat-cell draws `[0, 1, 2, 4]`, giving the same `[5, 5, 6]` class margin.
- Comparators: unchanged AdamW and sign baselines, each given 4,800 proposal minibatch updates. Runtime and optimizer arms use the same three frozen AR-01 seeds and begin from the same initialization per seed.
- Validation samples are never used for proposal, verification, scheduling, or commit decisions. Runtime commits are audited in shadow by measuring their full-training-set loss change; the reference audit never affects selection.
- Outputs report validation loss as primary, validation accuracy as secondary, train metrics, compute counters, wall time, and the shadow full-training-set commit audit. Runs are reported per seed; no seed is selected post hoc.

## Integrity checks

- Dataset serialization is frozen-length, header-validated, and read via memory mapping/zero-copy view.
- Unit tests validate deterministic dataset generation, balanced class composition, fixed verifier cardinality/composition, mapping parity, and K2 telemetry.
- The smoke test exercises a complete 4,800-commit K2 run.
- Candidate action counts and commits are logged; shadow reference utility is diagnostic only.

## Interpretation limits

The Gaussian-cell geometry and strata are known by construction. A latent-stratified benefit would show portability to this specific prospectively stratified task, not establish a generally available stratifier. Three seeds are descriptive. Wall times are machine/build-specific. This is not a benchmark claim and does not test path-source crossover or activation dependence.

## Observed results

Release run on the dated cleanroom branch, 2026-09-20. The mapped dataset SHA-256 is `a83d5dcce8bd8926cf1d548c58d4a9cbbef0ca97c72e1fd4331bc5d825a7a14a`.

| Method | Mean validation loss (sample SD, n=3) | Mean validation accuracy | Mean train loss | Mean runtime/run |
| --- | ---: | ---: | ---: | ---: |
| Same-batch random | 0.755435 (0.077115) | 73.61% | 0.691700 | 6.135 s |
| Independent random | 0.462739 (0.031336) | 89.58% | 0.419194 | 6.162 s |
| Class-balanced | 0.459252 (0.021122) | 84.03% | 0.411257 | 6.109 s |
| Latent-stratified | 0.501436 (0.033283) | 80.56% | 0.433902 | 6.107 s |
| AdamW | 0.292199 (0.102541) | 92.36% | 0.028797 | 0.012 s |
| Sign | 0.253423 (0.030937) | 90.28% | 0.323053 | 0.011 s |

The class-balanced mean validation loss is only `0.003487` below independent random, while its mean accuracy is `5.56` percentage points lower; it has lower loss in only one of the three paired seeds. Latent-stratified verification is worse than independent random on validation loss for all three seeds. Same-batch verification is substantially worse than every independent-evidence arm. Thus AR-01's strong geometry-stratification advantage did **not** reproduce as a robust advantage on this Gaussian-cell task. Class balance has, at most, a small mixed metric effect in this three-seed sample.

Each K2 run committed 4,800 programs and performed 4,132,800 singleton proposal evaluations plus 1,176,000 exact compound evaluations. All verifier arms used identical search counts. Full-training shadow audits found the committed move immediately improved the full training objective in 54.74% of same-batch commits, 60.53% of independent-random commits, 60.91% of class-balanced commits, and 59.51% of latent-stratified commits. These audits did not affect decisions. Runtime wall time includes those shadow audits; it is not a production-throughput comparison.

Per-seed outcomes and complete curves are in the CSV artifacts. With only three seeds, none of the small differences among independent, class-balanced, and latent-stratified verifiers warrants a broad statistical claim. The bounded update is that evidence independence remains useful relative to same-batch reuse, but **representative/latent coverage did not show a repeatable benefit here**. AR-02B and AR-02C remain gated; this result does not trigger them automatically.

## Build

Build output is directed to `D:\adaptive-runtime-targets\ar-02a` (`:G` convention), separate from source and artifacts.
