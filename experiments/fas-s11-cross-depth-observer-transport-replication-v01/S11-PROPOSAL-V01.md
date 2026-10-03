# FAS-S11: Fresh-Population Replication of Cross-Depth Observer Transport

**Status:** `DRAFT_FOR_REVIEW_NOT_SEALED`  
**Authority:** proposal only. No corpus generation, model loading, feature extraction, probe fitting, inference, or mechanism analysis is authorized here.

## Question

Does the S10 cross-depth transport pattern replicate on a genuinely fresh held-out population under the same task, family, template, observer, and measurement definitions?

The bounded hypothesis is that final-position (`F`) representations have higher cross-depth predictive transport than mean-full (`M`) representations, while raw balanced accuracy falls as source-observer/target-representation layer distance grows. This is fresh-world confirmation within the existing families and templates—not novel-family, novel-template, or new-task generalization.

## Why S11, and what S10 did (and did not) show

S10 was a descriptive replay on the already-revealed S01 grouped split. It tested all 16 sealed source-layer observers on all 16 target layers for both surfaces, without refitting. On its 21,272 held-out event rows, the mean off-diagonal balanced accuracy was `0.360020` for M and `0.465482` for F (`F−M = +0.105461`). The equal-distance-weighted least-squares slope of raw balanced accuracy over layer offsets 1–15 was `−0.00500` for M and `−0.01834` for F.

The distance claim is specifically about **raw balanced accuracy**. The diagonal-normalized retention ratio `T[i,j] / T[j,j]` is retained as a secondary S10-compatible diagnostic, but is not described as a monotone distance-decay measure: its S10 distance averages were non-monotone, particularly for M. S10 did not establish population-level uncertainty because its split had already been revealed.

Frozen S10 ancestry to bind at sealing:

```text
S10 protocol tree root: 3df14974035839db8f58bd96c5063127a3a30680cfa3572cdce47a6df170982e
S10 result tree root:   549d906042979261ec68fd0727486c21f0d132d6281940cb9222993f3f1357b1
S10 result JSON SHA256: 50767e14745d8ae805c78afb2533f3ab8171796a33d1198adfa98ec8952ab62d
S09 feature cache root: 82f9eb6ba0b9c37e58c415b03ec1bc4be00032f73cc43e70b3987ac4108f7653
S09 protocol root:      c1cf07e8b04ac1a3deff583e10257dcd3c5f3040e48bd4b05738cb3c4d4794b2
S09 analysis seal SHA:  44518d3901bf578a417d8897dda3485e9741262e80a676857d48297736cdcefc
```

The exact S09 observer/scaler states and the S10 numerical implementation remain immutable. S11 does not refit observers or change their preprocessing.

## Fresh held-out population contract (to freeze before generation)

Use a new, prospectively seeded draw from the sealed S01-2 counterfactual-world semantics, preserving the eight world-family definitions, eight observation templates, eight query templates, four A/C/E/P variants, exact-target labels, candidate ordering rules, and rendering interface. This is a fresh-world draw under a fixed measurement distribution; it does not test unseen templates or families.

The generator must receive a new S11 namespace and a fixed seed derived once from the frozen S11 seed label. The existing S01-2 generator source and all non-seed semantics are bound by hash; any seed-override adapter is separately versioned and hashed before it runs. No generation rule may depend on S09/S10 observer outputs, feature geometry, or errors.

Target the S10 panel size and exact-target class support:

```text
5,318 quartets = 21,272 event rows
class 0: 1,733 quartets = 6,932 rows
class 1: 1,815 quartets = 7,260 rows
class 2: 1,770 quartets = 7,080 rows
```

Select the contracted number from the fixed candidate stream by the frozen hash ordering within exact-target class. Keep each quartet and its four variants indivisible. Freeze the candidate budget and exhaustion rule before generation; no reseeding or post hoc replacement.

Freshness is checked before panel admission against hash-only identity sets derived from the already sealed S01/S09/S10 source lineage. Require zero collisions in quartet/world/episode identity and exact model-visible rendered-input SHA-256. The denylist is an exclusion oracle only; no raw historical identities, labels, features, predictions, or metrics are exposed to the generator. If the authorized ancestry cannot provide exact source identities for this check, S11 remains unconstructible rather than weakening the freshness claim.

The panel must pass exact-world target reconstruction, A/C/E/P quartet consistency, class-support counts, family/template support reporting, unique row identity, rendered-input disjointness, and independent deterministic regeneration checks before feature extraction. A failed panel is preserved and not repaired by changing the seed or sample rule.

## Frozen feature and observer path

For only the sealed fresh panel, materialize the 16 layer representations for both existing surfaces:

