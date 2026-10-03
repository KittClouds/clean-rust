# R1 Stage 1 engineering log

Date: 2026-09-26 (UTC)

This log records engineering attempts, not a preregistered scientific result. Stage 0 remains sealed. Stage 1 revisions retain earlier source and run artifacts.

## Frozen Stage 0 and sensor extraction

- Stage 0 source commit: `fb984e362a20c7a6ede2eb66b120859f150477d1`.
- Stage 0 source seal root: `dfe238d2e594ebbfa18ed2248444fbf61d21ca9f262562cce86e5c457474e66f`.
- Stage 0 run: `D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage0-v01\construction-attempt-v02`.
- Frozen public input SHA-256: `eed1f65aa9a1a51f7887808dae88655c1266cfeac674bf25611c0cd6cd8f6c58`.
- Frozen support v02 SHA-256: `b05e99f83cec97342582dbacec0a3c7ba0bf634130f301dd909a886bcbb66e46`.
- Extraction run: `D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v02\sensor-extraction-v01`.
- Extraction receipt SHA-256: `9d7714338ba0302d78d76eb75b4a7e8eb553921433e388b3d4b217e6d7ce3939`.
- `constraint_H.float32.npy`: shape `(872, 2048)`, SHA-256 `8c09bbc2a5219b15047372720a46d11c3ce018369ada4d2200bf0068b8056181`.
- `global_h.float32.npy`: shape `(96, 2048)`, SHA-256 `26152970dc396d50cbe87f90ef5b8f54b6b7b2147a846253904382457cdc3b72`.
- `rows.jsonl`: SHA-256 `dd143f882f3bf0ba06ecec0db850b760290933cdfb6eb2945af23e62cd1f16ec`.
- Offline labels: 872 clause rows and 55,008 action rows. Their hashes and qualification support floors are recorded in `offline-labels-v01/support-summary.json`.

## Sensor probe v01: first executable run

Source snapshot: `sensor/probe_sensor-v01.py`, SHA-256 `e1117fc571f287307bac1006d07cc65972a47635fea821438d929257e706474d`.

The preserved first run at `D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v02\sensor-probes-v01` failed with `KeyError: 7`. One valid public task has no constraints, so the action feature builder could not find a constraint-row list. This is an implementation failure, not an LFM result. The output contains `failure.json` and the code hash. The repair handles missing constraint lists as empty and uses a zero constraint mean for the empty task.

## Sensor probe v02: declared v01 diagnostics

Source snapshot: `sensor/probe_sensor-v02.py`, SHA-256 `8f2a81e0d3def2102a1a6f007e30a67de6bc8001e810a4f66090601052eeb7b3`.

Completed output: `D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v02\sensor-probes-v02`.

| Diagnostic | Validation | Qualification | Interpretation |
|---|---:|---:|---|
| Clause identity balanced accuracy | 0.985 | 0.971 | Passes the declared 0.90 metric |
| Template-only identity balanced accuracy | — | 0.167 | Low shortcut baseline |
| Pooled-H slot binding, entity micro-F1 | — | 0.268 | Fails |
| Pooled-H slot binding, role micro-F1 | — | 0.489 | Fails |
| Pooled-H slot binding, combined F1 | 0.364 | 0.379 | Fails |
| Pooled action MLP macro-F1 | 0.468 | 0.384 | Fails |
| Name/incidence-only action macro-F1 | 0.704 | 0.647 | Control |
| Template-only action macro-F1 | 0.713 | 0.650 | Private-metadata oracle shortcut only |

The v01 action comparison was confounded: its primary model omitted 12 public co-entity incidence counts that its incidence-only control included. The run remains a valid record of the declared v01 probes but cannot isolate the contribution of H. The pooled-H binding miss only tests one fixed affine readout over clause and task means; it does not establish that the representation lacks binding information under other adapters.

## Sensor probe v02 manifest: matched public-feature repair

Manifest: `manifests/sensor-probe-fit-manifest-v02.json`, SHA-256 `58ec8d28565169d2a04816c97ef7406bfd6f30b68eae0d3f10ac65e692a8b811`.

Implementation snapshot: `sensor/probe_sensor-v03.py`, SHA-256 `b4f3f37de1f348a905000ee4a74246ea289fbbf882879f8fc42d67dab1b6f860`.

The primary action vector now begins with the exact 259 public assignment/edit/incidence features used by the name/incidence control, then appends global H, mean all-constraint H, and mean edited-entity-incident H. All feature extraction outputs and label files are checked against their receipts before fitting. Binding positive weights follow the manifest without a floor at one.

Completed output: `D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v02\sensor-probes-v03`.

- Identity remains 0.971 balanced accuracy on the previously reported qualification partition.
- Binding remains a failure under the pooled-H affine readout (combined F1 0.379).
- Matched public-incidence-only action macro-F1 is 0.644 on qualification.
- Incidence plus the three pooled H summaries scores 0.390 macro-F1.

This is an adaptive engineering retest, not independent confirmation. The result points to lossy mean pooling and inadequate action-state interaction, not yet to a limit of the frozen LFM.

## Compositional semantic action adapter v01

Manifest: `manifests/semantic-action-adapter-manifest-v01.json`, SHA-256 `4bac71dc6673fdab6dcfefea8407dc84af8694f01c1e5d029f9b858e5920e02d`.

Source: `sensor/action_semantic_adapter.py`, SHA-256 `269160a6f8ef822a815b90c9167455afbe84e26f2c54d1710c8447a2ae2dd248`.

Output: `D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v02\semantic-adapter-v01`.

The adapter applies the frozen identity head to each constraint vector. For each candidate edit, it combines the six clause-kind probabilities with public entity/role incidence and the complete assignment, simulates each declared clause rule before and after the edit, sums expected per-clause satisfaction changes, and emits the sign. Private clause kinds appear only in a separate offline oracle comparison; private kinds and action labels do not enter the runtime score.

| Scoring path | Train macro-F1 | Validation macro-F1 | Qualification macro-F1 |
|---|---:|---:|---:|
| Frozen identity probabilities + public incidence | 0.989 | 0.980 | 0.974 |
| Private-kind oracle + public incidence | 1.000 | 1.000 | 1.000 |

The 0.974 qualification result is an adaptive engineering diagnostic because this partition was already reported by sensor probes v01 and v02. It shows that composing a strong kind sensor with public incidence and an explicit rule interpreter makes action consequences highly accessible on this task family. It does not validate the pooled action MLP or establish broad language generalization.

### Compositional adapter v02: observed implication shape correction

The independent source audit found that all 48 implication clauses in this support have one unique entity ID and two distinct role IDs. Each is a tautology, so the affected action delta is always zero. The generic v01 two-entity pairing branch was not exercised. Adapter v02 preserves v01 and encodes the actual tautology explicitly; it does not claim to test nontrivial implication grounding.

- Manifest: `manifests/semantic-action-adapter-manifest-v02.json`, SHA-256 `c2c4c3427fae75972e3c17224f4e0a696e7fc494ee54afa5aeaf2b4e9819fc47`.
- Source: `sensor/action_semantic_adapter.py`, SHA-256 `153fd7c1d0705184b269048e710a3ef24ec7e451cc2cfe2347d3ff3b2ec8d32c`.
- Output: `D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v02\semantic-adapter-v02`.
- Action rule unit tests: 8/8 passed.
- Scores reproduce v01: identity probabilities + public incidence 0.974 qualification macro-F1; private-kind oracle + public incidence 1.000.
- Independent audit confirmed the score arithmetic, input joins, manifest/receipt hashes, and offline-label boundary.

## Q_terminal v02

Source: `qterminal/manifest-v02.json`, SHA-256 `0cd7f5bd26e0ea59b2d29d83240cea013dc80ed75c3ac524ad16bc65473855a5`.

Run root: `D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v03`.

- Candidate traces: 332 replay-verified traces, 84,992 charged expansions.
- Dataset: 520 train, 50 validation, 24 held-out test rows.
- Validation balanced accuracy: 0.66.
- Test balanced accuracy: 0.50; ROC-AUC 0.653, with only four held-out families.
- Checkpoint SHA-256: `e484bdb0e51196002bcda997a96b9b5a40ace7a4b81e60e08396a32072c6e5f0`.
- Fit receipt SHA-256: `b3586adddc4eee33771b183dc719dcf1e8e4e81cae4e62d298da4424b9afdaab`.

This selector is not yet competent enough to make planner selection comparisons persuasive. The candidate generator, offline data preparation, replay checks, and fit all execute. Improve or broaden the selector training support while preserving the current fit.

## Current next work

1. Train and freeze the one-step proposal, then generate and fit `V_reach` under the exact proposal digest.
2. Retain the known limitation that the first proposal scorer does not consume the latent state.
3. Run the actual search arms with complete traces, post-hoc oracle reachability, the shared terminal selector, and operation/active-time/wall-time prefix curves.
4. Improve `Q_terminal` and the action interface in parallel. The semantic action adapter is a candidate control path; compare it with the learned proposal and preserve the original MLP as a failed baseline.
5. Broaden stress regimes after the first integrated machine runs: sparse/dense constraints, deceptive basins, long dependencies, prefix/suffix patterns, and assignment-merge continuation loss.

Do not describe any adaptive result here as an independent scientific confirmation. These results are intended to expose failure locations and guide the next implementation version.

## Proposal and V_reach v01

Run root: `D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v03\proposal-value-v01`.

- Run receipt SHA-256: `5871a6d709433076c01ddbc9f3adae459825c648fcf924fb67caa7c577af40fd`.
- Proposal teacher states: 2,048 (1,536 train / 512 validation); teacher is the class-balanced one-step reachability teacher.
- Proposal train/validation cross-entropy: 2.329 / 2.284; teacher mass at argmax: 0.178 / 0.175 versus uniform baselines 0.071 / 0.067.
- V_reach: 6,144 state-budget rows and 12,288 seeded rollouts; train/validation BCE 0.358 / 0.429, validation Brier 0.134 and AUC 0.663.
- Every validation probability exceeded 0.5, so threshold accuracy equals the majority-positive baseline (0.829). This is modest ranking signal, not yet useful allocation behavior.
- Qualification tasks were not consumed. Q_terminal v02 was pinned but not used as a proposal/V input.
- The v01 proposal uses eight H-derived summaries plus occupancy features; it does not consume the semantic action adapter or latent state. The v01 V_reach training starts with zero latent state and uses 16/32/64 horizons, producing mostly positive labels.

Preserve v01. The v02 engineering repair adds the pinned identity-probability semantic action signal and public incidence to proposal scoring, freezes/digests that proposal before creating V_reach labels, and trains V_reach on shorter horizons plus proposal-trajectory states. Qualification remains excluded from tuning.

## Build drive availability

The supplied `AGENTS.md` requests a G: build target, but this host currently exposes only C:, D:, and E: filesystem drives. Preserve the requested source-on-C / external-target separation by using the established D: `D:\cargo-targets\fas-r1-stage1-v01` target path, then execute tests from the C: worktree. Recheck mounted drives before any future build.

## Integrated proposal/V-reach pilot and merge-key ablation

The prior 32-task qualification pilot is an adaptive engineering diagnostic, not an independent confirmation. It completed 190 task-arm traces, skipped 34 canonical/particle conditions on ineligible grammars, and replayed every executed trace successfully. At 64 charged expansions, reachability/selected-valid counts were: depth 31/29, sampled depth 32/30, random width 8/8, learned width 29/27, assignment-merged width 31/29, canonical merge 15/13 on its 15 eligible tasks, and particle 13/12 on those same 15 tasks. The task family is too easy for a width claim: depth already reaches 31/32 by expansion 8. V_reach returned the same 0.4233177 value at every observed call, so it supplied no ranking signal. The terminal selector still lost two reached solutions in several arms.

The next adaptive run used the v02 pilot schema and added a paired `merged_width_strict_dynamic` condition. The same qualification tasks, task-derived seed, proposal, selector, and 64-expansion budget were used. Its output is `D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v05-merge-key-v02`. The first launch attempt (`run-v05-merge-key-v01`) used a stale input path, failed before loading tasks, and is preserved separately. The successful run has 222 executed condition traces, 34 expected canonical/particle skips, and 222/222 deterministic replays passed. Its pilot manifest SHA-256 is `43de0b9e3602bf10ff2bbbebfb979d019717d742822160be1dcad474e6467c89`; the 1,112,064-byte release binary SHA-256 is `181e0fc6fb58597a961f5142eb0203dd185786bad9d8e787a0c3833bde0b20cd`.

At 64 expansions, the paired merge comparison was:

| Condition | Reachable / 32 | Selected valid / 32 | Mean active CPU ms / task |
|---|---:|---:|---:|
| Assignment-key merge | 31 | 29 | 29.61 |
| Strict full-dynamic-state key | 29 | 27 | 30.43 |
| Learned width, no merge | 29 | 27 | 20.89 |

Assignment-key merging made 1,076 merges; strict dynamic identity made none. The assignment merge produced two additional reachable and selected-valid tasks relative to strict identity. This suggests slot recycling can help on the present easy worlds even while collapsing distinct latent states; it does not establish that this heuristic preserves continuation quality. The strict-key run paid its key-tracking cost without merging and ended at the same reachability as unmerged learned width. The merge-event telemetry found nonzero latent divergence in 470 assignment merges. Preserve the heuristic for harder stress runs and inspect its per-merge continuation losses there.

