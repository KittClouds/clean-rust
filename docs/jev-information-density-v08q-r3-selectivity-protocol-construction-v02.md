# JEV v0.8Q-R3: Selectivity Protocol Construction v02

**Status:** protocol construction; unsealed. Outcome-blind generator, step-80/step-120 calibration, replay, and sizing work are complete. No confirmatory panel, HALF branch, treatment metric, or R3 scientific result exists.

## Decision context

Q-R2, X1, and X2 remain closed. R3 is a prospective successor, not a literal replication: it balances high→low and low→high polarity in training and evaluation, measures the moderator before the late-dose branch, and tests role-following versus pole-following effects.

The primary measurement is a history-level response, not a neighborhood-level sample size. Neighborhoods reduce measurement error within a history; independent training histories determine precision for the treatment response.

## Completed outcome-blind work

### Balanced generator and calibration substrate

- The v02 calibration panel contains 2,000 neighborhoods and 4,000 anchor/fact rows. The four families are balanced across both polarities: 250 neighborhoods in each family × direction cell.
- Candidate admission consumed a fixed seed stream and rejected 52 candidates online. All 4,000 admitted model-visible view identities are unique. The earlier v01 panel with duplicate rendered identities is preserved as a failed construction attempt and is not used.
- Balanced training inputs contain 10,000 primary occurrences and 5,000 auxiliary SHAM rows; high→low and low→high exposure is balanced overall and within family to the generator's prospective allocation rule. Reverse-polarity SHAM targets were validated in their own semantic orientation.
- Frozen LFM extraction produced panel, candidate, and reverse-SHAM feature caches under the pinned revision `7453bca97ca1e67754c4035a4b4c584e1c9dd725`, using `mean_full@16`, BF16 backbone, FP32 2,048-dimensional output. Independent repeat maximum absolute error was `0.0`; model identity before/after matched. No head was loaded during extraction.
- The failed v01 and v02 construction/adapter attempts remain preserved. The final v02 panel, v03 balanced-input sidecars, v01 feature cache, v03 preflight, and v02 calibration-training artifacts are the only promoted calibration inputs.

### Pre-treatment (S_{80}) calibration

Forty-eight new common SHAM-1.0 histories were trained through step 80 on the balanced-polarity stream. Their checkpoints and telemetry were sealed before the calibration panel was read. They contain no HALF continuation and are prospectively excluded from the confirmatory cohort.

For each history, (S_{80}) is the equally weighted mean over four families × two polarity directions of:

\[
([\ell_{new}-\ell_{old}]_{fact}-[\ell_{new}-\ell_{old}]_{anchor}),
\]

with `new` and `old` assigned by semantic transition role, not pole, identity, or storage slot.

Observed calibration distribution (48 histories):

| Statistic | (S_{80}) |
|---|---:|
| Minimum | 0.000563 |
| 10th percentile | 0.004903 |
| 25th percentile | 0.006352 |
| Median | 0.009556 |
| 75th percentile | 0.016148 |
| 90th percentile | 0.028558 |
| 95th percentile | 0.053489 |
| Maximum | 0.838549 |

Twenty-four of 48 histories were below 0.01, 39/48 below 0.02, 45/48 below 0.05, and 3/48 at or above 0.05. One extreme history accounts for much of the raw-scale standard deviation (`0.11975`). The central 10th–90th percentile span is `0.023656`.

Within-history measurement precision is not the limiting factor: median SE `7.94e-6`, maximum SE `3.68e-4`, and the estimated reliability ratio is `0.99999978`. The between-history distribution is highly right-skewed, however, and its upper tail is estimated from only 48 histories. Use (S_{80}) continuously; do not import the old endpoint-derived “strong” cut or turn these 48 calibrators into confirmatory histories. The confirmatory analysis should report leverage/influence diagnostics for the raw-(S_{80}) slope without trimming or excluding histories.

### Step-120 1× ratio-floor feasibility check

After the step-80 S80 summary was sealed, all 48 calibration histories were continued through steps 81–120 at the unchanged 1.0× SHAM multiplier. The continuation restored each sealed model, AdamW, scheduler/event cursor, and RNG state. Exact same-fork replay had already passed under this runtime. No HALF branch was created. All 48 terminal checkpoints and telemetry were sealed before the target-free calibration-panel summary.

The first summary adapter stopped before loading a head because it expected panel view label `fact_flip`; the authoritative panel schema uses `fact`. Its failed receipt is preserved. A versioned target-free reader used the actual `anchor`/`fact` labels, reused the sealed terminal checkpoints, read no target fields, and wrote no row-level predictions. No training was repeated and no confirmatory panel was accessed.

Observed step-120 1× semantic-role separation (48 excluded calibration histories):

