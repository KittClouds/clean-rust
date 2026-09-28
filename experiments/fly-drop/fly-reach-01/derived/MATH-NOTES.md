# Adaptive Authority Geometry — Math Notes (v0.1)

Status: **math pass complete on sealed FLY-REACH-01 artifacts**. Engineering-only; no biological promotion; no PHENO reseal.

Machine-readable companions:

- `experiments/fly-reach-01/derived/authority-geometry-v0.json`
- `experiments/fly-reach-01/derived/AUTHORITY-GEOMETRY-V0.md`
- `experiments/fly-reach-01/derived/authority-channels.csv`
- generator: `experiments/fly-reach-01/scripts/authority_geometry_v0.py`

Primary measurements: **FLY-REACH-01** (`COLLECTION_COMPLETE`, 216 blocks, 1131.97 s wall, receipt in `artifacts/REACH01-RUN1/`). Cross-check: FLY-REACH-00. Cross-program: **AR-04C** @ `0335a840` on `codex/ar-04c-sentinel-reuse-20260921` (not in current `HEAD`).

Official REACH-01 disposition: `DIRECTION_FAILURE_ANATOMY_PARTIAL_WITH_EVALUATOR_FLOOR`.

---

## 1. Common object

\[
x_{t+1}=T_S(x_t,e_t,a_t),\qquad c:\mathcal X\to\mathbb R^k
\]

North star:

\[
\text{What capability trajectories are reachable from }x
\text{ under bounded adaptive authority?}
\]

| program | key object | status |
|---|---|---|
| local authority geometry | \(G_x=J_c B_x\), \(\kappa_A\) | **v0 measured** (arm-basis) |
| global reachability | \(\mathcal R_H,\mathcal C_H\) | finite arm sample of \(\mathcal C_H\) |
| noncommutative adaptation | \(\chi_{AB}\), \([u_A,u_B]\) | formulas locked; **no data** |
| evidence-coupled dynamics | fixed vs fresh \(S_t\) | AR-04C measured |

---

## 2. Local authority geometry (REACH-01)

### 2.1 Objects tied to the executor

From `executor/src/reach_sim.rs` + `main.rs`:

- \(u_N\) (native): eligibility × reward × DAN gain × scale, active-masked, then box-clamped to \([0,2]\);
- \(g\) (reference): `reference_delta_into` — analytic **surrogate** gradient of expected logistic-readout score; `REFERENCE_LR=0.05` (oracle: `0.5` × 128 steps);
- \(c\): \(-\)large-bank loss (4096 draws); descriptive competence gate 0.25 on 256-bank;
- stages logged: eligibility → modulation → aggregation → **delivered** (post-clamp actual \(\Delta w\)).

Alignment claims are alignment to surrogate \(g\). The direction arms validate that \(g\) is capability-relevant (following \(g\) improves \(c\)).

### 2.2 Authority triplet + stage factorization (native, 216 cells)

| quantity | value |
|---|---:|
| \(\eta_S^{\mathrm{L1}}\) (ref mass on native support) | **0.6486** |
| native support fraction | **0.3733** |
| \(\eta_M=\overline{\lVert u_N\rVert}/\overline{\lVert g\rVert}\) | **182.0** |
| \(\cos(\text{eligibility},g)\) | **0.002767** |
| \(\cos(\text{modulation},g)\) | **0.002728** (retention 98.6%) |
| \(\cos(\text{aggregation},g)\) | **0.002728** (retention 100%) |
| \(\eta_D=\cos(\text{delivered},g)\) | **0.000300** (retention **11.0%**) |
| sign agreement on support | **0.390** (\(< 0.5\)) |
| magnitude Pearson | **0.0137** \(\approx 0\) |
| bound clip fraction | **0.276** |

**Stage chain (the new object):**

\[
0.002767 \xrightarrow{\text{mod}} 0.002728
\xrightarrow{\text{agg}} 0.002728
\xrightarrow{\text{clamp+mask}} 0.000300
\]

Two distinct defects:

1. **Birth defect (upstream):** eligibility is already \(\cos\approx2.8\times10^{-3}\) against \(g\). Gain modulation and aggregation are essentially alignment-neutral (retention ≈ 1).
2. **Delivery defect:** active-mask + box clamp destroy **89%** of the remaining alignment (retention 0.11). Clip fraction 0.276 explains part of this.

REACH-00’s \(\eta_D\approx0.0032\) was the pre-clamp native-vs-reference cosine — consistent with REACH-01’s aggregation stage, not with delivered. Always label which stage \(\eta_D\) refers to.

Per-substrate: fly and all eight nulls show the same pattern (elig ~0.0022–0.0037, delivered ~0 or slightly signed, sign ~0.38–0.40). **Not a fly-topology signature.**

