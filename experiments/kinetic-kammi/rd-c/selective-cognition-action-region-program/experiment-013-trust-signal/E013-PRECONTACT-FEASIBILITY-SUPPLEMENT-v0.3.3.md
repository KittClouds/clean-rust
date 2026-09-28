# E013 Precontact Feasibility Supplement v0.3.3

**Parent design:** sealed E013 v0.3.2, lock SHA-256 `fbac0d86ffd6a593793d2a35d00d2250ae63b52a0abec99864d36456d1af1adb`  
**State:** `SEALED_PRECONTACT_DESIGN_ONLY`  
**Scope:** expose the already-calculated T5 and confirmation-support probabilities in readable receipt form. No input values, gates, bank design, or model-contact state change.

## T5 development-support feasibility

T5 requires at least 100 correct and 100 wrong non-null small proposals in E013-D (864 tasks). The probabilities below use the locked iid multinomial planning scenarios; they are sizing illustrations, not guarantees. The same projected counts are preserved for E013-C for lineage, though T5 is a development-only probe.

| Bank | Scenario | Expected correct raw | Expected wrong raw | P(both counts >=100) |
|---|---|---:|---:|---:|
| D / 864 | pooled_E012_conservative | 126.0 | 198.0 | 99.566205% |
| D / 864 | nominal_assumption | 216.0 | 216.0 | >99.999999% |
| D / 864 | E012_stratum_standardized_sensitivity_only | 142.8 | 195.6 | 99.998282% |
| C / 1120 | pooled_E012_conservative | 163.3 | 256.7 | >99.999999% |
| C / 1120 | nominal_assumption | 280.0 | 280.0 | >99.999999% |
| C / 1120 | E012_stratum_standardized_sensitivity_only | 184.8 | 253.6 | >99.999999% |

Under pooled E012 rates, E013-D expects 126 correct and 198 wrong proposals; the joint threshold probability is 99.5662%. Thus the 864-task resize addresses the prior correct-proposal support shortfall, while observed sealed-bank support still determines T5 eligibility. If either observed count is below 100, T5 remains unavailable; do not enlarge the bank after model outputs.

## Confirmation support ceiling

These are probabilities of having enough **correct proposals retained by an oracle trust signal** under the stated recall; they are not probabilities of passing the semantic-risk gate. False accepts and the exact Clopper-Pearson bound remain decisive.

| Scenario | Correct-proposal recall | Expected oracle correct accepts | P(n >= 60) | P(n >= 93) |
|---|---:|---:|---:|---:|
| E012_pooled_conservative | 50% | 81.7 | 99.5986% | 10.8046% |
| E012_pooled_conservative | 70% | 114.3 | >99.999999% | 98.6363% |
| E012_pooled_conservative | 90% | 147.0 | >99.999999% | 100.0000% |
| nominal | 50% | 140.0 | >99.999999% | 99.9997% |
| nominal | 70% | 196.0 | >99.999999% | >99.999999% |
| nominal | 90% | 252.0 | >99.999999% | >99.999999% |

For the retired 512-task sizing case, E012's pooled rate gives an oracle ceiling of `512 * 7/48 = 74.67` expected correct proposals: `P(n >= 59)=98.11%` at 100% recall. At 70% recall, expected oracle support is 52.27, `P(n >= 60)=14.59%`, and `P(n >= 93)=0.0000037%`. The current C=1,120 pooled case at 70% recall has 114.3 expected oracle accepts and 98.6363% support probability for 93. These comparisons explain the resize; neither predicts trust-signal specificity.

## Interpretation and boundaries

- `NO_PROPOSAL` is a separate outcome. An oracle trust signal cannot create a missing proposal.
- T5's sample-count event is only a precondition for attempting the probe, not a promotion result.
- The probabilities assume independent task-level outcomes and ignore repository/family clustering.
- The v0.3.2 correction to asymptotic FAR is unchanged; finite exact-gate illustrations and admission rules are unchanged.
- E013-D/C model contact remains unauthorized. The user builds both banks. No bank, task, fixture, screen, observer call, or score was created.