Expansion, active-time, and wall-time prefix curves are derived from complete traces. The reported active and wall clocks cover the scheduler/search execution only; frozen-LFM extraction and `policy.prepare_bound_task` run before timing and are excluded. They are not end-to-end latency. Qualification active/wall prefix results are engineering traces, not independent evidence. All seven original arms and the strict-key condition were replay-verified. Stage 0 source and run bytes remain untouched.

The pilot source now labels every condition independently, including the two `MergedWidth` merge modes, and records that distinction in traces, prefix rows, and the run manifest. Release all-target tests pass (18/18); release Clippy passes with warnings denied; the pilot binary builds successfully. Relevant current source hashes: pilot `382ef3b65deabfda81feb1871cd32861f236a8d86ebcea99d672fe32f0eb6dbd`; scheduler `aac5d0c85eba14e915c61b95cd83f075fed48817aa28d40aa2a5cdaaf8f53cb3`.

Next: run the frozen sensor on the Stage1-only n=14/18/20 graph-coloring batch, compare depth, sampled depth, learned width, assignment merge, strict identity, canonical merge, and particle with complete replayed traces, then use the failures to revise the proposal/value/merge machinery. The first generated batch's density labels are adaptive search starts rather than strict disjoint density strata; use its measured edge counts/probabilities as recorded, and correct the stratification contract before describing it as a density ladder.

## Particle cooldown and merge-key repair, V12

The initial cached-value particle run was underperforming. Trace inspection showed that cached reachability values were compared at different remaining horizons, and that greedy particle resampling could replace branches before they had meaningful allocation. V11 therefore added explicit `CachedTransition`, `EveryExpansion`, and `ResampleBoundary` scoring modes; resample-boundary mode refreshes values at a common remaining-budget horizon and allocates round-robin between resampling points. It also records a configurable minimum allocation age, prevents resampling from exceeding the width when no eligible victim exists, and adds a width-one regression test. V12 adds matched particle conditions for canonical-assignment merge, strict dynamic-state identity, and no merge.

The first V05 cooldown launch, `run-v46-v05-resample-period4-minalloc8-v01`, paired the v02 public task file with a sensor extraction receipt pinned to the v03 task file. The receipt check failed before search; the empty attempt directory is retained. Corrected runs use the matching 16 qualification tasks from `run-v20-stress-worlds-v03` and `run-v21-stress-sensor-v01`, proposal `incidence_masked_norm_4_v03` (`45960e4c62129998164ce6eaa20531ce8ea171bae962a979253b404d55f03ce0`), V_reach v05 (`f809e25c93ba8a99b769e3209d09294983089aadf601980425e89505ab8a85e6`), Q_terminal v07, paired seeds, and 256 expansions. The same V12 executable ran all merge-key comparisons; every trace replayed successfully and every arm had reachability equal to selected-valid count.

| Particle configuration | N14 | N18 | N20 | Reach / selected | Active CPU | V calls | Resamples |
|---|---:|---:|---:|---:|---:|---:|---:|
| Canonical merge, min allocation 1 | 5/6 | 2/6 | 1/4 | 8/16 | 2,101 ms | 12,396 | 1,008 |
| No merge, min allocation 1 | 5/6 | 2/6 | 0/4 | 7/16 | 2,005 ms | 11,280 | 1,008 |
| Canonical merge, min allocation 16 | 5/6 | 4/6 | 2/4 | 11/16 | 1,562 ms | 8,069 | 327 |
| No merge, min allocation 16 | 6/6 | 3/6 | 3/4 | 12/16 | 1,369 ms | 6,107 | 154 |
| No merge, min allocation 32 | 6/6 | 5/6 | 3/4 | 14/16 | 1,138 ms | 4,336 | 16 |

All rows use resample period 4. Strict dynamic identity exactly matched no merge in the age-1, age-16, and age-32 comparisons: it found no full dynamic-state duplicates, so exact-key bookkeeping bought nothing here. The no-merge age-32 particle reaches and selects 14/16, matching the prior learned-width and sampled-depth arms at 14/16; it costs about 16% more active CPU than learned width on this task set. Its task-level hit set is exactly the learned-width hit set, so particle resampling adds no new reachable task here. It beats deterministic depth at 8/16 and random width at 0/16, but does not establish a reachability advantage over ordinary learned width. A separate age-16/period-8 run fell to 7/16 at nearly the same cost, so cadence remains behaviorally sensitive.

The age-32 no-merge result uses only 16 resampling events across the 16 tasks. Its success is therefore mostly a broad, long-lived particle pool with sparse value-based replacement. The current engineering candidate is `particle_no_merge`, resample period 4, minimum allocation 32; the next useful push is to stress that machine on a harder generator and compare against learned width under both transition and measured-time budgets. Do not infer that value-guided resampling caused the tie.

Run roots and pilot-manifest SHA-256:

- `run-v52-v05-particle-merge-key-cooldown16-v01`: `dc98f0a89557fb9c255263d2e1465ab03d964f0afe64681cf30e9f9a62766b80`.
- `run-v53-v05-particle-merge-key-minalloc1-v01`: `45a8e141de7ec45309d891d64bda3ee6f5b3a01352a93c2138b80cc6a37a8a0a`.
- `run-v54-v05-particle-merge-free-minalloc32-v01`: `8113aa333c07744a5089932df93745e340cf596c4278a93f833a0b83a778cdaf`.

The release pilot executable SHA-256 is `19a5d7cdd2f780b5d49b5d1c948749b1e7e5ae64309c36dc116b6ab9910e3676`. V12 source hashes: scheduler `dc3e7ee70cf46b19ee1900f0df4c5f04716da035f159d591ed658ded8dff9fd4`, scheduler support `4d555dd1a5106995806a56e587e635c2992d61b12bb686437fa87eb6e87a985a`, pilot `f1746952b4e1a656dbc6adb80bbccd5a033804eb3c1aac7844038d3622dd12f2`, replay `fb0b60c6d819450e37522683670942af4504108832188e74070099e453e718e0`, and search tests `e3bbe90a472ad46b0ad3a18066f05453f745a56cd6b8db90469875f84e9e2c9f`. Formatting, all 27 tests, warning-denied all-target Clippy, and the optimized pilot build pass. Cargo target output remains on D: because G: is unavailable. Stage 0 source and run artifacts remain untouched.

## Matched all-world topology comparison, V13

The first mixed-arm train replay (`run-v55-v05-train64-width-vs-particle32-v01`) failed before its first expansion because the pilot applied `--particle-resample-only` to `LearnedWidth`. V13 scopes V-reach refresh policy to Particle arms, preserves cached/no-value behavior on the other arms, and bumps the pilot manifest schema. The failed directory is retained. All successful V13 runs used the same executable `2c0f1061f189b357698ac2e2d79380e31b0b3cd80b9842cce7db7e537d8985c5`, the same 96-world roster, proposal, V05 checkpoint, selector, 256-expansion budget, and task-derived paired seeds. Every trace replay passed; reachability equaled selected-valid for every task.

| Arm | N14 | N18 | N20 | Reach / 96 | Active CPU |
|---|---:|---:|---:|---:|---:|
| Deterministic depth | 16/32 | 10/32 | 13/32 | 39/96 | 1,828 ms |
| Sampled depth | 31/32 | 28/32 | 29/32 | 88/96 | 3,528 ms |
| Random width | 0/32 | 0/32 | 0/32 | 0/96 | 2,499 ms |
| Learned width | 31/32 | 25/32 | 25/32 | 81/96 | 3,170 ms |
| Particle, no merge, min allocation 32 | 31/32 | 25/32 | 25/32 | 81/96 | 6,467 ms |

The no-merge age-32 Particle hit the exact same 81 tasks as learned width and added no reachability on any of the 96 worlds. It made 26,016 V calls and 96 resampling operations, taking about twice the active CPU. That closes the present particle-resampling branch on this generator: keep it as a comparison arm, but do not spend more effort tuning its age/cadence here. Learned width still substantially exceeds deterministic depth, but sampled depth is the strongest arm at 88/96. The remaining width-versus-depth question is therefore whether width can beat a stochastic single trajectory across paired initial seeds, not whether it can beat only deterministic depth.

The train and validation partitions contributed to fitting/iteration, and the qualification partition is already adaptively reported; this full roster replay is engineering diagnosis, not confirmation. Output manifests:

- Train, learned width / Particle: `run-v56-v13-train64-learned-v-particle32-v01`, SHA-256 `3172390cac1b9a0f30acfdda58926c0c7da99fb40820d4b0a66388d74d8271e9`.
- Validation, learned width / Particle: `run-v57-v13-validation16-learned-v-particle32-v01`, SHA-256 `b65fa1dc081c87bf7acfad8edfce439bc6f31ef1f327cde5097609afb5a98d4a`.
- Qualification, learned width / Particle: `run-v58-v13-qualification16-learned-v-particle32-v01`, SHA-256 `22ab9b252acbbacd72b946ca485b2689016f4f2d74ede2302387300321b08a11`.
- Train, depth / sampled depth / random width: `run-v59-v13-train64-depth-sampled-random-v01`, SHA-256 `122c58184bfb61fd27e1c9ef8a45059727c25a711538f39a82b665caffa9e231`.
- Validation, depth / sampled depth / random width: `run-v60-v13-validation16-depth-sampled-random-v01`, SHA-256 `f77f832bd692f6c3b3243319d535cc23fa4761e293af2a4474527b9467a8e3d4`.
- Qualification, depth / sampled depth / random width: `run-v61-v13-qualification16-depth-sampled-random-v01`, SHA-256 `dea174fc39d5becef446974e7b99f04b7e735ad41b35ec47196b344a3b15862b`.

V13 pilot source SHA-256: `9575ab791aefd5abc669e6bac169dd2dd489cbf8573015ef31eca69317997d14`. Next: add a logged seed salt and compare deterministic depth, sampled depth, and learned width across several paired starts on the same task roster. This will show whether sampled depth's current lead persists across starts before building a new adversarial world family.

## Paired initial-seed sweep, V14

V14 adds `--seed-salt` to the pilot. It XORs the salt into the task-derived paired seed and records it at the top level of the pilot manifest; salt zero exactly reproduces the V13 trace IDs for all 48 qualification traces checked. The purpose is to vary both the initial assignment and the deterministic proposal stream while keeping each arm paired on each task/salt.

Four salts (0 through 3) were run on all 16 qualification tasks with deterministic depth, sampled depth, and learned width, each at 256 transitions. All 192 traces replayed, and `R=S` on every task/salt.

| Arm | Salt 0 | Salt 1 | Salt 2 | Salt 3 | Total |
|---|---:|---:|---:|---:|---:|
| Deterministic depth | 8/16 | 5/16 | 5/16 | 4/16 | 22/64 |
| Sampled depth | 14/16 | 13/16 | 14/16 | 13/16 | 54/64 |
| Learned width | 14/16 | 14/16 | 14/16 | 14/16 | 56/64 |

This strengthens the engineering case for multiple hypotheses over deterministic depth on the current family. Learned width slightly exceeds sampled depth across these four starts, while the V13 one-start all-world replay had favored sampled depth. Do not elevate the 2/64 difference into a general claim: the qualification set has already guided iteration.

A useful trace-level failure pair emerged on `stress-n20-e42e9acd2e86c9b6da84ef95` (44 edges, density 0.232, 16 canonical solution classes). With the same initial assignment at salt 0, sampled depth finds a valid assignment at transition 182; learned width misses it at all four salts, with per-particle depth capped at 32. A protected long trajectory alongside shallow branches is the next engineering candidate: it could preserve deep-basin access without abandoning alternate futures.

Pilot executable SHA-256: `d937baa2ff06ea186d41f7353dc5471226ee1855715ff1a37371e3480055e2db`. V14 pilot source SHA-256: `d7b63eb7b15a8a2c656b5f2a5c32f3eef1c123e8f3fdcbad090847209cf464d8`. Run manifests:

- Salt 0: `run-v62-v14-qual-seed0-v01`, SHA-256 `439469446368471c6e201b0845d818972403af9ae029e0f51aa9dcebaa47cd4b`.
- Salt 1: `run-v63-v14-qual-seed1-v01`, SHA-256 `261b9d72dce98f7634372269e153a5b3e6ba8920aca286a4650ddd75710a5670`.
- Salt 2: `run-v64-v14-qual-seed2-v01`, SHA-256 `c78eca78fbc3c46a00c92251b624fe077aa02d495aa01a5e7211b21b1bc49658`.
- Salt 3: `run-v65-v14-qual-seed3-v01`, SHA-256 `b83db95e5c008dcd88423348d6976bad58fbfbde845a33a47d4d437c203e987e`.

## Protected spine, V15

V15 adds a Stage1-only `ProtectedSpineThenWidth { spine_budget: 192 }` schedule on the `LearnedWidth` proposal path. Particle 0 follows the same seeded sampled trajectory as `SampledDepth` for expansions 1–192 and is then frozen. Particles 1–7 retain the original assignment and their independent, task-seeded RNG streams; they are delayed root trajectories, not copies of the spine endpoint. Expansions 193–256 cycle over IDs 1–7, giving particle 1 ten expansions and particles 2–7 nine each. This schedule uses no V_reach, merging, or value-based particle selection. Its assignment/transition trace records the spine and alternate paths; the manifest clarifies that `nominal_slot_particle_id` remains the legacy round-robin reference and `value_allocation_non_nominal` is reserved for Particle V_reach allocation.

The first V15 invocation used an invalid proposal-mode CLI value (`incidence_masked_norm_4_v03`); argument parsing rejected it before model loading or output-directory creation. The corrected parser value is `incidence_masked_norm_4`. No search trace was produced by the rejected invocation.

