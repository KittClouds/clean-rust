# JEV v0.8N-E1: Repaired Held-Out Evaluation of Sealed Phase-B Checkpoints

**Result identity:** POST-REGISTERED v0.8N-E1 REPAIRED HELD-OUT EVALUATION OF SEALED PHASE-B CHECKPOINTS  
**Disposition:** E1 evaluation and frozen analysis completed and sealed.  
**Original Phase B:** permanently `EVALUATION_INPUT_CONTRACT_INCOMPLETE`; this report does not amend or replace that disposition.

## Result in brief

The radius-matched comparison did **not** demonstrate localized control under the frozen criterion. SHAM-trained heads were less responsive to the held-out sham in all three seeds by posterior L1, and in two seeds by MAP-flip rate. But fact sensitivity was badly reduced: strict fact transitions were `64.70% → 0.00%`, `0.00% → 0.00%`, and `95.45% → 72.20%` for MATCHED→SHAM. The mean paired SHAM-minus-MATCHED transition change was `−29.32 percentage points`, beyond the preregistered maximum loss of 5 points.

The absolute `0.37` fact-transition floor failed for SHAM in seeds `20260927` and `20260928`, and for MATCHED in seed `20260928`. The frozen primary gate is therefore **false**. The appropriate reading is suppression/coupling or sensitivity insufficiency, not successful localized control.

This is a descriptive effect of which auxiliary examples trained the frozen-substrate decision head. It is not evidence that the frozen backbone changed capability, and it does not isolate semantic identity from representation direction, higher-order geometry, edited field, or edit position.

## What was evaluated

The original Phase-B evaluator could not bind four held-out schemas to candidate semantic vectors. That opening failed before head loading, predictions, or metrics. The original Phase B remains incomplete. E1 was separately registered after that failure and supplied the missing 16 candidate vectors by the same frozen text-to-feature recipe used for the training candidate catalog; it did not use positional crosswalks or nearest-neighbor matching.

One pre-opening, metadata-only validator invocation initially compared a terminal checkpoint's serialized-file digest with the distinct state-digest field and failed closed. The verifier was corrected to compare file bytes with the sealed hash-tree entry and state digests with the run-integrity receipt. This happened before opening 2, panel-body access, or checkpoint deserialization; the successful preflight rehashed all 81 training-tree entries and matched all nine terminal identities.

The E1 candidate basis contains 16 exact-identity vectors of dimension 2,048. Independent repeat extraction had maximum absolute error `0.0`. The target-free join resolved all 2,000 held-out neighborhoods to four unique candidate identities in authoritative schema order: zero missing, duplicate, or extra joins. The panel contains 500 neighborhoods in each of four families. All 9 frozen terminal heads were evaluated against anchor, fact-flip, sham, and matched-neutral views: `9 × 2,000 × 4 = 72,000` prediction rows. The 18,000 geometry/surface diagnostic rows were also retained.

The held-out matched-neutral basis is specifically the prospectively radius-matched `neutral_4`/`neutral_5` subset (896 and 1,104 neighborhoods respectively). It is not a representative sample of arbitrary irrelevant semantic changes.

## Full seed-by-arm response matrix

All rates below are proportions converted to percent. L1 is the four-way posterior L1 distance from the anchor. `Matched L1/flip` uses the held-out matched-neutral view; `Sham L1/flip` uses the held-out sham view. Fact metrics use the held-out fact-flip view. These are terminal-epoch results only.

### Locality outcomes

| Seed | Training arm | Sham L1 | Sham MAP flips | Matched-neutral L1 | Matched-neutral MAP flips |
|---|---|---:|---:|---:|---:|
| 20260927 | B-DUP | 0.007145 | 43.05% | 0.004448 | 24.70% |
| 20260927 | B-MATCHED | 0.142067 | 56.15% | 0.007758 | 2.20% |
| 20260927 | B-SHAM | 0.009309 | 0.00% | 0.005603 | 0.00% |
| 20260928 | B-DUP | 0.043129 | 0.00% | 0.028322 | 0.00% |
| 20260928 | B-MATCHED | 0.010591 | 0.00% | 0.001845 | 0.00% |
| 20260928 | B-SHAM | 0.006254 | 0.00% | 0.003620 | 0.00% |
| 20260929 | B-DUP | 0.165465 | 29.85% | 0.100929 | 18.60% |
| 20260929 | B-MATCHED | 0.158544 | 25.60% | 0.006572 | 0.20% |
| 20260929 | B-SHAM | 0.083965 | 0.55% | 0.048318 | 0.25% |

