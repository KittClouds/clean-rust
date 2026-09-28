# E4-0 Implementation Source Map v04

Status: final implementation closure for E4-0 v05. This map binds the exact frozen protocol inputs, source/build closure, source-test receipts, and independent auditor code. It does not itself grant execution authority.

## Immutable protocol baseline

- The immutable v05 draft identity and exact bytes are recorded once in the bound frozen-input table below.
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
| `experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/audit_e4_0_track_e.py` | 42870 | `e5068bd61211fe4a823baa85d3d3ec1609fa3887d45b2924672606d51cc2ccc7` | Independent Track E contract/source auditor |
| `experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/audit_e4_0_track_e_seal.py` | 10558 | `c7ffac775b97ed7ccfda21fcd74757379d8785d4699d9b9064766017cf7fd326` | Independent Track E seal-root and member auditor |
| `experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/test_audit_e4_0_track_e.py` | 5292 | `99f2301ae679df113d264fd5cd8ffeef53a55f96a6ac8006c8eb0b66bacc8a48` | Independent Track E contract/source auditor tests |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/e4-population-v01/Cargo.lock` | 19005 | `6f68318c480f45db9f3ac58d4d4f5c7dec79158e345902b3ce1b7c8742500d37` | Track A population generator / Rust build closure |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/e4-population-v01/Cargo.toml` | 500 | `dc824fec42b6c658c6cbd859f5170c68c083da62c9eec926d1165e515999116b` | Track A population generator / Rust build closure |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/e4-population-v01/benches/population_hot_path.rs` | 2522 | `97ec4da8c5df7c79395f79d1e9385b4871312cb7fcbd2d9d287c7df9d58f1eac` | Track A population generator / Rust build closure |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/e4-population-v01/src/bin/e4-population-v01.rs` | 16107 | `544ae86326472428228c350d7c73b0bfe0188fd302ec26f4f06c1608756deade` | Track A population generator / Rust build closure |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/e4-population-v01/src/identity.rs` | 14033 | `58e5c95ad5d00daeafc810b70d28aefa605f0320b2d7144651e85b5a598f3b5d` | Track A population generator / Rust build closure |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/e4-population-v01/src/lib.rs` | 3760 | `8de3e3ddf932011d83ca3131310fb97607e0bb00535e395b36c6712407ce014c` | Track A population generator / Rust build closure |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/e4-population-v01/src/population.rs` | 30119 | `674a610a29d5903ec34562d537fd45b573237d96b7a5450978545fc46d4363cf` | Track A population generator / Rust build closure |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/e4-population-v01/src/render.rs` | 9345 | `4bfe046c905b19733f809bc59434db781245f5c7412d77723d5bc13358f6f984` | Track A population generator / Rust build closure |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/e4-population-v01/src/schema.rs` | 4529 | `bc31c30b5f0bf512edcce7c306fd03fb1511cfe0c570cab03208b0707fdabef9` | Track A population generator / Rust build closure |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/e4-population-v01/src/support.rs` | 5793 | `8cbb8b4c2b61238481dfbe0815eb35930c67d1bce1cb8b000358079a33992a88` | Track A population generator / Rust build closure |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/e4-population-v01/src/writer.rs` | 12143 | `b9d70061432319991138f19585c2115555deabfbb372963edc56cd9c22a52997` | Track A population generator / Rust build closure |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/e4-support-plan-v11/Cargo.lock` | 6002 | `8a84004756324303676bae7acc1bd041d54530a93e9e85b074d65b162e9e3a8c` | Model-free symbolic support planner |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/e4-support-plan-v11/Cargo.toml` | 324 | `5634d636df04da59a64d5e1ed890641ebc3823ec9971b94673ffd123f3591379` | Model-free symbolic support planner |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/e4-support-plan-v11/src/main.rs` | 33181 | `d3cc9b9c36bbcde3bfdaac07f571e53a88374c26d076fb808b273bae4d3155ae` | Model-free symbolic support planner |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/panel-generator-v04/Cargo.lock` | 6015 | `4ed5fca0a39c8869c082daf94cb0afd183533714a8253e44acf8d610129e17d7` | Frozen local E1 schedule dependency |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/panel-generator-v04/Cargo.toml` | 321 | `c7448c046ceb9722a96ef3318bbc0b55e459ecdf06f6ea1c87634b10a27d022a` | Frozen local E1 schedule dependency |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/panel-generator-v04/src/generate.rs` | 25895 | `fa2bd0617135a0dce4e12f0e0967f82e461133b394a7d969daba5afb11e2cce1` | Frozen local E1 schedule dependency |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/panel-generator-v04/src/lib.rs` | 33 | `e57ddf18054a9c7d049d849d28654bbf85419e13993bc917906cfef3d4669cc7` | Frozen local E1 schedule dependency |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/panel-generator-v04/src/main.rs` | 31954 | `7ce62779ddf8dd994ad9ace6a10dd5bda76de3bd87c1c0e19459cf38b428ec0f` | Frozen local E1 schedule dependency |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/panel-generator-v04/src/model.rs` | 3680 | `94cca0249f5508be13e186921bc2441a830fa4af695211cd7fb08126a79c11e2` | Frozen local E1 schedule dependency |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_fresh_scorer_v01/README.md` | 8399 | `a77fb8f7a65ca1b3ab1706746643907aec9b53e061b8bea2eb6d5822b0265d1b` | Track C scorer / synthetic tests |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_fresh_scorer_v01/output_artifacts.py` | 5887 | `73fbdd184d01df6de913676a0caa0be8f38f264bc9667e3985b52485425b33d4` | Track C scorer / synthetic tests |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_fresh_scorer_v01/runner.py` | 41913 | `311b384bf337450112d4cb782e060c9ca900ca5f28b7aad55155f192577a99d5` | Track C scorer / synthetic tests |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_fresh_scorer_v01/scorer.py` | 33616 | `58bc957de63d430933570430ee0760a5833bc9c6ef5a82dae6dba78115b8b866` | Track C scorer / synthetic tests |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_fresh_scorer_v01/test_runner.py` | 25339 | `2dc421dc9e45e9d34b05823a9d85b87721c2c5b5a98d3d8fa7aeaeaa6fac16a0` | Track C scorer / synthetic tests |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_fresh_scorer_v01/test_scorer.py` | 11470 | `49918704b151c9055432f4fb6199e3621a619b21acfb85d2a0427883283132c6` | Track C scorer / synthetic tests |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_independent_audit_v01/README.md` | 1305 | `22e53a1c05a299ad559218381c45d0251fe03f49854991d2d66d8a03d17c56ea` | Track D independent population/parity/scoring replay auditor |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_independent_audit_v01/__init__.py` | 71 | `c5c6939552ed8fc92be9b0dd26f6732123dcccc44ef316eb3ab685f8bf291f12` | Track D independent population/parity/scoring replay auditor |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_independent_audit_v01/__main__.py` | 48 | `935a1c1166b0c1ea35a82256345000bf2c73ded718d77773bc27a71ecce28f7d` | Track D independent population/parity/scoring replay auditor |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_independent_audit_v01/cli.py` | 23715 | `7da687bf0ce195748d4f5f44547d26a975cacac838d9f8fdf1c3632844d382ec` | Track D independent population/parity/scoring replay auditor |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_independent_audit_v01/constants.py` | 2884 | `3456f9367f908fc3d6a6664bfa5047c969f18bcc8945733ace27f6ba3a2d0253` | Track D independent population/parity/scoring replay auditor |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_independent_audit_v01/features.py` | 12661 | `eb5d2ba1d94e932502db9b595f53e3e61da28ef8679ea8b95403e79fa909a4f0` | Track D independent population/parity/scoring replay auditor |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_independent_audit_v01/integrity.py` | 16233 | `d2ea4eba7cb61a40b6115428578e20fe244decc77c892748974f8facf94fc904` | Track D independent population/parity/scoring replay auditor |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_independent_audit_v01/population.py` | 16377 | `455ccef43a2889610134442ffe5edcd2a460a32fd3b21201574093a9118f62cb` | Track D independent population/parity/scoring replay auditor |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_independent_audit_v01/replay.py` | 24720 | `64c72105ce71c775395a8406366c7f1e8837d1c8da1b253f78b880c2122c1848` | Track D independent population/parity/scoring replay auditor |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_independent_audit_v01/tests/test_audit.py` | 23898 | `c0694dc95646cd1a179ab1d6654886d33c3c9aa8a79ce48f6fe3bd8d2270f876` | Track D independent population/parity/scoring replay auditor |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/audit_e4_0_contract_draft_v05.py` | 10706 | `08c57c91d5d3f3df6770098cac56dbdbfbde035859446801397eae5803919e2a` | Historical v05 draft auditor |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/build_e4_0_contract_draft_v05.py` | 7896 | `e980635bf79e7d33f07bf9cf35397101909247ec9c18cee3b2a183235da88eea` | Historical v05 draft builder |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/build_e4_0_source_map_v04.py` | 13638 | `532af82be19ca3bac28fd37d64ee57ebefe24d37e2a4ef26d113f006a177ae4b` | Final source map builder |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_gpu_lease_v01.py` | 23022 | `e95a6e40f4e9128d8c15cc758e91254e51936cb6b1e8942bbd1e76f635d82c21` | Track B process lease and resource telemetry |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_online_parity_v01.py` | 1375 | `febe1ef46f0e6529069a07c3a6a4bb4f372c5c3fab611afef4374770fa08a907` | Track B parity/feature runner entrypoint |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_runner_artifacts_v01.py` | 15794 | `d5b3fa29563877f34554d79b3a76524f488c6c7d4daaf3e4026d70b46e39a6c1` | Track B artifact custody and seals |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_runner_common_v01.py` | 20575 | `ca4ca4941323568e8a5cff651bb8cfcbf6ac9c74098b60608b54cc762108eb75` | Track B auth, identity, and parity selection |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/e4_runner_modes_v01.py` | 32467 | `95c87f22d9278afe1035d9d0b4ef6e2b2abd12f20810c80872b0b2cf2acd099a` | Track B panel, parity, and feature modes |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/finalize_e4_0_contract_v05.py` | 8851 | `cde570cf362265aae3055120447d6840bbe5658952413b8f727240b750276a9c` | Final v05 contract metadata binder |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/issue_e4_stage_authorization_v01.py` | 20639 | `fce139b12fc0885f2b7082019cecec7628654398858456900b7fc5bdeab7e2b9` | Normative stage authorization issuer |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/seal_e4_0_contract_v05.py` | 8620 | `e6eb28a5c1a5a116650ed2e01c615c46f9d94fc9b3f868d3746bb9a157ab7c25` | Generic final contract seal builder |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/tests/test_e4_runner_v01.py` | 16796 | `1b04c6d979acdc998fd09e6daf8e9dad9dd9122276c2f018d0cb1d34ab40bb15` | Track B synthetic source tests |
| `experiments/fas-frozen-observer-bundle-engineering-v01/source/tests/test_e4_stage_authorization_v01.py` | 14259 | `4d4a9e89cd45b58262be09b6d5777dbcb6af823e29bc6516030a2454c4b179b1` | Stage authorization issuer synthetic tests |

