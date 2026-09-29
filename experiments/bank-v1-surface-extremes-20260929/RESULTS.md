# BANK-v1 230M Surface Extremes Sweep — Results

**Disposition:** completed engineering capability-allocation sweep. These results do not qualify lexical transport or serving.

## Run identity

- BANK-v1 input rows: 215,996 (143,996 TRAIN; 24,000 DEV; 48,000 test-renderer rows across eight test partitions).
- Test scoring: 40,000 primary worlds plus 8,000 paired renderer variants.
- Backbone: frozen LFM2.5-230M-Base at `D:\phoenix-models\lfm2.5-230m-base-9d2be55`; FP32, no generation or fine-tuning; 14 layers, hidden size 1,024.
- Extraction: one pass for all rows, 64-row checkpoint groups / 32-row forward microbatches; single-vs-batch parity checked at max absolute tolerance `2e-4`.
- Every surface used the same train-only standardization, typed linear heads, AdamW settings (8 epochs, batch 2,048, learning rate `1e-3`, weight decay `1e-4`) and seed `20260929`.
- Protected test labels were read only after all ten prediction artifacts and the aggregate prediction seal verified.

## Capability map

Metrics are on primary BANK-v1 test worlds unless noted. Decision macro-F1 is the unweighted mean over ACT, ASK and ABSTAIN. Route exactness checks the available decision/route bundle; all-head exactness requires every scored BANK head to match.

| Surface | Decision accuracy | Decision macro-F1 | ACT recall | ASK recall | ABSTAIN recall | Route exact | All-head exact | NLI macro-F1 | Abstain-reason macro-F1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Final token | 0.6389 | 0.4688 | 0.6214 | 0.0950 | 0.6979 | 0.3884 | 0.0709 | 0.5930 | 0.2985 |
| Full token mean | 0.6278 | 0.4448 | 0.4527 | 0.0757 | **0.7894** | 0.3403 | 0.0618 | 0.5460 | 0.3184 |
| First token | 0.4533 | 0.3100 | 0.6194 | 0.0000 | 0.3857 | 0.1839 | 0.0017 | 0.2837 | 0.0571 |
| Layer −4 final token | 0.6393 | 0.4710 | 0.5947 | 0.1103 | 0.7146 | 0.4072 | 0.0647 | **0.6182** | 0.3184 |
| Layer −3 final token | 0.6453 | 0.4690 | 0.6072 | 0.0836 | 0.7193 | 0.3999 | 0.0551 | 0.6003 | 0.3072 |
| Layer −2 final token | 0.6376 | 0.4697 | 0.6213 | 0.1024 | 0.6950 | 0.3928 | 0.0698 | 0.5870 | 0.3068 |
| Mean of last four final-token states | 0.6373 | 0.4687 | 0.6237 | 0.0984 | 0.6933 | 0.3905 | 0.0708 | 0.5929 | 0.2997 |
| Final token + full mean | **0.6659** | 0.4977 | 0.5517 | 0.1162 | 0.7879 | 0.4013 | 0.0795 | 0.5917 | **0.3515** |
| Midpoint + final token | 0.6644 | **0.4981** | **0.6709** | **0.1306** | 0.7070 | **0.4328** | **0.0862** | 0.6299 | 0.3246 |
| Fixed 256-D random projection | 0.6193 | 0.4227 | 0.5231 | 0.0213 | 0.7340 | 0.3298 | 0.0497 | 0.5061 | 0.2723 |

The two concatenations are the strongest overall decision surfaces, but the result is not a universal winner: full mean is strongest on ABSTAIN recall, layer −4 on NLI accuracy (0.7919), and different surfaces lead different held-out test partitions. ASK remains the weakest decision class; even the best ASK recall is 0.1306. Route exactness tops out at 0.4328, so this is a capability map, not a successful end-to-end policy result.

The other typed heads also move independently across surfaces. The table shows action-type macro-F1 and micro/macro-F1 for the four multi-label heads; micro-F1 can look high when common labels dominate, so the macro values matter too.

