# REACH-03 v0.3 Authoritative Math Contract

Status: **SEALED PRE-CODE / ENGINEERING-ONLY / NO EXECUTION**

This is the combined authoritative contract for REACH-03. The historical
`MATH-CONTRACT.md` draft and both amendment files are incorporated below for
provenance. Where an earlier sentence conflicts with a later amendment, the
later v0.2 or v0.3 controlling section wins. No runner, feature collector,
classifier, seed namespace, or measured run is authorized by this seal.

The old `math-objects.json` is preserved as a v0.1 historical companion. The
controlling machine-readable companion is `math-objects-v0.3.json`.

## Controlling source order

1. `MATH-CONTRACT.md` is the preserved v0.1 base draft.
2. `MATH-CONTRACT-v0.2-AMENDMENT.md` controls evidence, estimator semantics,
   the filtration split, common scoring population, support, F4, temporal
   denominators, sampling, and interpretation.
3. `MATH-CONTRACT-v0.3-TIGHTENING.md` controls proposed-versus-delivered
   polarity, IPW/class-balancing composition, trial resolution, and the local
   interpretation limit of Psi.

The amendment sections below are the controlling clauses. The base draft is
retained intact so the historical design can be audited without mutating it.

---

## Incorporated v0.1 base draft
# REACH-03 — Dynamic Polarity Observability — Math Contract (frozen, pre-code)

Status: **FROZEN**. Engineering-only; no biological promotion; no PHENO reseal.
Authoritative before any classifier/runner code exists. Sealed identities must not be altered.

Machine-readable companion: `experiments/fly-reach-03/math-objects.json` (sha256: `math-objects.sha256`).

Grounded in sealed results:
- FLY-REACH-01 (`COLLECTION_COMPLETE`, 216 blocks, authority geometry v0.1 — see `experiments/fly-reach-01/derived/MATH-NOTES.md`).
- FLY-REACH-02 RUN1 (`experiments/fly-reach-02/artifacts/REACH02-RUN1/`) and RUN2/v0.1b (`experiments/fly-reach-02-v0.1b/artifacts/REACH02-RUN2/`).
- FLY-REACH-02 disposition (both runs): `SIGN_COUNTERFACTUAL_SUPPORTED_STABLE_MASK_NOT_EXPLANATORY`.

Out-of-scope, REACH-02-candidate designs only (not authorized here): order-swap (χ_AB), continuous-mixture probes.

---

## 0. Sealed REACH-02 anchors (do not re-derive)

| quantity | RUN1 | RUN2 |
|---|---|---|
| native loss_large | 0.307771 | 0.313368 |
| sign_ref_native_mag loss_large | **0.000000** | **0.001426** |
| stable_inversion_flip loss_large | 0.308597 | 0.316725 |
| reference_direction loss_large | 0.247794 | 0.249599 |
| weight_oracle loss_large | 0.232765 | 0.236026 |
| local/aggregate sign agreement (native vs reference) | 0.477835 | 0.488847 |
| stable_correct / stable_inverted / unstable fraction | 0.06415 / 0.06379 / **0.87206** | 0.06502 / 0.06308 / **0.87190** |
| qualification-derived stable mask fraction (mean over 18 masks) | ~0.00019 (≈0.019%) | ~0.00017 (≈0.017%) |
| local_cancellation | 0.012498 | 0.012382 |
| unstable_fraction trajectory @512→8192 | 0.9246 → 0.8721 | 0.9234 → 0.8719 |
| aggregate_sign_agreement trajectory @512→8192 | 0.5055 → 0.4778 | 0.5070 → 0.4888 |

REACH-02 stability rule (executor `stable_fractions`, `main.rs:117`): coordinate i is
- `stable_correct` if seen_i ≥ 128 and match-rate p_i ≥ 0.80,
- `stable_inverted` if seen_i ≥ 128 and p_i ≤ 0.20,
- `unstable` otherwise (includes insufficient observations).

Primary implication already supported: **Y_{i,t} is not a static property of coordinate identity i** (87% unstable under a static rule; a static inversion mask over qualification blocks is essentially empty and fails to improve loss). The dynamic polarity observability program asks: *what is Y_{i,t}, and from which nested information sets is it predictable out-of-sample?*

