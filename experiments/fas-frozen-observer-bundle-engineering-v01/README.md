# Frozen Substrate, Narrow Observer Bundle — Engineering Path v01

**Status:** `E0_V04_E1_V04_SEALED_E2_V01_PRESERVED_GPU_RESOURCE_GATE_UNVERIFIED; E0_V05_DRAFT; E2_V02_NOT_AUTHORIZED`  
**Created:** 2026-09-25; machine freeze v04 and panel contract v03  
**Purpose:** Preserve the starting point and define the first engineering question for the frozen-backbone / narrow-observer direction.

This is a new downstream engineering identity. It does not reopen or revise FAS-00, S01, S05–S11, or any sealed result. Historical artifacts motivate the design; they are not the evaluation set for this branch.
It is separate from the proposed FAS-S12 causal intervention and authorizes no part of that work.
Version 01 is one pinned 1.2B Base model only. No scale comparison, second representation surface, shared head, multitask loss, model update, or fine-tune belongs in this run.

## Current checkpoint — E1 sealed; E2 v01 preserved, not E3-eligible

E0 freeze v04 root: `fef50e3d7efe6ff35adf671940ee73112caf8ba6192596094aa6bb3e69ae9ab2` (`seals/e0-seal-v04.json`). It binds the machine-readable observer gates, B1/B2/B3 economics, serving workloads, representation ABI, extraction source, panel contract, and construction sources.

E1 panel v04 root: `6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03` (`D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e1-panel-v04`). The fresh panel has 26,624 quartets / 106,496 input rows, with 85,204 fit rows and 21,292 test rows. All eight support endpoints pass; the smallest test class has 592 rows against the frozen floor of 200. The [independent audit receipt](audits/e1-independent-audit-v04.json) rechecked both roots, row identity, whole-quartet split, label isolation, all support counts, and resource receipts.

**Receipt erratum:** E1's sealed split and labels are correct, but its build receipts mislabeled all quartets per target class as test quartets and reported `fit_quartets=0`. Use the [append-only correction](audits/e1-receipt-correction-v04-v01.json): all quartets `[8876, 8874, 8874]`, test quartets `[1775, 1774, 1774]` (5,323 total), fit quartets `[7101, 7100, 7100]` (21,301 total). Row totals remain 21,292 test / 85,204 fit. The E1 tree was not modified; its root remains valid. Do not use the incorrect count fields in the sealed build receipts.

The builder reports about 33.9k panel input rows/second on this machine. That measures panel construction only. E1 records `model_loaded=false`, `tokenizer_loaded=false`, `feature_extraction_performed=false`, `observer_fitting_performed=false`, and zero feature rows.

**E2 v01 disposition:** the user's explicit authorization bound to the E0/E1 roots was recorded before model contact. The pinned tokenizer and model passed their actual-asset hashes and runtime/ABI checks. The single `V1_FINAL_POSITION` pass wrote 106,496 rows (872,415,232 bytes); the 256-row repeat matched byte-for-byte. Independent checks passed the E1 ordered row identity, `[106496, 2048]` little-endian float32 shape, and all 218,103,808 values finite. Feature cache SHA-256: `8eb80df5f73e761fe6c025fc1c66abef2027d639b6c14f56d4177d6e6a7a45a4`.

The attempt is **not E2-complete and its cache is not eligible for fitting**. The E0 GPU-memory ceiling is 10,240 MiB. Device-wide telemetry sampled 11,814 MiB used and 278 MiB free while E2 PID 43172 overlapped a separate FAS-S12 Python workload, PID 34332 (`run_s12_v02.py`). Windows telemetry did not reliably attribute GPU memory to either process. This establishes neither an E2 process-level exceedance nor a pass, so the resource gate is **unverified**. Append-only corrections preserve the initial telemetry and supersede first the preliminary `PASS_WITHIN_FROZEN_LIMITS` claim, then the overstrong aggregate-exceedance disposition. The full attempt is preserved under `D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e2-v01` with current preservation root `0ff309d833cd87017f7384247e4420a508f582ad9f375c5637f586d73b703f4c`. No observer fitting, scoring, label opening, E3, or E4 work occurred.

## Proposed E0 v05 / E2 v02 amendment