| Statistic | S120, 1× |
|---|---:|
| Minimum | 0.011725 |
| 5th percentile | 0.038774 |
| 10th percentile | 0.046770 |
| 25th percentile | 0.070082 |
| Median | 0.300142 |
| 75th percentile | 1.059622 |
| 90th percentile | 1.629525 |
| 95th percentile | 1.887515 |
| Maximum | 2.163512 |

All 48/48 1× baseline separations exceed both candidate floors, 0.01 and 0.004. For the conservative 0.01 floor, calibration baseline support is 48/48; its Wilson 95% interval is 92.6%–100%, above the 173/192 requirement at the lower endpoint. This establishes that low 1× denominator separation is not the likely reason for failing R coverage under the calibrated stream. It does **not** guarantee joint ratio eligibility: HALF must also remain positive and above the floor, which this check deliberately does not measure.

Within-history measurement SE for S120, 1× has median `0.000181` and maximum `0.000987`; 0.01 is `10.13×` the largest observed SE. The lower 0.004 option is only `4.05×` that maximum and is not needed to make the 1× side feasible. Recommendation: retain S_min = 0.01, with the fixed 173/192 joint eligibility rule. If future HALF branches make the ratio ineligible, record that as an observed limitation rather than lowering the floor after outcomes.

The calibration median S120, 1× = `0.300142` is well above 0.01, so a null D is not expected to be an aggregate low-baseline floor artifact under these calibration conditions. Preserve the proposed per-run floor interpretation: if the confirmatory median S1X is below 0.01, an interval for D containing zero means insufficient baseline discrimination to assess attenuation, not evidence of no effect. Descriptively, S80 and S120, 1× correlate at `r=0.387` with raw-scale OLS slope `2.105`; this is calibration-only and is not a treatment moderation result.

Sealed step-120 calibration root: `D:\codex-runs\jev-information-density-v08q-r3-selectivity-v02\calibration-s1x-terminal-eval-v02\root-seal.json`, result SHA-256 `cd50ec49d5d2196cc92df0bb18276f2d10643d2cc5dc12b928dc6459bea16fab`, root `a6fd2b857a9b7b42dde965ccf57b7106d44b26c2d0e3b41876b8bedd8913bdea`.

### Continuation replay

Two clean processes resumed the same sealed step-80 checkpoint (seed `4064846075`) at cursor 80, restored the complete optimizer and RNG state, and executed the same 40-step 1.0× SHAM continuation using the frozen third-epoch schedule and auxiliary batches.

The final head, optimizer, RNG tree, telemetry, and serialized final checkpoint hashes were identical across the two processes. Final checkpoint SHA-256 in both replicas: `88e86eb5bbdb7aec767611a4bdd41e86d1ce7a19f54de4e90c55c34ad76192d3`. This establishes exact replay under the tested runtime and implementation; omit the redundant A/A continuation control. It does not prove replay on a different device/runtime.

### Design simulation

The outcome-blind simulation resampled complete histories from the sealed 24-history Q-R2 design-only table, crossed those scenarios with the 48 calibrated balanced-training (S_{80}) values, and ran 5,000 outer cohorts per scenario. It is a planning sensitivity analysis, not a prediction that balanced R3 effects follow R2.

- For median intervals, the narrowest symmetric order-statistic interval with at least 95% binomial coverage was more reliable than the percentile whole-history bootstrap under the heavy-tailed pilot. At (N=96), the order-statistic interval covered the empirical pseudo-population median in 96.1–97.5% of replicates across C/D/R. Bootstrap coverage was 94.6–96.4%; its median interval was only 0.8–4.1% narrower at (N=96). Keep the order-statistic interval as the frozen median method; no outcome-dependent method switch.
- The fixed sequence is simulated as (M>0), median (D<0), eligible median (R<0), then β≠0. Under the R2-resampling planning scenario, the median tests are already precise by (N=48); that is not a claim of R3 power under balanced training.
- The simulation directly records the probability that the median-(R) interval's upper endpoint is below zero. Under the 10%-attenuation R2 pseudo-scenario this is 91.3% at (N=24) and 100% at (N=48); under the zero-effect scenario the corresponding false-positive probability is 1.0% at both sizes. The fixed-sequence probability through the (R) decision at (N=24) is 85.0% under 10% attenuation and 1.0% under the null; at (N=48) it is 100% and 1.0%, respectively. These are conditional planning characteristics under R2-resampled histories, with all histories assumed ratio-eligible; they are not expected R3 performance.
- For the moderation simulation, the task-scale scenario is a direct `D ~ S80` change of `0.005` log-odds across the calibrated 10th–90th percentile span (`0.023656`). At (N=96), HC3 interval exclusion of zero was about 60%; at (N=192), about 90%; null rejection stayed near 5%. This supports **192 balanced histories** if the moderation slope remains confirmatory. The result is sensitive to the sparse extreme upper tail and must be treated as conditional on this calibration distribution.
- A candidate (S_{min}=0.01) log-odds floor, about ten times the worst prior terminal-history SE in Q-R2, yielded a median ratio-eligible fraction around 95.8% in the R2 pseudo-population. At (N=96), at least 90% ratio coverage occurred in about 99% of simulated 10%-attenuation cohorts; at (N=48), about 95%. This supports a **90% cohort coverage reporting gate**, but does not guarantee R3 coverage. Keep full-cohort signed (S_{1X}), (S_{HALF}), and universal (D) regardless.
- The new balanced-training 1× calibration removes the main baseline-floor concern: 48/48 step-120 (S_{1X}) values exceed 0.01, with a 92.6% Wilson lower bound for calibration-history support. This is only the necessary 1× side of the ratio; joint coverage still depends on the unobserved HALF branch.
- The proposed practical-equivalence band for (R) remains \([\log(0.9),\log(1.1)]\). Attenuation is an interval upper bound below zero, not below \(\log(0.9)\). The pilot's “more than 10%” threshold is retired as a confirmatory decision.

