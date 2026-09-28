# F4-PRESENTATION-03 Engineering Screen v0.1

**Status:** `SEALED_ENGINEERING_ONLY`  
**Purpose:** Fresh-block comparison of raw and factorized canonical tuple architectures.  
**Execution state:** No task IDs, task seeds, task bank, native collection, fits, or result namespace have been created.  
**Promotion boundary:** Engineering evidence only. This does not authorize F4 calibration, measured REACH-03, a controller experiment, PHENO, or biological promotion.

## Authority and lineage

This screen follows the completed F4-PRESENTATION-02 CΦ engineering screen. The earlier identity remains descriptive engineering evidence on a reused panel with prior held-out truth access. Its archived scientific disposition remains `NOT_EVALUABLE_SUPPORT`.

Frozen implementation anchors inspected for this draft:

| Artifact | SHA-256 |
| --- | --- |
| CΦ model source `cphi_model.py` | `d50521285235db36b062f9eda9a90eb4182a836e2ccb8ab292c04e9e74158099` |
| D/S model source `f4_invariant_01_model.py` | `2882482311355f5729fb3922d0b51fdef960f24a49d793a77ce855d903939f02` |
| CΦ v2 source manifest | `b4798ced6fa806abae373ea1daa05f477b23fcf127d5aa4e2e7e3880887b2041` |
| CΦ v2 terminal receipt | `754dd444fe408fd0001eeB0DC20EA36D2B255620BE70909181010B06BAE77EEC` |

Immediately before implementation freeze, the executor must rehash each referenced source and the complete CΦ v2 input/output lineage it consumes. These values identify the observed artifacts; they do not replace the run-time preflight.

## Question

Does the CΦ gain on the reused panel transfer to fresh task blocks, and does it depend on shared local tuple processing and stable canonical slot presentation?

The comparison is engineering-only. The primary endpoint is the frozen 200-epoch model. Checkpoints are descriptive diagnostics and cannot select a checkpoint for this identity.

## Frozen architecture arms

All arms receive the same fold-normalized 66D admissible base and the same four normalized six-field tuple values before arm-specific processing. No expected-score intermediate, reference value, target, or scoring field is an input feature.

### D — raw canonical baseline

Apply the frozen D tuple sort and concatenate the four raw six-field tuples with the 66D base. Use the existing D readout and training semantics. Retrain D on the fresh panel; do not reuse its old-panel predictions as fresh-panel results.

### CΦ — shared local map, canonical composition

Apply the exact frozen CΦ implementation: D-canonicalize the raw tuples; apply one shared `6 → 16` map to each tuple; concatenate the four outputs in canonical order; concatenate with the 66D base; use the frozen `130 → 101 → 64 → 1` readout. Preserve the existing initializer, float operation order, optimizer, learning rate, batch size, row traversal, and 200-epoch schedule.

### CΦ-unshared — slot-specific local maps, canonical composition

