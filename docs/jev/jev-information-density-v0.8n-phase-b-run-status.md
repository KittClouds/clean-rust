# JEV v0.8N Road-B Phase B — Run Status and Available Data

**Report date:** 2026-09-23  
**Current status:** Original Phase B remains `EVALUATION_INPUT_CONTRACT_INCOMPLETE`; its training is sealed and it has no behavioral result. Post-registered E1 candidate-basis extraction and the target-free whole-schema join are now sealed PASS. The panel opening count remains 1. No head inference, predictions, metrics, or second opening are authorized.

## Current E1 disposition (post-registered; supersedes the earlier metadata-only status)

The E1 candidate basis was extracted under the separately authorized repair contract and pinned frozen LFM revision. The two clean-process extractions agreed exactly, and the target-free join resolves every held-out neighborhood by exact schema identity plus candidate semantic identity. This repairs the missing *evaluation input basis* for a separately authorized E1 evaluation; it does not retroactively complete or alter the original Phase-B result.

| Check | Actual result |
|---|---|
| E1 repair contract SHA-256 | `770d2e3a548e4e31e6a1e7af878f19db925f901666c5bceecd0c11454ee858e2` |
| Extraction authorization receipt SHA-256 | `e1b0c2894eaa9330cabdb500330570d6d0edad9bba7a3067d2df41b10f32552f` |
| Sealed 16-row text-manifest SHA-256 | `7987ae385454b32ddec548e48ef6543253b7b061ee1f077c064363c06304a285` |
| Frozen model | `LiquidAI/LFM2.5-1.2B-Base`, revision `7453bca97ca1e67754c4035a4b4c584e1c9dd725` |
| Extraction | 16 rows × 2,048 dimensions; FP32 output, BF16 frozen backbone; exact-length, single-row, batch 1, no padding, final-layer `mean_full@16` |
| Independent clean-process repeat | PASS; max absolute error `0.0` (contract limit `1e-5`); token records identical |
| Canonical tensor contents SHA-256 | `642f7bf4d83866beb1efaa0d92e16544636cdc19e8e1e75b4f1424dce8a50fb8` |
| Serialized tensor file SHA-256 | `58f38feb6af0e1c4f7b6d245b3c374aea3c8777fdbb78b3626c8ee7f13e5448a` |
| Target-free join | 2,000/2,000 neighborhoods; exactly 4 unique candidate features each; 0 missing, 0 duplicate, 0 extra joins |
| Join key | Exact `schema_family_id + candidate_semantic_id`; manifest row index is storage only, not a slot mapping |
| Join manifest SHA-256 | `5d9b851b61a305091a6489df6f7a3b09b02dd70c043d2554f17e9487f6544003` |
| Join receipt SHA-256 | `03022f1159d7b29d51a33f3e0638b7d8e111cce0ae3795dc81177b2ccc4db920` |
| Final E1 candidate-basis seal SHA-256 | `f3469f326200d1c097969be1d36741e2b01cc7542911ce79c5b240dc5b6c2b33` |

| Held-out schema | Neighborhoods | Candidate rows | Token lengths, manifest order |
|---|---:|---:|---|
| `exposure_control` | 500 | 4 (feature rows 0–3) | 14, 15, 13, 14 |
| `respiratory_monitoring` | 500 | 4 (feature rows 4–7) | 13, 14, 12, 14 |
| `salinity_control` | 500 | 4 (feature rows 8–11) | 12, 13, 15, 14 |
| `vibration_monitoring` | 500 | 4 (feature rows 12–15) | 13, 13, 14, 14 |

The row-level output is concrete and identity-bound (feature hashes below; semantic ID is the exact join key):

