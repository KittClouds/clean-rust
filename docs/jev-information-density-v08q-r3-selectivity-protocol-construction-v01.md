# JEV v0.8Q-R3: Selectivity Protocol Construction

**Status:** design draft; not sealed; no new training or confirmatory evaluation authorized by this document.

## Decision

Q-R2, X1, and X2 are closed. Do not reopen their prediction matrix for further substantive analysis and do not run another dose sweep or fit a controller.

The next study is a new successor identity, provisionally `JEV-v0.8Q-R3`, testing whether the late 0.5× SHAM intervention changes an anchor-side criterion-like contrast and fact discrimination differently when candidate role and polarity are counterbalanced. It is not a literal replication of R2: training polarity will be balanced in R3, whereas R2 training always taught high-to-low flips.

The protocol should be completed as one execution packet. Successful construction and calibration steps advance automatically; stop only on a concrete invariant failure or at the final scientific result. Do not create a new authorization pause after every receipt.

## Pilot facts used for design, not as confirmatory evidence

The sealed R2 sizing artifact contains 24 history-level values. Its post-hoc groups were cut using step-120 1× separation, not a pre-treatment variable:

| Pilot-only endpoint group | n | Median C | Median D/B | Median R | D positive / negative |
|---|---:|---:|---:|---:|---:|
| B < 0.10 | 12 | +0.1255 | −0.1176 | −0.1251 | 0 / 12 |
| 0.21 ≤ B ≤ 0.61 | 6 | +0.1402 | −0.1567 | −0.1706 | 0 / 6 |
| B > 0.99 | 6 | +0.0258 | +0.0125 | +0.0124 | 4 / 2 |

In the first two pilot groups, C is generally positive while proportional discrimination change is negative; the strong group is mixed. These groups and their apparent prevalence are hypotheses only. Do not use endpoint B cut points as R3 strata or assume the strong-group prevalence transfers to polarity-balanced training.

The source is the sealed design-only sizing artifact, root `5d9df69d42885ae64d3b312b4d385f3d92b96c022aca1f8aea95b043611e89c4`. Its 24 histories are not a population estimate.

An initial empirical-resampling sensitivity screen sampled those 24 paired \((C,R)\) histories with replacement as a pseudo-population. For each simulated cohort, it formed a 95% percentile interval for the median from 1,000 whole-history bootstrap replicates; there were 500 simulated cohorts per N, NumPy linear quantiles, PCG64 seed `20260929`. No \(S_{min}\) was applied because it is not frozen; all 24 pilot ratios are positive. This is not confirmatory power and does not represent the balanced-polarity R3 history distribution.

| Histories N | P(C median interval lower > 0) | P(R median interval upper < log(0.9)) | P(R median interval inside ±10% band) | Median R interval width |
|---:|---:|---:|---:|---:|
| 48 | 1.000 | 0.104 | 0.008 | 0.0593 |
| 96 | 1.000 | 0.168 | 0.004 | 0.0447 |
| 192 | 1.000 | 0.210 | 0.000 | 0.0277 |
| 384 | 1.000 | 0.378 | 0.000 | 0.0224 |
| 512 | 1.000 | 0.502 | 0.000 | 0.0209 |

The pilot median R is −0.113945, only 0.008585 below the −10% boundary. Under this deliberately simple pseudo-population, C's positive-median decision is easy, while the attenuation decision is not; equivalence is not expected because the pseudo-population median lies outside the equivalence band. This warns against declaring 48 histories sufficient; it does not recommend 512. The balanced-polarity calibration and a scenario grid are needed before fixing N. The R2 sizing artifact has no role-oriented step-80 moderator, so this screen says nothing about S80-slope precision.

## Scientific question and claim boundary

After a common balanced-polarity SHAM-1.0 history through step 80, what is the paired effect of changing only the auxiliary SHAM multiplier to 0.5 for steps 81–120 on (a) anchor old/new preference and (b) fact-minus-anchor discrimination?

The claim is conditional on this training recipe, the observed common-history states, the fixed four-family/template task distribution, and the contracted fresh evaluation panel. It is not a universal control law, full-course dose effect, mechanism claim, or novel-family/template generalization result.

## Treatment and construction invariants

