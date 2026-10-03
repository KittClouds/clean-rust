# F4-INVARIANT-01 — Implementation Specification v0.1

**Status:** implementation specification only; no implementation, fixtures, task bank, seeds, run directory, or fit artifacts created  
**Controlling design:** `F4-INVARIANT-01-DESIGN-CONTRACT-v0.1.md`  
**Design SHA-256:** `52280190e160fafdbb973b4cda273bf9e24eca6ba96998a0393e90601fc88f40`  
**Parent feature/fit contract SHA-256:** `cfef638aaeac1dfc0b768d13cc95afe7724861f74e3d3111d91401925bed6379`  
**Measured REACH-03:** closed.

## 1. Purpose and authority

This document translates the frozen F4-INVARIANT-01 design into executable semantics. It does not change the scientific question, feature set, task distribution, support rule, model sizes, training budget, outcome order, or claim ceiling. Where an implementation cannot satisfy a stated byte or numerical invariant, stop and version an amendment before generating tasks or opening any arm comparison.

The sole comparison is the frozen sorted-sidecar MLP **D** versus the shared sum-pooled set-encoder **S**. The shared set encoder is invariant to tuple permutation while the common 66D base is fixed. No global cue-permutation invariance claim is allowed because that base retains absolute cue-slot fields.

No reference-derived values may enter predictor construction. Reference targets remain in a separate scoring/training-label stream. The measured REACH-03 filtration, any controller, PHENO, and biological interpretation remain outside this implementation.

## 2. Authority and preflight

Before creating a task or seed manifest, the implementation must verify byte-level SHA-256 for:

1. the controlling design contract, equal to `52280190e160fafdbb973b4cda273bf9e24eca6ba96998a0393e90601fc88f40`;
2. this implementation specification and all parent contracts listed in its header;
3. the frozen D model/training source, clean feature source, row-key and inclusion-probability source, ordinary task generator, replay/evaluator source, and dependency lock/runtime description.

The preflight records `{relative_path, byte_length, sha256}` for each source. It records both the canonical source-manifest digest and the on-disk file digest using the v0.2 manifest convention. Protected inputs are rehashed after collection; any drift stops the identity.

Before importing NumPy or any numerical runtime, set and require:

```text
OPENBLAS_NUM_THREADS=1
OMP_NUM_THREADS=1
MKL_NUM_THREADS=1
BLIS_NUM_THREADS=1
VECLIB_MAXIMUM_THREADS=1
NUMEXPR_NUM_THREADS=1
```

Use the parent implementation's pinned runtime identity (Python 3.13.15, NumPy 2.5.3, Windows x86_64, the recorded scipy-openblas build). Record `numpy.show_config()`, package versions, and effective thread variables. A different runtime is a preflight stop, not a reason to accept approximate parity.

The preflight receipt must state `qualification_only=true`, `measured_namespace_created=false`, `task_bank_created=false`, and `fit_manifest_created=false`.

## 3. Source rows and shared input stream

Use the exact admissible 66D base and four six-field tuples from the parent F4-SYMMETRY-01 contract. Each tuple's six values, in order, are:

```text
(I_ic, r_c, I_ic*r_c, delta_c, I_ic*delta_c, r_c*delta_c)
```

where `r_c = y_c * action_sign_j` and `delta_c = p_cj - 0.5`. The standalone ordinary-forward probability routine, its operation order, and its source dependencies remain those of the parent contract. Do not call or reproduce a reference-only intermediate.

For each leave-one-block-out fold:

- fit the 66 base means/scales from training rows only, in frozen source-field order; population standard deviation (`ddof=0`); scales below `1e-6` become `1.0`;
- fit the three relational float-component means/scales from training rows, pooling all four cue positions in frozen row order and cue indices 0, 1, 2, and 3; use the same component statistics at every cue position/rank; scales below `1e-6` become `1.0`;
- cast the first three tuple components to float32 without standardizing them;
- normalize the final three tuple components with the pooled fold statistics and apply them unchanged to held-out rows;
- serialize all normalized values as IEEE-754 little-endian float32, rejecting NaN and infinity and normalizing signed zero to positive zero.