Four paired seeds (0–3), 16 qualification tasks per seed, and 256 transitions per task were run for `sampled_depth`, `learned_width`, and `learned_spine192`. All 192 traces replayed successfully, all conditions completed exactly 256 expansions per task, and `R=S` throughout. These are adaptive engineering observations on the existing qualification roster.

| Condition | Salt 0 | Salt 1 | Salt 2 | Salt 3 | Total |
|---|---:|---:|---:|---:|---:|
| Sampled depth | 14/16 | 13/16 | 14/16 | 13/16 | 54/64 |
| Learned width | 14/16 | 14/16 | 14/16 | 14/16 | 56/64 |
| Protected spine 192 | 15/16 | 13/16 | 14/16 | 14/16 | 56/64 |

Against sampled depth, the spine has two paired wins, no losses, and 62 ties. Against learned width, it has four wins, four losses, and 56 ties, so it adds no total hits over ordinary width. It preserves the known deep path on `stress-n20-e42e9acd2e86c9b6da84ef95`: sampled depth and the protected spine both reach the solution at transition 182 for salt 0, while learned width does not. The small gain over sampled depth does not justify a width-over-width claim.

Run roots and manifest SHA-256:

- Salt 0: `run-v66-v15-qual-seed0-spine192-v01`, `8a45d50a715c87909b74af30913051b650b9e8a8f7bce20879d5513ae22858dc`.
- Salt 1: `run-v67-v15-qual-seed1-spine192-v01`, `e753971e7a28c6a24f156618aebfd212f538c05e6404ea864ff63179420bd735`.
- Salt 2: `run-v68-v15-qual-seed2-spine192-v01`, `d4b09afc14055dd643c0429e20777bfad234c2d137b7c09e08cd7a745209d2f6`.
- Salt 3: `run-v69-v15-qual-seed3-spine192-v01`, `54f20520d4802835514e1f6ede7673a4e410dd3501a8a10519ec87ba4bf60b5f`.

V15 executable SHA-256: `ac09210f9eb057396702e7694f1d507fa675b692adc12ab6f11e85339719e704`. Source hashes: scheduler `c7e7430e699d2b6c3c8679c3f55bd61bffec596a4aba6920f4acdb5ead43ba10`, scheduler support `f800e790b6ff72c1af942c9fe512968bfa9fabf52fdc0d30a512501bc7a1b0e7`, replay `f5285c4dd6167e75fa95e2da53fa79e363dfc6e9f25dad056181ffec64d4c918`, pilot `5591bafc7d33377003f7b21abcffb4a02a7b4b5f21e54401e927e321c15084af`, and search tests `d15cf0b6c94c58a13694375fa1dc5fd698e0b0df1cd3743236f17c99b491643d`. Release tests (29), warning-denied all-target Clippy, formatting, and the release pilot build passed. Stage 0 source and run bytes remain untouched.

## Protected-spine length sweep, V16

V16 adds root-delayed spine lengths 128, 160, and 224 around the existing 192 control. Each delayed trajectory starts from the initial assignment with its own seeded RNG stream; particle 0 is frozen after the configured spine budget. Four seeds were run on the same 16 qualification tasks for sampled depth, learned width, and all four spine lengths. All 384 traces replayed, all reached exactly 256 expansions, and the common terminal selector again gave `R=S` for every row. The four seed jobs ran concurrently, so retain active/wall values as descriptive and do not use them to rank runtime.

| Condition | Salt 0 | Salt 1 | Salt 2 | Salt 3 | Total | Mean active ms/task |
|---|---:|---:|---:|---:|---:|---:|
| Sampled depth | 14/16 | 13/16 | 14/16 | 13/16 | 54/64 | 33.85 |
| Learned width | 14/16 | 14/16 | 14/16 | 14/16 | 56/64 | 35.43 |
| Spine 128 | 14/16 | 14/16 | 13/16 | 14/16 | 55/64 | 34.13 |
| Spine 160 | 14/16 | 15/16 | 13/16 | 14/16 | 56/64 | 34.73 |
| Spine 192 | 15/16 | 13/16 | 14/16 | 14/16 | 56/64 | 34.64 |
| Spine 224 | 14/16 | 13/16 | 14/16 | 13/16 | 54/64 | 33.07 |

No tested root-delayed spine budget beats learned width in total hits. Budgets 160 and 192 tie it at 56/64; 128 reaches 55/64, and 224 falls to 54/64. Spine 192 beats sampled depth by two paired task-seed cases and has no sampled-depth-only hit, but it still only ties learned width overall. Treat the time values cautiously because the four seed processes competed for CPU; a follow-up should first alter branch state, not keep searching spine lengths on this saturated roster.

V16 outputs are `run-v70-v16-qual-seed0-spine-sweep-v01` (`a5b80b3e70783eed2c80b0d38e8e09dca5771381fa5b13991c91a258dc769f03`), `run-v71-v16-qual-seed1-spine-sweep-v01` (`0df9b187fbcfd769b212199c088416cab4fe7eacc67e59ab04fc6ebedb7e15e0`), `run-v72-v16-qual-seed2-spine-sweep-v01` (`78791270023fed5d732e301835aec8785723140593ffa484ac3c080490f50060`), and `run-v73-v16-qual-seed3-spine-sweep-v01` (`a18b0de2431c75b5c9c873b14d7ebc113cc3dd9e203bf6751855d2650086684e`). V16 pilot source SHA-256: `bba2031d7ece3b01c9ece1e176c0aabe4904e500989c389878e76eb98ebf265c`; executable SHA-256: `07ccf4628ce8cbb48ba8e08dae83af28ef2af442a74ca673e80ace885919d27e`. The exact task, support, and sensor receipts match V14/V15 input hashes. Release tests (29), warning-denied all-target Clippy, formatting, and release build passed.

Next engineering repair: test a fork-at-spine-boundary policy that copies particle 0's assignment and latent state into particles 1–7 at the boundary, then gives those descendants independent seeded proposal streams for the remaining budget. This distinguishes branching from the initial basin from branching around a deep state. Keep root-delayed policies as controls and preserve their results above.

## Fork-at-spine-boundary pilot, V17

V17 added `ForkFromSpineThenWidth { spine_budget: 192 }`. At expansion 193, particles 1–7 inherit particle 0's assignment, latent state, depth, last-event pointer, and current value, while retaining their independent pre-seeded RNG streams. Each fork is a new ancestry; the initial-particle header remains the pre-fork seed snapshot. Particle 0 remains live but is not scheduled after the boundary. Forking adds no expansion or resampling event, and its copy cost is charged inside the scheduler interval for expansion 193.

Four paired salts (0–3), all 16 qualification tasks, and 256 expansions per task compared sampled depth, learned width, root-delayed spine 192, and forked spine 192. The four jobs ran concurrently, so active and wall time are descriptive only. All 256 traces replayed, completed their full transition budgets, and had `R=S`.

| Condition | Salt 0 | Salt 1 | Salt 2 | Salt 3 | Total |
|---|---:|---:|---:|---:|---:|
| Sampled depth | 14/16 | 13/16 | 14/16 | 13/16 | 54/64 |
| Learned width | 14/16 | 14/16 | 14/16 | 14/16 | 56/64 |
| Root spine 192 | 15/16 | 13/16 | 14/16 | 14/16 | 56/64 |
| Fork spine 192 | 15/16 | 13/16 | 14/16 | 13/16 | 55/64 |

The fork preserves the known deep trajectory and has one paired win/no losses against sampled depth, but it does not beat learned width: four wins, five losses, and 55 ties. It is one hit below the root-delayed spine and adds no evidence that forking around this spine endpoint improves reachability on the current saturated roster. This closes the fork-192 tuning branch for this roster; the next push is harder topology, not another nearby spine schedule.

V17 outputs and manifest SHA-256: `run-v74-v17-qual-seed0-fork192-v01` (`43e51a1e8e99f488154b891a6654b77a1b5b17d498ef0e7551829cd6d01a9df0`), `run-v75-v17-qual-seed1-fork192-v01` (`27f01e34d6cc97ae7ab3cd8e93fd98754f1aad5747cac66904b9d621da14e08d`), `run-v76-v17-qual-seed2-fork192-v01` (`8d0293fed47b521c3655664f808a1c56af4591bfb681e86df0e9793d51a121ec`), and `run-v77-v17-qual-seed3-fork192-v01` (`dbe48ed251b0541fde5b898d6a41ed930f1eb24ac0b3a2c856e15fcc7a3b7efa`). V17 pilot executable SHA-256: `ef5cb66d1ecfef95d7e7a2345724edd42a2e2b1f5ff8705d9329e09b35f867d2`. Source hashes: scheduler `cfc72432d03bea980d3133641dec91a68b635ca70a136b33e79a24f9a17b2f52`, scheduler support `98efc427aae2d4cfb5edde5e7096c9017dcc9b30e84d324068ea3970ddaebf87`, replay `f5285c4dd6167e75fa95e2da53fa79e363dfc6e9f25dad056181ffec64d4c918`, pilot `9bf36431a68ac2aa4c3c40c35446cb9cd2a37c83b041a98027bafa048fdb83ca`, and tests `f2e239dadd6c38c624105865f9743eaf47fff1b6a16dc4a38df73f3653e6e597`.

## Fork lineage and depth contract hardening, V18

A read-only implementation audit found that the fork trace needed stronger lineage assertions. The Stage1 fork now derives child ancestry IDs using a domain-separated SHA-256 input and guards uniqueness against every pre-fork ancestry and sibling. The configuration validator also rejects fork schedules whose maximum round-robin branch depth would exceed `u32`. The manifest's allocation semantics now explicitly state that forked particles copy assignment, latent state, depth, and event pointer, receive new ancestry, reset allocation age, retain their own RNG stream, and leave `initial_particles` as the pre-fork snapshot.

The fork test now checks unique child ancestry distinct from the spine, stable ancestry across later events, per-branch parent-event continuity, latent-state continuity, zero resampling, and rejection at or beyond the `u32` depth limit, in addition to the 192-event SampledDepth prefix, copied state, independent RNG streams, full-width schedule, and replay. One initial focused compile caught a test-field typo (`latent` vs `latent_state`); it was corrected. Strict Clippy then caught two fixed-size temporary vectors, replaced with arrays.

Verification: all 30 Stage1 search-crate release tests passed; all-target release Clippy with `-D warnings` and `cargo fmt` passed; the optimized pilot binary built successfully. This is source/test/manifest hardening only: it made no new LFM calls and produced no new search run. Drive G: is unavailable, so the release target remains on D:. V18 scheduler SHA-256: `19b0fab6ea06d952288ed8f5059321b5bc865fe7464c882b9f5c35a626ce8b76`; support `2ea5cb41ad243cb2d70e9c857820b7591fb477e2ec33644cf919e7db2ba977f5`; pilot `4b5a0dd48fae3a5c73011a4e1957175c09c90434c06f774cb6703cc138ab5037`; tests `a9713e1f240d0fc7f93e26ad07c9e7d1305512cbf3423791ef400c3f7cddbe94`; executable `e80f6db32c43fb97205e0ebbd49b5da06531f263780b123979fa43b1d15eceed`. The next pilot uses schema `FAS_R1_STAGE1_ENGINEERING_PILOT_V18`.

## Next engineering push: exact bridge-motif worlds

The current sampled-density generator is not a controlled local-barrier family: its profile names are adaptive search starting points, not observed density strata. The next generator keeps `r1_world::Task`, `Clause::Different`, exact `enumerate_solutions`, independent validation, public rendering, and role-anonymous class filtering. It uses four internally rigid 3-color modules (triangle anchors plus leaves adjacent to two anchors), paired with two planted-compatible bridge edges per module pair. Each pair admits three relative color permutations, so two independent pairs yield exactly nine role-anonymous classes. Entity and clause order are deterministically permuted; construction metadata and exact labels stay private. A read-only adapter audit found that current Stage1 preparation rejects `N>20` and V_reach is fixed to 20 assignment slots, even when a no-value arm is selected. Therefore the first v04 roster is limited to N=20 (four modules with two leaves each), so the already frozen machine can be exercised end-to-end. Larger N requires a versioned adapter/V_reach widening and is deferred. This is a new Stage1 stress roster, not a change to Stage0 or prior V17 observations.

## V04 model-contact qualification and arm readout

Stage 0 remains untouched. V04 is a new 96-world N=20 stress roster with 64 train, 16 validation, and 16 qualification worlds. The exact solver reports 54 raw and 9 role-anonymous solution classes for each world. The generator is isolated under `stress-worlds-v04`; four release tests, format check, and strict all-target Clippy passed. The source receipt binds 14 source files, including read-only Stage 0 world sources. Corrected bundle `run-v75-stress-worlds-v04-v02` hashes: public tasks `4b257f4e484b268a14454a2392923f1b6d87f545d698191478c8c4e1396f6104`, private tasks `57705fa8c73281ffdd91e5b742f34fcdbdb443dc168cfc98ef1d7c029ab66ce8`, diagnostics `f224d656a81fba856b631f1456d164e5800927fd99c5125827b3e61ea94b5a2a`, support manifest `f2984a29897abff1271223ee3b570d9f5497b3a0ea4a66e3b669838bb6197c5c`, and generation receipt `e05a65b58e5e6f327b80e32d9611eab74a526d48a9d0d6df3db9bf3ba12d4786`. The original v01 bundle is preserved; v02 fixes the source-lineage receipt gap.