### Fact sensitivity and anchor preservation

| Seed | Training arm | Strict old→new transition | Correct direction | New-candidate Δp | Exact-Δ MAE | Anchor NLL | Anchor Brier | Anchor gold-MAP accuracy |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 20260927 | B-DUP | 0.00% | 75.00% | 0.000768 | 0.375203 | 1.333856 | 0.044955 | 96.30% |
| 20260927 | B-MATCHED | 64.70% | 100.00% | 0.244583 | 0.131389 | 1.329628 | 0.043571 | 64.70% |
| 20260927 | B-SHAM | 0.00% | 100.00% | 0.007380 | 0.368592 | 1.341731 | 0.050397 | 50.00% |
| 20260928 | B-DUP | 0.20% | 100.00% | 0.037532 | 0.338440 | 1.298509 | 0.024921 | 100.00% |
| 20260928 | B-MATCHED | 0.00% | 100.00% | 0.007199 | 0.368773 | 1.324388 | 0.039346 | 100.00% |
| 20260928 | B-SHAM | 0.00% | 100.00% | 0.005062 | 0.370910 | 1.325752 | 0.039696 | 100.00% |
| 20260929 | B-DUP | 99.55% | 100.00% | 0.196950 | 0.179022 | 1.289005 | 0.020659 | 99.95% |
| 20260929 | B-MATCHED | 95.45% | 100.00% | 0.267683 | 0.112971 | 1.290541 | 0.022972 | 95.45% |
| 20260929 | B-SHAM | 72.20% | 100.00% | 0.259618 | 0.116354 | 1.299776 | 0.027683 | 75.15% |

Correct-direction rates are not a substitute for strict transitions: in seed `20260928`, both matched arms had 100% direction but 0% strict transitions, with near-zero new-candidate movement and high exact-delta MAE. This is why the frozen report keeps direction, movement magnitude, and MAP transition separate.

## Primary paired comparison: B-SHAM versus B-MATCHED

The signed locality benefit is `B-MATCHED metric − B-SHAM metric`; positive values mean lower locality metric for B-SHAM. Intervals are the frozen 10,000-replicate, family-stratified neighborhood bootstrap, conditional on the trained seed. They do not treat three optimization seeds as a population sample.

| Seed | Sham-L1 benefit (95% interval) | Sham MAP-flip benefit (95% interval) | Strict transition, SHAM−MATCHED | Sensitivity floor: MATCHED / SHAM |
|---|---:|---:|---:|---|
| 20260927 | +0.132757 `[0.132367, 0.133134]` | +56.15 pp `[54.20, 58.10]` | −64.70 pp | pass / fail |
| 20260928 | +0.004338 `[0.004321, 0.004354]` | 0.00 pp `[0.00, 0.00]` | 0.00 pp | fail / fail |
| 20260929 | +0.074578 `[0.074235, 0.074921]` | +25.05 pp `[24.25, 25.80]` | −23.25 pp | pass / pass |

Across the three fixed seeds, the mean/median sham-L1 benefit was `0.070558 / 0.074578`; the mean/median MAP-flip benefit was `27.07 / 25.05` percentage points. The mean strict-transition change was `−29.32` percentage points. L1 favored SHAM in each seed, but MAP-flip benefit was zero in seed `20260928`, and the sensitivity guard failed. The predeclared 90% intervals did not establish all-seed equivalence under either frozen equivalence margin.

### Family-level locality and strict-transition results

Each cell shows `B-MATCHED / B-SHAM`; L1 is absolute, rates are percent. The family breakdown is descriptive, with no confirmatory family-level claims.