Before either arm presents the tuple values, construct three hashes per fold:

1. `base_stream_sha256`: row key followed by normalized 66D base bytes;
2. `normalized_tuple_stream_sha256`: row key followed by all four normalized tuples in original cue-slot order;
3. `paired_source_input_sha256`: row key, normalized base, and original-order normalized tuples.

For each stream, prepend its fixed ASCII domain tag plus NUL (`F4-INV01-BASE-v1`, `F4-INV01-TUPLES-v1`, or `F4-INV01-PAIRINPUT-v1`), then append records in frozen global row order. Each row key is the exact 18-byte parent-contract key. Base values are 66 consecutive LE f32 values. Tuple values are 4×6 consecutive LE f32 model-input values, with tuples in source cue order. D and S receipts for the same fold must name identical values for all three hashes and the same normalization hash. D's subsequent sort is an arm presentation operation and does not alter the common source-stream digest.

## 4. D presentation and fit

D consumes the common normalized base and normalized tuples. It sorts the four tuples using the exact parent comparator: the three discrete values first, followed by the three finite float32 values under `f32::total_cmp` after signed-zero normalization; no cue ID or original position breaks ties. D then concatenates the sorted 24-value sidecar after the 66 base values.

D's model remains the frozen float32 MLP `90→128→64→1`, GELU after the first two affine transforms, and linear logit output. Preserve the parent GELU expression, derivative, BCE-with-logits gradient, clipping interval `[-30,+30]` for the gradient sigmoid, Adam update, and minibatch traversal byte-for-byte at the source-code level where shared code is used. Do not copy old D weights or predictions; fit D anew on this branch's folds.

## 5. S forward pass and exact operation order

S receives the 66D normalized base and the same four normalized six-value tuples in original cue-slot order. Let `R` be the row-major float32 tuple matrix with shape `(N*4, 6)`; rows are ordered by frozen sample row, then cue index `0,1,2,3`.

### Shared tuple transform

The shared parameters are `phi_w` with shape `(6,16)` and `phi_b` with shape `(16,)`. For tuple row `n` and output coordinate `k`, compute the affine preactivation in the following exact order:

```text
acc = f32(R[n,0] * phi_w[0,k])
for d in [1, 2, 3, 4, 5], in ascending order:
    product = f32(R[n,d] * phi_w[d,k])
    acc = f32(acc + product)
z[n,k] = f32(acc + phi_b[k])
```

Each multiply and add rounds to binary32; multiplication and addition are separate operations, with no fused multiply-add. The implementation may vectorize over `n` and `k`, but it must preserve this six-feature accumulation order exactly. Then apply the existing frozen float32 GELU expression elementwise to obtain `H` with shape `(N*4,16)`, and reshape it to `(N,4,16)` without reordering rows.

For each training or inference row, pool in the fixed left-associated order:

```text
h01    = f32_add(h0, h1)
h012   = f32_add(h01, h2)
h_set  = f32_add(h012, h3)
```

Apply this componentwise to all 16 coordinates. Do not sort tuples, use a tree reduction, average, or add cue-position parameters. The permitted floating summation difference under tuple permutation is handled only by the fixture tolerance in §10; the training path always uses the source cue order.

### Readout

Concatenate `[x_base, h_set]` in that order to form float32 input width 82. `rho` has layers `82→128→64→1`, with GELU after the first two affine transforms and a linear logit. Its dense operations, activation, derivative, and BCE path use the same frozen NumPy/BLAS implementation and runtime as D. There is no normalization after `h_set`, dropout, residual path, positional encoding, or additional feature.

### S backpropagation

Use the ordinary chain rule through `rho`, then through the sum and shared `phi`:

