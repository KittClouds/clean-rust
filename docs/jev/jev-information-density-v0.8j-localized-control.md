# JEV v0.8J — Localized Capability Control

Status: Phase B complete; no follow-on experiment authorized.

Protocol: `jev-information-density/v0.8j-phase-b-v01`

Contract SHA-256: `2e461a7750d334d354c799a5eae9975502254068d23ddccbf2aa584d146a601f`

Objective-graph SHA-256: `99408b2aedb03c53c10f0aadb86e59bc26c4bdde2a402d9ac9d9017819cb541e`

## Executive result

The explicit anchor↔sham invariance relation learned the intended direction of
control—sham movement became much smaller—but it also suppressed the useful
fact-flip response. The preregistered localized-control criterion is **FAIL**:
J11 did not reduce sham L1 and sham MAP flips in all three paired seeds, and
strict fact-flip transitions fell by 25.7 percentage points on average versus
J10.

The result supports **suppression/invariance control**, not localized control.

No adaptation, hyperparameter search, bank change, or follow-on experiment is
authorized by this result.

## Sealed execution

- Phase-A identity: `phase-a-v01-clean`
- Parent Phase-A identity: `phase-a-v02-clean`
- Backbone: frozen `LiquidAI/LFM2.5-1.2B-Base`
- Revision: `7453bca97ca1e67754c4035a4b4c584e1c9dd725`
- Head: dynamic MLP, projection width 128, 590,081 trainable parameters
- Training: AdamW, lr 0.002, weight decay 0.01, batch 256, exactly 3 epochs
- Seeds: 20260927, 20260928, 20260929
- Runs: 12 arms × seeds; 36 epoch checkpoints
- Backbone contact: frozen feature extraction only
- Phoenix access: false
- Evaluation bodies opened only after all terminal checkpoints were sealed

All four arms used the same primary rows and the same 5,000 auxiliary sham
views. The only treatment difference was the objective graph:

| Arm | Sham pointwise target | New anchor↔sham edge |
| --- | ---: | ---: |
| J00 | no | no |
| J10 | yes | no |
| J01 | no | yes |
| J11 | yes | yes |

The inherited 4,982 v0.8I invariance events were active identically in every
arm.

## Primary direct contrast panel

Values below are terminal epoch-3 means across the three optimization seeds.
The direct panel contains 2,000 held-out triplets from four families.

| Arm | Strict old→new transition | Sham L1 | Sham MAP flip | Exact fact-direction |
| --- | ---: | ---: | ---: | ---: |
| J00 | 0.5313 | 0.3245 | 0.6127 | 1.0000 |
| J10 | 0.8325 | 0.0924 | 0.1685 | 1.0000 |
| J01 | 0.5587 | 0.3295 | 0.6465 | 1.0000 |
| J11 | 0.5753 | 0.0573 | 0.0213 | 1.0000 |

The primary factorial contrast is J11−J10:

| Metric | Seed 1 | Seed 2 | Seed 3 | Mean |
| --- | ---: | ---: | ---: | ---: |
| Strict fact transition | −0.5415 | −0.2075 | −0.0225 | −0.2572 |
| Sham L1 | −0.0505 | +0.0101 | −0.0648 | −0.0351 |
| Sham MAP flip | −0.3460 | +0.0555 | −0.1510 | −0.1472 |

Thus the invariance edge lowered sham movement in two of three seeds, but not
all three. It also substantially reduced strict fact-flip transitions in the
first two seeds. The exact-direction metric is 1.0 for every arm and seed and
therefore does not discriminate this suppression; strict transition and
probability-magnitude metrics are the informative sensitivity measures here.

The conditional locality panel does not rescue the result: because exact
fact-direction was 1.0 everywhere, conditioning on that event leaves the
sample unchanged. Conditioning on strict old→new transitions makes J11 look
more invariant partly because J11 produces far fewer such transitions.

## Four factorial contrasts

The reports retain all prospective contrasts:

