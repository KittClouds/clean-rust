# E4 Capability Fabric — Codebase Map v01

**Status:** planning map only, 2026-09-26. The current user instruction is to read, understand, and plan. No E4 panel construction, model contact, scoring, fitting, dispatch, or serving measurement is authorized by this map. The authorization requests inside the source proposal remain requests.

## Pinned source and starting line

The exact source proposal is preserved as [e4-proposal-source-v01.md](e4-proposal-source-v01.md): 16,014 bytes, SHA-256 `44d411190d69b317201e43b11126f3fad418caecbb0d8f98ec9b1180ee758bc6`. It was copied byte-for-byte from `D:\1-story\1-Notes Central\1- Core story\Newest Data\1-clean data\Lore\part 2\World\1-rewrite\!1-notes\! V5 rewite\E4 Proposal — Capability Fabric Routing and Integration.md`. The source copy is reference material; this map records the codebase reading and the single-phase work order.

| Existing identity | Root / binding | Current meaning |
| --- | --- | --- |
| E0 v10 | `899a131c09298fdafdcc6771ad01e8982857a1cd47900259800f97dd7bea7ccd` | Frozen E3-era model, ABI, resources, observer, and economics contract. |
| E1 v04 | `6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03` | Sealed 106,496-row, 26,624-quartet population with FIT/TEST split. |
| E2 v07 | `a2e2aa76f77904665b9abfa2a22f609c05219d8bc64c537bed41f5c634d1da8a` | Byte-stable 2,048D `V1_FINAL_POSITION` feature cache. |
| E3 v02 fits | `899ff6a61272b86fdf1cd51d8c14100e77185157c242f27fbffe452803a435e1` | Five fixed independent scaler-plus-linear-head artifacts. |
| E3 score v02 | `a104bffedbc3e31268c0f1c0103ad4326add5a9da93816007904b70cdf3c7d1f` | All eight individual held-out gates passed and independently replayed. It does not supply a simultaneous bundle guarantee. |

The [later Day 7 checkpoint](../../../docs/day-07-research-state-2026-09-26-late.md) carries the current cross-lab state. The project [README](../README.md) is a preserved earlier E2 snapshot, so the seals and receipts above govern current status. E4 is still unopened.

## What the current code can supply

| Seam | Observed code and artifact | E4 implication |
| --- | --- | --- |
| Panel generation | [`generate.rs`](../source/panel-generator-v04/src/generate.rs) SHA `fa2bd0617135a0dce4e12f0e0967f82e461133b394a7d969daba5afb11e2cce1` has a fixed seed, eight observation templates, eight query templates, and a deterministic factorial schedule. `term_inventory()` uses that seed to assign the 32 context and 32 entity IDs. The quartet key does not include a population namespace. | A versioned E4 generator must create genuinely fresh items and IDs while preserving the E1 class-ID-to-term mapping required by the frozen identity heads. Merely changing the generator seed would change label meanings, and merely rerunning the schedule would not establish a fresh population. Check quartet, row, and rendered-input overlap against E1 before sealing. |
| Panel materialization | [`main.rs`](../source/panel-generator-v04/src/main.rs) SHA `7ce62779ddf8dd994ad9ace6a10dd5bda76de3bd87c1c0e19459cf38b428ec0f` binds E0/E1 identities and writes only `FIT` and `TEST` partitions. The E3 fitter consumes FIT; there is no separately sealed E1 validation partition. | The proposal's “E1 train/validation rows” for label-free parity must be specified as eligible E1 FIT rows, or a newly defined partition. A new E4 panel builder needs its own split, support, label-isolation, and source receipts. |
| Template shift | All eight E1 query-template IDs are traversed by the generator; IDs 6 and 7 have a `HELDOUT` style-role string, but the E1 FIT/TEST split is by whole quartet, not by template. | E4's held-out-template set must contain newly frozen template text absent from E1 and every fit. The old style-role string is not evidence of structural holdout from E3 training. |
| Representation | [`representation-abi-v07.json`](../contracts/representation-abi-v07.json) SHA `3b36b066111872290b9f37a877b9043650867fa81658476c783a5c7e7485d319` fixes pinned model/tokenizer/runtime, CUDA:0, float32, batch 1, no padding/truncation, and `last_hidden_state[0, sequence_length - 1, :]`. [`extract_features_v07.py`](../source/scripts/extract_features_v07.py) SHA `2b210d4f65c37d823b7060278c8a29db3a5c5f7fb535e6bb28d5147bc56b7b24` is a one-shot E1-bound extractor. | E4 needs a separately versioned online extractor/loader. Start parity with the existing batch-1 CUDA path; any batched or cross-device serving path needs an explicit configuration and tolerance before it is tested. Keep E2 source and cache immutable. |
| Frozen heads | The E3 [bundle manifest](<D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e3-v02\frozen-capability-fabric-v02.json>) SHA `8fa86f8c9891949196844ca62522822a246e47b4185cc4ed45c45136ada6576f` binds each head's little-endian float32 mean, scale, weight, and bias. [`score_e3_v02.py`](../source/scripts/score_e3_v02.py) loads those files and computes standardized linear logits. | Reuse the sealed arrays read-only, verify every hash, and preserve task-specific output types and fit scopes. No E3 refit or threshold change is part of E4-0. |
| Scoring | The E3 scorer is bound to E1 TEST and computes the 5th percentile of 10,000 class-stratified whole-quartet bootstrap replicates. | A new E4 scorer/auditor must bind the new population and implement the proposed Bonferroni per-endpoint lower quantile `0.05 / 8 = 0.00625`. Reusing the E3 scorer unchanged would test the wrong panel and the wrong confidence level. |
| Economics and parity | [E0 v10](../contracts/e0-freeze-v10-sealed-v01.json) defines B1 shared extraction, B2 repeated pipelines, five-output fanout, single-head requests, and identical-feature standalone/bundle parity (100% labels; logits `atol=rtol=1e-6`). | E4-A must measure online per-request latency separately from E2's 3,402.17-second full-panel extraction. A B2 value computed from receipts must be labeled arithmetic unless the repeated serving plan is actually run. Online feature tolerance is a separate, still open E4-0 decision. |