- the gradient entering each `h_c` is the same row's gradient entering `h_set`;
- multiply each tuple's gradient by the frozen GELU derivative at its own `z[n,k]`;
- flatten tuple gradients in sample-row-major, cue-index-major order, matching `R`;
- compute shared `phi_w` gradient as `R.T @ dZ` and `phi_b` gradient as the sum of `dZ` over that same flattened order;
- keep all gradient arrays float32 and use the pinned single-thread numerical runtime.

No gradient clipping, weight decay, class weighting, or early stopping is added.

## 6. Parameter tensors and initialization identity

The exact trainable parameter counts are:

| Arm | Tensor shapes | Count |
| --- | --- | ---: |
| D | `(90,128),(128),(128,64),(64),(64,1),(1)` | 19,969 |
| S | `(6,16),(16),(82,128),(128),(128,64),(64),(64,1),(1)` | 19,057 |

S is 4.57% smaller than D and within the 5% matching band. Bias tensors are initialized to float32 zero.

The paired unit is `(fold_index, replicate_index)`, not a pair of equal weight tensors. `fold_index` is the integer 0 through 11 inclusive in ascending held-out task-block order; `replicate_index` is one of 0, 1, or 2. For each arm and each weight layer, derive a distinct deterministic seed using:

```text
payload = ASCII("F4-INVARIANT-01-INIT-v1") || 0x00 ||
          LE32(fold_index) || LE32(replicate_index) ||
          ASCII(arm) || 0x00 || UTF8(layer_name)
digest = SHA256(payload)
seed_u64 = LE64(digest[0:8])
```

Arm is exactly `D` or `S`. The D layer names are `w1`, `w2`, `w3`; S layer names are `phi.w`, `rho.w1`, `rho.w2`, `rho.w3`. Each tensor gets its own seed so tensor generation does not depend on another layer's shape or random-stream consumption. Use `numpy.random.Generator(numpy.random.PCG64(seed_u64))`; draw row-major standard-normal float64 values; multiply by `sqrt(2/fan_in)` in float64; cast once to float32. Record the full digest, seed value, tensor name, shape, and initialized tensor hash.

The D and S receipts share the same fold/replicate identity but have arm- and layer-specific seed digests. Do not assert or imply bit-identical initialization tensors across architectures. Do not choose, replace, or drop an initialization replicate based on its score.

Create `INITIALIZER-SEED-MANIFEST.json` from this formula before task IDs or task payloads exist. It lists every `(fold_index, replicate_index, arm, layer_name)` combination, exact payload bytes, digest, `seed_u64`, tensor shape, and fan-in. Hash it and name that hash in every fit-manifest row. Because folds are indexed by ascending task ID and IDs are not yet assigned, the manifest covers fold indices 0 through 11; no task, target, outcome, or task seed enters its derivation.

## 7. Optimizer and update schedule

Both arms use the parent binary cross-entropy training objective and update schedule:

- map `Y=-1` to `0.0f32` and `Y=+1` to `1.0f32`; reject `Y=0` in fit matrices;
- unweighted binary cross-entropy; inclusion weights affect scoring only;
- Adam with `lr=0.001`, `beta1=0.9`, `beta2=0.999`, `epsilon=1e-8`;
- zero-initialized first and second moments; one shared optimizer step counter per fit;
- 200 complete epochs, batch size 2,048, frozen global row order after excluding the held-out block, no shuffle, final short batch retained;
- update every weight and bias tensor exactly once per minibatch, in fixed tensor order; apply the same bias-correction expression as the parent implementation.

There is no checkpoint selection: the final epoch is the only prediction checkpoint. Expected update count per fit is `200 * ceil(training_rows / 2048)`.

## 8. Task panel, folds, and fail-closed cases

The future collection uses exactly 12 fresh ordinary task blocks, four cues, 8,192 trials per block, delay 12, nine frozen substrates, two sides, and the frozen 64 selected coordinates per substrate-side cell. Use one new domain-separated task/simulator seed namespace. Generate and freeze all 12 blocks once, with no structural screen, pattern quota, target inspection, U* screening, replacement, or seed shopping. This specification defines no concrete task IDs or seed values.