The pinned LFM extraction is `run-v78-v04-sensor-v01`: 96 tasks, 3,456 constraints, longest encoded input 907 tokens, hidden size 2,048, RTX 3080/CUDA BF16. The repeat extraction matched exactly and the pinned snapshot hashes stayed stable. Feature artifacts: `constraint_H.float32.npy` SHA-256 `0907856ce3f4b46cc7cfbba3fa3c4b17255ff31f0870ac78842e39c4e8e2635c`; `global_h.float32.npy` SHA-256 `0feacf761d25e70d78dd5014c04e22f484e714d19e2f60d01d5ba8445777c90d`; `rows.jsonl` SHA-256 `eb8d3aa906a82606bc8ba62a0ae772e20298176d040e18f4e9cd4c6ad28df378`; extraction receipt SHA-256 `5b513325fdc2b7ed5a17d0456df5d37f4599d69c8c3bf78a143327660699b28c`. The one-task smoke run `run-v79-v04-qual-smoke-v01` completed before the full runs.

Four all-arm V04 qualification runs used `incidence_masked_norm_4`, V_reach v06, transition budget 256, replay enabled, all 15 conditions, and the same 16 qualification tasks at salts 0-3. All 960 arm/task/salt traces completed 256 transitions and replayed successfully; all rows had R=S. Per-run manifest SHA-256: `run-v80-v04-qual-allarms-seed0-v01` `a5adbed23d481f88b4609e31c3d5c3599e202348f5664770e4842beb64f13e97`; `run-v81-v04-qual-allarms-seed1-v01` `388a86f86087029a2126b29a85cdbf5b7c952705e9264e25a48ae6c2e2e95f0d`; `run-v82-v04-qual-allarms-seed2-v01` `04bacfa0c97f4284e936e055e4843f39c88321df677e58623d2c5ce128c50331`; `run-v83-v04-qual-allarms-seed3-v01` `f013e3ddc077bec5ba651be12b23d18f2a2cf8eeebf636cd1f0fba63e7226729`.

| Condition | Salt 0 | Salt 1 | Salt 2 | Salt 3 | Total / 64 |
|---|---:|---:|---:|---:|---:|
| Depth | 4/16 | 3/16 | 6/16 | 7/16 | 20 |
| Sampled depth | 12/16 | 13/16 | 13/16 | 14/16 | 52 |
| Random width | 0/16 | 0/16 | 0/16 | 0/16 | 0 |
| Learned width | 14/16 | 13/16 | 13/16 | 13/16 | 53 |
| Learned spine 128 | 12/16 | 11/16 | 11/16 | 14/16 | 48 |
| Learned spine 160 | 13/16 | 12/16 | 11/16 | 14/16 | 50 |
| Learned spine 192 | 12/16 | 11/16 | 10/16 | 14/16 | 47 |
| Learned spine 224 | 12/16 | 13/16 | 11/16 | 14/16 | 50 |
| Learned fork 192 | 12/16 | 11/16 | 12/16 | 14/16 | 49 |
| Assignment merge | 4/16 | 4/16 | 6/16 | 5/16 | 19 |
| Strict dynamic merge | 14/16 | 13/16 | 13/16 | 13/16 | 53 |
| Canonical merge | 4/16 | 4/16 | 6/16 | 5/16 | 19 |
| Particle | 3/16 | 3/16 | 2/16 | 5/16 | 13 |
| Particle strict dynamic | 11/16 | 11/16 | 11/16 | 10/16 | 43 |
| Particle no merge | 11/16 | 11/16 | 11/16 | 10/16 | 43 |

Paired posthoc hit-set readback confirms strict dynamic merge is identical to learned width (53/64); assignment merge and canonical merge are identical (19/64); particle strict dynamic and particle no-merge are identical (43/64). The common terminal selector is not the observed bottleneck (`R=S` throughout). Learned width decisively outperforms deterministic depth on this roster, but its one-hit margin over sampled depth is small (53 vs 52; paired record is 7 wins, 6 losses, 51 ties). Random width reaches zero hits, showing that raw branching alone is not enough. Assignment/canonical merge prune useful paths when latent states differ; strict full-state identity produces no merges and adds overhead. Particle allocation without merge falls from 53 to 43 hits at roughly twice learned-width active time; merging does not explain the particle loss. These are adaptive engineering observations on a single qualification roster, not independent confirmation.

Reachability by expansion prefix, pooled across 64 task/salt cases, at B={0,32,64,128,256}: depth `{0,20,20,20,20}`, sampled depth `{0,22,32,43,52}`, random width `{0,0,0,0,0}`, learned width `{0,0,2,32,53}`, assignment/canonical merge `{0,5,10,15,19}`, strict dynamic merge `{0,0,2,32,53}`, particle `{0,5,10,12,13}`, particle strict/no-merge `{0,2,6,31,43}`. Mean per-task active/wall time in milliseconds: depth `18.97/24.50`; sampled `25.50/31.14`; random width `25.81/31.90`; learned width `34.64/40.49`; spine 128 `32.85/38.67`; spine 160 `31.27/37.10`; spine 192 `29.14/34.84`; spine 224 `27.73/33.51`; fork 192 `26.54/32.61`; assignment merge `58.08/65.55`; strict dynamic merge `69.71/75.95`; canonical merge `57.37/64.33`; particle `57.24/64.30`; particle strict dynamic `67.06/73.45`; particle no-merge `68.37/75.03`. The jobs ran sequentially; timings are descriptive and include policy overhead.

Next engineering push: add an isolated v04-specific class-balanced proposal trainer. The existing frozen v02 pipeline rejects the v04 64/16/16 roster and binds older sensor/adapter/Q receipts. Train on v04 train worlds, use validation only for engineering selection, and keep qualification labels out of all training rows. Version the new path instead of relaxing old hash pins. After the proposal is frozen, adapt the stress V_reach request/refit flow to v04 and keep its targets limited to train/validation trajectories. Do not retune merging or particle allocation until the proposal-specific change has a direct comparison.

### V04 interpretation caveat: the sensor action signal is confounded

A follow-up structural review found that every V04 clause is `Different`, i.e. the world is a planted role-anonymous 3-coloring graph. Given the public pairwise entity incidence and current assignment, immediate constraint-count delta for any single-entity edit is exactly computable without H. Therefore V04 is a valid reachability/proposal stress family, but action-relevance success on it cannot establish that the LFM contributes the action signal. After freezing the V04 proposal, run a paired qualification diagnostic with an identical-policy `NO_H_ACTION` mask (retain learned base logits, remove the LFM-derived action-semantic term); compare proposal ranking against exact ΔC and replayed R/S under identical tasks, salts, seeds, and budgets. Treat this as an engineering ablation because qualification was already opened. A symbolic oracle-ΔC arm can be added as a separate privileged ceiling, not as semantic evidence.

## V04 class-balanced proposal fit

The isolated V04 proposal trainer completed using only 64 train and 16 validation worlds; the private train/validation sidecar contains exactly 80 rows and is bound to the full V04 private-source digest. The 16 qualification rows were omitted, no qualification targets or labels were generated, and the fitter reports qualification features/metrics were not used. The teacher generated 2,560 states (2,048 train, 512 validation), 40 legal edits per state, and zero zero-mass states. `proposal-weights-v04.json` SHA-256: `3ce84b1e4f44f7713c80999223d5638b8ada0eeffea00a06f787de9dc0616f33`; receipt: `run-v84-v04-proposal-v01\proposal-fit-receipt-v04-v01.json`. Private sidecar SHA-256: `1ffabf3f78b9dc823950a0d7ae492fd57230c8b963f6b841da172bd15f4bfc66`; it binds full source private SHA `57705fa8c73281ffdd91e5b742f34fcdbdb443dc168cfc98ef1d7c029ab66ce8` and records 16 qualification rows omitted.

At epoch 30 the proposal reached validation cross-entropy 3.62991 and teacher mass under the predicted top edit 4.54%. Uniform choice over 40 legal edits yields 2.50% expected teacher mass. This is a modest but real fit signal, not yet evidence of an effective trajectory policy. The next read is the matched V04 rollout/V_reach comparison, followed by policy diagnosis if the proposal does not translate into useful reachability. The V04 generator's all-`Different` grammar remains action-signal-confounded: public incidence plus assignment suffices to compute one-edit constraint delta, so this fit cannot be used to claim that the LFM supplies that signal.

## V04 V_reach fit

After freezing the V04 proposal, the train/validation-only V_reach request set was built from exactly 80 tasks and 2,560 starts (16 uniform + 16 solution-neighborhood per task); the request receipt explicitly records no qualification private rows or targets. The Rust labeler then generated 21,120 materialized states and 84,480 rollout outcomes at the frozen 256-step horizon using proposal SHA `3ce84b1e4f44f7713c80999223d5638b8ada0eeffea00a06f787de9dc0616f33`. The request receipt's `rollout_request_start_states=25,600` is the combinatorial upper-slot count; 4,480 trace/budget combinations had no remaining trajectory horizon and were correctly omitted by the labeler. Labels SHA-256: `218d90e6a52810b9a6f6a4360231f7f98461fac5362512be3092e06a4577f48b`.

The fresh V04 V_reach-v07 fit selected epoch 70 using train/validation only. Validation ROC AUC against fractional rollout targets is 0.768, Brier 0.00185, and BCE 0.0354; positive target rate is 0.639%, so accuracy alone is not informative. The unscaled inherited v02 baseline is saturated and has near-chance ranking (AUC 0.50), while group-scaled but unrefit baseline is still poorly calibrated (AUC 0.529). New V_reach SHA-256: `aa11fca9bea2556600974da1c68cd15fe1a32a30e88ade8e69691c8287910170`; receipt SHA-256: `31cd1f1246c7199105695138786935de63f7c1e1754f7a42d8b1e460c8b98686`, under `run-v89-v04-vreach-fit-v01`. This gives us a plausible first reachability estimate to test in scheduling, not a planner result by itself.

## V04 proposal concentration diagnosis, V98-V109

The V04 learned-width collapse was isolated to the fitted proposal head rather than the V07 scheduler executable. Under the same `54939d1ac481496c94093fc274935b16ca8fa19630fd592f93a37878fad829b6` executable, the earlier proposal checkpoint `45960e4c62129998164ce6eaa20531ce8ea171bae962a979253b404d55f03ce0` reproduced its prior core-arm totals: Depth 20/64, SampledDepth 52/64, RandomWidth 0/64, LearnedWidth 53/64. Its four manifests are V101 `e074c215a2972603f93988eb447384853a78134b10d4d708db9c95043c46cfbb`, V102 `4bb98d78349c812aae7ecb081c038a8df018d6fd4697b6897731892bcc89ebfd`, V103 `33fa7dcad148b27daafa9f446463968ee9aeb21438acf6ea0e4080406214fc67`, and V104 `6069dc6c59deac5c336b0ce360b0853f8780d4991b692a8a98000bd48b2bd911`. This removes the earlier executable mismatch as an explanation for the V04 fit's zero learned-width hits.

The V04 head at `pinned_raw_v02` was run across all 15 arms, four salts, 16 qualification tasks, and 256 transitions. All 960 traces replayed and completed their budgets; only Depth reached valid states (24/64), while sampled/width/merge/particle arms reached 0/64. The run manifests are V98 seed 0 `a16381b473b8e7cb0390903cb6b7479c27cf31cc62c1ee211cc3be1c2c8e02c0`, V98 seed 1 `6affb02f26e5495728eb76dd12db12428877b28034b2f14f20e868c4e6cc10f5`, V99 seed 2 `3e7f8316b162d8ba4dcc8f7c11ab38416283b122f4bd8c0224e2fd98138e8f55`, and V100 seed 3 `2df6e5e8a0f00f7210c36d70e52066ea1a6c515a37e17c6f2f5b7ebfcf253962`.

The V04 normalized head's mean base-logit spread was about 5.598 times smaller than the recovered old head. V105 tests a copy-only weight-scaling diagnostic; transformed artifact SHA-256 is `3ef32dbff65fdf7cb2346c6bc63e17c4ee8bc8e3c0ec552b2901878eb4d91e58`, and its scale receipt SHA-256 is `27ef3f8791dcaf8e29897a2d134bd90fb9fa6f34afc751a2c11b13093c0b577b`. The helper and its tests are `proposal/v04/scale_norm4_logits_v01.py` (`dbd40621eb647b8458daad64ae3c2d9bf6bb49f4e448b446b62362f4dbac34a6`) and `test_scale_norm4_logits_v01.py` (`e326426113b62a98f2ae29018c0479ef8ca433f0618b89df0bd7c52869fd7c40`); its three unit tests passed. Four subsequent scaled-head core runs produced SampledDepth 55/64 and LearnedWidth 58/64, with Depth 18/64 and RandomWidth 0/64. The scaled `f32` weights shifted some near-tied Greedy choices, so this was retained as a diagnostic and replaced by a sampler-side scale.

## V19 learned-sampling temperature control

V19 adds `--learned-sample-temperature T`, default 1.0. It applies `logit/T` only inside the LearnedSample categorical sampler. Greedy consumes the original logits unchanged; UniformSample still uses the same bounded RNG. The T=1 path preserves the prior f32 subtraction and f64 accumulation bit-for-bit. Other temperatures use max-centered f64 differences before division, which remains stable for the smallest positive f64. Temperature is recorded in the pilot manifest; the per-arm manifest stores an effective temperature only on learned-sampling arms. A non-default learned-sampling temperature is included in trace identity, and replay checks it. Greedy and Uniform trace IDs remain independent of the requested temperature.

