# F4-BINDING-01 Stage B execution contract

**Identity:** `F4-BINDING-01-STAGE-B-PROSP-v0.1`  
**Status:** prospective confirmation continuation; Stage A is exploratory  
**Parent:** `F4-BINDING-01-STAGE-A-EXPLORATORY-v0.1`  
**Purpose:** test whether inference-time role-coordinate disruption degrades the frozen CΦ interface on fresh tasks.

## Frozen question and interventions

The primary contrast is the fixed pair swap versus intact. The fixed four-cycle is secondary. Each row uses one already-computed `H=(h0,h1,h2,h3)` and one unchanged trained CΦ readout. The 66D base, four 16D values, model parameters, normalizer, row, target, and inclusion probability are shared across conditions.

```text
intact   (0,1,2,3)
pair     (1,0,2,3)   primary
cycle    (1,2,3,0)   secondary
```

No refitting, weight averaging, selection among the 36 models, optimizer construction, gradient call, or φ recomputation per intervention is permitted. For each model and row, compute H once, hash it before scoring, run all three presentations, then verify that H and all eight parameter tensors retain their hashes.

## Fresh task panel

Generate exactly 24 independent 8,192-trial blocks, four per balanced two-positive/two-negative cue-label assignment, in the frozen assignment order `1100, 1010, 0110, 1001, 0101, 0011`. The mapping of four block ordinals to each assignment is deterministically shuffled from a domain-separated assignment seed before task materialization. Block IDs are `310000..310023`. Derive task, simulator, schedule, and bootstrap seeds under distinct Stage B domains. Use the frozen ordinary schedule generator and native task semantics.

There is no structural or outcome screening. Do not inspect reference values, target signs, margins, U* support, or model predictions when generating, retaining, or ordering tasks. Do not replace or reassign any block. Preserve all 432 substrate × side × block stream cells, including empty cells. The six-assignment equal-weight primary is non-evaluable if any assignment lacks either target polarity across its four blocks.

## Collection and frozen model panel

Run the existing native collector semantics with the Stage B task bank and the unchanged nine-substrate × two-side qualification panel. The native collector is read-only with respect to the existing graph lineage. Predictor and scoring-truth streams use the v3 binary row contract and key ordering. Freeze all collector and validator sources before task seeds are written.

Use exactly the 36 frozen CΦ fit identities in the parent `F4-PRESENTATION-03-EXECUTION-REPAIR-v0.1/FIT-MANIFEST.csv`. Bind every final tensor and normalizer by SHA-256. For every fresh row, evaluate the entire 36-model panel using each model's own normalizer. Average model-specific paired intervention effects only after computing each model's rowwise paired condition losses. Do not select or average weights.

## Frozen estimands

For each model and assignment, compute q-weighted class-balanced error for each condition over all rows in that assignment. The assignment effect is the model's intervention-minus-intact error. Average those paired model effects equally over the 36 fixed models. The primary aggregate is the equal-weight mean over the six assignment effects. Preserve the six effects individually. Per-block, substrate, side, and model diagnostics are secondary.

Use `q=1/p_inclusion` without trimming, capping, winsorization, or post-hoc normalization. Report raw q minimum, maximum, mean, sum, count, and ESS alongside every weighted result. Report Ψprop, its leverage ESS and top-1/5/20% shares, and delivery-aware alignment separately from classification. Trajectory endpoint capability is `NOT_MEASURED`.

Primary uncertainty is a paired cluster bootstrap with 10,000 draws. The uint64 PCG64 seed is the little-endian first eight bytes of `SHA256(BOOTSTRAP_DOMAIN || SHA256(ROOT_DOMAIN))`, where `BOOTSTRAP_DOMAIN = "F4-BINDING-01-STAGE-B/BOOTSTRAP-v0.1\\0"` and `ROOT_DOMAIN = "F4-BINDING-01-STAGE-B/ROOT-v1\\0"`. Within each of the six assignments, sample its four task blocks with replacement. Carry each sampled block's complete substrate × side × row × 36-model panel. Recompute class-balanced effects per model on the sampled rows, average the model effects, then give the six assignment effects equal weight. Report a two-sided 95% percentile interval. Rows, substrates, sides, and model evaluations are not independent bootstrap units.

Primary evidence for average role-binding dependence requires pair-swap mean ΔE > 0 and its 95% interval to exclude zero. Cycle is secondary and cannot rescue a failed primary. There is no minimum-effect threshold.

## Gates and truth handling

1. Before task-bank creation, replay the existing parent CΦ held-out states using the frozen Stage B inference path. The 4×16 φ outputs must match bitwise; float32 logits must differ by at most `1e-5` absolute per row and must preserve every zero-threshold sign decision. This replay uses predictor features and saved parent outputs only, never scoring truth. Record the arithmetic tolerance and observed maximum error in a task-free receipt.
2. Freeze executable, analysis, collector, task-generator, model-registry, and source/input hashes before task-bank creation.
3. Generate and seal the 24-task bank without outcomes.
4. Collect and seal the full native panel. Validate all 432 cells and binary stream/key parity before examining target values.
5. Freeze the inference manifest, produce all 36-model predictions for all three conditions, lock predictions, and pass independent integrity before opening scoring truth. Do this complete prediction surface regardless of later target support.
6. Only after integrity PASS, open scoring truth and calculate six-assignment target support. If any assignment lacks either class across its four blocks, retain the entire run and report `NOT_EVALUABLE_SUPPORT`; do not replace tasks, reweight survivors, or omit the locked predictions.
7. Score with the frozen analysis implementation and close with assignment-conditioned results. If a bootstrap draw lacks class support in any assignment, retain that draw as non-evaluable; if any of the 10,000 draws is non-evaluable, the primary percentile interval is undefined and the confirmatory decision is inconclusive.

Stage B is separate from the exploratory Stage A lineage. It cannot open a lesion atlas automatically and does not authorize calibration, measured REACH-03, controller work, PHENO, or biological promotion.

## Claim ceiling

A passing result supports only that inference-time role-coordinate binding is causally important to this trained CΦ interface under these fresh task and evaluation conditions. It does not establish intrinsic substrate necessity, universal assignment effects, or a biological mechanism.

```text
qualification_only = true
measured_reach03_authorized = false
biological_promotion = false
pheno_status = unchanged
```
