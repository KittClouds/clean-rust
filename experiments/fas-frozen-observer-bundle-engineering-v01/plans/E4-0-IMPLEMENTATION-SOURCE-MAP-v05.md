# E4-0 Implementation Source Map v05

Status: final implementation closure for E4-0 v06, superseding the immutable v05 packet. Scientific inputs and registered gates remain pinned to the v05 draft. This map binds the v06 source/build closure, source-test receipts, and independent auditor code; it does not grant execution authority.

## Immutable protocol baseline

- The immutable v05 draft identity and exact bytes are recorded once in the bound frozen-input table below.
- The superseded v05 final contract and seal are direct v06 seal lineage members and are not duplicated in source-map tables.
- Scientific, population, representation, parity, truth-access, resource, and scoring gates must match this baseline exactly. Only source-binding/status/receipt metadata may be serialized into the final contract.
- Fresh population: 18,667 whole quartets, 74,668 primary rows, 74,668 held-out-template rows, 149,336 unique feature rows; minimum selected support 252, immediately preceding prefix 248.
- Held-out template/joint truth remains escrowed; E4-0 scores only the eight registered primary endpoints.

## Bound frozen inputs

| Input Path | Bytes | SHA-256 | Role |
| --- | ---: | --- | --- |
| `experiments/fas-frozen-observer-bundle-engineering-v01/plans/E4-CODEBASE-MAP-v01.md` | 10008 | `9f3f8c048d48ccc7084189bd41a5b62ee4d1847c5146d9f77605ccc211321f0e` | Pinned E4 codebase orientation. |
| `experiments/fas-frozen-observer-bundle-engineering-v01/plans/E4-0-CONTRACT-DRAFT-v05.json` | 24469 | `e2910965b53313a34c3a7d870075d83dbc9e035a230fc68f3c177c12c71e9fcf` | Immutable scientific/protocol baseline; all gates compared against this file. |
| `experiments/fas-frozen-observer-bundle-engineering-v01/plans/E4-0-PRECONDITIONS-DESIGN-v03.md` | 12665 | `ce7ba083f359eb252a04e3c3971edf8251995dfe41d43f21a499c50727f5b42b` | Resolved E4-0 scientific design. |
| `experiments/fas-frozen-observer-bundle-engineering-v01/plans/E4-0-HELDOUT-TEMPLATES-v02.json` | 6716 | `e3b8a70b90b06fc4185d2e379cbfc7cf3724238d9505590add1cf8bba2e9b068` | Frozen held-out template bytes. |
| `experiments/fas-frozen-observer-bundle-engineering-v01/plans/E4-0-HELDOUT-TEMPLATES-v02-audit.json` | 1690 | `c5a6eb4412652122a5cfd126e50fc5c907d9fd9f94bd101d4549be2796535f87` | Exact/normalized template exclusion audit. |
| `experiments/fas-frozen-observer-bundle-engineering-v01/plans/E4-0-TEMPLATE-STRUCTURAL-AUDIT-v01.md` | 3718 | `aeca3020f0cbcb779ddb7dac7aea1b9b9f6f4db0fa1abb8221740e2ff188b9ff` | Descriptive structural novelty audit. |
| `experiments/fas-frozen-observer-bundle-engineering-v01/plans/E4-0-SYMBOLIC-SUPPORT-PLAN-v11.json` | 7785 | `a15bca5d78867ea32905299fabd21f85cf6846a5a02a0c55dd32337e0396847f` | Frozen 18,667-quartet support/collision plan. |
| `experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-support-plan-v11-source-tests.json` | 1889 | `833c011ff9a9770756f106f390a275949751b9b71d46dbb4efa92f806a82b0c6` | Support planner source/replay validation. |
| `experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-stage-authorization-schema-v01.json` | 3020 | `73a7cb5e4bb23463bc73e0591f903644c46ad17129f1bc3c1b1f58bccb87aed3` | Normative staged authorization schema. |
| `experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-artifact-seal-schema-v01.json` | 2267 | `8a43f3a945fefbf983b734f51b98093a4538e2ebceef6199f543cbd86b5ef6f9` | Normative artifact seal schema. |
| `experiments/fas-frozen-observer-bundle-engineering-v01/contracts/representation-abi-v07.json` | 3613 | `3b36b066111872290b9f37a877b9043650867fa81658476c783a5c7e7485d319` | Frozen model/representation ABI. |
| `experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e0-freeze-v10-sealed-v01.json` | 35176 | `a47c66391d9f691ed182ab327c6fd6d68a6ed18c5c08ac6250a46c5dde2556f3` | Frozen E0 v10 predecessor contract. |
| `experiments/fas-frozen-observer-bundle-engineering-v01/seals/e0-seal-v10.json` | 27253 | `f5138b5b90ea187c226521da2c8eaf8d60bb133b5c66ed54c8a822edf565197d` | Frozen E0 v10 seal manifest. |
| `experiments/fas-frozen-observer-bundle-engineering-v01/audits/e0-v10-independent-audit-v01.json` | 2383 | `e5462e6374a0e547965bec802183e42fb8b16d3518d65ed06eac2e343a5b178b` | Independent E0 v10 audit. |
| `experiments/fas-frozen-observer-bundle-engineering-v01/audits/e1-independent-audit-v04.json` | 1068 | `4bdb261a2c1c553377b6064ee6662ffb257a4e7e70dba97bf9d13d685d93dbf1` | Independent E1 v04 population audit. |
| `experiments/fas-frozen-observer-bundle-engineering-v01/seals/e3-score-v02-seal.json` | 4149 | `7874bd0c8e9b47973b7cae5cac44da394a6ad1113a98c80ce89d886bae729169` | Sealed E3 score replay artifact. |
| `experiments/fas-frozen-observer-bundle-engineering-v01/audits/e3-score-v02-independent-audit.json` | 1452 | `d7d384b1b5294e99bc3219c4c349f3e33beaf0f5fd246a5bef04b5ac0f95e227` | Independent E3 score replay audit. |
| `D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e1-panel-v04\e1-seal-v01.json` | 2500 | `973b53e93e2c56b0cc1054fd545a558dcce4de07068c9729bcd4fa4f1fc86168` | Sealed E1 v04 population root and member inventory. |
| `D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e2-v07\e2-v07-seal.json` | 4793 | `30981abe10b4e97ab4f39eb006f5fc24aaaa799f5381be13170dca49c3ddb7f7` | Sealed E2 v07 representation cache root. |
| `D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e2-v07\e2-v07-independent-audit-v01.json` | 1633 | `35a8a34f458ea8e35142778b72ca5a389fb1d8ea5efb4c534553d2126eb4e299` | Independent E2 v07 audit. |
| `D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e3-v02\e3-v02-seal.json` | 19475 | `b8dce8dc7ff2d1a1739619f1ed00444d970ccc46872bb1acca2f1e07bf31a485` | Sealed E3 v02 observer bundle root and head inventory. |
| `D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e3-v02\e3-v02-independent-audit-v01.json` | 12497 | `a0950baf5aa64f77b9789a6fcb64a7c3afd2c3c03dea87d66c76a47049ab6cbe` | Independent E3 v02 bundle audit. |

