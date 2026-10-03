# F4-SYMMETRY-01 — implementation specification v0.1

**Controlling contract:** `F4-SYMMETRY-01-CONTRACT-v0.1.md`  
**Contract SHA-256:** `cfef638aaeac1dfc0b768d13cc95afe7724861f74e3d3111d91401925bed6379`  
**Role:** literal implementation map for the frozen qualification design.  
**Status:** specification only; no collector or classifier implementation is added by this document.

## 1. Authority and immutable inputs

At process start, recompute and require the controlling F4-SYMMETRY contract SHA above. Hash and record this implementation specification and its SHA sidecar, the contract SHA sidecar, the historical math-audit draft (provenance only; it cannot override the frozen contract), the authoritative REACH-03 v0.3 math contract and machine objects used for secondary-score definitions, `F4-ENCODER-SPEC-v1.json` and its SHA file, the frozen training bank, qualification manifest, frozen graph/anatomy inputs, source files used for replay and feature generation, prior F4-v3 row streams and receipt, Python script(s), Rust executable, Python executable, and dependency/runtime description. Store `{relative_path, byte_length, sha256}` for each input in `SOURCE-INPUT-MANIFEST.json`. Normalize relative paths to `/`, reject `.` and `..` components, sort records by UTF-8 path bytes, then serialize the complete JSON value as UTF-8 with lexicographically sorted object keys, no insignificant whitespace, and no trailing LF; SHA-256 those bytes for the manifest digest. Hash the protected source inputs again after collection and require equality.

The original F4-v3 stream is used only to define the frozen eligible row-key set, inclusion probabilities, and target labels for row reconciliation. None of its 85 predictor values (including the legacy 80D feature block and its expected-score fields) are copied into A/B/C/D. The new raw predictor stream is reconstructed by deterministic native replay from the frozen qualification source/task inputs.

Required qualification facts before feature generation:

- Four task blocks: 303000, 303001, 303002, 303003; 18 substrate-side cells; 72 existing streams; 13,420 eligible rows in the prior F4-v3 collection.
- Substrate ordinals are fixed: `0=fly`, `1=g001`, `2=g002`, `3=g003`, `4=g004`, `5=g005`, `6=g006`, `7=g007`, `8=g008`; side ordinals are `0=L`, `1=R`.
- Row identity is `(substrate_id, side_id, block_id, trial, coordinate)`.
- For each substrate-side-block cell, initialize `row_index=0`. Iterate trials in ascending order and each cell coordinate in the manifest's stored order. Emit a row only when `Y != 0`, `abs(native_proposed_delta) > EPS`, and `row_index % 256 == 0`; increment `row_index` once for every coordinate on every trial, whether emitted or not. The target is `+1` iff the frozen reference value is greater than `EPS`, `-1` iff it is less than `-EPS`, and `0` otherwise. Each emitted row keeps its frozen inclusion probability.
- `EPS` is the frozen executor's `1.0e-12f32` constant; both support and target classification use the existing exact float32 comparisons, with no conversion to f64 before thresholding.
- Stream order is filenames in ascending UTF-8 byte order; rows within a stream retain collector order (trial ascending, then the coordinate sequence as stored in the frozen cell manifest).

Replay/source dependencies are limited to the frozen graph loader (`graph.rs`), task constructor and task bank (`task.rs`, `training.json`), native simulator state and trial schedule (`reach_sim.rs`), reference target implementation for scoring/eligibility (`collector.rs::reference_delta_into` and `collector.rs::target`), native proposed support (`Sim::proposed_delta_into`), and the qualification manifest/cell coordinate lists. Predictor generation may read the task label only for the declared label/sketch and relational fields; target/reference APIs are isolated to eligibility and the parallel truth stream.

Do not call legacy `qualification.rs::f4_features` or any expected-score helper while building predictors, even if the returned score fields would later be discarded. Reimplement the allowed source fields one by one in the new collector; use the old function only as a field-layout reference. This prevents a prohibited intermediate from entering the predictor-generation path at all.

Any contract, training-bank, graph, row-key, count, inclusion-probability, target, or native-replay mismatch stops before fitting. No replacement, remapping, or inferred row is allowed.