Verification used `G:\cargo-targets\fas-r1-stage1-temperature-v19`: formatting passed, all 45 Stage1 release tests passed, all-target release Clippy passed with warnings denied, and the optimized pilot built. The V19 pilot executable SHA-256 is `32b0dec0562f5c985d06fe30098ae877151e03d33e5de891b6a8b0e4c0b243a1`. Source SHA-256: policy `52db0a5a2da3619d1552fcf4bdebf438911772174e1b9c1ed937a056eb26c2b7`; scheduler `c0f51b829f1102d6dcebd4f62925039f23d8bb92caee3fd48d9e568895c401b8`; scheduler support `51fa906568b338741126f1bc03fba369b9dda3218e8807661d9cab627ab733f5`; replay `b44afc520bab12c8ad47fe2c92e22cdb013a255fc053bc2f625da52ca457b232`; pilot `c5dc35a441d3299ef3828487e86f4a9f1d1ae9ecf0d3f6ef9aa2fd80d7dd95d2`; search tests `9b4b9284fe4ede90712747eaf87c8aea35b8a49d9c36c04d999cef393325211a`.

The V19 core comparison kept the original proposal bytes (`3ce84b1e4f44f7713c80999223d5638b8ada0eeffea00a06f787de9dc0616f33`), `incidence_masked_norm_4`, the same V04 qualification tasks, selector, 256 budget, and salts 0-3. Only temperature changed between paired runs. Each run contains 64 traces; every trace replayed. At T=1 versus T=0.17864354564164298, pooled reachability at B={32,64,128,256} was:

| Arm | T=1 | T=0.17864 |
|---|---:|---:|
| Depth | 18, 18, 18, 18 | 18, 18, 18, 18 |
| SampledDepth | 0, 0, 0, 1 | 31, 41, 48, 55 |
| RandomWidth | 0, 0, 0, 0 | 0, 0, 0, 0 |
| LearnedWidth | 0, 0, 0, 0 | 0, 3, 41, 58 |

At B=256, lowering temperature gave SampledDepth 54 paired wins, 0 losses, and 10 ties; LearnedWidth had 58 wins, 0 losses, and 6 ties. Depth and RandomWidth were unchanged on all 64 pairs. `R=S` on every row. The eight core manifest SHA-256 values are V110 `1ec2a45f2b67ea994b0bfe7ac38ac8e1342b5d936d420c27d001aae7ec113f4e`, V111 `1a3bcb364818292a37039ccfdbbcdf435f58fdcf5889fe7d0c99f9e7cce84fce`, V112 `988eb845123cb8dbd1ce321e16ca3b673f090d2018a9bfb0bbd8a08874319455`, V113 `7ca4d2762b57002ad15cffa3bf9820be88f6e1c94522985af4cbdaff1b2671758`, V114 `f1a0f6040510951a51eb5eea35a37804a69b50902ec03a7a5508fa371f4acda`, V115 `18dd9908163d149c08f11a6d4eb24c4f6f441620aeb37bfd9e83ef1dc258948e`, V116 `8836bd3f18ea31f3ded1a909ee26c28146704bae5e53a45a18dafb989b34eb2c`, and V117 `ecda065d89baedaca11535110e422b6893581ef5451d2a9e0d04a09724c03046`.

The `base_only_v03` lesion was run at both temperatures on the same paired roster, four salts, and four core arms. All 512 traces replayed. It reached 0/64 under every arm at both temperatures. Thus temperature alone did not rescue this base-only policy on V04; the full V04 proposal adapter is needed for the observed hits on this family. Because all V04 constraints are `Different` and public incidence already determines exact one-edit constraint deltas, this remains an engineering ablation and does not establish that LFM content supplies the action signal. The eight lesion manifest hashes are V118 `81cb58db9f47425bcc92e732a1e5942609afdd2b63ecff291308f37e82beb9ba`, V119 `f0e69ae083b4a65c02664d55530f17a189a0568cd4c40074a88292390a730b2b`, V120 `3e09fc399b00fa5981958b9bc842d2d6a3dbb61e515c661b5ef1eef49ec6491f`, V121 `c2a536a21ead0c35636cbd73845d62b3c5a0fc640881c62fe7b09decd07531e0`, V122 `3d7cab5e82662ebb9fe030823648c85096b63826abc85385da4484d39cbbb20d`, V123 `c73e84d3ce0a317c26162795bb87956925f17038f27c1f79b9c93247e364923f`, V124 `3aa3c4f5384a82a4fd5b17d73ec08eaa6e4e62040a2be75405f63e0675e3af6`, and V125 `4aba697b0639a7a84981d49aaba9119f084aaaa4bb31ae4e206ef02ba0fb9a35`.

## V19 temperature pass across all search arms

With the calibrated sampler temperature, all 15 arms were run for four salts on the same 16 tasks, 256 transitions, V04 proposal, and V04 V_reach-v07 checkpoint. All 960 traces completed and replayed; `R=S` throughout. The four all-arm manifest hashes are V126 `8ac4ca7568ba30396940867269e028e2d10ea4c20ea7521d24fdf2d7b599548a`, V127 `20086985db2d7854c0b719b27e567c241f0ecf3429335c67d2152db8c3d51189`, V128 `76c5598fb22951278d291ff591c21be7922f96514a51c09232ee6d3dc30bc18b`, and V129 `489384152aa5918b4a0ed3f8961d80f8d3b8ac73d70b39444042e2e68220bb2f`. Every Particle trace made 264 V_reach calls. V_reach-v07 was trained using the T=1 proposal; Particle numbers here are therefore off-policy engineering diagnostics.

| Arm | T=1 B=256 | T=0.17864 B=256 | Paired wins / losses / ties |
|---|---:|---:|---:|
| Depth | 18/64 | 18/64 | 0 / 0 / 64 |
| SampledDepth | 1/64 | 55/64 | 54 / 0 / 10 |
| RandomWidth | 0/64 | 0/64 | 0 / 0 / 64 |
| LearnedWidth | 0/64 | 58/64 | 58 / 0 / 6 |
| Learned spine 128 | 0/64 | 57/64 | 57 / 0 / 7 |
| Learned spine 160 | 0/64 | 55/64 | 55 / 0 / 9 |
| Learned spine 192 | 0/64 | 53/64 | 53 / 0 / 11 |
| Learned spine 224 | 0/64 | 53/64 | 53 / 0 / 11 |
| Learned fork 192 | 0/64 | 53/64 | 53 / 0 / 11 |
| Assignment merge | 0/64 | 31/64 | 31 / 0 / 33 |
| Strict dynamic merge | 0/64 | 58/64 | 58 / 0 / 6 |
| Canonical merge | 0/64 | 31/64 | 31 / 0 / 33 |
| Particle | 0/64 | 17/64 | 17 / 0 / 47 |
| Particle strict dynamic | 0/64 | 51/64 | 51 / 0 / 13 |
| Particle no merge | 0/64 | 51/64 | 51 / 0 / 13 |

The width-depth contrast is now interpretable: calibrated SampledDepth reaches 55/64 while LearnedWidth reaches 58/64, with 5 width wins, 2 losses, and 57 ties. The much larger improvement over deterministic Depth mostly comes from learning a useful stochastic proposal distribution, not from width alone. Canonical/assignment merging reaches only 31/64 versus 58/64 for LearnedWidth. Strict dynamic merge matches LearnedWidth but spends about twice its active time on these runs. Particle no-merge and strict-dynamic reach 51/64; canonical Particle reaches 17/64, but all Particle comparisons need a V_reach refit under the new proposal temperature before interpreting allocation quality. Mean active/wall milliseconds per task at the new temperature were: Depth 17.13/21.94, SampledDepth 21.58/26.47, RandomWidth 21.04/25.85, LearnedWidth 28.22/33.05, assignment merge 57.31/63.19, strict dynamic merge 62.19/67.34, canonical merge 56.41/62.13, Particle 54.73/60.70, Particle strict dynamic 60.02/65.32, and Particle no-merge 60.48/65.92. Timing remains descriptive for this engineering sweep.

Next: calibrate/refit proposal and V_reach on the existing train/validation artifacts using exact Rust runtime scores at the selected temperature; keep qualification labels out of fitting. Then rerun Particle against a matching continuation policy and move the surviving search schedules onto a harder world roster. Preserve V98-V129 as adaptive engineering history; the qualification partition has already been opened and none of these results is independent confirmation.


## V132 low-temperature matched V_reach and all-arm rerun (V145–V152)

This is adaptive engineering on the qualification partition, which was previously opened. It is not an independent confirmation. Stage 0 remains untouched. The purpose was to repair the V140–V143 T=0.980906 collapse before judging particle allocation: reuse the already useful V19 engineering temperature, regenerate train/validation V_reach labels under the exact current V132 proposal policy, refit V_reach, and replay all 15 arms over the same four salts.

V145 regenerated 21,120 states and 84,480 rollouts with V132 proposal SHA 748ceb3d527408b06b7cb46b101c73e2609a7c13e7fd78dcde589fb9914c93d4, T=0.17864354564164298 (f64 bits 3c0f16adcaddc63f), and composite policy identity 275eb28082db27f7b82e81ce1a1b5aadd2217d39e70199ef4b35519329b61523. Labels SHA-256: d7fde1432764dbfc19b8417dd0b2eb28e7fa4de2eb73ef4652a6c2b298a8b434. Trajectories SHA-256: 9c13b8a56383f08f464023500bb1fb5dde202b7c38d43a9c1131bb94acce32f8. The simulator receipt records no qualification access.

V146 independently replayed the same requests, frozen V132 weights, and temperature. Both label and full trajectory hashes match V145 exactly; the policy identity also matches. The comparison receipt is run-v146-v132-t017864-v03-replay-v01/v03-replay-comparison-v01.json.

The temperature override is explicitly versioned as an adaptive engineering choice because its prior and paired evidence comes from already-open qualification runs. It binds the exact V132 proposal SHA, the f64 temperature bits, and the paired salt-0 V140/V144 manifest digests; it also records V19 temperature lineage. Override SHA-256: 913697200a2dd47452114503131e95abf68c6b7e98521384c3dc15ae9a283c14. The refit validator has 17 focused passing tests; calibration-only validation remains unchanged.

V147 refit V_reach from train/validation labels only: 16,896 train rows and 4,224 validation rows, no qualification features or targets. The checkpoint embeds policy identity 275eb28082db27f7b82e81ce1a1b5aadd2217d39e70199ef4b35519329b61523. Best epoch 12; validation AUC 0.7331, BCE 0.6194, Brier 0.1302, positive target rate 0.5258, mean forecast 0.5236. Weights SHA-256: 55cd68133b9cd9ee7ae336ac5dcf79f453437a8cfe1e854f1048cd8099dc8e42. Receipt SHA-256: 3a8b32b5ee61e8cf13de5a0688c4d96467adf0ea3112e84ae090a693b6edc017. Within validation source strata, AUC was 0.635 on proposal-trace rows, 0.707 on solution-neighborhood rows, and 0.784 on uniform-start rows. These are more informative diagnostics than accuracy; the fit is usable for an engineering allocation trial, not a claim of a strong value model.

V148–V151 ran all 15 conditions at N=20, budget 256, width 8, same 16 qualification tasks, and salts 0–3, using the V132 proposal at T=0.17864354564164298 and the matching V147 V_reach checkpoint. All 960 traces completed 256 expansions and replayed. No arms were skipped. The independent V152 audit verified 3,840 referenced trace/posthoc/selector/prefix file hashes, identical task-condition roster across salts and the paired V140–V143 batch, and common proposal/sensor/support/executable identity. Manifest SHA-256 values: V148 15f2e9a5a66101c54e0732de7afc856f9880a44992b57e739fa39f3116134da9; V149 2f5a40178394263d1f876ffc2db8663f20604ec7847edd9db61bae425f7bd912; V150 8c676e85a02800d09b4458605d45b62ca3d461a8672182ddb7ffb81f1d4a5a81; V151 f841c2ece4224e2770722c7816229dfe6c4f40912aea36c7a267b8ba1b11edae.

At B=256, pooled over the 64 task/salt cases per condition, reachability and selected-valid counts were identical (R=S):

| Condition | R / S |
|---|---:|
| Depth | 14 / 64 |
| SampledDepth | 58 / 64 |
| RandomWidth | 0 / 64 |
| LearnedWidth | 43 / 64 |
| Learned spine 128 | 50 / 64 |
| Learned spine 160 | 50 / 64 |
| Learned spine 192 | 50 / 64 |
| Learned spine 224 | 53 / 64 |
| Learned fork 192 | 52 / 64 |
| Assignment merge | 19 / 64 |
| Strict dynamic merge | 43 / 64 |
| Canonical merge | 19 / 64 |
| Particle | 8 / 64 |
| Particle strict dynamic | 46 / 64 |
| Particle no merge | 46 / 64 |

The low-temperature rerun paired against V140–V143 leaves deterministic Depth unchanged at 14/64 and RandomWidth at 0/64, while SampledDepth improves from 0/64 to 58/64 and LearnedWidth from 0/64 to 43/64. For the four arms where only temperature changed at fixed V132 proposal and the arm does not consume V_reach, this isolates the major high-temperature collapse. Width still does not beat sampled depth: SampledDepth reaches 58/64 versus LearnedWidth 43/64. Protected-spine schedules recover part of the gap (50–53/64) but remain below SampledDepth.

The matching V_reach fit does not make the default particle schedule competitive. Particle no-merge and strict-dynamic merge both reach 46/64, a small +3 over LearnedWidth, while spending more inference work; assignment/canonical merging falls to 19/64, and default Particle falls to 8/64. Strict dynamic merge matches LearnedWidth exactly, indicating no useful full-state merge events. R=S throughout, so terminal selection is not the observed bottleneck. At the 50 ms active-time prefix, SampledDepth reaches 58/64, LearnedWidth 43/64, protected spine 224 53/64, Particle no-merge 40/64, and assignment merge 18/64. At 50 ms wall time the counts are 58, 43, 53, 39, and **17** respectively. Full operation/active/wall prefix curves and hash receipts are in run-v152-v132-v07-lowtemp-pilot-audit-v01/pilot-batch-audit-v01.json.

