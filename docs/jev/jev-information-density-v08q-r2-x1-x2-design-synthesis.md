# JEV Q-R2 / X1 / X2: criterion, discriminability, and next design

## Disposition

Q-R2, X1, and X2 remain closed. This note adds one design-only calculation from the already sealed Q-R2 prediction matrix; it does not amend their registered analyses or conclusions. No head was loaded, no inference was run, and no new panel was opened for the calculation.

The design question is now whether the late HALF branch changes a common old/new preference on the anchor view, or changes fact discrimination between anchor and fact-flip views. On the log-odds scale, for each of the 24 paired step-80 histories:

\[
B_h = [\log(p_{new}/p_{old})_{fact}-\log(p_{new}/p_{old})_{anchor}]_{1X},
\]
\[
C_h = [\log(p_{new}/p_{old})_{anchor}]_{HALF-1X},
\]
\[
D_h = [\log(p_{new}/p_{old})_{fact}-\log(p_{new}/p_{old})_{anchor}]_{HALF-1X}.
\]

Probabilities were parsed as float64 and transformed as `ln(p_new) - ln(p_old)` with no clipping, smoothing, or rounding. A nonpositive or nonfinite required probability would have stopped the calculation; none occurred.

## Actual design-only values

Each history value is the equal-family mean over 2,000 neighborhoods (500 per family). Variation is across the 24 realized common-history seeds, not a population estimate.

| Coordinate | Mean | Median | Across-history SD | Positive / negative histories | Range |
|---|---:|---:|---:|---:|---:|
| Baseline fact-minus-anchor separation, B (1X) | +0.504051 | +0.153494 | 0.665937 | 24 / 0 | [+0.010866, +1.972186] |
| Anchor old/new contrast shift, C (HALF−1X) | +0.132564 | +0.121990 | 0.148451 | 20 / 4 | [−0.092471, +0.709689] |
| Fact-selective contrast shift, D (HALF−1X) | −0.017285 | −0.009877 | 0.055327 | 4 / 20 | [−0.168299, +0.108905] |

The baseline B distribution is strongly right-skewed: its mean is 0.504051 while its median is 0.153494. HALF's anchor-side old/new log-odds shift is positive in 20/24 histories, but this is only a pairwise contrast; X2 found anchor old-target MAP accuracy increased from 90.71% to 94.15%. Do not turn C into a claim of global criterion movement or anchor-preservation loss.

The typical fact-selective D is slightly negative, not positive: median −0.009877, with 20/24 histories negative. The mean (−0.017285) is also negative on this scale. This is consistent with the probability-scale result that the typical history is flat or slightly negative on selectivity; it is not evidence that HALF improves fact discrimination.

The within-history, family-stratified neighborhood SE estimate is tiny relative to history variation in this fixed panel. For D, its median was 0.0000364, while the across-history sample SD was 0.055327 (about 1,522 times larger). This comparison is descriptive and conditional on treating neighborhoods as the within-history measurement units in this panel; it is not a population estimate. For a replication, spend added compute on more paired histories before enlarging an already-large neighborhood panel.

## Post-hoc scale pattern: design hypothesis only

The per-history values suggest different behavior across baseline-separation ranges. The following groups use the **step-120 1× baseline B** and visible gaps in these 24 observed histories; they are post hoc and must not be reused as prospective strata or promoted to a replicated result. For each history, \(S_{HALF}=B+D\) and \(R=\log(S_{HALF}/B)\). All 24 observed ratios are defined and positive.

| Pilot-only B group | n | Median C (range) | Median D/B (range) | Median R (range) | D signs (+/−) |
|---|---:|---:|---:|---:|---:|
| Weak, B < 0.10 | 12 | +0.1255 (+0.1031 to +0.1727) | −0.1176 (−0.2793 to −0.0639) | −0.1251 (−0.3276 to −0.0661) | 0 / 12 |
| Moderate, 0.21 ≤ B ≤ 0.61 | 6 | +0.1402 (−0.0524 to +0.1833) | −0.1567 (−0.1993 to −0.0819) | −0.1706 (−0.2222 to −0.0854) | 0 / 6 |
| Strong, B > 0.99 | 6 | +0.0258 (−0.0925 to +0.7097) | +0.0125 (−0.0990 to +0.0552) | +0.0124 (−0.1042 to +0.0538) | 4 / 2 |