| Candidate semantic ID | Tokens | Feature-row SHA-256 |
|---|---:|---|
| `exposure_control::overexposure` | 14 | `01939291058b0a199c1e9515b8b8271fb354ea0e55a7365217cb9c2294d1c376` |
| `exposure_control::underexposure` | 15 | `f684030c1dfc7a531d4b84fae58ce4f78effc66a1e12600eefbce97f74258bb1` |
| `exposure_control::contrast_drift` | 13 | `609bc614b3b3f8f2200a4477ce2ae91da7f1b9d8d42ebe3510302cad4627dbab` |
| `exposure_control::sensor_bias` | 14 | `8030f7371e937dde0d027a5b599f6ee9e60683a4552aefa72e32dfa3bc408a6d` |
| `respiratory_monitoring::rapid_breathing` | 13 | `b6c986f3e04a7160265b5f5668a907858aded7a072ffe68df5c408f0a00f62ec` |
| `respiratory_monitoring::slow_breathing` | 14 | `8834d0a54b71df39ee945147b52f76f23ad74c5a2671ffb9962fac97e5ba1973` |
| `respiratory_monitoring::irregular_breathing` | 12 | `245e32c9c87518651c8dbd8c7e6bb53f53134e517e70c7099376ec811f7eac1e` |
| `respiratory_monitoring::sensor_bias` | 14 | `5c89875e698b32d3e268f08d7c9cfe6727246847843b198da6dc826b8b45ea3d` |
| `salinity_control::high_salinity` | 12 | `6e3b363d2e754c202730998e4a1c7f10442df6c6b2f7dcd16bf250e8f20074f2` |
| `salinity_control::low_salinity` | 13 | `95a812a80325b6071bc6e18213c1e53da1705eb92dc09b1d6d2e049a7d6a12ee` |
| `salinity_control::mineral_imbalance` | 15 | `92bee76797a4ac21c7b27ba92adeedc8fb61e75d474e79ce97c94873b7dbc4f1` |
| `salinity_control::sensor_bias` | 14 | `44d60dd042e502dbbcb47d78a01f88021a1cee5ea411f3527e839617adb42293` |
| `vibration_monitoring::excess_vibration` | 13 | `5f6847c5dabb760699701fe9a3f87e46127c61436889a9c48777d36c7ebf08f8` |
| `vibration_monitoring::low_vibration` | 13 | `dd77827eb625fe7183fec264579cccdb9846398ad6fab4925a381b36892a7a72` |
| `vibration_monitoring::resonance` | 14 | `d0b679b92e6dca65f19be2c867c534ede6f536925c62a2a2a633ca0ebf12bd77` |
| `vibration_monitoring::sensor_bias` | 14 | `a919a713502dc0c418218155b4950130dfb456e43fb1fa0f4665e27f6655abf5` |

The exact 16 input texts are listed in the metadata audit section below. Row-level semantic IDs, token IDs and token hashes, input-text hashes, feature-row hashes, and model/extractor identities are bound in the feature receipt. The full 2,000-row exact-identity join is included as data in the E1 output bundle.

The join implementation had one preserved, non-scientific first-attempt failure: it looked for a receipt field named `output_row`, while the authoritative feature receipt names the storage index `candidate_vector_index`. The attempt failed before writing a join manifest. The sidecar was corrected to use the receipt's actual storage-index field, then the full target-free join passed. The failed-attempt record remains preserved; no candidate mapping was inferred from row position.

```text
ORIGINAL PHASE B             EVALUATION_INPUT_CONTRACT_INCOMPLETE
TRAINING                     9/9 runs and 27/27 checkpoints valid and sealed
ORIGINAL PANEL OPENING       1; unchanged
E1 CANDIDATE BASIS           16/16 extracted; repeat parity PASS
E1 TARGET-FREE JOIN          2000/2000 exact; 0 missing/duplicate/extra
SECOND PANEL OPENING         NOT AUTHORIZED
HEAD LOADING / INFERENCE     NOT AUTHORIZED / NOT PERFORMED
PREDICTIONS / METRICS        NONE
NEWTIGHT / LEGACY / PHOENIX  NO ACCESS
```

Machine-readable artifacts: [final E1 seal](</D:/codex-runs/jev-information-density-v08n-e1/v0.8N-E1-heldout-candidate-basis-v01/e1-candidate-basis-seal-v01.json>), [feature receipt](</D:/codex-runs/jev-information-density-v08n-e1/v0.8N-E1-heldout-candidate-basis-v01/feature-cache/heldout-candidate-feature-receipt.json>), [repeat-parity receipt](</D:/codex-runs/jev-information-density-v08n-e1/v0.8N-E1-heldout-candidate-basis-v01/feature-cache/repeat-parity-receipt.json>), [target-free join receipt](</D:/codex-runs/jev-information-density-v08n-e1/v0.8N-E1-heldout-candidate-basis-v01/target-free-schema-candidate-join-receipt-v01.json>), and [2,000-row join manifest](</D:/codex-runs/jev-information-density-v08n-e1/v0.8N-E1-heldout-candidate-basis-v01/target-free-schema-candidate-join-v01.jsonl>).

