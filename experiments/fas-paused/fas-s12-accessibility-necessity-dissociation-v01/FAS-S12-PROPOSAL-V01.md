# FAS-S12 Proposal: Accessibility–Necessity Dissociation

**Status:** `DRAFT_FOR_REVIEW`  
**Execution authorization:** `NONE`  
**Model contact authorization:** `FALSE`  
**Purpose:** prospective design for a bounded activation-intervention study after the S05–S11 observational lineage.

## Research question

Does selectively removing the rank-2 decision plane identified by a frozen S09 observer at an intermediate layer change the terminal task decisions of the corresponding frozen observer-augmented FAS system more than an equal-energy random rank-2 activation intervention?

This tests causal dependence of a specified `LFM + fixed probe` system on a hidden activation subspace. It does not equate linear accessibility with necessity, and it does not establish necessity for the LFM’s native language-model output.

## Recommended scope

Use the pinned frozen LFM2.5-1.2B-Base revision and the already sealed S11 event panel, token identities, and exact rendered inputs. The S11 panel has already been used for transport analysis, so S12 is a paired mechanistic follow-up on this fixed population, not a new independent confirmation population. No generated labels or feature rows from FAS-00 are needed.

Use the six predeclared intervention sites:

```text
surface: M = mean_full observer plane; F = final-position observer plane
layer:   4, 8, 12
```

These are fixed quarter-depth, mid-depth, and three-quarter-depth locations in the 16-layer stack. Layer 16 is excluded from the causal propagation analysis because there are no subsequent transformer blocks through which to measure a propagated effect. The sealed S09 layer-16 observers remain the terminal outcome readouts.

No observer is refit. Load only the six corresponding frozen S09 layer/surface observer states for intervention definition, plus the two frozen S09 layer-16 readouts for the terminal outcomes. Verify their identities against the sealed S09 result tree.

## Intervention definition

At S09 layer `l`, let `H_l ∈ R^(T×2048)` be the model-visible hidden states immediately after transformer block `l`, matching the S09 extraction tap. Let `S_M(H_l)` be the exact mean over model-visible input positions and `S_F(H_l)` the final model-visible position. From the sealed scaler-plus-probe state, reconstruct the effective raw-coordinate pair normals and their rank-2 orthogonal projector `P_(s,l)`, for surface `s ∈ {M,F}`. Let `μ_(s,l)` be the sealed native scaler center in the corresponding summary coordinates.

For a frozen strength `λ ∈ {0, 0.25, 0.50, 1.00}`, define `q = S_s(H_l) − μ_(s,l)` and `δ_target = λ P_(s,l) q`.

- For F, subtract `δ_target` from the final model-visible position at layer `l`; leave earlier positions unchanged.
- For M, subtract the same `δ_target` vector from every model-visible position at layer `l`, so the mean summary changes by exactly `−δ_target`.
- Resume the unmodified frozen transformer blocks after layer `l` through layer 16.
- λ=0 is the paired sham forward pass. λ=1 removes the full centered projection onto the selected observer plane; intermediate values define a fixed dose curve.

The intervention is computed per event from its activation. Backbone weights, normalization parameters, and observer states remain unchanged.

## Controls

For each surface/layer site, construct eight rank-2 random orthonormal control subspaces from prospectively fixed seeds independent of labels, activations, and outcomes. For each event and strength, scale the random-plane perturbation to have the same L2 norm as `δ_target` for that event. The control direction is random; the perturbation energy is matched. All eight controls use the same examples and model/runtime settings as the target-plane intervention.

Record the perturbation norm relative to the unmodified summary and hidden tensor, plus resulting activation norms. Keep all events, including zero-projection cases; their matched controls receive zero displacement. No control may be selected or discarded based on task outcomes.

## Outcomes

### Primary: fixed-observer task behavior after the intervention

After the intervened forward pass reaches layer 16, apply the corresponding unchanged native terminal S09 readout:

```text
M intervention → layer-16 mean_full → sealed layer-16 M scaler + probe
F intervention → layer-16 final position → sealed layer-16 F scaler + probe
```