## 2. Source-to-A output map

The legacy 80D source is `qualification.rs::f4_features`. A is formed by selecting only the source indices listed below, preserving the order within each range. All values are stored as IEEE-754 float32 little-endian. Reserved zeros are omitted.

| A output positions | Legacy source positions | Content |
| --- | --- | --- |
| 0–20 | 0–20 | coordinate, edge pre/post, degrees, edge multiplicity, anatomical sign, normalized trial, current native state |
| 21–24 | 21–24 | task-label signs in absolute cue order |
| 25–28 | 29–32 | cue-edge incidence in absolute cue order |
| 29–41 | 33–45 | current schedule cue/distractor pattern IDs |
| 42–65 | 53–76 | four six-bucket signed task-coordinate sketches |

Source indices 25–28 (expected cue scores), 46–52 and 77–79 (padding) are forbidden from A. The resulting width is exactly 66. Do not regenerate sketch keys differently: port the existing `stable_mix`, wrapping arithmetic, six-bucket condition, signed contribution, accumulation order, and final division exactly from the frozen feature source.

For auditability, the retained source values are fixed index by index: `0=coordinate/edge_count`; `1=edge.pre/max(n_pre,1)`; `2=edge.post/max(n_post,1)`; `3=pre_degree/max(n_post,1)`; `4=post_degree/edge_count`; `5=edge.count/32`; `6=mb_sign[post]`; `7=trial/max(schedule_len,1)`; `8=weights[coordinate]`; `9=eligibility[coordinate]`; `10=cached probabilities[post]` from the final sample in `begin_trial`; `11=post[post]`; `12=baseline[post]`; `13=signed_post[post]`; `14=gain[post]` after `proposed_delta_into`; `15=denom[post]`; `16=bias[post]`; `17=scale`; `18=lambda`; `19=ln_1p(work)/32`; `20=ln_1p(events)/16`. Values 21–24 are labels in task cue order encoded as `+1.0f32` for true and `-1.0f32` for false. Values 25–28 are cue-edge membership bits in cue order. Values 29–41 are the first 13 current schedule pattern IDs, each divided by `max(cue_count+32,1)` and zero-filled if fewer than 13 entries occur. These source fields are sampled after `begin_trial` and `proposed_delta_into`, before `apply_delta`.

The 24 retained sketch values use four sketch families and six buckets. For each family `f=0..3` and cue `c` in order, form, with wrapping u64 arithmetic, `key=coordinate + c*0x9e3779b97f4a7c15 + (pattern_edge_count[c] << 17) + (f << 32)`. Apply the frozen `stable_mix`: xor with right shift 30; wrapping multiply by `0xbf58476d1ce4e5b9`; xor with right shift 27; wrapping multiply by `0x94d049bb133111eb`; xor with right shift 31. When `mixed % 6 == bucket`, add `sketch_sign * label_sign[c]`, with `sketch_sign=+1` for `mixed & 1 == 0` and `-1` otherwise, in ascending cue order. Divide each bucket sum by `max(cue_count,1)`. Sketch output index is `42 + 6*f + bucket`.

## 3. Standalone cue/post forward state

Implement `p_cj` in a new feature module as a pure function of graph pattern edges/offsets, post `j`, the pre-delivery `weights`, active mask, denominator, and bias. It may not call `expected_score`, `expected_score_for`, `reference_delta_into`, or read labels, target, reference values, or reference intermediates.

For each cue `c`, post `j`, and its edges in the existing pattern row order:

```
drive: f32 = 0.0
for edge in pattern.edges[pattern.offsets[j] .. pattern.offsets[j+1]]:
    if active[edge]:
        drive = drive + weights_before[edge]       // f32, same order as Sim::sample
x: f32 = 2.0 * (drive / denom[j] - bias[j])       // same expression as Sim::sample
x_clamped: f32 = clamp(x, -30.0, +30.0)
negative_x: f32 = -x_clamped
p_cj: f32 = 1.0 / (1.0 + exp_f32(negative_x))
```