---

## 1. Target: Y_{i,t} with explicit zero channel

Fix, before any REACH-03 run:

1. **Reference gradient.** \(g_{i,t}\) = the per-coordinate value produced by the frozen reference direction operator (REACH-02 `reference_delta_into`, same lr η_ref, same task patterns/labels, evaluated at weight state \(w_t\), before native delivery of step t). This is the REACH-02 `reference` vector, read-only, never fed to native learning.

2. **Tolerance τ.** A single scalar frozen in the REACH-03 contract before the measured run. Default proposal: \(\tau = \texttt{EPS} = 10^{-12}\) on the raw f64 gradient (matches executor EPS). A secondary tolerance grid may be reported for sensitivity, but **one primary τ is frozen**. Zero-reference coordinates are never silently folded into ±1.

3. **Three-valued target.**
\[
Y_{i,t}=\begin{cases}
+1 & g_{i,t} > \tau \\
-1 & g_{i,t} < -\tau \\
0 & |g_{i,t}| \le \tau
\end{cases}
\]
Binary observability is defined on the restricted target \(Y^{\pm}_{i,t} \in \{-1,+1\}\) conditioned on \(Y_{i,t} \ne 0\). The **zero rate** \(\pi_0 = P(Y_{i,t}=0)\) is reported as a first-class quantity; it is not folded into binary error.

4. **Binary marginal.** \(\pi_+ = P(Y^{\pm}_{i,t}=+1 \mid Y_{i,t}\ne 0)\), measured on the native trajectory, reported for every filtration. All balanced-error definitions below use the **balanced** convention (uniform class weighting), independent of \(\pi_+\). Raw agreement rates are never interpreted as "better/worse than chance" without \(\pi_+\).

5. **Support / observation mask.** A coordinate-time pair \((i,t)\) is *eligible for scoring* only if both \(Y_{i,t}\ne 0\) and the filtration feature vector at \((i,t)\) is well-defined (no NaN/Inf). Scoring may further restrict to coordinates native actually updates (nonzero eligibility), but the restriction is declared per-level and applied uniformly.

6. **On-policy.** All \((F, Y^{\pm})\) pairs are drawn from the **native** trajectory (on-policy). Predictors are fit on native logs only; they never observe \(g\) or \(Y\) before the prediction step they are scored on.

---

## 2. Nested filtrations \(\mathcal F_0 \ldots \mathcal F_4\)

Each level is a sigma-algebra / feature vector available to a predictor at time \(t\), before observing \(g_t\). Levels are strictly nested: \(\mathcal F_0 \subseteq \mathcal F_1 \subseteq \mathcal F_2 \subseteq \mathcal F_3 \subseteq \mathcal F_4\). Feature lists are **exact**; any addition requires a contract amendment before code.

### \(\mathcal F_0\) — static coordinate identity (no time, no state)
- Coordinate index \(i\) (hashed / one-hot / embedding — implementation detail, not contract).
- Anatomical descriptor of the edge: presynaptic cell type, postsynaptic cell type, compartment, sign of anatomical mb weight, in/out-degree buckets, side (L/R), substrate id.
- **Excluded:** any weight, activity, reward, eligibility, task label, or anything that varies with \(t\).
- Purpose: measures \(I(Y; \text{identity})\) — the static-mask baseline that REACH-02 already failed under a hard threshold rule.

### \(\mathcal F_1\) — instantaneous local dynamics (state at t, pre-update)
- \(\mathcal F_0\) plus, at time \(t\) **before** native delivery:
  - native weight \(w_{i,t}\),
  - eligibility trace \(E_{i,t}\) (post-synaptic and pre-synaptic components if stored separately),
  - local baseline / gain for the postsynaptic unit,
  - presynaptic spike/trace value and postsynaptic trace value at t,
  - local signed contribution magnitude (the quantity behind REACH-02 `local_signed` / `local_abs`),
  - sign of \(w_{i,t}\).
- **Excluded:** reward, DAN/feedback, any reference-derived quantity, any other coordinate's state.