The draft [process GPU measurement update](audits/e0-e2-process-gpu-update-v05-draft.md) defines the 10 GiB gate narrowly as the extractor process's PyTorch CUDA caching-allocator reserved peak. It explicitly does not claim total GPU memory used by E2; `nvidia-smi` device totals remain diagnostic-only. It also requires zero allocated/reserved current and peak counters after CUDA initialization and again after the peak reset, before loading the tokenizer or model.

The update adds a prospective byte-exact cache-equivalence gate against the preserved E2 v01 cache: SHA-256 `8eb80df5f73e761fe6c025fc1c66abef2027d639b6c14f56d4177d6e6a7a45a4`, `872415232` bytes. E2 v01's cache may be read only as a hash comparator; it is not v02 feature input and remains ineligible for fitting. A mismatch or change to the reference means preserve and stop.

The identified FAS-S12 run wait completed at `2026-09-26T05:18:12.9008204Z`: PID 34332, started `2026-09-25T20:08:43` local, was observed absent at `05:17:42.765Z` and `05:18:12.900Z`. The [completion receipt](audits/e2-v02-concurrent-wait-complete-v01.json) SHA-256 is `b926124f9aa55b1b9fec2d794d0ac6a7a808128d43df9d53babb6cf143454b80`. A separate device-wide snapshot at `05:19:27Z` showed 2,084 MiB used / 10,008 MiB free / 9% utilization; this is diagnostic context, not process attribution ([receipt](audits/e2-v02-post-wait-gpu-diagnostic-v01.json)). E0 v05 remains unsealed and E2 v02 remains unauthorized. Do not begin E2 model contact. The [latest draft integrity receipt](audits/e0-e2-draft-integrity-receipt-v08.json) binds these additions; v01–v07 preserve earlier draft states.

Preserved attempts and seal history:

- E1 v01 stopped at world-contract authority-field validation before creating panel outputs. Its preflight and failure receipt remain at `D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e1-panel-v01`.
- E0 v02 was superseded before E1 because its seal entry list named the v01 freeze and omitted the v02 freeze. The original manifest and an audit-defect receipt remain in `seals/`.
- E1 v03 stopped at the nested support-floor field check before creating panel outputs. Its preflight and failure receipt remain at `D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e1-panel-v03`.
- E0 v04 binds those earlier records and the corrected validator. E1 v04 is the first panel generation that reached and passed the support and storage gates.

No failed attempt produced a panel row or contacted the model/tokenizer. Keep each failed root and its receipt; do not reuse it for a later version.

## Start here

The engineering question is whether one pinned frozen representation cache can serve several small, independently fitted observers as one deployable bundle:

```text
one frozen backbone
  → one fixed representation surface and shared feature cache
  → independent linear observers for context, entity, relation, state, and target
```

The first milestone tests a shared cache with separate heads. It does not test a shared or jointly trained head. Each observer remains its own fitted scaler-plus-linear-readout system; integration must preserve each standalone observer's outputs.

## Historical starting point

| Stage | What the record says | Boundary |
|---|---|---|
| FAS-00 | Held-out context-term exact-target transfer scored `0.565406` against a `0.60` gate; entity-term transfer scored `0.811948`. FAS-00 closed as `SENSOR_FAIL_NO_SIGNAL`. | This is a failed required sensor gate, not evidence that the representation contains no usable information. Its result and inputs remain unchanged. |
| S01-3, mean-full (`V0`) | On the exploratory grouped split, exact-target balanced accuracy for context-novel / entity-novel / both-novel terms on seen templates was `0.866936` / `0.846252` / `0.758267`. | Linear probes fit the already sealed cache. The S01 population and split were already revealed; these are historical diagnostics, not fresh generalization estimates. |
| S01-3, final-position (`V1`) | The corresponding values were `0.999025` / `0.997260` / `0.991986`. | Strong motivation for testing the surface; not a guarantee on a fresh panel. Do not call these context/entity identity classifiers: these are exact-target transfer strata. |
| S05 | Fixed native representation-plus-readout pairs performed far better than crossed pairs on the S01 population. | A complete system includes the representation and its fitted readout. Do not mix readouts across surfaces and call that a head-only comparison. |
| S11 | Fresh quartets confirmed higher off-diagonal transport for the fixed F observer bank than the M bank, under the fixed generator and observer bank. | This is observer transport evidence, not a multi-task bundle test or a causal mechanism result. |