This is a useful hypothesis: C looks approximately additive in the weak/moderate pilot groups, while D/B and R are consistently negative there; the strong group is mixed and carries most of the dispersion. It is not yet evidence for an additive-criterion/multiplicative-sensitivity mechanism. In particular, D and B share the observed 1× endpoint, and the bins were selected from that endpoint. The ratio is denominator-sensitive, and conditioning on endpoint B risks regression-to-the-mean and mathematical-coupling artifacts. An A/A continuation check can measure continuation variability, but the prospective moderator must be measured at the common step-80 fork.

### Equivalence-margin scale

If the study chooses the proposed 10%-of-baseline-separation anchor, using 10% of the **median** B gives a candidate \(\delta=0.015349\) natural-log-odds units. Using 10% of the mean would instead give 0.050405, more than three times larger because B is skewed. The candidate is not a frozen threshold: justify the fraction in task terms and lock it before collecting fresh histories.

If the primary estimand is median history-level D, estimate its interval by resampling whole paired histories and call practical equivalence only when the entire predeclared interval lies inside \([-\delta,+\delta]\). Do not call that TOST. TOST is appropriate only for a separately declared mean estimand. A nonsignificant difference is not equivalence.

## Architecture and generator audit

The frozen `CompatibilityHead` applies the same state projection, candidate projection, and shared scoring function independently to each candidate. There are no slot-specific parameters or position embeddings. Permuting the candidate axis therefore permutes scores with the candidates; softmax and the candidate-aligned loss preserve that symmetry. Output slot is not a substantive causal factor for this head, except that exact ties may be resolved by the frozen ordering convention. Keep a candidate-order permutation sanity check, but do not spend a full factorial axis on slot.

The current generator does **not** counterbalance polarity. Its anchor is built with focus `+`, its fact flip with focus `−`, and the validator requires the exact winner to move from candidate index 0 to index 1. In all four evaluation families, candidate 0 is the high-pole label and candidate 1 is the low-pole label. Thus the current construction always makes the low pole the `new` target. A prospective study must explicitly support and validate both high→low and low→high transitions, balanced within family; do not infer reversed polarity from an output permutation.

The current fixed panel nests candidate identity and wording within family, and each high/low pole has one fixed semantic identity. Reversing fact-flip direction lets each existing high/low identity serve as `old` and `new` and separates a `new`-role-following shift from a low/high-pole-following shift. It does **not**, by itself, identify an identity-specific prior independently of pole meaning. If that distinction is required, include multiple independently validated lexical/semantic realizations per pole within family and cross them prospectively; otherwise limit the claim to role-following versus pole-following effects and report fixed candidate identities descriptively. Preserve the same anchor and fact-flip views. Add an answer-preserving placebo only if its semantics can be specified independently and cleanly before training.

## Next study: selective response under counterbalanced roles and polarity

Keep the late paired intervention at 1.0× versus 0.5× after a common history; do not sweep doses or fit a controller. Break the current confounding among semantic role, candidate identity, and high/low polarity. Slot is a symmetry check, not a treatment factor under the frozen scorer.

Record raw logits prospectively. Use the fixed old/new logit contrast as the primary score scale:

\[
C = \Delta_{HALF-1X}[\ell_{new}-\ell_{old}]_{anchor},
\qquad
D = \Delta_{HALF-1X}\left(([\ell_{new}-\ell_{old}]_{fact})-([\ell_{new}-\ell_{old}]_{anchor})\right).
\]

Report median history effects and sign counts first, then mean and the complete history distribution. Keep anchor old-target MAP, anchor old/new margin, fact MAP crossing, strict transition, and all candidate-aligned score changes separate. Do not use a moving strongest-competitor order statistic as the primary contrast.