### \(\mathcal F_2\) — local temporal history
- \(\mathcal F_1\) plus a frozen window of past local states:
  - ring buffer of last \(K\) values of \((E_{i,\cdot}, w_{i,\cdot}, \text{traces})\) for \(K\) frozen in the contract (default proposal: \(K=32\) trials, matching typical eligibility decay horizon),
  - lagged sign products / flip counters over the same window (for volatility features),
  - local running mean and variance of eligibility magnitude.
- Window length \(K\) and lag set \(\mathcal T = \{1,2,4,8,16,32\}\) are frozen before the measured run.

### \(\mathcal F_3\) — native-visible globals
- \(\mathcal F_2\) plus scalars/summaries native actually receives or can compute without the reference objective:
  - scalar reward \(r_t\) for the trial,
  - DAN / feedback amplitude summary for the trial,
  - global temperature / learning-rate / scale multipliers active at t,
  - aggregate eligibility activity summary (total mass, fraction active) across the network — computed from native state only,
  - trial index \(t\) (coarse-binned; not raw trial number if it would leak curriculum phase — binned form frozen).
- **Excluded:** task labels, cue pattern structure, any reference gradient component, any other arm's state.

### \(\mathcal F_4\) — full task + full state (sanity ceiling, still no direct g)
- \(\mathcal F_3\) plus the **complete deterministic inputs** that define \(g_{i,t}\): full weight vector \(w_t\) (all coordinates, not just i), full task definition (cue labels, pattern edge lists, schedule up to t).
- Still **excluded:** \(g_{i,t}\) itself, any function of \(g\) (sign, magnitude, cosine to g, reference arm outputs).
- Because \(g_{i,t}\) is a deterministic function of \((w_t, \text{task})\) (REACH-02 `reference_delta_into` uses no sampling noise beyond \(w_t\) and the fixed patterns/labels), a Bayes-optimal predictor on \(\mathcal F_4\) must achieve \(\varepsilon^*(\mathcal F_4) \approx \pi_0\)-floor (binary Bayes error → 0 on the non-zero channel), i.e. \(\Omega(\mathcal F_4) \approx 1\) up to estimator error and the zero channel. \(\Omega_4\) is therefore a **sanity ceiling / estimator calibration**, not an empirical unknown. A measured \(\Omega_4\) materially below 1 means either (a) features are incomplete, (b) estimator underfit, or (c) Y is not the object we think — all three are contract-level red flags.

### Information boundary
The native learner does **not** receive the reference objective (labels/patterns used only by the reference operator). \(\mathcal F_3\) is the intended "what native legally has." \(\mathcal F_4\) is "what exists in the simulator but is withheld from native." The gap \(\Omega_4 - \Omega_3\) is the **information-boundary gap**.

---

## 3. Bayes polarity observability \(\Omega(\mathcal F)\)

All definitions below are on the binary channel \(Y^{\pm} \in \{-1,+1\}\) conditioned on \(Y \ne 0\), under the **balanced** class convention (reweight so \(P(Y=+1)=P(Y=-1)=1/2\)).

### 3.1 Bayes error and \(\Omega\)
\[
\varepsilon^*(\mathcal F) = \mathbb E\Big[\min\big(P(Y^{\pm}=+1\mid \mathcal F),\; P(Y^{\pm}=-1\mid \mathcal F)\big)\Big]
\]
under the balanced measure. Equivalently, with \(P_{\mathcal F\mid +}, P_{\mathcal F\mid -}\) the class-conditional feature laws under balanced reweighting:
\[
\varepsilon^*(\mathcal F) = \tfrac12 - \tfrac12\,\mathrm{TV}\big(P_{\mathcal F\mid +},\; P_{\mathcal F\mid -}\big),
\qquad
\boxed{\;\Omega(\mathcal F) = 1 - 2\varepsilon^*(\mathcal F) = \mathrm{TV}\big(P_{\mathcal F\mid +},\,P_{\mathcal F\mid -}\big)\;}
\]
Properties (frozen):
- \(\Omega \in [0,1]\); \(\Omega=1\) iff the class-conditionals are disjoint (perfect polarity observability at level \(\mathcal F\)); \(\Omega=0\) iff \(\mathcal F \perp Y^{\pm}\).
- A constant predictor has balanced error \(1/2\), hence \(\Omega=0\) by construction — the null baseline.
- \(\Omega\) is **never** computed as raw \(2a-1\) on uncorrected agreement rate \(a\) unless \(\pi_+=1/2\) has been verified; if \(\pi_+\ne 1/2\), \(2a-1\) is biased and is not reported as \(\Omega\).
- Negative plug-in estimates from a finite classifier are **clipped to 0** for reporting, with the unclipped value also stored (clipping is a reporting convention, not a redefinition).