Use the same Rust compiler/toolchain and target as the frozen executor; reject nonfinite outputs. Reconciliation is a hard bitwise gate: for every cue/post in the fixed forward fixture, clone the simulator at the identical state, invoke its ordinary `sample(pattern)` path on the clone, and compare `p_cj.to_bits()` with the corresponding cached probability bits. Add only a crate-private fixture wrapper around the existing `Sim::sample` if module privacy requires it; it is called on disposable clones and must not be used by native replay. This uses the simulator forward path, never the reference operator. On mismatch write `STOP_FORWARD_PROBABILITY_RECONCILIATION` with the first mismatching fixture key and stop before creating arm matrices.

## 4. Raw tuple, C/D packing, and normalization

For a sampled coordinate at post `j`, compute four raw tuples in cue order. Store `I` as u8 (`0` or `1`), `r=y*a` as i8 (`-1` or `+1`), `I*r` as i8 (`-1`, `0`, or `+1`), and the three floating values as f32. Compute them in this order, rounding each operation to binary32: `delta = p_cj - 0.5f32`; `I_delta = f32(I) * delta`; `r_delta = f32(r) * delta`. Normalize either signed zero in these three values to `+0.0f32` before serialization or ordering. Encode the tuple as one u8, two one-byte two's-complement i8 values, and three LE f32 bit patterns:

```
tuple = (I, r, I*r, delta, I_delta, r_delta)
```

The `a` value is the simulator's action-sign state for post `j`; `y` is the task-label sign. No outcome target or reference value enters tuple construction.
Before casting to the frozen integer fields, require each `y_c` and `a_j` to be exactly `-1` or `+1`; a different value is a contract failure, not a rounding case.

Raw predictor record layout is fixed below. The feature file has a 32-byte header: bytes 0–15 are `FLYREACH3SYMINP\0`; bytes 16–19 are LE u32 schema version `1`; bytes 20–23 are LE u32 record width `342`; bytes 24–31 are LE u64 row count. Each record is:

| Record byte offsets | Encoding | Field |
| --- | --- | --- |
| 0 | u8 | substrate ordinal from frozen manifest order |
| 1 | u8 | side (`0=L`, `1=R`) |
| 2–9 | LE u64 | block ID |
| 10–13 | LE u32 | trial |
| 14–17 | LE u32 | coordinate |
| 18–281 | 66 × LE f32 | raw A values in output order above |
| 282–341 | 4 × 15-byte tuple | cue-order `(u8, i8, i8, f32, f32, f32)` |

The parallel truth record has a 32-byte header: magic `FLYREACH3SYMTRU\0`, LE u32 version `1`, LE u32 record width `39`, LE u64 count. Each record is keyed by the identical 18-byte row key, followed by inclusion probability LE f64, target sign i8, signed native proposed delta f32, pre-delivery weight f32, and reference value f32 (each f32 little-endian). Magnitude and native sign are derived from the signed proposed delta. Truth records are stored separately from predictors; the fitting loader receives training labels only. Held-out target/reference truth is opened by the analysis stage after prediction hashes and the integrity receipt are written.

### C and D sidecars

- C raw sidecar is the four packed tuples in cue order; model input positions 66–89 are fields `(0..5)` of cue 0, then cue 1, cue 2, cue 3.
- D sorts those same four raw tuples lexicographically by `(I, r, I*r, delta, I_delta, r_delta)`. Compare the first three fields as exact integers; compare the final three with Rust `f32::total_cmp` after signed-zero normalization. Reject NaN and infinity. No cue ID, schedule ID, or original tuple position is a tie-break. Equal tuples encode identically.
- Before normalization, require rowwise `multiset(C_raw)==multiset(D_raw)` by canonical serialized tuple bytes. After normalization, require the same multiset equality again. A mismatch stops as `STOP_CANONICAL_SIDECAR_VALUE_DRIFT`.
- For both C and D, estimate one mean/scale pair for each of the three float tuple components, pooling training rows across all four cue positions. Use those same three pairs at every cue/rank position. `scale < 1e-6` becomes `1.0`. Discrete tuple fields convert to f32 and are not standardized. Store C and D's shared component stats as LE f32 in the normalization artifact.

## 5. Normalization artifact and order