The current cross-lab baseline is [Day 6 Research State](../../docs/day-06-research-state-2026-09-25.md). It records FAS, JEV, and R&D-C histories, seals, open questions, stop rules, and the resource snapshot. Keep that snapshot immutable; add a new dated snapshot for future checkpoints.

The S01-3 metrics are in `D:\codex-runs\fas-s01-frozen-sensor-transfer-cartography\s01-3-linear-accessibility-v01\metrics-v01.json`; result-tree root SHA-256: `2581b50d75382c197793ea46400bf2b8a27508df22b2ff5bdbe82eb20a5238b7`. The output is explicitly marked `COMPLETE_EXPLORATORY_LINEAR_CARTOGRAPHY` and belongs to an already revealed population.

### Pinned historical substrate and surface

The source contracts and execution receipts resolve the historical backbone to `LiquidAI/LFM2.5-1.2B-Base@7453bca97ca1e67754c4035a4b4c584e1c9dd725`. Use this revision for v01. It resolved to the same commit in the FAS-00 and S01 records; do not use a mutable `main` reference.

- Model asset manifest SHA-256: `a76c55c90e6beaaf6acf145abcfbfa6bd5cbb7a1ff4788cbb80856f62adaa56e`.
- Historical tokenizer revision: `7453bca97ca1e67754c4035a4b4c584e1c9dd725`; S01 tokenizer asset-manifest SHA-256: `c5e9a5b08ec5658ef2a8760d8230bbe9367bea124451488e164baf0eeca95afc`. Before E2, hash the actual tokenizer files used and require a match to the pinned manifest; if it does not match, stop and version the identity rather than silently substituting.
- `model.safetensors` SHA-256: `7678ab9546a0c51c1fca161876b1efc4f0906277f170b5822045f40fdaf9eeff`; file size `2,340,697,936` bytes.
- Loaded state identity SHA-256: `14b8ccb6c347eb5a91ccb718de39d70865f15410f5b6e62ca747aaf77f6bb9e5`; the historical float32 state contained `1,170,340,608` elements and `4,681,362,432` bytes.
- Historical extraction used float32 inference, one row at a time, exact sequence length, no padding or mixed-length batches, with zero backbone parameter changes. The recorded device was an NVIDIA GeForce RTX 3080.
- Freeze one surface: `V1_FINAL_POSITION`, final hidden layer at token position `sequence_length - 1`, dimension 2048, serialized as little-endian float32. No layer or pooling search.
- The old model asset is present in the S01 run tree at `D:\codex-runs\fas-s01-frozen-sensor-transfer-cartography\s01-2-feature-geometry-v01\model-assets\hub-cache\models--LiquidAI--LFM2.5-1.2B-Base\snapshots\7453bca97ca1e67754c4035a4b4c584e1c9dd725`. E2 may reference it read-only only after rehashing the file and matching the pinned receipt. Do not reuse any S01 feature rows, corpus, labels, or fit artifacts.

### What this history changed

The original sensor failure asked whether the selected sensor exposed enough of the needed target computation. S01 showed that a fixed linear observer could access much stronger task structure on a controlled corpus, especially on the final-position surface. S05 showed that representation/readout compatibility is part of the system. S11 separately established bounded transport behavior on fresh worlds.

The engineering hypothesis is therefore narrower than “the backbone is an entity model” or “fine-tuning is unnecessary”:

> A fixed frozen representation may support useful task-specific systems through small readouts, if each readout is matched to that exact representation and evaluated on a fresh, appropriately split population.

## First experiment question

**Can one frozen feature cache support five separately fitted linear observers with acceptable task performance, while avoiding repeated backbone passes and duplicate task-cache storage? What are the resulting five-head fit, storage, and serving costs?**

The first experiment must answer each task separately. Do not average task performance into one score or let a strong entity result hide a failed target observer.

### Proposed first system