| Surface | Action macro-F1 | Entity micro / macro | Relation micro / macro | State micro / macro | Evidence micro / macro |
|---|---:|---:|---:|---:|---:|
| Final token | 0.5879 | 0.8879 / 0.6670 | 0.8711 / 0.8151 | 0.8740 / 0.8192 | 0.5740 / 0.4284 |
| Full token mean | 0.4688 | 0.8298 / 0.6292 | 0.8242 / 0.8145 | 0.8527 / 0.8181 | 0.4809 / 0.4137 |
| First token | 0.1760 | 0.9697 / 0.6667 | 0.7452 / 0.3971 | 0.7452 / 0.3971 | 0.6233 / 0.1846 |
| Layer −4 final token | 0.6109 | 0.9123 / 0.6854 | 0.8668 / 0.7817 | 0.8683 / 0.7822 | 0.6383 / 0.4574 |
| Layer −3 final token | 0.6133 | **0.9158** / **0.6857** | 0.8663 / 0.7758 | 0.8676 / 0.7769 | **0.6386** / 0.4542 |
| Layer −2 final token | 0.5859 | 0.8816 / 0.6650 | 0.8602 / 0.8091 | 0.8659 / 0.8144 | 0.5719 / 0.4290 |
| Mean of last four final-token states | 0.5894 | 0.8873 / 0.6668 | 0.8701 / 0.8144 | 0.8729 / 0.8179 | 0.5734 / 0.4285 |
| Final token + full mean | 0.6155 | 0.8412 / 0.6391 | **0.8422** / **0.8259** | 0.8468 / **0.8235** | 0.5592 / 0.4483 |
| Midpoint + final token | **0.6262** | 0.9042 / 0.6851 | 0.8860 / 0.8166 | **0.8841** / 0.8164 | 0.6193 / **0.4598** |
| Fixed 256-D random projection | 0.5108 | 0.9079 / 0.6796 | 0.8685 / 0.7928 | 0.8628 / 0.7879 | 0.5667 / 0.3994 |

The 11-reason head is scored separately from the decision head. For the best reason macro-F1 surface (final-token + mean, 0.3515), recalls are: insufficient evidence 0.610 (7,976); conflicting evidence 0.722 (3,255); unknown entity 0.525 (1,716); unknown target 0.473 (1,661); missing argument not present (0); no valid action 0.359 (2,923); impossible goal 0.614 (2,261); ambiguous reference 0.005 (1,090); multiple unresolved actions 0.002 (1,100); precondition unknown not present (0); out of scope 0.111 (1,084). Thus the macro score is weak, with particularly poor recovery for ambiguous-reference and multiple-unresolved-action cases.

## Held-out surface and challenge behavior

Decision macro-F1 on the held-out renderer families:

| Surface | S7 | S8 | S9 |
|---|---:|---:|---:|
| Final token | 0.4407 | 0.3935 | 0.2140 |
| Full token mean | 0.2966 | 0.3607 | 0.2262 |
| First token | 0.3246 | 0.3251 | 0.3176 |
| Layer −4 final token | 0.4841 | 0.3806 | 0.2010 |
| Layer −3 final token | 0.4697 | 0.3824 | 0.2312 |
| Layer −2 final token | 0.4553 | 0.3764 | 0.1893 |
| Mean of last four final-token states | 0.4462 | 0.3990 | 0.2008 |
| Final token + full mean | 0.3674 | 0.4125 | 0.2393 |
| Midpoint + final token | **0.4897** | **0.4967** | 0.2282 |
| Fixed 256-D random projection | 0.4044 | 0.3653 | **0.2441** |

The strongest route-exact arm varies by test family: final-token + mean leads IID (0.6234), entity (0.6066), composition (0.4858), and abstention (0.2784); midpoint + final leads lexical (0.4652), depth (0.5398), and joint (0.2094); layer −4 leads template (0.3790). The joint and S9 results remain weak across all surfaces.

Across the 14 difficulty metadata dimensions, mean decision macro-F1 across available low/mid/high tercile cells ranges from 0.530/0.478/0.535 for final-token + mean and 0.533/0.472/0.532 for midpoint + final. These are descriptive averages over feature-defined strata, not independent samples.

Across 8,000 same-world paired renderer variants, decision invariance ranges from 0.7746 to 1.0000; full typed-output invariance ranges from 0.0194 to 1.0000. First-token output is perfectly invariant but its feature vectors across a 10,000-row sample are nearly constant (mean per-dimension standard deviation `1.43e-4`) and it performs poorly. This is a useful warning that invariance alone can reward an uninformative representation. BANK-v1's sealed G20 construction/simulator check also reports PASS with no listed failures; that is distinct from model correctness.

## Interpretation and limits

Surface choice reallocates capability across policy, abstention, NLI and structured heads. The best aggregate decision surfaces are the two concatenations, while the weak ASK recall, low exact route rates, and collapse on joint/S9 cases show substantial remaining limitations. The first-token arm is effectively a negative control. The random projection degrades most aggregate policy metrics, as expected for a fixed compression baseline.

This run uses one 230M checkpoint and BANK-v1's synthetic task distribution. It does not compare 230M against 1.2B, test lexical transport, touch retrieval or authority, or establish natural-language generalization.

## Receipts

- Aggregate prediction seal: `D:\phoenix-target-overgraph\bank-v1-surface-extremes-20260929\all-surfaces-prediction-seal.json` (SHA-256 `876984c304723fbb4bbb29c157444bd3933f6b4c6bbcd6ebb9ba32edcaa3b613`).
- Full score receipt: `D:\phoenix-target-overgraph\bank-v1-surface-extremes-20260929\surface-score.json` (SHA-256 `bd9ad0a50a20f6155090bedbc2e0aabe2f1eb3dec8e96f354149a37e4ba87faf`).