Record for every event:

- target-vs-best-rival logit margin and all three class-pair margins;
- target probability under the frozen probe softmax;
- predicted class, correctness, and prediction transition from sham;
- balanced accuracy, accuracy, per-class recall, and confusion matrix by intervention site/strength.

For each site at λ=1, the primary selective-damage contrast is:

```text
(mean terminal target margin under the eight matched random controls)
− (mean terminal target margin under target-plane ablation)
```

and the corresponding control-adjusted BA contrast is computed as mean random-control BA minus target-plane BA. Positive values indicate greater damage from removing the observer plane than from an equal-energy random-plane perturbation. Report sham-relative damage too. The λ=0.25 and 0.50 results are dose-response descriptions, not separate promotion gates.

Resample whole A/C/E/P quartets, stratified by the exact target class with the sealed S11 class counts. Use one shared, prospectively seeded bootstrap plan and simultaneous intervals across the six primary layer × surface contrasts. Freeze implementation and hashes before opening intervention outcomes. No probe fitting, layer selection, strength changes, or additional controls after results are visible.

### Manipulation checks and secondary descriptions

- Apply the fixed source-layer observer to the pre-intervention and intervened layer-`l` summary to confirm the intended plane component was removed.
- Report both terminal M and terminal F observer outcomes after every intervention as a secondary cross-readout matrix. Only same-surface outcomes above are primary.
- Report target-vs-control effects by target class and quartet variant descriptively; do not promote subgroup claims without a separate design.
- Verify the unperturbed terminal features, probe probabilities, and metrics reproduce the sealed S11/S09 path exactly on the S11 panel before analyzing interventions.

## Interpretation rules

- Target-plane damage exceeding equal-energy random-plane damage supports **selective causal dependence of the frozen observer-augmented task system** on that layer/surface plane under this intervention.
- Similar target and random damage supports broad perturbation sensitivity, not plane-specific necessity.
- Little damage does not establish that the plane is unused: downstream redundancy, nonlinear recovery, or compensation may preserve the terminal decision.
- A result on the external probe does not establish causal necessity for native LFM token generation. A claim about native LFM behavior would need an explicit response format, tokenizer-qualified candidate scoring, a frozen model-native endpoint, and a baseline task-competence gate in a separate contract.
- Even a strong selective effect is local to this model revision, input panel, frozen observer bank, layers, perturbation, and endpoint; it is not a circuit-level causal claim.

## Validity and stop conditions

Stop and preserve the attempt if any of the following occurs:

- S11 panel, tokenizer, model revision, or observer identity mismatch;
- terminal sham parity with sealed features/readouts fails;
- intervention projector rank differs from the sealed rank-2 definition;
- nondeterministic repeat execution beyond frozen tolerance;
- target/control perturbation energy matching fails;
- missing rows, quartet members, cells, predictions, or bootstrap entries;
- any backbone parameter changes.

Ordinary software defects before outcome inspection should be traced and corrected in a versioned implementation, with the failed attempt retained. They do not require redesign when scientific inputs and outputs were untouched.

## Required execution packet if the design is accepted

1. Bind the S12 contract to exact S11 v02 panel/root, S09 observer/result roots, model/tokenizer identities, runtime, intervention formula, random-control seeds, outcome code, bootstrap plan, and execution order.
2. Perform tokenizer/input/model/observer identity preflight and establish exact terminal sham parity.
3. Run the six sites, four strengths, eight fixed random controls per site/strength, and deterministic repeat checks; keep model parameters immutable.
4. Seal raw perturbed activations or sufficient checksummed summaries, observer predictions, per-event margins, perturbation norms, and execution receipts before interpretation.
5. Independently replay a prospectively fixed subset or all outcome calculations and verify the shared bootstrap.
6. Seal result and stop.

This proposal does not authorize any of these execution steps. Its main reviewer decision is whether the primary endpoint should remain the established fixed-observer task output, or whether a separate model-native answer-generation task is required before using the word “behavior.”