Current diagnosis at V152: temperature repair restored stochastic reachability, but this V132 proposal/width combination is weaker than the earlier V19 V84 result (LearnedWidth 58/64 at low temperature). The current learned width also trails a single sampled trajectory. Value-guided particle scheduling adds only a small reachability increment without merge, and the assignment-equality merge remains destructive even though V_reach is temperature-matched. The subsequent scheduler and proposal ablations are recorded below. Preserve all artifacts and treat all observed scores as engineering diagnostics.

## Particle refresh and proposal ablations (V153–V164)

These are adaptive engineering diagnostics on the previously opened qualification partition. Stage 0 remains untouched, all runs use the same N=20/256-step qualification roster and frozen Stage1 identities, and no result below is scientific confirmation.

V153–V156 compared Particle's existing cached-greedy schedule against resample-boundary refresh with round-robin allocation between refreshes. V157–V160 refreshed V_reach at every expansion. All three particle conditions (canonical Particle, strict-dynamic Particle, and no-merge Particle) were replayed over four salts. The independent audit verified all 576 trace rows, 2,304 referenced sidecar hashes, equal paired rosters, and R=S at all audited prefixes.

For canonical Particle, cached-greedy reached 8/64; either resample-boundary or every-expansion refresh reached 30/64 (paired +23/-1/40 against baseline). Their final reachability matched, while resample-boundary used 45,442 value calls versus 140,167 for every-expansion refresh. In strict-dynamic and no-merge controls, cached-greedy reached 46/64, resample-boundary reached 39/64 (+7/-14/43), and every-expansion reached 41/64 (+10/-15/39); the refresh policies used 43,079 and 142,488 calls respectively. Thus more frequent value refresh is not a reliable improvement, costs about 3.3x as many calls, and remains below the cached no-merge baseline. At the 50 ms active prefix, canonical Particle reached 10 cases under resample-boundary and 9 under every-expansion; strict-dynamic reached 22 and 7, respectively; no-merge reached 23 and 7. Audit: run-v152-v132-v07-lowtemp-pilot-audit-v01/targeted-scheduler-audit-v01.json.

V161–V164 then isolated proposal checkpoint choice without consuming V_reach: V84 and V132 used the same current pilot executable, same four salts and qualification tasks, and T=0.17864354564164298. The paired audit verified 576 V84 traces and 2,304 sidecar hashes and matched the V148–V151 V132 roster. The V84 SHA is 3ce84b1e4f44f7713c80999223d5638b8ada0eeffea00a06f787de9dc0616f33; the V132 SHA is 748ceb3d527408b06b7cb46b101c73e2609a7c13e7fd78dcde589fb9914c93d4. At B=256, deterministic Depth was 18 versus 14, SampledDepth 55 versus 58, LearnedWidth 58 versus 43, spine widths 128/160/192/224 were 57/55/53/53 versus 50/50/50/53, and fork-192 was 53 versus 52 (V84 versus V132). For LearnedWidth the paired result was 17 V84 wins, 2 V132 wins, and 45 ties. For SampledDepth it was 6 V84 wins, 9 V132 wins, and 49 ties. The proposal effect depends on search topology: V84 is materially stronger for LearnedWidth but not for the single sampled trajectory at the full expansion budget. R=S for selected conditions. Audit: run-v152-v132-v07-lowtemp-pilot-audit-v01/proposal-ablation-v01.json.

Updated diagnosis: (1) proposal quality and topology interact; the current V132 artifact should not be treated as a universal replacement for V84, (2) Particle allocation behavior is schedule-sensitive but remains behind strong non-particle controls, and (3) assignment-equivalence merging still discards useful dynamic continuation state. Next, produce a train/validation-only V_reach fit matched to V84 at the same low temperature, if the existing request/refit contracts can bind it without weakening their lineage checks; then compare V84-matched Particle/no-merge and merge variants against V84 LearnedWidth and SampledDepth. If the current V03 label/refit path is hard-bound to V132, add a separately versioned generalized path rather than bypassing its checks. After that, carry the best schedule onto a deliberately harder stress roster and inspect branch-survival/value calibration traces to target the remaining gap. 

## V84 direct low-temperature V_reach refit (V165–V172)

This continues adaptive engineering on the previously opened qualification partition. No Stage0 files were changed; qualification labels were not consumed during fitting. The V84 policy was bound to the exact V03 replay and runtime-temperature override artifacts rather than represented as a fabricated V01 runtime-proposal receipt.

V165 used a PowerShell numeric argument that rounded the intended temperature (`0.17864354564164298`) to `0.178643545641643`; its labeler completed 21,120 states and 84,480 rollouts but emitted different temperature bits. Preserve the run as an invalid precision attempt and do not use its labels. V166's replay attempt was interrupted and its partial output is retained. The corrected V167 run passed the exact temperature string and recorded f64 bits `3c0f16adcaddc63f`; V168 independently replayed it. Both runs produced identical V84 policy identity `3525d5f1c5d09a9a6e0e5dd2e19b5bfbb8694ee904d94aff186670071c6d10ee`, label SHA `cecc7c4a0c5a9d99f935c0da0f8923c1a268af6025ed7e7727e243071eefdeea`, trajectory SHA `a35bb65e1bd27c8c6557836268855cf5458440b5dd15ff3e324ffc9d19638b86`, and 80 tasks / 21,120 states / 84,480 rollouts. Replay comparison V169 binds both receipts and exact hashes (SHA `2f834140ab471df555113bd3fccaf5c95eff935670c3ee83efc71e49d42a7574`). V170 binds V84 weights, exact temperature bits, and the engineering selection lineage from V110–V117 (SHA `04861bd6054b1bfd9d430941f9b089af5a6084f3dc5fc10b4a59472d33b4889e`). These artifacts explicitly remain scientifically ineligible.

A versioned direct-V84 refitter and 10 focused tests were added at `proposal/v04/refit_vreach_v84_runtime_v01.py` and `proposal/v04/test_refit_vreach_v84_runtime_v01.py`; all 10 tests passed and both V169/V170 validated. V171 is a retained first fit whose receipt reveals the shared helper uses `CLI seed + 1`; it was invoked with 20260928 and therefore trained with 20260929. V172 corrected the CLI seed to 20260927 so the actual recorded optimizer seed matches V147's 20260928, retaining CPU, AdamW, learning rate 0.001, weight decay 0.0001, 100-epoch cap, and patience 10. V172 selected epoch 2; validation fractional-target AUC 0.6244, BCE 0.6419, Brier 0.1701, ECE 0.0667, positive rate 0.6358. This is weaker ranking than V147's V132-matched value fit (AUC 0.7331), so treat V172 as a usable but weak engineering checkpoint. V172 weights SHA `a439b77ccf601e9a591b9b982adb9c8a5f99d787309a44c98856b700c7a72ab6`; receipt SHA `e441bd37f63705589e99a3590c7c0a57b26e32b1959939ea9763d0587ea11c8a`. V171's different-seed weights and receipt remain preserved (SHA `c009fb07c7263ac4272e9160ffc0a0e7893c354fe137df0a4377bd907d16dc28` and `9796cdd4ffa30379c2f8994224d1ad790565c83df47bc558f138f21bf04f977f`).

## V84-matched V_reach all-arm replay (V173–V176)

The 15-arm V84/V172 batch used the same N=20 qualification roster, salts 0–3, 256 expansions, V84 proposal at T=`0.17864354564164298`, and frozen V172 value checkpoint. All 960/960 rows replayed with 256 expansions; 3,840 referenced trace/posthoc/selector/prefix sidecars were hash-verified, and all four salts shared the same 16-task roster as V161–V164. The proposal, identity, sensor, support, and executable hashes remained fixed; the manifest hashes are V173 `00b988c768883115da349403eea51c64c9219111cac8823f53a4ca7cb4b2c5d0`, V174 `0ae85c3a9ef4084785dcc4dbb0750858f2aa239a10bdbe0f4f5814921eb2cbbd`, V175 `38481ccf518d4420aceffc90472ded49eaebde1db4e02ab95c467913701d6f87`, and V176 `154b4ef28117925ad42d49878504cd88547de83936f692090e0e899b158ba644`.

At B=256, V84 proposal-only conditions exactly retained their V161–V164 per-task outcomes: Depth 18/64, SampledDepth 55/64, RandomWidth 0/64, LearnedWidth 58/64, learned spines 128/160/192/224 at 57/55/53/53, and fork-192 at 53/64. This is expected because those arms do not call V_reach. Value-consuming outcomes under V84/V172 were: assignment merge 38/64, strict-dynamic merge 58/64, canonical merge 38/64, Particle 26/64, Particle strict-dynamic 39/64, and Particle no-merge 39/64. R=S for every arm.

Against the same-roster V132/V147 package in V148–V151, V84/V172 gives SampledDepth 55 vs 58 (paired +6/-9/49 ties), LearnedWidth 58 vs 43 (+17/-2/45), spine-224 53 vs 53 (+9/-9/46), assignment/canonical merge 38 vs 19 (+25/-6/33), strict-dynamic merge 58 vs 43 (+17/-2/45), Particle 26 vs 8 (+23/-5/36), and Particle no-merge/strict-dynamic 39 vs 46 (+14/-21/29). This contrast changes both proposal and value checkpoint, so it is an engineering package comparison; it does not isolate V_reach quality. It does show the strongest current gap is scheduler cost: at the 50 ms active prefix SampledDepth reaches 55, LearnedWidth 58, while Particle reaches 26 and no-merge 37; corresponding mean active/wall time per task is 25.83/31.76 ms, 35.22/41.34 ms, 58.59/66.03 ms, and 61.95/68.57 ms.

## V84/V172 particle refresh cadence (V185–V192)

To isolate scheduler policy, cached-score V173–V176 traces were compared with `--particle-resample-only` (resample-boundary refresh, V185–V188) and `--refresh-vreach` (every-expansion refresh, V189–V192), restricted to Particle, no-merge Particle, and strict-dynamic Particle. All 576 new rows replayed at 256 expansions and 2,304 referenced sidecars hash-verified. Each schedule used the same 16 qualification tasks over salts 0–3 and identical V84/V172 hashes. Manifest hashes: V185 `7522022f5cd938eb666363c0ebdd1164fe50bbb0b76f545d4fbd9abda7aa1b28`, V186 `0790b4811b200fd533e09f352a93531fc8b3df48b36b3fcb2e7180bba8fe1ffa`, V187 `1b811afef053142065dff4b052ac90796511a4171a37947fe2d279072330d6f4`, V188 `381cd60cfaefc655c1a333ad3e2b5ba3f872e4a381bfdde0b28c81311c0c19d3`, V189 `b20391337b3a3aedf6523a600f831413e12e1c0b24adb98c267ff4503e4e80e2`, V190 `9b006f1eb76cb267d03b12169939c5a62edec3aa94a50e22361a539a2f8c94d1`, V191 `dd0260bee217d755360f40cff76fed7644b760ec50ee21a31384977b084eaa17`, and V192 `46c9e2bb4082353ee19365fbc32d56cf2fac91704f1ea5435312677c4bbcac2a`.

Cached / boundary / every-expansion B=256 reachability was 26/44/35 for canonical Particle (+22/-4/38 paired wins/losses/ties versus cached), 39/51/39 for no-merge (+15/-3/46; every-expansion +5/-5/54), and 39/51/39 for strict-dynamic (same paired outcomes as no-merge). R=S throughout. Value calls were 16,896 / 38,657 / 120,632 for canonical Particle; 16,896 / 30,784 / 131,584 for each no-merge control. Mean active/wall ms were 58.59/66.03, 101.03/107.30, 266.68/273.95 for canonical; 61.95/68.57, 85.79/91.26, 294.48/301.35 for no-merge. Resample-boundary refresh is the current reachability winner among Particle schedules; per-expansion refresh spends roughly 3–4x the boundary value calls and returns fewer hits. It remains slower than the strong non-particle baselines and does not close the selection gap. Strict-dynamic identity still matches no-merge, with no useful full-state merges.

Updated engineering diagnosis: V84/V172's value-guided resampling can improve Particle reachability when refreshed at resampling boundaries, but its compute overhead is substantial. Assignment/canonical merging still discards useful continuation state; strict-dynamic merge still does no useful deduplication. Next, tune the boundary cadence (periods around the current 8-step interval) on Particle and no-merge, then examine merge-event/ancestry traces to decide whether any state-aware merge can preserve useful continuation. Carry the strongest schedule to a deliberately harder world roster after this local scheduler sweep. These are adaptive engineering observations on the already-open qualification partition, not independent confirmation.

The resampling interval sweep (V193–V224) compared periods 4, 8, 16, 24, 32, 40, 48, 56 and 64 over the same 64 task×salt cases, using Particle and Particle no-merge with V84/V172 and boundary-only refresh. All rows replayed at B=256, used the same qualification roster and value hash, and the period-4/16/24/32/48/64 runs plus period-8 references had their trace/posthoc/selector/prefix hashes verified; the period-40/56 runs were independently hash-checked in the same pass.