- Common history: SHAM multiplier 1.0 through global step 80.
- Paired continuations: 1.0× and 0.5× for steps 81–120; only the auxiliary SHAM multiplier changes.
- Keep architecture, optimizer, event identities/count/positions, denominator, batches, schedule, initialization, and all non-dose settings fixed within each fork.
- Use a new paired history cohort and a fresh held-out panel. Keep the same task-family/template distribution unless a separately justified revision is made before sealing.
- Balance high→low and low→high fact transitions within every family in both the training stream and evaluation construction. `new` and `old` are semantic roles defined by each prospective fact transition, not aliases for low/high polarity, candidate index, or class identity.
- Preserve candidate permutation equivariance. Candidate-slot permutation is a software sanity test, not a scientific factor for this head.
- With one semantic identity per pole/family, role-versus-polarity can be tested, but identity-specific effects cannot be separated from pole/family. Keep identity attribution out of scope unless alternate validated realizations are prospectively crossed.
- The history is the independent training unit. Neighborhoods improve measurement precision within a history; they do not increase the number of independent histories.

## Frozen estimand definitions

Use raw candidate logits in R3. For history \(h\), branch \(b\), and the prospectively defined family/polarity cells, define the semantic-role-oriented score:

\[
S_{h,b} = \operatorname{balanced\ mean}\left( [\ell_{new}-\ell_{old}]_{fact} - [\ell_{new}-\ell_{old}]_{anchor} \right).
\]

The balanced mean gives equal weight to the contracted families and to high→low and low→high direction cells; it does not let larger cell counts change the estimand. Preserve cell-specific values alongside the history summary.

The universal additive estimand is:

\[
D_h = S_{h,HALF}-S_{h,1X}.
\]

Report it for every history, including sign reversals and near-zero separations.

The proportional estimand is:

\[
R_h = \log(S_{h,HALF}/S_{h,1X}),
\]

reported only when both separations are positive and above a prospectively fixed floor. For eligible histories, \(R=0\) means unchanged proportional separation; \(R<0\) means proportional attenuation. A 10% reduction boundary is \(\log(0.9)=-0.10536\); the ±10% multiplicative equivalence interval is \([\log(0.9),\log(1.1)]=[-0.10536,+0.09531]\).

Also define the anchor criterion-like coordinate:

\[
C_h = \operatorname{balanced\ mean}\left( [\ell_{new}-\ell_{old}]_{anchor,HALF} - [\ell_{new}-\ell_{old}]_{anchor,1X} \right).
\]

Keep C, D, R, anchor old-target MAP, anchor old/new margin, fact MAP crossing, strict transition, and the complete candidate-aligned logit changes separate. No composite score.

## Ratio domain and reporting rule

Before confirmatory branch outcomes are observed, freeze:

1. the numeric \(S_{min}\) and its task/measurement justification;
2. the ratio eligibility rule, applied mechanically to both branch separations;
3. the minimum eligible-history coverage required before reporting a cohort-level median-R conclusion;
4. the handling of nonpositive and below-floor values.

Every history table must include signed \(S_{1X}\), signed \(S_{HALF}\), \(D\), sign-reversal status, ratio eligibility, and \(R\) when defined. Never silently remove a history. A coverage threshold is a reporting gate, not a correction for outcome-dependent eligibility: if the median R is reported, label its eligible-history scope and show the full-cohort signed-separation outcomes and coverage next to it. If the coverage rule fails, report `R = NOT_ESTIMABLE_FOR_COHORT`; retain D for all histories.

## Pre-treatment state and polarity interpretation

At the shared step-80 fork, define the moderator in semantic-role coordinates:

\[
S_{80,h} = \operatorname{balanced\ mean}\left( [\ell_{new}-\ell_{old}]_{fact} - [\ell_{new}-\ell_{old}]_{anchor} \right)_{step80},
\]

where `new` and `old` are assigned by the prospective fact transition. Positive S80 means movement toward the designated new role on the fact view relative to anchor, regardless of which pole or identity is new.

Use continuous S80 as the primary moderator. Any categorical boundary, enrichment rule, or target mix must be frozen using pre-treatment-only calibration under the balanced-polarity training recipe. Do not condition on step-120 1× B. If the R3 histories are enriched by S80, report stratum-conditional results and define any design-weighted pooled target before branching.

To test role-following versus polarity-following C, report C separately for high→low and low→high cells within family. A role-following effect tracks the designated `new` role in both directions; a pole-following effect tracks high/low polarity despite role reversal. Candidate slot is not a factor. Candidate identity remains nested within pole/family.

## Calibration and precision plan

Before the confirmatory cohort is branched, run one prospectively specified, pre-treatment-only calibration under the balanced-polarity common-history recipe. It may measure the S80 distribution and measurement precision only; it must not create HALF-versus-1× branch outcomes or inspect prospective treatment metrics. Keep calibration histories/panel identities distinct from the confirmatory held-out panel. The calibration seed count, panel construction, S80 measurement source, and whether calibration histories may enter the confirmatory cohort must be fixed in its own input-bound protocol before execution.