The R2 variance decomposition argues for more independent paired histories, not more neighborhoods. Use the observed history distribution only as a pilot for a prospective precision simulation; do not present the 24 histories as a population law. A 48-history cohort is a planning candidate, not a sufficiency claim; the strong-regime prevalence under a polarity-balanced training history is unknown. Do not define prospective strata using step-120 B. Use continuous \(S_{80}\) as the primary pre-branch moderator; if categories or S80-based enrichment are needed, freeze their cutpoint and target weighting before branch outcomes. Enrichment changes the sampled history mix, so report stratum-conditional effects and use the prespecified sampling weights for any pooled target.

Balance both high→low and low→high fact transitions within family in the **training stream as well as evaluation**. This makes the successor a deliberately cleaner experiment, not a literal replication of R2's high→low-only training history. Keep one-identity-per-pole/family attribution out of scope unless additional semantic realizations are crossed.

Because \(R=\log(S_{HALF}/S_{1X})\) requires positive, non-negligible separations in both branches, freeze \(S_{min}\), the eligibility rule, and the treatment of non-evaluable ratios before training. Do not decide eligibility from observed endpoint values and then silently omit histories: for every history report signed \(S_{1X}\), signed \(S_{HALF}\), additive \(D\), whether each separation clears the floor, and any sign reversal. Define a coverage rule in advance for when a cohort-level median-\(R\) claim is reportable; if coverage fails, report the ratio estimand as not estimable for the contracted cohort and retain the complete signed-separation analysis. Keep the pre-treatment \(S_{80}\) moderator distinct from ratio eligibility. If continuation is not bitwise deterministic, use a preselected subset with a crossed dose × continuation-replicate design (1× and HALF under each of two paired continuation streams); it supplies both an A/A repeat and replicate-specific HALF−1× contrasts. If it is deterministic, record an exact duplicate-continuation check and omit the redundant RNG factor.

For a median-R hypothesis of more than 10% attenuation, support requires the upper endpoint of the predeclared history-bootstrap interval to be below \(\log(0.9)=-0.10536\). Practical equivalence within a 10% multiplicative band instead requires the full median-R interval inside \([\log(0.9),\log(1.1)]=[-0.10536,+0.09531]\). The history is the resampling unit. Freeze the bootstrap and the analysis hierarchy in advance; a nonsignificant test is not equivalence. The study does not by itself authorize a controller.

If “approximately constant additive anchor shift” is a confirmatory claim, define it with a predeclared practical slope/equivalence region for \(C\) versus continuous \(S_{80}\); a positive median alone does not establish constancy. Likewise, treat increased strong-state heterogeneity as descriptive unless the study is sized for a frozen dispersion comparison. Do not use the pilot’s endpoint-defined B groups as prospective S80 cut points. If S80-based enrichment is used, define the target stratum and sampling design before branching, report stratum-conditional effects, and use the corresponding design-weighted quantile for any pooled median.

## Boundaries and provenance

The R2 log-odds values are reconstructed from sealed finite-precision probabilities, not raw logits. They identify the pairwise log-odds contrast under softmax, but prospective work should save logits directly. The fixed R2 construction cannot distinguish role, identity, slot, family, or polarity effects; the architecture audit removes slot as a meaningful axis for this head, while the generator audit confirms polarity still must be broken.

Design-only sizing output root: `5d9df69d42885ae64d3b312b4d385f3d92b96c022aca1f8aea95b043611e89c4`.

Inputs were the sealed raw prediction SHA-256 `39c3fd8fccbf0a53897ae780b2ddff0bbbf25df2016230d428ed8dea49c11f2c` and Q-R2 completion seal SHA-256 `5e5fd8a6b5d8255c57a480b9da4334307cf195bb07cf9cc6c0b200242f8abac4`. The complete per-history table and machine-readable summaries are in the sealed sizing report under `D:/codex-runs/jev-information-density-v08q-r2-late-branch-v01/evaluation-v03/criterion-discriminability-sizing-v01/`.
