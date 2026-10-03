# FAS-S11 v01: Fresh-Population Observer-Transport Confirmation

## Status and authority

The S11 confirmatory contract is frozen for review. This protocol seal authorizes no panel construction, tokenizer execution, model loading, feature extraction, observer replay, probe fitting, or result analysis. The current terminal authority is:

```text
S11_PROTOCOL_FROZEN                    true
S11_PANEL_CONSTRUCTION_AUTHORIZED      false
S11_MODEL_CONTACT_AUTHORIZED          false
S11_FEATURE_EXTRACTION_AUTHORIZED      false
S11_OBSERVER_REPLAY_AUTHORIZED         false
S11_RESULT_READY                       false
```

The experiment requires separate authorization before any construction or model contact. A later implementation must conform to the sealed contract and be hashed before it reads or emits the S11 candidate population.

## Question

Does final-position retain greater cross-depth observer compatibility than mean-full on a genuinely fresh held-out population, while both surfaces show decreasing raw balanced accuracy as source-observer and target-representation layers separate?

S10 observed this pattern on the already revealed S01 grouped split. Its off-diagonal mean balanced accuracy was 0.360020 for M and 0.465482 for F. Its equally weighted raw-BA distance slopes were -0.00500 for M and -0.01834 for F. Those are exploratory reference values only; they are not S11 thresholds and must not influence panel construction.

The confirmatory claim is scoped to fresh generated quartets under the same fixed world-family and surface-template distribution. S11 does not test new families, new templates, a new task, a new observer, or a causal transformer mechanism.

## Locked ancestry and observer bank

The machine-readable contract binds the S01-2 world construction and exact source semantics, the S09 fixed observer bank and feature protocol, and the S10 transport calculation. The corresponding parent hashes are recorded in `contracts/s11-confirmatory-contract-v01.json`.

The observer bank consists of the 32 sealed S09 scaler-plus-linear-probe states: 16 source layers for each of M and F. Every S11 cell transports one unchanged source-layer pipeline to one fresh target-layer representation. No S11 row may enter a fit, scaler, observer, or hyperparameter decision.

## Fresh panel definition

The candidate universe contains the complete S01-2 design: 24,576 FACTORIAL_BALANCED quartets, 1,024 BINDING_CONTEXT quartets, and 1,024 BINDING_ENTITY quartets. It retains the eight world-family strata, two relations, three exact states, eight observation templates, eight query templates, all four A/C/E/P variants, candidate-order rules, quartet semantics, and template pairing rules from the sealed parent world contract.

S11 uses a fixed, disjoint 64-term invented vocabulary. It is generated as the ordered Cartesian product of eight four-character prefixes and eight three-character suffixes. The inventory and role assignment are frozen in the JSON contract. Context and entity retain 32 role-local IDs each; IDs 0-15 are train-side-style and IDs 16-31 are novel-heldout-style. This preserves the parent split structure while ensuring S11 rendered inputs use a fresh lexical inventory. A protocol-time set check found zero term collisions with the sealed S01-2 vocabulary; the future panel must still pass exact rendered-input hash checks against the complete authorized S01/S09/S10 ancestry denylist.

The fixed generator seed is derived from the contract's literal label using SHA-256, with digest bytes 0 through 7 interpreted as an unsigned little-endian u64. Quartet rendering uses the parent SplitMix64 rule with this seed and the parent ordinal. S11 world, quartet, and event IDs use the frozen S11 namespace and ordinal format.

Select whole quartets without replacement from the full deterministic candidate universe, separately within exact-target classes, using the contract's canonical candidate key and SHA-256 sort. The quotas are 1,733, 1,815, and 1,770 quartets for classes 0, 1, and 2, respectively: 5,318 quartets and 21,272 rows total. There is no replacement, reseeding, quota relaxation, or post-result selection. Any shortage or support-gate failure is preserved as a failed construction.