- **Context term identity:** predict the explicit 32-way `context_term_id` class. Every class occurs in fitting rows; evaluate on held-out complete quartets. This is closed-set term-ID classification, not unseen-label recognition.
- **Entity term identity:** predict the explicit 32-way `entity_term_id` class under the same closed-set rule. Evaluate on held-out complete quartets.
- **Relation:** fixed 2-way classification of `relation_id`; both labels occur in training and test.
- **Observed state:** fixed 3-way classification of `state_id`; all labels occur in training and test.
- **Exact target:** fixed 3-way classification of `exact_target`; all target labels occur in training and test. This is the composed target task, distinct from predicting any input-factor ID.

The first two labels are surface-term IDs, as in the S01 `context_term_id` and `entity_term_id` tasks; they are not silently relabeled as underlying canonical context/entity referents. If referent-level identity is the required product behavior, define and bind that distinct target in a new contract before E1. Context/entity heads fit on all 32 term-ID classes. Relation, state, and exact-target heads fit only rows whose context and entity term IDs are both in their 16-member train-side sets, matching the S01 fitting boundary. Score relation and state on held-out quartets with both terms in-domain. For exact target, also score three lexical-transfer slices: context term novel, entity term novel, and both terms novel. Novelty means those surface terms were excluded from exact-target fitting; the three target class labels remain known from training. Do not report these as identity-classifier accuracy or ask a closed-set head to predict labels absent from its fit set.

Use 26,624 fresh quartets with four rows each (106,496 event rows), matching S01's panel size for an interpretable cache budget. Use new world seeds and new lexical term strings, with the sealed 16/16 train-side/novel-heldout term-ID allocation per role and a fresh deterministic assignment. Keep each quartet intact in an 80/20 deterministic fit/test split. The identity observers fit on all 32 `*_term_id` labels; relation, state, and target observers use only the 16-by-16 train-side context/entity combinations. The fresh panel builder must validate the per-class support floors before any feature extraction.

Fit five separate multinomial linear observers, each with its own train-only scaler and readout. Use the historical fixed linear recipe (zero initialization, unregularized intercept, L2 `1e-4`, fixed LBFGS settings) unless the sealed v01 contract states an independently justified revision. No shared trainable parameters, joint fit, view search, or post-score tuning.

One full-panel extraction produces one immutable cache and one row-identity manifest. The five fits read this common cache. A 256-row deterministic extraction repeat is a setup gate and is separately recorded; it does not count as a second full-panel extraction. Bundle integration must preserve each standalone observer's predictions and scores on identical feature rows.

S01 established the historical task definitions and a possible surface. It does not supply the fresh panel, thresholds, model revision, or new execution authorization.

## Measurements to freeze before execution

Report these separately, with exact denominators and per-task results. Freeze these v01 acceptance floors prospectively; they are engineering utility gates, not thresholds inherited from S01:

1. **Task behavior:** accuracy, balanced accuracy, per-class recall, and confusion matrix. Each of the five primary in-domain task scores must have a one-sided 95% whole-quartet-bootstrap lower bound of at least `0.90` balanced accuracy. The exact-target context-novel, entity-novel, and both-novel slices must each pass the same bound independently. Require at least 200 test rows per class in every scored endpoint; fail panel construction before extraction if support is short. No task average can rescue a failed endpoint. These are eight individual engineering gates; they do not make a simultaneous 95% guarantee over the bundle, and no familywise-adjusted claim is made.
2. **Observer size:** record parameters and bytes per head and for the bundle, including scalers; report the backbone as frozen context and the trainable fraction. With the stated dimensions and class counts, the expected heads contain 147,528 linear parameters (590,112 float32 bytes) plus 81,920 float32 scaler bytes, about 672,032 bytes total before metadata. Confirm from the fitted artifacts. B1 and B2 both have five independent heads, so observer trainable state is not a B1 saving; report it as the cost of the specialized interfaces.
3. **Work and latency:** capture one full-panel extraction receipt, per-head fit time, total fit time, cache read time per head, and standalone/bundled readout latency at fixed batch sizes. Record actual hardware/runtime versions. Separate backbone extraction from readout-only latency. Historical S01 receipts do not contain a comparable full-run wall-clock duration, so v01 must establish it.
4. **Memory and storage:** peak host RAM and accelerator memory; model and cache asset bytes; input, row-manifest, observer, temporary, and final-output bytes; and free bytes on each used volume before and after.
5. **Integration parity:** on the same cached rows, require exact predicted-label agreement and `allclose(atol=1e-6, rtol=1e-6)` for each standalone-versus-bundled logit vector. Any mismatch fails bundle integration; it cannot count as beneficial task sharing.