### 3.2 Increments
\[
\Delta\Omega_k = \Omega(\mathcal F_k) - \Omega(\mathcal F_{k-1}), \quad k=1,2,3,4, \qquad \Delta\Omega_0 = \Omega(\mathcal F_0).
\]
By nesting, population \(\Omega\) is nondecreasing in \(k\). Finite-sample estimates may violate monotonicity; monotonicity of the **reported** sequence is enforced only after estimator uncertainty is attached (a significantly negative \(\Delta\Omega_k\) is an estimator failure flag, not new physics).

### 3.3 Which \(\Omega\) is primary
Primary scientific object: **\(\Omega(\mathcal F_3)\)** — polarity observability from native-legal information.
Secondary: full ladder \(\Omega_0,\ldots,\Omega_4\) and \(\Delta\Omega_k\).
Mutual information \(I(Y;\mathcal F_k)\) and conditional forms \(I(Y^{\pm}; Z_{\mathrm{dyn}} \mid I_{\mathrm{coord}})\), \(I(Y^{\pm}; R, M \mid Z_{\mathrm{local}})\) are **secondary estimands** (high-dimensional MI is hard); they do not replace the \(\Omega\) ladder.

---

## 4. Volatility and temporal structure

### 4.1 Volatility \(V\)
For coordinate i over a trajectory window \([t_1, t_2]\) restricted to \(Y_{i,t}\ne 0\):
\[
V_i = 1 - \frac{1}{N_i-1}\sum_{t=t_1}^{t_2-1} \mathbf 1\big[Y^{\pm}_{i,t} = Y^{\pm}_{i,t+1}\big]
\]
(fraction of consecutive non-zero-target steps that flip). Network-level \(V = \mathbb E_i[V_i]\), reported with the distribution (not only the mean), stratified by \(\mathcal F_0\) anatomy buckets.

If exact consecutive steps are too expensive to log, \(V\) is estimated from a frozen lag-1 flip counter accumulated online; the estimator is specified in the run contract, not improvised in code.

### 4.2 Autocorrelation \(\rho_Y(\tau)\)
\[
\rho_Y(\tau) = \mathrm{Corr}\big(Y^{\pm}_{i,t},\; Y^{\pm}_{i,t+\tau}\big)
\]
over eligible pairs, for frozen lag set \(\mathcal T = \{1,2,4,8,16,32\}\). Reported as a curve, plus integrated autocorrelation time if the curve is summable within \(\mathcal T\).

### 4.3 Relationship to REACH-02 "unstable"
REACH-02's `unstable_fraction` ≈ 0.87 is a **cumulative match-rate** statistic under thresholds (128 obs, p outside [0.2, 0.8]) — it conflates (a) genuine intermediate agreement, (b) insufficient observations, and (c) sign drift. It is **not** \(V\) and must not be quoted as \(V\). REACH-03 reports both: the REACH-02-compatible cumulative statistic (for continuity) and the true flip-based \(V, \rho_Y(\tau)\) (for the contract). A coordinate can be "unstable" under REACH-02's rule with \(V=0\) if it is simply never observed 128 times with extreme agreement; conversely a coordinate can look "stable_correct" with nonzero short-lag \(V\) if long-run agreement is high but local flips occur.

---

## 5. Polarity efficiency \(\eta_P\) and the capability decomposition

Notation (aligned with authority geometry v0.1):
- \(u_N\) = native delivered update vector (or proposed native delta — declared per report),
- \(\hat s = \mathrm{sign}(g)\) on support, with the zero channel handled per §1 (zeros stay zero),
- \(D_{|u_N|} = \mathrm{diag}(|u_{N,i}|)\),
- \(g\) = reference direction, \(P_S\) = native support projector (nonzero native entries).

