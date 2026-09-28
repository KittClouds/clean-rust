# FLY-REACH-01 — Direction Failure Anatomy

Disposition: **DIRECTION_FAILURE_ANATOMY_PARTIAL_WITH_EVALUATOR_FLOOR**

Reference direction on native support improves the endpoint; native direction is the dominant shortfall.

This is a sealed engineering-only follow-up to FLY-REACH-00. It does not reopen PHENO, promote a biological mechanism, or make a claim about what a fly should learn.

## Primary endpoint

The primary readout is the floor-relative large-bank loss and excess above the same-cell 128-step weight-oracle loss. The old 0.25 gate is retained descriptively; the evaluator floor is reported explicitly.

| arm | large-bank loss | excess above oracle | 256-bank competence rate |
|---|---:|---:|---:|
| native | 0.313205 | 0.082593 | 20.4% |
| sign_ref_native_mag | 0.250699 | 0.020088 | 44.0% |
| mag_ref_native_sign | 0.332602 | 0.101991 | 0.0% |
| reference_direction_native_support | 0.248068 | 0.017457 | 45.8% |
| reference_direction_full_support | 0.242703 | 0.012091 | 63.0% |
| weight_oracle | 0.230611 | 0.000000 | 73.6% |

## Native stage anatomy

- eligibility cosine: 0.002767
- modulation cosine: 0.002728
- aggregation/native cosine: 0.002728
- delivered cosine: 0.000300
- native support fraction: 37.325%
- reference mass on native support: 64.860%
- sign agreement on native support: 38.975%
- magnitude Pearson correlation: 0.013744

All findings are bounded to this host, task, evaluator, and engineering counterfactuals. No biological promotion and no PHENO reseal are authorized.
