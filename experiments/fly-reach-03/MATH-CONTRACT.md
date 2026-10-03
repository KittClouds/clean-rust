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