Define three efficiencies (cosine to reference, all on the native trajectory, all with the same support/zero rules):

\[
\begin{aligned}
\eta_P^{\mathrm{native}} &= \cos\big(u_N,\; g\big) \\
\eta_P^{\mathrm{observable}} &= \cos\Big(D_{|u_N|}\,\mathrm{sign}\big(\hat s(\mathcal F_3)\big),\; g\Big) \\
\eta_P^{\mathrm{oracle}} &= \cos\Big(D_{|u_N|}\,\mathrm{sign}(g),\; g\Big)
\end{aligned}
\]

where \(\hat s(\mathcal F_3)\) is the **out-of-sample predicted sign** from the \(\mathcal F_3\) classifier (the same predictor whose \(\Omega_3\) is primary), applied to native magnitudes — the observable analogue of REACH-02's `sign_ref_native_mag` arm, but with predicted signs instead of oracle signs.

Telescoping decomposition (exact, in \(\eta_P\) space):
\[
\eta_P^{\mathrm{oracle}} - \eta_P^{\mathrm{native}}
= \underbrace{\eta_P^{\mathrm{oracle}} - \eta_P^{\mathrm{observable}}}_{\text{information deficit}}
+ \underbrace{\eta_P^{\mathrm{observable}} - \eta_P^{\mathrm{native}}}_{\text{mapping deficit}}
\]
- **Information deficit** large, mapping deficit small → the signs are knowable-in-principle but \(\mathcal F_3\) does not contain them (or estimator failed): push features, not rules.
- **Mapping deficit** large, information deficit small → \(\mathcal F_3\) knows the signs but the native rule / classifier-to-delivery path does not use them: push the rule.
- Both large → both.

REACH-02 already pins the **oracle endpoint**: `sign_ref_native_mag` reached loss_large ≈ 0 (RUN1) / 0.0014 (RUN2) — oracle online signs + native magnitudes are (near-)sufficient for capability on this task at this horizon. That is the ceiling \(\eta_P^{\mathrm{oracle}}\) is trying to explain, and it makes the information deficit the binding scientific question.

Also report, for continuity with authority geometry v0.1:
\[
\eta_S^{L1} = \frac{\langle u_N, g\rangle}{\|u_N\|_1\|g\|_\infty}\ \text{(or the exact v0.1 form)}, \quad
\eta_D = \cos(\text{delivered}, g), \quad
\eta_M = \frac{\text{mean } \|u\|_2 \text{ among nonzero}}{\text{native mean}}
\]
with the REACH-01/02 definitions reused verbatim where they already exist — no silent redefinition.

---

## 6. Decision tree (frozen interpretation rules)

Apply in order, using **out-of-sample** \(\hat\Omega_k\) with bootstrap CIs clustered on (substrate, side, block):

1. **\(\Omega_0 \gg 0\)** → static coordinate identity carries polarity signal; the REACH-02 hard-threshold mask was too crude (rule failure), not an identity failure. Revisit static masks as a *soft* prior, not a flip rule.
2. **\(\Omega_1 \gg 0\) (and \(\Omega_0 \approx 0\))** → local instantaneous state contains the sign; native's update rule fails to exploit it → **mapping failure** at the local level.
3. **\(\Omega_2 \gg 0\) but \(\Omega_1 \approx 0\)** → sign is in recent history but not in the instantaneous snapshot → native lacks / does not use temporal integration over the eligibility window → **integration failure**.
4. **\(\Omega_3 \gg 0\) but \(\Omega_2 \approx 0\)** → sign becomes visible only with reward/DAN/global context → **gating / feedback-credit failure**.
5. **\(\Omega_3 \approx 0\) but \(\Omega_4 \gg 0\)** → sign is a function of full state+task but is not recoverable from native-legal features → **information-boundary failure** (native cannot know the sign without the withheld task labels/reference objective).
6. **\(\Omega_4\) weak (CI excludes values near 1)** → estimator underfit, feature incompleteness, or Y not a function of captured state — **contract red flag**, stop and audit before any biological or rule-level conclusion.
7. **All \(\Omega_k\) near 0 while \(\eta_P^{\mathrm{oracle}}\) is high and \(\pi_0\) is not near 1** → polarity is real and capability-relevant but **stochastically unobservable at every frozen level** (e.g. high \(V\) with no predictive features) → target instability branch; report \(V, \rho_Y(\tau)\) prominently; do not ship a sign-based rule.