## Track receipts

- The former aggregate source integration receipt v01 is retained as superseded; current Track A/B/C/D/E and authorization-issuer receipts are bound individually.

| Track | Path | Bytes | SHA-256 | Status |
| --- | --- | ---: | --- | --- |
| Track A | `experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-a/track-a-receipt-v02.json` | 6821 | `54e143b1657d5f99a8f730604e4095bc0ece2521492124e6bb5effc52da92dcb` | `TRACK_A_COMPLETE_PREAUTHORIZATION` |
| Track B | `experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-b/track-b-source-tests-v01.json` | 7170 | `acba272c3eb177e8e15b178343a7fcc87ecc43e0bfb6bc665dda9ddf25e400a3` | `PASS_SYNTHETIC_SOURCE_AND_CLI_TESTS` |
| Track C | `experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-c/track-c-source-tests-v02.json` | 4768 | `e8ada9ff5288baa87c4aefc07a5acb2a31e1227862c36876004da958d5ce571b` | `PASS_SYNTHETIC_SOURCE_AND_CLI_TESTS` |
| Track D | `experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-d/track-d-receipt-v04.json` | 4828 | `41d35cc3003faa62ddd9fca33675800a33725ffe1410e565647efea54fb20720` | `TRACK_D_COMPLETE_PREAUTHORIZATION` |
| Track E | `experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/track-e-source-tests-v06.json` | 2671 | `05d7d621b0d7115dbe86ad9852e269adead5d59b1a0a2f874afb466d1fe883d9` | `TRACK_E_SOURCE_TESTS_PASS_PREMAP_UNIT_TESTS` |
| Auth issuer | `experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-auth-issuer-source-tests-v01.json` | 1334 | `0b5d809100319ae8674e60732f76e606fa6d787335fcbf72bad84ca58866b9dc` | `PASS_SYNTHETIC_TESTS` |

## Runtime identity

- Python 3.13.15; NumPy 2.5.3; PyTorch 2.11.0+cu128; CUDA runtime/model/tokenizer identities are bound by the included representation ABI v07 and checked at the authorized online stage.
- Rust release profile and exact Cargo resolution are bound by the population and support-planner manifests/lockfiles; the local panel-generator-v04 crate is explicitly included.
- GPU resource claim is process-scoped PyTorch CUDA caching allocator reserved peak, at most 10 GiB; device-wide telemetry is diagnostic only. Host extractor process peak working set is at most 25 GiB.

## Source map builder identity

- The source-map builder's exact path, byte length, and SHA-256 are recorded once in the bound source/build closure table above.

## Execution boundary

Pre-seal validation uses only synthetic fixtures and frozen public inputs. It does not materialize fresh E4 rows, load a tokenizer/model, initialize CUDA, open E4 terminal labels, emit E4 predictions, or score. Runtime stages require separate stage-specific authorization receipts bound to the final contract seal and exact predecessor roots.