Simulation root: `D:\codex-runs\jev-information-density-v08q-r3-selectivity-v02\design-simulation-v03\design-simulation-seal.json`, output SHA-256 `e098f44cbe0cf7c95395f3559451221d71b9946fa7208961f8460849690c89f5`.

## Proposed R3 protocol locks

### Scientific design

- Common history: SHAM-1.0 through step 80; fork from the complete model, AdamW, scheduler, event cursor, and RNG state.
- Balanced primary cohort: 192 fresh history seeds. Exactly two continuations per history, 1.0× and 0.5× SHAM, through step 120; only the auxiliary multiplier differs.
- Checkpoints: step 80 pre-branch, step 100 descriptive, step 120 primary. No other evaluation checkpoint.
- A separate **24-seed paired polarity bridge** is recommended: for a preselected subset of the balanced seeds, add a high→low-only training-history counterpart under the same R3 generator, panel, architecture, event budget, optimizer, and late branches. Treat the training-polarity comparison as secondary. This is the direct within-R3 comparison needed to assess whether a missing role/pole shift under balanced training is attributable to training polarity rather than the other differences from R2. It does not turn R3 into a literal R2 replication.
- Use a fresh confirmatory panel, disjoint from training, E1, P-R2, Q, the R3 calibration panel, and prior admitted R3 neighborhoods on every contracted identity field. Balance family and polarity. The calibration panel and 48 calibration histories are never confirmatory inputs.
- Candidate permutation remains a symmetry sanity check only. Semantic identity remains nested within pole/family unless alternate realizations are added; no identity-specific claim.

### Estimands and polarity decomposition

For each history, compute balanced semantic-role (C^{H\to L}), (C^{L\to H}), (D^{H\to L}), and (D^{L\to H}), equally averaging the fixed four families within direction. Preserve each family/direction cell.

\[
M_C=\tfrac12(C^{H\to L}+C^{L\to H}),\quad
P_C=\tfrac12(C^{H\to L}-C^{L\to H}).
\]

\[
M_D=\tfrac12(D^{H\to L}+D^{L\to H}),\quad
P_D=\tfrac12(D^{H\to L}-D^{L\to H}).
\]

`M` is role-following; `P` is low-pole-following. Report both per history with intervals. (M_C) is the first confirmatory coordinate; (P_C) is secondary. Record logits and all candidate-aligned ℓ_j-ℓ_old values.

The universal discrimination estimand is signed (D=S_{HALF}-S_{1X}) for every history. It is defined and reported for the full cohort, including histories with sign reversals or weak baseline separation. The proportional characterization is:

\[
R=\log(S_{HALF}/S_{1X}),
\]

only when both signed separations are positive and at least (S_{min}). Report signed branch separations, (D), sign reversal, ratio eligibility, and (R) when eligible for every history. Recommended lock: (S_{min}=0.01), minimum eligible coverage 90%. Since eligibility depends on both observed branch separations, (R) is explicitly a conditional estimand among histories for which both branches are positive and above the floor—not an estimate for the full cohort. Report the eligible fraction, every ineligible history and reason, and the signed branch values and (D) for all histories. If coverage is below 90%, label (R) `NOT_ESTIMABLE_FOR_COHORT`; do not headline a surviving-subset result. Passing the coverage gate does not erase the conditional scope or authorize extrapolation to ineligible histories.

For median (R): attenuation if the 95% interval upper endpoint is below 0; practically unchanged only if the entire interval lies inside \([\log(0.9),\log(1.1)]\); otherwise inconclusive. Report magnitude and interval, not a thresholded 10%-loss decision.

For median (D), use the same signed order-statistic interval to classify negative, positive, or inconclusive relative to zero. **Do not call an interval containing zero “practically unchanged.”** A separate additive practical-equivalence claim requires a task-justified δ_D; the current packet has not established one. Do not borrow the relative (R) band for (D).