## Executive summary

The authorized three-arm experiment completed all nine training runs. Each arm/seed run executed 3 epochs and 120 optimizer steps, producing 27 verified checkpoints. The training seal and implementation-correction chain pass independent verification.

The frozen evaluator opened the authorized held-out panel and loaded its evaluation scope, manifests, and frozen feature tensor. It stopped while resolving the candidate order for `salinity_control`, before importing the head implementation or loading a checkpoint. The user then authorized one outcome-blind whole-schema preflight and continuation **only if** every candidate-feature binding was uniquely reconstructible under the existing unlock. The preflight found no binding for any of the four held-out schemas, so no adapter was created and no continuation occurred.

```text
RuntimeError: held-out schema has no training candidate-order binding: salinity_control
```

The exception occurred before the evaluator imported the head implementation, loaded any terminal head checkpoint, or produced a prediction. No evaluation output directory, prediction, or metric file was created. The original opening remains `opening_count = 1`; the conditional continuation authorization did not permit a second unlock, and none was created. The initial report and traceback were preserved as failed-attempt provenance before this report was updated.

Accordingly, this is not a positive, negative, or null treatment result. The primary SHAM-versus-MATCHED estimand, the per-seed strict-transition floor (`0.37`), and all held-out metrics remain unevaluated. Training losses below are optimization telemetry only and must not be interpreted as held-out capability or treatment efficacy.

## Frozen experiment and execution

| Item | Executed specification |
|---|---|
| Arms | B-DUP, B-MATCHED, B-SHAM |
| Seeds | 20260927, 20260928, 20260929 |
| Runs / checkpoints | 9 runs / 27 epoch checkpoints |
| Backbone | `LiquidAI/LFM2.5-1.2B-Base`, revision `7453bca97ca1e67754c4035a4b4c584e1c9dd725`, frozen |
| Head | Dynamic MLP compatibility head, width 128, 590,081 trainable parameters |
| Optimizer | AdamW, learning rate 0.002, weight decay 0.01 |
| Budget | 3 epochs; 40 steps/epoch; 120 steps/run; no scheduler or clipping |
| Training events | 10,000 primary + 5,000 auxiliary per epoch; 45,000 event exposures/run over 3 epochs |
| Runtime | NVIDIA GeForce RTX 3080; CUDA locator `cuda:0` |
| Summed run time | 828.31 seconds across nine runs (about 13 min 48 sec; excludes setup and evaluation attempt) |

The scheduled run order completed exactly as frozen:

```text
20260927: B-DUP → B-MATCHED → B-SHAM
20260928: B-SHAM → B-DUP → B-MATCHED
20260929: B-MATCHED → B-SHAM → B-DUP
```

Paired initial-head identity, 120 optimizer steps per run, 3 checkpoints per run, finite training telemetry, and the recorded no-evaluation/no-Phoenix run flags were independently checked. The frozen trainer source remained unchanged from the authorization binding.

## Actual training telemetry

`Train loss` is the logged event-weighted training objective (categorical cross-entropy plus the frozen 0.25 Brier term). `Brier` is the raw Brier component reconstructed from step telemetry by weighting each step’s logged component by its primary-plus-auxiliary event count. Values are descriptive training diagnostics, not evaluation metrics.

### Mean across the three seeds, by epoch

| Epoch | B-DUP loss | B-DUP Brier | B-MATCHED loss | B-MATCHED Brier | B-SHAM loss | B-SHAM Brier |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1.948505 | 0.172901 | 1.937541 | 0.167541 | 1.889916 | 0.153342 |
| 2 | 1.379154 | 0.064564 | 1.381647 | 0.065020 | 1.376180 | 0.063300 |
| 3 | 1.360936 | 0.055857 | 1.347060 | 0.049005 | 1.356649 | 0.053758 |

### Terminal epoch-3 values by seed

