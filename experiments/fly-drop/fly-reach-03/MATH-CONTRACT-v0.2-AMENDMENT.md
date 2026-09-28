# REACH-03 v0.2 Math Contract Amendment

Status: **AMENDMENT DRAFT, PRE-CODE, NO EXECUTION**

This file amends the existing `MATH-CONTRACT.md` before any REACH-03 runner,
seed, feature collector, classifier, or measured artifact is created. The
existing draft remains preserved for provenance. No sealed identity is edited.
When REACH-03 is eventually resealed, this amendment and the parent draft must
be incorporated into one new authoritative contract and hashed together.

## 0. Evidence boundary and authoritative predecessor

The only authoritative REACH-02 empirical anchor for this contract is the
corrected v0.1b RUN2 terminal receipt:

`experiments/fly-reach-02-v0.1b/artifacts/REACH02-RUN2/REACH02-V0.1B-TERMINAL-RECEIPT.json`

Its disposition is:

`SIGN_COUNTERFACTUAL_SUPPORTED_STABLE_MASK_NOT_EXPLANATORY`

The earlier REACH-02 RUN1 is retained as a provenance and bug record only. Its
zero-reference support defect makes it **non-promotable**. RUN1 endpoint
numbers must not appear in REACH-03 scientific anchors, tables, summaries, or
interpretation text. Any earlier conflicting disposition is superseded by the
corrected v0.1b RUN2 disposition and remains non-promotable historical context.

The corrected v0.1b facts that REACH-03 may cite are bounded engineering
anchors: the oracle-sign/native-magnitude counterfactual is near sufficient;
native support captures about 0.65 of reference L1 mass while touching about
0.37 of coordinates; and the native aggregate/delivered direction is poorly
aligned. These facts do not establish a biological mechanism.

## 1. Capability-weighted polarity quality

For a native-support coordinate set (S_N^{\mathrm{signarm}}), define the
native magnitudes and reference signs by

\[
m_i = |u_{N,i}|,\qquad g_i = |g_i|y_i,\qquad y_i\in\{-1,+1\}
\]

on the nonzero reference channel. For any candidate sign prediction
(s_i\in\{-1,+1\}) emitted on every native-supported coordinate, define

\[
w_i=m_i|g_i|,
\qquad
A_w(s)=\frac{\sum_i w_i\mathbf 1[s_i=y_i]}{\sum_i w_i},
\qquad
\Psi(s)=2A_w(s)-1.
\]

With support and native magnitudes held fixed,

\[
u^\top g = \sum_i m_i|g_i|s_iy_i
          = \left(\sum_i w_i\right)(2A_w(s)-1).
\]

Therefore raw coordinate sign agreement is secondary. Every REACH-03 report
must pair extractable observability with capability-weighted polarity
quality:

* `raw_sign_agreement`: descriptive only;
* (\Psi(s)): the first-order useful signed component of the predicted update;
* the same quantities evaluated for native, reference-sign, and frozen
  predictor outputs where applicable.

The predictor does not receive (g_i\), its sign, or a hindsight zero mask.
It emits a sign for every native-supported coordinate. In offline scoring,
coordinates with (g_i=0) contribute (w_i=0) automatically. A ternary
zero/nonzero decision is a separate future experiment, not part of REACH-03.

## 2. Theoretical observability versus estimator output

The population quantity remains

\[
\Omega(\mathcal F)=
\operatorname{TV}(P_{\mathcal F\mid +},P_{\mathcal F\mid -})
\]

on the balanced nonzero target channel. A finite classifier does not estimate
Bayes TV without qualification. For frozen estimator family \(\mathcal M\),
define the operational quantity

\[
\widehat\Omega_{\mathcal M}(\mathcal F)
 = \max\left(0,1-2\widehat\epsilon_{\mathcal M,\mathrm{bal}}(\mathcal F)\right).
\]

The required name in results is **extractable observability under frozen
estimator class \(\mathcal M\)**. It is a model-class result and, absent an
independent estimator guarantee, a lower-bound-like diagnostic for the
underlying population quantity. A positive out-of-sample value demonstrates
extractable signal under the frozen estimator. A value near zero does not
prove that the information is absent; it means no signal was extracted under
the frozen estimator family and data contract.

Store the unclipped value as well as the reporting value. Clipping a negative
plug-in value to zero is only a reporting convention. Report estimator
learning curves and bootstrap uncertainty; an unsaturated learning curve is an
estimator-capacity warning.

## 3. Filtration ladder and information boundaries

The primary ladder is

