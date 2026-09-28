# FAS-S12: Observer-Plane Causal Dependence

**Protocol status:** `SEALED_FOR_EXECUTION`
**Execution authorization:** `AUTHORIZED_BY_USER`
**Model contact:** authorized for this experiment only
**Claim scope:** selective causal dependence of a frozen LFM plus observer system under the intervention below

## Question

Does removing the exact rank-2 decision plane of a frozen S09 linear observer at layers 4, 8, or 12 change its downstream terminal observer decisions more than an event-wise norm-matched random rank-2 perturbation?

The endpoint is the established fixed-observer task. S12 does not measure native LFM generation, does not establish mathematical necessity, and does not identify a transformer circuit.

## Evidence ancestry

S12 is a mechanistic follow-up on the already revealed S11 panel, not an independent replication. It binds the S11 v02 final result root `23758806537df1895772025e97824393dd4cd79ede7956360cd93f341c30740a`, S11 v02 panel root `9011d425faaac7c6c1bee0f619a696a4469816ebeae1c0df2c6d4f8516fde824`, S11 feature cache root `b93f724f674219484002aeece36eb0512322e59ae37df204b76885c22624cff3`, S11 tokenization root `1c759a420594db8ce682259058ac9da3cc52c202c1bbacf8ed4fe0235ba6cf39`, and S09 result root `664af5b22f071b28d52a67d748e9f6f93ae3e67d587edec80b921dd529945880`.

There are 5,318 quartets and 21,272 rendered events. The observed S11 panel is fixed for S12. Quartets remain the bootstrap unit, with exact-target strata 0/1/2 containing 1,733/1,815/1,770 quartets.

## Frozen model and execution

- Model: `LiquidAI/LFM2.5-1.2B-Base`, revision `7453bca97ca1e67754c4035a4b4c584e1c9dd725`.
- Model assets: local sealed S09 snapshot, root `661a7e73c0804e98bfb4ca9d1786ca9126a0a21595fbd2d3aea517c342fba1b3`.
- Weights load as FP32, evaluation mode, gradients disabled. Expected parameter identity is `14b8ccb6c347eb5a91ccb718de39d70865f15410f5b6e62ca747aaf77f6bb9e5`; pre/post identity must match exactly (`Δθ_LFM = 0`).
- Inputs are the sealed S11 token ID rows, including their existing special tokens. Base model passes use one event per forward call, exact sequence length, and no padding or attention mask.
- Counterfactual branches are batched only within one source event. Each branch has that event's exact sequence length; no padding or mixed-length batches are used. Fixed branch microbatch is 8.
- Deterministic PyTorch/CUDA settings match S11: TF32 disabled, deterministic algorithms enabled, one CPU thread, fixed CUDA device `NVIDIA GeForce RTX 3080`.
- No weights, normalization parameters, probe states, or tokenizer assets are changed. No features or probes are fitted.

## Frozen observer bank and interventions

The six source observers are S09 states at `(layer, surface) ∈ {4,8,12} × {M,F}`. The terminal observers are the unchanged S09 layer-16 M and F scaler-plus-probe states. Each probe has class order `[0,1,2]` and 2,048 input coordinates.

For source layer `l`, the tapped activation `H_l ∈ R^(T×2048)` is the output immediately after block `l`, matching the S09 hidden-state tap. The summary `S_M(H_l)` is the float32 mean across all `T` model-visible positions; `S_F(H_l)` is the float32 final-position vector. Let `μ_(s,l)` be the sealed source observer's FP64 scaler center, and let `U_(s,l) ∈ R^(2×2048)` be the frozen orthonormal basis of the row span of its three pairwise effective normals `W / scale`. Then:

```text
q = S_s(H_l) - μ_(s,l)
Pq = Uᵀ(Uq)
δ_target(λ) = λ Pq
```

For F, subtract `δ` from the final visible position only. For M, subtract the same `δ` from every visible position. The M edit is the minimum-Frobenius-norm activation edit among edits that shift the sequence mean by `−δ`; its tensor energy is `sqrt(T) * ||δ||₂`, while F tensor energy is `||δ||₂`. Target/control comparisons are valid within each site. Raw M-versus-F lesion magnitudes must not be ranked as if the operators had equal tensor energy.

The fixed strengths are `[0, 0.25, 0.50, 1.00]`. λ=1 is the only primary strength. λ=0.25 and 0.50 are descriptive. λ=0 is an exact sham; its output is the unmodified full-forward output shared by all zero-strength arms.

Each site has eight independently seeded random rank-2 orthonormal control planes. Seeds are generated from the fixed `FAS-S12-V01-RANDOM-PLANE|layer={l}|surface={s}|control={k}` labels by SHA-256, interpreting the first eight digest bytes as little-endian uint64. Each plane is a reduced QR basis of a 2048×2 standard-normal matrix from NumPy PCG64. Planes are not orthogonalized against the target plane; target/control principal angles are reported without selection.

For `r = U_Rᵀ(U_R q)`, the random control is:

```text
δ_random = 0                                      if ||δ_target||₂ = 0
δ_random = ||δ_target||₂ * r / ||r||₂            otherwise
```

If `||δ_target||₂ > 0` but `||r||₂ ≤ 1e-12 * max(||q||₂,1)`, the run fails closed. Norm matching is checked after FP32 conversion with relative error ≤ `1e-5` (absolute tolerance `1e-7`).

## Manipulation and execution checks