Cross-checks that must be consistent (any violation is a red flag):
- \(\pi_0\) low + \(\Omega_4 \approx 1\) + high \(V\) + \(\Omega_3 \approx 0\) ⇒ classic information-boundary + volatility story.
- \(\pi_0\) high ⇒ binary \(\Omega\) is computed on a thin non-zero channel; report \(\pi_0\) next to every \(\Omega\).
- \(\eta_P^{\mathrm{observable}} \approx \eta_P^{\mathrm{native}}\) while \(\Omega_3 \gg 0\) ⇒ classifier's signs do not transfer to delivery (support mismatch, magnitude mismatch, or off-distribution application) — mapping deficit, not information deficit.

---

## 7. Estimation protocol (frozen; predictors must not touch learning)

### 7.1 Data split
Mirror REACH-02:
- **Qualification blocks** (Q_BLOCKS, 4 blocks): feature selection, hyperparameter search, tolerance-adjacent choices, model class selection. Predictors may be tuned here freely against \(Y\).
- **Measured blocks** (BLOCKS, 12 blocks): final out-of-sample \(\hat\Omega_k\), \(\hat\eta_P\), \(V\), \(\rho_Y(\tau)\). No peeking for model choice.
- Same substrate × side grid as REACH-02 (9 substrates × 2 sides × 12 blocks = 216 cells), unless the REACH-03 run contract amends it before code.

### 7.2 Out-of-sample rules
- **Time-blocked CV** within each trajectory (never random shuffle across trials — temporal dependence is the signal).
- **Leave-block-out** across measured task blocks for the headline numbers.
- Cluster bootstrap over (substrate, side, block) for 95% CIs on every reported \(\hat\Omega_k\), \(\Delta\hat\Omega_k\), \(\hat\eta_P\), \(V\).
- Every \(\hat\Omega_k\) reported with (a) point estimate, (b) CI, (c) effective sample size of eligible \((i,t)\) pairs, (d) \(\pi_+\) and \(\pi_0\) on the scored set.

### 7.3 Model classes (frozen set; one per level, same budget)
To keep the ladder comparable, use the **same** model family and capacity budget at each \(\mathcal F_k\) (only the feature set grows):
- Primary: gradient-boosted trees (fixed depth/rounds frozen in run contract) **or** a small MLP with frozen architecture — pick one family in the run contract, apply to all k.
- Baselines: constant predictor (must yield \(\hat\Omega=0\)); \(\mathcal F_0\)-only coordinate embedding as sanity.
- Learning curves: \(\hat\Omega_k\) vs. number of eligible samples must be reported; a rising curve that has not plateaued means \(\hat\Omega\) is a **lower bound** on true \(\Omega\) (standard estimator-failure caveat: \(\hat\Omega \le \Omega\) up to noise when the class is underfit; overfit can inflate \(\hat\Omega\) out-of-sample only through leakage — CV rules above are the defense).

### 7.4 What predictors may never see
- \(g_{i,t}\), \(Y_{i,t}\), or anything derived from the reference operator, at prediction time.
- Other arms' trajectories (only native logs feed features).
- Evaluation outcomes / loss at time t (loss is a downstream label, not a feature).
- Any write path into simulator state — **read-only telemetry replay**.

### 7.5 Secondary MI estimands
On low-dimensional projections frozen in the run contract (do not attempt full-dim KSG on raw state):
- \(I(Y^{\pm}; \mathcal F_0)\),
- \(I(Y^{\pm}; Z_{\mathrm{dyn}} \mid I_{\mathrm{coord}})\) with \(Z_{\mathrm{dyn}}\) a frozen low-dim summary of \(\mathcal F_1\),
- \(I(Y^{\pm}; R, M \mid Z_{\mathrm{local}})\) with \(R\)=reward, \(M\)=DAN summary.
Reported as secondary; never used to override the \(\Omega\) ladder.