Use 12-fold leave-one-task-block-out fitting. A fold holds out that block across all 18 substrate-side cells. The complete planned grid is 12 folds × 3 initialization replicates × 2 arms = 72 fits.

Before fit 1, inspect training labels only to establish that every one of the 12 training partitions has at least one `Y=-1` and one `Y=+1` row and is nonempty. If any fold fails, stop the entire fit phase as `STOP_DEGENERATE_TRAINING_FOLD`; do not train only a subset of folds, merge folds, alter the label rule, or generate replacement tasks. Held-out class support is a separate matter: execute the full 72 fits regardless of whether an individual held-out block has both classes. If fewer than 10 of 12 held-out blocks are class-complete on U*, finish all fits and classify the comparison `NOT_EVALUABLE_SUPPORT`; pooled results may be shown as descriptive diagnostics only.

## 9. Fit and prediction artifacts

All fit inputs and the complete 72-row fit manifest are frozen before fit 1. Use UTF-8 without BOM and LF line endings for CSV. Manifest row order is replicate index ascending, arm `D` then `S`, then held-out block ascending. `fit_id` is `<arm>-H<block_id>-I<replicate_index>`.

The manifest header is:

```text
fit_id,arm,fold_index,heldout_block,replicate_index,train_rows,heldout_rows,contract_sha256,source_manifest_sha256,executable_sha256,analysis_sha256,base_stream_sha256,normalized_tuple_stream_sha256,paired_source_input_sha256,normalization_sha256,training_row_hash,training_order_hash,initializer_seed_manifest_sha256,initial_tensor_hash,expected_prediction_path
```

`training_row_hash` is SHA-256 over the concatenation of the 18-byte training row keys sorted lexicographically by raw bytes. `training_order_hash` is SHA-256 over the same keys in frozen global stream order after removing the held-out block.

Every fit receipt records those applicable fields plus architecture ID, parameter count, batch/epoch/update counts, all per-layer initializer digests, final tensor hash, finite status, prediction hash, elapsed time, and numerical runtime identity. Initial/final tensor hash serialization is: tensor name plus NUL, LE u32 rank, each dimension as LE u32, then row-major little-endian float32 tensor bytes, concatenated in the arm's declared tensor order and SHA-256 hashed.

Each prediction stream uses a 72-byte header:

| Bytes | Encoding |
| --- | --- |
| 0–15 | ASCII `F4INV01PREDv1` followed by three NUL bytes |
| 16–19 | LE u32 schema version `1` |
| 20–27 | LE u64 held-out block ID |
| 28 | u8 arm ID (`D=0`, `S=1`) |
| 29 | u8 replicate index (`0`, `1`, or `2`) |
| 30–31 | two reserved zero bytes |
| 32–39 | LE u64 prediction count |
| 40–71 | raw 32-byte SHA-256 of the exact manifest CSV row, including LF |

Each following record is 18-byte row key plus one LE f32 logit (22 bytes). Records follow frozen held-out global row order. Hash the complete stream and store that digest in its fit receipt. The prediction writer receives held-out features only; it does not receive held-out `Y` or `g`.

## 10. Pre-fit fixtures and implementation gates

Run all gates before any model fit, with a receipt for each. No task is created until the design/spec/source hash gate and code review pass.