### Moderator and intervals

- (S_{80}) remains semantic-role-oriented, evaluated on the complete fresh panel after all training artifacts are sealed. It is measured from the common step-80 head before late branching; no step-120 conditioning.
- Primary moderation: (D_h=\alpha+\beta S_{80,h}+\epsilon_h). Test β≠0; do not interpret β as a proportional attenuation fraction. Report β per calibrated 10th–90th percentile (S_{80}) span for scale, plus raw-scale coefficient and influence diagnostics. The estimated (S_{80}) measurement-error reliability ratio is `0.99999978`; the raw upper tail remains sparse, so report leverage/influence without trimming.
- Associations of (M_C) or (P_C) with (S_{80}) are descriptive only. Do not claim a constant (C) offset or use a confirmatory (C)-versus-(S_{80}) slope/equivalence test in this protocol.
- Use the symmetric order-statistic/sign-inversion interval for history medians, choosing the narrowest order interval with at least 95% binomial coverage. Freeze family order as exposure, respiratory, salinity, vibration and use the shared family × polarity cell weights. Use a two-sided 95% HC3 interval for β; no flexible moderator model.
- Fixed-sequence confirmatory order: (1) median (M_C>0); (2) median (D<0); (3) eligible median (R<0), subject to the 90% coverage gate; (4) β≠0. (P_C), equivalence, family patterns, bridge contrasts, and heterogeneity remain secondary/descriptive. Report all histories and signs; no population-law claim.
- The (0.005) log-odds change across the calibration (S_{80}) 10th–90th percentile span is a sizing scenario, not a pass threshold. Calibration shows why raw moderator influence must be reported: its SD is dominated by one rare extreme history.

### Execution and firewall

Construct and seal the fresh confirmatory panel and feature cache; verify the full schedule and both training regimes; train all common histories and registered branches without evaluation feedback; seal all checkpoints and telemetry; open the panel once; produce and seal all predictions; run the fixed analysis; independently replay; seal the result. Exact continuation replay passed, so no A/A stream is included. No dose sweep, checkpoint selection, rescue, adaptive policy, extra family treatment, NewTight, Phoenix, or post-result R2 mining.

**Confirmatory R3 training/evaluation remains unauthorized.** The work completed here is instrument/calibration/design construction only.

## Lock review before sealing

The evidence supports a concrete proposal: 192 balanced histories, a 24-history paired high→low bridge, (S_{min}=0.01), 173/192 joint ratio eligibility, median order-statistic intervals, and the stated fixed sequence. The step-120 calibration supports the 1× side of this floor; the HALF side remains unknown and must not be presumed eligible. Include the bridge because otherwise disappearance of (C) under balanced training cannot be attributed to training-polarity balance within R3; keep this bridge secondary and report its uncertainty, since the current simulation did not establish bridge power. Preselect its 24 seed/init pairs before training. The one conceptual correction is that (D) cannot have a practical-equivalence label without an additive task-scale margin. This memo resolves that by reserving “practically unchanged” for the conditional relative (R) estimand, while (D) remains universal and signed.

If these proposed values are adopted, bind the run, panel, and analysis contracts together and authorize one complete phase-sized execution. No more archaeology or calibration is indicated by the current evidence.

## Provenance roots

- Balanced calibration panel generation receipt: `D:\codex-runs\jev-information-density-v08q-r3-selectivity-v02\calibration-panel-v02\panel-generation-receipt.json`.
- Balanced feature cache seal: `D:\codex-runs\jev-information-density-v08q-r3-selectivity-v02\calibration-features-v01\feature-cache-seal-v01.json`, root `bd040d4b22eb3ba4098a593746cf8dcab9409e82b2359ddc185723c657db9e36`.
- 48-history pretraining schedule root: `fb962c44dfbb6c869957f54439cedec223159d88a427bbe44c7d6be641650795`.
- Sealed step-80 training tree: `5521b0a82b231dbe47e7b9f2235a8758f4ef29dbf4945c56ac6512e134c9150f`.
- Sealed S80 summary: `841a11b9f8d79e1a0353a38fb1fa38cb5b1a575039b952404a176679ef9f1e78`.
- Same-fork replay root: `55c2297843876bbf502485af28e3810742ed509bbe6ef2d307323552d7e90abe`.
- 48-history step-120 1× checkpoint tree root: `2ec37b7f57a039025f62705c9342993d0b61ed7e4c6c76e36422ed5d3fc77caf`.
- Target-free step-120 calibration result root: `a6fd2b857a9b7b42dde965ccf57b7106d44b26c2d0e3b41876b8bedd8913bdea`.
- Sizing simulation output: `e098f44cbe0cf7c95395f3559451221d71b9946fa7208961f8460849690c89f5`.
