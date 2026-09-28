# F4-BINDING-01 Protocol

**Identity:** `F4-BINDING-01`  
**Working title:** Inference-Time Role-Coordinate Binding Test  
**Status:** protocol ready for implementation planning; execution unauthorized  
**Program:** Frozen Fabrique; engineering-only unless a later prospectively sealed identity states otherwise

## 1. Question and claim ceiling

**Primary question:** Does the frozen trained canonical CΦ readout depend causally on matching each already-computed transformed tuple representation to its canonical role coordinate?

The intervention occurs after the local map has produced the four vectors. It changes only which downstream coordinate receives each vector. It does not retrain the model, recalculate φ under each intervention, modify the 66D base, or change any model parameter.

A successful fresh confirmation can support:

> Inference-time role-coordinate binding is causally important to this trained CΦ interface under the tested task and evaluation distribution.

It cannot establish that the substrate intrinsically requires canonical coordinates. A different façade may recover capability without that requirement.

## 2. Frozen model and feature contract

The parent CΦ implementation is `experiments/fly-reach-03/f4-presentation-02-v2/cphi_model.py`, SHA-256 `d50521285235db36b062f9eda9a90eb4182a836e2ccb8ab292c04e9e74158099`. It sorts the four normalized six-field tuples using the frozen D ordering, applies the shared `6 → 16` φ transform, and concatenates the resulting four 16D outputs with the 66D base for the frozen readout `130 → 101 → 64 → 1`.

The frozen trained-model pool is exactly the 36 CΦ fits (`12 held-out-block folds × 3 initialization replicates`) listed by `arm=Cphi` in the parent `FIT-MANIFEST.csv`. Bind each model by its final-tensor hash in the parent integrity receipt. Bind normalizers, fit identities, inputs, and prediction lineage through:

- fit-manifest SHA-256 `f71d344c5bc58e86a68e7bd9163aed1ab5d945468bfe84f06a8981e6a1c2ce66`;
- prediction-lock SHA-256 `dd387bcc52510eac947774cb6d9303d8cdd8142cee07a60b0e39cddd4dcb54ce`;
- integrity-receipt SHA-256 `cf52cc787b3bf501b3f80944d452af3247e569f82f110c06c597e499bfca2591`;
- parent analysis SHA-256 `d79f885d3d8b8bef0579312cc72c2b5c8fa08b6edb1fcf52b66bcf5abf1b51c5`.

For the existing-bank analysis, use each block's corresponding out-of-fold CΦ fit and its three initialization replicates. Existing `heldout-state/Cphi-H{block}-I{replicate}.npz` files contain `phi_outputs` with shape `(rows, 4, 16)`, `relational_concat`, and intact logits. Verify artifact hashes before use. For prospective evaluation, use all 36 frozen CΦ model bundles; use each bundle's own frozen normalizer. No weight averaging, fine-tuning, refitting, or selection among models is allowed. Every fresh row is evaluated by the same 36-model panel, with model effects averaged only after rowwise paired intervention scoring.

## 3. Exact intervention definitions

Let `H` be the already-computed float32 tensor of shape `(N, 4, 16)`. Slots are the D-canonical tuple order and are indexed `1..4` in prose (`0..3` in arrays). Define permutation convention as:

\[
H'[:,j,:]=H[:,\pi_j,:]
\]