Before model execution, require every source basis to be rank 2, orthonormal within max-absolute error `1e-10`, and to contain every reconstructed source pair normal with relative residual ≤ `1e-10`. For its projector, check `||P−Pᵀ||_F ≤ 1e-10` and `||P²−P||_F ≤ 1e-9`. Verify all 48 random bases are rank 2 and orthonormal under the same rule.

For each event/site/arm/strength, recompute the edited summary and require:

```text
||Pq' − (1−λ)Pq||₂ ≤ 5e-4 * max(1, ||Pq||₂)
```

Also record the summary perturbation norm and full activation-tensor Frobenius norm. These are manipulation checks, not outcomes.

The execution first runs an unmodified one-row full forward on all 21,272 inputs. It must reproduce byte-for-byte the S11 layer-16 M/F feature rows. Applying the frozen terminal probes to those verified rows must reproduce the sealed S11 native-diagonal class predictions byte-for-byte. S11 did not store probability arrays, so S12 derives baseline probe probabilities from the sealed feature rows and probe states; it does not claim byte-parity with a nonexistent parent probability artifact. After analysis opens labels, baseline metrics must reproduce the S11 class metrics exactly. Only after the feature and prediction parity gates does the runner proceed to intervention branches.

Manual suffix execution begins from the exact tapped `H_l`, uses the same LFM2 masks, rotary embeddings, positions, and subsequent blocks as the stock forward, and applies the final embedding norm. The unmodified suffix is checked byte-for-byte against the stock layer-16 output at layers 4, 8, and 12 for every input row. After all intervention branches are computed and flushed, but before sealing raw outputs, repeat extraction and the complete nonzero branch computation on the prospectively selected 30 quartets (10 per exact-target class); repeated branch logits and manipulation records must match byte-for-byte. A mismatch is an implementation failure; repair the implementation under a versioned code correction and rerun the affected phase before interpreting outcomes.

For each event, process the six sites in fixed order: layer 4 M, layer 4 F, layer 8 M, layer 8 F, layer 12 M, layer 12 F. At each site, process strength-major, then target arm, then controls 1–8. Record both terminal M and F probe logits for every branch. The inference runner does not load event targets, regime labels, or quartet membership; it seals logits and intervention checksums before analysis opens labels.

Repeat the complete deterministic branch computation for 30 fixed quartets (10 per exact-target stratum, selected prospectively by the frozen PCG64 repeat seed), including all four quartet events, six sites, nonzero strengths, and nine arms. Repeat outputs must be byte-identical to the corresponding primary rows.

## Outcomes and primary analysis

All logits are **frozen-observer probe logits**, not LFM language-model logits. For terminal observer `t`, the target-versus-best-rival probe-logit margin is the target-class logit minus the maximum of the other two class logits.

There are six primary contrasts, one for each source layer/surface. For every event at λ=1, calculate:

```text
contrast = mean(target-vs-best-rival margin across 8 random controls)
           - target-plane margin
```

Positive values mean that target-plane ablation lowers the frozen-observer target margin more than the matched random perturbation. The primary observer endpoint is the same-surface terminal observer. The other terminal observer is a descriptive cross-readout endpoint.

For each primary contrast, first average A/C/E/P event values within each quartet, then calculate the fixed-stratum weighted mean over all quartets. Generate 10,000 whole-quartet bootstrap replicates, resampling with replacement within exact-target classes 0, 1, and 2 at the observed stratum counts. The single frozen plan is shared by all six contrasts. Construct 95% simultaneous intervals by the maximum absolute standardized deviation across the six estimands, using NumPy linear quantiles. A site supports selective causal dependence under this intervention only if its simultaneous interval lower bound is greater than zero. Report all six sites; there is no all-sites promotion gate.

Secondary outputs include accuracy, balanced accuracy, per-class recall, confusion matrices, probe probabilities, predictions, sham-relative changes, pairwise class probe-logit margins, target-class and A/C/E/P descriptions, prediction transitions, and λ=.25/.50 descriptions. These do not replace the primary contrast.

## Interpretation and limits

- A positive simultaneous lower bound supports selective causal dependence of this frozen LFM plus observer system on the named activation plane under the specified edit, layer, panel, and observer.
- Similar target and random effects indicate perturbation sensitivity without selective privilege under this control.
- Small effects do not show that the plane is unused; downstream redundancy or recovery may preserve the observer decision.
- No result establishes mathematical necessity, native LFM language behavior, a semantic feature, a circuit, or generalization beyond the fixed model revision, observer bank, panel, and intervention.
- S11 is already revealed. S12 is paired mechanistic follow-up on that population, not independent confirmation.

## Fail-closed conditions and authorized packet

Stop and preserve the attempt on a parent/root/row/token/model/observer identity mismatch, any baseline parity failure, source-plane or random-plane invariant failure, manipulation/norm-match failure, non-finite output, missing branch/event/cell, nondeterministic repeat, backbone parameter change, raw-output hash mismatch, or independent verifier disagreement. A code defect before outcome inspection may be repaired in a versioned implementation while preserving the failed attempt and scientific contract.

The user authorized the complete S12 packet. Execute: parent and code preflight → model load and immutable-state check → base feature/logit parity → branch interventions → repeat parity → raw output and receipt seal → frozen bootstrap/metrics → independent replay and hash verification → final seal → stop. No native LM endpoint, new representation, observer fit, changed intervention, extra layer, extra strength, selected control, or FAS-00 data is in scope.