Before any future feature extraction, the panel must pass independent target reconstruction, A/C/E/P invariance, exact support, family/template presence, identity uniqueness, zero input-hash collisions, deterministic regeneration parity, and complete rejection accounting. The freshness denylist is hash-only. If exact ancestry identities are unavailable, construction fails closed.

## Frozen representation and transport path

For the sealed fresh panel only, a later authorized extraction will compute M=mean_full and F=final model-visible position at every layer 1 through 16, each 2,048-dimensional and serialized as little-endian FP32. Extraction must follow the pinned LFM revision and the sealed S09 single-row, exact-length, no-padding protocol. Backbone parameter identity must match before and after extraction; deterministic repeat features must match byte-for-byte.

The fresh feature cache must be sealed before the 32 S09 observers are loaded. The unchanged S10/S09 arithmetic, precision, batch semantics, class order [0,1,2], metric implementation, and deterministic settings are required. The resulting analysis contains 512 cells: two surfaces by 16 source layers by 16 target layers.

For each surface s, T_s[i,j] is the balanced accuracy of the frozen source-layer i observer on target representation layer j. Rows are source observers; columns are target representations. The full matrices, predictions, hashes, support, recalls, and confusion matrices are retained.

## Confirmatory summaries and uncertainty

The three primary summaries are:

1. D_off: the equally weighted mean of T_F[i,j]-T_M[i,j] over all 240 ordered off-diagonal layer pairs.
2. M slope: ordinary least-squares slope of the 15 equally distance-weighted M mean-BA points B_M(d), d=1 through 15.
3. F slope: the same slope for F.

Use 10,000 bootstrap replicates, resampling whole quartets with replacement within exact-target class and preserving the three exact class counts. One shared resample plan applies to every surface, matrix cell, and primary summary. Use NumPy 2.5.3 Generator(PCG64(seed)) with the fixed bootstrap seed in the contract.

For the three primary summaries, compute each bootstrap standard deviation with ddof=1. For replicate b, compute the maximum over the three absolute deviations divided by their corresponding bootstrap standard deviations. The 95th percentile, using NumPy quantile with method `linear`, is the common max-deviation critical value. Each simultaneous interval is the full-data estimate plus or minus that critical value times its bootstrap standard deviation. Non-finite values or a zero/non-finite standard deviation fail closed. These intervals quantify quartet-sampling uncertainty for the fixed observer bank and generator; they do not quantify observer-training, model-seed, or generator-family variation.

The joint replication criterion requires all three conditions: the D_off interval lies above zero, the M slope interval lies below zero, and the F slope interval lies below zero. Always report each interval and component outcome. Mixed outcomes are not collapsed into a single pass label.

## Required secondary reporting

Report every distance point and the full M/F 16-by-16 matrices; native diagonal scores; forward, backward, and adjacent bidirectional transport; the S10-compatible target-diagonal retention ratios; per-class recalls and confusion matrices; and prediction hashes. Report principal-angle trajectories as fixed-observer geometry context only. The observer planes do not change in S11, so those angles are not evidence from the fresh population.

Do not promote a favorable layer, distance, direction, family, template, class, or subgroup to primary status. Do not use S11 outcomes to revise the contract, select another observer, or open a mechanism branch.

## Stop conditions and interpretation limits

Fail closed on any parent-hash mismatch, identity collision, support shortage, target mismatch, quartet violation, tokenizer/backbone mismatch, feature nondeterminism, observer-state mismatch, incomplete cell matrix, prediction-hash mismatch, or bootstrap disagreement. Preserve every failed attempt and do not repair it by changing the seed, terms, quotas, or analysis.

If the joint rule passes, the bounded conclusion is that on fresh generated quartets within these fixed families and templates, the sealed F observers have greater mean off-diagonal predictive accuracy than the sealed M observers and raw balanced accuracy decays with layer distance for both. This supports local predictive transport without local plane identity for this observer bank and generator. It does not identify a circuit, a semantic feature, a mechanism, or a general law beyond this population.

No FAS-00 data are permitted in S11. No adaptation, SAE, nonlinear analysis, refitting, new representation view, layer selection, or causal claim is authorized.