| Seed | Family | Sham L1 | Sham MAP flips | Strict fact transition |
|---|---|---:|---:|---:|
| 20260927 | Exposure control | 0.1791 / 0.0072 | 81.6 / 0.0 | 99.6 / 0.0 |
| 20260927 | Respiratory monitoring | 0.0991 / 0.0087 | 21.0 / 0.0 | 100.0 / 0.0 |
| 20260927 | Salinity control | 0.1380 / 0.0082 | 69.8 / 0.0 | 45.4 / 0.0 |
| 20260927 | Vibration monitoring | 0.1521 / 0.0131 | 52.2 / 0.0 | 13.8 / 0.0 |
| 20260928 | Exposure control | 0.0090 / 0.0048 | 0.0 / 0.0 | 0.0 / 0.0 |
| 20260928 | Respiratory monitoring | 0.0094 / 0.0039 | 0.0 / 0.0 | 0.0 / 0.0 |
| 20260928 | Salinity control | 0.0099 / 0.0069 | 0.0 / 0.0 | 0.0 / 0.0 |
| 20260928 | Vibration monitoring | 0.0140 / 0.0094 | 0.0 / 0.0 | 0.0 / 0.0 |
| 20260929 | Exposure control | 0.1898 / 0.1030 | 5.4 / 0.0 | 100.0 / 99.8 |
| 20260929 | Respiratory monitoring | 0.1016 / 0.0615 | 0.0 / 0.0 | 100.0 / 100.0 |
| 20260929 | Salinity control | 0.1464 / 0.0689 | 0.4 / 0.0 | 100.0 / 88.2 |
| 20260929 | Vibration monitoring | 0.1964 / 0.1024 | 96.6 / 2.2 | 81.8 / 0.8 |

The family table makes the suppression/coupling pattern concrete: in seed `20260927`, SHAM removes sham MAP flips in every family while also reducing strict fact transitions to zero in every family. In seed `20260929`, the largest sensitivity loss is in vibration monitoring (`81.8% → 0.8%`) even as sham flips fall (`96.6% → 2.2%`).

## Secondary response-matrix observations

- The frozen `B-DUP minus B-MATCHED` sham-L1 benefit was `−0.134922`, `+0.032537`, and `+0.006921` by seed (positive means lower sham L1 for B-MATCHED). Thus matched-local support did not improve sham locality consistently over DUP.
- The frozen `B-DUP minus B-MATCHED` matched-neutral-L1 benefit was `−0.003310`, `+0.026477`, and `+0.094357` by seed; matched-neutral MAP-flip benefits were `22.5`, `0.0`, and `18.4` points.
- The frozen cross-perturbation L1 interaction was `−0.130602`, `−0.006112`, and `−0.116324` by seed. This is descriptive only and does not rescue the failed primary sensitivity gate.
- Broad NewTight, legacy evaluation, and Phoenix were not accessed. No checkpoint selection, extra training, calibration, or follow-on experiment occurred.

## Interpretation boundary

The E1 result does not support the preregistered localized-control claim. The selected SHAM views can produce much lower response to the held-out sham than the radius-matched `neutral_4`/`neutral_5` views, but that reduction co-occurs with large or complete losses of fact-flip transition performance in key seeds. The result is best classified as **sensitivity/locality coupling with strong seed dependence**. It does not establish that radius explains the effect, nor that semantic identity or representation direction caused the residual.

`B-DUP` is a dose control, not a control for novel support or gradient-correlation structure. `B-MATCHED` represents only the prospectively selected controls with common radius support. The residual SHAM–MATCHED contrast is conditional on that basis; no claim extends to arbitrary invariant semantic changes.

## Post-seal descriptive decomposition: where strict transitions were lost

This addendum reads separate, already-frozen components of the E1 analysis. It does not change the primary estimand, thresholds, predictions, or sealed machine analysis. Strict old→new transition requires both an anchor prediction of the old winner and a fact-view prediction of the new winner, so the two component rates help distinguish failure modes.

