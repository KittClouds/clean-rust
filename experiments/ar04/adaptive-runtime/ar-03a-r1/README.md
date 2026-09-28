# AR-03A-R1 — Gradient-geometry portability replication

Status: one diagnostic-only new-substrate replication, prospectively specified. No proxy-controlled runtime decisions and no end-to-end training comparison. Engineering-only; no biological interpretation.

## Question

Does candidate-independent, current-state per-example gradient geometry predict candidate-utility response homogeneity on held-out evidence streams and held-out compound actions when the data live in eight dimensions and the class boundary depends on nonlinear coordinate interactions?

The one-factor action-scale sidecar evaluates the same frozen states and candidate universe at `alpha ∈ {0.5, 1, 2}`. It never changes training actions or selects the runtime verifier. Its purpose is to compare Taylor validity and gradient-partition advantage as action magnitude changes.

## Frozen substrate and runtime

- **Data:** one deterministic 96-example synthetic training set in `R^8`; no validation set is generated or read. Each clean latent vector has independent standard-normal coordinates. Observed coordinates are corrupted by independent normal noise with example-specific scale `sigma = 0.04 + 0.18 * sigmoid(0.7 * (z0*z1 + z2*z3 - z4*z5 + z6*z7))`. The three target scores are cyclic nonlinear combinations of coordinate products and sine terms:
  - `s0 = z0*z1 + 0.60*sin(z2) - 0.35*z4*z5 + 0.25*z6`
  - `s1 = z2*z3 + 0.60*sin(z4) - 0.35*z6*z7 + 0.25*z0`
  - `s2 = z4*z5 + 0.60*sin(z6) - 0.35*z0*z1 + 0.25*z2`

  The target is `argmax(s0,s1,s2)`. No latent coordinate, score, noise scale, or generating label margin is exposed to any proxy. This gives heteroskedastic observation noise and a non-spatial, interaction-defined boundary without a privileged example partition.
- **Dataset RNG seed:** `72d84f31a06cb59e` (fixed). The generated training rows are written as an immutable binary artifact before state replay; the artifact hash is recorded after generation.
- **Model:** fully connected `8-8-8-3` ReLU MLP (171 parameters), deterministic AR-02-style initialization `0.22*sin(i*1.3714) + 0.03*((i mod 5)-2)`, parameter bounds `[-2,2]`.
- **Action/runtime:** unchanged discrete action values `{0, ±0.005, ±0.01, ±0.02}`, singleton top-2 proposal, exact top-2×top-2 pair verification, deterministic rotating pair schedule, one pair program per commit; P16 proposal and independent V48 verification batches, four commits per evidence draw. Training uses only the `alpha=1` action grammar. Checkpoints are post-commit 600, 2,400, and 4,200.
- **New evidence streams:** six development and six evaluation seeds, disjoint from AR-03A and all AR-02 seed records:

  | Split | Seeds |
  | --- | --- |
  | Development | `1e27c8d46a90b35f`, `64b091f2d37a58ce`, `c31975a60de248bf`, `7f52e8a1349c06d7`, `a83d26f1c59740be`, `35e6b9128c4f70ad` |
  | Evaluation | `9d047ac26e31b58f`, `4f86d203b1a975ce`, `b27c5e0983d164af`, `0a53f8c62d9147be`, `6e1903d4a7c285bf`, `d5a841f07c3692eb` |

  All streams start from the same frozen initialization and training set; seeds vary proposal and verifier sampling only. Evaluation seeds are the replication units; checkpoints are nested.

## Held-out state/action design