---

## 8. What REACH-03 must log (collector contract sketch — define before runner code)

Full per-trial full-network \(g\) vectors are too large (edge count × 8192 trials). Use **streaming sufficient statistics + stratified subsampling**:

1. **Target stream.** For a frozen stratified subsample of coordinates (strata: pre/post cell-type pair, side, \(|w|\) bin, native-support vs. off-support), log per trial (or per frozen stride): \(Y_{i,t}\), \(|g_{i,t}|\) (or a coarse bin of \(|g|\)), and the \(\mathcal F_0\ldots\mathcal F_3\) feature vector. Subsample size and stride frozen in run contract.
2. **Flip / lag accumulators (online).** For every sampled coordinate, accumulate for \(\tau\in\mathcal T\): count of \(Y_{i,t}=Y_{i,t+\tau}\), and consecutive-flip count — gives \(\rho_Y(\tau)\) and \(V\) without storing full series.
3. **Marginals.** Running \(\pi_0, \pi_+\) overall and per stratum, per checkpoint (checkpoints = REACH-02 set: 0, 512, 1024, 2048, 4096, 8192, or a superset frozen in run contract).
4. **REACH-02-compatible cumulative statistics** (seen/match counts, `stable_fractions`, local_cancellation, cosines at eligibility/modulation/aggregation/delivery) for direct continuity with sealed tables — reuse executor functions, do not re-derive differently.
5. **Qualification namespace** parallel to measured, so \(\mathcal F_0\) soft priors can be tuned without touching measured blocks.
6. **Receipt** mirroring `FLY-REACH-02-collection-receipt-v1`: counts, arm list (native only for the observability run — counterfactual arms are a separate, later stage), contract sha256, wall time.

Prediction/analysis is a **separate offline stage** reading these logs; it never runs inside the learning loop.

---

## 9. Explicit non-goals and freeze rules

- No biological promotion; no PHENO reseal; no lesion language.
- Sealed REACH-01/02 identities, dispositions, and artifacts are read-only inputs.
- Order-swap (χ_AB) and continuous-mixture probes: **not authorized** by this contract (REACH-02-candidate only).
- No classifier, runner, or collector code may be written until this contract is accepted; any change to §1–§7 requires a versioned amendment (`MATH-CONTRACT.md` → v0.2) *before* the corresponding code change.
- Primary estimand remains **out-of-sample polarity prediction**; MI is secondary; capability (\(\eta_P\), loss) is the downstream check that the observability story matters, not a substitute for it.

---

## 10. One-paragraph summary (the frozen question)

REACH-02 showed that replacing native signs with reference signs (keeping native magnitudes, online) drives loss to ≈0, while a static coordinate-inversion mask is empty and useless, and 87% of coordinates fail a static stability rule — so capability is polarity-gated and polarity is dynamic. REACH-03 freezes the question: define \(Y_{i,t}=\mathrm{sign}(g_{i,t})\) with a real zero channel and balanced-Bayes \(\Omega(\mathcal F)=1-2\varepsilon^*(\mathcal F)=\mathrm{TV}(P_{\mathcal F|+},P_{\mathcal F|-})\) on the nested ladder \(\mathcal F_0\) (identity) → \(\mathcal F_1\) (instant local) → \(\mathcal F_2\) (local history) → \(\mathcal F_3\) (native-legal globals) → \(\mathcal F_4\) (full state+task, no g), estimate each level out-of-sample on native trajectories only, decompose the gap to oracle polarity efficiency into information vs. mapping deficits, and apply the frozen decision tree to decide whether the failure is a static-mask artifact, a local mapping miss, a temporal-integration miss, a feedback-gating miss, an information-boundary failure, or genuine target instability — before any rule-level or biological claim is entertained.

---

## Incorporated v0.2 amendment
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

---

## Incorporated v0.3 tightening
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

---

## Seal boundary

This contract is sealed only at the math and provenance layer. It authorizes
no implementation or execution. Any change to the target, support semantics,
filtration features, estimator weighting, trial resolution, bootstrap unit,
F4 audit, or interpretation boundary requires a new versioned amendment.
