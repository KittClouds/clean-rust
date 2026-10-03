# Decision Data Information-Density Experiment v0.8

**Status:** dataset construction and audit only; model contact is blocked until the data gate is sealed.

## Purpose

This slice separates four effects that were previously entangled:

1. **Quantity:** more groups from the established generator (`Old100` to `Old250`).
2. **Generator quality:** a broader, more structurally varied universe (`Old100` to `NewTight-R100`).
3. **Curation:** metadata-driven selection from a fixed universe (`NewTight-R100` to `NewTight-C100`).
4. **Novelty:** transfer from the unrevised strict-remainder candidate (`StrictNovel93`), reported separately.

The 93,252-group remainder is now located in the detached worktree at `C:/Users/shuga/.codex/worktrees/3c8a/clean-rust/experiments/jev-curated-c100-v01/`. Its manifest reports 23,313 episodes from 1,132 roots, all `system_diagnosis`, with zero exact-ID, semantic-fingerprint, exact-text, normalized-text, structural-fingerprint, and root-family overlap against the specified current banks; the train-file SHA-256 was independently recomputed and matches the manifest. The candidate remains underfilled and family-narrow. It is a novelty-transfer diagnostic, not evidence that a selector found the best 93k from an overcomplete pool. Its original files remain untouched. It is never padded or relabeled `C100`.

## Hard boundary

Until every data artifact, overlap report, split manifest, selector receipt, and contract hash listed below is present and verified:

