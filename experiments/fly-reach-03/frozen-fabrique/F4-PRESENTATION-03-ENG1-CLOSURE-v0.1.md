# F4-PRESENTATION-03-ENG1 Closure

**Disposition:** `Cphi_RETAINS_ENGINEERING_LEAD`  
**Closed:** true  
**Scope:** engineering evidence only  
**Run modified:** no

## Bounded result

The completed fresh continuation compared four trained interface packages on 29,275 rows across 12 task blocks, six cue-label assignments, nine substrates, two sides, and three initialization replicates (144 fits total). The equal-assignment macro balanced errors at epoch 200 were:

| Interface | Macro balanced error |
| --- | ---: |
| D, raw canonical tuples | 0.114168 |
| CΦ, shared local map with canonical concatenation | **0.032491** |
| CΦ-unshared | 0.032358 |
| CΦ-shuffled | 0.270111 |

CΦ beat D in all three replicate aggregates and in five of six assignment means. The six `CΦ − D` assignment effects, in frozen assignment order, were:

| Assignment | Effect |
| --- | ---: |
| `1100` | −0.209175 |
| `1010` | −0.043100 |
| `0110` | −0.000630 |
| `1001` | −0.211083 |
| `0101` | +0.000321 |
| `0011` | −0.026396 |

The effect is assignment-conditioned, not uniform. CΦ and CΦ-unshared were practically tied at the fixed endpoint; this run shows no endpoint advantage from sharing the local φ weights. The shuffled arm's worse score shows strong dependence of this trained interface family on stable role-coordinate presentation. It does not establish that the substrate intrinsically requires canonical coordinates: a different interface could recover the same function.

The supported terminal map is:

| Finding | Status |
| --- | --- |
| CΦ | Fresh engineering leader on this panel |
| Shared φ | No demonstrated epoch-200 endpoint advantage |
| Shared local weights | Not required for the observed engineering advantage |
| Stable canonical role coordinates | Strong interface dependence on this panel |
| Intrinsic coordinate necessity | Not established |
| Effect uniformity | False; materially assignment-conditioned |
| Causal role binding | Motivated next hypothesis; not established by this comparison |

## Measurement and provenance limits

Classification error, signed-margin orientation, proposed alignment Ψ, delivery-aware alignment, and trajectory endpoint capability remain separate quantities. The q-weighted classification score had pooled ESS 29,274.23 of 29,275 rows, with q from 376.421875 to 380.546875. By contrast, CΦ's median Ψ summaries had leverage ESS about 43.36, median top-1% leverage share 77.65%, and median top-5% share 96.97%. Ψ therefore describes alignment on highly concentrated consequential leverage, not broad polarity accuracy. Continue attaching leverage ESS and top-1/5/20% shares to every Ψ report.

The final comparative analysis was not a completely blind first pass. Fits and predictions were locked and integrity passed before the successful scoring path, but an earlier post-integrity analyzer opened comparative truth and computed metrics in memory before failing at receipt construction. That failed attempt wrote or emitted no comparative result; a versioned one-line repair then completed the analysis. Preserve this truth-access history with every reuse of the result.

The archived engineering disposition remains unchanged. This result does not authorize learned-F4 calibration, measured REACH-03, controller work, PHENO, biological promotion, or a universal scientific claim. Do not alter the completed run.

## Controlling artifacts

All paths are relative to the repository root.

| Artifact | SHA-256 |
| --- | --- |
| Terminal receipt `experiments/fly-reach-03/runs/F4-PRESENTATION-03-EXECUTION-REPAIR-v0.1/F4-PRESENTATION-03-TERMINAL-RECEIPT.json` | `298a77fe8aa815a3ff58722dd52a06a8e1e0637fce505955662354150203f2bb` |
| Analysis `experiments/fly-reach-03/runs/F4-PRESENTATION-03-EXECUTION-REPAIR-v0.1/ANALYSIS.json` | `d79f885d3d8b8bef0579312cc72c2b5c8fa08b6edb1fcf52b66bcf5abf1b51c5` |
| Integrity receipt | `cf52cc787b3bf501b3f80944d452af3247e569f82f110c06c597e499bfca2591` |
| Prediction lock | `dd387bcc52510eac947774cb6d9303d8cdd8142cee07a60b0e39cddd4dcb54ce` |
| Fit manifest | `f71d344c5bc58e86a68e7bd9163aed1ab5d945468bfe84f06a8981e6a1c2ce66` |
| CΦ implementation source `experiments/fly-reach-03/f4-presentation-02-v2/cphi_model.py` | `d50521285235db36b062f9eda9a90eb4182a836e2ccb8ab292c04e9e74158099` |

The q-weight diagnostics companion is `experiments/fly-reach-03/runs/F4-PRESENTATION-03-EXECUTION-REPAIR-v0.1/Q-WEIGHT-DIAGNOSTICS-RECEIPT-v0.1.json`, SHA-256 `17f4a6af4330b3929b8e97ad788e2d88d8d3df07d70b8149a2ffe969abaa7d03`. It attaches unmodified `q=1/p` diagnostics to the weighted scopes and does not recompute scores.

## Program flags

```text
F4_PRESENTATION_03_CLOSED = true
F4_PRESENTATION_03_DISPOSITION = Cphi_RETAINS_ENGINEERING_LEAD
ENGINEERING_ONLY = true
MEASURED_REACH03_AUTHORIZED = false
PHENO_STATUS = unchanged
BIOLOGICAL_PROMOTION = false
```