Each cell is `training loss / raw Brier component`.

| Seed | B-DUP | B-MATCHED | B-SHAM |
|---:|---:|---:|---:|
| 20260927 | 1.370119 / 0.060556 | 1.349036 / 0.049962 | 1.369165 / 0.060044 |
| 20260928 | 1.364635 / 0.057784 | 1.369421 / 0.060145 | 1.370424 / 0.060652 |
| 20260929 | 1.348054 / 0.049230 | 1.322724 / 0.036908 | 1.330359 / 0.040579 |

All nine runs show decreasing training loss from epoch 1 to epoch 3. This establishes successful optimization under the frozen recipe; it does **not** establish that any arm performs better on the held-out task.

## Held-out opening and failure record

The sealed panel identity was `v0.8N-eval-panel-v01/matched-panel-v02`, with 2,000 neighborhoods balanced across four families (500 each). The authorized evaluator validated and read the 22,000-row held-out feature scope, 2,000 neighborhood records, 2,000 selected-panel records, and the frozen feature tensor of shape `22,000 × 2,048` before failing at the schema-to-candidate-order join for `salinity_control`.

The execution trace places this failure before head loading and prediction generation. Post-failure checks found:

- one panel-unlock receipt, `opening_count: 1`;
- no `evaluation/` output directory;
- no predictions or geometry/surface diagnostic output;
- no evaluation analysis report;
- no NewTight or legacy-evaluation access;
- no Phoenix access.

The frozen evaluator itself was not edited. Its runtime attempted to pass the human-readable device name to PyTorch, so a separate, hash-recorded adapter verified the live RTX 3080 identity and mapped only the in-memory device locator to `cuda:0`. The adapter’s non-panel preflight passed. The later schema join remains unresolved; this report does not authorize a retry or a second panel opening.

## Integrity and provenance

| Artifact | SHA-256 |
|---|---|
| Phase-B authorization event | `0cad8d2e45fe8e7e5eed7f9bcdeab406926f24605ad9f62396d83f9512bb0a09` |
| Run contract | `da538aa03355732a2ba362da45d947e169b87aa644d0efd6ba7ef7a546306c1f` |
| Analysis contract | `0072c44903ea253cd8ad288cda8c100270f19d909ddced098af32d388ac29e1f` |
| Execution-input contract | `efb2bbe59293d7899083927cc187a292b5dfd1dc2948a0b752b3d9cbae2fd18d` |
| Candidate tensor contents (`48 × 2,048`, float32) | `f76e573779152fd3966845a39e29206c333eef388e0511c5f3e07f8f1b46d593` |
| Superseding training-seal manifest | `43932fc963b150167972e81b1c1bb93f6989e9b93faa65ab1eee3ecf55c7b727` |
| Corrected checkpoint hash tree | `add6dfd013c936b100e7cbdb205018bf91b95e91ed11ca854b26aed998c66923` |
| Seal metadata correction receipt | `52d70193fc9236491b86da9825a8589f5eb513283f4c44a40d6354989ad4a93b` |
| Held-out panel seal | `425cef320df94e2b47b448203f8a916ebcbb2019539b2d09e51f5b4ced92f614` |
| Held-out panel manifest | `80e09c0f203b8a6505e062a2091a594273dca808258ff2f4539ab8414db9eabe` |
| Panel unlock receipt | `e8ff5e4548ab5e0b2b96433d844c64836aa03ff878034381c1933db913cb3ec0` |
| Frozen evaluator source | `fa22bc8febff89d2b635091c6cb40be6f3beba4549c4a135d16e213f6fd3dda4` |
| Runtime alias adapter | `3ff0f993c80a09923fe589964932e57496c5e574cd43ab1bdb7c94116922eb43` |
| Runtime alias correction receipt | `cbd4e209ce3a174fc46d61150c5b795c7bc2e0af05c22d4eb2eec75e695acefe` |

The original defective training-seal manifest and tree were retained byte-for-byte as superseded artifacts. The corrected tree retains all 77 original unique training entries and adds four correction-provenance entries. The original training-seal verifier, correction-chain verifier, and the new metadata-correction verifier all passed after this supersession. Five frozen metric smoke tests passed before the held-out panel was opened.

## Current scientific disposition