## Bound source and build closure

All source, frozen-input, and receipt table paths are relative to the workspace root; only external predecessor diagnostics use absolute paths. The source table includes runtime code, local dependencies, manifests/lockfiles, schemas, tests, and contract processing/audit utilities. Python bytecode and caches are excluded.

| Path | Bytes | SHA-256 | Role |
| --- | ---: | --- | --- |
| `experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-b-v02/attempt-note-v01.json` | 1999 | `90342d5884adaec5506586e0ac7b8cdd61cc015de82c95f6da9ccc878cd2ecc5` | Preserved Track B v02 failed-import attempt and repair provenance |
| `experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/audit_e4_0_track_e_seal_v06.py` | 12515 | `397e999448aa5aac1252c8bb746301577d737653cd2e562523c0babf6a6d9647` | Independent Track E v06 seal-root/member auditor |
| `experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/audit_e4_0_track_e_v06.py` | 45759 | `86049aa4041922972690f4c7edc95411d095cab1266a04e95b493416f0c327f9` | Independent Track E v06 contract/source auditor |
| `experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/fixtures/sealed-v05-source-map-v04.md` | 20808 | `cd460160797c91e3655a06cf6bda9d2598fbb46c6564c729c4eaa1f6d5a9a4f9` | Exact immutable v05 map fixture for semantic-role parser regression |
| `experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/history/build_e4_0_source_map_v05-zero-byte-attempt-v01.json` | 748 | `dbedbb2d84ba11588a86fc9300a0d12b7540fdba425bcfeea4d50381f2ac7a47` | Receipt for preserved empty failed builder-write attempt |
| `experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/history/build_e4_0_source_map_v05-zero-byte-attempt-v01.py` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | Preserved empty failed builder-write attempt; history only |
| `experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/test_audit_e4_0_track_e_v06.py` | 7083 | `721fe632f2940dc1edd42f345565343de3602f9b150849b2cec4fa036a2cf141` | Independent Track E v06 source auditor tests |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/e4-population-v02/Cargo.lock` | 19005 | `ebe38c4657bf638886f81916734b31506ea535dd4840d36dba9d1974b208a9ca` | Track A v06 population generator / Rust build closure |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/e4-population-v02/Cargo.toml` | 500 | `faa0515d9a4308bd3e128c49131fdc3a95eb795e385518b2c47ae26f647e436c` | Track A v06 population generator / Rust build closure |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/e4-population-v02/benches/population_hot_path.rs` | 2522 | `c87bb976feea504935d8f3042f577d74f5809314294507f2881a8c192835deda` | Track A v06 population generator / Rust build closure |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/e4-population-v02/src/bin/e4-population-v02.rs` | 16107 | `ffa41e08ca9f5d06fe7eb9d414d470e208d864e679bce688b4b84c4d4c319ea7` | Track A v06 population generator / Rust build closure |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/e4-population-v02/src/identity.rs` | 14033 | `58e5c95ad5d00daeafc810b70d28aefa605f0320b2d7144651e85b5a598f3b5d` | Track A v06 population generator / Rust build closure |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/e4-population-v02/src/lib.rs` | 3760 | `8de3e3ddf932011d83ca3131310fb97607e0bb00535e395b36c6712407ce014c` | Track A v06 population generator / Rust build closure |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/e4-population-v02/src/population.rs` | 30119 | `674a610a29d5903ec34562d537fd45b573237d96b7a5450978545fc46d4363cf` | Track A v06 population generator / Rust build closure |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/e4-population-v02/src/render.rs` | 9345 | `4bfe046c905b19733f809bc59434db781245f5c7412d77723d5bc13358f6f984` | Track A v06 population generator / Rust build closure |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/e4-population-v02/src/schema.rs` | 4529 | `bc31c30b5f0bf512edcce7c306fd03fb1511cfe0c570cab03208b0707fdabef9` | Track A v06 population generator / Rust build closure |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/e4-population-v02/src/support.rs` | 5793 | `8cbb8b4c2b61238481dfbe0815eb35930c67d1bce1cb8b000358079a33992a88` | Track A v06 population generator / Rust build closure |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/e4-population-v02/src/writer.rs` | 12143 | `b9d70061432319991138f19585c2115555deabfbb372963edc56cd9c22a52997` | Track A v06 population generator / Rust build closure |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/e4-support-plan-v11/Cargo.lock` | 6002 | `8a84004756324303676bae7acc1bd041d54530a93e9e85b074d65b162e9e3a8c` | Model-free symbolic support planner |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/e4-support-plan-v11/Cargo.toml` | 324 | `5634d636df04da59a64d5e1ed890641ebc3823ec9971b94673ffd123f3591379` | Model-free symbolic support planner |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/e4-support-plan-v11/src/main.rs` | 33181 | `d3cc9b9c36bbcde3bfdaac07f571e53a88374c26d076fb808b273bae4d3155ae` | Model-free symbolic support planner |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/panel-generator-v04/Cargo.lock` | 6015 | `4ed5fca0a39c8869c082daf94cb0afd183533714a8253e44acf8d610129e17d7` | Frozen local E1 schedule dependency |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/panel-generator-v04/Cargo.toml` | 321 | `c7448c046ceb9722a96ef3318bbc0b55e459ecdf06f6ea1c87634b10a27d022a` | Frozen local E1 schedule dependency |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/panel-generator-v04/src/generate.rs` | 25895 | `fa2bd0617135a0dce4e12f0e0967f82e461133b394a7d969daba5afb11e2cce1` | Frozen local E1 schedule dependency |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/panel-generator-v04/src/lib.rs` | 33 | `e57ddf18054a9c7d049d849d28654bbf85419e13993bc917906cfef3d4669cc7` | Frozen local E1 schedule dependency |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/panel-generator-v04/src/main.rs` | 31954 | `7ce62779ddf8dd994ad9ace6a10dd5bda76de3bd87c1c0e19459cf38b428ec0f` | Frozen local E1 schedule dependency |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/panel-generator-v04/src/model.rs` | 3680 | `94cca0249f5508be13e186921bc2441a830fa4af695211cd7fb08126a79c11e2` | Frozen local E1 schedule dependency |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_fresh_scorer_v02/README.md` | 8585 | `5a24f8ae2339cd972a3963c1ef3a81badf99270c4b451188e74ce025eb303b57` | Track C v06 scorer / synthetic tests |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_fresh_scorer_v02/output_artifacts.py` | 5887 | `73fbdd184d01df6de913676a0caa0be8f38f264bc9667e3985b52485425b33d4` | Track C v06 scorer / synthetic tests |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_fresh_scorer_v02/runner.py` | 44491 | `49c21eaee43b2e9d4d1f67b32ba299c0ed238fdc8783a020554517a745ed4e41` | Track C v06 scorer / synthetic tests |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_fresh_scorer_v02/scorer.py` | 33616 | `58bc957de63d430933570430ee0760a5833bc9c6ef5a82dae6dba78115b8b866` | Track C v06 scorer / synthetic tests |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_fresh_scorer_v02/test_runner.py` | 27529 | `51366268036367a3443925ad200e2035792c43a73a8ba1182ecc232b6c1dce89` | Track C v06 scorer / synthetic tests |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_fresh_scorer_v02/test_scorer.py` | 11470 | `49918704b151c9055432f4fb6199e3621a619b21acfb85d2a0427883283132c6` | Track C v06 scorer / synthetic tests |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_independent_audit_v02/README.md` | 1305 | `95e71f621cd3ce2bfda319d32c27e8aed249d59cfa01ea884f2ea837be2d3ca4` | Track D independent population/parity/scoring replay auditor |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_independent_audit_v02/__init__.py` | 71 | `c5c6939552ed8fc92be9b0dd26f6732123dcccc44ef316eb3ab685f8bf291f12` | Track D independent population/parity/scoring replay auditor |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_independent_audit_v02/__main__.py` | 48 | `935a1c1166b0c1ea35a82256345000bf2c73ded718d77773bc27a71ecce28f7d` | Track D independent population/parity/scoring replay auditor |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_independent_audit_v02/cli.py` | 23715 | `13ef86c35c6b853b0a889823fe7e2210c2114f4edfd9a4bf032ca89a19065b9a` | Track D independent population/parity/scoring replay auditor |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_independent_audit_v02/constants.py` | 3849 | `32b4ff47c2ffcc4d7f34df5f152ab902e9cb0c17c70a2af6e21ba1f02ae0d9b4` | Track D independent population/parity/scoring replay auditor |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_independent_audit_v02/features.py` | 12661 | `eb5d2ba1d94e932502db9b595f53e3e61da28ef8679ea8b95403e79fa909a4f0` | Track D independent population/parity/scoring replay auditor |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_independent_audit_v02/integrity.py` | 22115 | `3c2f9f4e5eb6b9deada4eb367003ea477ab5dae0aff70214ca20734306676fbe` | Track D independent population/parity/scoring replay auditor |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_independent_audit_v02/population.py` | 16377 | `455ccef43a2889610134442ffe5edcd2a460a32fd3b21201574093a9118f62cb` | Track D independent population/parity/scoring replay auditor |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_independent_audit_v02/replay.py` | 24720 | `64c72105ce71c775395a8406366c7f1e8837d1c8da1b253f78b880c2122c1848` | Track D independent population/parity/scoring replay auditor |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_independent_audit_v02/tests/test_audit.py` | 30122 | `aca08a95b71cbca4a72f4e10b47ceeda0a90a0d7c9121f08150b3ca5c2e5a6c0` | Track D independent population/parity/scoring replay auditor |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/audit_e4_0_contract_draft_v05.py` | 10706 | `08c57c91d5d3f3df6770098cac56dbdbfbde035859446801397eae5803919e2a` | Historical v05 draft auditor |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/build_e4_0_contract_draft_v05.py` | 7896 | `e980635bf79e7d33f07bf9cf35397101909247ec9c18cee3b2a183235da88eea` | Historical v05 draft builder |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/build_e4_0_source_map_v04.py` | 13638 | `532af82be19ca3bac28fd37d64ee57ebefe24d37e2a4ef26d113f006a177ae4b` | Preserved v04 source map builder |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/build_e4_0_source_map_v05.py` | 16381 | `8640e7cb869a261f545ebc6ea78298e45901f6dd86c1121994ac314999033c0b` | v05 source map builder |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_gpu_lease_v01.py` | 23022 | `e95a6e40f4e9128d8c15cc758e91254e51936cb6b1e8942bbd1e76f635d82c21` | Track B process lease and resource telemetry |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_online_parity_v02.py` | 1375 | `02a26b5f3b2b2327a2e21bdaadec5e250ecf9ba0381a6b7707882ab9302ecb16` | Track B v06 parity/feature runner entrypoint |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_runner_artifacts_v02.py` | 15794 | `9976bb9ece709631ab33dcecaf3caa59b99268fdd39d413ad38b28a8d959a4a3` | Track B v06 artifact custody and seals |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_runner_common_v02.py` | 20575 | `83d5a0a1dad9b9d56773bca7d38ae8ff98ada0e8ff46101c282e233ea1094899` | Track B v06 auth, identity, and parity selection |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_runner_modes_v02.py` | 32754 | `654974ee5c32c6482e868d9885ba9d92e4928ef25bc0713400cece253390f5af` | Track B v06 panel, parity, and feature modes |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/finalize_e4_0_contract_v05.py` | 8851 | `cde570cf362265aae3055120447d6840bbe5658952413b8f727240b750276a9c` | Preserved v05 contract metadata binder |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/finalize_e4_0_contract_v06.py` | 10360 | `384d1c9d5b8d5340b7b04406cf03a1c7c2a199aeab799103705733508bec8876` | v06 contract metadata binder |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/issue_e4_stage_authorization_v02.py` | 20639 | `be597668d7a637d94a138dfccfc061066d484000818f69ee679a419f5c5c419c` | Normative v06 stage authorization issuer |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/seal_e4_0_contract_v05.py` | 8620 | `e6eb28a5c1a5a116650ed2e01c615c46f9d94fc9b3f868d3746bb9a157ab7c25` | Preserved v05 contract seal builder |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/seal_e4_0_contract_v06.py` | 9883 | `8695b6091df5a1135d0468c52b524e6cd6a9c9602b8e4318f9456b0cc576f51e` | v06 contract seal builder |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/tests/test_e4_runner_v02.py` | 16787 | `4af0fcab1f33aa13d6d586c7cfe440675ec6c0e61b4ecb7b055759c30fc3edd6` | Track B v06 synthetic source tests |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/tests/test_e4_stage_authorization_v02.py` | 14259 | `1ce5e19eb106b42f48828307c991cfb7298e64292a3c1a0b85a4c5c12b37c154` | v06 stage authorization issuer synthetic tests |

