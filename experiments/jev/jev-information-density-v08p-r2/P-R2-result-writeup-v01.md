# JEV v0.8P-R2 — Fresh-Panel Trajectory Result

**Disposition:** `POST_REGISTERED_V08P_R2_FRESH_PANEL_TRAJECTORY_RESULT_SEALED`  
**Scientific scope:** a fresh-world/fresh-rendered-input draw under the fixed four families and p0–p3 measurement interface. This is not novel-family or novel-template generalization, and it does not complete the closed original v0.8P line.

## Bottom line

On the fresh R2 panel, all nine runs began the step-80-to-120 interval with zero fact-view new-winner MAP rate and zero strict old-to-new transitions. Small, directionally correct fact-probability movement became detectable early in the interval in every arm/seed. But the discrete transition was treatment- and seed-dependent:

- **DUP:** persistent fact-new-MAP and strict-transition events appeared in all three seeds, at steps 105, 85, and 110.
- **MATCHED:** they appeared only for seed `669993655`, at step 108.
- **SHAM:** neither event appeared in any seed by step 120.

At step 120, SHAM had the lowest sham L1 in all three paired seeds, but also zero fact-new-MAP and zero strict transitions in every seed. Its fact-view direction was correct on 100% of neighborhoods in all three runs, while new-winner probability movement remained only 0.0032–0.0099 and exact-delta MAE remained 0.366–0.372. That is a small response in the correct direction, not acquisition of the requested MAP behavior.

This is evidence of a pronounced locality/response-magnitude tradeoff in these fixed runs. It is not a mechanism result, a population estimate over seeds, or evidence that an intermediate checkpoint is a validated operating point.

## Experiment and integrity

The frozen recipe used three arms (`B-DUP`, `B-MATCHED`, `B-SHAM`), three new paired seeds (`3243871208`, `669993655`, `3076094663`), nine complete 120-step training runs, and the frozen LFM2.5-1.2B-Base representation revision `7453bca97ca1e67754c4035a4b4c584e1c9dd725`. The backbone remained frozen; the dynamic MLP had width 128 and 590,081 trainable parameters. The sealed fresh panel contains 2,000 neighborhoods (500 per fixed family) and 22,000 episodes. The checkpoint set was step 40, step 80, and every step 81–120: 42 trained snapshots per run, 378 total, plus three shared initialization baselines.

Every prescribed checkpoint was evaluated; no checkpoint was selected or promoted. The complete 3,048,000-row prediction set was sealed before metrics and event times were computed; the analysis produced 762,000 neighborhood-metric rows across 381 cells. It used the frozen neighborhood-level shared bootstrap plan, family order, linear quantile rule, simultaneous bands, and onset definitions. No NewTight, legacy evaluation, or Phoenix access occurred.

The primary result is descriptive at the fixed fresh panel, conditional on each of the three optimizer seeds. The families and templates remain fixed. It does not establish performance on new families or templates.

## Terminal metrics at step 120

Rates are percentages except L1, probability movement, exact-delta MAE, NLL, and Brier. `A_old` is anchor old-winner MAP rate; `F_new` is fact-view new-winner MAP rate; `Strict` requires both jointly on the same neighborhood. No composite score is used.

| Seed | Arm | Sham L1 | Sham MAP flip | Matched L1 | Matched MAP flip | A_old | F_new | Strict | New-winner Δp | Exact-Δ MAE | Anchor NLL | Anchor Brier |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 3243871208 | DUP | 0.147051 | 71.20% | 0.090253 | 50.65% | 73.30% | 100.00% | 73.30% | 0.151306 | 0.224659 | 1.351287 | 0.054322 |
| 3243871208 | MATCHED | 0.022721 | 0.00% | 0.003809 | 0.00% | 100.00% | 0.00% | 0.00% | 0.027709 | 0.348256 | 1.332348 | 0.043203 |
| 3243871208 | SHAM | 0.003684 | 0.00% | 0.001548 | 0.00% | 75.00% | 0.00% | 0.00% | 0.003175 | 0.372790 | 1.341995 | 0.049630 |
| 669993655 | DUP | 0.204153 | 9.35% | 0.121970 | 9.25% | 59.30% | 62.75% | 44.75% | 0.218552 | 0.157413 | 1.309738 | 0.032846 |
| 669993655 | MATCHED | 0.112909 | 41.85% | 0.009585 | 1.00% | 51.25% | 49.00% | 48.50% | 0.179330 | 0.196635 | 1.345723 | 0.054475 |
| 669993655 | SHAM | 0.009210 | 0.00% | 0.003218 | 0.00% | 75.00% | 0.00% | 0.00% | 0.009920 | 0.366045 | 1.335288 | 0.045392 |
| 3076094663 | DUP | 0.140985 | 25.00% | 0.084039 | 11.55% | 85.65% | 74.30% | 74.30% | 0.119541 | 0.256424 | 1.315060 | 0.033799 |
| 3076094663 | MATCHED | 0.012128 | 0.00% | 0.002309 | 0.00% | 75.00% | 0.00% | 0.00% | 0.006848 | 0.369117 | 1.336456 | 0.046330 |
| 3076094663 | SHAM | 0.006081 | 0.45% | 0.003492 | 0.00% | 75.00% | 0.00% | 0.00% | 0.004546 | 0.371419 | 1.343602 | 0.050954 |