```text
TRAINING                    COMPLETE; 9/9 runs, 27/27 checkpoints
TRAINING SEAL               INDEPENDENTLY VALIDATED
HELD-OUT PANEL              UNLOCKED/READ ONCE
HEAD INFERENCE              NOT STARTED
PRIMARY METRICS             NOT PRODUCED
STRICT-TRANSITION FLOOR     NOT EVALUATED
NEW TIGHT / LEGACY / PHOENIX NO ACCESS
PHASE-B SCIENTIFIC RESULT   INCOMPLETE; no treatment conclusion
```

The authorized, outcome-blind schema-join correction attempt ended in a fail-closed disposition because exact candidate-feature bindings do not exist in the sealed training catalog for the held-out candidate identities. No treatment interpretation should be drawn from training-loss differences. This report does not authorize another panel opening, new candidate features, a crosswalk, inference, or any change to the evaluation contract.

## Outcome-blind schema-join correction disposition

The correction authorization was limited to reconstructing a uniquely supported schema-to-candidate-order binding from sealed metadata. The frozen evaluator and scientific contracts were not edited. A read-only preflight checked all 2,000 held-out neighborhood identities before any head load. It found that the issue was not an isolated missing dictionary key:

| Held-out schema identity | Neighborhoods | Exact training-order binding before correction | Matching candidate rows in the sealed 48-row catalog | Binding after preflight |
|---|---:|---|---:|---|
| `jev-v08n-schema:exposure_control` | 500 | None | 0 | None; unresolved |
| `jev-v08n-schema:respiratory_monitoring` | 500 | None | 0 | None; unresolved |
| `jev-v08n-schema:salinity_control` | 500 | None; initial exception | 0 | None; unresolved |
| `jev-v08n-schema:vibration_monitoring` | 500 | None | 0 | None; unresolved |

The run-contract-bound common primary occurrence stream contains 10,000 rows and 12 exact candidate-order namespaces: `chemical_concentration`, `dosage_safety`, `flow_management`, `humidity_control`, `inventory_control`, `liquid_level`, `load_management`, `power_quality`, `pressure_control`, `rotational_speed`, `thermal_control`, and `torque_control`. The sealed candidate catalog contains 48 candidate feature rows (four per namespace), each 2,048-dimensional, and exactly those same 12 namespaces. None of the held-out namespaces appears in either source.

The authoritative generator definitions do establish the held-out semantic candidate identities and their order, for example `salinity_control::{high_salinity, low_salinity, mineral_imbalance, sensor_bias}` and `exposure_control::{overexposure, underexposure, contrast_drift, sensor_bias}`. But those identities have no corresponding rows in the 48-entry candidate feature tensor. The identities therefore do not establish which trained candidate-feature vectors the head should receive. A slot-based or semantic-role crosswalk would be an unsealed assumption and would change the head inputs; it was not invented.

| Correction/provenance item | Value |
|---|---|
| Original frozen evaluator SHA-256 | `fa22bc8febff89d2b635091c6cb40be6f3beba4549c4a135d16e213f6fd3dda4` |
| Schema-join correction source SHA-256 | **Not created**; unique feature binding failed closed |
| Metadata preflight source SHA-256 | `8a8747d8a442f5e789ae28c2a026c7fd36ded61965efa6d86ce9918c354a7e20` |
| Correction disposition receipt SHA-256 | `1db0042f1a15364e6a304daf426a56c561ca44986c632b6453f960bcf4e6d41f` |
| Preserved failed-attempt/traceback receipt SHA-256 | `c2f430c43ed02bc77dee84bff0566ad66888e73070d76d3b07847cb4d361a19e` |
| Existing unlock receipt SHA-256 / count | `e8ff5e4548ab5e0b2b96433d844c64836aa03ff878034381c1933db913cb3ec0` / `1` |