Use the sealed R2 history table only as a planning scenario, not as the assumed R3 effect distribution. The precision simulation must report operating characteristics for the actual decision questions across a sensitivity grid:

- median C interval excludes zero in the positive direction;
- median R upper interval endpoint is below \(\log(0.9)\);
- median R interval is wholly inside the ±10% multiplicative equivalence band;
- uncertainty/precision for the continuous S80 moderation slope;
- representation of the observed S80 range and any prospectively defined upper stratum.

Vary the prevalence and response distribution of the high-S80 region rather than importing the R2 endpoint-group prevalence. Use whole histories as the resampling/simulation unit. Allocate additional budget to histories, not to neighborhoods once within-history measurement error is already negligible. The history-count target is not frozen until this simulation and the balanced-training S80 calibration are complete.

## C versus S80 and heterogeneity rules

If the confirmatory claim says C is “roughly constant” across S80, freeze a practical slope-equivalence interval and the slope estimator before training. A positive median C alone supports a positive typical shift, not constancy. If no defensible practical slope interval is available, phrase the hypothesis as positive median C and treat the slope as descriptive.

The strong-state heterogeneity question is descriptive unless the study is explicitly sized for a predeclared dispersion estimand and test. Do not define “heterogeneous” by inspecting whichever seed/family split looks striking.

For median C, D, and eligible-history R, use history-level summaries and whole-history bootstrap intervals. Report median and sign count first, then mean and the complete history distribution. Do not call median-interval inclusion an equivalence test unless the entire interval is contained in the predeclared equivalence region.

## Continuation replay and randomness control

Before the confirmatory cohort, test from a common step-80 state whether a continuation with the same complete checkpoint, data/event cursor, nominal seed, and implementation reproduces bit-identically in a clean process. Compare model/optimizer state and contracted checkpoint bytes, not only metrics.

- If exact replay passes, bind the replay receipt and omit a redundant A/A branch.
- If exact replay fails, characterize the stochastic sources and include a preselected crossed dose × continuation-stream control on a subset: both doses under each of two paired continuation streams from the same fork. Do not attribute an unpaired branch difference to dose alone.

Within each paired continuation stream, hold event order, minibatches, and random streams aligned as far as the implementation permits. If execution consumes random numbers differently after the branches diverge, use stateless/keyed randomness or record that limitation and preserve the crossed-stream comparison.

## Prospective analysis hierarchy

1. **Universal:** report signed S values and D for all histories; show direction/polarity/family cells.
2. **Proportional:** report R only under the frozen domain/coverage rule, with the conditional eligible-history scope explicit.
3. **Criterion-like:** summarize C and test role-following versus pole-following under polarity reversal.
4. **State moderation:** relate C, D, and eligible R to continuous, semantic-role-oriented S80 using one predeclared history-level model per coordinate. Show every history and uncertainty; no flexible predictor or controller.
5. **Equivalence:** for median R, practical equivalence requires its full predeclared history-bootstrap interval inside \([\log(0.9),\log(1.1)]\). More-than-10% attenuation requires the upper endpoint below \(\log(0.9)\). Failure to reject zero is not equivalence.

## Remaining lock items before confirmatory training

These are the five concrete values/identities that protocol construction must resolve; do not leave them as prose placeholders in the sealed packet:

1. **S80 measurement contract:** exact calibration/evaluation rows, role orientation, aggregation, and family/polarity weighting.
2. **Ratio domain:** numeric Smin, eligibility, non-evaluable accounting, and minimum coverage/reporting rule.
3. **C moderation:** slope estimator and practical slope-equivalence interval, or explicit downgrade of “constant” to descriptive.
4. **History count:** precision simulation and pre-treatment-only S80 distribution under balanced training; freeze target N, any strata/enrichment, and pooled weighting.
5. **Continuation behavior:** exact replay result and bound randomness-control implementation.

After these are resolved, seal the run, panel, and analysis contracts together. Then execute one complete phase-sized packet: fresh confirmatory panel, all common histories, paired branches, sealed training states, one contracted panel evaluation, full history-level analysis, independent replay, final result seal. No dose sweep, post-result threshold change, checkpoint selection, controller fitting, or further R2 mining.

## Provenance

Planning input: `D:/codex-runs/jev-information-density-v08q-r2-late-branch-v01/evaluation-v03/criterion-discriminability-sizing-v01/criterion-discriminability-sizing-v01.json`, SHA-256 `5d9df69d42885ae64d3b312b4d385f3d92b96c022aca1f8aea95b043611e89c4` (root). The pilot table above is design provenance only. R2 remains closed and unchanged.