## First phase: design E4-0 only

1. **Freeze the population definition before construction.** Preserve the E1 term inventory and class meanings; define a new population namespace, fresh world/render schedule, explicit E1-overlap check, and whole-quartet unit. Freeze the new template text and hash before generation. Specify seen-rendering, lexical novelty, template novelty, and any joint stratum. Reserve distinct label-access partitions needed by future companion analyses without running those analyses.
2. **Freeze online/cache parity.** Choose the intended device and batch configurations and a numerical feature tolerance before observing parity results. Use a hash-fixed, label-free panel of E1 FIT rows for the initial comparison. Require per-head prediction agreement and receipt replay; bind the original E2 ABI and E3 head hashes. The existing E0 identical-feature logit tolerance remains a separate invariant.
3. **Freeze fresh simultaneous qualification.** Keep the five E3 heads and eight task definitions fixed. Decide the performance floor and per-class support prospectively; the 0.90 E3 floor is the continuity baseline. Size each fresh stratum for the one-sided `0.00625` whole-quartet bootstrap lower bound, register replicate count/RNG/quantile method, and keep held-out-template results outside this eight-endpoint gate for the companion branch.
4. **Freeze resources and truth access.** Budget the new corpus, row manifest, feature cache, staging copy, model residency, and disk reserve from the selected population size. Require an available GPU lease before eventual model contact. Define separate sealed receipts for construction, feature extraction/parity, label opening, score, and independent replay.

This map leaves those choices open. It is not an E4-0 contract or a preflight pass. The first eventual run boundary is fresh panel construction and seal; model contact and held-out scoring need their own explicitly bound gates after that panel is audited.

## Phase queue and stop points

| Order | Stage | Present state | Advance only when |
| --- | --- | --- | --- |
| Now | Proposal pin and codebase map | Complete planning artifacts | Review the E4-0 open decisions above. |
| Next | E4-0 contract and fresh panel design | Proposed | A versioned contract fixes population identity, support, templates, resource envelope, parity configurations, and truth partitions. |
| Later | E4-0 panel, parity, fresh qualification | Not executed | Each preceding gate passes and its artifact is sealed/audited. A parity or qualification failure preserves the attempt and stops this path. |
| Later | E4-A typed dispatch and serving economics | Proposed | E4-0 has a disposition; E4-A receives its own freeze and authorization. Its typed task ID is explicit dispatch, while E4-B addresses inferred request routing. |
| Later | FF-BUNDLE-TEMPLATE-01 and FF-BUNDLE-ATTRIBUTION-01 | Proposed, separate identities | Their fit/evaluation populations and truth-access rules are frozen separately. Sharing construction does not grant shared execution authority. |
| Later | E4-B, E4-C, E5 | Proposal only | Prior stages answer their bounded questions and each next branch gets a new decision. |

One unresolved dependency deserves attention during E4-0 design: attribution compares newly fitted feature-source heads, whereas E4-0 qualifies the already frozen E3 heads. The population contract must say whether those new fits use E1 FIT or a distinct fresh FIT/DEV partition, and must prevent them from using E4-0's terminal scoring labels. The proposal also leaves open whether E4-A can run as a systems-only measurement after fresh qualification fails; no answer is assumed here.

**Stop rule for this planning checkpoint:** no E4 execution follows from the copied proposal or this map. The next concrete artifact is a reviewed E4-0 design with the open choices resolved, while E3's sealed results and earlier Day 7 snapshots stay intact.