Use a task-specific, class-stratified bootstrap that resamples complete quartets, with 10,000 replicates and a frozen seed. Identity evaluation remains closed-set; exact-target lexical transfer is scored only on the three predeclared novel-term slices plus in-domain.

## Economic baselines

Define the compared work precisely:

| Baseline | Definition | Role in v01 |
|---|---|---|
| `B1_SHARED` | One full extraction of the common 106,496-row panel, one 2048D float32 cache and row manifest, five heads. | Actual v01 path; receipts capture extraction, cache, fit, read, and serving costs. |
| `B2_FIVE_PIPELINES` | Five task-specific pipelines each run the same pinned backbone over the same rows and materialize their own identical cache and row manifest; one input corpus is shared read-only. At serving, each task pipeline repeats the backbone pass for its requested task. | Primary counterfactual. Work is 5× the measured B1 full-pass work; storage is 5× one task-specific cache-plus-manifest. Report savings as receipt-derived arithmetic, not as an executed five-run latency. The five independent heads occupy the same total observer state as B1. |
| `B3_FIVE_DEPLOYED_BACKBONES` | Five separately stored/loaded copies of the pinned backbone, each with one head. | Deployment-context arithmetic only; not run or used for the primary claim. |

For the historical panel size, one feature cache is `872,415,232` bytes (832 MiB) and its row manifest is `368,110,353` bytes. Thus `S_task = 1,240,525,585` bytes; B2 is `6,202,627,925` bytes and B1 saves `4,962,102,340` bytes (about 4.62 GiB) in task-specific cache/manifest artifacts. The full-panel work count is 106,496 row forwards for B1 versus 532,480 for B2, or 425,984 repeated row forwards avoided. B1 still pays for five observer fits and five readouts; it does not reduce those costs relative to B2. Capture actual v01 extraction time/bytes/peak memory; derive B2 from that receipt and label it counterfactual.

For B3 context only, the historical `model.safetensors` artifact is `2,340,697,936` bytes: five copies would be `11,703,489,680` bytes before filesystem deduplication. The loaded float32 state was `4,681,362,432` bytes, so five independent resident states would be `23,406,812,160` bytes before activations. These are arithmetic bounds, not measured deployment costs. B1 and B2 both use one pinned backbone; five heads do not imply five model copies.

### Serving workload definitions

The declared bundle-serving workload is **one raw input → one backbone extraction → all five requested heads**. For that fanout, B1 has one extraction and five readouts; B2 has five pipeline extractions and five readouts. Any B2 serving comparison remains receipt-derived counterfactual arithmetic unless separately executed.

Also report **one raw input → one requested head**. B1 and B2 each need one extraction for that request, so v01 makes no shared-compute advantage claim for one-head serving. Report backbone extraction separately from readout-only latency in both workloads.

### Representation ABI receipt

`contracts/representation-abi-v01.json` is the exact representation identity required by every observer. It binds the model revision, config and weights hashes, tokenizer manifest, Python/PyTorch/Transformers/tokenizers/Hugging Face Hub/safetensors/NumPy/CUDA versions, and the extractor source hash. The model config hash comes from the historical pinned asset receipt and must be rehashed against the local file before E2 loads weights.

The tensor identity is `output.last_hidden_state[0, sequence_length - 1, :]`: the final transformer-block output at the final unpadded token, before the language-model head. There is no registered module hook. Inputs use the fast tokenizer with special tokens, no padding/truncation/chat template, batch size 1, and an all-ones attention mask. Output is a 2048-element little-endian float32 row. A head must declare this full ABI as its required representation identity.

No numeric performance gate is inherited from S01. E0 v04 froze the task floors, resource caps, timing procedure, readout batch sizes, and parity tolerance before E1. The E1 audit read label files only to verify split identity and support; it performed no feature extraction, fitting, or score calculation.

## Phases and authorization boundary

