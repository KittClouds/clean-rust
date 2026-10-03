# JEV v0.8Q-R2: Paired late-SHAM weight intervention

## Result

After a common SHAM-1.0 training history through step 80, each of 24 seeds was
forked into matched 1.0- and 0.5-weight continuations for steps 81–120. On the
fresh, fixed-family panel, halving the late SHAM weight shifted several
decision-boundary coordinates, but did not provide a clean gain/locality
control. The response remained strongly seed-dependent.

The primary estimand is the paired, within-seed step-120 difference
`HALF − 1X`. Seeds—not neighborhoods—are the 24 observed trajectory units.
Numbers below summarize those 24 realized paired effects descriptively; they
are not estimates of a seed-population law.

| Coordinate | Mean paired effect | Median paired effect | Seed signs (+ / − / 0) |
|---|---:|---:|---:|
| Strict old→new transition | +6.91 pp | 0 pp | 10 / 2 / 12 |
| Fact-view new-winner rate | +7.30 pp | 0 pp | 10 / 1 / 13 |
| Anchor old-winner rate | +3.44 pp | 0 pp | 8 / 5 / 11 |
| Correct-direction rate | −1.39 pp | 0 pp | 3 / 2 / 19 |
| Fact-induced new-candidate probability movement | +0.00228 | −0.00076 | 4 / 20 / 0 |
| Fact-view new-vs-best-competitor winner gap | +0.03653 | +0.03284 | 23 / 1 / 0 |
| Fact-conditioned old/new pairwise-margin movement | −0.00009 | −0.00283 | 4 / 20 / 0 |
| Sham posterior L1 (larger is less invariant) | +0.00824 | +0.00120 | 22 / 2 / 0 |
| Matched-neutral posterior L1 (larger is less invariant) | +0.00521 | +0.00087 | 19 / 5 / 0 |
| Anchor NLL (larger is worse) | +0.01046 | +0.01604 | 20 / 4 / 0 |

The average transition-rate gain is real in the observed paired runs but is not
typical of their median: half the seeds have exactly zero strict-transition
difference, and the largest positive changes contribute heavily to the mean.
The strict-transition effects range from −24.5 pp to +53.9 pp. Fact-new-winner
effects range from −24.5 pp to +55.8 pp.

## What moved—and what did not

The most consistent geometric change was an increase in the multiclass
fact-view winner gap: it was positive in 23 of 24 seeds. That did **not** mean
that the intended candidate's probability movement consistently increased.
The mean change in fact-induced new-candidate probability movement was only
+0.00228, its median was negative, and it decreased in 20 of 24 seeds. The
fact-conditioned old/new pairwise-margin movement was also negative in 20
seeds. Thus the result is not well described as “half weight increases gain.”
The multiclass standing of the new candidate improved much more consistently
than its probability movement or its pairwise response relative to the old
candidate. This points to broader competitor geometry as a measurement target,
not to an established mechanism.

The locality cost was more consistent: sham L1 increased in 22/24 seeds and
matched-neutral L1 increased in 19/24. Anchor NLL worsened in 20/24 seeds even
though the mean old-winner rate rose. Winner preservation and probability
calibration therefore remain distinct coordinates.

Family summaries were heterogeneous rather than a stable family rule. The
mean paired strict-transition changes were +4.0 pp for exposure, +0.4 pp for
respiratory, +16.4 pp for salinity, and +6.8 pp for vibration; each family had
large seed-to-seed ranges. These descriptive summaries do not justify
family-specific training policy.

## State moderation

The preregistered secondary step-80 landmark analysis used 24 seed-level
paired effects within each family. All four family intervals for
`fact_new_winner_gap → new_probability_delta` included zero. Of the four
`anchor_old_winner_gap → anchor_old_map` intervals, only respiratory excluded
zero (slope per 0.1 gap: +0.335; descriptive paired-seed bootstrap interval
[+0.001, +1.225]). The interval is broad, and this is one result among eight
family-specific descriptive relationships. It is a follow-up hypothesis, not
a validated moderator or a usable intervention rule.

## Interpretation and next research move

R2 identifies a late-only effect conditional on the common SHAM-1.0 history:
changing the multiplier affects the resulting multiclass boundary, and often
weakens both sham and matched-neutral locality. But the effect does not move
all coordinates together, and step-80 measurements did not yield a general
state-conditioned rule. This does not support fitting a controller or calling
0.5 a universal operating point.

The next useful question is narrower than another dose sweep: **does the
late-weight effect improve the intended candidate's standing by increasing
its probability, by changing which alternative is the strongest competitor,
or by moving the anchor and fact views together?** A follow-up should resolve
competitor identity and class-wise probability redistribution on a new paired
trajectory set, keeping the already tested 1.0-versus-0.5 late fork fixed.
That would distinguish target-response gain from broader multiclass
reallocation before attempting state-conditioned control.

Scope: this is conditional on these 24 paired trajectories, their shared
step-80 SHAM-1.0 histories, and fresh worlds drawn from the same four families
and fixed templates. It does not establish effects for a full-course half
weight, new families/templates, a causal mechanism, or a controller.

## Reproducibility

- Frozen result report: [`q-r2-results-v01.md`](D:/codex-runs/jev-information-density-v08q-r2-late-branch-v01/evaluation-v03/q-r2-results-v01.md)
- Machine-readable analysis: [`q-r2-analysis-v01.json`](D:/codex-runs/jev-information-density-v08q-r2-late-branch-v01/evaluation-v03/q-r2-analysis-v01.json)
- Independent replay: 120 cells; 960,000 prediction rows; 240,000 metric rows; 29 coordinates; 696 paired effects. Status: `Q_R2_INDEPENDENT_RESULT_REPLAY_PASS`.
- Completion seal: `q-r2-completion-seal-v06.json`; artifact-root SHA-256 `95e95ce58602a8c47923a05dfd6af2d8eb303b9456e866a6a6a708dff17bc464`.
- Raw prediction SHA-256: `39c3fd8fccbf0a53897ae780b2ddff0bbbf25df2016230d428ed8dea49c11f2c`.
- Panel opening count: 1. Training, panel, predictions, and frozen analysis were not changed during verifier/final-seal repairs.

The independent replay exposed an exact-float comparison bug in nested
bootstrap intervals. A versioned verifier adapter applied the existing
`1e-12` tolerance recursively; 58,757 nonidentical numeric leaves differed by
at most `2.22e-16`. A later completion-manifest path alias was deduplicated in
a seal-only finalizer. Failed attempts remain preserved; neither correction
changed scientific inputs, predictions, metrics, or the analysis contract.
