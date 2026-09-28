# Adaptive Runtime — AR-02 Graduation Record

Date: 2026-09-20
Status: sealed / graduated. Engineering-only, synthetic toy tasks; no biological correspondence and no general optimizer claim.

AR-02 is closed. The evidence-architecture result is retained as the primary finding. The path-source branch is retained as a bounded dynamical observation, but its genericity and any special advantage of runtime-selected transitions remain unresolved or unsupported, respectively. No further AR-02 experiments are authorized by this record.

## Main result: utility-response-homogeneous verification strata

The strongest AR-02 result is that a useful verifier partition groups examples with similar candidate-transition utility responses. For a candidate transition (a), let (u_a(x)) be its per-example utility and (h(x)) the stratum. When the partition reduces within-stratum response variance, equal-allocation stratified sampling reduces verifier-estimator variance and error:

```text
meaningful strata
    -> lower within-stratum variance of candidate-example utility
    -> lower finite-population estimator variance
    -> lower observed utility-estimation RMSE and decision error
```

The frozen AR-02A-R2 panel audit compared cell and class-by-Bayes-margin strata against eight equal-quota hash-placebo partitions on the same 48-example budget. Cell stratification reduced utility RMSE from `6.216e-4` (placebo mean) to `4.332e-4`, sign error from `29.80%` to `21.85%`, cross-block regret from `5.395e-4` to `4.126e-4`, selected-program regret from `6.686e-4` to `5.073e-4`, and false authorization from `20.68%` to `14.24%`. Cell stratification beat the placebo mean on RMSE and sign error at all nine audited seed/snapshot states.

The diagnostic variance sidecar then supplied the mechanism. Exact finite-population variance predicted observed panel RMSE closely:

| Construction | Predicted RMSE | Observed RMS panel RMSE |
| --- | ---: | ---: |
| Cell, four per true cell | `5.312e-4` | `5.371e-4` |
| Class × Bayes-margin, four per stratum | `5.953e-4` | `6.080e-4` |
| Hash placebo, mean over eight partitions | `7.090e-4` | `7.077e-4` |

The cell partition's mean within-stratum utility-variance component was `43.8%` below the placebo mean; the margin partition's was `29.5%` below. Predicted and observed panel RMSE differed by a mean `3.65%` relative across the 108 state/method rows. This supports the bounded mechanism that these prospective task-informed strata reduce candidate-utility heterogeneity and thereby improve estimation.

This is not proof that variance reduction alone caused the full-training trajectory gains, that these particular labels are generally available, or that arbitrary stratification helps. The audit conditions on nine dependent states and a frozen candidate universe. The original AR-02A 16-example stratifiers did not outperform random; the corrected R1/R2 evidence shows coverage benefits are conditional on evidence budget and useful stratum contents. Independent verification itself transferred strongly relative to same-batch reuse.

## Path-source branch: bounded observation, no selected-state privilege

The path-source experiments measured whether two nearby initial states have different relative loss consequences under frozen future programs generated from each state. For states (A,B), define

```text
Delta(P) = L(A, P) - L(B, P)
I = Delta(P_A) - Delta(P_B)
```

where (P_A) and (P_B) are state-generated continuations. A nonzero (I) is a source-by-continuation interaction; its sign does not imply that either state wins under either path.

AR-02B-R1 and AR-02C-TANH observed negative active-path means in all contributing seeds (8/8 and 7/7, respectively), with the effect also present under smooth `tanh`. This supports retaining a bounded observation that state-generated continuations can alter the relative consequences of nearby states, and that ReLU gating is not necessary for the measured phenomenon. It does not establish a universal direction or optimization advantage.

AR-02D was the predeclared generic-source / selected-state-excess control. Its primary D1 exact-displacement domain produced only 13 triplets across seven streams and a near-zero, mixed contrast: pooled `I_GC = -8.115e-7`, `I_CC = +1.453e-6`, and `I_GC - I_CC = -2.265e-6`; seven of thirteen paired comparisons were ties. The secondary D2 magnitude-only domain was suggestive in aggregate but heterogeneous across seeds and comparisons, so it cannot rescue D1. The proposed monotonic ancestor-path ordering was uncommon.

Disposition:

- **AR-H45 — state-generated continuations can alter relative consequences:** retained as a bounded phenomenon across the tested synthetic substrates/activations.
- **Generic source-conditioned compatibility:** unresolved. AR-02D did not establish that nearby states generally favor their own source paths.
- **AR-H46 — selected-state excess compatibility:** not supported under the strongest declared exact-displacement-matched test.

Do not reinterpret D2, widen matching tolerances, rematch on outcomes, or add checkpoints to rescue either claim. AR-02D's full frozen protocol and integrity receipts are authoritative.

## Integrity and scope

The component experiment records remain authoritative and unchanged:

- [AR-02A — Gaussian-cell portability](ar-02a/README.md)
- [AR-02A-R1 — corrected weighting and evidence-size oracle](ar-02a-r1/README.md)
- [AR-02A-R2 — placebo-strata audit](ar-02a-r2/README.md)
- [AR-02A-R2-VAR1 — finite-population variance sidecar](ar-02a-r2-var1/README.md)
- [AR-02B-R1 — independent-seed path-source crossover](ar-02b-r1/README.md)
- [AR-02C-TANH — smooth-activation diagnostic](ar-02c-tanh/README.md)
- [AR-02D — generic source-conditioning null](ar-02d/README.md)

All claims remain engineering-only and specific to the tested synthetic setups. They do not establish benchmark superiority, a general optimizer, or biological correspondence.

## Stop decision and next-family boundary

AR-02 is sealed. Do not run AR-02E, add more D checkpoints/seeds, widen match tolerances, or continue mining the same Gaussian substrate for a preferred path-source result.


The next proposed family, **AR-03**, is evidence-architecture only and has not started. Its question is whether observable, outcome-independent features can approximate partitions that make candidate-example utility responses homogeneous, without privileged synthetic latent labels. Any future diagnostic should retain random and hash-placebo controls and evaluate utility-estimator error on held-out candidate actions/states so the proposed partition does not simply memorize the responses it is meant to predict. No proxy, controller, or training experiment is selected or authorized by this graduation record.