Use population standard deviation (`ddof=0`) as in NumPy's frozen `standardize` helper. All input arrays and means/scales are float32. Compute means/scales in this order: A fields in output-index order; B projections in projection-index order; relational float components `(delta, I_delta, r_delta)` in that order, pooling values in frozen row order and cue index 0–3 within each row (equivalently, C-order reshape of the training tuple array from `(n_train,4,3)` to `(4*n_train,3)`). Set any scale below `1e-6` to `1.0` before transforming. Do not compute statistics on held-out rows.

Each fold writes `NORMALIZATION-<holdout-block>.bin` with a 32-byte header and 744-byte payload:

| File offset | Encoding | Contents |
| --- | --- | --- |
| 0–15 | fixed bytes | ASCII `FLYREACH3SYMNOR` followed by one NUL byte |
| 16–19 | LE u32 | version `1` |
| 20–27 | LE u64 | held-out block ID |
| 28–31 | LE u32 | payload size `744` |
| 32–295 | 66 LE f32 | A mean vector |
| 296–559 | 66 LE f32 | A scale vector |
| 560–655 | 24 LE f32 | B projection mean vector |
| 656–751 | 24 LE f32 | B projection scale vector |
| 752–763 | 3 LE f32 | shared relation-component mean vector |
| 764–775 | 3 LE f32 | shared relation-component scale vector |

The complete file is 776 bytes. Hash the whole file and name that hash in each fold/arm receipt. A/C/D share A means/scales; B/C/D use the listed sidecar statistics. C and D share relation-component statistics exactly.

## 6. B projections and fold preprocessing

Use per-fold A normalization computed from training rows only, in f32, with the exact normalization in §5. Hash the exact LE f32 mean and scale vectors. B's random matrix has shape `(24,66)`. For zero-based `(r,k)`, construct the exact message bytes:

```
UTF8("F4-SYMMETRY-01-B-PROJ-v1") || LE32(r) || LE32(k)
```

Compute SHA-256 and use `digest[0] & 1`: zero selects `f32::from_bits(0x3dfc1764)`, one selects its negative; the positive bit pattern is binary32 `1/sqrt(66)`. No arm/block/fold/row/label/target value is added to the hash key. Hash the complete row-major projection matrix as LE f32. Compute B features from fold-normalized A with 66 ordered float32 multiply then add operations per projection, with no fused multiply-add and no BLAS matrix multiplication. Then fit 24 training-fold-only means/scales over B projection outputs (same `std<1e-6 => 1` rule) and apply unchanged to held-out rows. The B-sidecar receipt hashes the projection matrix, fold A normalizer, B normalizer, and output sidecar.

For C and D, base columns use the exact A fold normalizer. Sidecar normalization follows §4 and §5. Norm statistics are fit from the training fold and apply unchanged to held-out rows. No statistic is fit on the full panel.

## 7. Estimator and fit identity

Use the existing `numpy_mlp` calculation without changing its loss, derivative order, activation, optimizer, or batch traversal:

- float32 arrays; hidden widths `(128,64)`; GELU formula and derivative from `f4_encoder_qualification.py`;
- map the nonzero target `Y=-1` to training label `0.0f32` and `Y=+1` to `1.0f32`; reject `Y=0` in fit matrices. Use unweighted binary cross-entropy logits, implemented through sigmoid with logits clipped to `[-30,+30]` for the gradient; prediction is `logit > 0`. Inclusion weights do not affect training loss;
- Adam: `lr=0.001`, `beta1=0.9`, `beta2=0.999`, `epsilon=1e-8`; 200 epochs; batch size 2048; no shuffle; contiguous slices in frozen row order, final short batch retained;
- initialization follows the existing encoder: `np.random.default_rng(304000 + fold_index)`, `w1=standard_normal((input_width,128))*sqrt(2/input_width)`, zero `b1`, `w2=standard_normal((128,64))*sqrt(2/128)`, zero `b2`, `w3=standard_normal((64,1))*sqrt(2/64)`, zero `b3`, cast weights to float32 in that order. Fold indices are 0–3 for held-out blocks 303000–303003.