- C1: J10−J00, sham labels beyond the base objective
- C2: J01−J00, relation alone
- C3: J11−J10, relation beyond sham labels
- C4: J11−J01, labels beyond the relation

No global arm ranking or composite score is used. The full values are in
`factorial-effects.json`.

The most stable direct pattern is C1: pointwise sham supervision lowered sham
drift and usually preserved or improved strict fact sensitivity. C3 lowered
sham drift further on average, but with unstable seed behavior and a large
sensitivity cost.

## Family transfer

Mean terminal strict-transition rates by family:

| Family | J00 | J10 | J01 | J11 |
| --- | ---: | ---: | ---: | ---: |
| exposure control | 0.6607 | 0.6647 | 0.4147 | 0.9273 |
| respiratory monitoring | 0.6927 | 0.9993 | 0.6733 | 0.6700 |
| salinity control | 0.6893 | 0.6707 | 0.9713 | 0.3333 |
| vibration monitoring | 0.0827 | 0.9953 | 0.1753 | 0.3707 |

Vibration remains a useful stress family rather than a result to average away.
J10 nearly solves its strict transition rate, while J11 reduces its sham flip
rate but retains much weaker sensitivity than J10.

## NewTight collateral capability vector

Terminal means across seeds on the unchanged NewTight surface:

| Arm | Choice accuracy | Choice Brier | Applicability accuracy | Applicability Brier | Ordinal exact | Ordinal adjacent | Ordinal RPS |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| J00 | 0.1277 | 0.1881 | 0.7902 | 0.0504 | 0.1641 | 0.5447 | 0.02050 |
| J10 | 0.1587 | 0.1909 | 0.7899 | 0.0472 | 0.1658 | 0.5876 | 0.02228 |
| J01 | 0.1334 | 0.1890 | 0.7894 | 0.0509 | 0.1750 | 0.5821 | 0.01846 |
| J11 | 0.1371 | 0.2015 | 0.7902 | 0.0542 | 0.1030 | 0.4737 | 0.02418 |

J10 improves mean choice accuracy by 3.10 percentage points versus J00, with
slightly worse choice Brier. J11 does not preserve that choice gain and is
worst on choice Brier and the ordinal panel. Applicability accuracy is nearly
unchanged, while J11 has worse applicability NLL/Brier on average.

Ordinal expected-rank Spearman means are −0.0453, 0.0788, 0.2099, and −0.1068
for J00, J10, J01, and J11 respectively. This is another clear collateral
tradeoff rather than a scalar improvement.

## Schema binding and intervention geometry

Mean contradictory-binding drift over the three terminal seeds:

| Arm | Paired L1 drift | Argmax flip rate |
| --- | ---: | ---: |
| J00 | 0.1297 | 0.2643 |
| J10 | 0.1431 | 0.2891 |
| J01 | 0.1603 | 0.3184 |
| J11 | 0.1038 | 0.2910 |

J11 lowers mean binding L1 but does not lower the mean flip rate versus J00;
this is mixed evidence, not a binding claim.

On NewTight intervention rows, mean observation-intervention Pearson
correlation is 0.1315, 0.1049, 0.1266, and 0.1029 for J00/J10/J01/J11. Mean
world-intervention correlation is −0.0551, 0.0168, −0.0161, and −0.0415.
The objective-graph treatment therefore does not produce a broad intervention
geometry improvement.

## Disposition

| Question | Result |
| --- | --- |
| Does sham pointwise supervision help? | Yes, most clearly in direct sham drift and often in strict fact sensitivity. |
| Does the relation alone help? | It does not reliably improve locality; sensitivity and sham movement remain unstable. |
| Does the relation add beyond sham labels? | It reduces sham movement on average, but fails the all-seed criterion and suppresses strict fact response. |
| Is localized control supported? | **No.** |
| Is suppression/invariance control observed? | **Yes, with a sensitivity tradeoff.** |
| Is broad capability improvement established? | **No.** |

This completes v0.8J Phase B. No LoRA/QLoRA, lambda sweep, new contrast
family, bank regeneration, or follow-on experiment is authorized by this
result.