| Phase | Work | Current state |
|---|---|---|
| E0 — design and budget | Bind source history; define fresh-panel construction, task metrics, thresholds, model identity fields, and resource envelope. | Sealed as v04; root is recorded above. |
| E1 — freeze inputs | Build and seal the fresh panel, split, labels, support, and resource receipts without loading model weights. | Sealed as v04; independent audit passed. |
| E2 — feature cache | Load the pinned backbone and tokenizer once; extract only the predeclared surface; validate and seal the cache. | Requires a new explicit model-contact authorization. |
| E3 — fit and score | Fit the five fixed linear observers and score the sealed split; no view search or post-result threshold changes. | Requires the run contract and execution authorization. |
| E4 — integration and close | Verify bundle parity, seal outputs and resource receipts, then answer the question task by task. | Not started. |

Completing E0 or E1 does not authorize E2 or E3. A failure or repair gets a new versioned identity; preserve failed attempts and their receipts.

## Storage and stop rules

- **Storage estimate through E2:** cap the fresh input corpus at 2× the historical 205,585,547-byte corpus, the row manifest at 2× 368,110,353 bytes, the feature array at 2× 872,415,232 bytes to allow an atomic staging copy, and allow 512 MiB for labels, heads, predictions, receipts, and scratch. With the model artifact referenced read-only, the projected peak is `3,429,093,176` bytes (about 3.19 GiB). E1 v04 recorded D: free space before and after panel construction in its resource receipt. If the model must be copied, add `2,340,697,936` bytes plus any staging copy; recalculate before E2. If any cap is exceeded, stop and update the budget before feature extraction.
- Keep the shared cache, corpus, and run outputs on `D:` (the project `:G` target volume). At E1/E2 preflight, record current total/free bytes and model-cache location; require projected peak to fit while leaving at least 10% of target-volume capacity free. The design-day snapshot at 2026-09-25 22:25 UTC was `D:` free `769,932,251,136` bytes and `C:` free `353,649,098,752` bytes. E1 v04 ran a live preflight and postflight; those receipts supersede this older capacity observation.
- The model asset at the verified historical path may be referenced read-only after SHA-256 verification; never copy five model files for B2. Do not duplicate the common feature array for the five heads. Record RAM, VRAM, disk capacity, free bytes, and runtime versions.
- Stop before model contact if model/tokenizer revision, panel identity, split, resource estimate, or authority fields are unresolved.
- Stop and preserve the run if row identity, feature shape, cache hash, task support, or standalone/bundle parity fails. Do not repair in place or drop a failing task after looking at its score.
- A failed task-specific performance gate closes the “five-task bundle” claim for that version. Retain any successful task results as bounded results; do not promote the complete architecture pattern.
- This branch cannot establish a causal mechanism in LFM, broad generalization across model families or seeds, superiority to fine-tuning, or a scaling law. Those require separate designs and evidence.

## Questions this branch can retire

At close, record each question as `ANSWERED`, `FAILED`, `OPEN`, or `SUPERSEDED`, with its evidence root:

- Can one fixed cache serve all five separately fitted observers without task-specific feature extraction?
- Does the fresh panel reproduce useful performance for each task, including novel-term target transfer?
- How much work and storage does shared extraction actually save, and what is the readout-only serving cost?
- Do the separately trained observers preserve their outputs when assembled into one runtime bundle?
- Which task or resource limit, if any, prevents this from being a useful engineering pattern?

After v01 closes, routing integration is the immediate downstream option. Universal capability cartography follows as a separate phase. Pooling geometry, fly/shared-head work, scale fan-out, and multi-model comparison remain deferred and cannot be folded into this run.

“Frozen Capability Fabric” is a possible name for a passing, sealed engineering result, not the status or conclusion of this design draft.

## Revision history