No-merge Particle final R/S by period was 46/64, 51/64, 57/64, 56/64, 56/64, 58/64, 57/64, **60/64**, and 56/64, respectively. Mean active/wall ms were 124.9/133.0, 85.8/91.3, 75.9/81.9, 72.0/77.8, 68.4/73.9, 94.5/103.8, 70.2/76.4, 72.5/79.3, and 72.6/79.3. Value-call counts fell monotonically from 45,120 at period 4 through 30,784/23,616/21,376/20,032/19,584/19,136/18,688 to 18,240 at period 64. Period 56 was the reachability leader; paired against period 8 it was +11/-2/51 wins/losses/ties, against period 16 +4/-1/59, against period 32 +4/-0/60, against period 40 +3/-1/60, against period 48 +3/-0/61, and against period 64 +5/-1/58. At the 50 ms active/wall prefixes period 56 reached 48/48, below period 16's 54/53, but it reached 60/60 by 100 ms while period 16 reached 57/57. The data favor a broad high-cadence-cost plateau rather than a sharp period-16 optimum; period 56 is the current full-budget reachability choice, while period 16 is faster at the 50 ms prefix.

Canonical Particle remained consistently behind its no-merge partner at every interval: its R/S counts across periods 4/8/16/24/32/40/48/56/64 were 42/44/46/41/45/44/43/43/42. At period 56 it used 29,632 value calls and 87.3/94.8 ms active/wall for 43/64, versus 18,688 calls and 72.5/79.3 ms for no-merge at 60/64. Thus reducing merge frequency through a longer resampling interval does not rescue assignment merging; the next merger work should use the recorded representative latent divergence and ancestry to design a state-aware eligibility rule, rather than further cadence-only tuning.

Against the V84/V172 proposal-only baselines on this same roster, period-56 no-merge reached 60/64 versus SampledDepth 55/64 (paired +8/-3/53) and LearnedWidth 58/64 (+4/-2/58). At both 50 ms active and wall prefixes it reached 48/64 versus 55 and 58; at 100 ms it reached 60 versus 55 and 58. Its full-run mean active time (72.5 ms) was about 2.1× LearnedWidth (35.2 ms) and 2.8× SampledDepth (25.8 ms). The best particle setting has now edged out both proposal-only baselines at the fixed 256-transition budget and 100 ms wall budget, but not at 50 ms, and the selected schedule came from a wide sweep on opened qualification data. It is a candidate to carry to the harder synthetic roster, not a result to promote.

## Merge trace diagnosis and accounting repair target (V185–V224 readback)

A read-only trace audit extended the assignment-merge diagnosis through the period-56 runs. In V221–V224, canonical assignment merging fired 12,037 times across 16,384 recorded events (73.5%); 5,112 losing-merge records show nonzero latent divergence and 5,099 show depth differences. Period-56 canonical Particle reached 43/64 versus 60/64 for its no-merge partner (paired 1 particle-only, 18 no-merge-only). At actual resampling boundaries, excluding final-budget events, merge rates were 71.0% for period 8 (1,409/1,984), 74.5% for period 16 (715/960), and 85.9% for period 56 (220/256). Strict-dynamic merge continues to match no-merge exactly and records no merges.

The current trace accounting needs a versioned repair before interpreting individual merge events: when a candidate wins `apply_merge`, the displaced representative is not marked `retired_by_merge`, so `nominal_slot_redirected` misses some merge-caused redirects. The `value_allocation_non_nominal` flag counts any `particle_id != nominal_slot_particle_id`, including ordinary no-merge scheduler choices; it is not a value-only reallocation measure. In addition, retained-representative ancestry/latent fields conceal the displaced state for candidate-wins; 1,591 period-8 and 1,425 period-16 events report the current event as representative with zero latent distance. These counters are diagnostic defects, not evidence that the scheduler performed no redirect.

Engineering direction: version trace accounting to preserve the pre-merge loser, identify every merge-retired particle, and distinguish scheduler slot mapping from value-caused reallocation. Keep assignment-equality merging as the deliberately aggressive, lossy baseline; test state-aware merge eligibility against no-merge rather than treating assignment identity as sufficient continuation-state equivalence. Source locations from the audit: `search/scheduler.rs` around merge application, slot selection, and trace emission; `search/support.rs` around merge accounting.

## V05 paired stress fixture and first sensor handoff (V225–V226)

The V05 generator now emits a balanced paired 2×2 roster: base/dense constraint graphs crossed with independent random starts / explicitly exposed witness-derived two-conflict swap-trap starts. Twenty-four underlying seeds produce four task variants each; all variants from a seed remain in one split. The `InferenceTask` schema is unchanged, and the separate `public-search-starts-v05.jsonl` sidecar is declared as search input and excluded from sensor extraction. The swap-trap cell is an engineered warm-start diagnostic, not no-leakage generalization. Stage 0 and V04 were not modified.

The generator crate passed `cargo fmt --check`, release tests (1 unit + 8 integration tests), strict release Clippy, and release build using `G:\cargo-targets\fas-r1-stage1-stress-worlds-v05`. V225 generated all 96 worlds in 253 ms, with 154 ms total and 17 ms maximum exact-solver time. It preserved 54 raw solutions, 9 role-anonymous classes, and six role automorphisms per world. Artifact hashes: public tasks `6722d98d1e390387c4ba1f9804ebe5d00104c137d9359590ce777af2eb1a8118`; search starts `f2bd7a6c73f9bbfad562819560a45d6da176f9ee26d11c4202526d58d2e040dc`; support manifest `fd5938f9e2c67af01e4d103325f02d1e72a76122edc764dd23c82c488959da65`; generation receipt `6f4458e16238129722e988b5986b759079c484e6d3746029970f894db996d809`.

The first V226 sensor handoff failed closed before importing the model stack or performing inference. The generic extractor requires `split_counts` to have exactly `train`, `validation`, and `qualification` keys (or its legacy `_families` form); V05 placed an extra `paired_worlds` count inside that object. Preserve V225 and V226, and repair this through a new V05.1 support/receipt identity with paired-world count stored separately. No sensor features or model outputs were produced by V226.

## V05.1 model handoff, start-state integration, and four-salt pilot (V227–V235)

V227 repaired the support schema under a new V05.1 identity. It regenerated the same 96 public tasks and search-start sidecar as V225; support SHA-256 is `b1ae31c762cfbd34662d7ac54f3557c144948137fa34f1e7fe06e08acc755624`, generation-receipt SHA-256 `5f1a30b6c42d0c82806ac89cefa2c9ad4074b1b179c92bfb95edc89f3aaa3d3d`. V228 then completed frozen LFM extraction for all 96 tasks / 3,936 constraints on the RTX 3080. Exact repeat-forward verification passed; constraint H, global h, and row outputs hash to `f0d4bd632c19e384c034f4165a4e77e940a582e7b93fa34981e82c84dce477f5`, `b6deacaed23e1ad03cd0655242dd8373d0e0fd6cf50097a22b53a44ef9ed89b6`, and `d2f5d949ff6a23c948091870bb1f6254da43d7fd5245505c6eac9ea70b09fab6`; V228 receipt SHA-256 is `be79afad2303f096a08972a98e3ab3b7bad755f3b9892398f2bb8d2c088a9a88`. No probe, proposal, selector, or V_reach fitting occurred in the extraction run.

The Stage1 runner now consumes the separately declared public start sidecar, validates its complete task roster and assignment hashes, and sets that assignment as the initial state for every arm. The V229 integration smoke ran nine arms for one qualification task at 16 expansions; all nine replayed, each trace's initial assignment matched the sidecar, and merge-v2 diagnostics round-tripped. Pilot schema advanced to V20. The pilot integration changes and sidecar-loader tests are confined to Stage1; Stage0 remains untouched. Release tests, strict Clippy, and the G:-target release build passed. V229 manifest SHA-256: `f076db49b3155f52fe5e936e9bf6cdfe44ca3e688c7d3d599b67cf9013ccce5c`.

V230, V232, V233, and V234 then ran all 15 arms on the 16 qualification tasks at N=20 and B=256, with action RNG salts 0–3. All 960 task/arm/salt traces completed 256 expansions, replayed successfully, and used the identical V05.1 public roster, sensor arrays, explicit initial assignments, V84 proposal SHA `3ce84b1e4f44f7713c80999223d5638b8ada0eeffea00a06f787de9dc0616f33`, and matched V172 V_reach SHA `a439b77ccf601e9a591b9b982adb9c8a5f99d787309a44c98856b700c7a72ab6`. No arm was skipped. Pilot manifest hashes: V230 `07e8e61b89b30180a680cc24164953ebdfec564722e69a4e89a328c8ed82bb96`; V232 `d7e60ac477373cf414f030d1445d50dde5eadbc6ae8ee13ebff00b166fc0157f`; V233 `855f2a5fda8e003fb10b14e8fdba840b5967aec6120a55344fbf04a430a8d77e`; V234 `276ae6c4089c50c8dc3f25aee4c37c9140531ced201d3a158e59afe3619b73c3`. Pilot executable SHA-256: `7b93507838cc696dcef2f3b89eeeda66dbc918480e9e05ee3d831efc758aae32`.

The V235 audit verified trace/posthoc alignment, complete budgets, replay status, and exact sidecar initial states while reading all 960 trajectories. At B=256, oracle reachability and selected-valid outcomes were identical in all 15 conditions (zero selector loss in these 64 task×salt cases):

| Condition | Reach / selected |
|---|---:|
| Depth | 32 / 64 |
| SampledDepth | 34 / 64 |
| RandomWidth | 0 / 64 |
| LearnedWidth | 42 / 64 |
| Learned spine 128 / 160 / 192 / 224 | 39 / 39 / 37 / 37 of 64 |
| Learned fork 192 | 34 / 64 |
| Assignment merge | 34 / 64 |
| Strict-dynamic merge | 42 / 64 |
| Canonical merge | 33 / 64 |
| Particle | 35 / 64 |
| Particle strict-dynamic / no-merge | 35 / 64 |

On the paired task/salt cases, LearnedWidth beat SampledDepth on 8, tied on 56, and lost on none; it beat Depth on 10, tied on 54, and lost on none. This is a useful engineering signal that learned width contributes beyond stochastic depth on this V05 family, while naive random width fails badly. It is not an independent scientific confirmation: qualification was deliberately opened and the proposal/value artifacts were transferred from V04. Mean measured active time was 36.45 ms for LearnedWidth, 31.08 ms for SampledDepth, and 24.94 ms for Depth. At the nearest common prefix to 50 ms, 38.13 ms active, reach was 0.656 / 0.531 / 0.500 for LearnedWidth / SampledDepth / Depth. The common terminal selector chose a valid assignment whenever any arm had reached one in this batch.

