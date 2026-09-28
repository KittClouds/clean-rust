# E4-0 Implementation Source Map v02

Status: planning artifact; no E4 population rows, features, predictions, or scores were produced by this map. Supersedes v01 to bind the row/quartet collision correction and clarify the held-out prediction firewall.

This map turns the E4-0 draft into four independent, versioned implementation units. It is subordinate to the pinned E4 codebase map and the machine-readable contract draft. It does not authorize population construction, tokenizer/model contact, label opening, scoring, or downstream E4 work.

## Bound planning inputs

| Artifact | SHA-256 | Role |
| --- | --- | --- |
| `E4-CODEBASE-MAP-v01.md` | `9f3f8c048d48ccc7084189bd41a5b62ee4d1847c5146d9f77605ccc211321f0e` | Pinned source/codebase orientation; remains immutable. |
| `E4-0-CONTRACT-DRAFT-v03.json` | `3c55e5778d3dd104c60a57286563d67d6a3906d2e2f7d217de39f409229e5bb4` | Current machine-readable design and resource arithmetic; draft only. |
| `E4-0-SYMBOLIC-SUPPORT-PLAN-v10.json` | `808e6c167f877a9cbb926c4c989bc06dc74136d94fb9f3c02693ab99c72e3dfb` | Model-free support plan with E1 quartet-ID, row-ID, and rendered-input collision checks. |
| `E4-0-IMPLEMENTATION-SOURCE-MAP-v01.md` | `bb8ad64e0a33e2394e5a9746a48dc45458ec51693390a80ae4296a51a3543c37` | Preserved predecessor map; v02 corrects the omissions noted below. |
| E4-0 design v03 | `ce7ba083f359eb252a04e3c3971edf8251995dfe41d43f21a499c50727f5b42b` | Scientific scope, strata, thresholds, truth boundary. |

All paths below are relative to `experiments/fas-frozen-observer-bundle-engineering-v01/` unless stated otherwise.

## Existing immutable reference implementations

| Existing source | SHA-256 | Reuse boundary |
| --- | --- | --- |
| `source/panel-generator-v04/src/generate.rs` | `fa2bd0617135a0dce4e12f0e0967f82e461133b394a7d969daba5afb11e2cce1` | Reference for E1 semantic schedule, four A/C/E/P variants, term inventory, and rendered row meaning. Do not edit or invoke its E1 materializer as the E4 writer. |
| `source/panel-generator-v04/src/main.rs` | `7ce62779ddf8dd994ad9ace6a10dd5bda76de3bd87c1c0e19459cf38b428ec0f` | Reference for E1 schemas, support receipt, atomic file-writing, and seal conventions. E4 must have its own versioned CLI and output identity. |
| `contracts/representation-abi-v07.json` | `3b36b066111872290b9f37a877b9043650867fa81658476c783a5c7e7485d319` | Frozen model, tokenizer, runtime, tensor identity, device, dtype, and extraction semantics. |
| `source/scripts/extract_features_v07.py` | `2b210d4f65c37d823b7060278c8a29db3a5c5f7fb535e6bb28d5147bc56b7b24` | Reference for pinned runtime verification, ABI checks, CUDA allocator accounting, cache layout, and E2 cache integrity. E2 source/cache stay immutable. |
| `source/scripts/score_e3_v02.py` | `8075335328e6ad81b8df227fd117d8ab1d871cd70b033c362289ac901f6f2e85` | Reference for five frozen heads, eight endpoints, BA, whole-quartet stratified bootstrap, seed mechanics, and prediction serialization. E3 score remains immutable. |
| `source/scripts/audit_e3_score_v02.py` | `813c6b009799a65dfddceac6730bba28d95b89cae2cd9d5395052b41297e49ac` | Reference for independent reconstruction from sealed predictions and bootstrap inputs. The E4 auditor must not import E4 scorer disposition code. |
| `source/scripts/fit_observers_e3_v02.py` | `9871d81638c9000ed912d395f3a7ba566301d09dda4fb74ba52ba979ba46487c` | Reference for the frozen head file schema only. No fitting is part of E4-0. |

## Four E4-0 source units to implement and bind