The preflight ran at `2026-09-23 10:34:42 UTC`. At that time the evaluation output directory was absent, no predictions or metrics existed, and no head had been loaded. The original traceback was recovered from the recorded evaluator execution, copied into the immutable failed-attempt record, and retained with the pre-correction report under `D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\phase-b-run-v01\failed-attempts\`. The unchanged metric smoke tests passed `5/5`; that does not overcome the unresolved input binding. No second unlock was issued.

The machine-readable disposition is [phase-b-evaluator-schema-join-correction-v01.json](</C:/code land/clean-rust/experiments/jev-information-density-v08n/phase_b/phase-b-evaluator-schema-join-correction-v01.json>), the metadata-only whole-schema preflight is [preflight_evaluator_schema_join_v01.py](</C:/code land/clean-rust/experiments/jev-information-density-v08n/phase_b/preflight_evaluator_schema_join_v01.py>), and the preserved failure record is [evaluator-failed-attempt-v01.json](</C:/code land/clean-rust/experiments/jev-information-density-v08n/phase_b/evaluator-failed-attempt-v01.json>).

## Final disposition and post-registered E1 basis audit

The original v0.8N Phase B is now sealed as **`EVALUATION_INPUT_CONTRACT_INCOMPLETE`**. This is not a treatment failure or a null result. The nine runs and 27 checkpoints remain valid and sealed; the intended held-out candidate semantic basis was missing, so no head inference, prediction, metric, or `0.37` sensitivity-floor evaluation exists. The original panel opening remains count 1. The final machine-readable disposition is [phase-b-final-disposition-v01.json](</C:/code land/clean-rust/experiments/jev-information-density-v08n/phase_b/phase-b-final-disposition-v01.json>) (SHA-256 `bae6d7ac88f5ca0c5684c219e0e0b82f03962bf6f0292c205cba58765c75a656`).

### What the 48 training candidate vectors are—and are not

The sealed training catalog contains 48 candidate vectors (12 training schema namespaces × 4 candidates), each 2,048-dimensional. They are not opaque schema-slot embeddings: the original run contract binds candidate representation to the `name_definition` surface (`name — description`) and the generic frozen `encode_lfm_texts` function. That function accepts a text list and contains no schema/candidate lookup. Therefore a held-out semantic candidate can be represented directly from its authoritative text under the same frozen encoder; there is no need—and no authority—to map it to one of the 48 training candidates by slot.

### E1 metadata-only result (historical pre-extraction snapshot; superseded by current status above)

A separate identity, **v0.8N-E1: Held-Out Candidate Semantic Basis Recovery**, is post-registered. Its metadata audit passed. The source is the authoritative held-out `FamilySpec` candidate identity/order and the frozen surface serializer; all 16 semantic IDs and input-text hashes are unique, none overlaps the training catalog, and each held-out schema namespace has four exact candidate IDs and 500 neighborhoods. The pinned tokenizer was loaded for length checking only; the longest candidate is 15 tokens versus the frozen 1,024-token limit. No LFM backbone weights were loaded and no candidate feature vectors were created.

| Schema | Candidate semantic ID | Exact model-input text | Tokens |
|---|---|---|---:|
| `exposure_control` | `exposure_control::overexposure` | `Overexposure — The exposure level exceeds the target range.` | 14 |
| `exposure_control` | `exposure_control::underexposure` | `Underexposure — The exposure level falls below the target range.` | 15 |
| `exposure_control` | `exposure_control::contrast_drift` | `Contrast drift — Image contrast differs from the expected profile.` | 13 |
| `exposure_control` | `exposure_control::sensor_bias` | `Sensor bias — The exposure measurement channel has a persistent offset.` | 14 |
| `respiratory_monitoring` | `respiratory_monitoring::rapid_breathing` | `Rapid breathing — The breathing rate exceeds the expected range.` | 13 |
| `respiratory_monitoring` | `respiratory_monitoring::slow_breathing` | `Slow breathing — The breathing rate falls below the expected range.` | 14 |
| `respiratory_monitoring` | `respiratory_monitoring::irregular_breathing` | `Irregular breathing — Breaths occur with inconsistent timing.` | 12 |
| `respiratory_monitoring` | `respiratory_monitoring::sensor_bias` | `Sensor bias — The breathing-rate channel has a persistent offset.` | 14 |
| `salinity_control` | `salinity_control::high_salinity` | `High salinity — The salinity exceeds the expected operating range.` | 12 |
| `salinity_control` | `salinity_control::low_salinity` | `Low salinity — The salinity falls below the expected operating range.` | 13 |
| `salinity_control` | `salinity_control::mineral_imbalance` | `Mineral imbalance — The mineral mixture differs from its expected profile.` | 15 |
| `salinity_control` | `salinity_control::sensor_bias` | `Sensor bias — The salinity measurement channel has a persistent offset.` | 14 |
| `vibration_monitoring` | `vibration_monitoring::excess_vibration` | `Excess vibration — The vibration amplitude exceeds the expected range.` | 13 |
| `vibration_monitoring` | `vibration_monitoring::low_vibration` | `Low vibration — The vibration amplitude falls below the expected range.` | 13 |
| `vibration_monitoring` | `vibration_monitoring::resonance` | `Resonance — The platform has a frequency-specific oscillation.` | 14 |
| `vibration_monitoring` | `vibration_monitoring::sensor_bias` | `Sensor bias — The vibration measurement channel has a persistent offset.` | 14 |

Candidate feature identity is joined by exact `candidate_semantic_id` plus schema identity. Manifest row index is storage order only; it is not a candidate-slot crosswalk.

The prospective extraction recipe is sealed to the existing frozen model revision `7453bca97ca1e67754c4035a4b4c584e1c9dd725`, `mean_full@16`, exact-length single-row extraction, no padding, batch size 1, frozen BF16 backbone, and FP32 output of shape `16 × 2,048`. A second clean-process extraction must agree within the existing `1e-5` maximum-absolute-error determinism tolerance. The future extraction output has a separate E1 path; it cannot overwrite or be confused with the existing 48-row training candidate tensor.

At the time of this metadata-only snapshot, this established **metadata-level constructibility**, not a repaired behavioral result. The separately authorized extraction and target-free join have since passed; see the current E1 disposition at the top of this report. A second opening of the held-out panel, loading any head, and inference remain unauthorized. Any eventual metrics must be labeled a **post-registered E1 repaired held-out evaluation of the sealed checkpoints**, not the preregistered original Phase-B result. NewTight, legacy evaluation, and Phoenix remain out of scope.

| E1 artifact | SHA-256 | Status |
|---|---|---|
| Candidate text manifest, 16 rows | `7987ae385454b32ddec548e48ef6543253b7b061ee1f077c064363c06304a285` | Sealed; texts only |
| Metadata audit | `f91b27f60905280d86cbf302520945c59619a501ae749b6ecfeee75d5c5ed752` | Pass; no feature vectors |
| E1 repair contract | `770d2e3a548e4e31e6a1e7af878f19db925f901666c5bceecd0c11454ee858e2` | At this historical snapshot: recipe sealed; extraction not yet authorized |
| E1 seal receipt | `eea9467fb47e117a86b65c41b4c86758f1eece908729562b71befe6f5d0fa8a7` | Binds the above artifacts and preserves the pre-extraction no-authorization snapshot |

Machine-readable E1 artifacts: [repair contract](</C:/code land/clean-rust/experiments/jev-information-density-v08n/phase_b/e1/e1-repair-contract-v01.json>), [metadata audit](</C:/code land/clean-rust/experiments/jev-information-density-v08n/phase_b/e1/e1-candidate-basis-metadata-audit-v01.json>), and [candidate text manifest](</C:/code land/clean-rust/experiments/jev-information-density-v08n/phase_b/e1/e1-candidate-text-manifest-v01.jsonl>). The separate [seal receipt](</C:/code land/clean-rust/experiments/jev-information-density-v08n/phase_b/e1/e1-repair-seal-receipt-v01.json>) binds the contract and source hashes.

```text
ORIGINAL PHASE B             EVALUATION_INPUT_CONTRACT_INCOMPLETE
TRAINING                     9/9 runs and 27/27 checkpoints sealed
ORIGINAL HELD-OUT OPENING    1; no predictions or metrics
E1 METADATA BASIS            PASS; 16 candidate texts; extraction had not yet been authorized at this snapshot
E1 REPAIR RECIPE             SEALED; post-registered, not retroactive
CANDIDATE EXTRACTION         NOT AUTHORIZED
SECOND PANEL OPENING         NOT AUTHORIZED; opening count was 1
HEAD INFERENCE               NOT AUTHORIZED
NEWTIGHT / LEGACY / PHOENIX  NO ACCESS
```