| Seed | Arm | Anchor old-winner MAP | Fact-view new-winner MAP | Strict transition | Mean new-winner Δp |
|---|---|---:|---:|---:|---:|
| 20260927 | B-MATCHED | 64.70% | 100.00% | 64.70% | 0.24458 |
| 20260927 | B-SHAM | 50.00% | 0.00% | 0.00% | 0.00738 |
| 20260928 | B-MATCHED | 100.00% | 0.00% | 0.00% | 0.00720 |
| 20260928 | B-SHAM | 100.00% | 0.00% | 0.00% | 0.00506 |
| 20260929 | B-MATCHED | 95.45% | 100.00% | 95.45% | 0.26768 |
| 20260929 | B-SHAM | 75.15% | 97.05% | 72.20% | 0.25962 |

The decomposition refines the seed-level reading:

- **Seed 20260927:** broad response collapse. Under B-SHAM, both anchor old-winner MAP and fact-view new-winner MAP deteriorate; the fact probability movement falls from `0.24458` to `0.00738`. By family, the B-SHAM fact-view new-winner rate is zero in all four families. This is not merely a strict-transition bookkeeping loss.
- **Seed 20260928:** low-response terminal basin in both arms. Both retain 100% correct fact direction, but neither reaches the new-winner MAP; new-winner probability movement is near zero in both. Strict-transition and direction therefore tell different parts of the story.
- **Seed 20260929:** substantial fact movement remains (`0.26768` vs `0.25962`), and fact-view new-winner MAP remains `97.05%` under B-SHAM. The strict-transition reduction is instead concentrated in anchor old-winner preservation, especially vibration monitoring (`81.8%` to `0.8%`); in that family, fact-view new-winner MAP is `100%` in both arms. Salinity also contributes a smaller fact-view loss (`100%` to `88.2%`). This is consistent with a changed mapping between anchor boundaries and fact-view winners, not a uniform scalar-amplitude collapse. It does not identify the underlying mechanism.

These are terminal-checkpoint decompositions only. They do **not** reveal whether the coupling arose early or accumulated across epochs. Evaluating epoch 1/2 checkpoints would be a separate, newly authorized post-hoc evaluation; it is not included in E1 and no checkpoint trajectory claim is made here.

## Provenance and sealed artifacts

- E1 opening-2 receipt SHA-256: `8400f4013ad34670d540dcfa6a5ba0a3796465a5123b4995e2198af60b74c6ca`
- E1 candidate-basis seal SHA-256: `f3469f326200d1c097969be1d36741e2b01cc7542911ce79c5b240dc5b6c2b33`
- Target-free join manifest SHA-256: `5d9b851b61a305091a6489df6f7a3b09b02dd70c043d2554f17e9487f6544003`
- Held-out panel seal SHA-256: `425cef320df94e2b47b448203f8a916ebcbb2019539b2d09e51f5b4ced92f614`
- Training checkpoint tree SHA-256: `add6dfd013c936b100e7cbdb205018bf91b95e91ed11ca854b26aed998c66923`
- Frozen analysis contract SHA-256: `0072c44903ea253cd8ad288cda8c100270f19d909ddced098af32d388ac29e1f`
- Raw predictions SHA-256: `0f4acf9cffa9b70cc87bf55eb5e4b2e6f04b612986a87ff0521ae622ab63cc0a` (`72,000` rows)
- Raw prediction hash tree SHA-256: `04a05dafabe8a46954d5352378cc9e3e63aca5f266a53c6160f5c563827908af`
- Frozen analysis output SHA-256: `cd1c5578ff10420cec3e596ffa2f60cd5962c60633e79c29bc2dc871a2cf93f2`
- Final E1 result seal SHA-256: `a23b3a6dc90a739888ae8d1cab440ac6c8f6ed23dd12b26c1bfd7786cd56ce68`

The original Phase-B incomplete disposition was not modified. E1 is post-registered, not retroactively preregistered. There is no authorization for another training or evaluation phase.

Machine-readable full response matrix and paired bootstrap report: [E1 analysis JSON](</D:/codex-runs/jev-information-density-v08n-e1/v0.8N-E1-postregistered-repaired-heldout-evaluation-v01/e1-analysis-v01.json>). Raw predictions and integrity receipts are sealed alongside it in the E1 output directory.