\[
\mathcal F_0\subset\mathcal F_1\subset\mathcal F_2
\subset\mathcal F_{3a}\subset\mathcal F_{3b}\subset\mathcal F_4.
\]

The feature lists in the parent contract remain frozen except for this split:

* **\(\mathcal F_0\)**: static coordinate and anatomical identity only.
* **\(\mathcal F_1\)**: instantaneous local state before native delivery.
* **\(\mathcal F_2\)**: the frozen local temporal window and lag features.
* **\(\mathcal F_{3a}\)**: only signals that actually enter the native update
  mechanism at time (t): reward/DAN/feedback values, active global scales,
  and native-visible summaries actually consumed by the rule.
* **\(\mathcal F_{3b}\)**: \(\mathcal F_{3a}\) plus summaries computable
  from native state without reference information, even when the current
  native update does not consume them. This is an interface/aggregation
  boundary, not proof that the existing rule possessed and ignored the signal.
* **\(\mathcal F_4\)**: the complete deterministic inputs to
  `reference_delta_into`, including full current state and task inputs, while
  still excluding (g), its sign, and any derived reference quantity.

The primary information increments are therefore

\[
\Omega_0,
\Delta\Omega_1,
\Delta\Omega_2,
\Delta\Omega_{3a},
\Delta\Omega_{3b},
\Delta\Omega_4.
\]

Use (\Omega_{3a}) for the native-legal information claim. Use the
\(3a\rightarrow3b\) increment to identify an interface/aggregation
opportunity. Do not call a (3b)-only result a failure of a rule to exploit
information it actually received.

## 4. One common primary scoring population

The entire primary ladder must be scored on one frozen row universe
\(U^*\), not on a different maximal dataset at each level. A row
\((\text{substrate},\text{side},\text{block},i,t)\) enters \(U^*\) only if:

1. every \(\mathcal F_0\ldots\mathcal F_4\) feature vector is defined and
   finite;
2. the target is on the nonzero channel, \(Y_{i,t}\ne0\);
3. the declared native-support condition for the primary arm holds;
4. the row belongs to the predeclared scoring block and time rules.

The same rows, with the same inclusion indicators, are used for every ladder
level. Per-level maximal populations may be reported as secondary diagnostics,
never substituted into the primary increments. This makes
\(\Delta\Omega_k\) an information increment rather than a population-change
artifact.

The native-support condition is not allowed to drift between feature levels.

## 5. Exact support and magnitude semantics

The primary support is explicitly the support used by the corrected v0.1b
`sign_ref_native_mag` arm. In that arm, support is taken from the native
proposed delta before `sim.apply_delta` performs delivery and clipping:

\[
S_N^{\mathrm{signarm}}=
\{i:\text{the native sign-arm update authorizes a nonzero coordinate }i\}.
\]

With the frozen executor tolerance \(\mathrm{EPS}\), the exact operational
definition is

\[
S_N^{\mathrm{signarm}}=\{i:|\Delta_i^{\mathrm{native,proposed}}|>\mathrm{EPS}\},
\qquad
u_{N,i}=\Delta_i^{\mathrm{native,proposed}}.
\]

The sign arm preserves this support and uses

\[
m_i=|u_{N,i}|=|\Delta_i^{\mathrm{native,proposed}}|
\]

Delivered nonzero support after `sim.apply_delta` and clipping is a diagnostic
sidecar only. It must not replace \(S_N^{\mathrm{signarm}}\) in the primary
result. Eligibility support may also be reported, but it is not the primary
support.

The REACH-01 support quantity is fixed verbatim as reference L1 mass captured
on native support:

\[
\boxed{
\eta_S^{\mathrm{L1}}
 = \frac{\sum_i |g_i|\mathbf 1[i\in S_N^{\mathrm{signarm}}]}
        {\sum_i |g_i|}
}
\]

This is not a cosine and not the alternative
\(\langle u_N,g\rangle/(\|u_N\|_1\|g\|_\infty)\). The latter must not remain
as an “or exact v0.1 form” placeholder. Any authority-geometry sidecar must
reuse the exact REACH-01 definitions by name.

## 6. Exact \(\mathcal F_4\) reconstruction audit

Because \(\mathcal F_4\) contains every deterministic serialized input to
`reference_delta_into`, the contract invariant is

\[
\boxed{\Omega(\mathcal F_4)=1}
\]

on the nonzero channel, assuming lossless serialization and the frozen
tolerance \(\tau\). This is a reconstructability theorem of the contract,
not a learned scientific hypothesis.