Trajectory (native, cumulative means):

| ckpt | elig | delivered | sign agr |
|---:|---:|---:|---:|
| 512 | 0.00414 | −0.00018 | 0.420 |
| 1024 | 0.00368 | −0.00041 | 0.404 |
| 2048 | 0.00327 | −0.00022 | 0.396 |
| 4096 | 0.00296 | +0.00004 | 0.392 |
| 8192 | 0.00277 | +0.00030 | 0.390 |

Alignment does **not** self-repair over \(H=8192\); the phenotype is stable, not a transient.

### 2.3 First-order useful vs sideways motion

Normalize \(\lVert g\rVert=1\), \(\lVert u_N\rVert=\eta_M=182\):

\[
\text{useful}=\eta_M\eta_D \approx 0.055,\qquad
\text{orthogonal}\approx 182.0,
\qquad
\frac{\text{useful}}{\lVert u_N\rVert}=\eta_D=3.0\times10^{-4}.
\]

**\(\approx99.97\%\) of delivered native step energy is lateral to \(g\).**

\[
\boxed{\text{adaptive power}\neq\text{adaptive progress}.}
\]

Magnitude arm confirms in capability space: reference magnitudes × native signs → gain **−0.019** (harms by 23% of the oracle gap).

### 2.4 Nested channel gains = finite-difference authority spectrum

Endpoint loss_large, means over 216 cells:

| arm | loss_large | gain vs native | share of oracle gap |
|---|---:|---:|---:|
| native | 0.313205 | — | — |
| sign_ref_native_mag | 0.250699 | **+0.06251** | **75.7%** |
| mag_ref_native_sign | 0.332602 | **−0.01940** | −23.5% |
| reference_direction_native_support | 0.248068 | **+0.06514** | **78.9%** |
| reference_direction_full_support | 0.242703 | +0.07050 | 85.4% |
| weight_oracle | 0.230611 | +0.08259 | 100% |

Nested increments:

| channel | gain | share |
|---|---:|---:|
| direction on native support | +0.06514 | 78.9% |
| sign swap @ native magnitude | +0.06251 | 75.7% |
| support expansion after direction | +0.00537 | 6.5% |
| free weight beyond reference | +0.01209 | 14.6% |
| magnitude swap @ native sign | **−0.01940** | −23.5% |

**Refined anatomy (math, not the sealed disposition string):**

- Sign correction alone recovers **~76%** of the oracle gap — within 2.6 points of full direction-on-support (78.9%).
- Magnitude structure is nearly absent (\(\rho_{\mathrm{mag}}\approx0.014\)); swapping magnitudes while keeping native signs is actively harmful.
- Support expansion and oracle residual are real but secondary (6.5% + 14.6%).
- So the “direction failure” decomposes primarily into a **sign-coordinate failure** inside native support, plus a delivery/clamp tax, plus a smaller out-of-support/oracle residual.

Official interpretation line stays conservative (sign arm \(0.2507\) is slightly worse than direction@support \(0.2481\), so the frozen decision tree does not promote “sign leading”). Mathematically they are nearly tied; both crush native.

**Incremental spectrum** on \(\lvert\text{gains}\rvert\) (5 values, signed mag counted by absolute):

\[
\sigma\approx[0.0651,\ 0.0625,\ 0.0194,\ 0.0121,\ 0.0054]
\]

- participation-ratio effective rank \(\approx 2.26\)
- condition proxy \(\approx 12.1\)
- \(1/5\) channels nonpositive

Anisotropic, low effective rank, one harmful mode — a concrete \(\kappa_A\)-like phenotype on the arm basis. Label it **`kappa_A_arm`**, not a full-state condition number.

### 2.5 True \(G_x=J_cB_x\) — estimator recipe (no new seal required in principle)

1. Pairwise per-trial \(\Delta w\) per arm at checkpoints (need vector dumps; current JSONL is scalar means).
2. Finite-difference \(J_c\) by KC×MBON row-block perturbations of \(w\).
3. \(B_x\) columns = arm directions {sign-fix, mag-fix, dir@support, dir@full, oracle residual}.
4. Thin SVD of \(G_x=J_cB_x\) on that 4–6 column space; \(\kappa_A=\sigma_{\max}/\sigma_{\min}^{+}\) only over numerically nonzero modes.
5. Optional JVP of \(c\circ T\) for engineering audit only.

Claim limit: local to checkpoint, surrogate \(g\), box \([0,2]\), this evaluator.

---

## 3. Global reachability — arm map as \(\mathcal C_H\) sample

All arms share the same `initial` sim (checkpoint-0 losses identical by construction). At \(H=8192\):

\[
\mathcal C_H \supseteq \{c_{\mathrm{native}},c_{\mathrm{sign}},c_{\mathrm{mag}},c_{\mathrm{dir@sup}},c_{\mathrm{dir@full}},c_{\mathrm{oracle}}\}
\]