## Track receipts

- Versioned predecessor receipts are retained as history rows; v02 runtime sources, D/E independent auditors, and their current receipts define the v06 implementation closure.

| Track | Path | Bytes | SHA-256 | Status |
| --- | --- | ---: | --- | --- |
| Track A v03 | `experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-a/track-a-receipt-v03.json` | 4915 | `1d992466421569ed1318ed9132c02902eefa9cc3341df150c857a26c69f6d51e` | `TRACK_A_COMPLETE_PREAUTHORIZATION` |
| Track A history v02 | `experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-a/track-a-receipt-v02.json` | 6821 | `54e143b1657d5f99a8f730604e4095bc0ece2521492124e6bb5effc52da92dcb` | `TRACK_A_COMPLETE_PREAUTHORIZATION` |
| Track A history v01 | `experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-a/track-a-receipt-v01.json` | 5369 | `6ff04e3eefae26d419560d30158fb863545f5d348478fdd59cc3013daba867d7` | `TRACK_A_COMPLETE_PREAUTHORIZATION` |
| Track B v02 | `experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-b-v02/track-b-source-tests-v01.json` | 2800 | `a1e691405e3aea33845aacdf14dbe24617569b64f1a9450c63378d80d304dbbf` | `PASS_SYNTHETIC_SOURCE_AND_CLI_TESTS` |
| Track B history v01 | `experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-b/track-b-source-tests-v01.json` | 7170 | `acba272c3eb177e8e15b178343a7fcc87ecc43e0bfb6bc665dda9ddf25e400a3` | `PASS_SYNTHETIC_SOURCE_AND_CLI_TESTS` |
| Track C v02 | `experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-c-v02/track-c-source-tests-v01.json` | 6584 | `04514426de6e72ea0dcc63f2b5f1e72f37620da11ec01f297da1196fa11614a1` | `PASS_SYNTHETIC_SOURCE_AND_CLI_TESTS` |
| Track C history v01 | `experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-c/track-c-source-tests-v02.json` | 4768 | `e8ada9ff5288baa87c4aefc07a5acb2a31e1227862c36876004da958d5ce571b` | `PASS_SYNTHETIC_SOURCE_AND_CLI_TESTS` |
| Track D v02 | `experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-d/track-d-receipt-v06.json` | 5510 | `d53cf6bf67700746875fb1ead3572006bc36a12163156689b9c8287dfa3bfc0a` | `TRACK_D_COMPLETE_PREAUTHORIZATION` |
| Track D history v05 | `experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-d/track-d-receipt-v05.json` | 5241 | `dfadc86ce0ec5d8e70c512b6980b4e66753659461ac7e555b6df006a0878d23b` | `TRACK_D_COMPLETE_PREAUTHORIZATION` |
| Track E v06 | `experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/track-e-source-tests-v08.json` | 2081 | `7550268d61495c1a4bd211109d849c33490dafed36516b6cc4475a332f38df4a` | `TRACK_E_SOURCE_TESTS_PASS_PREMAP_UNIT_TESTS` |
| Auth issuer v02 | `experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-auth-issuer-v02/source-tests-v01.json` | 1565 | `22c4d3137e9adb05f3312be638c02517f39f816bf50bb9711d8498c54c7291ff` | `PASS_SYNTHETIC_TESTS` |
| Auth issuer history v01 | `experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-auth-issuer-source-tests-v01.json` | 1334 | `0b5d809100319ae8674e60732f76e606fa6d787335fcbf72bad84ca58866b9dc` | `PASS_SYNTHETIC_TESTS` |

## Runtime identity

- Python 3.13.15; NumPy 2.5.3; PyTorch 2.11.0+cu128; CUDA runtime/model/tokenizer identities are bound by the included representation ABI v07 and checked at the authorized online stage.
- Rust release profile and exact Cargo resolution are bound by the population and support-planner manifests/lockfiles; the local panel-generator-v04 crate is explicitly included.
- GPU resource claim is process-scoped PyTorch CUDA caching allocator reserved peak, at most 10 GiB; device-wide telemetry is diagnostic only. Host extractor process peak working set is at most 25 GiB.

## Source map builder identity

- The source-map builder's exact path, byte length, and SHA-256 are recorded once in the bound source/build closure table above.

## Execution boundary

Pre-seal validation uses only synthetic fixtures and frozen public inputs. It does not materialize fresh E4 rows, load a tokenizer/model, initialize CUDA, open E4 terminal labels, emit E4 predictions, or score. Runtime stages require separate stage-specific authorization receipts bound to the final contract seal and exact predecessor roots.

