# AR-03A — held-out response-geometry diagnostic

Status: frozen diagnostic-only experiment. No runtime/controller change and no end-to-end optimizer comparison. All claims are engineering-only and synthetic-task bounded.

## Question and hypothesis

**AR-H47:** candidate-independent local gradient geometry predicts candidate-utility response geometry on held-out actions and states.

For state (s), candidate parameter program (a), and training example (x), the response is

```text
U[s,a,x] = loss_x(W_s) - loss_x(W_s + delta_a)
```

The proxy hypothesis uses each example's full per-example gradient (g_x(W_s)), without consulting candidate utilities, to form balanced example strata. The first-order audit separately tests

```text
U[s,a,x] ~= -g_x(W_s) dot delta_a
```

## Frozen protocol

- **Task and objective:** reuse the immutable AR-02A 12-cell anisotropic-Gaussian dataset (96 training examples; 48 validation examples). The runtime/diagnostic reads only the first 96 training examples. Validation is not read by state replay, features, partitioning, utility calculation, or panels.
- **Frozen state generator:** unchanged AR-02A-R1 P16/V48-random K2 trajectory; same deterministic initialization, proposal/verifier samplers, action vocabulary, bounds, pair scheduler, K2 selection and commit semantics. State checkpoints are post-commit 600, 2,400, and 4,200. Replayed parameter fingerprints and training losses are checked against the saved AR-02A-R2 reference for a prior seed before new-stream outputs are accepted.
- **New independent evidence streams:** six development seeds and six evaluation seeds, all disjoint from AR-02A/R1/R2/B/C/D seeds and from each other:

  | Split | Seeds |
  | --- | --- |
  | Development | `8a6d39c17f02b4e5`, `31f0c72ba845196d`, `e5b4087a61c39f20`, `7d29a6f304b1ce58`, `b0625e91d83f47ac`, `4c178bfa2d60e935` |
  | Evaluation | `96e104bd3c72a85f`, `205ad7c3918e64fb`, `d43c6a107e95b281`, `5e8f13a2c64970bd`, `a17c2d48f03695e2`, `3bc9704ea251d68f` |

- **Candidate universe:** at each state, build the same proposal-selected K2 top-2-by-top-2 compounds for every legal two-coordinate block. The odd singleton block is excluded from the primary action-generalization analysis because it has no within-block action split. A block is included only if all four shortlisted compounds are legal under the frozen bounds.
- **Prospective action split:** within each eligible block, split the four rank combinations into two development and two evaluation programs using a fixed hash of the canonical parameter-pair IDs. One side receives the diagonal and the other the off-diagonal; the orientation is frozen, identical across states, and independent of utility. Each side has one occurrence of each shortlisted singleton rank on each coordinate. All development response features use development-stream states and development programs only. Primary evaluation uses evaluation-stream states and evaluation programs only.
- **Balanced partition contract:** every partition has exactly 12 strata of 8 examples. Verifier panels select 4 examples without replacement from each stratum (48 total), and each selected example has equal objective weight.
- **Partition ladder:** eight deterministic hash-placebo partitions; one input-only ((x_0,x_1)) partition; one current-state partition using per-example loss, true-class logit margin, and predictive entropy; one current-state partition using the raw 123-dimensional per-example gradient; one development-response oracle partition; and one per-evaluation-state response oracle ceiling. Feature partitions use deterministic balanced k-means with exact 8-example capacities. The clustering implementation, initialization, iteration limit, standardization rule, and seeds are fixed in source before execution.
- **Oracle boundaries:** the development-response oracle clusters each example's response profile over development states × development programs, then remains frozen for evaluation. The per-evaluation-state response oracle clusters the held-out response matrix at that evaluation state and is a privileged diagnostic comparator, not a mathematically guaranteed global optimum. Neither oracle affects a model transition or runtime decision.
- **Panels:** 64 deterministic 4-per-stratum panels per method/state, paired by panel seed across partitions. Panel rows are nested measurements, not independent training replications. Evaluation-stream seeds are the primary replication units; the three checkpoints within a seed are dependent.

## Primary outputs

For held-out evaluation states × held-out programs, report:

1. Mean within-stratum utility variance.
2. Analytically predicted finite-population RMSE using

   ```text
   Var(U_hat) = sum_h W_h^2 * (1 - n_h/N_h) * S_h^2/n_h
   ```

   with (N_h=8), (n_h=4), and (W_h=1/12).
3. Observed verifier RMSE over paired panels.
4. Candidate sign error (excluding exact utilities within the frozen epsilon), cross-block opportunity regret, selected-program regret, and false authorization.
5. Taylor prediction RMSE, correlation, (R^2), and sign error on evaluation examples × evaluation programs.

The main effect-size summary is proxy headroom closed relative to the hash-placebo mean and the per-evaluation-state oracle. It is descriptive only; no arbitrary pass threshold is introduced. Results are reported by evaluation seed first, then pooled with seeds—not panels—as the replication unit.

## Frozen stop tree

- If the per-evaluation-state response oracle has no meaningful held-out-panel headroom over hash placebos, stop: this action/state distribution offers little response-partition opportunity at the tested budget.
- If the development-response oracle does not transfer to evaluation states × programs, stop the persistent-partition hypothesis; response geometry is too state/action-specific under this protocol.
- If the development oracle transfers but observable proxies fail, do not start a feature hunt. A later proposal would need to be explicitly state/action-conditioned.
- If the raw-gradient proxy consistently beats hash-placebo on held-out evaluation seeds/actions, report that bounded result and request review before any new-substrate replication.
- AR-03A does not authorize AR-03B, controller changes, or an end-to-end training comparison.