1. **Authority and source gate:** controlling hashes, runtime, source manifest, source paths, and absence of pre-existing task/run output under this identity match.
2. **Parent-input reconciliation:** replay the frozen feature builder on predeclared non-outcome fixtures; verify the exact 66D field map, four tuple values, 18-byte row key format, fold normalizers, U* rule, inclusion probabilities, and predictor/truth separation.
3. **Forward-probability parity:** reuse the exact standalone `p_cj` ordinary-forward reconciliation fixture and operation order from the parent implementation contract; no reference helper may be used to produce predictor values.
4. **S tuple-permutation fixture:** for each fixed fixture base and tuple set, evaluate all 24 tuple permutations while holding `x_base` fixed. Use the identity cue order as the reference. Require every S logit to satisfy `abs(logit_perm-logit_identity) <= 1e-6 + 1e-6*abs(logit_identity)`. Record maximum absolute difference and tested tuple/base hashes. This is a representation fixture only: it reads no target/reference value and does not assert whole-model invariance under task relabeling.
5. **Operation-order fixture:** compare an independently written small scalar reference for the six-feature affine pass and the left-associated four-embedding sum against the production S forward pass. Require bit-identical float32 outputs for the same tuple order; verify all 24 permutation outputs remain within the §4 tolerance.
6. **Shared-input gate:** require byte-identical base, pre-presentation normalized tuple, and paired-source stream hashes for D and S on every fold. Recompute tuple multisets and require equality between D's sorted values and S's cue-order values before the S transform.
7. **Architecture/initialization gate:** assert exact tensor shapes/counts, shared `phi` use, distinct per-layer seed digest derivation, deterministic tensor regeneration, zero biases, and exact tensor hashes for every fold/replicate/arm before fitting.
8. **Training-partition gate:** all 12 training partitions are nonempty and contain both classes. A failure stops the entire fit phase before fit 1.
9. **Score-fixture gate:** synthetic fixture data verifies the frozen prediction threshold, IPW-balanced error, class-absent block behavior (`null`), signed-margin calculation, `Psi` and leverage concentration accounting. The fixture contains no measured task outcomes.

Any hard-gate failure receives a named stop receipt and blocks all fits. A gate cannot be bypassed by widening the tolerance, switching BLAS, adding a feature, changing fold support, or substituting another task.

The tuple/order fixture inputs are fixed by formulas, not sampled from task or outcome data. For each integer `k` from 0 through 65 inclusive, set `x_base[k]=f32(((k mod 11)-5)/8)`. The four six-field tuple rows, in fixture identity order, are exactly:

```text
(1,+1,+1,-0.375,-0.375,-0.375)
(0,-1, 0,-0.125, 0.000,+0.125)
(1,-1,-1,+0.125,+0.125,-0.125)
(0,+1, 0,+0.375, 0.000,+0.375)
```

For the operation-order fixture only, initialize deterministic test weights from integer index formulas, then cast once to f32: `phi_w[d,k]=(((11*d+5*k) mod 23)-11)/128`, `phi_b[k]=((k mod 5)-2)/32`, `rho_w1[i,j]=(((7*i+3*j) mod 31)-15)/256`, `rho_w2[i,j]=(((5*i+11*j) mod 29)-14)/256`, and `rho_w3[i,0]=(((3*i+13) mod 17)-8)/128`; all fixture biases are zero. Index ranges are the tensor dimensions in §6. Modulo means the nonnegative remainder. Hash these exact fixture inputs and weights in the gate receipt. These arrays are disposable audit fixtures, not training examples or part of the task bank.

## 11. Prediction lock, integrity, and analysis

During collection and fitting, operational output may report counts, hashes, finite status, process/resource health, and completed fit IDs. It must not report D-versus-S losses, signed margins, `Psi`, block rankings, or interim comparative summaries.

Before held-out truth opens, an independent integrity pass verifies:

- exactly 72 unique `(arm, fold, replicate)` fits and expected predictions;
- no missing, duplicate, extra, malformed, or nonfinite rows/logits/tensors;
- exact row-key and held-out ordering per fold;
- the same paired source-input hashes and normalizers for D/S within each fold;
- the full initialization-seed and tensor receipts;
- all fixture and training-partition gates passed;
- original source and executable hashes remain unchanged.