The V05 strata show the clearest width gains on dense tasks: LearnedWidth reached 0.75 on dense/random-start and 0.81 on dense/swap-trap cases, versus Depth at 0.50 in both; it also reached more distinct valid classes on dense/random-start cases (2.81 mean versus SampledDepth's 1.31). V_reach-guided Particle did not yet pay for its overhead: Particle no-merge reached 35/64, seven fewer cases than LearnedWidth and one more than SampledDepth, while averaging 71.31 ms active. Canonical Particle reached 35/64 as well; canonical assignment merging reduced its paired reachability by two cases overall and merged 13,641 of 16,384 expansion events. The canonical-merge arm had 13,951 merges, raw-assignment merge had 13,940, and strict full-dynamic duplicates remained zero. Strict-dynamic merge matched LearnedWidth's reach but roughly doubled its active time because the expensive identity-check path found no duplicates.

The retained analysis is `run-v235-v05-four-salt-analysis-v01/engineering-summary-v01.json` (SHA-256 `e7280e8553d8ebda221ae8342b4bd8de7bd58a29f3fe0698f189a116234e01f9`); the analysis script records its own source hash. Current engineering direction: keep LearnedWidth as the V05 planner reference, then transfer the already useful V04 period-56 boundary-refresh/no-merge schedule to V05 as a targeted diagnostic. In parallel, make a V05 train/validation-only action-relevance and proposal path; do not treat V04 proposal transfer as a V05-trained planner. Use per-task paired traces to inspect why canonical merge loses and why learned width finds more solution classes. Keep the full failed and successful run directories immutable.

## V05 period-56 resample-boundary follow-up (V236–V240)

V236–V239 transferred the period-56 resample-boundary refresh schedule to six V05 arms on the same 16 qualification tasks, four action salts, V84 proposal, V172 V_reach, B=256, width 8, and explicit V05.1 start sidecar. All 384 task/arm/salt traces completed the budget, replayed, and matched the sidecar initial state. The V240 aggregation is `run-v240-v05-p56-refresh-analysis-v01/engineering-summary-v01.json` (SHA-256 `a04df4a058ce02d95c5a1595b9833125094adee4c6de11b8961a455fb42df17e`); its four pilot-manifest hashes are `c4e945712ef9c840ba4df125c04aafe478a373e646ff3f9b3e6267a17d46c0cf`, `7459291039bb1537cdfcba578abf947d014946214ca0c53e46591c1c40248658`, `785cd26504ad4ce4b7bc31b95cd7684bec77cb6a05fbd39bf9fa10c1009f7cd0`, and `45cb0d6005fe892b5f53d958a90fc30d56126b8ec3dbdede140a998b3d2ac940` for salts 0–3.

At 256 expansions, LearnedWidth remained 42/64, SampledDepth 34/64, and canonical merge 33/64. Period-56 Particle reached 37/64; period-56 Particle no-merge and strict-dynamic each reached 41/64. Paired against the prior period-8 V05 runs on the same task/salt cases, period-56 no-merge gained six hits with no losses (6 wins, 58 ties, 0 losses), while Particle gained two (5 wins, 56 ties, 3 losses). No-merge remained one case below LearnedWidth, with 0 wins, 63 ties, and 1 loss. Period-56 Particle lost to no-merge on reach in five paired cases and won one; it also reached 0.375 fewer valid classes per case on average. Strict-dynamic matched no-merge on all 64 cases, again with zero full dynamic duplicates. Thus the refresh cadence repairs much of the earlier particle deficit, while assignment merging still costs reachability and particle control still does not exceed LearnedWidth.

Mean active CPU time was 30.49 ms for LearnedWidth, 25.60 ms for SampledDepth, 88.39 ms for Particle, 67.87 ms for Particle no-merge, 68.43 ms for strict-dynamic Particle, and 59.51 ms for canonical merge. Across the four salts, period-56 particle arms made 30,681 V_reach calls for Particle and 18,688 each for no-merge and strict-dynamic; even the no-merge arm still performed canonicalization and duplicate detection. The run therefore identifies a promising allocation schedule, not an efficiency win: no-merge's reach is close to LearnedWidth at over twice the active cost. Preserve period 56 as a useful engineering schedule candidate and continue reducing value/canonicalization overhead before treating it as a practical planner.

The V05 trainer audit also found the existing Stage1 sensor probe fitter is not a proposal/value trainer and opens/hashes its qualification label files before filtering. Do not route V05 through that fitter. V05.1 currently has a paired-group 64/16/16 support roster and frozen features, but no V05 action/proposal labels. The next model-contact implementation is a separately versioned train/validation-only teacher and fit path that consumes only train/validation targets, checks all four variants of each paired world stay in one split, and never includes a qualification-target path or hash. The V04 proposal machinery may supply reusable implementation routines, but its pinned V04 bundle contract must remain unchanged.

## V05 action-proposal diagnostics and common Q-terminal selector (V247–V264)

This is adaptive engineering on the already-open V05 qualification family. It does not independently confirm the planner comparison, and V02 selector inference was applied offline to closed trajectories rather than inside the earlier runs. No Stage0 source was changed.

V247’s action-relevance probe reached 0.3344 validation accuracy and 0.3308 macro-F1 across 5,120 rows, close to the three-class chance region. V248’s class-balanced one-step reachability teacher gave proposal cross-entropy 3.68385 versus uniform 3.68888 over 40 actions; V249 regressed to 3.68838 and V250 to 3.68958. The original action/proposal façade is not reliably extracting useful edit direction. These results motivate diagnosis of the feature/teacher interface, not planner comparisons using this proposal as if it were qualified.

The initial common selector V254 was chance-level (validation balanced accuracy 0.5, ROC AUC 0.528). The V02 repair provides per-clause predictions conditioned on public incidence and assignment, then aggregates them as a conjunction. V255 created 5,120 balanced candidate records with clause targets whose conjunction matches the independent validity label; public/private edge multisets matched across all 80 candidate-generation tasks. V258 fit only train/validation targets and pinned the trainer/model source. On its 1,024 synthesized validation assignments it reached terminal and clause ROC AUC / balanced accuracy 1.0, with 41,984 clause judgments. The fitted temperature hit the 0.05 floor, so the tiny calibrated BCE is saturation, not evidence of probability calibration or out-of-family selector quality.

V259 applied frozen V02 Q scores to 960 completed qualification traces from V230/V232/V233/V234, scoring 23,945 unique assignments in 104 forward batches (about 646 ms GPU active). V260 joined scores to the already-open post-hoc labels: all 15 arms had equal oracle reachability and V02-selected success (R=S) on these 960 traces. Counts were Depth 32/64, SampledDepth 34/64, RandomWidth 0/64, LearnedWidth 42/64, spines 128/160/192/224 at 39/39/37/37, fork-192 34/64, assignment merge 34/64, strict-dynamic merge 42/64, canonical merge 33/64, and Particle variants 35/64. This says the selector found a valid visited state whenever one existed in this finite readback; it does not turn the offline V02 rescoring into a cause of the trajectories or establish selector generalization.

Failure and repair history is retained: V251 candidate generation stopped on an input-shape mismatch; V257’s first trace-scoring attempt stopped at receipt validation because it expected `outputs` while V246 used `output_files`; V261 scored but Windows rejected long sidecar filenames after eight writes; V263’s first readback rejected exact logit parity. V261 partial sidecars and the source snapshot are retained and excluded from analysis. V262 reran the salt-0 240-trace slice with compact deterministic filenames and completed without the read-only mmap warning.

V264 compared V262 against V259. Calibrated probability arrays were bitwise identical; raw FP32 logits differed by at most 7.6294e-05 under different batch composition. Two of 240 global argmax indices changed at near-equal scores, but both traces were unreachable according to the existing V260 readback, so the selected-valid outcome was unchanged. The eight V261 partial sidecars matched V259 within the same 1e-4 logit tolerance and had no global argmax changes. This is bounded numerical drift, not exact score identity; preserve it as a selector determinism edge case if tie-sensitive outcomes appear on a reachable trace.

Current direction: keep V02 as a useful common selector for this opened roster while moving engineering effort back to the action proposal. Diagnose whether the near-chance action probe reflects missing relational features, teacher ambiguity/entropy, or a mismatch between the class-balanced one-step target and the planner’s actual transition need. Use train/validation-only, versioned ablations (symbolic public incidence versus frozen semantic features; proposal ranking versus teacher entropy and nearest-class distance), preserve qualification labels, then refit V_reach only after a proposal that beats uniform reliably. Do not attribute the V230–V234 arm curves to V02 Q scoring, since those trajectories predate the scorer and used their original runtime selector.

## V05 Q-terminal action delta and residual proposal follow-up (V265–V269)

This remains adaptive engineering on the already-open V05 family. V265 stopped before data loading on a sibling-module import error; its failed receipt is preserved. V266 corrected the import and evaluated the frozen clausewise Q-terminal on all 2,560 train/validation assignments and 102,400 legal edits. Predicted constraint-satisfaction delta recovered exact sign labels on both splits (validation sign accuracy and macro-F1 1.0; ΔC MAE 1.525e-5). The class-balanced teacher remained broader and differently ranked: validation teacher entropy 3.3423 nats / 40 actions, uniform CE 3.68888, Q-delta proposal CE 3.63889, mean top teacher mass 0.07036, and teacher mass at the Q-delta argmax 0.04867. Q-terminal delta is a useful local consequence sensor, not a direct surrogate for class-balanced reachability.

V267 failed at the receipt boundary before loading model inputs because the new fitter required `qualification_targets_generated` on V266, whose schema instead explicitly records `qualification_labels_read=false` and `qualification_target_paths_or_hashes_recorded=false`. The attempt is reconstructed in its failure receipt; no model data were loaded. The schema-aware correction was followed by V268, which completed artifact verification and state/action joins, wrote the 409,728-byte delta sidecar, then failed in the validation prediction loop because of an indentation error. Both failed run directories are retained.

V269 completed with the frozen Q-delta scorer as a direct skip plus a zero-initialized learned MLP residual. Against the same validation targets, the frozen skip achieved CE 3.63888860; every residual checkpoint was worse, so checkpoint selection retained epoch 0 (3.63888860; 10 residual epochs run). This is 0.05069 nats better than V250's 3.689575 validation CE, but Q-terminal itself was fit and selected on this same train/validation roster. Treat it as an adaptive fit result, not independent confirmation. The result supports retaining the Q-delta proposal for an engineering integration check and rejects the current residual correction on this roster. Two V04 feature-view unit tests pass; no qualification labels/targets were read, and Stage0 remains untouched.

## V05 Q-terminal delta feature-only ablation (V270)

V270 held the V250 proposal architecture, hidden size, optimizer, seed, teacher targets, and split fixed; its only model input change was appending the frozen V266 predicted ΔC scalar to each action row. The MLP reached validation teacher CE 3.641774 at epoch 21 (31 epochs run), improving by 0.047801 nats over V250's 3.689575 and 0.047106 nats over uniform. The direct Q-terminal ΔC policy remains slightly better at 3.638889. This clean ablation shows the action-conditioned Q signal is usable by the original proposal network, while the direct local-delta ranker still wins on this teacher objective. The fit remained train/validation-only and adaptive; no qualification labels/targets were read. Runtime search integration is still absent: the Rust runner has a generic SearchPolicy seam, but its current frozen proposal loader cannot read this Q-terminal model.

## V05 Q-terminal ΔC runtime and merge diagnosis (V271–V279)

This is adaptive engineering on the already-open V05 train/validation family. The Rust runtime scores the frozen V05 clausewise Q-terminal ΔC head and wraps only action scoring; latent updates, the common Q-terminal selector, and V_reach remain delegated to the frozen base policy. No qualification/test split or Stage0 source was read or changed.

V272 assembled 2,560 train/validation states and 102,400 legal edits for Python/Rust parity. V273 exported the frozen V258 checkpoint as a 2,273,284-byte f32le artifact: checkpoint SHA-256 `00e1654dbd335b9bd7622b8bb65b983a20335f81f226904cc2c808f934d4838c`, weights SHA-256 `e1ce1fe358052af666df05f5f93e5b9ee25770405032099cc4bfe79e40480e4a`, manifest SHA-256 `83ba94efd053c8f56b577c0847151ae1749b9bc2e3aca5da402fafad59b077c2`. V272 parity report `40757695AE123D30833A4AD6DA0AFC9C6F6E98C7D1A13BA6FB82384EFC5DF307` measured ΔC RMSE 1.37e-6 and max absolute error 6.92e-6; probability max absolute error was 5.84e-8. Stable top actions agreed on all 1,297 non-near-tie states; the 251 global top-action mismatches were all near ties. For states with Python |ΔC| > 1e-5, sign agreement was 100%. The parity supports the Rust scorer's numerical fidelity while identifying near-tie ranking as the relevant edge case.

V274's 20-trace validation smoke replayed exactly. The full temperature-1 sweeps V275/V276 completed 640 train and 160 validation traces at 256 expansions each. At temperature 1, deterministic Depth reached 39/64 train and 9/16 validation tasks, while sampled depth, learned width, random width, and the merged/particle conditions reached 0 in both splits. The learned distribution was effectively near-uniform over 40 edits, so stochastic proposal use without sharpening erased the action preference.

The sharpened T=0.1 sweeps V277/V278 completed 640 train and 224 validation traces; V278 replay passed 224/224. On training, Depth reached 39/64, RandomWidth 0/64, SampledDepth 62/64, LearnedWidth 63/64, Particle with canonical assignment merge 30/64, and Particle without merge 57/64. On validation, Depth reached 9/16; RandomWidth 0/16; SampledDepth, LearnedWidth, all three tested spines, Fork192, and strict-dynamic merged width each reached 16/16. Raw assignment merge and canonical merge each reached 8/16. Particle with canonical merge reached 6/16, versus 15/16 for Particle without merge and 16/16 for strict-dynamic Particle. Across every arm in these readbacks, selected success equaled oracle reachability (R=S); the common terminal selector did not lose a reached valid assignment.

On validation, LearnedWidth used mean active CPU time of about 599 ms and reached a mean 3.44 valid equivalence classes per task, versus Depth at about 562 ms and 0.56 classes. Particle without merge took about 856 ms and remained one hit below LearnedWidth. Particle with canonical assignment merge recorded 3,288 merges (205.5 per run) and retained 47.69 unique assignments per run versus 149 for Particle without merge. Separately, the `canonical_merge` width arm recorded 3,587 merges across 16 traces; 1,633 joined different latent vectors, 1,634 joined different depths (maximum gap 7), and none was a strict full-dynamic duplicate. Strict-dynamic merge therefore recorded no useful duplicates and matched its no-merge control. Assignment equality is not adequate continuation-state equivalence in this runtime: it retires search branches with different latent state, depth, or stochastic continuation and sharply reduces reachability. Keep the aggressive merge arms as diagnostics; next work should test a versioned state-aware eligibility rule against no-merge.

V279's engineering summary SHA-256 is `FBB64027036F400932820508BD15A514178CA101F080D46E667A641D86BAC860`. It verified referenced trace/posthoc/selector/prefix hashes, complete 256-expansion budgets, and exact replay for V275–V278. Run manifests: V274 `1B1BEEE40D0024C3FE72BC996086C37C5074BB7E2B0F94C23E502915E5B9432E`; V275 `6855603E0D9AE9754F94DA6ACB4799F75E295726F04BD1F1DDF607911A614411`; V276 `6A7883D604BD008F1C1B8A4A32489134BE326839F5310061397BD51DA0319C62`; V277 `3E46B8B19AADABFF3224616AD3BD9F699EC8E183F39637F61B4E4B398F8C2ADC`; V278 `8E83CA08E6C8655FC9F84034C860E99005DA8AFB05B09CB19C2721CA07469902`. The updated Rust source passes Clippy with warnings denied and all 66 all-target tests. These are adaptive results for the current synthetic family, not independent scientific confirmation.

V280 reran the complete QDelta Python/Rust parity bundle against the final source and release build: all 2,560 states and 102,400 actions completed within every parity threshold. The pilot release executable hash is `EDEB06C3C1F554E9FE6753CBA286971E0D5B01CEF02E6D54211A1D23129175D0`, identical to the executable recorded in the V278 run manifest. The parity runner executable hash is `dd6b31e515c3037c23ce0072b3527383521875ead3de77fae6e7538019ce6c64`; report SHA-256 is `6D2ED24CDBDA8F17EFE6644303FF16D6312AE5FAF29DB252E86E3779E83E996C`. The report and original runner output are retained under `run-v280-v05-qdelta-runtime-parity-rebuild-v01`.