| Contract component | Proposed source path | Required behavior and tests | Must not do |
| --- | --- | --- | --- |
| `e4_population_generator` | `source/e4-population-v01/` | Read and hash-check only the sealed E1 semantic inputs; preserve ID-to-term tables. Implement the frozen namespace/seed/counter/ordinal byte encodings; shared-counter, paired-surface collision rejection over all eight rendered inputs; reject the full candidate if its quartet ID, any row ID, or any exact rendered-input hash collides with E1 or prior E4 rows; deterministic candidate permutation; required seen/lexical/held-out/joint labels and support receipts; atomic bounded output with file-size ceilings. Unit/property tests use synthetic fixtures for byte identity, all three collision classes, retry exhaustion, support-prefix agreement, row ordering, and reproducibility. | No tokenizer/model import; no held-out truth display; no invocation on sealed E1 to write E4 rows until separately authorized. No edits to E1 generator. |
| `e4_online_feature_and_parity_runner` | `source/scripts/e4_online_parity_v01.py` | Implement two disjoint operations. First, the label-free E1 FIT parity operation recomputes only the hash-selected 256-quartet panel and compares feature bytes and all five predictions with E2 cache/E3 heads. Second, after the population seal, extract and seal the E4 feature cache for primary plus held-out-template rows under the same ABI; emit no E4 predictions or class-support summaries. Load the pinned stack only when the separately authorized entry point is called. Write resource, row-identity, parity, and preservation receipts. | No evaluation labels or E4 predictions before scorer authorization; no template/joint support or scores; no other device/batch surface, head fitting, or E2 cache mutation. Source tests must not initialize CUDA or contact the model hub. |
| `e4_fresh_scorer` | `source/scripts/score_e4_0_v01.py` | After the fresh population/parity predecessor seals pass, open only the registered seen-rendering and lexical terminal labels once; score the frozen five heads on exactly eight endpoints. Keep BA, whole-quartet class-stratified bootstrap, 10,000 replicates, PCG64 seed `2026092604`, and linear quantile; use `alpha=0.00625` and gate each lower bound at `0.90`. Emit predictions, metrics, support, bootstrap outputs, and a non-aggregating all-eight disposition. | No refit, tuning, endpoint dropping, template/joint truth opening, analysis of held-out-template labels, or E4-A. |
| `e4_independent_auditor` | `source/scripts/audit_e4_0_v01.py` | Independently hash/replay sealed inputs and reconstruct row identity, class support, predictions, BA, bootstrap lower bounds, endpoint ordering, and all-eight disposition from source artifacts. Implement the analysis path separately from the scorer; compare reproduced bytes/values under frozen exactness/tolerance rules and issue a replay receipt. Tests must use synthetic sealed fixtures, including pass, single-endpoint fail, support fail, and tamper cases. | No importing scorer's final disposition or helper that decides pass/fail; no access to template/joint truth; no model contact or mutation of sealed artifacts. |

## Required source-identity receipt before sealing

The next contract version can replace the four pending fields only after each implementation exists, has a stable path, exact byte length, SHA-256, and a passing source-level test receipt. Bind transitive local imports/configuration and lockfiles that can change behavior, not only the top-level entry point. The independent auditor source must be independently hashed and must not consume scorer code as a library.

Pre-seal tests are implementation checks on synthetic data and sealed public metadata. They must not generate the E4 population, load a tokenizer/model, initialize CUDA, open fresh terminal labels, or produce performance outcomes. The production entry points remain inert without a separately bound authorization receipt.

## Execution ordering after source freeze

1. Independent audit the completed source hashes and draft contract.
2. Seal the E4-0 contract only after that audit passes.
3. Obtain a distinct authorization for fresh population materialization and its support/freshness seal.
4. Only after the population seal and parity-panel seal pass, obtain authorization for online extractor/model contact.
5. Keep fresh scoring separately closed until parity and all required preconditions pass; open the registered terminal labels once under its scoring authorization.
6. Run the independent auditor after scoring; E4-A remains a separate later decision.

The contract and authorization flags, not source-code availability, control these transitions.

## v02 correction record

The v01 symbolic support source checked rendered-input hashes but did not enforce the contract's E1 quartet-ID and row-ID disjointness. Support planner v10 adds both checks against the sealed E1 row manifest and against accepted E4 items; the selected prefix and support counts remain unchanged. This is a planning-receipt correction, not a population attempt or scientific result.

The online runner also keeps the E1 FIT parity output separate from fresh E4 feature extraction. Predictions and class-support summaries for held-out-template and joint strata remain forbidden until the companion contract allows them.