The environment identity is Python 3.13.15, NumPy 2.5.3, Windows x86_64, NumPy's reported scipy-openblas 0.3.34.106.0 build. Record full `numpy.show_config()`, executable hash, dependency versions, and BLAS/thread environment in the implementation receipt. Run one fitting process at a time and preserve the environment used to build these settings. B/C/D use identical 90D shape and the same per-fold seed, so their six initial tensors must be byte-identical; assert and record their hashes before fitting. A uses the deterministic 66D shape with the same fold seed and is descriptive only.

There are 16 fits: four scientific arms `(A,B,C,D)` × four held-out blocks. HIST is not fitted. In each fold, the training matrix preserves frozen global row order after removing held-out rows; each 2048-row minibatch is a contiguous slice of that order. The fit manifest records all row, order, normalizer, initial-tensor, source, and executable hashes before fit 1. Fit receipts record arm, fold, input width, train/held-out counts, training-row hash, order hash, normalization hash, initial/final tensor hashes, update count, finite status, and final prediction hash.

Tensor hashes use this canonical stream: tensor names `w1,b1,w2,b2,w3,b3` in that order, UTF-8 name plus NUL, rank as LE u32, each dimension as LE u32, then C-order little-endian float32 values. Hash the concatenation with SHA-256. Hash initial tensors before fitting and final tensors after epoch 200.

The fixed `FIT-MANIFEST.csv` header is `fit_id,arm,holdout_block,input_width,train_rows,heldout_rows,contract_sha256,source_manifest_sha256,implementation_executable_sha256,analysis_script_sha256,feature_hash,training_row_hash,training_order_hash,normalization_hash,initial_tensor_hash,expected_prediction_path`. Use UTF-8 without BOM, LF line endings, RFC 4180 quoting, and manifest rows in arm order `A,B,C,D`, then holdout block ascending; `fit_id` is `<arm>-H<holdout_block>`, receipt path is `fit-receipts/<fit_id>.json`, and prediction path is `heldout-predictions/<fit_id>.bin`. `feature_hash` is SHA-256 over all 13,420 normalized model-input rows in frozen global order, each row as C-order LE f32 values. `training_row_hash` hashes the concatenated 18-byte row keys sorted lexicographically by their raw bytes; `training_order_hash` hashes the same training keys in frozen global stream order after removing the held-out block. Fit receipts record those fields plus final tensor hash, update count (`200 * ceil(train_rows / 2048)`), finite status, prediction hash, and runtime seconds.

Each held-out prediction file has a 72-byte header: 16-byte magic `F4SYMPREDv1` followed by five NUL bytes; LE u32 version `1`; LE u64 held-out block; LE u32 arm ID (`A=0`, `B=1`, `C=2`, `D=3`); LE u64 prediction count; and the 32 raw bytes of the SHA-256 of that fit's exact `FIT-MANIFEST.csv` row, including its terminating LF. Each following 22-byte record is the 18-byte row key followed by one LE float32 logit. Records follow the held-out rows' frozen global stream order. The prediction-file SHA-256 is written in the fit receipt and independently rechecked before target truth is joined.

Freeze exact runtime environment from the preflight receipt. Record NumPy configuration and BLAS thread variables; do not silently change thread count, library, or compiler between preflight and fitting. If deterministic runtime replay changes any initial tensor, normalized feature byte, or repeat prediction byte under an identical frozen input, stop before comparative analysis.

## 8. Row and truth reconciliation

Build the expected eligible row-key table from the immutable F4-v3 streams, sorted by the stream/row order in §1. Independently replay the frozen native tasks and verify, for each expected key:

1. the same substrate/side/block/trial/coordinate exists once;
2. the same inclusion probability is present;
3. recomputed reference target sign and native proposed support satisfy the frozen U* eligibility rule;
4. the resulting row-key count and ordered-key SHA match the expected table exactly.

Reject missing, duplicate, extra, reordered, nonfinite, or mismatched records. Record row-key-set and ordered-row-key hashes separately. The new label/reference truth file must match the old target labels and inclusion probabilities byte for byte after key-join; reference values may be compared under the frozen source precision but are not predictors.

## 9. Pre-fit implementation gates

Run gates in this order, with one append-only gate receipt per stage:

