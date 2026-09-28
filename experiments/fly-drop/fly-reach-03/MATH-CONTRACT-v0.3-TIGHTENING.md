# REACH-03 v0.3 Tightening Before Seal

Status: **PRE-CODE CONTRACT TIGHTENING**

This is a narrow amendment to the v0.2 math contract. It does not change the
scientific question, filtration ladder, target, support stage, estimator
family, or inference population. It only makes delivery scoring, weighting,
temporal resolution, and the interpretation limit of \(\Psi\) explicit.

## 1. Proposed versus delivered polarity quality

The primary capability-weighted polarity quantity remains the proposed-update
quantity \(\Psi_{\mathrm{prop}}\) from v0.2. For candidate signs \(s_i\), native
proposed magnitudes \(m_i=|u_{N,i}|\), and pre-step weight \(w_{i,t}\), define a
delivery-aware offline sidecar using the frozen actuator bounds:

\[
\widetilde u_i(s)=
\Pi_{[0,2]}\left(w_{i,t}+m_i s_i\right)-w_{i,t}.
\]

The secondary delivery polarity score is

\[
\eta_{\mathrm{del}}(s)=
\cos\left(\widetilde u(s),g\right).
\]

Report it for native signs, reference signs, and every out-of-sample
predictor. It is computed offline from frozen \(w_t\), \(m\), and bounds; it
does not alter the learner or create a new arm. The proposed score remains
primary because

\[
u^\top g=\left(\sum_i m_i|g_i|\right)\Psi_{\mathrm{prop}}
\]

is the clean first-order sign identity. The delivery sidecar measures which
part of that polarity survives clipping and bounds.

## 2. Exact composition of IPW and class balancing

For every scored row \(j\) with inclusion probability
\(p_j^{\mathrm{incl}}\), define

\[
q_j=\frac{1}{p_j^{\mathrm{incl}}}.
\]

The primary balanced error uses the sampling weights inside each target class:

\[
\widehat\epsilon_{\mathrm{bal}}
=\frac12
\frac{\sum_{j:Y_j=+1}q_j\mathbf1[\widehat Y_j\ne Y_j]}
     {\sum_{j:Y_j=+1}q_j}
+\frac12
\frac{\sum_{j:Y_j=-1}q_j\mathbf1[\widehat Y_j\ne Y_j]}
     {\sum_{j:Y_j=-1}q_j}.
\]

Then, and only then,

\[
\widehat\Omega_{\mathcal M}
=\max\left(0,1-2\widehat\epsilon_{\mathrm{bal}}\right).
\]

The capability-weighted sign score uses the same sampling correction when its
estimand is the full common population \(U^*\):

\[
A_w(s)=
\frac{\sum_jq_jm_j|g_j|\mathbf1[s_j=y_j]}
     {\sum_jq_jm_j|g_j|},
\qquad
\Psi(s)=2A_w(s)-1.
\]

If a later contract intentionally targets the stratified sample distribution,
it must say so explicitly and set \(q_j=1\) for that estimand. IPW and class
balancing may not be composed ad hoc by estimator code.

## 3. Trial-resolution requirement for temporal statistics

The measured collector must observe sampled coordinates at **every trial**.
Online lag buffers may retain only the counters and short history required by
the contract, so this does not require serializing every full feature row.

The declared lag set

\[
\mathcal T=\{1,2,4,8,16,32\}
\]

therefore means trial units. A future design using a frozen stride greater than
one must amend the contract and redefine every lag in stride units before code.
It may not silently call an eight-trial interval “lag 1”. The lag-1 volatility
and all lagged correlations use the actual every-trial target stream and the
eligible-pair denominators specified in v0.2.

## 4. Interpretation limit for \(\Psi\)

\(\Psi_{\mathrm{prop}}\) is a first-order reference-alignment quantity. It is
not assumed to be monotonic with endpoint capability under nonlinear,
bounded, multi-step dynamics. The delivery-aware \(\eta_{\mathrm{del}}\) is
also local to a frozen step. Both are authority diagnostics, not substitutes
for trajectory-level loss or an endpoint claim.

The contract must preserve the distinction

\[
\boxed{\text{local authority quality}\ne\text{trajectory outcome}.}
\]

## 5. v0.3 status

These additions are required in the combined authoritative contract. No code,
runner, feature collector, seed manifest, or measured namespace is authorized
by this amendment alone.