```text
M = mean_full
F = final_position
dimension = 2,048
model = LiquidAI/LFM2.5-1.2B-Base
revision = 7453bca97ca1e67754c4035a4b4c584e1c9dd725
```

Use the exact S09/S10 extraction, row-order, dtype, feature serialization, and deterministic repeat rules. No alternate pooling, normalization, model revision, or feature view is permitted. Verify the frozen backbone identity before and after extraction. Seal the complete fresh feature cache before loading any observer state.

Load the 32 already-sealed S09 scaler-plus-linear-observer states (16 layers × M/F). Apply each source observer `i` to each target-layer representation `j` without refitting or modifying any scaler or probe. Preserve S10's arithmetic and metric implementation exactly. A fresh held-out row may be scored by all cells, but no S11 row may enter fitting.

## Primary estimands and confirmatory rule

For each surface `s ∈ {M,F}`, define `T_s[i,j]` as balanced accuracy of the unchanged source-layer `i` observer evaluated on target representation layer `j`, with the frozen class order `[0,1,2]`.

The primary transport asymmetry is the equally weighted mean paired off-diagonal contrast over all 240 ordered layer pairs:

```text
D_off = mean_{i != j}(T_F[i,j] - T_M[i,j])
```

The primary distance curve for each surface is:

```text
B_s(d) = mean_{|i-j|=d} T_s[i,j], d = 1,...,15
```

The distance-decay summary is the ordinary least-squares slope of `B_s(d)` on integer distance `d`, with each of the 15 distances equally weighted. Report all 15 points and the full 16×16 matrices; do not choose a distance window after seeing S11.

Use a predeclared 10,000-replicate bootstrap resampling whole quartets with replacement, stratified by exact-target class, with one shared resample plan across all M/F surfaces, layers, and matrix cells. Use NumPy `quantile(method="linear")`. Construct simultaneous two-sided 95% max-deviation intervals for the three primary summaries (`D_off`, M slope, F slope) from that shared plan.

The joint replication criterion is met only when the simultaneous interval for `D_off` lies above zero **and** the simultaneous intervals for both distance slopes lie below zero. Otherwise report which component replicated and which did not; do not collapse the result into a single success/failure score. The three primary directions and interval outcomes are reported together. These intervals quantify held-out-quartet uncertainty for the fixed observers and fixed fresh panel; they do not quantify observer-training or model-seed variation.

Adjacent transport, per-distance M/F contrasts, native diagonal scores, forward/backward transport, the S10-compatible retention-ratio matrices, per-class recalls, confusion matrices, and prediction hashes are required secondary/descriptive outputs. Do not promote a favorable layer, distance, direction, family, or class slice to primary status.

Decision-plane principal angles and normalized subspace overlap are historical S08/S10 context, not S11 confirmatory outcomes: observer parameters are unchanged, so recomputing them would not provide fresh-population evidence. No circuit or semantic-feature interpretation is authorized.

## Analysis firewall and stop conditions

Before model contact, seal the fresh-panel contract, source identities, generator and seed, support table, feature extractor binding, observer-state hashes, metric implementation, bootstrap implementation, and analysis code. Then execute:

```text
fresh panel generation and exact-world audit
        ↓
seal panel identities and rendered-input hashes
        ↓
extract and seal fresh M/F layer features
        ↓
load the 32 frozen observer states
        ↓
produce all 512 surface × source-layer × target-layer prediction cells
        ↓
seal raw predictions
        ↓
run the frozen metrics/bootstrap once
        ↓
seal the result before interpretation
```

Fail closed on identity collision, support shortage, target mismatch, extractor/backbone mismatch, nondeterministic features, observer-state mismatch, incomplete matrix, prediction/hash mismatch, or bootstrap implementation disagreement. Preserve failed attempts. No observer refit, new probe, LFM adaptation, FAS-00 access, mechanism work, threshold search, selective reporting, or S10 split reuse.

## Interpretation boundary

If the joint criterion passes, the defensible claim is:

> On fresh generated quartets within the same fixed families/templates, the sealed final-position observers retain higher mean cross-depth predictive accuracy than the mean-full observers, while raw balanced accuracy declines with layer separation on both surfaces.

This would support **local predictive transport without local plane identity** on a fresh held-out population. It would not show that the surfaces are geometrically interchangeable, identify a mechanism, establish novel-template/family transfer, or imply a population-wide law beyond this frozen generator and observer bank.

If it fails, report the component results and conclude that the S10 transport asymmetry and/or distance-decay pattern did not fully replicate at the contracted resolution. No mechanism branch is opened by a mixed or null result.