After collection, independently recompute \(g\) from the serialized
\(\mathcal F_4\) inputs and compare the resulting \(Y\) to the stored target
with the exact/tolerance-matched rule. A learned \(\mathcal F_4\) predictor is
permitted only as estimator-capacity calibration. A weak learned
\(\widehat\Omega_4\) does not refute the invariant; it flags incomplete serialization,
underfit, leakage/label mismatch, or implementation error.

## 7. Temporal estimands

For coordinate (i), volatility uses only eligible adjacent nonzero pairs:

\[
V_i=
\frac{\sum_t\mathbf 1[Y_{i,t}\ne0,Y_{i,t+1}\ne0,
                         Y_{i,t}\ne Y_{i,t+1}]}
     {\sum_t\mathbf 1[Y_{i,t}\ne0,Y_{i,t+1}\ne0]}.
\]

If the denominator is zero, report undefined with its support count; do not
substitute (N_i-1). Lagged sign correlations use the analogous eligible-pair
denominator for each lag in

\[
\mathcal T=\{1,2,4,8,16,32\}.
\]

Report the decay curve and pair counts. Do not call this an integrated
autocorrelation time; the sparse lag set is a diagnostic decay curve, not a
dense-lag IACT estimate.

## 8. Sampling, weighting, and dependency structure

If coordinates or times are sampled with stratification, freeze every inclusion
probability. Population-level estimates of \(\Omega\), \(\Psi\), zero rate,
and volatility must either use inverse-probability weights or explicitly name
the stratified sampling distribution as the estimand. The primary contract
uses inverse-probability weighting unless a later sealed amendment says
otherwise.

The independent resampling axis is the task/learner block. A bootstrap draw of
one block carries its complete substrate-by-side panel, including the literal
fly and every null side. Do not bootstrap the 216 substrate/side/block cells
as independent observations. Preserve the cross-substrate and cross-side
pairing, and report effective block support.

## 9. Frozen interpretation rules

The ladder is interpreted in this order:

* \(\widehat\Omega_0>0\): static identity carries a soft polarity prior.
* \(\widehat\Omega_1-\widehat\Omega_0>0\): instantaneous local dynamics add
  extractable information.
* \(\widehat\Omega_2-\widehat\Omega_1>0\): history adds information.
* \(\widehat\Omega_{3a}-\widehat\Omega_2>0\): signals actually delivered to
  the native rule add information.
* \(\widehat\Omega_{3b}-\widehat\Omega_{3a}>0\): native state contains a
  computable signal not currently delivered to the rule.
* \(\Omega_4=1\) is the exact reconstruction invariant; a weak learned
  estimator is an audit failure, not a scientific negative.
* All estimator outputs near zero, with high oracle \(\Psi\) and nontrivial
  nonzero target rate, support only “no extractable signal under the frozen
  estimator family.” Report volatility and autocorrelation; do not claim that
  native sign information is impossible.

Replace the earlier sentence claiming that (Y_{i,t}) is not a static
property of coordinate identity with:

> **REACH-02 does not support a simple static-inversion account.**

The REACH-03 \(\mathcal F_0\) rung remains open to a soft coordinate prior.

## 10. Pre-code checklist

Before any implementation is authorized, the new sealed contract must pin:

- the exact target tolerance \(\tau\);
- the byte-level feature schemas for \(\mathcal F_0\ldots\mathcal F_4\);
- the distinction between \(\mathcal F_{3a}\) and \(\mathcal F_{3b}\);
- the common scoring universe \(U^*\) and support condition;
- the corrected v0.1b sign-arm stage and \(S_N^{\mathrm{signarm}}\);
- coordinate/time inclusion probabilities and IPW convention;
- block-preserving bootstrap resampling;
- the F4 reconstruction tolerance and audit receipt;
- the exact estimator class, capacity, and out-of-sample split;
- the formulas for \(\Psi\), \(\eta_S^{\mathrm{L1}}\), (V_i\), and lagged
  correlations;
- the no-biological-promotion and no-PHENO-reseal boundaries.

Until this checklist is sealed, do not create a runner, feature collector,
classifier, seed manifest, measured namespace, or result artifact.

## 11. Current disposition

**MATH STRUCTURE ACCEPTED; v0.2 AMENDMENT REQUIRED BEFORE CODE.**

This amendment narrows claims, preserves the paired sampling structure, adds
the capability-weighted polarity estimand, and makes \(\mathcal F_4\) an exact
reconstruction audit. It does not authorize execution and does not change the
closed REACH-02 or paused FLY-PHENO dispositions.