Two patterns are robust across these three observed seeds: SHAM has markedly lower endpoint sham L1 than its paired alternatives, and SHAM never produces a fact-view new-winner MAP transition. The size of the sensitivity effect is not uniform: DUP produces strong transitions in seeds 1 and 3 and a mixed result in seed 2; MATCHED produces a substantial transition only in seed 2.

## Where the sampled transition occurs

The following are the frozen descriptive onset labels relative to step 80. `Δp rise` is a simultaneous-band/persistence event for continuous probability movement. It is not a MAP-transition event. `F_new` and `Strict` are the first persistent MAP events under the contracted rule.

| Seed | Arm | Fact Δp rise | Anchor old-MAP loss | Persistent F_new | Persistent strict |
|---:|---|---:|---:|---:|---:|
| 3243871208 | DUP | 83 | Not observed by 120 | 105 | 105 |
| 3243871208 | MATCHED | 87 | Not observed by 120 | Not observed by 120 | Not observed by 120 |
| 3243871208 | SHAM | 81 | 89 | Not observed by 120 | Not observed by 120 |
| 669993655 | DUP | 81 | 82 | 85 | 85 |
| 669993655 | MATCHED | 84 | Not observed by 120 | 108 | 108 |
| 669993655 | SHAM | 84 | Not observed by 120 | Not observed by 120 | Not observed by 120 |
| 3076094663 | DUP | 81 | Not observed by 120 | 110 | 110 |
| 3076094663 | MATCHED | 85 | Not observed by 120 | Not observed by 120 | Not observed by 120 |
| 3076094663 | SHAM | 87 | 84 | Not observed by 120 | Not observed by 120 |

Thus the fresh trajectories do **not** show one common late acquisition event. Continuous probability changes are detectable near the start of the final interval, while robust MAP crossings—when they occur—arrive later and vary by arm and seed. SHAM’s probability movement also begins early, but it stays too small to create the new fact-view winner. An onset label is a property of the sampled checkpoint path under the fixed band rule, not the unobserved instant when a capability “came into existence.”

### Locality along the SHAM path

SHAM’s endpoint locality advantage should not be mistaken for a newly emerging step-81-to-120 invariance gain. Sham L1 at step 80 was already low for SHAM (`0.001377`, `0.001871`, `0.001516` by seed); at step 120 it was `0.003684`, `0.009210`, `0.006081`. The contracted event detector recorded a sham-L1 increase at step 81 for all three SHAM trajectories and no sustained decrease by step 120. SHAM remained much more locally invariant than the other arms at the endpoint, but this specific late window mostly preserved a low-response state rather than progressively learning greater sham invariance.

For contrast, DUP’s step-80 to step-120 sham L1 rose from `0.005410` to `0.147051`, `0.048577` to `0.204153`, and `0.012787` to `0.140985` across the three seeds, as fact response developed. MATCHED’s own-view locality remained comparatively low at step 120 (`0.003809`, `0.009585`, `0.002309`), although its fact-MAP outcome varied sharply by seed.

## The four-cell decomposition matters

Cell order below is `(A_old & F_new, A_old & not F_new, not A_old & F_new, not A_old & not F_new)`, as percentages. It separates failure to preserve the anchor from failure to respond to the changed fact.

| Seed | Arm | Four cells (%) |
|---:|---|---|
| 3243871208 | DUP | (73.30, 0.00, 26.70, 0.00) |
| 3243871208 | MATCHED | (0.00, 100.00, 0.00, 0.00) |
| 3243871208 | SHAM | (0.00, 75.00, 0.00, 25.00) |
| 669993655 | DUP | (44.75, 14.55, 18.00, 22.70) |
| 669993655 | MATCHED | (48.50, 2.75, 0.50, 48.25) |
| 669993655 | SHAM | (0.00, 75.00, 0.00, 25.00) |
| 3076094663 | DUP | (74.30, 11.35, 0.00, 14.35) |
| 3076094663 | MATCHED | (0.00, 75.00, 0.00, 25.00) |
| 3076094663 | SHAM | (0.00, 75.00, 0.00, 25.00) |

All SHAM runs end with 75% anchor old-winner preservation, 0% fact new-winner rate, and therefore 0% strict transitions. Family stratification shows that the 75% anchor rate is exactly 100% in exposure, respiratory, and salinity and 0% in vibration for each SHAM seed; fact new-winner rate is zero in every family. This is a striking repeated family pattern in this panel, not proof of a family-general mechanism.

The directional diagnostic prevents an overly simple “no learning” account: SHAM’s correct fact direction is 100% in all three terminal runs, but its new-winner probability shifts are small and its exact-delta errors remain high. In these runs, direction is present without adequate response magnitude or the contracted MAP outcome.