Spread:

\[
c_{\mathrm{oracle}}-c_{\mathrm{native}} = 0.0826\ \text{loss units}
\quad(\text{competence }73.6\%\ \text{vs}\ 20.4\%).
\]

**Same present capability state, radically different reachable endpoints under bounded mechanism swaps** — engineering instantiation of the adaptive-configuration conjecture.

Missing for a true body with interior: continuous mixtures \(\alpha u_N+(1-\alpha)g\), support-mask schedules, multi-step authority budgets. Not authorized by current seals; REACH-02 candidate design only.

---

## 4. Noncommutative adaptation — locked, unmeasured

\[
\chi_{AB}(x)=\lVert T_B(T_A(x))-T_A(T_B(x))\rVert,
\qquad
[u_A,u_B]=(Du_B)u_A-(Du_A)u_B.
\]

Standard sign convention; matches \(Ju_B u_A - Ju_A u_B\) when \(Ju\) = Jacobian of \(u\).

**Cheapest future probe:** apply sign-fix then mag-fix vs mag-fix then sign-fix over half-horizons from shared \(x_0\); \(\chi_{AB}\) on endpoints. Natural REACH-02 / order-swap mini-protocol — **do not** sneak into sealed identities.

---

## 5. Evidence-coupled dynamics — AR-04C

| arm | final measurement loss | terminal op − final |
|---|---:|---:|
| training_full96 | 4.942 | \(\approx-4.94\) |
| sentinel_fixed128 | 3.209 | \(\approx-3.18\) (op≈0.03) |
| sentinel_rotating128 | **0.768** | \(\approx+0.01\) |

Wins: rotating vs training 25/25; rotating vs fixed 25/25; fixed vs training 22/25.

Conditional unbiasedness for fresh panels:

\[
\mathbb E[\nabla J_{S_t}(x_t)\mid x_t]=\nabla J(x_t)
\quad\text{when } S_t\perp x_t
\]

holds by construction (disjoint seeds, prospective schedule). Fixed reuse couples learner to panel: \(\lvert\mathrm{op}-\mathrm{final}\rvert\) ratio fixed/rotating \(\approx 318\times\) (3.18 vs 0.01).

**Does not imply ranking preservation:** AR-H56 failed (terminal Spearman ≈ −0.15 / 0.02 / −0.08). Unbiased trajectory pressure ≠ checkpoint myopic alignment.

Bridge to fly: FLY-REACH fixes \(\partial T/\partial a\) (direction of authority) under fixed evidence; AR-04C fixes endogeneity of \(e_t\). Complementary axes of \(T_S\).

---

## 6. Claim audit (post REACH-01)

| claim | verdict | evidence |
|---|---|---|
| adaptive power ≠ progress | **supported** | \(\eta_D^{\mathrm{del}}=3\times10^{-4}\); mag arm −23% of gap |
| direction dominates amplitude | **supported** | dir/sign +76–79% vs mag −23% |
| sign is the leading *component* of direction failure | **supported (math)** | sign arm 75.7% of gap ≈ dir@support 78.9% |
| support secondary | **supported** | \(\eta_S^{\mathrm{L1}}=0.65\); support increment 6.5% |
| delivery/clamp is a real stage defect | **supported** | agg→del retention 0.11; clip 0.28 |
| fly-specific misalignment | **not supported** | nulls same band |
| same \(c(x)\), different \(\mathcal C_H\) | **supported (eng.)** | shared init; spread 0.083 |
| alignment self-repairs in training | **not supported** | trajectory stable/declining |
| fresh evidence ≈ unbiased pressure | **consistent (AR-04C)** | rotating gap 0.01 |
| fresh evidence preserves ranking | **rejected (H56)** | Spearman ~0 |
| Lie-bracket path dependence | **unmeasured** | no order-swap data |

---

## 7. Next math (ordered)

1. ~~Stage chain~~ — **done** (elig/mod/agg/delivered above).
2. ~~Sign vs magnitude channels~~ — **done** (sign 75.7%, mag −23.5%).
3. When convenient, re-run `authority_geometry_v0.py` after any REACH-01 re-analysis; it auto-prefers REACH-01.
4. Design-only: order-swap \(\chi_{AB}\) mini-protocol; continuous-mixture \(\mathcal C_H\) interior; block-wise \(J_c\) finite differences for thin \(G_x\).
5. Keep AR-04C citations branch-pinned (`0335a840`).

---

## 8. Reproduce

```text
python experiments/fly-reach-01/scripts/authority_geometry_v0.py
```

Reads sealed REACH-01 (fallback REACH-00), writes `derived/authority-geometry-v0.json` + markdown + CSV.