- Do not train, tune, score, or extract model features for LFM or any other model using either new bank.
- Do not use protected evaluation predictions or outcomes to generate, filter, stratify, or curate data.
- Do not change v0.4–v0.7 contracts, banks, reports, or receipts.
- Do not access Phoenix production data.
- Keep generated banks and run reports outside the repository, under `D:\codex-runs\jev-information-density-v08\`.

The new generator may use exact-world and gold metadata. The selection algorithm may not use model predictions, learned embeddings, protected-test scores, or post hoc adjustments.

## Preselection amendment: expose repeated inputs to the curator

The full 500,000-group generator audit found 30,956 unique normalized model-visible input signatures and 469,044 repeated occurrences. Each signature maps to exactly one exact gold target (`max_gold_signatures_per_input = 1`); the input/target consistency gate passed. This is a structural census of generated training-side metadata, not a model-performance result. Group count must not be presented as unique-input or unique-semantic count.

Before either bank was selected, C100 was amended to version `C100-v1.2-static-frequency-coverage`. Its redundancy axis includes the normalized model-input digest in addition to root, semantic, structural, and observable-text fingerprints. R100 is unchanged. The exact dynamic lazy-greedy implementation was stopped after more than ten CPU minutes without producing selected IDs; its preselection receipts were preserved. The final policy ranks each eligible group once using the equal-axis mean of inverse-square-root *eligible-pool feature frequency*, then chooses the exact top 100,000 with the frozen deterministic tie-break. This is a static global coverage ranking, not dynamic greedy selection. The v1.2 seed and selector source hash are recorded in the selection receipt. This makes the curator explicitly observe exact exposed-input repetition; it does not make repeated inputs disappear, and the final information-density report must show unique-input counts for both banks. The full universe may proceed if it passes the frozen 300,000 eligible-group floor, but that floor is not evidence of 300,000 distinct inputs.

## Model-visible target consistency

The pilot uncovered identical normalized state/query/candidate inputs with different exact targets when causal topology and parameterization varied invisibly by sampled root. That is not a valid information-density example: the target would depend on a generator variable absent from the model input. Before any full universe is accepted, topology and parameterization are fixed within each observable domain family; sampled truth and evidence continue to vary. Every group carries a digest of its normalized model-visible input and a digest of its exact typed target. The signature includes observable state, query view/instruction, candidate-set role/semantics/order, exposed candidate name/definition, and ordinal rank where applicable. It excludes internal semantic IDs, latent values, and gold values; candidate presentation order is normalized away. The preselection audit must report zero input-to-multiple-target mappings. A conflict blocks selection and requires a new generator revision; it is never “resolved” by majority vote.

## Bank roles and lineage

| Name | Role | Frozen interpretation |
|---|---|---|
| `Old100` | Historical quantity reference | v0.5 bank; manifest reports 100,060 groups, not exactly 100,000. |
| `Old250` | Historical quantity reference | v0.6 bank; manifest reports 250,052 groups. |
| `StrictNovel93` | Novelty-transfer diagnostic | User-reported 93,252 groups; preserve exact artifact and report verified counts/overlap. Not a curated comparison. |
| `NewTight-Eval` | New-generator family-held-out evaluation bank | Reserve families before any train-bank selection; never used for selection. |
| `NewTight-R100` | Same-universe randomized control | Exactly 100,000 atomic decision groups, sampled by the frozen stratified-random policy. |
| `NewTight-C100` | Same-universe curated bank | Exactly 100,000 atomic decision groups, selected by the frozen metadata-only coverage policy. |

The read-only tail audit defines the tail as S250 serialized grouped-train ordinals 100,001–250,000, not `S250 minus S100`. It found 150,000 tail groups, 37,501 episodes, and 1,861 root families. Although root-family IDs are nested, only 22,346 episode IDs overlap S100; just 37 overlapping episodes share a semantic fingerprint, and only 3,804 of 89,384 overlapping group IDs share candidate-aligned gold. Therefore S250 is not a clean content-nested S100 expansion.

On the current compiler-visible input signature (state/query plus `name_definition` candidate surfaces), the tail contains 7,863 unique signatures and 142,137 repeated occurrences, with no signature mapping to conflicting gold. All 19 candidate semantic IDs, candidate-definition tuples, query semantic IDs, candidate-set combinations, 66 coarse structural tuples, and 32 observed-variable masks already occur in S100. The tail does add 258 generator-side latent-state signatures not seen in S100; these are not necessarily model-visible novelty. Its median target entropy is 0.611 and 35,828 groups have maximum gold probability at least 0.95; this is target concentration, not model-evaluated ease. These measurements support low visible-structure novelty in the historical tail, not a claim that a selector curated better examples.

## Universe, split, and firewall order

1. Pin and hash generator source, configuration, schemas, candidate ontology sources, and all legacy manifests.
2. Generate an overcomplete raw universe. Target 400k–500k potentially eligible groups. Do not call it overcomplete unless at least 300,000 groups remain eligible after validation, legacy-firewall exclusions, and removal of held-out evaluation families.
3. Assign train/evaluation roles before constructing either training bank. The indivisible split unit is a `split_family_bundle_id`: each bundle names one coherent world/topology, ontology, schema-composition, candidate-construction, definition-template, and intervention family package. Component family IDs, root IDs, and episode IDs must each belong to exactly one bundle. Hold out bundles with `SHA256(frozen_salt || "family_bundle" || bundle_id)` at a 20% target. This preserves about 80% of the raw group universe for training while guaranteeing that every held-out component family is absent from training. Verify actual held-out and retained coverage on all six axes; report a missing axis as unavailable rather than renaming IDs to simulate novelty.
4. Construct `NewTight-Eval` from valid held-out-bundle groups. Tag every evaluation group with the six held-out axes and its bundle identity in the protected split sidecar. Exclude all such groups, and all their family-linked siblings, from the eligible training universe. This is a composite OOD evaluation; it is not a factorial estimate of each axis's independent effect.
5. Apply the same frozen validity and overlap firewall to candidate training groups. Compare against all prior generated training banks, v0.4–v0.7 training sources, the verified read-only `StrictNovel93` files, and protected evaluation-family registries. Emit only collision counts and digests for protected material; do not export protected text.
6. Freeze the resulting eligible universe and its hash. Only now construct `NewTight-R100` and `NewTight-C100` from that exact universe.

The firewall checks, where available, episode/group IDs, root/parent IDs, semantic fingerprints, exact and normalized observable-text hashes, runtime-schema surface hashes, normalized model-input hashes, structural fingerprints, world-family IDs, ontology-family IDs, schema-composition IDs, generator-template IDs, definition-template IDs, and perturbation-family IDs. Text normalization is Unicode NFKC plus lowercase, replacing each non-alphanumeric run with one space and trimming. Raw text is not included in overlap receipts. The normalized model-input signature combines observable state, query semantics/instruction, and candidate names, definitions, aliases, and opaque IDs in semantic-ID order.

Any collision or invalid target is excluded before R/C selection and counted by reason. Conflicting source labels are reported, not silently resolved. The final audit must establish zero prohibited train/evaluation family crossing and report exact/normalized/structural collisions separately.

## Matched bank policies

### `NewTight-R100`

Select exactly 100,000 atomic decision groups from the frozen eligible universe. Use proportional stratification on the broad tuple `(world family, query/view type, candidate-cardinality bin, posterior-entropy quintile)`. Allocate integer quotas by largest remainder, then order members within each stratum by `SHA256(frozen_seed || group_id)`. This is a random/stratified baseline; it must not rank examples by difficulty, confidence, uniqueness, or model behavior.

### `NewTight-C100`

Use the same eligible universe and exact 100,000-group budget. The sole allowed ranking signal is a prospective global rarity-weighted coverage score over eligible training-side metadata. For each group, expose categorical features in five equally weighted axes:

- semantic novelty: world family, ontology family, schema composition, candidate-definition family;
- local discrimination: explicit ontology-distance/density category (unknown/proxy remains a distinct category);
- probability geometry: exact-gold entropy band and target type;
- structural coverage: causal/ontology topology, query type, candidate-cardinality bin, evidence-density bin, intervention class, and rendering family;
- redundancy: root-world ID, semantic/structural fingerprint, normalized-observation hash, and normalized model-input hash.

Score each group once as the mean across axes of the mean `1/sqrt(eligible_pool_count(feature))` for its features. Select the top 100,000; ties break by ascending `SHA256(frozen_seed || group_id)`, then lexical group ID. The bounded top-k procedure is deterministic and does not iteratively update feature counts. It deliberately favors under-covered metadata signatures, not examples predicted to be difficult by a model.

If the selector cannot reach exactly 100,000 valid groups, or any selector rule requires post hoc changes, fail closed and issue a new protocol version. Never overshoot silently. R/C overlap is allowed because both are samples from the same universe; report exact group, root-world, and fingerprint overlap.

## Required evidence and completion gate

Before model contact, seal the protocol and produce:

- Old-tail audit: group/family nesting, exact Old100-minus-Old250 relation, fingerprint growth, family/topology/query/cardinality/entropy/intervention composition, and classifications of added material (new constraint, new structural combination, surface-only, near duplicate, family repetition, or redundant/easy case). Unknown classifications stay unknown.
- New-universe audit: raw, valid, held-out, firewall-excluded, and eligible counts; duplicate and rejection reasons; family/topology/ontology/definition diversity; and deterministic novelty-growth curves.
- Input-target consistency audit: unique model-input signatures, repeated input count, conflicting input-to-gold mappings (required zero), and digest of the audit implementation.
- New evaluation split receipt: held-out family IDs in a protected sidecar, axis coverage, zero crossing to any training family, group counts, and hash.
- Same-universe selection receipt: eligible-universe hash, exact R/C group counts, policy/seed hashes, strata and coverage census, overlap, and proof that neither selector read evaluation scores or model outputs.
- `source-audit.json`, `old-tail-audit.json`, `new-universe-novelty-audit.json`, `input-target-consistency.json`, `ood-family-split.json`, `source-overlap-report.json`, `r100-c100-selection-audit.json`, `information-density.json`, `novelty-growth-curves.json`, and `v08-integrity-receipt.json`.

The target for calling the candidate universe genuinely overcomplete is at least 300,000 eligible training groups for a 100,000-group bank. If it falls short, the result is “insufficient selection surplus”; do not treat a 100k subset as a curation experiment.

After, and only after, this gate is complete, a separate sealed run may compare LFM on `Old100`, `Old250`, `StrictNovel93` (if verified), `NewTight-R100`, and `NewTight-C100`. The core curation contrast is paired `R100` versus `C100`: same eligible universe, group budget, head, optimizer, update count, and evaluation. Keep all previous results read-only. `NewTight-Eval` and the legacy protected evaluation remain untouched by selection and training.

## Interpretation limits

- `Old100 → Old250` is a historical quantity contrast; state exact group/update counts and any schedule differences.
- `Old100 → NewTight-R100` is a generator/universe contrast, not a pure generator-quality causal estimate unless training budget and group semantics match.
- `NewTight-R100 → NewTight-C100` is the intended selection-policy contrast.
- `Old250 → NewTight-C100` compares information composition against historical quantity; it is not a single-factor causal contrast.
- `StrictNovel93` tests transfer under strict novelty with its narrow family coverage preserved. Zero overlap and broad coverage are distinct properties.
- Report discrimination, calibration, binding, OOD, and intervention metrics separately. Do not produce a composite winner score.

No result in v0.8 reopens the v0.4 QLoRA gate.
