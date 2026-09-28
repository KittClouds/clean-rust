# F4-BINDING-01 Stage A: exploratory existing-bank anatomy

This is a post-selection engineering diagnostic on the already-open F4-PRESENTATION-03 bank. No training, fitting, gradient, optimizer, or phi recomputation occurred.

## Equal-weight assignment effects

Positive Δ balanced error means role disruption worsened classification. Values average the three frozen initialization replicates within assignment; the six assignments receive equal weight.

| Condition | ΔE 1100 | ΔE 1010 | ΔE 0110 | ΔE 1001 | ΔE 0101 | ΔE 0011 | Equal-weight mean |
|---|---:|---:|---:|---:|---:|---:|---:|
| pair_swap | +0.190087 | +0.109073 | +0.126909 | +0.139993 | +0.140143 | +0.091449 | +0.132942 |
| cycle_4 | +0.622294 | +0.498653 | +0.413502 | +0.502606 | +0.499544 | +0.499466 | +0.506011 |

## Scope

These estimates are descriptive and exploratory. They do not establish general causal necessity, authorize Stage B, or change REACH-03, calibration, controller, PHENO, or biological status. Classification, proposed polarity alignment, delivery alignment, and trajectory capability remain separate.