Only after `INTEGRITY_PASS`, join held-out truth and compute outcomes using float64 accumulators for weighted summaries. For scoring row `j`, use `q_j=1/p_inclusion_j`. Pooled balanced error is the mean of the two q-weighted class-conditional error rates. Report unclipped `Omega_hat=1-2*epsilon_bal` and clipped `max(0, Omega_hat)`. No denominator floor is allowed for a class-absent held-out block; its blockwise balanced error is null, while its one-class signed-margin diagnostic may be shown. The pooled OOF score uses all eligible rows across blocks.

For every `Psi`, report the leverage weights `w_j=q_j*abs(native_proposed_delta_j)*abs(g_j)`, leverage ESS, and top 1%, 5%, and 20% leverage shares. If `sum(w)=0`, `Psi` and its concentration metrics are null. For concentration ranks, order rows by descending `w`, breaking ties by ascending raw row-key bytes; the top `p%` contains `ceil(p*N)` rows. Report accuracy/error, signed-margin orientation, `Psi`, and delivery alignment as separate quantities. No endpoint trajectory or controller run is part of this branch.

The terminal result reports the comparison in this order: pooled D/S balanced error and `Delta_(S-D)`; the three replicate contrasts; blockwise paired errors and evaluability; signed margins; `Psi` with concentration; delivery-aware local alignment; support and integrity dispositions. The advancement disposition is `NOT_EVALUABLE_SUPPORT` if fewer than 10 blocks are class-complete; otherwise nominate S for a separate calibration design only if mean `Delta_(S-D)<0`, S has lower pooled error in at least two of the three initialization replicates, and the mean blockwise difference favors S in at least `ceil(2E/3)` of E class-complete blocks. If support passes but any comparative condition fails, disposition is `NO_CLEAR_COMPARATIVE_ADVANTAGE`. Passing nominates a candidate only; it is not a calibration pass. Interpret any positive result as utility of the **shared set-encoder architecture package** under the fixed base, task distribution, estimator, and training budget. Do not attribute the change to permutation invariance alone.

## 12. Required receipt set

The later execution package must include at least:

```text
DESIGN-CONTRACT-HASH.json
SOURCE-INPUT-MANIFEST.json
INITIALIZER-SEED-MANIFEST.json
IMPLEMENTATION-PREFLIGHT-RECEIPT.json
TASK-BANK-MANIFEST.json
SHARED-INPUT-RECONCILIATION.json
S-PERMUTATION-FIXTURE-RECEIPT.json
S-OPERATION-ORDER-FIXTURE-RECEIPT.json
TRAINING-SUPPORT-RECEIPT.json
FIT-MANIFEST.csv
fit-receipts/<fit_id>.json
heldout-predictions/<fit_id>.bin
PREDICTION-LOCK.json
INTEGRITY-RECEIPT.json
ANALYSIS.json
RESULTS.md
F4-INVARIANT-01-TERMINAL-RECEIPT.json
```

JSON is UTF-8 with sorted keys, two-space indentation, and one trailing LF. Hash both the canonical JSON value and the on-disk file bytes where a manifest digest is used. The terminal receipt includes the contract/spec/code/runtime and initializer-seed-manifest hashes, task-bank identity, actual and expected fit/row counts, training and held-out support, gate statuses, prediction-lock and integrity statuses, primary paired contrasts, advancement-rule disposition, and explicit `qualification_only=true`, `measured_reach03_authorized=false`, and `biological_promotion=false` fields.

## 13. Stop boundaries

Stop before any fit if authority/source hashes fail, the shared input streams differ, parent row/forward computations do not reconcile, S fails tuple permutation or operation-order fixtures, parameter counts differ from contract, or any training fold is empty or one-class. After fitting, stop before analysis if any integrity condition fails. Preserve every failure under its run identity; do not repair it in place, regenerate tasks, change the estimator, or replace any seed.

This document specifies implementation semantics only. It does not itself authorize code changes, task generation, fixture execution, seed creation, native collection, fitting, or a measured REACH-03 run. Those are subsequent steps under the user's direction.
