# JEV Information Density v0.8H — Treatment Attribution Audit

**Status:** Complete; post-hoc metadata and saved-prediction audit only.  
**Primary question:** Which parts of the matched R100* / C100* treatment differ in learner-visible space, and how do the saved v0.8G outcomes vary alongside those differences?  
**Conclusion:** The observed contrast is mixed by decision type. It does not establish a general curation advantage or identify a causal mechanism.

## Scope and integrity

v0.8H consumed the sealed v0.8G manifests, receipts, metadata, and saved predictions. It did not load LFM, run inference, extract features, train or inspect a head, reconstruct or optimize a bank, alter P*, change evaluation, or access Phoenix. v0.8G remains sealed and unchanged.

Preflight revalidated the two 100,000-group arms, the P* profile, source lineage and hashes, zero held-out overlap, and the training-signature treatment. The primary NewTight-Eval surface contains 83,328 groups per run: 20,832 choice, 41,664 independent-applicability, and 20,832 ordinal groups. Three paired seed runs are reported. Metrics below are means of the three per-seed metrics, not pooled-row estimates; each seed's paired difference remains visible in the JSON reports.

The authoritative audit artifacts are under `D:\codex-runs\jev-information-density-v08h\`. The final integrity receipt SHA-256 is:

```text
7a07b7a7d1af99efb3d4382c0ab9dd97c7de98067c114443231879eaeff9aa2e
```

Two executive summaries were compacted after analysis to remove duplicated row-level payloads. Their detailed source reports were preserved. The receipt records the refresh script and updated hashes.

## Treatment reconstruction

| Quantity | Random R100* | Curated C100* |
| --- | ---: | ---: |
| Groups | 100,000 | 100,000 |
| Choice | 25,015 | 25,015 |
| Independent applicability | 49,999 | 49,999 |
| Ordinal score | 24,986 | 24,986 |
| Exact training-signature mass enriched in this arm | 13,489 | 13,489 |
| Unique exact training signatures | 22,959 | 23,253 |

The exact v0.5 training unit includes supervised-signature multiplicity and the selected directed invariance-pair role events. Replaying the frozen attachment rule gives `D_train = 0.13489`; the supervised-signature-only distance is `0.13479`. Both arms contain 16 selected invariance pairs. Raw group-ID Jaccard is 0.71493, but row overlap is provenance telemetry, not the treatment measure.

The declared state-exposure control is multiplicity geometry, not identical state IDs. Both arms have 8,599 unique states, 8,564 shared, 35 unique to each, and a state-multiplicity histogram TV of 0. State identity Jaccard is 0.99189. Nevertheless, exact training-signature composition differs within 7,283 shared states. Root identity Jaccard is 0.98414 and root-multiplicity TV is 0.01987, within the frozen 0.02 bound. This is consistent with the sealed P* interpretation; it is not evidence that state identity was held fixed.

## Primary NewTight-Eval results

Delta is curated minus random. For Brier, NLL, L1, ECE, and RPS, negative is numerically better; accuracy and rank metrics are better when positive. These signs do not make different metrics interchangeable.

| Typed task / metric | Random mean | Curated mean | Mean paired delta | Three seed deltas |
| --- | ---: | ---: | ---: | --- |
| Choice accuracy | 0.13457 | 0.10879 | -0.02578 | -0.00187, -0.04383, -0.03163 |
| Choice Brier | 0.18412 | 0.18203 | -0.00209 | -0.00149, +0.00425, -0.00904 |
| Choice NLL | 1.47470 | 1.47595 | +0.00125 | -0.00032, +0.01319, -0.00912 |
| Choice ECE | 0.16208 | 0.14787 | -0.01420 | -0.01887, +0.00366, -0.02739 |
| Choice posterior L1 | 0.69848 | 0.69935 | +0.00087 | -0.00216, +0.01745, -0.01268 |
| Applicability accuracy* | 0.79018 | 0.79018 | 0.00000 | 0, 0, 0 |
| Applicability Brier | 0.05246 | 0.05462 | +0.00216 | +0.00399, +0.00084, +0.00166 |
| Applicability NLL | 0.59151 | 0.59924 | +0.00774 | +0.01244, +0.00264, +0.00813 |
| Applicability ECE | 0.10278 | 0.09901 | -0.00377 | -0.00208, +0.00133, -0.01056 |
| Applicability posterior L1 | 0.19123 | 0.19781 | +0.00658 | +0.01351, +0.00099, +0.00523 |
| Ordinal exact accuracy | 0.14372 | 0.14619 | +0.00246 | +0.02909, +0.01118, -0.03288 |
| Ordinal adjacent accuracy | 0.55074 | 0.52520 | -0.02554 | +0.07301, -0.14809, -0.00154 |
| Ordinal expected-rank Spearman | 0.07933 | 0.04578 | -0.03355 | +0.20398, -0.30546, +0.00084 |
| Ordinal normalized RPS | 0.02264 | 0.02154 | -0.00110 | -0.00961, +0.00819, -0.00188 |

*Applicability accuracy uses the evaluator's descriptive 0.5 threshold; its canonical target remains an independent probability, not a closed-set class label.

The most stable metric pattern is not a win: choice accuracy falls in all three paired seeds, while choice Brier improves on average but is seed-mixed and NLL is nearly unchanged. Applicability accuracy is unchanged by thresholding, while Brier, NLL, and L1 worsen in every seed; ECE improves slightly on average but is mixed. Ordinal deltas vary by metric and seed, including a large seed-2 reversal in adjacent accuracy and rank correlation. There is no defensible single aggregate score.

### Hard siblings

Choice accuracy is lower for C100* in every same-parent competitor-count stratum, while Brier is slightly lower on average. Means below average the three seed-specific stratum metrics; rows are repeated across seeds and are not independent sample counts.

| Same-parent competitors | Random accuracy | Curated accuracy | Delta | Random Brier | Curated Brier |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 0.13447 | 0.10753 | -0.02695 | 0.18622 | 0.18338 |
| 1 | 0.13383 | 0.11095 | -0.02288 | 0.18456 | 0.18274 |
| 3 | 0.13614 | 0.10573 | -0.03040 | 0.18115 | 0.17925 |

## What the frozen policy selected

The exact frozen scorer replay passed at absolute tolerance `1e-12`. Full-bank mean score was 0.04808 for R100* (descriptive only) and 0.04959 for C100*, a +0.00151 difference. On the equal 13,489 enriched mass in each arm, mean score was 0.04782 versus 0.05803 (+0.01021).

The enriched-mass component mean deltas, curated minus random, were:

| Frozen score axis | Mean delta |
| --- | ---: |
| Semantic novelty | +0.00000105 |
| Local discrimination | +0.00000152 |
| Probability geometry | +0.00000145 |
| Structural coverage | approximately 0 |
| Redundancy | +0.05103020 |

Given the frozen equal component weights, the observed selected-mass score separation is overwhelmingly on the redundancy axis. This describes what the policy score selected; it does not show that redundancy caused any model outcome.

The active-mass redundancy descriptors do not all move together: signature multiplicity mean is 5.91 random versus 5.29 curated; state multiplicity 15.27 versus 14.81; root multiplicity 4.59 versus 5.27; semantic recurrence 2.31 versus 2.55; structural recurrence 19.38 versus 22.45; text recurrence 45.97 versus 34.53. “Redundancy” is a policy feature name, not a universal claim that repeated material is harmful.

## Binding, interventions, and acquisition

### Binding

The ordinary `opaque_definition` versus `name_definition` aggregate profile drift averaged L1 0.16061 / flip rate 0.32217 for random and L1 0.14139 / flip rate 0.28982 for curated. Seed patterns are mixed.

The separate saved identity challenge substitutes opaque IDs while keeping definitions and gold fixed. On choice pairs, random has mean L1 0.28741 and flip rate 0.56641; curated has L1 0.48527 and flip rate 0.29167. Ordinal predictions are unchanged (L1 0, flips 0). The choice result is not a simple “better binding” signal: curated redistributes probability more while flipping fewer argmax decisions. The probe does **not** change definitions, so it cannot measure signed response to definition semantics.

### Evidence/world interventions

The table summarizes candidate-delta-count-weighted sign agreement and absolute delta error across 12 family-by-seed cells per arm; the Pearson column is the **unweighted mean of family-level correlations**, not a pooled rowwise correlation.

| Intervention / task | Random sign | Curated sign | Random MAE | Curated MAE | Mean family Pearson R / C |
| --- | ---: | ---: | ---: | ---: | ---: |
| Observation / choice | 0.506 | 0.497 | 0.0736 | 0.0694 | -0.038 / -0.036 |
| Observation / applicability | 0.774 | 0.737 | 0.0407 | 0.0420 | 0.517 / 0.524 |
| Observation / ordinal | 0.531 | 0.546 | 0.0345 | 0.0311 | 0.054 / 0.047 |
| World / choice | 0.480 | 0.466 | 0.2048 | 0.2035 | -0.118 / -0.150 |
| World / applicability | 0.509 | 0.551 | 0.2013 | 0.2009 | -0.022 / 0.083 |
| World / ordinal | 0.569 | 0.558 | 0.0747 | 0.0738 | 0.159 / 0.117 |

World-intervention false-movement rates were high and mixed: choice 0.462 / 0.445, applicability 0.384 / 0.494, ordinal 0.304 / 0.320 (random / curated). Surface-invariance false-movement rates were choice 0.435 / 0.440, applicability 0.363 / 0.481, ordinal 0.302 / 0.310. These data do not support a broad intervention-tracking advantage. Counterfactual locality itself is not measurable: the persisted evaluation lacks compiler-side direct/indirect/unaffected query truth.

### Acquisition

Mean choice-accuracy delta (C-R) by epoch is -0.02474, -0.02018, and -0.02578 at epochs 1, 2, and 3. Choice Brier delta is +0.00856, -0.00226, and -0.00209. Mean terminal train losses are nearly tied: 0.90632 random and 0.90692 curated. This does not show a consistent faster-learning advantage for C100*.

## Legacy human-uncertainty audit and limitations

The saved v0.7 legacy aggregate metrics for empirical annotator-distribution evaluation are extremely seed-by-arm unstable. On the legacy test surface (13,973 records per run), raw Brier ranges from 0.5461 to 0.1553 to 0.2497 across random seeds 1–3, while the corresponding curated values are 0.05595, 0.36722, and 0.11896. These are historical aggregate outputs, not rowwise attribution evidence. No class histograms, confusion matrices, or per-row legacy predictions were available, and the v0.8H audit did not load checkpoints to recreate them.

Additional limits:

- One fixed bank per policy arm and three paired optimization seeds do not estimate a broad distribution over possible curated/random banks.
- The audit is post-hoc; training exposures and evaluation differences are descriptive associations, not identified mediators.
- Standard-schema per-row predictions were not persisted.
- The opaque-ID probe is identity substitution only; it does not alter candidate definitions.
- Locality labels were unavailable, so locality mediation was not inferred.
- Legacy human-disagreement metrics remain separate from exact synthetic posterior metrics.

## Decision

v0.8H finds a real, reconciled learner-visible treatment but **no general curation win**. The observed pattern is a task-specific tradeoff: lower choice accuracy, slightly better average choice Brier/ECE, worse independent-applicability Brier/NLL/L1, and unstable/mixed ordinal behavior. Intervention and binding results are also mixed. The redundancy score axis dominates the frozen policy-score difference, but the available artifacts cannot establish that this or any other exposure dimension explains the performance contrast.

No follow-on training or model experiment is authorized by this audit.

## External report index

All 17 JSON reports and `integrity-receipt.json` are in `D:\codex-runs\jev-information-density-v08h\`. The compact `capability-allocation-map.json` points to detailed metrics without embedding their row-level payloads; `candidate-mechanisms.json` contains descriptive candidates only.