## Interpretation

The clean result is **coupled shaping, with seed- and family-dependent boundary outcomes**:

1. SHAM is associated with far smaller posterior movement under the sham perturbation at the endpoint than DUP, and also smaller movement than MATCHED in all three seeds.
2. The matched-neutral arm shows that equal-radius local support does not yield one uniform trajectory: it preserves strong matched-view locality in all seeds, but only one seed crosses to the fact-view winner.
3. SHAM keeps fact movement directionally correct but suppresses its magnitude enough that no seed reaches the new MAP winner. That is consistent with suppression/coupling, not successful localized control.
4. DUP supplies the clearest fact-MAP acquisition in two seeds, with substantial locality loss. The third DUP seed is mixed and loses anchor preservation in several families.
5. MAP behavior is family-structured: for SHAM, vibration is the consistent anchor-preservation failure. Do not collapse that into a single sensitivity scalar.

This fresh draw therefore supports the practical warning from E1/O: locality and fact response are not independently controlled by the current pointwise recipe. It does **not** isolate semantic identity from displacement direction, text/edit location, or higher-order representation geometry, nor establish a universal optimizer-basin story. The three seeds are three trajectories, not an estimate of the seed-population distribution.

## What the result suggests next

Do not extend the step window, promote a convenient checkpoint, or simply run more of the same recipe. P has answered the timing question at the contracted resolution: measurable probability changes start early, but the useful MAP transition is arm/seed-specific and absent under SHAM in this fresh panel.

The next useful experiment should test a **single prospective intervention aimed at preserving SHAM’s locality while restoring response amplitude**, with MATCHED and DUP retained as controls. A predeclared lower auxiliary SHAM dose or less frequent SHAM event schedule is a plausible hypothesis, but choose one intervention and its exact rule before training; do not sweep doses or select an epoch from these held-out trajectories. Keep anchor preservation, fact-new MAP, continuous movement, and both locality channels as separate outcomes. If the priority is instead to explain the vibration-specific anchor failure, make that a separate training-side diagnostic using no new held-out-guided selection.

No result here licenses an “optimal training duration,” checkpoint selection, or a capability-mechanism claim. Any intermediate step that looks favorable remains an unvalidated observation and would need a new prospective test.

## Provenance and limits

- Original v0.8P remains closed/unexecutable under its incomplete overlap schema; R2 is a fresh successor identity, not retroactive completion.
- R2 trained and sealed all nine runs before opening the fresh evaluation panel. The single R2 opening and all prediction outputs are receipt-bound.
- Two evaluator implementation failures were preserved. The target-free panel feature scope initially lacked a target field; it was joined by exact episode identity from the sealed exact-world source, not by candidate slot. A later scope-index mismatch occurred after one common initialization head was deserialized but before any model forward; the failed prediction output remained zero rows. The evaluator was corrected with an episode/role index adapter, tested on synthetic fixtures, and the complete prediction matrix was then produced. No predictions or treatment metrics existed when these corrections were authored; the frozen metric and analysis identities remained bound in the final seal.
- Training telemetry remained descriptive and did not guide evaluation or checkpoint choice. No NewTight, legacy, or Phoenix access occurred.

## Reproduction bindings

| Artifact | SHA-256 |
|---|---|
| Run contract | `e345225b4a17fc18eb35fcab24cbe1d72bd0e34bed9de272f927a7be461853e6` |
| Analysis contract | `84111122033fda65c84344317cfe3b50639b23be4c71f480ba665c67a23cc939` |
| Analysis addendum | `4cd14671ffe7c032864fdc0bd5f75db1d1edea666cc58eb43aae0e6c820d0431` |
| Training checkpoint hash tree | `a901890434000dcb928fabe3e0eee0d1ab9cd6d7744b0d02f26d04456ea15c21` |
| Raw prediction hash tree | `80facbd2fd4ecaa967ea85013a81370a75adc9f3008132535cc72293eaa3d505` |
| Raw predictions | `6338c54b160d8e0e357085f8215d75235c7be9a71be124110fb3637d7f12c0e7` |
| Response matrix | `98c8ba0659fdaba4f6a78923650348b24b40f1716f795914b6a4f1816119217d` |
| Event-time analysis | `59d6b5e5e44dcfae9854237ef62a82b12daac4a20b786f9ad0fd0cfb8aa9ce01` |
| Frozen metric implementation | `dbde07fe1ec009f2bca7f1f22ad913a2a79f4f8dfb8120a1f31ebf37d5f59b70` |
| Sealed P-R2 result receipt | `5007168cac89c4cd8c0765f1188f2ef4516b941757037585744489a966a4ed3e` |

The canonical run-output write-up is `D:\codex-runs\jev-information-density-v08p-r2\v0.8P-R2\evaluation\v08p-r2-trajectory-results-v01.md`; the full response matrix and event-time JSON are alongside it. This shareable analysis is an interpretive companion; it does not alter the sealed result artifacts.