- **States:** the three frozen checkpoints from each of six development and six evaluation streams. No evaluation stream contributes to feature fitting or response-oracle construction.
- **Candidate universe:** at each checkpoint, form the exact K2 top-2 singleton shortlists from the next P16 proposal sample. For every legal two-coordinate schedule block, enumerate its four top-2×top-2 programs. The singleton bye is omitted from the action-generalization audit. A block is retained only when all four programs remain within bounds at all three sidecar scales, so the action universe is identical across `alpha`.
- **Prospective action split:** within each pair block, a fixed hash of canonical parameter IDs assigns either the diagonal or off-diagonal rank combinations to development; the other two are evaluation actions. Each side contains one occurrence of each top-singleton rank on each coordinate. The same split is frozen across states and action scales.
- **Balanced estimator:** 12 equal strata of 8 examples; each verifier panel samples 4 per stratum without replacement and gives each stratum population weight `1/12`. Eight deterministic hash-placebo partitions are retained.
- **Proxy ladder:** input-only (all eight observed coordinates, standardized); current-state scalars (per-example loss, true-class logit margin, entropy); full raw 171D per-example gradient; development-response oracle (fitted only on development states × development actions); and per-evaluation-state response comparator (held-out response matrix, diagnostic only). All are exact-capacity 12×8 partitions. No utility response enters an observable proxy.
- **Clustering:** deterministic balanced k-means with one frozen initialization seed, exact 8-example capacities via Hungarian assignment, and a 25-iteration cap. Feature scaling and partition code are fixed before response evaluation.
- **Response scales:** at `alpha=0.5,1,2`, both action deltas are multiplied by alpha for diagnostic utility calculation. For each alpha, the response-oracle partitions are separately fit to the corresponding development or evaluation response matrix; input/state/gradient/hash partitions remain fixed. No sidecar result changes a state or action.
- **Panels:** 64 paired panel seeds per evaluation state, scale, and method. Panels are nested Monte Carlo measurements, not independent replications.

## Measures

Primary at `alpha=1`: mean within-stratum candidate-utility variance, exact finite-population predicted RMSE, observed panel RMSE, candidate sign error, cross-block opportunity regret, selected-program regret, and false authorization. Report per-seed values before seed-level means. Compare each proxy against the mean of eight hash placebos; report oracle headroom descriptively without a pass/fail threshold.

For every scale, report gradient and hash-placebo (plus response-comparator) within-stratum variance, predicted/observed RMSE, decision errors, and held-out Taylor RMSE/correlation/R²/sign error for `u_a(x)` versus `-g_x·(alpha*delta_a)`.

## Integrity and stop rules

- Test data generation/layout, model gradient consistency, exact partition quotas, action split balance, deterministic stream sampling, and schedule coverage before the diagnostic run.
- Verify all 12 stream seeds are disjoint from previous AR runs and development/evaluation splits do not overlap.
- Require identical eligible block/action counts across the three alpha values; otherwise the sidecar comparison is invalid and the cause must be resolved without changing the frozen data or seeds.
- Do not use the response matrices, validation labels, or partition outcomes to tune the dataset, action grammar, state checkpoints, clustering, or seeds.
- If the development-response oracle does not transfer, stop persistent response-partition discovery. If it transfers but gradient does not beat hash placebos consistently across evaluation seeds/actions, report the negative portability result and stop. If gradient does, request review for any later runtime/training experiment; this run does not authorize one.
- No AR-03B, controller change, learned proxy, action-scale training, feature zoo, or extra seed sweep is authorized by this protocol.

## Result

### Run identity and integrity

- Frozen protocol/source commit: `98f37dc1` (`exp(ar-03a-r1): freeze gradient geometry portability protocol`).
- Run: `artifacts/run-20260921-r1/`; release execution took 134.17 s. No validation data were generated or accessed.
- The generated 96-row dataset has class counts `32/27/37`; its SHA-256 is `02b771fe11bd8fe6c10c1103b0f09ce7bfe398c61105765d336ad2dd79961482`.
- The ordered 36 model snapshots are preserved in `model-states.bin` and indexed by `states.csv`; SHA-256: `dfc3302d7cd864f6ab523610afb443e4a23fbe27f49c521cc76ba5e43732c3b5`.
- Integrity counts: 36 states; 6,102 development-action and 6,102 held-out-action rows; 67,680 partition assignments; 702 state/method metrics; 44,928 panel measurements; 54 Taylor rows. Development/evaluation candidate-count checks had zero mismatches. All output values were finite, the JSON report parsed, and independent file hashes matched the report.
- Development/evaluation stream seeds and the dataset seed were checked against the other AR source records and were distinct. All six evaluation seeds contribute three nested checkpoints; checkpoints and 64 panel replicates are not independent seed-level replications.
- Preflight: 10 Rust tests pass; strict Clippy passes with `-D warnings`. The release diagnostic completed successfully.

### Held-out response geometry at the frozen training scale (`alpha=1`)

Means below first average checkpoints within each of the six held-out evidence streams, then average the six streams. The primary comparison is candidate-independent full per-example gradient features against the mean of eight hash-placebo partitions.