1. **Authority/hash gate:** contract hash, source/input hash manifest, and runtime hashes match.
2. **Row gate:** all 13,420 row keys, labels, inclusion probabilities, and order reconcile exactly.
3. **Forward probability gate:** standalone `p_cj` agrees bitwise with ordinary `Sim::sample` probabilities on a fixed replay fixture: `fly:L`, block 303000, after native `begin_trial` at trial 0 and before `apply_delta`, all four cues and all posts. For each cue, clone that fixed state and call ordinary `sample(pattern)` on the clone. Use disposable clones so fixture calls cannot change native replay state. Failure disposition: `STOP_FORWARD_PROBABILITY_RECONCILIATION`.
4. **B determinism gate:** regenerate the projection matrix and B sidecars twice; require byte-identical hashes. Reconstruct every B sidecar element solely from normalized A and the frozen matrix; require bitwise equality and verify no forbidden key/data entered projection generation.
5. **C/D value gate:** check raw and normalized multiset equality on every row; failure disposition: `STOP_CANONICAL_SIDECAR_VALUE_DRIFT`.
6. **Cue representation gate:** define each permutation `pi` as mapping an old cue slot `c` to new slot `pi(c)`. On each fixture state, require `C'_{pi(c)} == C_c` tuple bytes for all four cues and D bytes to remain unchanged for all 24 permutations in S4. These are implementation gates.
7. **Cue target diagnostic:** separately recompute implemented reference vectors for each transformed task and record max absolute value difference, counts where the exact three-way sign in `{-1,0,+1}` changes, and counts where the thresholded target channel changes at `EPS`. No bitwise requirement for `g`; do not remove affected rows.
8. **Joint inversion representation gate:** invert all task label signs and action signs at fixed state. Require every tuple and D sidecar to remain byte-identical.
9. **Joint inversion target diagnostic:** independently recompute implemented reference vectors and record the same three numerical diagnostics as gate 7. Do not change row membership based on this diagnostic.

Fixture snapshots are `fly:L`, each block 303000–303003, trials `0,1,2,7,31,255`, captured after native `begin_trial`, after `proposed_delta_into`, and immediately before `apply_delta`. Cue relabeling covers all 24 permutations in S4 for every such snapshot and every KC-to-MB edge coordinate. Joint label/action inversion uses the same snapshots and coordinates. Fixture transforms alter only disposable task/simulator copies.

Complete steps 1–9 and write the combined pre-fit receipt before creating any fit. Steps 1–6 and 8 are hard implementation gates. Steps 7 and 9 are record-only target diagnostics: they impose no target-invariance threshold and never change row eligibility. Gates 6 and 8 test representation invariants; they do not assert that the actual floating reference target is exactly invariant.

## 10. Prediction lock, integrity, and scoring

During the 16 fits, logs may expose fit counts, hashes, finite status, runtime, and resource health. They must not expose arm-comparative error, margins, Psi, or C/D rankings.

Write held-out logits with row keys, arm, fold, float32 logit bytes, and fit-receipt hash. Write and hash all 16 prediction streams before joining held-out target/reference truth. The independent integrity pass requires exactly one fit per `(arm, heldout_block)`, exact expected row counts and keys, no duplicates/extras/missing predictions, finite tensors/logits/features, identical B/C/D initial tensor hashes within fold, successful gates, and unchanged source hashes.

After integrity passes, compute the following from the locked out-of-fold predictions and reconciled truth:

- pooled out-of-fold IPW-balanced error using `q=1/p_inclusion`, one half-weighted q-error rate per class; report unclipped and clipped `Omega_hat`;
- primary error differences `error_C-error_B` and `error_D-error_C`;
- blockwise signed margins with class-balanced q weights where both classes exist; for 303003, report only the one-class q-weighted `Y*logit` diagnostic and balanced error/observability as null;
- A/B-A descriptions and frozen secondary `Psi`/delivery metrics. For each arm's out-of-fold signs, plus native proposed signs and oracle reference signs, compute `m_i=abs(native_proposed_delta_i)`, `q_i=1/p_inclusion_i`, `A_w(s)=sum(q_i*m_i*abs(g_i)*1[s_i=sign(g_i)])/sum(q_i*m_i*abs(g_i))`, and `Psi(s)=2*A_w(s)-1`. For delivery, compute `u_tilde_i(s)=clamp(pre_weight_i + m_i*s_i, 0, 2)-pre_weight_i`; report the q-weighted common-population cosine `sum(q_i*u_tilde_i*g_i)/sqrt(sum(q_i*u_tilde_i^2)*sum(q_i*g_i^2))`, or `null` if either denominator norm is zero. These are local sidecars only and do not replace the C-B or D-C endpoint contrast.