Use four separately trainable `6 → 16` maps, one for each D-canonical tuple position, followed by the same concatenation and readout dimensions as CΦ. At initialization, copy the frozen CΦ φ tensors into all four maps, so all slot maps implement the same function at step zero. Their optimizer moments and updates are independent thereafter. The resulting parameter count is 20,272, 336 parameters above CΦ and 303 above D (about 1.5% of D's count); no width is adjusted to force exact equality.

This arm tests whether shared local parameterization contributes beyond canonical composition.

### CΦ-shuffled — shared local map, row-wise shuffled presentation

Use the exact CΦ computation and initialization, then apply a deterministic row-keyed random permutation to the four 16D tuple outputs before concatenation. The permutation is fixed per row, independent of task outcome, target, and reference values. The 66D base remains unchanged.

The permutation generator, row-key encoding, and seed derivation must be frozen before task generation. The operation shuffles only the CΦ sidecar; it does not remove absolute cue-slot information already present in the base. This arm tests the value of stable canonical alignment for the processed sidecar under the fixed base.

### Parameter counts

| Arm | Parameter count |
| --- | ---: |
| D | 19,969 |
| CΦ | 19,936 |
| CΦ-unshared | 20,272 |
| CΦ-shuffled | 19,936 |

## Task-panel proposal

Generate 12 fresh task blocks, each retaining the ordinary 8,192-trial schedule budget. The six possible balanced four-cue label assignments are the six subsets of two positive cue labels from four cue slots. Assign exactly two independent blocks to each assignment using a frozen task-independent mapping. The assignment and all task/simulator/schedule seeds are fixed before collection.

The block IDs are fixed as `309000` through `309011`; implementation preflight verifies no collision before they are reserved. The seed namespaces are domain-separated for assignment mapping, task pattern, simulator, and schedule. Each block has distinct task-pattern, simulator, and schedule seeds; the collector uses the task-pattern seed for `Task::new` and the simulator seed for `Sim::new`. The task generator must preserve its ordinary schedule semantics within each declared assignment.

There is no structural or outcome screening, no target/reference inspection during task creation, no seed shopping, and no replacement. If an output target class is absent after collection, record that support result; do not modify the bank. Balancing cue-label assignments is a generator-condition control and is not a guarantee that every scored `U*` stratum contains both target polarities.

Each leave-one-block-out fold holds out one complete block. The training panel is the other 11 blocks. The assignment remains present in training through its second independently generated block; this is a fresh-world transfer test conditional on balanced assignment coverage, not a leave-one-assignment-out test.

## Fit surface and training support

The planned fit surface is:

```text
12 held-out blocks × 3 initialization replicates × 4 arms = 144 fits
```

Before fit 1, every leave-one-block-out training partition must be nonempty and contain both target classes. If any training fold is degenerate, stop before fitting and preserve the task/collection identity. Held-out support does not remove folds or alter the 144-fit surface.

Use the frozen 200-epoch schedule for all arms. CΦ and CΦ-shuffled use byte-identical initial tensors per fold and replicate. CΦ-unshared starts from four copies of CΦ's φ initialization and the same readout tensors. D uses its frozen D initializer semantics. Task identity is not included in model initialization.

## Checkpoint instrumentation

For all four arms, retain model snapshots at epochs:

```text
1, 2, 4, 8, 16, 32, 64, 128, 200
```

Record epoch training BCE, unweighted training balanced error, per-layer gradient norms, and finite-state status. Generate held-out checkpoint logits only after each fit has completed; score them after the full fit surface exists. Epoch 200 is the only primary endpoint. Checkpoint comparisons are descriptive, do not trigger early stopping, and cannot replace the epoch-200 model in this identity.

Retain final tensors, checkpoint tensor hashes, per-layer optimizer summaries, and held-out diagnostics needed to recover four φ outputs, the 64D concatenated state, the pre-output hidden state, and per-row role separation. For each row, record all six pairwise distances among its four 16D φ outputs and their mean. Any post-hoc sum-state or collision diagnostic must be explicitly labeled as a representation diagnostic; it cannot establish that S's learned state collided because S is not refit here.

## Scoring and contrasts

The truth stream stores the inclusion probability (p_j^{\mathrm{incl}}). Scoring derives (q_j=1/p_j^{\mathrm{incl}}) and uses it inside each target class before class balancing. This follows the authoritative REACH-03 math contract; archived helper outputs that treated the stored (p) value itself as (q) are not directly comparable. Score the frozen `U*` rows with these reciprocal-inclusion weights. Report each block's class counts, weighted balanced error (or `null` for a one-class block), signed margin, logit magnitude, and all four arms' paired differences.

The primary endpoint is epoch-200 weighted balanced error, first reported per replicate and then as an equal-weight mean over initialization replicates. Report pooled row-weighted balanced error as a secondary statistic.

Report assignment-specific scores by pooling the two held-out blocks for each of the six cue-label assignments, applying the class-balanced IPW score within assignment, then giving each assignment equal weight in the stratified aggregate. Never weight an assignment by its row count in that aggregate. Also report the two constituent block results separately. If an assignment lacks either target class across its two blocks, its assignment score is `null`; the full six-assignment aggregate is `null` unless all six are evaluable. Do not silently reweight over only the surviving assignments.

The controlling contrasts are:

1. `CΦ − D`: fresh-panel transfer of the CΦ package versus the raw canonical baseline.
2. `CΦ − CΦ-unshared`: contribution of shared local tuple processing under canonical composition.
3. `CΦ − CΦ-shuffled`: contribution of stable canonical slot alignment for the processed sidecar.

For each contrast report equal-replicate mean, all three replicate values, all assignment-specific values, and blockwise values. A negative error difference favors the first arm named in the contrast. Do not treat the CΦ-unshared/CΦ-shuffled contrasts as isolated proof of a biological or general architectural mechanism.

For the engineering nomination rule, CΦ remains the leading candidate only if all six assignment strata are evaluable, its equal-assignment epoch-200 balanced error is lower than D's, it wins pooled epoch-200 error in at least two of three initialization replicates, and it wins in at least four of six assignment-specific comparisons. Otherwise close or retain it as descriptive according to the observed result; do not repair support by replacing blocks.

The sharing and canonical-alignment contrasts are interpreted as descriptive component probes. Their signs and consistency are reported without overriding a failed CΦ-versus-D nomination gate.

## Leverage and polarity reporting

If capability-weighted polarity `Ψ` is reported, accompany it with leverage effective sample size and top 1%, 5%, and 20% leverage mass. Use (q_jm_j|g_j|) as the leverage weight. Compute delivery alignment as the declared cosine of the delivered update and reference vector over the selected `U*` rows; do not reuse (q_j) inside this cosine. Keep ordinary classification error, signed-margin orientation, `Ψ`, and delivery-aware alignment as separate measures. No one measure substitutes for another.

## Freeze sequence and stop rules

1. Freeze this contract, the six-assignment mapping, and all scoring semantics before task generation.
2. Implement the four-arm runner, keyed row permutation, checkpoint capture, analysis, and integrity checks without creating task IDs or seeds.
3. Run task-independent synthetic/operation-order and deterministic replay fixtures; freeze all source/runtime hashes and initializer manifests.
4. Generate exactly the 12-block assignment-balanced task bank and immediately seal its manifest. Do not inspect `U*`, target signs, reference values, or predictions to choose tasks.
5. Collect the native panel; reconcile common raw and normalized base/tuple bytes across arms.
6. Check training support. If valid, freeze the 144-fit manifest and run all 144 fits, regardless of held-out support.
7. Lock predictions and pass independent integrity before scoring.
8. Score the fixed epoch-200 primary endpoint, then the frozen checkpoint diagnostics and secondary measures.
9. Write a terminal receipt preserving task, collection, fit, prediction, analysis, and source hashes.

Stop on source/contract mismatch, task namespace collision, feature leakage, cross-arm input mismatch, nondeterministic row permutation, model-semantic drift, training-fold class failure, missing fits/predictions, nonfinite outputs, or integrity failure. No stop is repaired in place after task creation.

## Claim and authorization limits

This is a fresh engineering screen. A positive result would support only the tested architecture package under this generator distribution and training budget. It would not establish that shared abstraction, canonical ordering, or either component is universally superior; it would not pass the learned-F4 calibration gate or authorize measured REACH-03, controller work, PHENO, or biological promotion.

This contract is the authority for task-bank, collection, fit, and analysis construction. Task generation remains blocked until the implementation preflight and source freeze pass.