- **v01, initial design:** one fixed frozen surface, five separate observers, fresh evaluation, with model identity, task gates, resource accounting, and B2 counterfactual unspecified.
- **v02, 2026-09-25:** pinned the historical 1.2B Base revision and V1 surface; specified closed-set term-ID tasks separately from lexical exact-target transfer; matched relation/state/target fit scope to S01; fixed 80/20 quartet split and task-specific floors; specified B1/B2/B3; added cache-write temporary space, tokenizer manifest, and parity rule. Clarified that shared extraction reduces repeated backbone work and task-cache storage, not five-head trainable state. Still design only; no freeze seal or execution authorization.
- **E0/E1 construction v01–v03:** preserved two E1 pre-output validator stops and one superseded E0 seal-membership defect as explicit receipts; none accessed model/tokenizer assets or wrote panel rows. Each correction received a new versioned identity.
- **E0 v04 / panel contract v03 / E1 v04, 2026-09-26 UTC:** froze the individual-versus-joint confidence statement, one-head versus five-head fanout costs, and the representation ABI; sealed a fresh 106,496-row panel and support receipt; all eight support endpoints passed with minimum 592 test rows/class. Independent root, row, split, label, and resource audit passed. The user later authorized only the bounded E2 model contact and extraction phase.
- **E1 v04 receipt erratum:** appended corrected quartet split counts from the sealed split manifest and label files. The panel, row assignments, support, and root are unchanged; the source-level receipt counter defect is documented for future builder versions.
- **E2 v01, 2026-09-26 UTC:** pinned model/tokenizer/runtime and extraction checks passed; one full cache and the 256-row byte-exact repeat completed; independent cache shape/finiteness and ordered row-identity checks passed. Device-wide sampled GPU use was above the E0 10-GiB ceiling while E2 overlapped another GPU workload, so the per-process resource gate remains unverified and E3 is closed. Preservation seal v01 had a canonical path-order defect; v02 corrected it. Resource correction v01 over-attributed aggregate usage to E2; attribution correction v02 records the concurrent FAS-S12 process. Current preservation seal v03 root: `0ff309d833cd87017f7384247e4420a508f582ad9f375c5637f586d73b703f4c`. No fitting or scoring was performed.
- **E0 v05 / E2 v02 draft update, 2026-09-26 UTC:** retains E0 v04, E1 v04, and E2 v01 unchanged. It narrows the GPU gate claim to the extractor-process PyTorch allocator, requires a clean pre-reset and post-reset allocator baseline, and prospectively binds exact cache SHA/length equality against E2 v01. This is a draft amendment only: it neither seals E0 v05 nor authorizes E2 v02.
- **Draft integrity receipts v06 → v08:** v06 and v07 are preserved interim draft snapshots. v08 is current: it aligns terminal receipt field names and records the required `total_gpu_memory_claimed=false` value as a machine-readable constraint. These receipts are not seals or authorizations.

## Program boundary after v01

After the observer-bundle engineering run closes, routing integration is the immediate downstream option. Universal capability cartography follows as a distinct phase. Geometry, fly/shared-head work, scale fan-out, and multi-model comparison stay separate and deferred. This run cannot establish a causal mechanism, broad model-family generalization, or a scaling law.

## Source records

- FAS-00 terminal disposition: [`FAS00-CLOSURE.md`](../fas-frozen-adaptive-substrate-v00/closure-v01/FAS00-CLOSURE.md)
- S01-3 protocol and frozen cache contract: [`S01-3-PROTOCOL.md`](../fas-s01-frozen-sensor-transfer-cartography/s01-3-linear-accessibility-v01/S01-3-PROTOCOL.md), [`linear-accessibility-contract-v01.json`](../fas-s01-frozen-sensor-transfer-cartography/s01-3-linear-accessibility-v01/contracts/linear-accessibility-contract-v01.json)
- Pinned FAS model/feature contract: [`FAS-00-PROTOCOL.md`](../fas-frozen-adaptive-substrate-v00/FAS-00-PROTOCOL.md), [`feature-contract-v01.json`](../fas-frozen-adaptive-substrate-v00/contracts/feature-contract-v01.json)
- S05–S11 synthesis and evidence limits: [`FAS-S05-S11-OBSERVER-GEOMETRY-SYNTHESIS-V01.md`](../fas-s05-s11-observer-geometry-synthesis-v01/FAS-S05-S11-OBSERVER-GEOMETRY-SYNTHESIS-V01.md)
- Cross-lab Day 6 starting snapshot: [`day-06-research-state-2026-09-25.md`](../../docs/day-06-research-state-2026-09-25.md)
