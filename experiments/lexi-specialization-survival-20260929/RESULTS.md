# Lexi specialization survival: NER and NLI

Engineering result on the locked BANK-v1 Rung-0 atlas. BANK is an evaluation ruler; the external NER/NLI data trained the specialization arms. The old observers were applied unchanged, then the same linear observer family was refit on BANK TRAIN only. Rung 0 and its cached scores remain unchanged.

## Specialization acquired

| Arm | Frozen-backbone control | Late-layer LoRA | Task result |
|---|---:|---:|---|
| English NER (OpenNER) | span F1 0.2058, 250 steps | span F1 0.2619, 500 steps | Test span F1 improved by 0.0561. |
| NLI (MNLI) | matched/mismatched accuracy 0.3940/0.4043; macro-F1 0.3825/0.3974 | matched/mismatched accuracy 0.6140/0.6354; macro-F1 0.5989/0.6224 | Validation performance improved in both MNLI splits. |

Both LoRA arms use rank 8, alpha 16, with q/v projections in the last four full-attention layers. The arms start from the same 230M Base checkpoint and were trained separately. No joint training or full-model fine-tuning was used.

## BANK atlas survival

Each triple is **Base / unchanged old head / BANK-TRAIN refit head**. The final column is route exactness on held renderer families S7/S8/S9 for the refit head. Scores are canonical TEST worlds; first-token is retained only as the locked dead control.

### NER-specialized backbone

| Locked surface | Route exact | Decision macro-F1 | Abstain-reason macro-F1 | NLI macro-F1 | Held renderer route exact, refit |
|---|---:|---:|---:|---:|---:|
| middle + final | 0.4328 / 0.2773 / 0.4163 | 0.4981 / 0.3928 / 0.4868 | 0.3246 / 0.2815 / 0.3199 | 0.6299 / 0.2145 / 0.6441 | 0.2335 |
| final + mean | 0.4013 / 0.2190 / 0.4044 | 0.4977 / 0.3263 / 0.5141 | 0.3515 / 0.2354 / 0.3379 | 0.5917 / 0.3549 / 0.5865 | 0.2065 |
| layer −4 | 0.4072 / 0.2346 / 0.4092 | 0.4710 / 0.2503 / 0.4759 | 0.3184 / 0.2083 / 0.3212 | 0.6182 / 0.2667 / 0.6163 | 0.2724 |
| full mean | 0.3403 / 0.2328 / 0.3448 | 0.4448 / 0.2491 / 0.4570 | 0.3184 / 0.2053 / 0.3149 | 0.5460 / 0.4851 / 0.5528 | 0.2184 |
| first token (control) | 0.1839 / 0.1346 / 0.1861 | 0.3100 / 0.1810 / 0.3158 | 0.0571 / 0.0571 / 0.0571 | 0.2837 / 0.2837 / 0.2837 | 0.1809 |

### NLI-specialized backbone

| Locked surface | Route exact | Decision macro-F1 | Abstain-reason macro-F1 | NLI macro-F1 | Held renderer route exact, refit |
|---|---:|---:|---:|---:|---:|
| middle + final | 0.4328 / 0.3333 / 0.4322 | 0.4981 / 0.4639 / 0.4973 | 0.3246 / 0.3085 / 0.3264 | 0.6299 / 0.2838 / 0.6216 | 0.2563 |
| final + mean | 0.4013 / 0.2557 / 0.3970 | 0.4977 / 0.3731 / 0.4883 | 0.3515 / 0.2732 / 0.3324 | 0.5917 / 0.3553 / 0.5648 | 0.1719 |
| layer −4 | 0.4072 / 0.2360 / 0.4179 | 0.4710 / 0.3812 / 0.4783 | 0.3184 / 0.2444 / 0.3285 | 0.6182 / 0.2235 / 0.6404 | 0.2798 |
| full mean | 0.3403 / 0.2634 / 0.3477 | 0.4448 / 0.2634 / 0.4526 | 0.3184 / 0.2795 / 0.3213 | 0.5460 / 0.4959 / 0.5143 | 0.1921 |
| first token (control) | 0.1839 / 0.1779 / 0.1875 | 0.3100 / 0.1810 / 0.3318 | 0.0571 / 0.0571 / 0.0571 | 0.2837 / 0.2837 / 0.2837 | 0.1583 |

## Graph-local sentinel

The original Rung-1 edge-existence head and scaler were frozen. Only its local entity vectors changed.

| Backbone | TEST aggregate AUC | Held S7/S8/S9 AUC | Base reference |
|---|---:|---:|---:|
| Base | 0.9819 | 0.9553 | — |
| NER-specialized | 0.9706 | 0.9406 | modest reduction; strong signal retained |
| NLI-specialized | 0.9716 | 0.9452 | modest reduction; strong signal retained |

## Readout

Both specializations acquired their target capability and shifted the frozen coordinates. On the four locked surfaces, the unchanged observers often lost substantial performance; refitted linear observers recovered most of the base route/decision performance. This is predominantly **ROTATED** in the operational sense used by the plan, rather than evidence that the information disappeared. NLI specialization also improved NLI macro-F1 on layer −4 after refitting (0.6404 versus the 0.6182 base score).

The edge-existence sentinel remained strong in both arms, with small declines in aggregate and held-renderer AUC. That is compatible with preservation under both local/span and global-relational specialization, but renderer transfer remains weaker than canonical TEST: refit route exactness on S7/S8/S9 ranges from 0.1719 to 0.2798 for the five NLI-arm surfaces. Treat that as a robustness limitation, not a universal survival pass.

The first-token control remains uninformative. No new surface search, backbone-wide tuning, retrieval run, authority update, or attention-head intervention was performed. The next planned rung is head/group masking on the base, NER-specialized, and NLI-specialized backbones, using these frozen capability readouts.

## Receipts and verification

- L-S0 lock: `L-S0-lock.json`; verifier reports `L_S0_VERIFIED`.
- NER task run: `D:\phoenix-target-overgraph\lexi-specialization-survival-20260929\runs\ner-late-lora-r8-500`.
- NLI task run: `D:\phoenix-target-overgraph\lexi-specialization-survival-20260929\runs\nli-late-lora-r8-500`.
- NER atlas and sentinel: `D:\phoenix-target-overgraph\lexi-specialization-survival-20260929\scored\ner-step500-atlas` and `...\ner-step500-edge-sentinel`.
- NLI atlas and sentinel: `D:\phoenix-target-overgraph\lexi-specialization-survival-20260929\scored\nli-step500-atlas` and `...\nli-step500-edge-sentinel`.
- Prediction manifests seal all 215,996-row feature sets before truth joins; the score receipts record the post-seal BANK evaluation.
- Verification: five unit tests pass; the specialization scripts compile; the Rung-0 lock verifies.