## Outputs and integrity

The release run writes only to its selected `artifacts/run-*` directory:

- `report.json`: frozen protocol identity, counts, integrity checks, and aggregate metrics.
- `states.csv`: stream role, checkpoint, training loss, fingerprint, candidate counts, and eligible block counts.
- `candidate-index.csv`: candidate metadata and action split, without validation data.
- `partitions.csv`: balanced assignments for all methods and evaluation states, plus the frozen development-response oracle assignment.
- `panels.csv` and `seed-summary.csv`: per-panel metrics and seed-first summaries.
- `taylor.csv`: first-order response audit by evaluation state.

The dataset is read from the existing AR-02A-R2 artifact and is not copied or modified. State replay parity tests are required before the diagnostic run. Build/test output is directed to `D:\adaptive-runtime-targets\ar-03a` (`:G` convention); source and scientific artifacts remain in this experiment directory.

## AR-03A result and disposition

Integrity checks passed before interpretation:

- Frozen dataset SHA-256: `a83d5dcce8bd8926cf1d548c58d4a9cbbef0ca97c72e1fd4331bc5d825a7a14a`.
- Release tests: **6 passed**, including exact checkpoint fingerprint/loss parity with the frozen AR-02A-R2 replay reference.
- Replay produced 36 snapshots (6 development and 6 evaluation streams × 3 checkpoints); the diagnostic used 18 held-out evaluation states.
- All 235 recorded partitions had exactly 12 strata of 8. All 2,164 state/block action splits had 2 development and 2 evaluation compounds, with balanced singleton-rank marginals.
- The run emitted 14,976 panel rows and all reported numeric panel metrics were finite. Validation examples were not read.

Held-out evaluation means (the independent stream seed is the replication unit; checkpoints and 64 panels are nested measurements):

| Partition method | Within-stratum utility variance | Predicted RMSE | Observed panel RMSE | Sign error | Cross-block regret | Selected-program regret | False authorization |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 8 hash placebos, averaged | 4.837e-5 | 6.506e-4 | 6.509e-4 | 26.93% | 5.684e-4 | 7.168e-4 | 15.84% |
| Input only | 3.481e-5 | 5.266e-4 | 5.310e-4 | 22.20% | 4.613e-4 | 5.653e-4 | 10.42% |
| Current-state loss/margin/entropy | 4.608e-5 | 6.141e-4 | 6.124e-4 | 25.29% | 5.516e-4 | 6.912e-4 | 15.19% |
| Full 123D per-example gradient | 2.261e-5 | 4.064e-4 | 4.041e-4 | 18.25% | 4.014e-4 | 4.774e-4 | 7.47% |
| Development-response oracle | 2.367e-5 | 4.176e-4 | 4.105e-4 | 18.51% | 3.845e-4 | 4.665e-4 | 7.99% |
| Per-evaluation-state response comparator | 2.206e-5 | 4.016e-4 | 4.053e-4 | 18.15% | 3.711e-4 | 4.343e-4 | 6.77% |

The full-gradient partition reduced within-stratum utility variance by **53.3%** and observed panel RMSE by **37.9%** versus the hash-placebo mean. It also lowered sign error, cross-block regret, selected-program regret, and false authorization. The gradient method beat the hash-placebo mean in the favorable direction on **all six evaluation seeds for each of those metrics**, not merely in the pooled mean. The development-response oracle also transferred to held-out states/actions: its observed RMSE was 4.105e-4 versus 6.509e-4 for placebos. Input-only features helped moderately; the three current-state scalar features were close to the placebo floor.

The exact finite-population variance prediction tracked observed panel RMSE closely across all six methods (method means differed by less than about 2%). The gradient method's predicted RMSE closed about **98%** of the gap between hash placebos and the per-state response comparator. Its observed panel RMSE was marginally below that comparator, but this finite-panel estimate is not evidence that the proxy exceeds a strict oracle bound; the comparator is privileged but not a global optimum guarantee.

The first-order response audit was strong on every held-out evaluation state: correlation 0.9945–0.9995, R² 0.9889–0.9989, and sign error at most 0.344%. This is consistent with the Taylor mechanism `u_a(x) ≈ -g_x·delta_a` explaining why gradient geometry groups similar candidate responses. It does not establish that linearization is the sole cause of the partition advantage.

**Disposition:** AR-H47 is supported descriptively on this Gaussian-cell task, frozen ReLU MLP, K2 proposal/action universe, and six held-out evidence-stream seeds. Candidate-independent local gradient geometry predicts held-out action response homogeneity and improves verifier estimation over arbitrary balanced partitions. The development-response oracle also transfers, while input-only geometry has a smaller but positive effect. The result is not a training-performance claim and does not establish portability beyond this substrate. The frozen gate is met to *request review* for one new-substrate replication; **AR-03B, controller changes, and end-to-end training comparison were not run or authorized here.**

**Strongest alternative/limit:** per-example gradients use the current training objective and are therefore a task-informed, state-conditioned feature—not a free, task-agnostic input partition. The evidence comes from six independent stream seeds on one fixed training set and initialization; three checkpoints and 64 panels per state do not increase the independent seed count. The action split generalizes only within the proposal-selected K2 top-2×top-2 compound universe.
