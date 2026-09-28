# F4-PRESENTATION-03 Engineering Screen

**Identity:** `F4-PRESENTATION-03-ENG1`  
**Status:** Engineering-only comparison; no scientific promotion.  
**Rows:** 29,275; **fits:** 144; **assignments:** 6, two blocks each.

## Primary endpoint

Epoch 200, class-balanced within each assignment using inverse inclusion weights, then equally weighted across the six assignments. Negative CΦ-minus-control differences favor CΦ.

| Arm | Macro balanced error |
| --- | ---: |
| D | 0.114168 |
| Cphi | 0.032491 |
| Cphi_unshared | 0.032358 |
| Cphi_shuffled | 0.270111 |

## CΦ contrasts

| Contrast | Replicate values | Mean |
| --- | --- | ---: |
| Cphi_minus_D | -0.009840, -0.144791, -0.090400 | -0.081677 |
| Cphi_minus_Cphi_unshared | +0.000605, +0.000021, -0.000226 | +0.000133 |
| Cphi_minus_Cphi_shuffled | -0.279134, -0.155774, -0.277951 | -0.237620 |

## Assignment support

| Assignment | Blocks | + rows | − rows | Evaluable | CΦ−D |
| --- | --- | ---: | ---: | --- | ---: |
| 1100 | 309004, 309011 | 495 | 3983 | True | -0.209175 |
| 1010 | 309003, 309007 | 2453 | 2461 | True | -0.043100 |
| 0110 | 309005, 309008 | 4624 | 1665 | True | -0.000630 |
| 1001 | 309000, 309001 | 1783 | 5504 | True | -0.211083 |
| 0101 | 309009, 309010 | 403 | 1792 | True | +0.000321 |
| 0011 | 309002, 309006 | 3066 | 1046 | True | -0.026396 |

## Leverage concentration

Each Ψ report is stored with leverage ESS and top 1%, 5%, and 20% leverage shares in `ANALYSIS.json`. Classification error, margin orientation, Ψ, and delivery alignment remain separate measures.

## Disposition

Engineering nomination: `Cphi_RETAINS_ENGINEERING_LEAD`. This does not authorize F4 calibration, measured REACH-03, controller work, PHENO, or biological promotion.

The raw truth field stores the inclusion probability p; this analysis uses q=1/p as required by the frozen REACH math contract. Archived scorer outputs that used p directly are not directly comparable.
