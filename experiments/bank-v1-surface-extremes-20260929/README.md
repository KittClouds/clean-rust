# BANK-v1 230M Surface Extremes Sweep

Engineering-only capability allocation map for the pinned local LFM2.5-230M-Base checkpoint.

## Frozen experiment

- Inputs: full sealed BANK-v1 release; input rows include paired renderer variants.
- Backbone: frozen D:\phoenix-models\lfm2.5-230m-base-9d2be55, FP32, no generation or fine-tuning.
- One inference pass per input row stores seven primitive 1024-D views.
- Ten unique linear-readout surfaces are derived from the shared primitive cache.
- Every arm uses identical train-only Welford standardization, head definitions, AdamW settings, seed and epoch count.
- Input text alone enters the backbone. BANK bindings/goals/labels are used only to form supervised targets or score outputs.
- The 8 TEST partitions and S7/S8/S9 held-out renderer styles are reported separately.
- Protected TEST truth is opened only by score.py, after the aggregate all-surface prediction seal verifies.
- This is an engineering probe over synthetic BANK-v1, not external lexical-transport qualification.

## Readout vector

Decision (ACT/ASK/ABSTAIN), action type, 11 abstain reasons (GOAL_SATISFIED is not an abstention), NLI, entity-type set, relation-predicate set, transition/state-predicate set, evidence-predicate set, .

Structured facts are scored as typed predicate sets, exactly as represented by BANK-v1's protected labels. This readout does not claim full fact-graph reconstruction.

Paired renderer rows carry policy labels only. Policy heads train and score on those rows; other heads use only rows where BANK-v1 supplies their target.

## Surface list

1. Final transformer layer, final nonpadding token.
2. Final layer, attention-mask mean across tokens (including special tokens).
3. Final layer, first nonpadding token.
4-6. Each of the three preceding transformer layers, final token (the fourth-from-final arm is included; the final layer is arm 1).
7. Mean of the final-token vectors from the final four transformer layers.
8. Concatenated final-token and final-layer mean.
9. Concatenated midpoint-layer final token and final-layer final token; midpoint layer is 1 + num_layers // 2 in the hidden-state tuple.
10. Seeded 256-D Gaussian projection of the final-token vector.

The random projection is fixed and untrained. The surface arms are representation views, not independently tuned feature pipelines.

## Run

Use Python 3.13 with PyTorch CUDA and Transformers already installed:

    $exp = 'experiments/bank-v1-surface-extremes-20260929'
    $bank = 'C:\code land\clean-rust\experiments\ff-s15-bank-01\releases\BANK-v1'
    $model = 'D:\phoenix-models\lfm2.5-230m-base-9d2be55'
    $out = 'D:\phoenix-target-overgraph\bank-v1-surface-extremes-20260929'
    python "$exp\extract.py" --bank-root $bank --model $model --output $out --batch-size 64 --microbatch-size 32
    python "$exp\fit_predict.py" --bank-root $bank --model $model --output $out
    python "$exp\score.py" --bank-root $bank --output $out

Extraction checkpoints at batch boundaries. Preserve the output directory if interrupted; rerun the exact extraction command to resume. Do not alter its bank root, model, or batch contract mid-resume.

## Metamorphic reporting

BANK-v1's sealed G20 metamorphic checks are simulator/construction checks, not hidden-state model accuracy. The model-facing metamorphic measurement here is consistency across the bank's actual paired_world renderer rows: decision invariance and full typed-output invariance. These are consistency diagnostics, not correctness scores.