| Partition | Within-stratum utility variance | Predicted RMSE | Observed panel RMSE | Sign error | Cross-block regret | Selected-program regret | False authorization |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Hash-placebo mean | `2.929e-5` | `5.222e-4` | `5.216e-4` | 31.26% | `5.375e-4` | `6.069e-4` | 17.96% |
| Input-only | `2.998e-5` | `5.252e-4` | `5.279e-4` | 31.14% | `5.331e-4` | `6.043e-4` | 17.97% |
| Current-state scalars | `2.868e-5` | `5.126e-4` | `5.147e-4` | 30.85% | `5.335e-4` | `6.009e-4` | 18.06% |
| **Current-state gradient (171D)** | **`2.309e-5`** | **`4.517e-4`** | **`4.510e-4`** | **29.13%** | **`4.941e-4`** | **`5.520e-4`** | **14.15%** |
| Development-response oracle | `2.401e-5` | `4.614e-4` | `4.626e-4` | 29.40% | `5.047e-4` | `5.714e-4` | 17.62% |
| Per-evaluation-state response comparator | `2.280e-5` | `4.495e-4` | `4.482e-4` | 28.78% | `4.728e-4` | `5.300e-4` | 14.15% |

Against the hash-placebo mean, gradient strata reduce within-stratum utility variance by 21.2%, observed panel RMSE by 13.5%, sign error by 2.13 percentage points, cross-block regret by 8.1%, selected-program regret by 9.0%, and false authorization by 3.81 points. The gradient partition improves variance, RMSE, sign error, cross-block regret, and selected-program regret in all six evaluation streams; false authorization improves in five of six. The analytic finite-population RMSE prediction closely tracks observed panel RMSE (gradient: `4.517e-4` predicted, `4.510e-4` observed).

The development-response partition also improves held-out observed RMSE over hash placebo (`4.626e-4` versus `5.216e-4`), indicating some response-partition transfer across streams/actions. The per-state response comparator is diagnostic only, not a guaranteed optimum. Relative to the gap between hash placebo and that comparator, the gradient proxy closes 96.2% of the observed-RMSE gap; treat this ratio descriptively.

### Action-scale sidecar

| `alpha` | Mean held-out Taylor R² | Taylor R² range across 18 nested evaluation states | Gradient RMSE reduction vs hash | Gradient RMSE wins / 6 streams | Selected-regret wins / 6 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0.5 | 0.9926 | 0.9568–0.9991 | 13.56% | 6 | 6 |
| 1.0 | 0.9868 | 0.9301–0.9974 | 13.54% | 6 | 6 |
| 2.0 | 0.9755 | 0.9030–0.9919 | 13.44% | 6 | 5 |

Taylor fit weakens as action magnitude grows, as expected, while gradient-partition RMSE advantage remains nearly constant over this three-point diagnostic range. This supports the first-order explanation at the tested scales, but does **not** show that Taylor accuracy mediates the full partition benefit; gradient geometry may retain useful structure beyond the linear utility approximation. No scale other than `alpha=1` was used for training or runtime selection.

## Disposition

**AR-H47 is supported descriptively on this second synthetic substrate**, with important scope limits: one fixed 96-example dataset, one initialization, an eight-dimensional interaction-defined task, six evaluation evidence streams, held-out candidate rank-combinations, and three nested checkpoints per stream. This is a held-out state/action result over the same training-example universe, not generalization to unseen datapoints or an end-to-end optimizer-performance claim.

The result sharpens H44: current-state per-example gradient geometry is a strong candidate-independent proxy for grouping examples with similar local transition responses, and it improves finite-sample verifier estimation beyond arbitrary balanced partitions on this substrate. The scale sidecar is consistent with `u_a(x) ≈ -g_x·delta_a`, but does not isolate it as the sole mechanism. Full 171D gradients are a diagnostic proxy here; their runtime cost and any cheaper approximation remain untested.

**Strongest alternative explanation:** the held-out split is over evidence streams and top-rank action combinations, not over examples, datasets, or initializations. All six evaluation streams reuse one 96-example training set and one initialization, and the tested parameter moves remain locally small enough for Taylor fit to stay high even at `2x`. The observed benefit may therefore be a stable property of this fixed empirical objective/local action family rather than a broadly generalizable feature map. Gradient-stratum computation cost is also not included in the panel-evaluation RMSE and has not been justified as an end-to-end runtime tradeoff.

**Gate cleared for review of one further portability test only.** This run does not authorize AR-03B, using gradient strata in runtime decisions, action-scale training, feature expansion, or an end-to-end training comparison. Preserve the complete diagnostic outputs in this run directory and do not treat the six stream means as broad statistical qualification.