where `π` lists the original source slot for each destination slot. `H` is immutable; construct a separate contiguous intervention buffer. For each buffer, keep the row's 66D base unchanged, flatten the presented `(4,16)` tensor in C order, concatenate `[base; H'.reshape(64)]`, and evaluate the already-trained `ρ` readout.

| Condition | Frozen source-slot vector `π` | Meaning |
|---|---|---|
| Intact control | `(0,1,2,3)` | `(h1,h2,h3,h4)` |
| Fixed pair swap | `(1,0,2,3)` | `(h2,h1,h3,h4)`; primary intervention |
| Fixed all-slot 4-cycle | `(1,2,3,0)` | `(h2,h3,h4,h1)`; secondary intervention |

These permutations are fixed here, before any new Stage-A or Stage-B intervention scores are examined. The all-slot cycle moves every vector and is nonidentity. No search over permutations is allowed.

No value-only matched control is included. A role-preserving cross-row donor operation would change row-level feature/state coherence and would not match the within-row perturbation severity of a swap; it is not a clean matched control under this contract. Do not add it after seeing results.

## 4. Stage A — existing-bank exploratory anatomy

Stage A is explicitly `EXPLORATORY_EXISTING_BANK_ANALYSIS_ONLY`. It uses the already-open F4-PRESENTATION-03 panel and is post-selection: CΦ was nominated using these outcomes, and truth access occurred during the prior analysis lineage. It cannot establish general causal necessity, promote a theory claim, or authorize Stage B automatically.

For each existing held-out block and replicate:

1. Load the frozen CΦ out-of-fold final tensors, normalization identity, saved canonical `phi_outputs`, row keys, and intact predictions.
2. Rehash every input; verify the 36 fit identities and the selected out-of-fold model mapping.
3. Run only the frozen readout `ρ` on intact `H`, pair-swapped `H'`, and cycled `H'`. Do not call φ in intervention branches. No optimizer, gradient, update, fit, or native-learning call is permitted.
4. Require intact recomputation to reproduce the saved intact logits within the implementation-frozen tolerance; if reproducible deterministically, require byte equality. Stop on mismatch.
5. Score the three paired conditions on the existing rows. Label every result exploratory and post-selection.

Stage A is for checking mechanics, estimating the effect scale, and seeing whether disruption looks catastrophic, selective, or negligible. It is not a promotion gate. No execution is authorized by this protocol document.

## 5. Stage B — prospective confirmation plan

If a later explicit decision opens confirmation, create a new identity and use a genuinely fresh task/evaluation bank. Proposed fixed coverage is **24 independent task blocks: four per each of the six balanced cue-label assignments**, with the same frozen task generator and 8,192-trial budget per block. Assignment and all task/simulator/schedule seeds must be fixed before collection. Generate the complete task bank without inspecting `Y`, `g`, predictions, target margins, U* support, or model outcomes. Do not replace, reassign, or seed-shop blocks. If an assignment lacks both target polarities across its four blocks, the equal-weight six-assignment primary aggregate is non-evaluable; retain all cells and do not reweight the surviving assignments.

Collect the full frozen substrate-side panel (nine substrates × two sides) for all 24 blocks, producing 432 cell records. Keep empty cells as explicit rows with generated trials, eligible/sampled counts, assignment, class support, substrate, block, side, and seed-domain identities. Use the frozen U* construction and inclusion probabilities. Do not fit CΦ again. Evaluate every fresh row with all 36 frozen CΦ model bundles, using each model's own normalizer and φ tensors. For each model-row, compute H once, hash it, and reuse that exact H for all three presentation conditions. Average the model panel only after the paired per-model/per-row scoring is formed.

The fresh bank, collection, implementation and analysis source hashes, model registry, and all stopping rules must be sealed before model inference or outcome opening. This document does not itself authorize creating that bank or running that inference.

## 6. Assignment-conditioned metric schema

Assignment order is fixed as `1100, 1010, 0110, 1001, 0101, 0011`. For every intervention, retain the full vector:

\[
F_L=[\Delta E_{1100},\Delta E_{1010},\Delta E_{0110},
\Delta E_{1001},\Delta E_{0101},\Delta E_{0011}],
\]

where `ΔE = E_intervention − E_intact`; positive values mean increased balanced error after role disruption. Primary aggregation is an equal-weight mean of the six assignment-specific scores. Within each assignment, use inverse inclusion weights `q=1/p` inside each target class, then class-balance. If an assignment lacks a polarity, report its score as null and the six-assignment aggregate as non-evaluable. No assignment replacement, survivor reweighting, or pooled-score override is allowed.

The row and summary schema must keep these quantities distinct:

| Measure | Required fields |
|---|---|
| Classification / fixed readout endpoint | rows, positive/negative counts, q-weighted class-balanced error, signed margin, mean absolute logit; per block and assignment |
| q-weight diagnostics | min, max, mean, sum, ESS, count; overall and by assignment/block/class; ESS descriptive, no weight trimming/capping/normalization |
| Proposed alignment `Ψprop` | frozen candidate sign from intervention logit, q·m·|g| weighted agreement and Ψ; leverage ESS and top-1/5/20% shares |
| Delivery-aware alignment | clamp-aware η-delivery using the frozen preweight, native magnitude, and reference vector; q is context only if the frozen contract defines an unweighted cosine |
| Trajectory endpoint capability | `NOT_MEASURED`: inference-time readout interventions do not alter weights or run trajectories |

Classification, Ψprop, η-delivery, and trajectory endpoint capability are never combined into a composite. Ψprop is not broad accuracy; always report leverage concentration. The q-diagnostics ESS is separate from leverage ESS.

For the block/assignment phenotype, report counts and paired intervention-minus-intact effects by assignment, block, substrate, side, and model replicate. Report each assignment's ΔE and its class support, signed-margin delta, logit-magnitude delta, Ψprop delta with leverage concentration, and delivery-alignment delta. Global averages are secondary; do not call an average uniform when assignment effects differ.

## 7. Prospective analysis and decision rules

For Stage B, the fixed pair swap is the sole primary intervention. Estimate the equal-weight six-assignment mean of paired ΔE. Quantify uncertainty by a paired cluster bootstrap over independent task blocks, resampling blocks within each assignment and carrying each sampled block's complete substrate × side × row × frozen-model panel together. Use 10,000 draws and a domain-separated bootstrap seed frozen before task generation. Report a two-sided 95% percentile interval; do not treat rows, substrates, sides, or model evaluations of the same block as independent task replicates.

The all-slot 4-cycle is a prespecified secondary intervention, analyzed and reported in the same way. Assignment-specific effects and heterogeneity remain mandatory. Evidence for average causal role-binding dependence requires the pair-swap mean ΔE to be positive and its 95% interval to exclude zero. If this rule is not met, the confirmation is inconclusive or does not support average degradation, according to the estimate and interval. The cycle cannot rescue a failed primary pair-swap rule. Neither outcome establishes intrinsic substrate necessity or a uniform assignment effect. There is no additional minimum-effect threshold in this protocol; practical magnitude and interval are reported transparently rather than selected after results.

## 8. Integrity and immutability plan

Before any intervention scoring, create and seal a source/model/input manifest containing:

- parent terminal, fit-manifest, prediction-lock, integrity-receipt, task-bank, collection, and analysis hashes;
- exact 36 CΦ fit IDs, final-tensor hashes, and normalizer hashes;
- raw row-key and H source hashes for each fit/block; H shape, dtype, and canonical slot order;
- model implementation, intervention runner, metric code, and test source hashes;
- fresh task-bank and collection hashes for Stage B;
- prediction/output schemas and expected counts.

For every fit/model-row panel, require:

1. all four tensors in H are finite float32 arrays with shape `(N,4,16)` and the declared canonical slot order;
2. H is hashed before evaluation and rehashed after all arms; the original H bytes are unchanged;
3. each transformed input buffer is separately identified by its intervention permutation and hash;
4. every trained CΦ parameter tensor is hashed before and after all interventions; all eight named tensors (`phi.w`, `phi.b`, `rho1.w`, `rho1.b`, `rho2.w`, `rho2.b`, `rho3.w`, `rho3.b`) remain byte-identical;
5. optimizer state is not instantiated or mutated; no gradient/update API is called;
6. intact output reproduces the frozen logits under the locked tolerance;
7. all conditions use the same row keys, base values, target rows, inclusion probabilities, task assignment, and model parameters;
8. there are no missing, duplicate, extra, NaN, or infinite rows/logits; the D/CΦ experiment artifacts remain untouched.

Any mismatch stops the identity before scoring. Preserve failed receipts; do not repair the same identity after outcomes are opened.

## 9. Stop rules and authorization

Stop before scoring on parent-hash drift, missing model tensors, normalizer mismatch, H/order mismatch, intact-logit replay failure, row-key mismatch, target leakage, nonfinite output, or parameter/input mutation. Preserve all generated collection cells, including empty cells. Failed class support makes the affected block score null; failed assignment support makes the primary equal-weight aggregate non-evaluable. No replacement or reweighting is allowed.

`F4-BINDING-01` execution is not authorized by this protocol. Stage A requires a separate execution instruction; Stage B requires a new prospective identity with frozen implementation/analysis hashes and explicit authorization. A positive Stage A finding cannot automatically open Stage B, a lesion atlas, calibration, measured REACH-03, controller work, PHENO, or biological promotion.

## 10. Protocol flags

```text
F4_BINDING_01_PROTOCOL_READY = true
F4_BINDING_01_EXECUTION_AUTHORIZED = false
STAGE_A_EXECUTED = false
STAGE_B_TASK_BANK_CREATED = false
MODEL_FITTING_AUTHORIZED = false
BIOLOGICAL_PROMOTION = false
```