The `RESULTS.md` readout order is fixed: HIST provenance note only; A's clean-baseline held-out result; `error_B-error_A` as the descriptive width/control contrast; primary `error_C-error_B`; primary `error_D-error_C`; blockwise signed-margin diagnostics; then the secondary polarity and delivery metrics. No later section may be presented before the preceding section is written.

The scorer has no denominator floor for a class-absent block. It must refuse to output a finite balanced error for a fold without both classes; pooled scoring is valid because the pooled out-of-fold set contains both classes. Store the analysis inputs and outputs as float64 for q-weighted summaries, while preserving source logits and per-row truth bytes for audit.

## 11. Required result tree and receipts

```text
artifacts/f4-symmetry-01/
  SOURCE-INPUT-MANIFEST.json
  IMPLEMENTATION-PREFLIGHT-RECEIPT.json
  FORWARD-P-RECONCILIATION-RECEIPT.json
  ROW-RECONCILIATION-RECEIPT.json
  REPRESENTATION-FIXTURE-RECEIPT.json
  TARGET-SYMMETRY-DIAGNOSTIC.json
  B-DETERMINISM-RECEIPT.json
  CD-MULTISET-RECEIPT.json
  RAW-PREDICTORS.bin
  RAW-SCORING-TRUTH.bin
  FIT-MANIFEST.csv
  normalization/
  fit-receipts/
  heldout-predictions/
  INTEGRITY-RECEIPT.json
  F4-SYMMETRY-01-ANALYSIS.json
  RESULTS.md
  F4-SYMMETRY-01-TERMINAL-RECEIPT.json
```

All JSON is UTF-8, sorted keys, two-space indentation, one trailing LF. All binary values are little-endian; source input hashes and row hashes are SHA-256. The terminal receipt names the controlling contract and hash, implementation/analysis hashes, runtime identity, expected and actual row/fit counts, all gate statuses, integrity status, primary contrasts, and the qualification-only/nonpromotion disposition. A failed gate writes its failed receipt and stops; it does not create replacement inputs or fits.

Required JSON fields are fixed as follows. The preflight receipt contains `schema`, `status`, controlling contract SHA, source-manifest SHA, runtime/source hashes, row/fit expectations, and `measured_namespace_created=false`. Every gate receipt contains `schema`, `gate_id`, `status`, expected/actual counts or hashes, the checked fixture/input identities, and first-mismatch details or `null`. The fit receipt contains `schema`, `fit_id`, `arm`, `holdout_block`, input width, train/held-out counts, contract/source-manifest/executable/analysis-script hashes, feature/training-row/training-order/normalization/initial-tensor hashes, final-tensor hash, update count, finite status, prediction SHA-256, and runtime seconds. The integrity receipt contains expected/actual fit and prediction counts, missing/duplicate/extra key counts, nonfinite counts, source-drift status, gate-status map, B/C/D paired-initialization status, `heldout_truth_state=SEALED`, and `status=PASS|FAIL`; it is written before analysis opens held-out truth. The terminal receipt additionally records `heldout_truth_opened_after_integrity`, implementation and analysis SHA-256 values, seed namespace `qualification-v2-only`, and explicit no-promotion/no-PHENO-change dispositions. The analysis JSON contains pooled OOF metrics for each arm, `error_B_minus_A`, primary `error_C_minus_B` and `error_D_minus_C`, per-block metrics with `null` for undefined balanced metrics, and secondary polarity/delivery metrics.

## 12. Scope

This specification freezes how to implement the qualification design. It authorizes no biological claim, measured REACH-03 execution, native learning change, PHENO reopening, or promotion. Do not change contract values while implementing; any ambiguity or mismatch returns to a versioned contract amendment before arm outcomes exist.
